"""People's personal data for data subject requests: the employee's profile, ids, payment details, time and leave, pay.

Plugged into the kernel's "kernel.personal_data" socket (docs/privacy.md). Payroll and employment records are the kind
a business is normally required to keep for a period. The period is the company setting
`retention_employee_records_years` (the business's own decision, 0 for no minimum), counted from the end of employment
or the last payslip, whichever is later:

- still employed: an erasure is refused;
- employment ended, inside the period: only what payroll does not need is removed (phone, email, leave reasons and
  notes) and the rest is kept, with the reason and the date it can be erased;
- employment ended, after the period: the identifying fields are replaced. Payslips keep their amounts and numbers.
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import (
    PLACEHOLDER,
    Kept,
    Outcome,
    PersonalDataProvider,
    PersonalRecord,
    RetentionRule,
    Session,
    Subject,
    company_setting,
    decrypt_text,
    json_one,
    json_rows,
    like_pattern,
    provides,
    sql_digits,
    sql_identifier,
)

STRIP = "- 'tenant_id' - 'created_by' - 'updated_by'"
PAYROLL_STATUSES = ("approved", "posted", "paid")


def _clean(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isalnum()).upper()


def _national_id(ciphertext: Any) -> str | None:
    return decrypt_text(bytes(ciphertext).decode()) if ciphertext is not None else None


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:                                         # 29 February
        return day.replace(year=day.year + years, day=28)


@provides("kernel.personal_data")
class PeoplePersonalData(PersonalDataProvider):
    name = "people"

    # ------------------------------------------------------------------ find
    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[UUID, PersonalRecord] = {}

        def add(rows: Any, match: str) -> None:
            for row in rows:
                if row.full_name.startswith(PLACEHOLDER):
                    continue
                previous = found.get(row.id)
                if previous is None or (previous.match == "possible" and match == "exact"):
                    found[row.id] = PersonalRecord("people", "employee", row.id,
                                                   f"{row.full_name} ({row.employee_no})", match, company_id)

        base = "select id, full_name, employee_no from people.employee where company_id = :c and "
        if subject.email:
            add(session.execute(text(base + "lower(email) = :e"), {"c": str(company_id), "e": subject.email}), "exact")
        digits = subject.phone or (subject.identifier if subject.identifier and subject.identifier.isdigit() else None)
        if digits:
            add(session.execute(text(base + f"phone is not null and {sql_digits('phone')} = :p"),
                                {"c": str(company_id), "p": digits}), "exact")
        if subject.identifier:
            add(session.execute(text(base + f"tax_id is not null and {sql_identifier('tax_id')} = :i"),
                                {"c": str(company_id), "i": subject.identifier}), "exact")
            # National ids and registration numbers are stored encrypted or inside a document: compare them here.
            wanted = _clean(subject.identifier)
            rows = session.execute(text(
                "select id, full_name, employee_no, national_id_ciphertext, registrations from people.employee "
                "where company_id = :c and (national_id_ciphertext is not null or registrations <> '{}'::jsonb)"),
                {"c": str(company_id)}).all()
            add([r for r in rows if _clean(_national_id(r.national_id_ciphertext)) == wanted
                 or wanted in {_clean(str(v)) for v in (r.registrations or {}).values()}], "exact")
        if subject.name:
            add(session.execute(text(base + "full_name ilike :n"),
                                {"c": str(company_id), "n": like_pattern(subject.name)}), "possible")
        return list(found.values())

    # ------------------------------------------------------------------ export
    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = str(record.record_id)
        profile = json_one(session, f"select to_jsonb(e) {STRIP} - 'national_id_ciphertext' from people.employee e "
                                    "where id = :i", i=i)
        ciphertext = session.execute(text("select national_id_ciphertext from people.employee where id = :i"),
                                     {"i": i}).scalar_one_or_none()
        if profile is not None:
            profile["national_id"] = _national_id(ciphertext)
        return {
            "profile": profile,
            "payment_details": json_rows(
                session, f"select to_jsonb(b) {STRIP} - 'employee_id' - 'account_no_ciphertext' "
                         "from people.employee_bank_account b where employee_id = :i order by valid_from", i=i),
            "employment_terms": json_rows(session, f"select to_jsonb(t) {STRIP} - 'employee_id' "
                                                   "from people.employment_terms t where employee_id = :i "
                                                   "order by valid_from", i=i),
            "pay_items": json_rows(session, f"select to_jsonb(p) {STRIP} - 'employee_id' from "
                                            "people.employee_pay_item p where employee_id = :i", i=i),
            "attendance": json_rows(session, f"select to_jsonb(a) {STRIP} - 'employee_id' from people.attendance a "
                                             "where employee_id = :i order by work_date", i=i),
            "leave": json_rows(session, f"select to_jsonb(l) {STRIP} - 'employee_id' from people.leave_request l "
                                        "where employee_id = :i order by start_date", i=i),
            "payslips": json_rows(
                session, "select jsonb_build_object('period_start', r.period_start, 'period_end', r.period_end, "
                         "'pay_date', r.pay_date, 'run_status', r.status, 'gross_pay', s.gross_pay, "
                         "'taxable_pay', s.taxable_pay, 'total_deductions', s.total_deductions, 'net_pay', s.net_pay, "
                         "'benefits', s.benefits, 'status', s.status, 'pay_method', s.pay_method) "
                         "from people.payslip s join people.payroll_run r on r.id = s.run_id "
                         "where s.employee_id = :i order by r.period_start", i=i),
        }

    # ------------------------------------------------------------------ anonymise
    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = str(record.record_id)
        e = session.execute(text(
            "select id, company_id, employee_no, termination_date, status from people.employee "
            "where id = :i for update"), {"i": i}).first()
        if e is None:
            return Outcome("refused", message="The employee no longer exists")
        if e.termination_date is None or e.status in ("active", "on_leave"):
            return Outcome("refused", message="This person is still employed. The business needs their details "
                                              "to employ and pay them. Record the end of employment first, then erase")
        years = int(company_setting(session, e.company_id, "retention_employee_records_years"))
        last_pay = session.execute(text(
            "select max(r.period_end) from people.payslip s join people.payroll_run r on r.id = s.run_id "
            "where s.employee_id = :i and r.status = any(:st)"), {"i": i, "st": list(PAYROLL_STATUSES)}).scalar_one()
        latest = max([d for d in (e.termination_date, last_pay) if d is not None])
        keep_until = _add_years(latest, years)
        notes = self._clear_notes(session, i)
        if years > 0 and date.today() < keep_until:
            session.execute(text("update people.employee set phone = null, email = null, updated_at = now() "
                                 "where id = :i"), {"i": i})
            why = (f"payroll and employment records must be kept until {keep_until.isoformat()} "
                   f"({years} years after {latest.isoformat()}; company setting retention_employee_records_years)")
            return Outcome(
                "partial", changed=["phone removed", "email removed", f"{notes} leave reason(s) and note(s) removed"],
                kept=[Kept("name, employee number, tax number and registration numbers, national id", why),
                      Kept("payment details (bank or mobile money)", why),
                      Kept("payslips, pay items, employment terms and attendance", why)],
                message=f"The rest can be erased on {keep_until.isoformat()}: raise a new request then")
        session.execute(text(
            "update people.employee set full_name = :n, national_id_ciphertext = null, tax_id = null, phone = null, "
            "email = null, registrations = '{}'::jsonb, updated_at = now() where id = :i"),
            {"n": f"{PLACEHOLDER} employee {e.employee_no}", "i": i})
        accounts = session.execute(text(
            "update people.employee_bank_account set bank_name = null, account_no_ciphertext = null, "
            "account_no_masked = null, updated_at = now() where employee_id = :i"), {"i": i}).rowcount  # type: ignore[attr-defined]
        return Outcome(
            "anonymised",
            changed=["name replaced", "national id, tax number and registration numbers removed",
                     "phone and email removed", f"{accounts} payment detail record(s) emptied",
                     f"{notes} leave reason(s) and note(s) removed"],
            kept=[Kept("employee number, hire and end dates, status",
                       "needed to read the payslips and attendance that remain"),
                  Kept("payslips, pay amounts, deductions and the payroll runs and ledger entries made from them",
                       "accounting and payroll records; they name the employee by number only")])

    @staticmethod
    def _clear_notes(session: Session, employee_id: str) -> int:
        leave = session.execute(text(
            "update people.leave_request set reason = null, decided_note = null, updated_at = now() "
            "where employee_id = :i and (reason is not null or decided_note is not null)"),
            {"i": employee_id}).rowcount  # type: ignore[attr-defined]
        terms = session.execute(text(
            "update people.employment_terms set note = null, updated_at = now() "
            "where employee_id = :i and note is not null"), {"i": employee_id}).rowcount  # type: ignore[attr-defined]
        return int(leave) + int(terms)

    # ------------------------------------------------------------------ retention
    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        years = int(company_setting(session, company_id, "retention_employee_records_years"))
        return [RetentionRule(
            "people", "employees", "Employee profile, ids, payment details, attendance, leave and payslips",
            "Employment and payroll records the business must keep after employment ends",
            setting="retention_employee_records_years",
            period=f"{years} years after employment ended or the last payslip" if years else "no minimum set",
            at_end="review")]

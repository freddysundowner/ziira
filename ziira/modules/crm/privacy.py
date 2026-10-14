"""CRM's personal data for data subject requests: customers, their contacts, leads and the follow-up notes about them.

Plugged into the kernel's "kernel.personal_data" socket (see ziira/kernel/personal_data.py and docs/privacy.md).
Anonymising a customer keeps the customer record itself (its code, credit limit, terms and status), because posted
invoices, receipts and the ledger point at it; only the identifying fields change.
"""

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
    json_one,
    json_rows,
    like_pattern,
    provides,
    sql_digits,
    sql_identifier,
)

PLACEHOLDER_NOTE = "[removed]"
KEEP_FINANCIAL = Kept("customer code, credit limit, payment terms, status and every invoice, receipt and sale that "
                      "points at the customer",
                      "the business's financial records; they name the customer by code and amounts only")


@provides("kernel.personal_data")
class CrmPersonalData(PersonalDataProvider):
    name = "crm"

    # ------------------------------------------------------------------ find
    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[UUID, PersonalRecord] = {}
        specs = (("customer", "crm.customer", "company_id = :c"),
                 ("lead", "crm.lead", "company_id = :c"),
                 ("contact", "crm.customer_contact",
                  "customer_id in (select id from crm.customer where company_id = :c)"))
        name_col = "name"
        for kind, table, scope in specs:
            conditions: list[tuple[str, dict[str, Any], str]] = []
            if subject.email:
                conditions.append(("lower(email) = :e", {"e": subject.email}, "exact"))
            if subject.phone or (subject.identifier and subject.identifier.isdigit()):
                digits = subject.phone or str(subject.identifier)
                conditions.append((f"phone is not null and {sql_digits('phone')} = :p", {"p": digits}, "exact"))
            if subject.identifier and kind == "customer":
                conditions.append((f"tax_id is not null and {sql_identifier('tax_id')} = :i",
                                   {"i": subject.identifier}, "exact"))
            if subject.name:
                conditions.append((f"{name_col} ilike :n", {"n": like_pattern(subject.name)}, "possible"))
                if kind == "lead":
                    conditions.append(("business_name ilike :n", {"n": like_pattern(subject.name)}, "possible"))
            for condition, params, match in conditions:
                rows = session.execute(text(
                    f"select id, {name_col} as label from {table} where {scope} and ({condition})"),
                    {"c": str(company_id), **params})
                for row in rows:
                    if row.label.startswith(PLACEHOLDER):
                        continue
                    previous = found.get(row.id)
                    if previous is None or (previous.match == "possible" and match == "exact"):
                        found[row.id] = PersonalRecord("crm", kind, row.id, row.label, match, company_id)
        return list(found.values())

    # ------------------------------------------------------------------ export
    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = str(record.record_id)
        strip = "- 'tenant_id' - 'created_by' - 'updated_by' - 'owner_user_id'"
        if record.kind == "customer":
            data: dict[str, Any] = {
                "customer": json_one(session, f"select to_jsonb(c) {strip} from crm.customer c where id = :i", i=i),
                "contacts": json_rows(session, f"select to_jsonb(c) {strip} - 'customer_id' "
                                               "from crm.customer_contact c where customer_id = :i", i=i),
                "credit_history": json_rows(
                    session, "select jsonb_build_object('credit_limit', credit_limit, 'payment_terms_days', "
                             "payment_terms_days, 'valid_from', valid_from, 'status', status, 'reason', reason) "
                             "from crm.customer_credit_version where customer_id = :i order by valid_from", i=i),
            }
        elif record.kind == "lead":
            data = {"lead": json_one(session, f"select to_jsonb(l) {strip} from crm.lead l where id = :i", i=i)}
        else:
            data = {"contact": json_one(session, f"select to_jsonb(c) {strip} from crm.customer_contact c "
                                                 "where id = :i", i=i)}
        if record.kind in ("customer", "lead"):
            data["follow_ups"] = json_rows(
                session, f"select to_jsonb(a) {strip} - 'related_id' - 'related_type' from crm.activity a "
                         "where related_id = :i order by created_at", i=i)
        return data

    # ------------------------------------------------------------------ anonymise
    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = str(record.record_id)
        if record.kind == "customer":
            row = session.execute(text("select code from crm.customer where id = :i for update"), {"i": i}).first()
            if row is None:
                return Outcome("refused", message="The customer no longer exists")
            session.execute(text(
                "update crm.customer set name = :n, phone = null, email = null, tax_id = null, updated_at = now() "
                "where id = :i"), {"n": f"{PLACEHOLDER} customer {row.code}", "i": i})
            notes = self._clear_notes(session, i)
            return Outcome("anonymised", changed=["name replaced", "phone removed", "email removed",
                                                  "tax number removed", f"{notes} follow-up note(s) removed"],
                           kept=[KEEP_FINANCIAL])
        if record.kind == "lead":
            if session.execute(text("select 1 from crm.lead where id = :i for update"), {"i": i}).first() is None:
                return Outcome("refused", message="The lead no longer exists")
            session.execute(text(
                "update crm.lead set name = :n, business_name = null, phone = null, email = null, lost_reason = null, "
                "updated_at = now() where id = :i"), {"n": f"{PLACEHOLDER} lead", "i": i})
            notes = self._clear_notes(session, i)
            return Outcome("anonymised", changed=["name replaced", "business name, phone and email removed",
                                                  f"{notes} follow-up note(s) removed"],
                           kept=[Kept("the lead's status and source", "sales statistics, with no personal data")])
        if session.execute(text("select 1 from crm.customer_contact where id = :i for update"),
                           {"i": i}).first() is None:
            return Outcome("refused", message="The contact no longer exists")
        session.execute(text("update crm.customer_contact set name = :n, phone = null, email = null, role = null "
                             "where id = :i"), {"n": f"{PLACEHOLDER} contact", "i": i})
        return Outcome("anonymised", changed=["name replaced", "phone, email and role removed"],
                       kept=[Kept("the link to the customer", "the customer is a business record; the contact no "
                                                              "longer names anyone")])

    @staticmethod
    def _clear_notes(session: Session, related_id: str) -> int:
        result = session.execute(text(
            "update crm.activity set note = :n, updated_at = now() where related_id = :i and note is not null"),
            {"n": PLACEHOLDER_NOTE, "i": related_id})
        return int(result.rowcount)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ retention
    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        years = int(session.execute(text(
            "select coalesce((settings->>'retention_inactive_customers_years')::int, 0) from kernel.company "
            "where id = :c"), {"c": str(company_id)}).scalar_one())
        eligible = 0
        if years > 0:
            eligible = int(session.execute(text(
                "select count(*) from crm.customer where company_id = :c and status <> 'active' "
                "and name not like :p and coalesce(updated_at, created_at) < now() - make_interval(years => :y)"),
                {"c": str(company_id), "y": years, "p": f"{PLACEHOLDER}%"}).scalar_one())
        return [
            RetentionRule("crm", "customers", "Customer name, phone, email, tax number and contacts",
                          "Serving the customer and keeping the business's invoices and receipts understandable",
                          setting="retention_inactive_customers_years",
                          period=f"{years} years after the customer was last touched, if not active" if years
                          else "while the customer exists (no review period set)", at_end="review",
                          eligible=eligible),
            RetentionRule("crm", "leads", "Lead name, phone, email and follow-up notes",
                          "Following up an enquiry", period="until the lead is erased on request", at_end="review"),
        ]

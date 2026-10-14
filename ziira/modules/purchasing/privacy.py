"""Purchasing's personal data for data subject requests: suppliers who are individuals, their contacts and bank details.

Plugged into the kernel's "kernel.personal_data" socket (docs/privacy.md). A supplier record is kept (its code, status,
and every order, bill, payment and credit note that points at it); only the identifying fields are replaced. While the
business still owes the supplier money, the name and payment details are needed to pay them, so only the phone and
email are removed and the rest is kept with the reason.
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
    sql_identifier,
    sql_phone_matches,
)

STRIP = "- 'tenant_id' - 'created_by' - 'updated_by'"


@provides("kernel.personal_data")
class PurchasingPersonalData(PersonalDataProvider):
    name = "purchasing"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[UUID, PersonalRecord] = {}
        base = "select id, name, code from purchasing.supplier where company_id = :c and "
        params: dict[str, Any] = {"c": str(company_id)}
        queries: list[tuple[str, dict[str, Any], str]] = []
        if subject.email:
            queries.append(("lower(email) = :e", {"e": subject.email}, "exact"))
        digits = subject.phone or (subject.identifier if subject.identifier and subject.identifier.isdigit() else None)
        if digits:
            queries.append((sql_phone_matches("phone", "p"), {"p": digits}, "exact"))
        if subject.identifier:
            queries.append((f"tax_id is not null and {sql_identifier('tax_id')} = :i", {"i": subject.identifier},
                            "exact"))
        if subject.name:
            queries.append(("(name ilike :n or id in (select supplier_id from purchasing.supplier_bank_account "
                            "where account_name ilike :n))", {"n": like_pattern(subject.name)}, "possible"))
        for condition, extra, match in queries:
            for row in session.execute(text(base + condition), {**params, **extra}):
                if row.name.startswith(PLACEHOLDER):
                    continue
                previous = found.get(row.id)
                if previous is None or (previous.match == "possible" and match == "exact"):
                    found[row.id] = PersonalRecord("purchasing", "supplier", row.id, f"{row.name} ({row.code})",
                                                   match, company_id)
        return list(found.values())

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = str(record.record_id)
        return {
            "supplier": json_one(session, f"select to_jsonb(s) {STRIP} from purchasing.supplier s where id = :i", i=i),
            "payment_details": json_rows(
                session, f"select to_jsonb(b) {STRIP} - 'supplier_id' - 'account_no_ciphertext' "
                         "from purchasing.supplier_bank_account b where supplier_id = :i order by valid_from", i=i),
            "bills": json_rows(
                session, "select jsonb_build_object('number', number, 'supplier_invoice_no', supplier_invoice_no, "
                         "'bill_date', bill_date, 'due_date', due_date, 'total', total, 'amount_paid', amount_paid, "
                         "'status', status) from purchasing.supplier_bill where supplier_id = :i order by bill_date",
                i=i),
            "orders": json_rows(
                session, "select jsonb_build_object('number', number, 'order_date', order_date, 'total', total, "
                         "'status', status) from purchasing.purchase_order where supplier_id = :i "
                         "order by order_date", i=i),
        }

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = str(record.record_id)
        supplier = session.execute(text("select code from purchasing.supplier where id = :i for update"),
                                   {"i": i}).first()
        if supplier is None:
            return Outcome("refused", message="The supplier no longer exists")
        owed = session.execute(text(
            "select coalesce(sum(total - amount_paid - credited), 0) from purchasing.supplier_bill "
            "where supplier_id = :i and status in ('posted', 'part_paid')"), {"i": i}).scalar_one()
        if owed > 0:
            session.execute(text("update purchasing.supplier set phone = null, email = null, updated_at = now() "
                                 "where id = :i"), {"i": i})
            why = f"the business still owes this supplier {owed}; their name and payment details are needed to pay them"
            return Outcome("partial", changed=["phone removed", "email removed"],
                           kept=[Kept("name, tax number and bank or mobile money details", why)],
                           message="Pay or settle the bills, then raise a new request to erase the rest")
        session.execute(text(
            "update purchasing.supplier set name = :n, phone = null, email = null, tax_id = null, "
            "status = 'inactive', updated_at = now() where id = :i"),
            {"n": f"{PLACEHOLDER} supplier {supplier.code}", "i": i})
        accounts = int(session.execute(text(
            "update purchasing.supplier_bank_account set account_name = null, bank_name = null, "
            "account_no_ciphertext = null, account_no_masked = null, updated_at = now() where supplier_id = :i"),
            {"i": i}).rowcount)  # type: ignore[attr-defined]
        return Outcome(
            "anonymised",
            changed=["name replaced", "phone, email and tax number removed", f"{accounts} payment detail record(s) "
                     "emptied", "supplier set to inactive (no new orders or bills)"],
            kept=[Kept("supplier code and every order, bill, receipt, payment and credit note that points at it",
                       "the business's purchasing and financial records; they name the supplier by code and amounts")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("purchasing", "suppliers", "Supplier name, phone, email, tax number and bank details",
                              "Ordering from and paying suppliers, and the business's purchasing records",
                              period="while the supplier is used; erased on request unless money is still owed",
                              at_end="review")]

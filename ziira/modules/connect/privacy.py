"""Connectors' personal data for data subject requests: the customers, suppliers and users read from other systems.

Only parties and users carry identifying details (names, phone, email, tax number); the sales, payments and invoices
that point at them hold their source reference and, for a statement line, the payer's name as the statement showed it.
Anonymising replaces the identifying fields and marks the record `erased`, so a later read of the source does not bring
the details back. The source system still holds them: the business must correct it there too.
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
)

TABLES = {"party": "connect.src_party", "user": "connect.src_user"}


@provides("kernel.personal_data")
class ConnectPersonalData(PersonalDataProvider):
    name = "connect"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[UUID, PersonalRecord] = {}
        for kind, table in TABLES.items():
            conditions: list[tuple[str, dict[str, Any], str]] = []
            if subject.email:
                conditions.append(("lower(email) = :e", {"e": subject.email}, "exact"))
            if kind == "party":
                if subject.phone or (subject.identifier and subject.identifier.isdigit()):
                    digits = subject.phone or str(subject.identifier)
                    conditions.append((f"phone is not null and {sql_digits('phone')} = :p", {"p": digits}, "exact"))
                if subject.identifier:
                    conditions.append(("tax_id is not null and upper(regexp_replace(tax_id, '[\\s/-]', '', 'g')) = :i",
                                       {"i": subject.identifier}, "exact"))
            if subject.name:
                conditions.append(("name ilike :n", {"n": like_pattern(subject.name)}, "possible"))
            for condition, params, match in conditions:
                for row in session.execute(text(
                        f"select id, name as label from {table} where company_id = :c and not erased and "
                        f"({condition})"),
                        {"c": str(company_id), **params}):
                    previous = found.get(row.id)
                    if previous is None or (previous.match == "possible" and match == "exact"):
                        found[row.id] = PersonalRecord("connect", kind, row.id, row.label, match, company_id)
        return list(found.values())

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = str(record.record_id)
        strip = "- 'tenant_id' - 'content_hash' - 'erased'"
        if record.kind == "party":
            data: dict[str, Any] = {"party": json_one(session, f"select to_jsonb(p) {strip} from connect.src_party p "
                                                               "where id = :i", i=i)}
            ref = session.execute(text("select connection_id, ref from connect.src_party where id = :i"),
                                  {"i": i}).first()
            if ref is not None:
                data["invoices"] = json_rows(
                    session, "select jsonb_build_object('number', number, 'kind', kind, 'issued', issue_date, "
                             "'due', due_date, 'total', total, 'paid', paid, 'status', status) from "
                             "connect.src_invoice "
                             "where connection_id = :c and party_ref = :r order by issue_date",
                                 c=str(ref.connection_id),
                    r=ref.ref)
            return data
        return {"user": json_one(session, f"select to_jsonb(u) {strip} from connect.src_user u where id = :i", i=i)}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = str(record.record_id)
        table = TABLES[record.kind]
        row = session.execute(text(f"select ref, connection_id from {table} where id = :i for update"),
            {"i": i}).first()
        if row is None:
            return Outcome("refused", message="The record no longer exists")
        if record.kind == "party":
            session.execute(text(
                "update connect.src_party set name = :n, phone = null, email = null, tax_id = null, erased = true "
                "where id = :i"), {"n": f"{PLACEHOLDER} party", "i": i})
            session.execute(text(
                "update connect.src_payment set party_name = :n where connection_id = :c and party_ref = :r "
                "and party_name is not null"), {"n": PLACEHOLDER, "c": str(row.connection_id), "r": row.ref})
            changed = ["name replaced", "phone, email and tax number removed", "payer name on payments removed"]
        else:
            session.execute(text("update connect.src_user set name = :n, email = null, erased = true where id = :i"),
                            {"n": f"{PLACEHOLDER} user", "i": i})
            changed = ["name replaced", "email removed"]
        return Outcome("anonymised", changed=changed, kept=[
            Kept("amounts, dates and references of the sales, payments and invoices read from the other system",
                 "copies of the business's own records; they name the person only by the other system's code"),
            Kept("the person's details in the other system itself",
                 "Ziira only reads it; correct or erase the person there as well, or the next read of that system "
                 "will bring them back into its own records (Ziira keeps this record anonymised)")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("connect", "source_copies",
                              "Customers, suppliers and users read from connected systems, and the sales, payments and "
                              "invoices they appear on (read-only copies)",
                              "Intelligence needs the history to learn what is normal; disconnecting a system can "
                              "delete everything read from it",
                              period="until the system is disconnected with its data deleted", at_end="review")]

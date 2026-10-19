"""Time and Billing's personal data for data subject requests: notes written about clients.

Plugged into the kernel's "kernel.personal_data" socket (docs/privacy.md). The module holds no names of its own (clients
are CRM customers, staff are users): what can identify a person here is free text, the billing notes on a client and the
notes on a project. Those are found by name and emptied on erasure. Time, expenses and invoice reviews stay: they are
the business's financial records and name people only by id.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import (
    Kept,
    Outcome,
    PersonalDataProvider,
    PersonalRecord,
    RetentionRule,
    Session,
    Subject,
    json_one,
    like_pattern,
    provides,
)


@provides("kernel.personal_data")
class TimeBillingPersonalData(PersonalDataProvider):
    name = "timebilling"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        terms = [t for t in (subject.name, subject.email, subject.phone) if t]
        found: list[PersonalRecord] = []
        for term in terms:
            params = {"c": str(company_id), "n": like_pattern(term)}
            for r in session.execute(text(
                    "select id, customer_id from timebilling.client_terms where company_id = :c and "
                    "billing_notes ilike :n"), params):
                found.append(PersonalRecord("timebilling", "client_notes", r.id, "Billing notes of a client",
                                            "possible", company_id))
            for r in session.execute(text(
                    "select id, code, name from timebilling.project where company_id = :c and notes ilike :n"),
                    params):
                found.append(PersonalRecord("timebilling", "project_notes", r.id,
                                            f"Notes on project {r.code} {r.name}", "possible", company_id))
        seen: set[UUID] = set()
        unique = []
        for x in found:
            if x.record_id not in seen:
                seen.add(x.record_id)
                unique.append(x)
        return unique

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        table = "client_terms" if record.kind == "client_notes" else "project"
        column = "billing_notes" if record.kind == "client_notes" else "notes"
        return {"record": json_one(session, f"select jsonb_build_object('{column}', {column}) from timebilling.{table} "
                                            "where id = :i", i=str(record.record_id))}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        table = "client_terms" if record.kind == "client_notes" else "project"
        column = "billing_notes" if record.kind == "client_notes" else "notes"
        session.execute(text(f"update timebilling.{table} set {column} = null, updated_at = now() where id = :i"),
                        {"i": str(record.record_id)})
        return Outcome("anonymised", changed=[f"{column.replace('_', ' ')} emptied"],
                       kept=[Kept("time entries, expenses and invoice reviews",
                                  "the business's billing records; they name people only by id")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("timebilling", "notes", "Notes on clients, projects, time entries and expenses",
                              "Billing the client and answering questions about an invoice",
                              period="as long as the project is billed or open; the company can set a limit in the "
                                     "time settings", at_end="review")]

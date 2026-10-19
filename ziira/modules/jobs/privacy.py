"""Jobs' personal data for data subject requests: the customer's name and phone kept on jobs, their notes, and the
items they brought.

Plugged into the kernel's "kernel.personal_data" socket (docs/privacy.md). The customer record itself belongs to the
CRM unit. A job is a business record (parts used, labour, an invoice), so it is kept; only the identifying text is
replaced. An open job (not yet collected or closed) still needs the customer's name and phone to give the item back,
so those are kept with the reason.
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
    json_rows,
    like_pattern,
    provides,
    sql_phone_matches,
)

STRIP = "- 'tenant_id' - 'created_by' - 'updated_by'"


@provides("kernel.personal_data")
class JobsPersonalData(PersonalDataProvider):
    name = "jobs"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[UUID, PersonalRecord] = {}
        base = "select id, number, title, customer_name from jobs.job where company_id = :c and "
        queries: list[tuple[str, dict[str, Any], str]] = []
        digits = subject.phone or (subject.identifier if subject.identifier and subject.identifier.isdigit() else None)
        if digits:
            queries.append((sql_phone_matches("customer_phone", "p"), {"p": digits}, "exact"))
        if subject.name:
            queries.append(("customer_name ilike :n", {"n": like_pattern(subject.name)}, "possible"))
        for condition, extra, match in queries:
            for row in session.execute(text(base + condition), {"c": str(company_id), **extra}):
                if (row.customer_name or "").startswith(PLACEHOLDER):
                    continue
                previous = found.get(row.id)
                if previous is None or (previous.match == "possible" and match == "exact"):
                    found[row.id] = PersonalRecord("jobs", "job", row.id, f"Job {row.number}: {row.title}", match,
                                                   company_id)
        return list(found.values())

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = str(record.record_id)
        return {
            "job": json_rows(session, f"select to_jsonb(j) {STRIP} from jobs.job j where id = :i", i=i),
            "notes_and_history": json_rows(
                session, "select jsonb_build_object('when', created_at, 'kind', kind, 'note', note) "
                         "from jobs.job_event where job_id = :i order by created_at", i=i),
            "checklist": json_rows(
                session, "select jsonb_build_object('line', label, 'state', state, 'note', note) "
                         "from jobs.job_checklist_item where job_id = :i order by position", i=i),
            "item": json_rows(
                session, f"select to_jsonb(a) {STRIP} from jobs.asset a where id = (select asset_id from jobs.job "
                         "where id = :i)", i=i),
        }

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = str(record.record_id)
        job = session.execute(text(
            "select j.number, s.kind from jobs.job j join jobs.job_status s on s.id = j.status_id "
            "where j.id = :i for update of j"), {"i": i}).first()
        if job is None:
            return Outcome("refused", message="The job no longer exists")
        if job.kind in ("open", "waiting"):
            return Outcome("refused", kept=[Kept("the whole job", "the item is still with the business and the "
                                                                  "customer's name and phone are needed to return it")],
                           message="Finish or cancel the job first, then raise a new request")
        session.execute(text(
            "update jobs.job set customer_name = :n, customer_phone = null, collected_by_name = null, "
            "updated_at = now() where id = :i"), {"n": f"{PLACEHOLDER} customer", "i": i})
        notes = int(session.execute(text(
            "update jobs.job_event set note = :p where job_id = :i and kind = 'note' and note is not null"),
            {"p": PLACEHOLDER, "i": i}).rowcount)  # type: ignore[attr-defined]
        session.execute(text("update jobs.job_checklist_item set note = null where job_id = :i"), {"i": i})
        session.execute(text("update jobs.estimate set decided_by_name = null, decision_note = null where job_id = :i"),
                        {"i": i})
        return Outcome(
            "anonymised",
            changed=["customer name and phone replaced", f"{notes} note(s) emptied", "checklist notes and the name "
                     "given when approving or collecting removed"],
            kept=[Kept(f"job {job.number} with its parts, labour, estimates and invoice link",
                       "the business's repair and financial records; they name the customer only by number")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("jobs", "jobs", "Customer name and phone on jobs, notes on the timeline and the items "
                                              "customers brought",
                              "Doing and warranting the work, and the business's repair records",
                              period="while the job is open and through its warranty; erased on request once closed",
                              at_end="review")]

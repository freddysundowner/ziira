"""Claims' personal data for data subject requests: the insured person's name and phone kept on claims, their notes, and
the names typed when signing off or deciding.

Plugged into the kernel's "kernel.personal_data" socket (docs/privacy.md). The customer record itself belongs to the CRM
unit. A claim is a business record (amounts, invoices, the payer's answers), so it is kept; only the identifying text is
replaced. An open claim still needs the name and phone to finish the work and be paid, so those are kept with the
reason.
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
class ClaimsPersonalData(PersonalDataProvider):
    name = "claims"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        found: dict[UUID, PersonalRecord] = {}
        base = "select id, number, subject, insured_name from claims.claim where company_id = :c and "
        queries: list[tuple[str, dict[str, Any], str]] = []
        digits = subject.phone or (subject.identifier if subject.identifier and subject.identifier.isdigit() else None)
        if digits:
            queries.append((sql_phone_matches("insured_phone", "p"), {"p": digits}, "exact"))
        if subject.name:
            queries.append(("insured_name ilike :n", {"n": like_pattern(subject.name)}, "possible"))
        for condition, extra, match in queries:
            for row in session.execute(text(base + condition), {"c": str(company_id), **extra}):
                if (row.insured_name or "").startswith(PLACEHOLDER):
                    continue
                previous = found.get(row.id)
                if previous is None or (previous.match == "possible" and match == "exact"):
                    found[row.id] = PersonalRecord("claims", "claim", row.id,
                                                   f"Claim {row.number}: {row.subject or ''}".strip(), match,
                                                   company_id)
        return list(found.values())

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        i = str(record.record_id)
        return {
            "claim": json_rows(session, f"select to_jsonb(c) {STRIP} from claims.claim c where id = :i", i=i),
            "timeline": json_rows(
                session, "select jsonb_build_object('when', created_at, 'kind', kind, 'note', note, 'by', actor_name) "
                         "from claims.claim_event where claim_id = :i order by created_at", i=i),
            "estimates": json_rows(
                session, "select jsonb_build_object('version', e.version, 'status', e.status, 'total', e.total) "
                         "from claims.estimate e where claim_id = :i order by seq", i=i),
        }

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        i = str(record.record_id)
        claim = session.execute(text("select number, status from claims.claim where id = :i for update"),
                                {"i": i}).first()
        if claim is None:
            return Outcome("refused", message="The claim no longer exists")
        if claim.status not in ("settled", "closed"):
            return Outcome("refused", kept=[Kept("the whole claim", "the claim is still open: the name and phone are "
                                                                    "needed to finish the work and be paid")],
                           message="Close or settle the claim first, then raise a new request")
        session.execute(text(
            "update claims.claim set insured_name = :n, insured_phone = null, loss_description = null, "
            "assessor_name = null, assessor_phone = null, completion_signed_by = null, completion_note = null, "
            "authority_by = null, closed_note = null, updated_at = now() where id = :i"),
            {"n": f"{PLACEHOLDER} customer", "i": i})
        session.execute(text("update claims.estimate_line set customer_decision_by = null where claim_id = :i"),
                        {"i": i})
        session.execute(text("update claims.estimate set notes = null, revision_note = null where claim_id = :i"),
                        {"i": i})
        return Outcome(
            "anonymised",
            changed=["insured name and phone replaced", "loss description, assessor and sign-off names emptied",
                     "notes on estimates emptied"],
            kept=[Kept(f"claim {claim.number} with its estimates, the payer's answers, invoices and receipts",
                       "the business's and the payer's financial records; they name the customer only by number"),
                  Kept("the timeline of the claim", "an audit trail of what was done; written by staff and kept "
                                                    "as a record")])

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        return [RetentionRule("claims", "claims", "Insured name and phone, notes, assessor details and the names typed "
                                                  "when signing off, on claims and their estimates",
                              "Settling the claim with the payer and the business's financial records",
                              period="while the claim is open and until the payer has paid; erased on request once "
                                     "settled or closed", at_end="review")]

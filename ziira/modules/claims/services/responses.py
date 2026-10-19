"""Use cases: the payer's answers, and the business's answers to them.

The payer answers each line of an estimate: approved, countered with an amount, rejected with a reason, or needs more
information. The answer reaches us on the response link (`channel = link`) or is written down by staff after a phone
call,
an email or a portal (`channel = staff`, with who answered, when and how). Every answer is kept for ever. After a
counter
the business accepts it or argues it again (a new version); after a rejection the customer says whether they will pay.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.permissions import CLAIMS_ESTIMATE
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Estimate, EstimateLine, EstimateResponse, LineResponse
from ziira.modules.claims.services import status
from ziira.modules.claims.services.common import add_event, clean, load_estimate, load_line, now
from ziira.sdk import Conflict, Event, Session, ValidationFailed, audit_record, current_context, publish

VIAS = ("phone", "email", "portal", "in_person", "message", "letter", "other")


@dataclass(frozen=True)
class AnswerIn:
    line_id: UUID
    state: str
    amount: Decimal | None = None
    reason: str | None = None


def apply_response(session: Session, estimate: Estimate, claim: Claim, answers: list[AnswerIn], *, by_name: str,
                   by_user: UUID | None, channel: str, via: str | None, occurred_at: datetime | None,
                   note: str | None, authority_ref: str | None, authority_amount: Decimal | None) -> EstimateResponse:
    """Store an answer of the payer. The estimate must be waiting for it; only lines still waiting can be answered."""
    who = clean(by_name, 160)
    if who is None:
        raise ValidationFailed("Say who gave the answer")
    if estimate.status != "submitted":
        raise Conflict(f"This estimate is {estimate.status}: it cannot be answered")
    if claim.status == "closed":
        raise Conflict("This claim is closed")
    if not answers:
        raise ValidationFailed("Answer at least one line")
    if len({a.line_id for a in answers}) != len(answers):
        raise ValidationFailed("Each line is answered once")
    moment = occurred_at or now()
    if moment > now() + timedelta(minutes=5):
        raise ValidationFailed("The time of the answer cannot be in the future")
    rows = {r.id: r for r in repo.estimate_lines(session, estimate.id)}
    round_no = repo.rounds_so_far(session, estimate.id) + 1
    ctx = current_context()
    for answer in answers:
        row = rows.get(answer.line_id)
        if row is None:
            raise ValidationFailed("A line in the answer is not on this estimate")
        if row.locked or row.payer_state not in ("pending", "needs_information"):
            raise ValidationFailed(f"'{row.description}' was already answered")
        try:
            amount = rules.check_answer(answer.state, row.asked_total, answer.amount, answer.reason)
        except ValueError as problem:
            raise ValidationFailed(f"{row.description}: {problem}") from None
        row.payer_state, row.payer_amount = answer.state, amount
        row.payer_reason = clean(answer.reason, 500)
        row.responded_at = moment
        row.our_decision = row.customer_decision = row.shortfall_to = None
        session.add(LineResponse(
            tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id, estimate_id=estimate.id,
            line_id=row.id, round=round_no, state=answer.state, amount=amount, reason=row.payer_reason, by_name=who,
            by_user=by_user, channel=channel, via=via, answered_at=moment))
    session.flush()
    overall = rules.overall_response([a.state for a in answers]) or "partly_accepted"
    waiting = [r for r in rows.values() if not r.locked and r.payer_state in ("pending", "needs_information")]
    estimate.response = overall
    if not any(r.payer_state == "pending" for r in rows.values()) and not waiting:
        estimate.status, estimate.answered_at = "answered", now()
        estimate.response = rules.overall_response([r.payer_state for r in rows.values()]) or overall
    elif not any(r.payer_state == "pending" for r in rows.values()):
        estimate.response = rules.overall_response([r.payer_state for r in rows.values()]) or overall
    record = EstimateResponse(
        tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id, estimate_id=estimate.id,
        round=round_no, response=overall, by_name=who, by_user=by_user, channel=channel, via=via, occurred_at=moment,
        note=clean(note, 1000), authority_ref=clean(authority_ref, 80), authority_amount=authority_amount)
    repo.add(session, record)
    if record.authority_ref:
        claim.authority_ref, claim.authority_amount = record.authority_ref, authority_amount
        claim.authority_by, claim.authority_at = who, moment
    counts = _summary(answers)
    from ziira.modules.claims.services.estimates import label

    add_event(session, claim, "response", f"{label(estimate)}: {who} ({_how(channel, via)}) answered, {counts}"
              + (f". {record.note}" if record.note else "") + (f". Authority {record.authority_ref}"
                                                              if record.authority_ref else ""),
              estimate_id=estimate.id, actor=who, channel=channel, system=channel == "link")
    if record.authority_ref:
        add_event(session, claim, "authority", f"Authority to repair {record.authority_ref}"
                  + (f" for {record.authority_amount}" if record.authority_amount else ""), estimate_id=estimate.id,
                  actor=who, channel=channel, system=channel == "link")
    audit_record(session, "respond", "claims.estimate", estimate.id, {"channel": channel, "response": overall,
                                                                       "round": round_no})
    status.refresh(session, claim)
    publish(session, Event("claim.response_recorded", "claims.claim", claim.id, {
        "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number,
        "estimate_id": estimate.id, "response": overall, "channel": channel,
        "source_type": claim.source_type, "source_id": claim.source_id}))
    return record


def _summary(answers: list[AnswerIn]) -> str:
    names = {"approved": "approved", "countered": "countered", "rejected": "rejected",
             "needs_information": "need more information"}
    parts = []
    for state, word in names.items():
        count = sum(1 for a in answers if a.state == state)
        if count:
            parts.append(f"{count} {word}")
    return ", ".join(parts)


def _how(channel: str, via: str | None) -> str:
    return "on the response link" if channel == "link" else f"recorded by staff, {(via or 'other').replace('_', ' ')}"


def record_response(session: Session, estimate_id: UUID, answers: list[AnswerIn], *, by_name: str, via: str,
                    occurred_at: datetime | None = None, note: str | None = None, authority_ref: str | None = None,
                    authority_amount: Decimal | None = None) -> Estimate:
    """Write down an answer received by phone, email, a portal or in person: who gave it, how and when. Needs
    'claims.estimate'."""
    estimate, claim = load_estimate(session, estimate_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)
    if via not in VIAS:
        raise ValidationFailed(f"The answer came by one of: {', '.join(VIAS)}")
    apply_response(session, estimate, claim, answers, by_name=by_name, by_user=ctx.user_id, channel="staff", via=via,
                   occurred_at=occurred_at, note=note, authority_ref=authority_ref, authority_amount=authority_amount)
    return estimate


def record_withdrawal(session: Session, estimate: Estimate, claim: Claim, note: str | None) -> None:
    ctx = current_context()
    round_no = repo.rounds_so_far(session, estimate.id) + 1
    repo.add(session, EstimateResponse(
        tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id, estimate_id=estimate.id,
        round=round_no, response="withdrawn", by_name="Us", by_user=ctx.user_id, channel="staff", via="other",
        occurred_at=now(), note=clean(note, 1000)))


def _open_line(session: Session, line_id: UUID) -> tuple[EstimateLine, Estimate, Claim]:
    line, estimate, claim = load_line(session, line_id, lock=True)
    current_context().require(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)
    if claim.status == "closed":
        raise Conflict("This claim is closed")
    if line.invoiced_run_id is not None:
        raise Conflict("This line has been invoiced: use a reduction to change what the payer pays")
    if estimate.status not in ("submitted", "answered"):
        raise Conflict("This estimate is no longer in play")
    return line, estimate, claim


def decide_counter(session: Session, line_id: UUID, *, accept: bool, shortfall_to: str | None = None,
                   customer_agreed_by: str | None = None, note: str | None = None) -> EstimateLine:
    """Answer a counter-offer. Accepting makes the line worth the payer's amount; say who carries the difference
    (`business` absorbs it, `customer` pays it, and then the customer's name is needed). Declining keeps the line
    open to
    be argued again in the next version. Needs 'claims.estimate'."""
    line, estimate, claim = _open_line(session, line_id)
    if line.payer_state != "countered":
        raise Conflict("Only a counter-offer can be accepted or declined")
    if accept:
        carrier = shortfall_to or "business"
        if carrier not in ("customer", "business"):
            raise ValidationFailed("The difference is carried by the customer or the business")
        if carrier == "customer" and not (customer_agreed_by or "").strip():
            raise ValidationFailed("Type the name of the customer who agreed to pay the difference")
        line.our_decision, line.shortfall_to = "accepted", carrier
        if carrier == "customer":
            line.customer_decision, line.customer_decision_by = "pays", clean(customer_agreed_by, 160)
            line.customer_decision_at = now()
    else:
        line.our_decision, line.shortfall_to, line.customer_decision = "declined", None, None
    session.flush()
    add_event(session, claim, "decision", f"{line.description}: counter-offer of {line.payer_amount} "
              f"{'accepted' if accept else 'declined (to be argued again)'}"
              + (f", difference carried by the {line.shortfall_to}" if accept else "")
              + (f". {note.strip()}" if note and note.strip() else ""), estimate_id=estimate.id)
    audit_record(session, "decide", "claims.estimate_line", line.id, {"accept": accept})
    status.refresh(session, claim)
    return line


def decide_customer(session: Session, line_id: UUID, *, pays: bool, by_name: str, note: str | None = None
                    ) -> EstimateLine:
    """Write down whether the customer will pay for a line the payer rejected. Needs 'claims.estimate'."""
    line, estimate, claim = _open_line(session, line_id)
    if line.payer_state != "rejected":
        raise Conflict("Only a rejected line waits for the customer's decision")
    who = clean(by_name, 160)
    if who is None:
        raise ValidationFailed("Type the name of the customer who decided")
    line.customer_decision, line.customer_decision_by = ("pays" if pays else "declined"), who
    line.customer_decision_at = now()
    session.flush()
    verdict = "agreed to pay for it" if pays else "declined it"
    add_event(session, claim, "decision", f"{line.description}: {who} {verdict}"
              + (f". {note.strip()}" if note and note.strip() else ""), estimate_id=estimate.id, actor=who)
    audit_record(session, "decide", "claims.estimate_line", line.id, {"pays": pays})
    status.refresh(session, claim)
    return line


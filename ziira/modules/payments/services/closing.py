"""Use cases: the daily branch close (specification section 10).

    open --submit--> submitted --(lock, at once if nothing needs approval)--> locked --reopen (approved)--> reopened

1. All till sessions for the branch and date are closed (asked of POS when it is enabled).
2. M-Pesa and card takings are compared with what the provider's transactions covered.
3. The cash banked is recorded against the cash expected.
4. Variances are listed, with the branch manager's explanation where there are any.
5. The close is locked. Changing that day's payments afterwards needs a reopening (through the approval matrix).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.payments.permissions import CLOSE_REOPEN, CLOSE_SUBMIT
from ziira.modules.payments.repository import payments_repo
from ziira.modules.payments.repository.models import DailyClose
from ziira.modules.payments.services.access import can_view, view_scopes
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    flag_for_review,
    publish,
    submit_for_approval,
)

DOC_TYPE = "daily_close"
LOCKED = ("locked",)


def check_day_open(session: Session, branch_id: UUID | None, day: date) -> None:
    """Refuse changes to a branch's payments for a day whose close is locked."""
    if branch_id is None:
        return
    close = payments_repo.get_close(session, branch_id, day)
    if close is not None and close.status in LOCKED:
        raise ValidationFailed(f"The close for {day} is locked: ask for it to be reopened before changing that day")


@dataclass(frozen=True)
class CloseSummary:
    close: DailyClose
    problems: list[str]
    totals: dict[str, Any]


def _open_till_sessions(session: Session, branch_id: UUID, day: date) -> int:
    """How many till sessions of the branch and date are still open (zero when POS is not enabled)."""
    enabled = session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'pos' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first()
    if enabled is None:
        return 0
    from ziira.modules.pos.public import open_till_sessions

    return open_till_sessions(session, branch_id, day)


def compute_totals(session: Session, company_id: UUID, branch_id: UUID, day: date,
                   cash_banked: Decimal | None) -> tuple[dict[str, Any], list[str], Decimal]:
    """The close's figures, what is wrong, and the variance (cash banked less cash expected, plus unmatched takings)."""
    totals = payments_repo.payment_totals(session, branch_id, day)

    def amount(direction: str, method: str) -> Decimal:
        return totals.get((direction, method), Decimal(0))

    problems: list[str] = []
    open_sessions = _open_till_sessions(session, branch_id, day)
    if open_sessions:
        problems.append(f"{open_sessions} till session(s) are still open")
    figures: dict[str, Any] = {}
    unmatched_takings = Decimal(0)
    for method in ("mpesa", "card"):
        taken = amount("in", method) - amount("out", method)
        matched = payments_repo.matched_total_for_branch(session, branch_id, day, method)
        figures[method] = {"taken": str(taken), "matched": str(matched), "unmatched": str(taken - matched)}
        if taken != matched:
            problems.append(f"{method}: {taken - matched} of {taken} taken is not yet matched to the provider")
            unmatched_takings += taken - matched
    cash_expected = amount("in", "cash") - amount("out", "cash")
    figures["cash"] = {"expected": str(cash_expected), "banked": str(cash_banked) if cash_banked is not None else None}
    variance = unmatched_takings
    if cash_banked is not None:
        variance += cash_expected - cash_banked
    figures["variance"] = str(variance)
    return figures, problems, variance


def get_or_start(session: Session, company_id: UUID, branch_id: UUID, day: date) -> DailyClose:
    close = payments_repo.get_close(session, branch_id, day, lock=True)
    if close is not None:
        return close
    ctx = current_context()
    close = DailyClose(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
                       business_date=day)
    payments_repo.add(session, close)
    return close


def preview(session: Session, company_id: UUID, branch_id: UUID, day: date,
            cash_banked: Decimal | None = None) -> CloseSummary:
    """Where the branch stands for a day: the figures and what is still wrong. Needs 'close.submit' for the branch."""
    check_company(session, company_id, branch_id)
    current_context().require(CLOSE_SUBMIT, company_id=company_id, branch_id=branch_id)
    close = get_or_start(session, company_id, branch_id, day)
    figures, problems, _ = compute_totals(session, company_id, branch_id, day, cash_banked)
    return CloseSummary(close, problems, figures)


def submit(session: Session, company_id: UUID, branch_id: UUID, day: date, *, cash_banked: Decimal,
           explanation: str | None = None) -> CloseSummary:
    """Submit the day's close and lock it. Every till session must be closed; a variance needs an explanation. Needs
    'close.submit' for the branch."""
    check_company(session, company_id, branch_id)
    ctx = current_context()
    ctx.require(CLOSE_SUBMIT, company_id=company_id, branch_id=branch_id)
    if cash_banked < 0 or cash_banked != cash_banked.quantize(Decimal("0.01")):
        raise ValidationFailed("Cash banked must be an amount with at most 2 decimal places")
    close = get_or_start(session, company_id, branch_id, day)
    if close.status in ("submitted", "locked"):
        raise Conflict(f"The close for {day} is already {close.status}")
    figures, problems, variance = compute_totals(session, company_id, branch_id, day, cash_banked)
    blocking = [p for p in problems if "till session" in p]
    if blocking:
        raise ValidationFailed("The day cannot be closed: " + "; ".join(blocking))
    if variance != 0 and not (explanation and explanation.strip()):
        raise ValidationFailed(f"The day has a variance of {variance}: explain it before closing")
    close.totals, close.variance, close.cash_banked = figures, variance, cash_banked
    close.explanation = (explanation or "").strip() or None
    close.submitted_by, close.submitted_at = ctx.user_id, datetime.now(UTC)
    close.status = "locked"
    close.locked_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "submit", "payments.daily_close", close.id,
                 {"date": day, "variance": variance, "cash_banked": cash_banked})
    publish(session, Event("close.completed", "payments.daily_close", close.id, {
        "company_id": company_id, "branch_id": branch_id, "business_date": day, "variance": variance}))
    if variance != 0:
        publish(session, Event("close.variance", "payments.daily_close", close.id, {
            "company_id": company_id, "branch_id": branch_id, "business_date": day, "variance": variance}))
        flag_for_review(session, unit="payments", kind="close_variance", severity="medium", company_id=company_id,
                        branch_id=branch_id, ref_type="daily_close", ref_id=close.id, amount=variance,
                        dedupe_key=f"close_variance:{close.id}",
                        message=f"The close for {day} has a variance of {variance}: {close.explanation}")
    return CloseSummary(close, problems, figures)


def request_reopen(session: Session, close_id: UUID, reason: str) -> DailyClose:
    """Ask to reopen a locked day. With no approval rule it reopens at once; otherwise an approver decides. Needs
    'close.reopen'."""
    close = payments_repo.get_close_by_id(session, close_id, lock=True)
    if close is None or not can_view(close.company_id, close.branch_id):
        raise NotFound("Close not found")
    current_context().require(CLOSE_REOPEN, company_id=close.company_id, branch_id=close.branch_id)
    if close.status != "locked":
        raise Conflict(f"The close is {close.status}, not locked")
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    audit_record(session, "reopen_requested", "payments.daily_close", close.id, {"reason": reason.strip()})
    if submit_for_approval(session, company_id=close.company_id, doc_type=DOC_TYPE, doc_id=close.id,
                           amount=abs(close.variance)) == "approved":
        _reopen(session, close, current_context().user_id)
    else:
        close.explanation = f"{close.explanation or ''}\n[Reopen requested: {reason.strip()}]".strip()
        session.flush()
    return close


def apply_decision(session: Session, close_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Reopen the day when the approval is granted (from `approval.decided`)."""
    close = payments_repo.get_close_by_id(session, close_id, lock=True)
    if close is None or close.status != "locked":
        return
    current_context().require(CLOSE_REOPEN, company_id=close.company_id, branch_id=close.branch_id)
    if approved:
        _reopen(session, close, decided_by)


def _reopen(session: Session, close: DailyClose, by: UUID | None) -> None:
    close.status, close.reopened_by, close.locked_at = "reopened", by, None
    session.flush()
    audit_record(session, "reopen", "payments.daily_close", close.id, {"date": close.business_date})


def list_closes(session: Session, *, branch_id: UUID | None = None, status: str | None = None, limit: int = 100,
                offset: int = 0) -> list[DailyClose]:
    return payments_repo.list_closes(session, view_scopes(), branch_id=branch_id, status=status,
                                     limit=min(limit, 500), offset=offset)

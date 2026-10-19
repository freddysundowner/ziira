"""Recurring work of Time and Billing (run by `ziira worker`): prepare the dated work of recurring engagements, draft
the month's invoice for monthly-fee retainers, expire unused prepaid hours, and queue the reminders. Each piece is done
in its own savepoint, so one company's or one client's problem never stops the rest, and a problem is put in the
exceptions inbox (never skipped silently). Nothing here sends a message or issues an invoice: messages are queued and
invoices are only ever drafted for a person to review."""

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select, text

from ziira.modules.timebilling.repository.models import Retainer
from ziira.modules.timebilling.services import billing, common, engagements, nudges, retainers
from ziira.sdk import Session, flag_for_review, periodic

log = logging.getLogger("ziira.timebilling")


def _guarded(session: Session, company_id: UUID, what: str, key: str, work: object) -> None:
    try:
        with session.begin_nested():
            work()  # type: ignore[operator]
    except Exception as error:  # noqa: BLE001 - flagged for a person, the next run tries again
        log.exception("Time and Billing: %s failed", what)
        flag_for_review(session, unit="timebilling", kind="task_failed", severity="medium", company_id=company_id,
                        message=f"{what} could not be done: {error}"[:500], dedupe_key=f"timebilling-task:{key}")


def draft_monthly_fees(session: Session, company_id: UUID, today: date) -> int:
    """For each active monthly-fee retainer set to draft its invoices: from its billing day on, start a review for the
    current month if that month has not been drafted yet (a draft a person discarded stays discarded). Returns how
    many reviews were drafted."""
    made = 0
    period = f"{today.year}-{today.month:02d}"
    for retainer in session.scalars(select(Retainer).where(
            Retainer.company_id == company_id, Retainer.kind == "monthly_fee", Retainer.status == "active",
            Retainer.auto_draft.is_(True))):
        if today.day < retainer.bill_day:
            continue
        taken = session.execute(text(
            "select 1 from timebilling.invoice_batch_line l join timebilling.invoice_batch b on b.id = l.batch_id "
            "where l.retainer_id = :r and l.period = :p and l.kind = 'retainer_fee'"),
            {"r": str(retainer.id), "p": period}).first()        # any review, even a discarded one
        if taken is not None:
            continue
        _guarded(session, company_id, f"Drafting the {period} fee for a retainer", f"fee:{retainer.id}:{period}",
                 lambda r=retainer: billing.add_retainer_fee(session, r.id, period=period))
        made += 1
    return made


def run_company(session: Session, company_id: UUID, now: datetime) -> dict[str, int]:
    """Everything due for one company now. Returns counts, for tests and `ziira run-task`."""
    today = common.today(session, company_id)
    done = {"tasks": 0, "fees": 0, "expired": 0}
    _guarded(session, company_id, "Preparing recurring work", f"recur:{company_id}",
             lambda: done.update(tasks=engagements.generate(session, company_id, today)))
    _guarded(session, company_id, "Drafting monthly fees", f"fees:{company_id}",
             lambda: done.update(fees=draft_monthly_fees(session, company_id, today)))
    _guarded(session, company_id, "Expiring prepaid hours", f"expire:{company_id}",
             lambda: done.update(expired=retainers.expire_due(session, company_id, today)))
    reminders: dict[str, int] = {}
    _guarded(session, company_id, "Queueing reminders", f"nudges:{company_id}",
             lambda: reminders.update(nudges.run_company(session, company_id, now)))
    done.update(reminders)
    return done


@periodic("timebilling.run", every_seconds=3600)
def run(session: Session) -> None:
    """Hourly: prepare dated work, draft monthly fees, expire prepaid hours and queue reminders, for each company in
    its own date and hour."""
    for company in session.execute(text("select id from kernel.company order by id")).all():
        run_company(session, company.id, datetime.now(UTC))

"""Messages to the people who work in Time and Billing: missed time, weeks waiting for approval, invoices waiting for a
partner, work coming due. Only ever queued (the worker sends them) through the business's channels in the order the
notification layer ranks them, in each person's language, outside their quiet hours; a person who chose "app only" for
that kind of message, or whom nobody can reach, is simply not messaged (the app shows the same things on its own pages).
Each message is sent once per subject and day (`nudge_log`) so a task that runs every hour never repeats itself."""

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.timebilling.permissions import TIME_APPROVE, TIME_PARTNER
from ziira.modules.timebilling.repository.models import InvoiceBatch
from ziira.sdk import (
    Session,
    channel_names,
    configured_channels,
    current_context,
    format_day,
    notify_user_templated,
    recipients_with_permission,
)

log = logging.getLogger("ziira.timebilling")


def business_name(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select name from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar() or "")


def tell(session: Session, *, company_id: UUID, user_id: UUID, kind: str, template: str, variables: dict[str, str],
         subject_id: UUID, day: date, ref_type: str | None = None) -> bool:
    """Queue one templated message to a staff member, once per (template, subject, person, day). Never raises: a message
    that cannot be queued must not stop the work that wanted it. Returns True when something was queued."""
    ready = [c for c in channel_names(session) if c in configured_channels(session, company_id)]
    if not ready:
        return False
    marked = session.execute(text(
        "insert into timebilling.nudge_log (tenant_id, company_id, kind, subject_id, user_id, day) "
        "values (kernel.current_tenant(), :c, :k, :s, :u, :d) on conflict do nothing returning id"),
        {"c": str(company_id), "k": template, "s": str(subject_id), "u": str(user_id), "d": day}).first()
    if marked is None:
        return False
    try:
        with session.begin_nested():
            queued = notify_user_templated(
                session, company_id=company_id, user_id=user_id, kind=kind, template=template, variables=variables,
                default_channels=ready, require_configured=True, ref_type=ref_type, ref_id=subject_id,
                dedupe_key=f"tb:{template}:{subject_id}:{user_id}:{day}")
        if queued is None:                       # nobody to reach: let a later run try again
            session.execute(text("delete from timebilling.nudge_log where kind = :k and subject_id = :s and "
                                 "user_id = :u and day = :d"),
                            {"k": template, "s": str(subject_id), "u": str(user_id), "d": day})
        return queued is not None
    except Exception:  # noqa: BLE001 - see the docstring
        log.exception("Could not queue %s for %s", template, user_id)
        return False


def partner_review_requested(session: Session, batch: InvoiceBatch, client_name: str, amount: Decimal) -> int:
    """Tell the partners an invoice review is waiting for them (not the person who asked, if they are one)."""
    told = 0
    me = current_context().user_id
    for person in recipients_with_permission(session, TIME_PARTNER):
        if person.user_id == me or not person.covers(TIME_PARTNER, batch.company_id, batch.branch_id):
            continue
        told += tell(session, company_id=batch.company_id, user_id=person.user_id, kind="approvals",
                     template="partner_review",
                     variables={"name": person.full_name.split()[0], "client": client_name or "-",
                                "amount": f"{amount:,.2f}", "business": business_name(session, batch.company_id)},
                     subject_id=batch.id, day=_today(session, batch.company_id), ref_type="timebilling.invoice_batch")
    return told


def review_sent_back(session: Session, batch: InvoiceBatch, note: str) -> None:
    """Tell the person who built the review that a partner sent it back."""
    if batch.review_requested_by is None:
        return
    from ziira.modules.timebilling.services import common

    names = common.customer_names(session, {batch.client_id})
    first = common.user_names(session, {batch.review_requested_by}).get(batch.review_requested_by, "").split()
    tell(session, company_id=batch.company_id, user_id=batch.review_requested_by, kind="approvals",
         template="review_sent_back",
         variables={"name": first[0] if first else "", "client": names.get(batch.client_id, "-"), "note": note[:200],
                    "business": business_name(session, batch.company_id)},
         subject_id=batch.id, day=_today(session, batch.company_id), ref_type="timebilling.invoice_batch")


def _today(session: Session, company_id: UUID) -> date:
    from ziira.modules.timebilling.services import common

    return common.today(session, company_id)


def approvers_for(session: Session, company_id: UUID, branch_id: UUID | None, author: UUID) -> list[Any]:
    """People who may approve a week (never its author), best placed first is up to the caller."""
    return [p for p in recipients_with_permission(session, TIME_APPROVE)
            if p.user_id != author and p.covers(TIME_APPROVE, company_id, branch_id)]


def short_day(day: date) -> str:
    return format_day(day)

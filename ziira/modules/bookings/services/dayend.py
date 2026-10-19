"""The day-end summary for a branch: what was taken and how, tips owed, commission earned, and the day's visits.

Everything is read from Bookings' own checkouts; the cash drawer itself is counted in Point of Sale's till close.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.bookings.permissions import BOOKINGS_REPORTS
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.services import access
from ziira.modules.bookings.services.common import zone
from ziira.sdk import NotFound, Session, current_context

ZERO = Decimal(0)


def day_end(session: Session, branch_id: UUID, day: date) -> dict[str, Any]:
    """The branch's figures for one local day. Needs 'bookings.reports' at the branch."""
    found = raw.one(session, "select company_id from kernel.branch where id = :b", b=branch_id)
    if found is None or not access.can_view(found["company_id"], branch_id):
        raise NotFound("Branch not found")
    company_id = found["company_id"]
    current_context().require(BOOKINGS_REPORTS, company_id=company_id, branch_id=branch_id)
    tz = str(zone(session, company_id))
    p = {"b": branch_id, "d": day, "tz": tz, "c": company_id}
    done = raw.one(session, """
        select count(*) as visits, coalesce(sum(total), 0) as billed, coalesce(sum(paid_total), 0) as paid,
               coalesce(sum(discount_total), 0) as discounts, coalesce(sum(credit_total), 0) as credit_used,
               coalesce(sum(tip_total), 0) as tips
        from bookings.checkout
        where branch_id = :b and status = 'done' and (completed_at at time zone :tz)::date = :d""", **p) or {}
    methods = raw.many(session, """
        select p.kind, p.method, sum(p.amount) as amount, count(*) as n
        from bookings.checkout_payment p join bookings.checkout c on c.id = p.checkout_id
        where c.branch_id = :b and c.status = 'done' and (c.completed_at at time zone :tz)::date = :d
        group by p.kind, p.method order by p.kind, p.method""", **p)
    lines = raw.one(session, """
        select coalesce(sum(l.quantity * l.unit_price - l.discount) filter (where l.kind = 'service'), 0) as services,
               coalesce(sum(l.quantity * l.unit_price - l.discount) filter (where l.kind = 'product'), 0) as products,
               coalesce(sum(l.quantity * l.unit_price - l.discount) filter (where l.kind = 'fee'), 0) as fees
        from bookings.checkout_line l join bookings.checkout c on c.id = l.checkout_id
        where c.branch_id = :b and c.status = 'done' and (c.completed_at at time zone :tz)::date = :d""", **p) or {}
    tips = raw.many(session, """
        select t.resource_id, r.name, sum(t.amount) as amount,
               coalesce(sum(t.amount) filter (where t.held), 0) as held_by_business
        from bookings.checkout_tip t join bookings.resource r on r.id = t.resource_id
        join bookings.checkout c on c.id = t.checkout_id
        where t.branch_id = :b and (c.completed_at at time zone :tz)::date = :d group by t.resource_id, r.name
        order by r.name""", **p)
    commission = raw.many(session, """
        select l.resource_id, r.name, sum(l.amount) as amount from bookings.commission_line l
        join bookings.resource r on r.id = l.resource_id where l.branch_id = :b and l.earned_on = :d
        group by l.resource_id, r.name order by r.name""", **p)
    appts = raw.one(session, """
        select count(*) filter (where status = 'completed') as completed,
               count(*) filter (where status = 'no_show') as no_shows,
               count(*) filter (where status = 'cancelled' and late_cancellation) as late_cancellations,
               count(*) filter (where source = 'walk_in') as walk_ins,
               count(*) filter (where status in ('checked_in', 'in_service')) as still_in
        from bookings.appointment where branch_id = :b and kind = 'appointment'
          and (starts_at at time zone :tz)::date = :d""", **p) or {}
    unbilled = raw.scalar(session, """
        select count(*) from bookings.appointment a where a.branch_id = :b and a.kind = 'appointment'
          and a.status in ('in_service', 'completed') and a.invoice_id is null
          and (a.starts_at at time zone :tz)::date = :d""", **p)
    owing = raw.many(session, """
        select number, client_name, total - paid_total - credit_total as owes from bookings.checkout
        where branch_id = :b and status = 'done' and (completed_at at time zone :tz)::date = :d
          and total - paid_total - credit_total > 0 order by number""", **p)
    return {
        "day": day, "branch_id": branch_id, "visits": int(done.get("visits", 0)),
        "billed": done.get("billed", ZERO), "paid": done.get("paid", ZERO),
        "discounts": done.get("discounts", ZERO), "credit_used": done.get("credit_used", ZERO),
        "tips_total": done.get("tips", ZERO), "services": lines.get("services", ZERO),
        "products": lines.get("products", ZERO), "fees": lines.get("fees", ZERO),
        "payments_by_method": methods, "tips": tips, "commission": commission,
        "completed": int(appts.get("completed", 0)), "no_shows": int(appts.get("no_shows", 0)),
        "late_cancellations": int(appts.get("late_cancellations", 0)), "walk_ins": int(appts.get("walk_ins", 0)),
        "still_in": int(appts.get("still_in", 0)), "not_billed": int(unbilled), "owing": owing}

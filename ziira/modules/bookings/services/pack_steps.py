"""The first-run checklist an industry pack gives a business: 5 to 7 plain steps that tick themselves when the work is
done (prices set, staff named, a first booking taken ...). The owner can hide the list."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.bookings.permissions import BOOKINGS_SETUP
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.services import access
from ziira.sdk import NotFound, Session, current_context

CHECKS = {
    "prices_set": ("select not exists (select 1 from bookings.service_offer where company_id = :c and is_active "
                   "and price_is_example)"),
    "staff_named": ("select not exists (select 1 from bookings.resource where company_id = :c and is_active "
                    "and is_template and kind = 'staff') and exists (select 1 from bookings.resource where "
                    "company_id = :c and is_active and kind in ('staff', 'chair'))"),
    "services_linked": ("select exists (select 1 from bookings.service_offer where company_id = :c and is_active) and "
                        "not exists (select 1 from bookings.service_offer where company_id = :c and is_active "
                        "and product_id is null)"),
    "booking_page": ("select coalesce((select online_enabled from bookings.booking_settings "
                     "where company_id = :c), false)"),
    "first_booking": ("select exists (select 1 from bookings.appointment a where a.company_id = :c and not exists "
                      "(select 1 from bookings.sample_record s where s.entity = 'appointment' "
                      "and s.entity_id = a.id))"),
    "first_checkout": ("select exists (select 1 from bookings.checkout where company_id = :c and status = 'done')"),
    "fee_item": ("select coalesce((select fee_product_id is not null or (late_cancel_fee_percent = 0 and "
                 "no_show_fee_percent = 0) from bookings.booking_settings where company_id = :c), true)"),
    "commission": "select exists (select 1 from bookings.commission_rule where company_id = :c and is_active)",
    "payers": ("select exists (select 1 from bookings.appointment where company_id = :c "
               "and payer_customer_id is not null)"),
}


def steps_for(session: Session, company_id: UUID) -> list[dict[str, Any]]:
    """The pack's steps for the company, each with `done` (worked out now). Empty when no pack gave any."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    rows = raw.many(session, "select * from bookings.pack_step where company_id = :c order by sort_order, created_at",
                    c=company_id)
    for r in rows:
        sql = CHECKS.get(r["check_key"] or "")
        done = bool(r["done_at"])
        if not done and sql:
            done = bool(session.execute(text(sql), {"c": str(company_id)}).scalar())
            if done:
                raw.run(session, "update bookings.pack_step set done_at = now() where id = :i", i=r["id"])
        r["done"] = done
    return rows


def hide(session: Session, company_id: UUID, hidden: bool) -> None:
    """Hide or show the checklist (the owner or a manager)."""
    current_context().require(BOOKINGS_SETUP, company_id=company_id)
    raw.run(session, "update bookings.pack_step set hidden = :h where company_id = :c", h=hidden, c=company_id)

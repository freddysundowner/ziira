"""Fees for a late cancellation or a no-show: worked out from the business's percents, kept until the client's next
checkout (where they appear as a line), and waived with a reason if the business decides not to charge."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.bookings.domain import checkout as dom
from ziira.modules.bookings.permissions import BOOKINGS_MANAGE
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import Appointment, BookingSettings
from ziira.modules.bookings.services import access
from ziira.sdk import Event, NotFound, Session, ValidationFailed, audit_record, check_reason, current_context, publish


def charge_for_appointment(session: Session, appt: Appointment, settings: BookingSettings, *, late: bool,
                           no_show: bool) -> dict[str, Any] | None:
    """Note the fee owed for an appointment that was cancelled late or missed (nothing when the business set no percent,
    the client is unknown or a fee was already noted). The client sees it as a line on their next checkout."""
    if appt.customer_id is None:
        return None
    amount = dom.fee_due(late, no_show, settings.late_cancel_fee_percent, settings.no_show_fee_percent, appt.price)
    if amount <= 0:
        return None
    kind = "no_show" if no_show else "late_cancel"
    made = raw.one(session, "insert into bookings.client_fee (tenant_id, company_id, branch_id, customer_id, "
                            "appointment_id, kind, amount) values (kernel.current_tenant(), :c, :b, :cu, :a, :k, :m) "
                            "on conflict do nothing returning *",
                   c=appt.company_id, b=appt.branch_id, cu=appt.customer_id, a=appt.id, k=kind, m=amount)
    if made is not None:
        audit_record(session, "fee", "bookings.appointment", appt.id, {"kind": kind, "amount": amount})
        publish(session, Event("client.fee_added", "bookings.appointment", appt.id, {
            "company_id": appt.company_id, "branch_id": appt.branch_id, "customer_id": appt.customer_id,
            "appointment_id": appt.id, "kind": kind, "amount": amount, "fee_id": made["id"]}))
    return made


def add_fee_lines(session: Session, co: dict[str, Any], settings: BookingSettings, customer_id: UUID,
                  number: int) -> int:
    """Put the client's open fees on the checkout as lines. Needs the business's fee service item (Booking settings);
    without it fees wait. Returns the last line number."""
    if settings.fee_product_id is None:
        return number
    on_bill = {r["fee_id"] for r in raw.many(
        session, "select fee_id from bookings.checkout_line where checkout_id = :c and fee_id is not null",
        c=co["id"])}
    for fee in raw.many(session, "select * from bookings.client_fee where customer_id = :cu and company_id = :c and "
                                 "status = 'open' order by created_at", cu=customer_id, c=co["company_id"]):
        if fee["id"] in on_bill:
            continue
        number += 1
        label = "Late cancellation fee" if fee["kind"] == "late_cancel" else "Missed appointment fee"
        raw.insert(session, "checkout_line", {
            "checkout_id": co["id"], "line_no": number, "kind": "fee", "fee_id": fee["id"],
            "product_id": settings.fee_product_id, "description": label, "quantity": 1, "unit_price": fee["amount"]})
    return number


def mark_charged(session: Session, checkout_id: UUID, rows: list[dict[str, Any]]) -> None:
    for r in rows:
        if r["fee_id"] is not None:
            raw.run(session, "update bookings.client_fee set status = 'charged', checkout_id = :c, updated_at = now() "
                             "where id = :f", c=checkout_id, f=r["fee_id"])


def list_fees(session: Session, *, customer_id: UUID | None = None, status: str | None = "open",
              limit: int = 100) -> list[dict[str, Any]]:
    scopes = access.view_scopes()
    where: list[str] = ["true"]
    params: dict[str, Any] = {"lim": min(limit, 300)}
    if scopes is not None:
        parts = []
        for i, (c, b) in enumerate(scopes):
            params[f"c{i}"], params[f"b{i}"] = c, b
            parts.append(f"(company_id = :c{i} and (cast(:b{i} as uuid) is null or branch_id = :b{i}))")
        where.append("(" + " or ".join(parts or ["false"]) + ")")
    if customer_id:
        where.append("customer_id = :cu")
        params["cu"] = customer_id
    if status:
        where.append("status = :st")
        params["st"] = status
    return raw.many(session, f"select * from bookings.client_fee where {' and '.join(where)} "
                             "order by created_at desc limit :lim", **params)


def waive(session: Session, fee_id: UUID, reason_code_id: UUID | None, note: str | None) -> dict[str, Any]:
    """Do not charge a fee. Needs 'bookings.manage' and a reason; it leaves any open checkout it was on."""
    fee = raw.one(session, "select * from bookings.client_fee where id = :i", i=fee_id)
    if fee is None or not access.can_view(fee["company_id"], fee["branch_id"]):
        raise NotFound("Fee not found")
    current_context().require(BOOKINGS_MANAGE, company_id=fee["company_id"], branch_id=fee["branch_id"])
    if fee["status"] != "open":
        raise ValidationFailed("That fee is already charged or waived")
    check_reason(session, "fee_waive", reason_code_id, note)
    why = raw.one(session, "select label from kernel.reason_code where id = :i", i=reason_code_id)
    raw.run(session, "delete from bookings.checkout_line where fee_id = :f and checkout_id in "
                     "(select id from bookings.checkout where status = 'open')", f=fee_id)
    row = raw.update(session, "client_fee", fee_id, {
        "status": "waived", "waived_reason": f"{why['label'] if why else ''}: {note or ''}"[:300]})
    audit_record(session, "waive_fee", "bookings.client_fee", fee_id, {"amount": Decimal(fee["amount"])})
    return row

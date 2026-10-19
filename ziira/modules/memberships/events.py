"""Events Memberships handles.

Publishes: membership.activated | renewed | paused | resumed | cancelled | expired | plan_changed, package.sold | used |
expiring | expired, checkin.recorded, voucher.sold.
Subscribes: appointment.completed (Bookings: a trainer's earning for the session), customer.paid, invoice.cancelled and
sale.returned (Sales): when money moved for a customer, their membership
invoices are read again so arrears, the late-payment list and the door decision are right at once; customer.paid also
earns loyalty points.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.memberships.services import common, dues, trainers, values
from ziira.sdk import Event, Session, subscribe


def _has_runs(session: Session, customer_id: UUID) -> bool:
    return session.execute(text("select 1 from memberships.invoice_run where customer_id = :c and status = 'issued' "
                                "and settle_state = 'open' limit 1"), {"c": str(customer_id)}).first() is not None


@subscribe("customer.paid")
def on_customer_paid(session: Session, event: Event) -> None:
    customer_id = event.payload.get("customer_id")
    if customer_id is None:
        return
    company_id = event.payload.get("company_id")
    if company_id is not None and event.payload.get("amount") is not None:
        values.earn_points(session, company_id=company_id, customer_id=customer_id,
                           amount_paid=event.payload["amount"], source_type="receipt", source_id=event.aggregate_id)
    if _has_runs(session, customer_id):
        dues.refresh_payer(session, customer_id)


@subscribe("invoice.cancelled")
def on_invoice_cancelled(session: Session, event: Event) -> None:
    customer_id = event.payload.get("customer_id")
    if customer_id is not None and _has_runs(session, customer_id):
        dues.refresh_payer(session, customer_id)


@subscribe("sale.returned")
def on_sale_returned(session: Session, event: Event) -> None:
    customer_id = event.payload.get("customer_id")
    if customer_id is not None and _has_runs(session, customer_id):
        dues.refresh_payer(session, customer_id)


@subscribe("appointment.completed")
def on_appointment_completed(session: Session, event: Event) -> None:
    """A personal-training session was delivered: write what each trainer in it earns (only trainers with a rate)."""
    p = event.payload
    if not p.get("resource_ids") or p.get("company_id") is None:
        return
    value = sum((Decimal(str(x.get("unit_price") or 0)) * Decimal(str(x.get("quantity") or 1))
                 for x in p.get("lines") or []), Decimal(0))
    today = common.today(session, p["company_id"])
    refs: list[str | None] = [r for r in (str(p.get("product_id") or ""), str(p.get("service") or "").lower()) if r]
    for trainer in p["resource_ids"]:
        for ref in refs or [None]:
            row = trainers.record_session(
                session, company_id=p["company_id"], branch_id=p.get("branch_id"), trainer_ref=trainer,
                customer_id=p.get("customer_id"), service_ref=ref, source_type="appointment",
                source_id=event.aggregate_id, session_value=value, earned_on=today)
            if row is not None:
                break


# --------------------------------------------------------------------------- classes (Bookings' group sessions)
CLASS_SOURCE = "class_attendance"


def _class_ref(session: Session, appointment_id: object) -> str:
    """The name members' packages and plans list for this class (lower case); 'class' when it cannot be read."""
    if not common.unit_enabled(session, "bookings"):
        return "class"
    try:
        with session.begin_nested():
            from ziira.modules.bookings.public import get_session_view

            return str(get_session_view(session, appointment_id).name).strip().lower() or "class"  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - a class whose name cannot be read is still a class
        return "class"


def _covers_class_free(session: Session, customer_id: object) -> bool:
    """True when the customer's active membership includes classes at no credit."""
    return session.execute(text(
        "select 1 from memberships.member m join memberships.plan p on p.id = m.plan_id where m.customer_id = :c "
        "and m.status = 'active' and p.classes_mode = 'included' limit 1"), {"c": str(customer_id)}).first() is not None


def _spend_for_class(session: Session, event: Event, *, why: str) -> None:
    from ziira.modules.memberships.repository import memberships_repo as repo
    from ziira.modules.memberships.services import credits
    from ziira.sdk import ValidationFailed, flag_for_review

    p = event.payload
    customer_id, attendee_id = p.get("customer_id"), p.get("attendee_id")
    if customer_id is None or attendee_id is None or _covers_class_free(session, customer_id):
        return
    if repo.one(session, "select 1 as x from memberships.member where customer_id = :c and status = 'active' "
                         "union all select 1 from memberships.sold_package where customer_id = :c and "
                         "status = 'active' limit 1", c=customer_id) is None:
        return                                                      # nothing to spend: the desk takes a drop-in fee
    try:
        with session.begin_nested():
            credits.consume(session, customer_id=customer_id, service_ref=_class_ref(session, event.aggregate_id),
                            quantity=Decimal(1), source_type=CLASS_SOURCE, source_id=attendee_id)
    except ValidationFailed as error:
        flag_for_review(session, unit="memberships", kind="class_credit", severity="low",
                        company_id=p.get("company_id"), branch_id=p.get("branch_id"),
                        message=f"A class credit could not be used ({why}): {error}",
                        dedupe_key=f"memberships-class:{attendee_id}:{why}")


def _give_back_for_class(session: Session, event: Event) -> None:
    from ziira.modules.memberships.services import credits

    if event.payload.get("attendee_id") is not None:
        credits.release(session, source_type=CLASS_SOURCE, source_id=event.payload["attendee_id"])


@subscribe("class.attendee_attended")
def on_class_attended(session: Session, event: Event) -> None:
    """A class pack (or the plan's credits) is used up on attendance, once per person per class."""
    _spend_for_class(session, event, why="attended")


@subscribe("class.attendee_no_show")
def on_class_no_show(session: Session, event: Event) -> None:
    from ziira.modules.memberships.repository import memberships_repo as repo

    company_id = event.payload.get("company_id")
    if company_id is not None and repo.get_settings(session, company_id)["no_show_consumes"]:
        _spend_for_class(session, event, why="no_show")


@subscribe("class.attendee_reset")
def on_class_reset(session: Session, event: Event) -> None:
    """A mark was undone (attended or no-show back to booked): the credit comes back."""
    _give_back_for_class(session, event)


@subscribe("class.attendee_cancelled")
def on_class_cancelled(session: Session, event: Event) -> None:
    """Cancelled inside the late window: the credit is spent (when the company says so). A class the business called off
    gives everything back."""
    from ziira.modules.memberships.repository import memberships_repo as repo

    p = event.payload
    if p.get("session_cancelled"):
        _give_back_for_class(session, event)
        return
    company_id = p.get("company_id")
    if p.get("late") and company_id is not None and repo.get_settings(session, company_id)["late_cancel_consumes"]:
        _spend_for_class(session, event, why="late_cancel")

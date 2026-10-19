"""HTTP endpoints for checkout, the front desk board, visits, group sessions, recalls, fees, commission, tips, chair
rental, closed days, the client card, the day-end summary and a pack's first-run steps. Routes only convert HTTP to
service calls."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from ziira.modules.bookings.api import outputs
from ziira.modules.bookings.api import schemas as sc
from ziira.modules.bookings.api import schemas_wave2 as w2
from ziira.modules.bookings.api.deps import CHECKOUT, MANAGE, REPORTS, SETUP, VIEW
from ziira.modules.bookings.domain import checkout as dom
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.services import (
    access,
    appointments,
    checkout,
    clients,
    closed_days,
    commission,
    dayend,
    deposits,
    fees,
    frontdesk,
    pack_steps,
    pricing,
    recalls,
    rentals,
    sessions,
    tenders,
)
from ziira.modules.bookings.services.common import zone
from ziira.sdk import (
    DB_SESSION,
    NotFound,
    Session,
    page_limit,
    page_offset,
)

router = APIRouter()
public_router = APIRouter()
CREATED = status.HTTP_201_CREATED
NO_CONTENT = status.HTTP_204_NO_CONTENT


# =========================================================================== front desk board, walk-ins, visits
@router.get("/front-desk/board", response_model=w2.FrontDeskBoardOut, dependencies=VIEW)
def get_board(branch_id: UUID, session: Session = DB_SESSION) -> object:
    """The branch right now: who is free, who is with a client, who is next, who is waiting and who is ready to pay."""
    return frontdesk.board(session, branch_id)


@router.post("/front-desk/walk-in", response_model=w2.WalkInOut, status_code=CREATED, dependencies=MANAGE)
def post_walk_in_smart(body: sc.WalkInIn, session: Session = DB_SESSION) -> object:
    """A walk-in: starts now when someone is free, else joins the queue at the earliest time the calendar allows."""
    appt, wait = frontdesk.walk_in(session, **body.model_dump())
    return w2.WalkInOut(appointment=outputs.one_appointment(session, appt), wait_minutes=wait)


@router.post("/visits", response_model=w2.VisitOut, status_code=CREATED, dependencies=MANAGE)
def post_visit(body: w2.VisitIn, session: Session = DB_SESSION) -> object:
    """Book several services for one client in sequence (each may be done by someone different)."""
    data = body.model_dump()
    items = [{"offer_id": i["offer_id"], "resource_ids": i["resource_ids"], "price_variant": i["price_variant"]}
             for i in data.pop("items")]
    payer = {k: data.pop(k) for k in ("payer_customer_id", "payer_member_no", "preauth_ref", "copay_amount")}
    legs = frontdesk.create_visit(session, items=items, payer={k: v for k, v in payer.items() if v is not None} or None,
                                  **data)
    return w2.VisitOut(visit_id=legs[0].visit_id, appointments=outputs.appointments_out(session, legs))  # type: ignore[arg-type]


@router.get("/visits/{visit_id}", response_model=w2.VisitOut, dependencies=VIEW)
def get_visit(visit_id: UUID, session: Session = DB_SESSION) -> object:
    legs = frontdesk.visit_appointments(session, visit_id)
    if not legs:
        raise NotFound("Visit not found")
    return w2.VisitOut(visit_id=visit_id, appointments=outputs.appointments_out(session, legs, with_warnings=True))


@router.post("/appointments/{appointment_id}/deposit", response_model=sc.AppointmentOut, dependencies=CHECKOUT)
def post_deposit(appointment_id: UUID, body: w2.DepositIn, session: Session = DB_SESSION) -> object:
    """The client paid a deposit: it is kept on their account until the checkout uses it."""
    return outputs.one_appointment(session, deposits.record_deposit(
        session, appointment_id, amount=body.amount, method=body.method, reference=body.reference))


@router.post("/appointments/{appointment_id}/deposit-reminder", status_code=NO_CONTENT, dependencies=MANAGE)
def post_deposit_reminder(appointment_id: UUID, session: Session = DB_SESSION) -> None:
    """Queue a message asking the client for the deposit."""
    appt = appointments.get_appointment(session, appointment_id)
    deposits.remind(session, appt)


@router.post("/appointments/{appointment_id}/claim", response_model=sc.AppointmentOut, dependencies=MANAGE)
def post_open_claim(appointment_id: UUID, body: w2.ClaimOpenIn, session: Session = DB_SESSION) -> object:
    """Bill an insurer or scheme for this appointment: opens a claim in Claims (when that unit is on)."""
    from ziira.modules.bookings.services import claims_seam

    return outputs.one_appointment(session, claims_seam.open_claim(
        session, appointment_id, payer_id=body.payer_id, policy_number=body.policy_number,
        member_number=body.member_number, preauth_ref=body.preauth_ref))


# =========================================================================== checkout
@router.get("/checkouts", response_model=list[w2.CheckoutListOut], dependencies=CHECKOUT)
def list_checkouts(branch_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                   customer_id: UUID | None = None, owing: bool = False, day: date | None = None,
                   limit: int = page_limit(50), offset: int = page_offset(),
                   session: Session = DB_SESSION) -> object:
    return checkout.list_checkouts(session, branch_id=branch_id, status=status_, customer_id=customer_id, owing=owing,
                                   day=day, limit=limit, offset=offset)


def _checkout_out(view: dict[str, Any]) -> w2.CheckoutOut:
    totals = view["totals"]
    shares = view.get("line_shares") or []
    lines = []
    for i, r in enumerate(view["lines"]):
        line = dom.Line(r["quantity"], r["unit_price"], r["discount"], r["credit_quantity"])
        share = shares[i] if i < len(shares) else Decimal(0)
        lines.append(w2.CheckoutLineOut.model_validate({**r, "order_discount_share": share,
                                                         "net": dom.line_net(line) - share}))
    return w2.CheckoutOut(
        **{k: view[k] for k in ("id", "company_id", "branch_id", "number", "customer_id", "client_name", "visit_id",
                                "status", "note", "discount_kind", "discount_value", "discount_reason_id",
                                "discount_note", "payer_customer_id", "copay_amount", "preauth_ref", "total",
                                "paid_total", "credit_total", "tip_total", "invoice_id", "invoice_number",
                                "payer_invoice_id", "payer_invoice_number", "completed_at", "created_at", "warnings",
                                "deposit_held", "credit_on_account")},
        lines=lines, payments=[w2.CheckoutPaymentOut.model_validate(p) for p in view["payments"]],
        tips=[w2.CheckoutTipOut.model_validate(t) for t in view["tips"]],
        totals=w2.CheckoutTotalsOut(subtotal=totals.subtotal, line_discounts=totals.line_discounts,
                                    order_discount=totals.order_discount, credit_value=totals.credit_value,
                                    total=totals.total))


@router.post("/checkouts", response_model=w2.CheckoutOut, status_code=CREATED, dependencies=CHECKOUT)
def post_checkout(body: w2.CheckoutOpenIn, session: Session = DB_SESSION) -> object:
    """Open the bill for a visit (or for a sale of products over the desk). Asking again returns the open one."""
    return _checkout_out(checkout.open_checkout(session, **body.model_dump()))


@router.get("/checkouts/{checkout_id}", response_model=w2.CheckoutOut, dependencies=CHECKOUT)
def get_checkout(checkout_id: UUID, session: Session = DB_SESSION) -> object:
    return _checkout_out(checkout.get_checkout(session, checkout_id))


@router.put("/checkouts/{checkout_id}", response_model=w2.CheckoutOut, dependencies=CHECKOUT)
def put_checkout(checkout_id: UUID, body: w2.CheckoutDraftIn, session: Session = DB_SESSION) -> object:
    """Save what is on the desk's screen: the lines, the discount and the payer's share. Nothing is billed yet."""
    data = body.model_dump()
    lines = [checkout.LineIn(**line) for line in data.pop("lines")]
    return _checkout_out(checkout.save_draft(session, checkout_id, lines=lines, **data))


@router.put("/checkouts/{checkout_id}/customer", response_model=w2.CheckoutOut, dependencies=CHECKOUT)
def put_checkout_customer(checkout_id: UUID, body: w2.CheckoutCustomerIn, session: Session = DB_SESSION) -> object:
    return _checkout_out(checkout.set_customer(session, checkout_id, body.customer_id))


@router.post("/checkouts/{checkout_id}/complete", response_model=w2.CheckoutOut, dependencies=CHECKOUT)
def post_checkout_complete(checkout_id: UUID, body: w2.CheckoutCompleteIn, session: Session = DB_SESSION) -> object:
    """Bill the visit: invoice, payments (split as needed), tips and commission, all or nothing. Safe to repeat."""
    return _checkout_out(checkout.complete(
        session, checkout_id, payments=[checkout.PaymentIn(**p.model_dump()) for p in body.payments],
        tips=[checkout.TipIn(**t.model_dump()) for t in body.tips],
        tender_uses=[checkout.TenderIn(**t.model_dump()) for t in body.tenders], use_deposit=body.use_deposit))


@router.post("/checkouts/{checkout_id}/tips", response_model=w2.CheckoutOut, dependencies=CHECKOUT)
def post_checkout_tip(checkout_id: UUID, body: w2.CheckoutTipIn, session: Session = DB_SESSION) -> object:
    """A tip added after the bill was paid."""
    return _checkout_out(checkout.add_tip_later(session, checkout_id, checkout.TipIn(**body.model_dump())))


@router.post("/checkouts/{checkout_id}/discard", response_model=w2.CheckoutOut, dependencies=CHECKOUT)
def post_checkout_discard(checkout_id: UUID, body: w2.CheckoutDiscardIn, session: Session = DB_SESSION) -> object:
    return _checkout_out(checkout.discard(session, checkout_id, body.reason))


@router.get("/checkout/tenders", response_model=list[w2.TenderKindOut], dependencies=CHECKOUT)
def get_tender_kinds(session: Session = DB_SESSION) -> object:
    """Other ways to pay that this business has (a gift voucher, points), from the units that offer them."""
    return tenders.available(session)


@router.get("/checkout/tenders/{kind}/balance", response_model=w2.TenderBalanceOut, dependencies=CHECKOUT)
def get_tender_balance(kind: str, customer_id: UUID | None = None,
                       code: str | None = Query(default=None, max_length=80),
                       session: Session = DB_SESSION) -> object:
    found = tenders.balance(session, kind, customer_id=customer_id, code=code)
    if found is None:
        raise NotFound("That code is not valid, or has nothing left")
    return w2.TenderBalanceOut(kind=kind, available=found.available, description=found.description)


@router.get("/retail-items", response_model=list[sc.ServiceItemOut], dependencies=CHECKOUT)
def get_retail_items(company_id: UUID, branch_id: UUID | None = None,
                     search: str | None = Query(default=None, max_length=100),
                     session: Session = DB_SESSION) -> object:
    """Products the desk can add to a bill (not service items), with their prices."""
    from ziira.modules.products.public import sellable_products, selling_prices

    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    found = [p for p in sellable_products(session, company_id, search, 30) if p.product_type != "service"]
    prices = selling_prices(session, company_id, branch_id, {p.id for p in found})
    return [sc.ServiceItemOut(id=p.id, sku=p.sku, name=p.name, price=prices.get(p.id)) for p in found]


@router.get("/clients/search", response_model=list[sc.ServiceItemOut], dependencies=CHECKOUT)
def search_clients(company_id: UUID, q: str = Query(min_length=2, max_length=60),
                   session: Session = DB_SESSION) -> object:
    """Find a client by name or phone (id, code as `sku`, name)."""
    from ziira.modules.crm.public import search_customers

    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    return [sc.ServiceItemOut(id=c.id, sku=c.code, name=f"{c.name}{' · ' + c.phone if c.phone else ''}")
            for c in search_customers(session, company_id, q, 15)]


@router.post("/clients", response_model=sc.ServiceItemOut, status_code=CREATED, dependencies=CHECKOUT)
def post_client(company_id: UUID, name: str = Query(min_length=1, max_length=200),
                phone: str | None = Query(default=None, max_length=30),
                email: str | None = Query(default=None, max_length=200),
                session: Session = DB_SESSION) -> object:
    """Add a client at the desk (found again by phone or email instead of duplicated)."""
    from ziira.modules.bookings.services import delegate
    from ziira.modules.crm.public import match_or_create_customer

    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    branches = raw.many(session, "select id from kernel.branch where company_id = :c", c=company_id)
    with delegate.front_desk_rights(company_id, branches[0]["id"] if branches else company_id):
        customer, _ = match_or_create_customer(session, company_id, name=name, phone=phone, email=email)
    return sc.ServiceItemOut(id=customer.id, sku=customer.code, name=customer.name)


# =========================================================================== price variants
@router.put("/offers/{offer_id}/variants", response_model=list[sc.PriceVariantOut], dependencies=SETUP)
def put_variants(offer_id: UUID, body: w2.PriceVariantsIn, session: Session = DB_SESSION) -> object:
    """Replace a service's prices by staff level or variant."""
    return pricing.set_variants(session, offer_id, [v.model_dump() for v in body.variants])


# =========================================================================== group sessions
def _session_out(session: Session, appt: Any) -> w2.ClassSessionOut:
    c = sessions.counts(session, appt)
    offer = repo.get_offer(session, appt.offer_id)
    return w2.ClassSessionOut(
        id=appt.id, branch_id=appt.branch_id, number=appt.number, offer_id=appt.offer_id,
        name=offer.name if offer else "", status=appt.status, starts_at=appt.starts_at, ends_at=appt.ends_at,
        capacity=appt.capacity, booked=c["booked"], held=c["held"], waiting=c["waiting"], free=c["free"],
        resource_ids=repo.appointment_resources(session, {appt.id}).get(appt.id, []))


@router.get("/sessions", response_model=list[w2.ClassSessionOut], dependencies=VIEW)
def get_sessions(branch_id: UUID | None = None, start: datetime | None = None, end: datetime | None = None,
                 offer_id: UUID | None = None, include_cancelled: bool = False,
                 session: Session = DB_SESSION) -> object:
    """Group sessions (classes) in a stretch of time with their places."""
    return [_session_out(session, a) for a in sessions.list_sessions(
        session, branch_id=branch_id, start=start, end=end, offer_id=offer_id, include_cancelled=include_cancelled)]


@router.post("/sessions", response_model=w2.ClassSessionSeriesOut, status_code=CREATED, dependencies=MANAGE)
def post_session(body: w2.ClassSessionIn, session: Session = DB_SESSION) -> object:
    """Schedule one class, or the same class each week (`weeks`); closed days and clashes are skipped and listed."""
    if body.weeks:
        out = sessions.create_weekly(session, offer_id=body.offer_id, starts_at=body.starts_at, weeks=body.weeks,
                                     branch_id=body.branch_id, resource_ids=body.resource_ids)
        made = out["created"]
        if body.capacity:
            for a in made:
                sessions.set_capacity(session, a.id, body.capacity)
        return w2.ClassSessionSeriesOut(created=[_session_out(session, a) for a in made], skipped=[
            w2.ClassSessionSkippedOut(starts_at=c["starts_at"], problem=c["problem"]) for c in out["conflicts"]])
    one = sessions.create_session(session, offer_id=body.offer_id, starts_at=body.starts_at, branch_id=body.branch_id,
                                  resource_ids=body.resource_ids, note=body.note, capacity=body.capacity)
    return w2.ClassSessionSeriesOut(created=[_session_out(session, one)], skipped=[])


@router.get("/sessions/{session_id}", response_model=w2.ClassSessionOut, dependencies=VIEW)
def get_session(session_id: UUID, session: Session = DB_SESSION) -> object:
    return _session_out(session, sessions.get_session(session, session_id))


@router.get("/sessions/{session_id}/roster", response_model=list[sc.AttendeeOut], dependencies=VIEW)
def get_roster(session_id: UUID, session: Session = DB_SESSION) -> object:
    return sessions.roster(session, session_id)


@router.get("/sessions/{session_id}/waitlist", response_model=list[w2.ClassSessionWaitingOut], dependencies=VIEW)
def get_session_waitlist(session_id: UUID, session: Session = DB_SESSION) -> object:
    return [w2.ClassSessionWaitingOut(id=r["id"], customer_id=r["customer_id"], name=r["name"], phone=r["phone"],
                                 status=r["status"], joined_at=r["created_at"], confirm_by=r["confirm_by"])
            for r in sessions.waitlist_of(session, session_id)]


@router.post("/sessions/{session_id}/book", response_model=w2.ClassSessionBookedOut, status_code=CREATED,
             dependencies=MANAGE)
def post_session_book(session_id: UUID, body: w2.ClassSessionBookIn, session: Session = DB_SESSION) -> object:
    """Put someone on the class, or on its waitlist when it is full."""
    done = sessions.book_attendee(session, session_id, **body.model_dump())
    return w2.ClassSessionBookedOut(status="booked" if done.status == "booked" else "waitlisted",
                               attendee_id=done.attendee.id if done.attendee else None,
                               waitlist_id=done.waitlist["id"] if done.waitlist else None, position=done.position)


@router.post("/sessions/attendees/{attendee_id}/cancel", response_model=sc.AttendeeOut, dependencies=MANAGE)
def post_attendee_cancel(attendee_id: UUID, session: Session = DB_SESSION) -> object:
    return sessions.cancel_attendee(session, attendee_id)


@router.post("/sessions/waitlist/{waitlist_id}/confirm", response_model=w2.ClassSessionBookedOut, dependencies=MANAGE)
def post_waitlist_confirm(waitlist_id: UUID, session: Session = DB_SESSION) -> object:
    done = sessions.confirm_offer(session, waitlist_id)
    return w2.ClassSessionBookedOut(status="booked", attendee_id=done.attendee.id if done.attendee else None,
                               waitlist_id=waitlist_id, position=None)


@router.post("/sessions/waitlist/{waitlist_id}/leave", status_code=NO_CONTENT, dependencies=MANAGE)
def post_waitlist_leave(waitlist_id: UUID, session: Session = DB_SESSION) -> None:
    sessions.leave_waitlist(session, waitlist_id)


@router.put("/sessions/{session_id}/capacity", response_model=w2.ClassSessionOut, dependencies=MANAGE)
def put_session_capacity(session_id: UUID, body: w2.ClassSessionCapacityIn, session: Session = DB_SESSION) -> object:
    return _session_out(session, sessions.set_capacity(session, session_id, body.capacity))


@router.put("/sessions/{session_id}/instructor", response_model=w2.ClassSessionOut, dependencies=MANAGE)
def put_session_instructor(session_id: UUID, body: w2.ClassSessionResourceIn, session: Session = DB_SESSION) -> object:
    """Another instructor or room takes the class."""
    return _session_out(session, sessions.substitute_resource(session, session_id, body.resource_id))


@router.post("/sessions/{session_id}/cancel", response_model=w2.ClassSessionOut, dependencies=MANAGE)
def post_session_cancel(session_id: UUID, body: w2.ClassSessionCancelIn, session: Session = DB_SESSION) -> object:
    return _session_out(session, sessions.cancel_session(session, session_id, reason_code_id=body.reason_code_id,
                                                         note=body.note))


# =========================================================================== closed days
@router.get("/closed-days", response_model=list[w2.ClosedDayOut], dependencies=VIEW)
def get_closed_days(company_id: UUID, start: date | None = None, end: date | None = None,
                    session: Session = DB_SESSION) -> object:
    return closed_days.list_closed(session, company_id, start, end)


@router.post("/closed-days", response_model=w2.ClosedDayOut, status_code=CREATED, dependencies=SETUP)
def post_closed_day(body: w2.ClosedDayIn, session: Session = DB_SESSION) -> object:
    return closed_days.close_day(session, body.company_id, body.day, branch_id=body.branch_id, label=body.label)


@router.delete("/closed-days/{closed_id}", status_code=NO_CONTENT, dependencies=SETUP)
def delete_closed_day(closed_id: UUID, session: Session = DB_SESSION) -> None:
    closed_days.reopen_day(session, closed_id)


# =========================================================================== recalls and fees
@router.get("/recalls", response_model=list[w2.RecallOut], dependencies=VIEW)
def get_recalls(company_id: UUID, branch_id: UUID | None = None, limit: int = page_limit(200),
                session: Session = DB_SESSION) -> object:
    """Clients who are due for their service again and have nothing booked."""
    return recalls.due_list(session, company_id, branch_id=branch_id, limit=limit)


@router.post("/recalls/send", response_model=w2.RecallLogOut, status_code=CREATED, dependencies=MANAGE)
def post_recall_send(body: w2.RecallSendIn, session: Session = DB_SESSION) -> object:
    """Message the client now (once per visit)."""
    return recalls.send_recall(session, body.company_id, body.customer_id, body.offer_id)


@router.post("/recalls/outcome", response_model=w2.RecallLogOut, status_code=CREATED, dependencies=MANAGE)
def post_recall_outcome(body: w2.RecallOutcomeIn, session: Session = DB_SESSION) -> object:
    """Note that the client was phoned, declined, was snoozed until a date, or booked."""
    return recalls.log_outcome(session, body.company_id, body.customer_id, body.offer_id, body.outcome,
                               snooze_until=body.snooze_until, note=body.note)


@router.get("/fees", response_model=list[w2.ClientFeeOut], dependencies=VIEW)
def get_fees(customer_id: UUID | None = None, status_: str | None = Query(default="open", alias="status"),
             session: Session = DB_SESSION) -> object:
    """Late-cancellation and missed-appointment fees waiting for the client's next bill."""
    return fees.list_fees(session, customer_id=customer_id, status=status_)


@router.post("/fees/{fee_id}/waive", response_model=w2.ClientFeeOut, dependencies=MANAGE)
def post_fee_waive(fee_id: UUID, body: w2.FeeWaiveIn, session: Session = DB_SESSION) -> object:
    return fees.waive(session, fee_id, body.reason_code_id, body.note)


# =========================================================================== commission and tips
@router.get("/commission/rules", response_model=list[w2.CommissionRuleOut], dependencies=VIEW)
def get_commission_rules(company_id: UUID, include_inactive: bool = False, session: Session = DB_SESSION) -> object:
    return commission.list_rules(session, company_id, include_inactive=include_inactive)


@router.post("/commission/rules", response_model=w2.CommissionRuleOut, status_code=CREATED, dependencies=SETUP)
def post_commission_rule(body: w2.CommissionRuleIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    return commission.create_rule(session, data.pop("company_id"), **data)


@router.patch("/commission/rules/{rule_id}", response_model=w2.CommissionRuleOut, dependencies=SETUP)
def patch_commission_rule(rule_id: UUID, body: w2.CommissionRuleUpdate, session: Session = DB_SESSION) -> object:
    return commission.update_rule(session, rule_id, **body.model_dump(exclude_unset=True))


@router.get("/commission/report", response_model=list[w2.CommissionPersonOut], dependencies=REPORTS)
def get_commission_report(company_id: UUID, start: date, end: date, branch_id: UUID | None = None,
                          session: Session = DB_SESSION) -> object:
    """Per person for a period: services and products done, commission earned, tips (kept apart)."""
    return commission.report(session, company_id, start, end, branch_id=branch_id)


@router.post("/commission/checkouts/{checkout_id}/reverse", response_model=w2.TipsPaidOut, dependencies=REPORTS)
def post_commission_reverse(checkout_id: UUID, body: w2.CommissionReverseIn, session: Session = DB_SESSION) -> object:
    """Take back the commission of a checkout whose bill was reversed (adds negative lines)."""
    return w2.TipsPaidOut(amount=Decimal(commission.reverse_checkout(session, checkout_id, body.reason)))


@router.get("/tips/owed", response_model=list[w2.TipsOwedOut], dependencies=REPORTS)
def get_tips_owed(company_id: UUID, branch_id: UUID | None = None, session: Session = DB_SESSION) -> object:
    return commission.tips_owed(session, company_id, branch_id)


@router.post("/tips/pay-out", response_model=w2.TipsPaidOut, dependencies=REPORTS)
def post_tips_pay_out(body: w2.TipsPayOutIn, session: Session = DB_SESSION) -> object:
    """Record that the tips held for a person were handed over."""
    return w2.TipsPaidOut(amount=commission.pay_out_tips(session, body.company_id, body.resource_id, body.branch_id))


# =========================================================================== chair rental
@router.get("/rentals", response_model=list[w2.RentalOut], dependencies=VIEW)
def get_rentals(company_id: UUID, active_only: bool = False, session: Session = DB_SESSION) -> object:
    return rentals.list_rentals(session, company_id, active_only=active_only)


@router.post("/rentals", response_model=w2.RentalOut, status_code=CREATED, dependencies=SETUP)
def post_rental(body: w2.RentalIn, session: Session = DB_SESSION) -> object:
    return rentals.create_rental(session, **body.model_dump())


@router.post("/rentals/{rental_id}/end", response_model=w2.RentalOut, dependencies=SETUP)
def post_rental_end(rental_id: UUID, body: w2.RentalEndIn, session: Session = DB_SESSION) -> object:
    return rentals.end_rental(session, rental_id, body.end_date)


# =========================================================================== reports, client card, rota, pack steps
@router.get("/day-end", response_model=w2.DayEndOut, dependencies=REPORTS)
def get_day_end(branch_id: UUID, day: date | None = None, session: Session = DB_SESSION) -> object:
    """What the branch took and did on a day (default today)."""
    from ziira.sdk import company_today

    found = raw.one(session, "select company_id from kernel.branch where id = :b", b=branch_id)
    if found is None:
        raise NotFound("Branch not found")
    return dayend.day_end(session, branch_id, day or company_today(session, found["company_id"]))


@router.get("/clients/{customer_id}/card", response_model=w2.ClientCardOut, dependencies=VIEW)
def get_client_card(customer_id: UUID, company_id: UUID, session: Session = DB_SESSION) -> object:
    """The client's card: history, usual staff, fees, credit and the business's own fields."""
    return clients.client_card(session, company_id, customer_id)


@router.get("/clients/{customer_id}/fields", response_model=dict[str, object], dependencies=VIEW)
def get_client_fields(customer_id: UUID, session: Session = DB_SESSION) -> object:
    """The values on a client card."""
    from ziira.sdk import custom_fields

    return custom_fields.read_values(session, clients.ENTITY, customer_id)


@router.put("/clients/{customer_id}/fields", response_model=dict[str, object], dependencies=MANAGE)
def put_client_fields(customer_id: UUID, company_id: UUID, body: w2.ClientFieldsIn,
                      session: Session = DB_SESSION) -> object:
    """Change some fields on a client card (preferred stylist, allergy note, formula, patch-test date ...)."""
    return clients.save_fields(session, company_id, customer_id, body.values)


@router.get("/rota", response_model=list[w2.RotaPersonOut], dependencies=VIEW)
def get_rota(branch_id: UUID, week_start: date | None = None, session: Session = DB_SESSION) -> object:
    """Who works when: the weekly hours of each person and their time off in a week."""
    rows = [r for r in repo.list_resources(session, access.view_scopes(), branch_id=branch_id, active_only=True)
            if r.kind in ("staff", "chair")]
    if not rows:
        return []
    zn = zone(session, rows[0].company_id)
    first = week_start or (datetime.now(zn).date() - timedelta(days=datetime.now(zn).date().weekday()))
    start = datetime.combine(first, datetime.min.time(), tzinfo=zn)
    end = start + timedelta(days=7)
    hours = repo.hours_of(session, {r.id for r in rows})
    off = repo.time_off_of(session, {r.id for r in rows}, start, end)
    out = []
    for r in rows:
        days = []
        for d in range(7):
            days.append(w2.RotaDayOut(weekday=d, windows=[f"{h.start_time:%H:%M}-{h.end_time:%H:%M}"
                                                         for h in hours.get(r.id, []) if h.weekday == d]))
        out.append(w2.RotaPersonOut(
            resource_id=r.id, name=r.name, kind=r.kind, level=r.level, days=days,
            time_off=[f"{t.starts_at.astimezone(zn):%a %d %b %H:%M} to {t.ends_at.astimezone(zn):%a %d %b %H:%M}"
                      + (f" ({t.reason})" if t.reason else "") for t in off.get(r.id, [])]))
    return out


@router.get("/pack-steps", response_model=list[w2.PackStepOut], dependencies=VIEW)
def get_pack_steps(company_id: UUID, session: Session = DB_SESSION) -> object:
    """The first-run checklist an industry pack gave this business (ticks itself)."""
    return pack_steps.steps_for(session, company_id)


@router.put("/pack-steps/visibility", status_code=NO_CONTENT, dependencies=SETUP)
def put_pack_steps_visibility(body: w2.PackStepsHideIn, session: Session = DB_SESSION) -> None:
    pack_steps.hide(session, body.company_id, body.hidden)


@router.get("/sample-data", response_model=dict[str, int], dependencies=VIEW)
def get_sample_data(company_id: UUID, session: Session = DB_SESSION) -> object:
    """What sample data this business has (empty: none)."""
    from ziira.modules.bookings.services import sample_data

    return sample_data.status(session, company_id)


@router.post("/sample-data", response_model=dict[str, int], status_code=CREATED, dependencies=SETUP)
def post_sample_data(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Make a believable week of sample clients and visits (no invoices, no money). Once."""
    from ziira.modules.bookings.services import sample_data

    return sample_data.create(session, company_id)


@router.delete("/sample-data", response_model=dict[str, int], dependencies=SETUP)
def delete_sample_data(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Remove the sample appointments (the sample clients stay in Customers)."""
    from ziira.modules.bookings.services import sample_data

    return sample_data.remove(session, company_id)

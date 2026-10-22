"""Use cases: ring up a sale, void it, look sales up.

One sale is one transaction: the sale and its lines, the payments (through Payments), the stock leaving (Inventory
reacts to `sale.posted` inside the same transaction) and the books (Finance does the same). If any of them refuses, the
whole sale is refused and nothing is half done.

Selling online is strict: the till must be open, prices come from the price list, and anything that is not the list
price needs the right to override and a reason. A sale made offline already happened - the customer has paid and gone -
so the same sale arriving later is never refused for business reasons: it is recorded and anything that does not add up
(a price that changed meanwhile, stock that was not there, an unexplained discount) goes to the exceptions inbox.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from ziira.modules.inventory.public import posted_cost
from ziira.modules.payments.public import account_for_method, day_is_locked, record_payment, reverse_payment
from ziira.modules.pos.domain import sales as rules
from ziira.modules.pos.permissions import PRICE_OVERRIDE, SALES_SELL, SALES_VOID
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import Sale, SaleLine, SalePayment
from ziira.modules.pos.services import access, credit, devices, invoices, tills
from ziira.modules.products.public import ProductView, find_product, selling_prices
from ziira.sdk import (
    Conflict,
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_reason,
    current_context,
    flag_for_review,
    publish,
)

PRICE_OVERRIDE_REASONS = "price_override"
VOID_REASONS = "void"


@dataclass(frozen=True)
class LineIn:
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal | None = None          # None: the list price
    discount: Decimal = Decimal(0)             # money off the whole line
    reason_code_id: UUID | None = None         # why the price or discount differs from the list
    batch_id: UUID | None = None
    reference: str | None = None               # a note typed at the till for a product that asks for one


@dataclass(frozen=True)
class PaymentIn:
    method: str
    amount: Decimal
    external_ref: str | None = None            # mobile money code, card slip number
    payment_account_id: UUID | None = None     # default: the branch's account for the method


@dataclass
class SaleView:
    sale: Sale
    lines: list[SaleLine]
    payments: list[SalePayment]
    replayed: bool = False
    change: Decimal = Decimal(0)
    warnings: list[str] = field(default_factory=list)


def _view(session: Session, sale: Sale, **extra: object) -> SaleView:
    return SaleView(sale, pos_repo.lines_of(session, sale.id), pos_repo.payments_of(session, sale.id),
                    **extra)  # type: ignore[arg-type]


def _can_see(session: Session, sale: Sale) -> bool:
    scopes = access.sale_scopes()
    if scopes is None:
        return True
    return any((c is None or c == sale.company_id) and (b is None or b == sale.branch_id) for c, b in scopes)


def get_sale(session: Session, sale_id: UUID) -> SaleView:
    sale = pos_repo.get_sale(session, sale_id)
    if sale is None or not _can_see(session, sale):
        raise NotFound("Sale not found")
    return _view(session, sale)


def list_sales(session: Session, *, branch_id: UUID | None = None, business_date: date | None = None,
               status: str | None = None, till_session_id: UUID | None = None, number: str | None = None,
               limit: int = 50, offset: int = 0) -> list[Sale]:
    return pos_repo.list_sales(session, access.sale_scopes(), branch_id=branch_id, business_date=business_date,
                               status=status, till_session_id=till_session_id,
                               number=number.strip().upper() if number else None, limit=min(limit, 200),
                               offset=offset)


def _load_products(session: Session, lines: list[LineIn], company_id: UUID, *,
                   offline: bool) -> dict[UUID, ProductView]:
    found: dict[UUID, ProductView] = {}
    for line in lines:
        if line.product_id in found:
            continue
        product = find_product(session, line.product_id)
        if product is None or product.company_id != company_id:
            raise ValidationFailed("A product in the sale was not found in this company")
        if not product.is_active and not offline:
            raise ValidationFailed(f"{product.sku} is no longer sold")
        found[line.product_id] = product
    return found


def post_sale(session: Session, *, till_session_id: UUID, lines: list[LineIn], payments: list[PaymentIn],
              local_id: UUID | None = None, customer_id: UUID | None = None, offline_number: str | None = None,
              sold_at: datetime | None = None, offline: bool = False) -> SaleView:
    """Record a sale on the signed-in cashier's open till. Returns the sale; `replayed` is true when `local_id` had
    already been used (the client retried), in which case nothing new is recorded. See the module note for what
    `offline` changes. Needs 'sales.sell' at the till's branch."""
    ctx = current_context()
    if ctx.user_id is None:
        raise Forbidden("A sale is rung up by a signed-in person")
    local_id = local_id or uuid4()
    pos_repo.lock_key(session, f"pos.sale:{local_id}")
    earlier = pos_repo.sale_by_local_id(session, local_id)
    if earlier is not None:
        if not _can_see(session, earlier):
            raise Conflict("This local_id was already used")
        return _view(session, earlier, replayed=True)

    till = pos_repo.get_till(session, till_session_id, share=True)
    if till is None:
        raise NotFound("Till not found")
    company_id = tills.company_of(session, till)
    ctx.require(SALES_SELL, company_id=company_id, branch_id=till.branch_id)
    if till.cashier_id != ctx.user_id:
        raise Forbidden("This is another cashier's till")
    warnings: list[str] = []
    if till.status != "open":
        if not offline:
            raise Conflict("This till is closed: open a till to sell")
        warnings.append("till_closed")
    device = pos_repo.get_device(session, till.device_id, lock=True)
    if device is None:
        raise NotFound("Device not found")
    if device.status != "active" and not offline:
        raise ValidationFailed("This device is blocked")
    devices.check_has_store(session, device)

    # when the sale happened, and which trading day it belongs to
    sold_at = sold_at or datetime.now(UTC)
    day = till.business_date if not offline else tills.business_day(session, company_id, sold_at)
    if offline and day_is_locked(session, till.branch_id, day):
        day = tills.today(session, company_id)
        warnings.append("closed_day")

    if not lines or len(lines) > rules.MAX_LINES:
        raise ValidationFailed(f"A sale has between 1 and {rules.MAX_LINES} lines")
    products = _load_products(session, lines, company_id, offline=offline)
    wants_credit = any(p.method == "credit" for p in payments)
    customer = None
    if customer_id is not None:
        customer = credit.load_customer(session, customer_id, company_id, for_credit=wants_credit)
    elif wants_credit:
        raise ValidationFailed("A sale on credit needs the customer")
    prices = selling_prices(session, company_id, till.branch_id, set(products), day,
                            customer.customer_group if customer else None)
    can_override = ctx.can(PRICE_OVERRIDE, company_id=company_id, branch_id=till.branch_id)

    rows: list[SaleLine] = []
    amounts: list[rules.LineAmounts] = []
    overridden = False
    for number, line in enumerate(lines, start=1):
        product = products[line.product_id]
        list_price = prices.get(product.id)
        unit = line.unit_price if line.unit_price is not None else list_price
        if unit is None:
            raise ValidationFailed(f"{product.sku} has no price: ask a manager to set one")
        if offline and line.unit_price is not None and list_price is not None and line.unit_price != list_price \
                and line.discount == 0 and line.reason_code_id is None:
            warnings.append(f"price_changed:{product.sku}:{line.unit_price}:{list_price}")
        differs = list_price is None or (unit != list_price and not offline) or line.discount > 0 \
            or line.reason_code_id is not None
        if differs:
            overridden = True
            if not offline:
                if not can_override:
                    raise Forbidden("Changing a price or giving a discount needs the price override permission")
                check_reason(session, PRICE_OVERRIDE_REASONS, line.reason_code_id)
            elif not can_override or line.reason_code_id is None:
                warnings.append(f"unauthorised_override:{product.sku}")
        amount = rules.price_line(line.quantity, unit, line.discount, product.vat_rate)
        amounts.append(amount)
        rows.append(SaleLine(
            tenant_id=ctx.tenant_id, line_no=number, product_id=product.id, uom_id=product.base_uom_id,
            batch_id=line.batch_id, quantity=line.quantity, list_price=list_price if list_price is not None else unit,
            unit_price=unit, discount_amount=line.discount, price_reason_code_id=line.reason_code_id,
            tax_code_id=product.tax_code_id, tax_amount=amount.tax, line_total=amount.gross,
            reference=(line.reference or "").strip()[:120] or None, sale_id=UUID(int=0)))
    subtotal = sum((a.before_discount for a in amounts), Decimal(0))
    discount_total = sum((a.discount for a in amounts), Decimal(0))
    total = sum((a.gross for a in amounts), Decimal(0))
    tax_total = sum((a.tax for a in amounts), Decimal(0))

    legs = rules.settle(total, [(p.method, p.amount) for p in payments])
    offered = {p.method: p for p in payments}
    credit_amount = next((leg.amount for leg in legs if leg.method == "credit"), Decimal(0))
    if credit_amount and customer is not None:
        warnings += credit.check_credit(session, customer, credit_amount, offline=offline)
    prefix = rules.device_prefix(pos_repo.branch_code(session, till.branch_id), device.code)
    if offline_number is not None:
        number_text = rules.check_offline_number(offline_number, prefix)
        pos_repo.lock_key(session, f"pos.number:{company_id}:{number_text}")
        if pos_repo.number_taken(session, company_id, number_text) is not None:
            raise Conflict(f"Sale number {number_text} is already used by another sale")
    else:
        number_text = rules.server_number(prefix, pos_repo.next_sequence(session, device.id))

    sale = Sale(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=till.branch_id,
        number=number_text, device_id=device.id, local_id=local_id, till_session_id=till.id, customer_id=customer_id,
        cashier_id=ctx.user_id, business_date=day, sold_at=sold_at, subtotal=subtotal, discount_total=discount_total,
        tax_total=tax_total, total=total, paid_total=total - credit_amount, synced_offline=offline,
        location_id=device.location_id)
    try:
        pos_repo.add(session, sale)
    except IntegrityError:
        raise Conflict("A sale with this number or local_id already exists") from None
    for row in rows:
        row.sale_id = sale.id
        session.add(row)
    session.flush()

    payment_rows: list[SalePayment] = []
    for leg in legs:
        given = offered[leg.method]
        if leg.method == "credit":
            payment_rows.append(SalePayment(tenant_id=ctx.tenant_id, sale_id=sale.id, method="credit",
                                            amount=leg.amount))
            session.add(payment_rows[-1])
            continue
        reference = given.external_ref.strip().upper() if given.external_ref and given.external_ref.strip() else None
        if leg.method == "mobile_money" and reference is None:
            if not offline:
                raise ValidationFailed("A mobile money payment needs the mobile money code")
            warnings.append("mobile_money_without_code")
        account_id = given.payment_account_id
        if account_id is None and leg.method != "cash":
            account_id = account_for_method(session, company_id, till.branch_id, leg.method)
            if account_id is None:
                raise ValidationFailed(f"No {leg.method.replace('_', ' ')} account is set up for this branch")
        paid = record_payment(
            session, company_id=company_id, branch_id=till.branch_id, method=leg.method, amount=leg.amount,
            payment_account_id=account_id, business_date=day, external_ref=reference,
            party_type="customer" if customer_id else None, party_id=customer_id,
            allocations=[("sale", sale.id, leg.amount)], till_session_id=till.id, paid_at=sold_at if offline else None)
        payment_row = SalePayment(tenant_id=ctx.tenant_id, sale_id=sale.id, method=leg.method,
                                  payment_account_id=account_id, amount=leg.amount, external_ref=reference,
                                  payment_id=paid.id)
        session.add(payment_row)
        payment_rows.append(payment_row)
    session.flush()
    if credit_amount and customer is not None:
        invoices.issue_credit_sale_invoice(session, sale, customer, credit_amount)

    publish(session, Event("sale.posted", "pos.sale", sale.id, {
        "company_id": company_id, "branch_id": till.branch_id, "business_date": day, "number": number_text,
        "location_id": device.location_id, "net": total - tax_total, "tax": tax_total, "customer_id": customer_id,
        "offline": offline, "till_session_id": till.id, "cashier_id": ctx.user_id,
        "payments": [{"method": leg.method, "amount": leg.amount} for leg in legs],
        "lines": [{"line_id": row.id, "product_id": row.product_id, "quantity": row.quantity,
                   "batch_id": row.batch_id} for row in rows]}))
    costs = posted_cost(session, "sale", sale.id)
    for row in rows:
        if row.id in costs:
            row.cost_amount = costs[row.id]
    session.flush()
    audit_record(session, "sell", "pos.sale", sale.id, {"number": number_text, "total": total, "offline": offline})
    if overridden:
        publish(session, Event("discount.override", "pos.sale", sale.id, {
            "company_id": company_id, "branch_id": till.branch_id, "number": number_text, "discount": discount_total,
            "cashier_id": ctx.user_id}))
    _flag_warnings(session, sale, warnings)
    change = sum((leg.change for leg in legs), Decimal(0))
    return SaleView(sale, rows, payment_rows, change=change, warnings=warnings)


WARNING_TEXT = {
    "till_closed": ("offline_late_sale", "medium", "was made offline on a till that was closed before it synced"),
    "closed_day": ("offline_closed_day", "medium", "belongs to a day that was already closed: booked today instead"),
    "mobile_money_without_code": ("offline_mobile_money_no_code", "medium",
                                  "has a mobile money payment without its reference"),
}


def _flag_warnings(session: Session, sale: Sale, warnings: list[str]) -> None:
    """Put whatever did not add up in a sale taken offline in front of a manager."""
    for warning in warnings:
        kind, _, detail = warning.partition(":")
        if kind in WARNING_TEXT:
            code, severity, text = WARNING_TEXT[kind]
        elif kind == "price_changed":
            sku, said, now = detail.split(":")
            code, severity, text = "offline_price_changed", "low", f"sold {sku} at {said} but the price is now {now}"
        elif kind == "over_credit_limit":
            code_, owed, limit = detail.split(":")
            code, severity, text = ("offline_over_credit_limit", "high",
                                    f"put {code_} at {owed} on account, over their limit of {limit}")
            publish(session, Event("customer.over_limit_attempt", "pos.sale", sale.id, {
                "company_id": sale.company_id, "branch_id": sale.branch_id, "customer": code_, "would_owe": owed,
                "limit": limit, "offline": True}))
        elif kind == "customer_on_hold":
            code, severity, text = "offline_customer_on_hold", "high", f"was sold on credit to {detail}, who is on hold"
        elif kind == "unauthorised_override":
            code, severity, text = ("offline_unauthorised_discount", "high",
                                    f"gave a discount or changed the price of {detail} without permission or a reason")
        else:
            continue
        flag_for_review(session, unit="pos", kind=code, severity=severity, company_id=sale.company_id,
                        branch_id=sale.branch_id, ref_type="sale", ref_id=sale.id, amount=sale.total,
                        dedupe_key=f"{code}:{sale.id}:{detail}", message=f"Sale {sale.number} {text}")


def void_sale(session: Session, sale_id: UUID, reason_code_id: UUID, note: str | None = None) -> SaleView:
    """Cancel a sale as if it never happened: its payments are reversed, the stock goes back at the cost it left with
    and the books are reversed. Allowed while the sale's till is still open; after that, take the goods back as a
    return. Needs 'sales.void' at the branch and a reason from the 'void' list."""
    sale = pos_repo.get_sale(session, sale_id, lock=True)
    if sale is None or not _can_see(session, sale):
        raise NotFound("Sale not found")
    ctx = current_context()
    ctx.require(SALES_VOID, company_id=sale.company_id, branch_id=sale.branch_id)
    check_reason(session, VOID_REASONS, reason_code_id, note)
    if sale.status != "posted":
        raise Conflict("This sale is already voided")
    till = pos_repo.get_till(session, sale.till_session_id, lock=True) if sale.till_session_id else None
    if till is not None and till.status != "open":
        raise ValidationFailed("The till has been closed: take the goods back as a return instead")
    if pos_repo.returned_quantities(session, sale.id):
        raise ValidationFailed("Part of this sale has been returned: it cannot be voided")
    lines = pos_repo.lines_of(session, sale.id)
    paid = pos_repo.payments_of(session, sale.id)
    invoice = pos_repo.invoice_for_sale(session, sale.id, lock=True)
    if invoice is not None:
        if invoice.amount_paid > 0 or invoice.credited > 0:
            raise ValidationFailed("The customer has paid or been credited on this sale's invoice: reverse that first")
        invoice.status, invoice.cancelled_at = "cancelled", datetime.now(UTC)
        invoice.cancelled_by, invoice.cancel_reason = ctx.user_id, f"Sale {sale.number} voided"
        session.flush()
        publish(session, Event("invoice.cancelled", "pos.sales_invoice", invoice.id, {
            "company_id": invoice.company_id, "number": invoice.number, "customer_id": invoice.customer_id,
            "total": invoice.total, "reason": invoice.cancel_reason}))
    for payment in paid:
        if payment.payment_id is not None:
            reverse_payment(session, payment.payment_id, f"Sale {sale.number} voided")
    sale.status, sale.voided_by, sale.voided_at = "voided", ctx.user_id, datetime.now(UTC)
    sale.void_reason_code_id, sale.voided_note = reason_code_id, (note or "").strip() or None
    session.flush()
    audit_record(session, "void", "pos.sale", sale.id, {"number": sale.number, "total": sale.total})
    device = pos_repo.get_device(session, sale.device_id) if sale.device_id else None
    publish(session, Event("sale.returned", "pos.sale", sale.id, {
        "company_id": sale.company_id, "branch_id": sale.branch_id, "business_date": sale.business_date,
        "number": f"{sale.number} (void)", "sale_id": sale.id, "location_id": sale.location_id or (
            device.location_id if device else None), "net": sale.total - sale.tax_total, "tax": sale.tax_total,
        "customer_id": sale.customer_id, "voided": True,
        "payments": [{"method": p.method, "amount": p.amount} for p in paid],
        "lines": [{"line_id": line.id, "sale_line_id": line.id, "product_id": line.product_id,
                   "quantity": line.quantity, "batch_id": line.batch_id} for line in lines]}))
    publish(session, Event("sale.voided", "pos.sale", sale.id, {
        "company_id": sale.company_id, "branch_id": sale.branch_id, "number": sale.number, "total": sale.total,
        "voided_by": ctx.user_id, "reason_code_id": reason_code_id}))
    return _view(session, sale)

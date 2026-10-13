"""Journal entries made from other units' events, inside the publisher's transaction.

Finance never imports POS or Inventory: they publish, and these handlers post. If a posting fails (no posting rule, the
period is locked and the company's policy is 'reject'), the publisher's whole operation rolls back, so stock, sales and
books always agree.

Event contracts (payload keys; ids may be UUIDs or strings, amounts Decimals or strings):

  stock.moved      aggregate = the stock movement (published by Inventory for every movement)
      company_id, branch_id (null for the in-transit location), location_kind, movement_type, value, business_date
  sale.posted      aggregate = the sale
      company_id, branch_id, business_date, number (optional), customer_id (optional, for credit sales),
      net, tax, payments: [{method: cash|mpesa|card|credit|other, amount}]   (payments add up to net + tax)
  sale.returned    aggregate = the return
      the same keys: net and tax returned, refunds paid back in `payments` (credit = reduced receivable)

The cost of goods sold is not in `sale.posted`: the sale's stock movements publish `stock.moved`, which posts it.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from ziira.modules.finance.domain import recipes
from ziira.modules.finance.repository.models import JournalEntry
from ziira.modules.finance.services.posting import post_from_recipe, today
from ziira.sdk import Event, Session, ValidationFailed


def _uuid(value: Any, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        raise ValidationFailed(f"'{name}' is not a valid id") from None


def _amount(value: Any, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValidationFailed(f"'{name}' is not a number") from None
    if not number.is_finite():
        raise ValidationFailed(f"'{name}' is not a number")
    return number


def _date(value: Any) -> date:
    if value is None:
        return today()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationFailed("'business_date' is not a date") from None


def _optional_uuid(value: Any, name: str) -> UUID | None:
    return _uuid(value, name) if value else None


def post_stock_movement(session: Session, event: Event) -> JournalEntry | None:
    """`stock.moved`: inventory, cost of goods sold, shrinkage, goods received not invoiced, transfers."""
    p = event.payload
    movement_type = str(p.get("movement_type"))
    value = _amount(p.get("value"), "value")
    recipe = recipes.stock_movement(movement_type, value, str(p.get("location_kind") or "store"))
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="stock_movement", journal_code="STK",
        entry_date=_date(p.get("business_date")), recipe=recipe, context={"movement_type": movement_type},
        branch_id=_optional_uuid(p.get("branch_id"), "branch_id"), source_type="stock_movement",
        source_id=event.aggregate_id, description=f"Stock {movement_type.replace('_', ' ')}")


def _sale_parts(event: Event) -> tuple[Decimal, Decimal, list[tuple[str, Decimal]], UUID | None]:
    p = event.payload
    payments = p.get("payments")
    if not isinstance(payments, list):
        raise ValidationFailed(f"{event.type}: payments are required")
    money = [(str(x.get("method", "other")), _amount(x.get("amount"), "payment amount")) for x in payments]
    return (_amount(p.get("net"), "net"), _amount(p.get("tax", 0), "tax"), money,
            _optional_uuid(p.get("customer_id"), "customer_id"))


def post_sale(session: Session, event: Event) -> JournalEntry | None:
    """`sale.posted`: money received (or owed) against sales and VAT output."""
    net, tax, money, customer = _sale_parts(event)
    p = event.payload
    number = p.get("number")
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="sale", journal_code="SAL",
        entry_date=_date(p.get("business_date")), recipe=recipes.sale(net, tax, money, party=customer),
        context={}, branch_id=_optional_uuid(p.get("branch_id"), "branch_id"), source_type="sale",
        source_id=event.aggregate_id, description=f"Sale {number}" if number else "Sale")


def post_sale_return(session: Session, event: Event) -> JournalEntry | None:
    """`sale.returned`: sales returns and VAT output reversed against the refund."""
    net, tax, money, customer = _sale_parts(event)
    p = event.payload
    number = p.get("number")
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="sale_return", journal_code="SAL",
        entry_date=_date(p.get("business_date")), recipe=recipes.sale_return(net, tax, money, party=customer),
        context={}, branch_id=_optional_uuid(p.get("branch_id"), "branch_id"), source_type="sale_return",
        source_id=event.aggregate_id, description=f"Sales return {number}" if number else "Sales return")


def post_settlement(session: Session, event: Event) -> JournalEntry | None:
    """`payment.settled`: M-Pesa takings reached the bank (less Safaricom's charges)."""
    p = event.payload
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="settlement", journal_code="CSH",
        entry_date=_date(p.get("business_date")),
        recipe=recipes.settlement(_amount(p.get("amount"), "amount"), _amount(p.get("fee", 0), "fee"),
                                  description=f"M-Pesa settlement {p.get('reference') or ''}".strip()),
        context={}, branch_id=_optional_uuid(p.get("branch_id"), "branch_id"), source_type="settlement",
        source_id=event.aggregate_id, description=f"M-Pesa settlement {p.get('reference') or ''}".strip())


def post_cash_deposit(session: Session, event: Event) -> JournalEntry | None:
    """`payment.banked`: a branch's cash was deposited in the bank."""
    p = event.payload
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="cash_deposit", journal_code="CSH",
        entry_date=_date(p.get("business_date")), recipe=recipes.cash_deposit(_amount(p.get("amount"), "amount")),
        context={}, branch_id=_optional_uuid(p.get("branch_id"), "branch_id"), source_type="cash_deposit",
        source_id=event.aggregate_id, description=f"Cash deposit {p.get('reference') or ''}".strip())


def post_till_variance(session: Session, event: Event) -> JournalEntry | None:
    """`till.closed`: a till was counted short or over."""
    p = event.payload
    variance = _amount(p.get("variance", 0), "variance")
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="till_variance", journal_code="CSH",
        entry_date=_date(p.get("business_date")), recipe=recipes.till_variance(variance), context={},
        branch_id=_optional_uuid(p.get("branch_id"), "branch_id"), source_type="till_variance",
        source_id=event.aggregate_id, description="Till shortage" if variance < 0 else "Till overage")


def post_supplier_bill(session: Session, event: Event, *, reverse: bool = False) -> JournalEntry | None:
    """`bill.posted`: what was received is no longer "not invoiced"; the supplier is owed the bill's total. With
    `reverse` (`bill.reversed`) the entry is mirrored."""
    p = event.payload
    expenses = p.get("expenses") or []
    if not isinstance(expenses, list):
        raise ValidationFailed("bill.posted: expenses must be a list")
    recipe = recipes.supplier_bill(
        _amount(p.get("stock_received_value", 0), "stock_received_value"),
        _amount(p.get("stock_billed_value", 0), "stock_billed_value"), _amount(p.get("tax", 0), "tax"),
        [(_uuid(x.get("account_id"), "expense account"), _amount(x.get("amount"), "expense amount")) for x in expenses],
        party=_optional_uuid(p.get("supplier_id"), "supplier_id"),
        description=f"Supplier bill {p.get('number') or ''}".strip(), reverse=reverse)
    label = "Reversal of supplier bill" if reverse else "Supplier bill"
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="supplier_bill", journal_code="PUR",
        entry_date=_date(p.get("business_date")), recipe=recipe, context={},
        branch_id=_optional_uuid(p.get("branch_id"), "branch_id"),
        source_type="supplier_bill_reversal" if reverse else "supplier_bill", source_id=event.aggregate_id,
        description=f"{label} {p.get('number') or ''}".strip())


def post_supplier_payment(session: Session, event: Event, *, reverse: bool = False) -> JournalEntry | None:
    """`supplier.paid`: money left the business to pay a supplier's bill (`supplier.payment_reversed`: it came back)."""
    p = event.payload
    label = "Reversal of payment of supplier bill" if reverse else "Payment of supplier bill"
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="supplier_payment",
        journal_code="CSH", entry_date=_date(p.get("business_date")),
        recipe=recipes.supplier_payment(str(p.get("method") or "other"), _amount(p.get("amount"), "amount"),
                                        party=_optional_uuid(p.get("supplier_id"), "supplier_id"), reverse=reverse),
        context={}, branch_id=_optional_uuid(p.get("branch_id"), "branch_id"),
        source_type="supplier_payment_reversal" if reverse else "supplier_payment", source_id=event.aggregate_id,
        description=f"{label} {p.get('number') or ''}".strip())


def post_supplier_credit_note(session: Session, event: Event) -> JournalEntry | None:
    """`credit_note.posted`: the supplier credited us, so we owe less."""
    p = event.payload
    expenses = p.get("expenses") or []
    if not isinstance(expenses, list):
        raise ValidationFailed("credit_note.posted: expenses must be a list")
    recipe = recipes.supplier_credit_note(
        _amount(p.get("stock_value", 0), "stock_value"), _amount(p.get("goods_credit", 0), "goods_credit"),
        _amount(p.get("tax", 0), "tax"),
        [(_uuid(x.get("account_id"), "expense account"), _amount(x.get("amount"), "expense amount")) for x in expenses],
        party=_optional_uuid(p.get("supplier_id"), "supplier_id"),
        description=f"Supplier credit note {p.get('number') or ''}".strip())
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="supplier_credit_note",
        journal_code="PUR", entry_date=_date(p.get("business_date")), recipe=recipe, context={},
        branch_id=_optional_uuid(p.get("branch_id"), "branch_id"), source_type="supplier_credit_note",
        source_id=event.aggregate_id, description=f"Supplier credit note {p.get('number') or ''}".strip())


def post_customer_payment(session: Session, event: Event, *, reverse: bool = False) -> JournalEntry | None:
    """`customer.paid`: a customer paid what they owe (`customer.payment_reversed`: the payment was cancelled)."""
    p = event.payload
    label = "Reversal of customer payment" if reverse else "Customer payment"
    return post_from_recipe(
        session, company_id=_uuid(p.get("company_id"), "company_id"), doc_type="customer_payment",
        journal_code="CSH", entry_date=_date(p.get("business_date")),
        recipe=recipes.customer_payment(str(p.get("method") or "other"), _amount(p.get("amount"), "amount"),
                                        party=_optional_uuid(p.get("customer_id"), "customer_id"), reverse=reverse),
        context={}, branch_id=_optional_uuid(p.get("branch_id"), "branch_id"),
        source_type="customer_payment_reversal" if reverse else "customer_payment", source_id=event.aggregate_id,
        description=f"{label} {p.get('number') or ''}".strip())

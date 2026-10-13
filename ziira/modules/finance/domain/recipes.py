"""How documents become journal entries: which roles are debited and credited. Pure Python.

A recipe decides the *shape* of an entry (which line roles, which side). Which account a role uses is data: the
company's posting rules (domain/rules.py), seeded from domain/chart.py and changeable per company.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ziira.modules.finance.domain.entries import MONEY
from ziira.sdk import ValidationFailed

# The roles each document type can ask for, and the conditions a rule for it may use.
DOC_ROLES: dict[str, tuple[str, ...]] = {
    "stock_movement": ("inventory", "inventory_in_transit", "cogs", "grni", "opening_equity", "shrinkage",
                       "transfer_clearing"),
    "sale": ("cash", "mpesa", "card", "credit", "other", "sales", "vat_output"),
    "sale_return": ("cash", "mpesa", "card", "credit", "other", "sales_returns", "vat_output"),
    "settlement": ("bank", "bank_charges", "mpesa_clearing"),
    "cash_deposit": ("bank", "cash"),
    "till_variance": ("cash", "till_variance"),
    "supplier_bill": ("grni", "purchase_variance", "vat_input", "payable"),
    "supplier_payment": ("payable", "cash", "bank", "mpesa", "card", "other"),
}
RULE_CONDITIONS: dict[str, tuple[str, ...]] = {"stock_movement": ("movement_type",), "sale": (), "sale_return": (),
                                               "settlement": (), "cash_deposit": (), "till_variance": (),
                                               "supplier_bill": (), "supplier_payment": ()}
MOVEMENT_TYPES = ("receipt", "opening", "sale", "sale_return", "purchase_return", "adjustment", "count_variance",
                  "write_off", "transfer_in", "transfer_out")


@dataclass(frozen=True)
class RecipeLine:
    """A line to post: the role (resolved to an account by the posting rules), the side and the amount."""

    role: str
    side: str                     # "debit" or "credit"
    amount: Decimal
    party_type: str | None = None
    party_id: Any = None
    description: str | None = None
    account_id: Any = None        # a line that names its own account (a bill's expense line) skips the posting rules


def stock_movement(movement_type: str, value: Decimal, location_kind: str) -> list[RecipeLine]:
    """Entry for one stock movement worth `value` (+ in, - out). Nothing to post when it is worth nothing.

    receipt        Dr inventory           Cr goods received not invoiced
    opening        Dr inventory           Cr opening balance equity
    sale           Dr cost of goods sold  Cr inventory
    sale_return    Dr inventory           Cr cost of goods sold
    purchase_return Dr goods received not invoiced  Cr inventory
    adjustment, count_variance, write_off   (loss) Dr shrinkage  Cr inventory  /  (gain) Dr inventory  Cr shrinkage
    transfer_out   Dr transfer clearing   Cr inventory      (the stock left this place)
    transfer_in    Dr inventory           Cr transfer clearing
    The inventory side is "inventory in transit" for the in-transit location.
    """
    amount = abs(value).quantize(MONEY)
    if amount == 0:
        return []
    inventory = "inventory_in_transit" if location_kind == "transit" else "inventory"
    gained = value > 0
    other = {
        "receipt": "grni", "opening": "opening_equity", "sale": "cogs", "sale_return": "cogs",
        "purchase_return": "grni", "adjustment": "shrinkage", "count_variance": "shrinkage",
        "write_off": "shrinkage", "transfer_in": "transfer_clearing", "transfer_out": "transfer_clearing",
    }.get(movement_type)
    if other is None:
        raise ValidationFailed(f"No posting recipe for stock movement type '{movement_type}'")
    inventory_side, other_side = ("debit", "credit") if gained else ("credit", "debit")
    return [RecipeLine(inventory, inventory_side, amount), RecipeLine(other, other_side, amount)]


def sale(net: Decimal, tax: Decimal, payments: list[tuple[str, Decimal]], *, party: Any = None,
         description: str | None = None) -> list[RecipeLine]:
    """Entry for a sale: the money received (or owed) against sales and VAT output.

    Dr cash / mpesa / card / receivable (credit sales) / other   Cr sales   Cr VAT output
    """
    return _sale_lines(net, tax, payments, party, description, returned=False)


def sale_return(net: Decimal, tax: Decimal, refunds: list[tuple[str, Decimal]], *, party: Any = None,
                description: str | None = None) -> list[RecipeLine]:
    """Entry for a customer return: sales returns and VAT output reversed against the money given back (or the
    reduced receivable). Dr sales returns, Dr VAT output  Cr cash / mpesa / card / receivable / other."""
    return _sale_lines(net, tax, refunds, party, description, returned=True)


def _sale_lines(net: Decimal, tax: Decimal, money: list[tuple[str, Decimal]], party: Any,
                description: str | None, *, returned: bool) -> list[RecipeLine]:
    if net < 0 or tax < 0:
        raise ValidationFailed("Sale amounts cannot be negative")
    total = net + tax
    paid = sum((amount for _, amount in money), Decimal(0))
    if any(amount <= 0 for _, amount in money):
        raise ValidationFailed("Payment amounts must be positive")
    if paid != total:
        raise ValidationFailed(f"The payments add up to {paid} but the sale is worth {total}")
    if total == 0:
        return []
    sides = ("credit", "debit") if returned else ("debit", "credit")
    lines = [RecipeLine(method if method in ("cash", "mpesa", "card", "credit") else "other", sides[0], amount,
                        party_type="customer" if method == "credit" and party else None,
                        party_id=party if method == "credit" else None, description=description)
             for method, amount in money]
    lines.append(RecipeLine("sales_returns" if returned else "sales", sides[1], net, description=description))
    if tax:
        lines.append(RecipeLine("vat_output", sides[1], tax, description=description))
    return [line for line in lines if line.amount > 0]


def settlement(amount: Decimal, fee: Decimal, *, description: str | None = None) -> list[RecipeLine]:
    """M-Pesa paid its takings into the bank, keeping a fee.

    Dr bank (what arrived)   Dr bank and M-Pesa charges (the fee)   Cr M-Pesa clearing (both)
    """
    if amount <= 0 or fee < 0:
        raise ValidationFailed("A settlement needs a positive amount and a fee of zero or more")
    lines = [RecipeLine("bank", "debit", amount, description=description)]
    if fee:
        lines.append(RecipeLine("bank_charges", "debit", fee, description=description))
    lines.append(RecipeLine("mpesa_clearing", "credit", amount + fee, description=description))
    return lines


def cash_deposit(amount: Decimal, *, description: str | None = None) -> list[RecipeLine]:
    """Cash from a till was taken to the bank. Dr bank  Cr till cash."""
    if amount <= 0:
        raise ValidationFailed("A deposit needs a positive amount")
    return [RecipeLine("bank", "debit", amount, description=description),
            RecipeLine("cash", "credit", amount, description=description)]


def till_variance(variance: Decimal, *, description: str | None = None) -> list[RecipeLine]:
    """A till was counted at `variance` more (+) or less (-) than expected. A shortage is an expense, an overage
    income: shortage Dr cash shortages and overages, Cr till cash (the reverse for an overage). Nothing when zero."""
    amount = abs(variance).quantize(MONEY)
    if amount == 0:
        return []
    if variance < 0:                                    # short: the cash is gone, the loss is recognised
        return [RecipeLine("till_variance", "debit", amount, description=description),
                RecipeLine("cash", "credit", amount, description=description)]
    return [RecipeLine("cash", "debit", amount, description=description),
            RecipeLine("till_variance", "credit", amount, description=description)]


def supplier_bill(stock_received_value: Decimal, stock_billed_value: Decimal, vat: Decimal,
                  expenses: list[tuple[Any, Decimal]], *, party: Any = None,
                  description: str | None = None) -> list[RecipeLine]:
    """A supplier bill: goods received not invoiced cleared at what was received, any price difference, other costs and
    VAT input, against what is owed to the supplier.

    Dr goods received not invoiced (value when received)   Dr/Cr purchase price variance (billed - received)
    Dr expense accounts (non-stock lines)                    Dr VAT input        Cr accounts payable (the bill's total)
    """
    if min(stock_received_value, stock_billed_value, vat) < 0 or any(amount <= 0 for _, amount in expenses):
        raise ValidationFailed("A bill's amounts cannot be negative")
    variance = (stock_billed_value - stock_received_value).quantize(MONEY)
    lines = []
    if stock_received_value:
        lines.append(RecipeLine("grni", "debit", stock_received_value, description=description))
    if variance:
        lines.append(RecipeLine("purchase_variance", "debit" if variance > 0 else "credit", abs(variance),
                                description=description))
    for account_id, amount in expenses:
        lines.append(RecipeLine("expense", "debit", amount, description=description, account_id=account_id))
    if vat:
        lines.append(RecipeLine("vat_input", "debit", vat, description=description))
    total = stock_billed_value + sum((a for _, a in expenses), Decimal(0)) + vat
    if total <= 0:
        raise ValidationFailed("A bill must be worth more than nothing")
    lines.append(RecipeLine("payable", "credit", total, party_type="supplier", party_id=party, description=description))
    return lines


def supplier_payment(method: str, amount: Decimal, *, party: Any = None,
                     description: str | None = None) -> list[RecipeLine]:
    """Paying a supplier: Dr accounts payable  Cr cash / bank / M-Pesa / card."""
    if amount <= 0:
        raise ValidationFailed("A payment must be more than nothing")
    role = method if method in ("cash", "mpesa", "card", "bank") else "other"
    return [RecipeLine("payable", "debit", amount, party_type="supplier", party_id=party, description=description),
            RecipeLine(role, "credit", amount, description=description)]

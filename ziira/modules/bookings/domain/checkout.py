"""The arithmetic of a checkout. Pure rules: money is Decimal, rounded to cents, and every split adds up exactly.

A checkout is a list of lines (a quantity at a tax-inclusive unit price, less a line discount), an order discount spread
over the lines, credit that pays whole units of a service (a package, a membership), a payer's share (insurance) and the
commission each person earns. Nothing here knows a country, a tax or a currency: the tax rate of a product is passed in.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from uuid import UUID

CENT = Decimal("0.01")
ZERO = Decimal(0)


def cents(value: Decimal) -> Decimal:
    """Round to two decimals, halves up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Line:
    """One line as typed at the desk. `credit_quantity` of the quantity is paid with credit (not charged)."""

    quantity: Decimal
    unit_price: Decimal
    discount: Decimal = ZERO
    credit_quantity: Decimal = ZERO


def gross(line: Line) -> Decimal:
    """What the line is worth before any discount."""
    return cents(line.quantity * line.unit_price)


def charged_quantity(line: Line) -> Decimal:
    return max(line.quantity - line.credit_quantity, ZERO)


def charged_gross(line: Line) -> Decimal:
    """The part of the line that is charged (not paid with credit), before discounts."""
    return cents(charged_quantity(line) * line.unit_price)


def line_discount(line: Line) -> Decimal:
    """The line's own discount, never more than the part charged."""
    return min(line.discount, charged_gross(line))


def line_net(line: Line) -> Decimal:
    """What the client is charged for the line before the order discount."""
    return charged_gross(line) - line_discount(line)


def spread(amounts: list[Decimal], total: Decimal) -> list[Decimal]:
    """Share `total` over `amounts` in proportion, to the cent, so the shares add up to exactly `total` (the largest
    remainders take the leftover cents) and no share is more than its amount. `total` is capped at the sum."""
    whole = sum(amounts, ZERO)
    total = min(max(total, ZERO), whole)
    if whole <= 0 or total <= 0:
        return [ZERO for _ in amounts]
    raw = [total * a / whole for a in amounts]
    floors = [r.quantize(CENT, rounding=ROUND_DOWN) for r in raw]
    left = int(((total - sum(floors, ZERO)) / CENT).to_integral_value())
    order = sorted(range(len(amounts)), key=lambda i: (raw[i] - floors[i], amounts[i]), reverse=True)
    out = list(floors)
    for i in order:
        if left <= 0:
            break
        if out[i] + CENT <= amounts[i]:
            out[i] += CENT
            left -= 1
    return out


def percent_of(amount: Decimal, percent: Decimal) -> Decimal:
    return cents(amount * percent / Decimal(100))


@dataclass(frozen=True)
class Totals:
    """The bill: what is worth what, and what is left to pay."""

    subtotal: Decimal                 # everything at list, credit-covered units included
    line_discounts: Decimal
    order_discount: Decimal
    credit_value: Decimal             # worth of the units paid with credit (not charged)
    total: Decimal                    # what the client pays
    shares: tuple[Decimal, ...]       # the order discount given to each line


def totals(lines: list[Line], order_discount: Decimal = ZERO) -> Totals:
    """Add up a checkout. The order discount is spread over the charged lines and cannot make the bill negative."""
    nets = [line_net(x) for x in lines]
    shares = spread(nets, order_discount)
    credit = sum((cents((x.quantity - charged_quantity(x)) * x.unit_price) for x in lines), ZERO)
    return Totals(
        subtotal=sum((gross(x) for x in lines), ZERO), line_discounts=sum((line_discount(x) for x in lines), ZERO),
        order_discount=sum(shares, ZERO), credit_value=credit, total=sum(nets, ZERO) - sum(shares, ZERO),
        shares=tuple(shares))


def invoice_discounts(lines: list[Line], order_discount: Decimal) -> list[Decimal]:
    """The discount to put on each invoice line: the line's own plus its share of the order discount."""
    shares = totals(lines, order_discount).shares
    return [line_discount(x) + s for x, s in zip(lines, shares, strict=True)]


def order_discount_amount(lines: list[Line], kind: str, value: Decimal) -> Decimal:
    """An order discount typed as an amount or as a percent of what is charged (after line discounts)."""
    base = sum((line_net(x) for x in lines), ZERO)
    if kind == "percent":
        return min(percent_of(base, value), base)
    return min(cents(value), base)


def split_payer(amounts: list[Decimal], patient_share: Decimal) -> list[tuple[Decimal, Decimal]]:
    """Divide each line between the patient (the co-pay) and the payer (an insurer or scheme). Returns (patient, payer)
    per line; the patient parts add up exactly to `patient_share` (capped at the bill) and each pair adds up to its
    line."""
    patient = spread(amounts, patient_share)
    return [(p, a - p) for a, p in zip(amounts, patient, strict=True)]


def net_of_tax(amount: Decimal, vat_rate: Decimal) -> Decimal:
    """A tax-inclusive amount without its tax (the rate is a percent)."""
    return amount - cents(amount * vat_rate / (Decimal(100) + vat_rate))


@dataclass(frozen=True)
class Rule:
    """A commission rule. A field left empty matches anything; the more fields match, the more specific the rule."""

    id: UUID
    applies_to: str                   # "service" or "product"
    kind: str                         # "percent" or "fixed"
    value: Decimal
    resource_id: UUID | None = None
    level: str | None = None
    offer_id: UUID | None = None
    product_id: UUID | None = None


def pick_rule(rules: list[Rule], *, applies_to: str, resource_id: UUID | None, level: str | None,
              offer_id: UUID | None = None, product_id: UUID | None = None) -> Rule | None:
    """The most specific rule that fits: this person, then this item, then this level. Ties go to the lowest id so the
    answer never changes between runs."""
    best: tuple[int, Rule] | None = None
    for r in rules:
        if r.applies_to != applies_to:
            continue
        if r.resource_id is not None and r.resource_id != resource_id:
            continue
        if r.level is not None and (level is None or r.level.casefold() != level.casefold()):
            continue
        if r.offer_id is not None and r.offer_id != offer_id:
            continue
        if r.product_id is not None and r.product_id != product_id:
            continue
        score = (8 if r.resource_id else 0) + (4 if r.offer_id or r.product_id else 0) + (2 if r.level else 0)
        if best is None or score > best[0] or (score == best[0] and str(r.id) < str(best[1].id)):
            best = (score, r)
    return best[1] if best else None


def commission_amount(rule: Rule, base: Decimal, quantity: Decimal = Decimal(1)) -> Decimal:
    """What the rule pays on `base`: a percent of it, or a fixed amount per unit (never more than nothing below
    zero)."""
    if base <= 0 and rule.kind == "percent":
        return ZERO
    return percent_of(base, rule.value) if rule.kind == "percent" else cents(rule.value * quantity)


def fee_due(late: bool, no_show: bool, percent_late: Decimal, percent_no_show: Decimal, price: Decimal) -> Decimal:
    """The fee for a late cancellation or a no-show: the business's percent of the service price (0: no fee)."""
    percent = percent_no_show if no_show else percent_late if late else ZERO
    return percent_of(price, percent) if percent > 0 else ZERO


def deposit_due(price: Decimal, fixed: Decimal, percent: Decimal) -> Decimal:
    """The deposit a service asks for: the fixed amount or the percent of the price, whichever is larger, never more
    than the price."""
    return min(max(cents(fixed), percent_of(price, percent)), price)

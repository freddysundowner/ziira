"""Project budgets: how much is used. Pure rules."""

from decimal import Decimal


def percent_used(used: Decimal | int, budget: Decimal | int | None) -> Decimal | None:
    """Used as a percentage of the budget to one place, or None when there is no budget (or it is zero)."""
    if budget is None or Decimal(budget) <= 0:
        return None
    return (Decimal(used) * 100 / Decimal(budget)).quantize(Decimal("0.1"))


def state(percent: Decimal | None, alert_at: int) -> str:
    """`none` (no budget), `ok`, `near` (at or above the alert level) or `over` (above 100)."""
    if percent is None:
        return "none"
    if percent > 100:
        return "over"
    return "near" if percent >= alert_at else "ok"

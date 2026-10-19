"""A payer's terms applied to a price. Pure Python.

Terms are data on the payer: a labour rate per hour for each kind of work, a paint rate, and a parts discount or markup.
They only ever suggest a price; the estimate keeps what the business typed or accepted.
"""

from decimal import Decimal
from typing import Any

from ziira.modules.claims.domain.money import cents

HUNDRED = Decimal(100)


def labour_rate(rates: dict[str, Any], work_type: str | None) -> Decimal | None:
    """The payer's hourly rate for a kind of work, or its default rate, or none."""
    for key in ((work_type or "").strip().lower(), "default"):
        if key and key in rates:
            return Decimal(str(rates[key]))
    return None


def parts_price(list_price: Decimal, discount_pct: Decimal, markup_pct: Decimal) -> Decimal:
    """A part's price under the payer's rules: the markup first, then the discount."""
    return cents(list_price * (HUNDRED + markup_pct) / HUNDRED * (HUNDRED - discount_pct) / HUNDRED)

"""Shared pieces of Inventory's checks and figures: money and quantity wording, and the on-hand query."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text

from ziira.sdk import Session

# Quantity on hand per branch and product, over the locations that really hold stock (not in-transit or virtual ones).
ON_HAND_CTE = """
onhand as (
  select l.branch_id, b.product_id, sum(b.quantity) as qty
  from inventory.stock_balance b
  join inventory.location l on l.id = b.location_id
  where l.company_id = :company and l.kind in ('store', 'warehouse') and l.branch_id is not null
  group by l.branch_id, b.product_id
)"""

# Manual stock removals: adjustments made by hand and write-offs (not the small differences a transfer receipt records).
MANUAL_OUT = ("((m.movement_type = 'adjustment' and m.source_type = 'stock_adjustment') "
              "or m.movement_type = 'write_off')")


def currency(session: Session, company_id: UUID) -> str:
    """The company's currency code, for wording."""
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def money(amount: Decimal, code: str) -> str:
    """'USD 1,250.00' style wording (the code is the company's own currency)."""
    return f"{code} {amount:,.2f}"


def qty(value: Decimal) -> str:
    """A quantity without trailing zeros."""
    text_value = f"{value.normalize():f}"
    return text_value


def local_date(value: date) -> str:
    """ISO date wording, unambiguous in any country."""
    return value.isoformat()


def query(session: Session, sql: str, **params: Any) -> list[Row[Any]]:
    """Run a read-only query; ids may be passed as UUIDs."""
    clean = {k: str(v) if isinstance(v, UUID) else v for k, v in params.items()}
    return list(session.execute(text(sql), clean).all())

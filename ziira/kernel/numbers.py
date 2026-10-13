"""Number types for request bodies and query parameters.

They match the database columns (numeric(18,4) and so on), so a value that cannot be stored is refused with
a clear 422 at the edge instead of failing inside a transaction. NaN and infinity are never accepted.
Combine with more limits: `Annotated[Quantity, Field(gt=0)]`.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field

Quantity = Annotated[Decimal, Field(max_digits=18, decimal_places=4, allow_inf_nan=False)]
UnitCost = Annotated[Decimal, Field(max_digits=18, decimal_places=6, allow_inf_nan=False)]
Amount = Annotated[Decimal, Field(max_digits=18, decimal_places=2, allow_inf_nan=False)]
Rate = Annotated[Decimal, Field(max_digits=5, decimal_places=2, allow_inf_nan=False)]

MAX_PAGE = 500


def page_limit(default: int = 100) -> int:
    """Query parameter `limit` of a list endpoint: 1 to 500. Use as `limit: int = page_limit()`."""
    return Query(default, ge=1, le=MAX_PAGE)  # type: ignore[no-any-return]


def page_offset() -> int:
    """Query parameter `offset` of a list endpoint. Use as `offset: int = page_offset()`."""
    return Query(0, ge=0, le=1_000_000_000)  # type: ignore[no-any-return]

"""Small helpers shared by Finance's checks."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import Session


def currency(session: Session, company_id: UUID) -> str:
    """The company's currency code."""
    row = session.execute(text("select base_currency from kernel.company where id = :c"),
                          {"c": str(company_id)}).first()
    return str(row.base_currency).strip() if row else ""


def money(value: Decimal | int | str) -> str:
    """An amount with thousands separators and two decimals."""
    return f"{Decimal(str(value)):,.2f}"


def since(today: date, days: Decimal | int) -> date:
    """The first day of a look-back window of `days` days ending today."""
    return today - timedelta(days=int(days))


def ids(value: Any) -> UUID | None:
    """A row's id column as a UUID (or None)."""
    return UUID(str(value)) if value is not None else None

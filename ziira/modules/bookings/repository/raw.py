"""Plain-SQL access to the newer `bookings` tables (checkout, commission, fees, recalls, rentals, group waitlist).

Rows come back as dictionaries. Every insert stamps the tenant from the session (row-level security does the rest).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import Session

Row = dict[str, Any]


def _plain(value: Any) -> Any:
    return str(value) if isinstance(value, UUID) else value


def one(session: Session, sql: str, **params: Any) -> Row | None:
    """The first row of a query, or None."""
    found = session.execute(text(sql), {k: _plain(v) for k, v in params.items()}).mappings().first()
    return dict(found) if found is not None else None


def many(session: Session, sql: str, **params: Any) -> list[Row]:
    """Every row of a query."""
    return [dict(r) for r in session.execute(text(sql), {k: _plain(v) for k, v in params.items()}).mappings()]


def scalar(session: Session, sql: str, **params: Any) -> Any:
    """The first column of the first row."""
    return session.execute(text(sql), {k: _plain(v) for k, v in params.items()}).scalar_one()


def run(session: Session, sql: str, **params: Any) -> None:
    """Run a statement that returns nothing."""
    session.execute(text(sql), {k: _plain(v) for k, v in params.items()})


def insert(session: Session, table: str, values: Row, *, user_id: UUID | None = None) -> Row:
    """Add a row to `bookings.<table>` and return it."""
    data = dict(values)
    if user_id is not None:
        data.setdefault("created_by", user_id)
    columns = list(data)
    marks = ", ".join(f":{c}" for c in columns)
    found = session.execute(text(
        f"insert into bookings.{table} (tenant_id, {', '.join(columns)}) values (kernel.current_tenant(), {marks}) "
        "returning *"), {c: _plain(data[c]) for c in columns}).mappings().one()
    return dict(found)


def update(session: Session, table: str, row_id: UUID, values: Row, *, user_id: UUID | None = None) -> Row:
    """Change some columns of a row (and stamp it) and return it."""
    data = {**values, "updated_at": datetime.now(UTC), "updated_by": user_id}
    sets = ", ".join(f"{c} = :{c}" for c in data)
    found = session.execute(text(f"update bookings.{table} set {sets} where id = :_id returning *"),
                            {**{c: _plain(v) for c, v in data.items()}, "_id": str(row_id)}).mappings().one()
    return dict(found)

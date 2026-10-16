"""Database access for moving a connected system's data into Ziira: reading the canonical copy, the codes given, the
moves and their batches. SQL only; rules live in services/move.py and domain/move.py."""

import json
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import Session

MOVE_COLUMNS = "id, created_at, created_by, connection_id, company_id, as_of, options, status, finished_at"


# --------------------------------------------------------------------------- the canonical copy
def products(session: Session, connection_id: UUID) -> list[Row[Any]]:
    return list(session.execute(text(
        "select ref, name, sku, category, unit_cost, unit_price from connect.src_product "
        "where connection_id = :k order by first_seen_at, ref"), {"k": str(connection_id)}))


def parties(session: Session, connection_id: UUID, kind: str) -> list[Row[Any]]:
    return list(session.execute(text(
        "select ref, name, phone, email, tax_id, erased from connect.src_party where connection_id = :k and kind = :t "
        "order by coalesce(source_created_at, first_seen_at), ref"), {"k": str(connection_id), "t": kind}))


def stock_positions(session: Session, connection_id: UUID, as_of: date, zone: str) -> list[Row[Any]]:
    """The running balance per product and branch as at the end of `as_of` (in the company's time zone), with the
    weighted average of what the receipts cost (the movements that came in with a unit cost)."""
    return list(session.execute(text(
        "select m.product_ref, m.branch_id, sum(m.quantity) as quantity, "
        "sum(m.quantity * m.unit_cost) filter (where m.quantity > 0 and m.unit_cost is not null) as cost_value, "
        "sum(m.quantity) filter (where m.quantity > 0 and m.unit_cost is not null) as cost_quantity, "
        "p.sku, p.name, p.unit_cost as product_cost "
        "from connect.src_stock_movement m left join connect.src_product p on p.connection_id = m.connection_id "
        "and p.ref = m.product_ref where m.connection_id = :k and (m.occurred_at at time zone :tz)::date <= :d "
        "group by m.product_ref, m.branch_id, p.sku, p.name, p.unit_cost "
        "order by upper(p.sku) nulls last, m.product_ref, m.branch_id"),
        {"k": str(connection_id), "tz": zone, "d": as_of}))


def open_invoices(session: Session, connection_id: UUID, kind: str, as_of: date) -> list[Row[Any]]:
    return list(session.execute(text(
        "select i.ref, i.number, i.issue_date, i.due_date, i.total, i.paid, i.party_ref, p.name as party_name "
        "from connect.src_invoice i left join connect.src_party p on p.connection_id = i.connection_id "
        "and p.ref = i.party_ref where i.connection_id = :k and i.kind = :t and i.status = 'open' "
        "and i.issue_date <= :d and i.total - i.paid > 0 order by i.issue_date, i.ref"),
        {"k": str(connection_id), "t": kind, "d": as_of}))


def mapped_branches(session: Session, connection_id: UUID) -> list[Row[Any]]:
    return list(session.execute(text(
        "select m.external_ref, m.external_name, m.branch_id, m.ignored, b.name as branch_name "
        "from connect.branch_map m left join kernel.branch b on b.id = m.branch_id where m.connection_id = :k "
        "order by m.external_name nulls last, m.external_ref"), {"k": str(connection_id)}))


def count_users(session: Session, connection_id: UUID) -> int:
    return int(session.execute(text(
        "select count(*) from connect.src_user where connection_id = :k and not erased"),
        {"k": str(connection_id)}).scalar_one())


def source_counts(session: Session, connection_id: UUID) -> dict[str, int]:
    """What the other system holds that a move could use."""
    r = session.execute(text(
        "select (select count(*) from connect.src_product where connection_id = :k) as products, "
        "(select count(*) from connect.src_party where connection_id = :k and kind = 'customer' and not erased) "
        "as customers, "
        "(select count(*) from connect.src_party where connection_id = :k and kind = 'supplier' and not erased) "
        "as suppliers, "
        "(select count(*) from connect.src_stock_movement where connection_id = :k) as stock_movements, "
        "(select count(*) from connect.src_invoice where connection_id = :k and kind = 'customer' "
        "and status = 'open' and total - paid > 0) as customer_invoices, "
        "(select count(*) from connect.src_invoice where connection_id = :k and kind = 'supplier' "
        "and status = 'open' and total - paid > 0) as supplier_invoices, "
        "(select count(*) from connect.src_user where connection_id = :k and not erased) as users"),
        {"k": str(connection_id)}).one()
    return {name: int(value) for name, value in r._mapping.items()}


def has_finished_move(session: Session, connection_id: UUID) -> bool:
    return session.execute(text("select 1 from connect.move where connection_id = :k and status = 'done' limit 1"),
                           {"k": str(connection_id)}).first() is not None


def enabled_units(session: Session) -> set[str]:
    return set(session.execute(text(
        "select unit_name from kernel.tenant_unit where status = 'enabled' and tenant_id = kernel.current_tenant()"
    )).scalars())


# --------------------------------------------------------------------------- codes given to customers and suppliers
def codes(session: Session, connection_id: UUID, kind: str) -> dict[str, tuple[str, bool]]:
    """source ref -> (Ziira code, whether it is an existing record the source's one matched)."""
    return {r.source_ref: (r.code, r.matched) for r in session.execute(text(
        "select source_ref, code, matched from connect.move_code where connection_id = :k and kind = :t"),
        {"k": str(connection_id), "t": kind})}


def save_codes(session: Session, connection_id: UUID, kind: str, found: dict[str, tuple[str, bool]]) -> None:
    for ref, (code, matched) in found.items():
        session.execute(text(
            "insert into connect.move_code (tenant_id, connection_id, kind, source_ref, code, matched) values "
            "(kernel.current_tenant(), :k, :t, :r, :c, :m) on conflict (connection_id, kind, source_ref) do nothing"),
            {"k": str(connection_id), "t": kind, "r": ref, "c": code, "m": matched})


# --------------------------------------------------------------------------- moves and their batches
def add_move(session: Session, *, connection_id: UUID, company_id: UUID, as_of: date, options: dict[str, Any],
             created_by: UUID | None) -> UUID:
    row = session.execute(text(
        "insert into connect.move (tenant_id, connection_id, company_id, as_of, options, created_by) values "
        "(kernel.current_tenant(), :k, :c, :d, cast(:o as jsonb), :u) returning id"),
        {"k": str(connection_id), "c": str(company_id), "d": as_of, "o": json.dumps(options),
         "u": str(created_by) if created_by else None}).one()
    move_id: UUID = row.id
    return move_id


def get_move(session: Session, move_id: UUID, *, lock: bool = False) -> Row[Any] | None:
    return session.execute(text(f"select {MOVE_COLUMNS} from connect.move where id = :i" + (" for update" if lock
                                                                                              else "")),
                           {"i": str(move_id)}).first()


def running_move(session: Session, connection_id: UUID) -> Row[Any] | None:
    return session.execute(text(
        f"select {MOVE_COLUMNS} from connect.move where connection_id = :k and status = 'running' "
        "order by created_at desc limit 1"), {"k": str(connection_id)}).first()


def list_moves(session: Session, connection_id: UUID, limit: int = 20) -> list[Row[Any]]:
    return list(session.execute(text(
        f"select {MOVE_COLUMNS} from connect.move where connection_id = :k order by created_at desc limit :l"),
        {"k": str(connection_id), "l": limit}))


def finish_move(session: Session, move_id: UUID) -> None:
    session.execute(text("update connect.move set status = 'done', finished_at = now() where id = :i"),
                    {"i": str(move_id)})


def add_move_batch(session: Session, *, move_id: UUID, kind: str, phase: int, batch_id: UUID | None, staged: int,
                   note: str | None) -> None:
    session.execute(text(
        "insert into connect.move_batch (tenant_id, move_id, kind, phase, batch_id, staged, note) values "
        "(kernel.current_tenant(), :m, :k, :p, :b, :s, :n) on conflict (move_id, kind) do nothing"),
        {"m": str(move_id), "k": kind, "p": phase, "b": str(batch_id) if batch_id else None, "s": staged, "n": note})


def move_batches(session: Session, move_id: UUID) -> list[Row[Any]]:
    return list(session.execute(text(
        "select kind, phase, batch_id, staged, note from connect.move_batch where move_id = :m order by phase, kind"),
        {"m": str(move_id)}))

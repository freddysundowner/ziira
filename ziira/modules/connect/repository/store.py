"""Writing the canonical model into the `connect.src_*` tables.

One path for every source: an API connector's batches and an uploaded file's rows both come through `store_records`.
Upserts are keyed by (connection, ref), so reading the same record again changes nothing (idempotent). Every record is
written in its own savepoint, so one bad record is skipped and counted while the others are kept. This module only
writes our own `connect.src_*` tables: nothing here touches a source system.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.connect.public import (
    Branch,
    Expense,
    Invoice,
    JournalEntry,
    Party,
    Payment,
    Product,
    Record,
    Sale,
    StockMovement,
    User,
)
from ziira.sdk import Session

MAX_NOTES = 20


class SkipRecord(Exception):
    """A record that cannot be stored (the message says why, in plain words) or that belongs to an ignored branch."""


@dataclass
class Counts:
    read: int = 0
    new: int = 0
    changed: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        if len(self.notes) < MAX_NOTES:
            self.notes.append(message)

    def add(self, other: "Counts") -> None:
        self.read += other.read
        self.new += other.new
        self.changed += other.changed
        self.skipped += other.skipped
        for message in other.notes:
            self.note(message)


@dataclass
class Target:
    """Where records go: one connection of one company, with its branch resolver."""

    connection_id: UUID
    company_id: UUID
    resolve_branch: Callable[[str | None], tuple[UUID | None, bool]]    # ref -> (kernel branch or None, ignored)


def content_hash(record: Record) -> str:
    return hashlib.sha256(json.dumps(asdict(record), default=str, sort_keys=True).encode()).hexdigest()


def _aware(value: datetime | None, what: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise SkipRecord(f"{what} has no time zone")
    return value


def _money(value: Decimal, what: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise SkipRecord(f"{what} is not a number")
    if abs(value) >= Decimal("1e16"):
        raise SkipRecord(f"{what} is too large")
    return value


def _text(value: str | None, limit: int = 500) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value[:limit] if value else None


# --------------------------------------------------------------------------- row builders
def _branch(record: Branch, target: Target) -> dict[str, Any]:
    return {"name": _text(record.name, 200) or record.ref}


def _party(record: Party, target: Target) -> dict[str, Any]:
    if record.kind not in ("customer", "supplier"):
        raise SkipRecord(f"unknown party kind '{record.kind}'")
    return {"kind": record.kind, "name": _text(record.name, 200) or record.ref, "phone": _text(record.phone, 60),
            "email": _text(record.email, 200), "tax_id": _text(record.tax_id, 60),
            "source_created_at": _aware(record.created_at, "created_at")}


def _product(record: Product, target: Target) -> dict[str, Any]:
    return {"name": _text(record.name, 300) or record.ref, "sku": _text(record.sku, 100),
            "category": _text(record.category, 200),
            "unit_cost": _money(record.unit_cost, "unit_cost") if record.unit_cost is not None else None,
            "unit_price": _money(record.unit_price, "unit_price") if record.unit_price is not None else None}


def _user(record: User, target: Target) -> dict[str, Any]:
    return {"name": _text(record.name, 200) or record.ref, "role": _text(record.role, 100),
            "email": _text(record.email, 200), "source_created_at": _aware(record.created_at, "created_at")}


def _with_branch(target: Target, branch_ref: str | None) -> dict[str, Any]:
    branch_id, ignored = target.resolve_branch(branch_ref)
    if ignored:
        raise SkipRecord("its branch is set to be ignored")
    return {"branch_ref": _text(branch_ref, 200), "branch_id": branch_id}


def _sale(record: Sale, target: Target) -> dict[str, Any]:
    if record.status not in ("posted", "voided", "refunded"):
        raise SkipRecord(f"unknown sale status '{record.status}'")
    return {"occurred_at": _aware(record.occurred_at, "occurred_at"), "entered_at": _aware(record.entered_at,
        "entered_at"),
            "total": _money(record.total, "total"), "status": record.status, "number": _text(record.number, 100),
            **_with_branch(target, record.branch_ref), "cashier_ref": _text(record.cashier_ref, 200),
            "customer_ref": _text(record.customer_ref, 200), "tax_total": _money(record.tax_total, "tax_total"),
            "discount_total": _money(record.discount_total, "discount_total"), "currency": _text(record.currency, 10),
            "voided_by_ref": _text(record.voided_by_ref, 200)}


def _payment(record: Payment, target: Target) -> dict[str, Any]:
    if record.direction not in ("in", "out"):
        raise SkipRecord(f"unknown direction '{record.direction}'")
    return {"occurred_at": _aware(record.occurred_at, "occurred_at"), "direction": record.direction,
            "amount": _money(record.amount, "amount"), "method": _text(record.method, 40) or "other",
            "reference": _text(record.reference, 200), "party_ref": _text(record.party_ref, 200),
            "party_name": _text(record.party_name, 200), "account": _text(record.account, 200),
            **_with_branch(target, record.branch_ref), "invoice_ref": _text(record.invoice_ref, 200),
            "currency": _text(record.currency, 10)}


def _movement(record: StockMovement, target: Target) -> dict[str, Any]:
    return {"occurred_at": _aware(record.occurred_at, "occurred_at"), "product_ref": _text(record.product_ref, 200),
            "quantity": _money(record.quantity, "quantity"), "kind": record.kind,
            **_with_branch(target, record.branch_ref), "user_ref": _text(record.user_ref, 200),
            "reason": _text(record.reason, 300),
            "unit_cost": _money(record.unit_cost, "unit_cost") if record.unit_cost is not None else None,
            "entered_at": _aware(record.entered_at, "entered_at")}


def _invoice(record: Invoice, target: Target) -> dict[str, Any]:
    if record.kind not in ("customer", "supplier"):
        raise SkipRecord(f"unknown invoice kind '{record.kind}'")
    if record.status not in ("open", "paid", "cancelled", "draft"):
        raise SkipRecord(f"unknown invoice status '{record.status}'")
    return {"kind": record.kind, "issue_date": record.issue_date, "due_date": record.due_date,
            "total": _money(record.total, "total"), "paid": _money(record.paid, "paid"),
            "number": _text(record.number, 100), "party_ref": _text(record.party_ref, 200),
            **_with_branch(target, record.branch_ref), "status": record.status,
            "created_by_ref": _text(record.created_by_ref, 200), "approved_by_ref": _text(record.approved_by_ref, 200),
            "currency": _text(record.currency, 10)}


def _expense(record: Expense, target: Target) -> dict[str, Any]:
    return {"occurred_at": _aware(record.occurred_at, "occurred_at"), "amount": _money(record.amount, "amount"),
            "category": _text(record.category, 200), "description": _text(record.description, 500),
            **_with_branch(target, record.branch_ref), "user_ref": _text(record.user_ref, 200),
            "party_ref": _text(record.party_ref, 200)}


def _journal(record: JournalEntry, target: Target) -> dict[str, Any]:
    if not record.lines:
        raise SkipRecord("it has no lines")
    return {"entry_date": record.entry_date, "number": _text(record.number, 100),
            "entered_at": _aware(record.entered_at, "entered_at"),
            "created_by_ref": _text(record.created_by_ref, 200), "approved_by_ref": _text(record.approved_by_ref, 200),
            "memo": _text(record.memo, 500), "is_manual": bool(record.is_manual),
            "total_debit": sum((_money(line.debit, "debit") for line in record.lines), Decimal(0))}


BUILDERS: dict[str, tuple[str, Callable[[Any, Target], dict[str, Any]]]] = {
    "branches": ("src_branch", _branch), "parties": ("src_party", _party), "products": ("src_product", _product),
    "users": ("src_user", _user), "sales": ("src_sale", _sale), "payments": ("src_payment", _payment),
    "stock_movements": ("src_stock_movement", _movement), "invoices": ("src_invoice", _invoice),
    "expenses": ("src_expense", _expense), "journal_entries": ("src_journal_entry", _journal),
}
ERASABLE = {"src_party": ("name", "phone", "email", "tax_id"), "src_user": ("name", "email")}
EXPECTED = {"branches": Branch, "parties": Party, "products": Product, "users": User, "sales": Sale,
            "payments": Payment, "stock_movements": StockMovement, "invoices": Invoice, "expenses": Expense,
            "journal_entries": JournalEntry}


# --------------------------------------------------------------------------- writing
def _upsert(session: Session, table: str, target: Target, ref: str, digest: str, columns: dict[str, Any]) -> UUID:
    names = list(columns)
    erasable = ERASABLE.get(table, ())
    updates = ", ".join(
        f"{n} = case when connect.{table}.erased then connect.{table}.{n} else excluded.{n} end" if n in erasable
        else f"{n} = excluded.{n}" for n in names)
    sql = (f"insert into connect.{table} (tenant_id, connection_id, company_id, ref, content_hash, "
           f"{', '.join(names)}) values (kernel.current_tenant(), :connection_id, :company_id, :ref, :content_hash, "
           f"{', '.join(':' + n for n in names)}) on conflict (connection_id, ref) do update set "
           f"content_hash = excluded.content_hash, last_seen_at = now(), {updates} returning id")
    row = session.execute(text(sql), {"connection_id": str(target.connection_id), "company_id": str(target.company_id),
                                      "ref": ref, "content_hash": digest, **columns}).one()
    row_id: UUID = row.id
    return row_id


def _children(session: Session, target: Target, entity: str, parent_id: UUID, record: Any) -> None:
    c = {"t": str(target.connection_id), "p": str(parent_id)}
    if entity == "sales":
        session.execute(text("delete from connect.src_sale_line where sale_id = :p"), {"p": c["p"]})
        session.execute(text("delete from connect.src_sale_payment where sale_id = :p"), {"p": c["p"]})
        for n, line in enumerate(record.lines, 1):
            session.execute(text(
                "insert into connect.src_sale_line (tenant_id, sale_id, connection_id, line_no, product_ref, quantity, "
                "unit_price, discount, list_price) values (kernel.current_tenant(), :p, :t, :n, :r, :q, :u, :d, :l)"),
                {**c, "n": n, "r": _text(line.product_ref, 200), "q": _money(line.quantity, "quantity"),
                 "u": _money(line.unit_price, "unit_price"), "d": _money(line.discount, "discount"),
                 "l": _money(line.list_price, "list_price") if line.list_price is not None else None})
        for n, pay in enumerate(record.payments, 1):
            session.execute(text(
                "insert into connect.src_sale_payment (tenant_id, sale_id, connection_id, line_no, method, amount, "
                "reference) values (kernel.current_tenant(), :p, :t, :n, :m, :a, :r)"),
                {**c, "n": n, "m": _text(pay.method, 40) or "other", "a": _money(pay.amount, "amount"),
                 "r": _text(pay.reference, 200)})
    elif entity == "journal_entries":
        session.execute(text("delete from connect.src_journal_line where entry_id = :p"), {"p": c["p"]})
        for n, jl in enumerate(record.lines, 1):
            session.execute(text(
                "insert into connect.src_journal_line (tenant_id, entry_id, connection_id, line_no, account, debit, "
                "credit, party_ref) values (kernel.current_tenant(), :p, :t, :n, :a, :d, :c, :r)"),
                {**c, "n": n, "a": _text(jl.account, 300) or "?", "d": _money(jl.debit, "debit"),
                 "c": _money(jl.credit, "credit"), "r": _text(jl.party_ref, 200)})


def _existing_hashes(session: Session, table: str, connection_id: UUID, refs: list[str]) -> dict[str, str]:
    return {r.ref: r.content_hash for r in session.execute(text(
        f"select ref, content_hash from connect.{table} where connection_id = :c and ref = any(:refs)"),
        {"c": str(connection_id), "refs": refs})}


def _store_one(session: Session, target: Target, entity: str, table: str,
               build: Callable[[Any, Target], dict[str, Any]], record: Record, known: dict[str, str]) -> str:
    """Store one record; returns 'new', 'changed' or 'same'. Raises SkipRecord (or a database error) when it cannot."""
    if not isinstance(record, EXPECTED[entity]):
        raise SkipRecord(f"not a {EXPECTED[entity].__name__} record")
    ref = _text(getattr(record, "ref", None), 300)
    if not ref:
        raise SkipRecord("it has no reference")
    digest = content_hash(record)
    columns = build(record, target)
    previous = known.get(ref)
    row_id = _upsert(session, table, target, ref, digest, columns)
    if previous != digest:
        _children(session, target, entity, row_id, record)
    known[ref] = digest
    return "new" if previous is None else "changed" if previous != digest else "same"


def store_records(session: Session, target: Target, entity: str, records: Sequence[Record]) -> Counts:
    """Write a page of records of one entity, each in its own savepoint: a bad record is skipped and counted, and never
    stops the page."""
    table, build = BUILDERS[entity]
    counts = Counts(read=len(records))
    refs = [r for r in (_text(getattr(rec, "ref", None), 300) for rec in records) if r]
    known = _existing_hashes(session, table, target.connection_id, refs)

    for record in records:
        try:
            with session.begin_nested():                       # a savepoint per record: a bad one never stops the page
                outcome = _store_one(session, target, entity, table, build, record, known)
        except SkipRecord as error:
            counts.skipped += 1
            counts.note(f"{getattr(record, 'ref', '?')}: {error}")
        except Exception as error:  # noqa: BLE001 - one bad record never stops the page
            counts.skipped += 1
            counts.note(f"{getattr(record, 'ref', '?')}: could not be stored ({type(error).__name__})")
        else:
            if outcome == "new":
                counts.new += 1
            elif outcome == "changed":
                counts.changed += 1
    return counts

"""The exceptions inbox: things a person must look at, raised by any unit and worked in one place.

Examples: stock sold that the system did not have, an offline sale that conflicted with a price change, a till that came
up short, a payment nobody has matched. Units raise them with `flag` (SDK name: `flag_for_review`); people with the
permission `exceptions.manage` list, assign, explain and resolve them. Raising is idempotent when a `dedupe_key` is
given, so the same problem seen twice is one item.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.context import get_context
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.events import Event, publish

SEVERITIES = ("info", "low", "medium", "high", "critical")
STATUSES = ("open", "explained", "resolved", "dismissed")
TRANSITIONS = {"open": {"explained", "resolved", "dismissed"}, "explained": {"resolved", "dismissed"},
               "resolved": set(), "dismissed": set()}
COLUMNS = ("id, created_at, unit_name, kind, severity, company_id, branch_id, ref_type, ref_id, amount, message, "
           "status, assigned_to, resolution_note, resolved_by, resolved_at")


@dataclass(frozen=True)
class ExceptionItem:
    id: UUID
    created_at: datetime
    unit_name: str
    kind: str
    severity: str
    company_id: UUID | None
    branch_id: UUID | None
    ref_type: str | None
    ref_id: UUID | None
    amount: Decimal | None
    message: str
    status: str
    assigned_to: UUID | None
    resolution_note: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None


def flag(s: Session, *, unit: str, kind: str, message: str, severity: str = "medium", company_id: UUID | None = None,
         branch_id: UUID | None = None, ref_type: str | None = None, ref_id: UUID | None = None,
         amount: Decimal | None = None, dedupe_key: str | None = None) -> UUID | None:
    """Add an item to the inbox. Returns its id, or None if an item with the same `dedupe_key` already exists."""
    if severity not in SEVERITIES:
        raise ValidationFailed(f"Severity must be one of: {', '.join(SEVERITIES)}")
    row = s.execute(text(
        "insert into kernel.exception_item (tenant_id, unit_name, kind, severity, company_id, branch_id, ref_type, "
        "ref_id, amount, message, dedupe_key) values (kernel.current_tenant(), :u, :k, :sv, :c, :b, :rt, :ri, :a, "
        ":m, :d) on conflict (tenant_id, dedupe_key) do nothing returning id"),
        {"u": unit, "k": kind, "sv": severity, "c": str(company_id) if company_id else None,
         "b": str(branch_id) if branch_id else None, "rt": ref_type, "ri": str(ref_id) if ref_id else None,
         "a": amount, "m": message[:1000], "d": dedupe_key}).first()
    if row is None:
        return None
    publish(s, Event("exception.raised", "kernel.exception_item", row.id, {
        "unit": unit, "kind": kind, "severity": severity, "company_id": company_id, "branch_id": branch_id,
        "ref_type": ref_type, "ref_id": ref_id, "amount": amount, "message": message[:1000]}))
    item_id: UUID = row.id
    return item_id


def _scope_filter() -> tuple[str, dict[str, str]]:
    """SQL limiting items to the companies and branches the actor may manage exceptions for."""
    scopes = get_context().scopes_with("exceptions.manage")
    if scopes is None:
        return "true", {}
    if not scopes:
        return "false", {}
    parts: list[str] = []
    params: dict[str, str] = {}
    for i, (company, branch) in enumerate(scopes):
        params[f"c{i}"] = str(company)
        if branch is None:
            parts.append(f"company_id = :c{i}")
        else:
            params[f"b{i}"] = str(branch)
            parts.append(f"(company_id = :c{i} and branch_id = :b{i})")
    return "(" + " or ".join(parts) + ")", params


def list_items(s: Session, *, status: str | None = None, unit: str | None = None, kind: str | None = None,
               branch_id: UUID | None = None, limit: int = 100, offset: int = 0) -> list[ExceptionItem]:
    """Items the actor may see, newest first."""
    scope, params = _scope_filter()
    rows = s.execute(text(
        f"select {COLUMNS} from kernel.exception_item where {scope} and (cast(:st as text) is null or status = :st) "
        "and (cast(:u as text) is null or unit_name = :u) and (cast(:k as text) is null or kind = :k) "
        "and (cast(:b as uuid) is null or branch_id = :b) order by created_at desc, id limit :n offset :o"),
        {**params, "st": status, "u": unit, "k": kind, "b": str(branch_id) if branch_id else None,
         "n": min(limit, 500), "o": offset})
    return [ExceptionItem(**r._mapping) for r in rows]


def get_item(s: Session, item_id: UUID) -> ExceptionItem:
    scope, params = _scope_filter()
    row = s.execute(text(f"select {COLUMNS} from kernel.exception_item where id = :i and {scope}"),
                    {**params, "i": str(item_id)}).first()
    if row is None:
        raise NotFound("Item not found")
    return ExceptionItem(**row._mapping)


def change_status(s: Session, item_id: UUID, status: str, note: str) -> ExceptionItem:
    """Explain, resolve or dismiss an item. A note is required."""
    item = get_item(s, item_id)
    if status not in STATUSES:
        raise ValidationFailed(f"Status must be one of: {', '.join(STATUSES)}")
    if status not in TRANSITIONS[item.status]:
        raise ValidationFailed(f"An item that is {item.status} cannot become {status}")
    if not note.strip():
        raise ValidationFailed("A note is required")
    user = get_context().user_id
    s.execute(text(
        "update kernel.exception_item set status = :st, resolution_note = :n, resolved_by = case when :st in "
        "('resolved', 'dismissed') then :u else resolved_by end, resolved_at = case when :st in "
        "('resolved', 'dismissed') then now() else resolved_at end where id = :i"),
        {"st": status, "n": note.strip()[:2000], "u": str(user) if user else None, "i": str(item_id)})
    audit.record(s, status, "kernel.exception_item", item_id, {"kind": item.kind, "note": note.strip()[:500]})
    return get_item(s, item_id)


def assign(s: Session, item_id: UUID, user_id: UUID | None) -> ExceptionItem:
    """Give an item to a user (or take the assignment away)."""
    get_item(s, item_id)
    if user_id is not None and s.execute(text("select 1 from kernel.app_user where id = :u and status = 'active'"),
                                         {"u": str(user_id)}).first() is None:
        raise ValidationFailed("User not found")
    s.execute(text("update kernel.exception_item set assigned_to = :u where id = :i"),
              {"u": str(user_id) if user_id else None, "i": str(item_id)})
    audit.record(s, "assign", "kernel.exception_item", item_id, {"to": user_id})
    return get_item(s, item_id)

"""Reason codes: the managed list of reasons required for voids, refunds, discounts above
policy, price overrides, stock adjustments, write-offs and variances.

Units seed their default codes through the [reason_codes] table of their manifest;
tenants can add their own and deactivate any.
"""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.errors import Conflict, NotFound, ValidationFailed

CATEGORIES = ("void", "refund", "discount", "price_override", "stock_adjustment", "write_off",
              "transfer_variance", "till_variance", "count_variance")
CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,30}$")


@dataclass(frozen=True)
class ReasonCode:
    """One reason a user can pick."""

    id: UUID
    category: str
    code: str
    label: str
    requires_note: bool
    is_active: bool


_COLUMNS = "id, category, code, label, requires_note, is_active"


def list_reasons(s: Session, category: str | None = None, include_inactive: bool = False) -> list[ReasonCode]:
    """Reason codes of the tenant, optionally for one category."""
    rows = s.execute(text(
        f"select {_COLUMNS} from kernel.reason_code "
        "where (cast(:c as text) is null or category = :c) and (is_active or :all) order by category, code"),
        {"c": category, "all": include_inactive})
    return [ReasonCode(**r._mapping) for r in rows]


def create_reason(s: Session, category: str, code: str, label: str, requires_note: bool = False) -> ReasonCode:
    """Add a reason code for the tenant."""
    if category not in CATEGORIES:
        raise ValidationFailed(f"Category must be one of: {', '.join(CATEGORIES)}")
    code = code.strip().upper()
    if not CODE_PATTERN.match(code):
        raise ValidationFailed("Code must be 1-30 capital letters, digits or '_'")
    if not label.strip():
        raise ValidationFailed("Label is required")
    exists = s.execute(text("select 1 from kernel.reason_code where category = :c and code = :k"),
                       {"c": category, "k": code}).first()
    if exists:
        raise Conflict(f"Reason code '{code}' already exists for {category}")
    row = s.execute(text(
        "insert into kernel.reason_code (tenant_id, category, code, label, requires_note) "
        f"values (kernel.current_tenant(), :c, :k, :l, :n) returning {_COLUMNS}"),
        {"c": category, "k": code, "l": label.strip(), "n": requires_note}).one()
    return ReasonCode(**row._mapping)


def set_reason_active(s: Session, reason_id: UUID, active: bool) -> None:
    """Activate or deactivate a reason code. Codes are never deleted: old records refer to them."""
    done = s.execute(text("update kernel.reason_code set is_active = :a, updated_at = now() where id = :i "
                          "returning id"), {"a": active, "i": str(reason_id)}).first()
    if done is None:
        raise NotFound("Reason code not found")


def check_reason(s: Session, category: str, reason_id: UUID | None, note: str | None = None) -> ReasonCode:
    """Check that a reason was given, belongs to `category`, is active, and has a note if it needs one.

    Call this in every service that voids, refunds, overrides or adjusts.
    """
    if reason_id is None:
        raise ValidationFailed("A reason is required")
    row = s.execute(text(f"select {_COLUMNS} from kernel.reason_code where id = :i"), {"i": str(reason_id)}).first()
    if row is None or row.category != category:
        raise ValidationFailed(f"Choose a reason from the '{category}' list")
    if not row.is_active:
        raise ValidationFailed(f"Reason '{row.code}' is no longer in use")
    if row.requires_note and not (note and note.strip()):
        raise ValidationFailed(f"Reason '{row.code}' needs a note")
    return ReasonCode(**row._mapping)

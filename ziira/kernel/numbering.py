"""Document numbering: human document numbers per document type, company and branch.

Numbers come from kernel.document_series, e.g. prefix "ADJ-THK-" and padding 6 gives
ADJ-THK-000001, ADJ-THK-000002, ... The series row is locked while a number is taken,
so two transactions never get the same number, and a rolled-back transaction gives its
number back (no gaps from failures).
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.errors import NotFound, ValidationFailed


@dataclass(frozen=True)
class Series:
    """One numbering series."""

    id: UUID
    company_id: UUID
    branch_id: UUID | None
    doc_type: str
    prefix: str
    next_number: int
    padding: int


def _find(s: Session, company_id: UUID, branch_id: UUID | None, doc_type: str) -> UUID | None:
    return s.execute(text(
        "select id from kernel.document_series where company_id = :c and doc_type = :d "
        "and branch_id is not distinct from :b"),
        {"c": str(company_id), "b": str(branch_id) if branch_id else None, "d": doc_type}).scalar()


def _default_prefix(s: Session, branch_id: UUID | None, prefix: str) -> str:
    if branch_id is None:
        return f"{prefix}-"
    code = s.execute(text("select code from kernel.branch where id = :b"), {"b": str(branch_id)}).scalar()
    if code is None:
        raise NotFound("Branch not found")
    return f"{prefix}-{code}-"


def next_document_number(s: Session, *, company_id: UUID, branch_id: UUID | None, doc_type: str,
                         prefix: str) -> str:
    """Take the next number for this document type, creating the series on first use.

    `prefix` (e.g. "ADJ") is used only when the series is created: the series prefix becomes
    "ADJ-<branch code>-", or "ADJ-" for company-level documents. Tenants can change it later.
    """
    if not doc_type or not prefix:
        raise ValidationFailed("doc_type and prefix are required")
    if s.execute(text("select 1 from kernel.company where id = :c"), {"c": str(company_id)}).first() is None:
        raise NotFound("Company not found")
    # Serialise creation of a missing series (the unique constraint does not cover a null branch).
    s.execute(text("select pg_advisory_xact_lock(hashtext(:k))"),
              {"k": f"series:{company_id}:{branch_id}:{doc_type}"})
    if _find(s, company_id, branch_id, doc_type) is None:
        s.execute(text(
            "insert into kernel.document_series (tenant_id, company_id, branch_id, doc_type, prefix) "
            "values (kernel.current_tenant(), :c, :b, :d, :p)"),
            {"c": str(company_id), "b": str(branch_id) if branch_id else None, "d": doc_type,
             "p": _default_prefix(s, branch_id, prefix)})
    row = s.execute(text(
        "update kernel.document_series set next_number = next_number + 1, updated_at = now() "
        "where company_id = :c and doc_type = :d and branch_id is not distinct from :b "
        "returning prefix, next_number - 1 as number, padding"),
        {"c": str(company_id), "b": str(branch_id) if branch_id else None, "d": doc_type}).one()
    return f"{row.prefix}{str(row.number).zfill(row.padding)}"


def list_series(s: Session) -> list[Series]:
    """All numbering series of the tenant."""
    rows = s.execute(text(
        "select id, company_id, branch_id, doc_type, prefix, next_number, padding "
        "from kernel.document_series order by doc_type, prefix"))
    return [Series(**r._mapping) for r in rows]


def update_series(s: Session, series_id: UUID, *, prefix: str | None = None, padding: int | None = None,
                  next_number: int | None = None) -> Series:
    """Change a series' prefix, padding or next number. The next number can only move forward."""
    current = s.execute(text(
        "select id, company_id, branch_id, doc_type, prefix, next_number, padding "
        "from kernel.document_series where id = :i for update"), {"i": str(series_id)}).first()
    if current is None:
        raise NotFound("Numbering series not found")
    if padding is not None and not 1 <= padding <= 12:
        raise ValidationFailed("Padding must be between 1 and 12")
    if next_number is not None and next_number < current.next_number:
        raise ValidationFailed("The next number cannot go back; that would repeat numbers")
    if prefix is not None and not prefix.strip():
        raise ValidationFailed("Prefix cannot be empty")
    s.execute(text(
        "update kernel.document_series set prefix = coalesce(:p, prefix), padding = coalesce(:pad, padding), "
        "next_number = coalesce(:n, next_number), updated_at = now() where id = :i"),
        {"p": prefix.strip() if prefix else None, "pad": padding, "n": next_number, "i": str(series_id)})
    return next(x for x in list_series(s) if x.id == series_id)

"""Which rate applies to a piece of work: pure rules, no database.

A rate card row names the work it covers by up to five things: a project, a client, a person, a service and a role.
A row that leaves a thing out covers every value of it. A row *matches* a piece of work when each thing it names equals
the work's. When several rows match, the most specific one wins; specificity is a sum of weights that rank the things
strictly, so a more important thing always beats any mix of less important ones:

    project (32) > client (16) > person (8) > service (4) > role (2)

So "this project, this role" (34) beats "this client, this person" (24), and "this person" (8) beats "this role"
(2). Rows must also be in force on the day of the work (`effective_from` <= day <= `effective_to`). Two rows with
the same specificity are decided by the later `effective_from`, then by the later entry (`seq`), so a newer card
always replaces an older one of the same kind. No match means no rate (the work is unpriced until someone sets one).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

WEIGHTS = {"project": 32, "client": 16, "user": 8, "service": 4, "role": 2}


@dataclass(frozen=True)
class RateRow:
    """One row of a rate card."""

    id: UUID
    kind: str                       # "bill" (what the client pays per hour) or "cost" (what an hour costs the business)
    rate: Decimal                   # per hour
    effective_from: date
    effective_to: date | None = None
    project_id: UUID | None = None
    client_id: UUID | None = None
    user_id: UUID | None = None
    service_id: UUID | None = None
    role_title: str | None = None
    seq: int = 0                    # order of entry, to settle exact ties


@dataclass(frozen=True)
class WorkContext:
    """The work a rate is wanted for."""

    day: date
    project_id: UUID | None = None
    client_id: UUID | None = None
    user_id: UUID | None = None
    service_id: UUID | None = None
    role_title: str | None = None


def _norm(role: str | None) -> str | None:
    return role.strip().casefold() if role and role.strip() else None


def in_force(row: RateRow, day: date) -> bool:
    return row.effective_from <= day and (row.effective_to is None or day <= row.effective_to)


def matches(row: RateRow, work: WorkContext) -> bool:
    """True when every thing the row names equals the work's, and the row is in force on the day."""
    if not in_force(row, work.day):
        return False
    pairs = ((row.project_id, work.project_id), (row.client_id, work.client_id), (row.user_id, work.user_id),
             (row.service_id, work.service_id), (_norm(row.role_title), _norm(work.role_title)))
    return all(want is None or want == have for want, have in pairs)


def specificity(row: RateRow) -> int:
    """How many weights the row names (see the module note)."""
    named = {"project": row.project_id, "client": row.client_id, "user": row.user_id, "service": row.service_id,
             "role": _norm(row.role_title)}
    return sum(w for key, w in WEIGHTS.items() if named[key] is not None)


def resolve(rows: list[RateRow], work: WorkContext, kind: str = "bill") -> RateRow | None:
    """The row that prices the work, or None."""
    found = [r for r in rows if r.kind == kind and matches(r, work)]
    if not found:
        return None
    return max(found, key=lambda r: (specificity(r), r.effective_from, r.seq))


def overlaps(a: RateRow, b: RateRow) -> bool:
    """True when two rows of the same kind name exactly the same things and are in force on a common day (the newer
    one wins, but a card that does this is probably a mistake worth warning about)."""
    if a.kind != b.kind or (a.project_id, a.client_id, a.user_id, a.service_id, _norm(a.role_title)) != (
            b.project_id, b.client_id, b.user_id, b.service_id, _norm(b.role_title)):
        return False
    a_end = a.effective_to or date.max
    b_end = b.effective_to or date.max
    return a.effective_from <= b_end and b.effective_from <= a_end

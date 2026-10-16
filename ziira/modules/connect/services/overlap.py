"""Running the business twice: which areas both an active connected system and Core units cover.

An area is **supplied** by a connection once it has read the entities that make it up (sales, customer invoices, stock
movements...). Core **covers** it when a unit that runs it is switched on and in real use: its `connect.core_coverage`
provider reports activity (a posted sale, a stock movement that is not an opening balance) in the last days, by branch.
Where both hold, the standalone checks for that area and branch stay silent, because Core's own checks look at the live
data and the connected copy is a second, older view of the same business. A business that wants both keeps both
(`keep_both`, remembered on the connection) and findings carry their source.
"""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.connect.permissions import CONNECT_MANAGE, CONNECT_VIEW
from ziira.modules.connect.public import CORE_COVERAGE, OVERLAP_AREAS, AreaOverlap, CoreCoverage, Overlap
from ziira.modules.connect.repository import connect_repo as repo
from ziira.sdk import (
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    company_today,
    current_context,
    implementations,
)

DAYS = 14                                   # how recent Core's activity must be to count as "in use"
SIMPLE_AREAS = {"sales": "sales", "stock_movements": "stock", "payments": "payments", "expenses": "expenses",
                "journal_entries": "journals"}
LIVE_STATUSES = ("active", "error")         # a paused or disconnected connection no longer feeds the checks


def core_activity(session: Session, company_id: UUID | None, days: int) -> dict[str, set[UUID | None]]:
    """area -> branches where Core has real activity in the last `days` days, from every unit that reports it."""
    today = company_today(session, company_id) if company_id else date.today()
    since = today - timedelta(days=days)
    found: dict[str, set[UUID | None]] = {}
    for provider in implementations(session, CORE_COVERAGE):
        assert isinstance(provider, CoreCoverage)
        for area, branches in provider.active(session, company_id, since).items():
            if area in OVERLAP_AREAS and branches:
                found.setdefault(area, set()).update(branches)
    return found


def supplied_areas(session: Session, company_id: UUID | None, *, honour_choice: bool) -> dict[str, list[UUID]]:
    """area -> the live connections that supply it (they have read the entities of it to the end at least once)."""
    where = "k.status = any(:live)" + (" and k.overlap_choice is null" if honour_choice else "")
    params: dict[str, Any] = {"live": list(LIVE_STATUSES)}
    if company_id is not None:
        where += " and k.company_id = :c"
        params["c"] = str(company_id)
    found: dict[str, list[UUID]] = {}
    for r in session.execute(text(
            "select c.connection_id, c.entity from connect.cursor c "
            f"join connect.connection k on k.id = c.connection_id where {where} order by c.connection_id"), params):
        if r.entity in SIMPLE_AREAS:
            found.setdefault(SIMPLE_AREAS[r.entity], []).append(r.connection_id)
        elif r.entity == "invoices":
            for kind in session.execute(text(
                    "select distinct kind from connect.src_invoice where connection_id = :k and status <> 'cancelled'"),
                    {"k": str(r.connection_id)}).scalars():
                found.setdefault("receivables" if kind == "customer" else "payables", []).append(r.connection_id)
    return found


def coverage_overlap(session: Session, company_id: UUID | None = None, *, days: int = DAYS,
                     honour_choice: bool = True) -> Overlap:
    """The areas Core covers that a live connection also supplies (see `connect.public.coverage_overlap`)."""
    supplied = supplied_areas(session, company_id, honour_choice=honour_choice)
    if not supplied:
        return Overlap((), days)
    active = core_activity(session, company_id, days)
    return Overlap(tuple(AreaOverlap(area, frozenset(active[area]), tuple(dict.fromkeys(supplied[area])))
                         for area in OVERLAP_AREAS if area in supplied and area in active), days)


def covered_by_core(session: Session, company_id: UUID, areas: tuple[str, ...]) -> Overlap | None:
    """For a standalone check: the overlap when it touches any of `areas`; None when the check has nothing to skip."""
    if not areas:
        return None
    found = coverage_overlap(session, company_id)
    return found if any(a.area in areas for a in found.areas) else None


def set_choice(session: Session, connection_id: UUID, choice: str | None) -> None:
    """Remember that the business keeps checking this connection while Core covers the same areas (or forget it)."""
    row = repo.get_connection(session, connection_id)
    if row is None:
        raise NotFound("Connection not found")
    ctx = current_context()
    ctx.require(CONNECT_MANAGE, company_id=row.company_id)
    if choice not in (None, "keep_both"):
        raise ValidationFailed("The choice is keep_both, or none")
    if choice is None:
        session.execute(text("update connect.connection set overlap_choice = null, overlap_choice_at = null, "
                             "overlap_choice_by = null where id = :i"), {"i": str(connection_id)})
    else:
        session.execute(text("update connect.connection set overlap_choice = :ch, overlap_choice_at = now(), "
                             "overlap_choice_by = :u where id = :i"),
                        {"ch": choice, "u": str(ctx.user_id) if ctx.user_id else None, "i": str(connection_id)})
    audit_record(session, "overlap_choice", "connect.connection", connection_id, {"choice": choice})


def overview(session: Session, company_id: UUID) -> tuple[Overlap, bool, list[tuple[UUID, str, str, bool]]]:
    """For the banners: every area both cover (including connections the business chose to keep), whether a choice is
    still to be made, and the connections concerned as (id, name, status, kept both)."""
    current_context().require(CONNECT_VIEW, company_id=company_id)
    every = coverage_overlap(session, company_id, honour_choice=False)
    pending = coverage_overlap(session, company_id, honour_choice=True).overlapping
    ids = {c for found in every.areas for c in found.connection_ids}
    concerned = [(r.id, r.name, r.status, r.overlap_choice == "keep_both")
                 for r in repo.list_connections(session, {company_id}) if r.id in ids]
    return every, pending, concerned

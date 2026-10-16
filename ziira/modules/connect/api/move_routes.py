"""HTTP endpoints for "Move to Ziira Core" (bring a connected system's data into Core units through Data Import) and
for the overlap between a connected system and Core units that cover the same ground."""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from ziira.modules.connect.api.move_schemas import (
    AreaOverlapOut,
    BatchStateOut,
    BranchLineOut,
    BranchStockOut,
    KindPlanOut,
    LocationChoiceOut,
    MoveIn,
    MoveKindOut,
    MoveOptionsOut,
    MoveOut,
    MoveReasonOut,
    MoveSuggestionOut,
    OverlapChoiceIn,
    OverlapConnectionOut,
    OverlapOut,
    PlanOut,
    UndoIn,
)
from ziira.modules.connect.permissions import CONNECT_MANAGE, CONNECT_VIEW
from ziira.modules.connect.services import connections, move, overlap
from ziira.sdk import DB_SESSION, Session, check_company, require_permission

router = APIRouter()
VIEW = [Depends(require_permission(CONNECT_VIEW))]
MANAGE = [Depends(require_permission(CONNECT_MANAGE))]


def _options(body: MoveIn) -> move.MoveOptions:
    return move.MoveOptions(tuple(body.kinds), body.as_of, (body.unit or "").strip() or None,
                            (body.tax_code or "").strip() or None, dict(body.locations))


def _kind(k: move.KindPlan) -> KindPlanOut:
    return KindPlanOut(
        kind=k.kind, title=k.title, selected=k.selected, available=k.available, allowed=k.allowed,  # type: ignore[arg-type]
        needs=k.needs, candidates=k.candidates, create=k.create, exists=k.exists, skipped=k.skipped,
        reasons=[MoveReasonOut(status=r.status, reason=r.reason, count=r.count, examples=r.examples)  # type: ignore[arg-type]
                 for r in k.reasons], sample=k.sample, warnings=k.warnings)


def _move(m: move.MoveState) -> MoveOut:
    return MoveOut(
        id=m.id, connection_id=m.connection_id, company_id=m.company_id, as_of=m.as_of, state=m.state,  # type: ignore[arg-type]
        needs_attention=m.needs_attention, created_at=m.created_at, finished_at=m.finished_at,
        batches=[BatchStateOut(kind=b.kind, title=b.title, phase=b.phase, batch_id=b.batch_id,  # type: ignore[arg-type]
                               status=b.status, staged=b.staged, counts=b.counts, reversible=b.reversible,
                               reversal_note=b.reversal_note) for b in m.batches])


@router.get("/connections/{connection_id}/move/options", response_model=MoveOptionsOut, dependencies=MANAGE)
def get_move_options(connection_id: UUID, session: Session = DB_SESSION) -> object:
    """The first step of "Move to Ziira Core": which kinds of record can be brought over now (and which need a unit
    switched on), what the other system holds, and the branches' stock locations to choose from."""
    o = move.options(session, connection_id)
    return MoveOptionsOut(
        connection_id=connection_id, as_of=o.as_of, source_counts=o.source_counts,
        kinds=[MoveKindOut(kind=k.kind, title=k.title, available=k.available, allowed=k.allowed,  # type: ignore[arg-type]
                           needs=k.needs) for k in o.kinds],
        mapped_branches=[BranchStockOut(branch_id=b, branch_name=name,
                                        locations=[LocationChoiceOut(code=c, name=n) for c, n in places])
                         for b, name, places in o.branches],
        unmapped_branches=o.unmapped_branches, running_move_id=o.running_move_id, last_move_id=o.last_move_id)


@router.post("/connections/{connection_id}/move/preview", response_model=PlanOut, dependencies=MANAGE)
def post_move_preview(connection_id: UUID, body: MoveIn, session: Session = DB_SESSION) -> object:
    """What bringing the chosen records over would do: for each kind what would be created, what is already in Ziira
    and what cannot be brought over, and why. Checked by the owning units' own rules. Writes nothing."""
    plan = move.preview(session, connection_id, _options(body))
    return PlanOut(
        connection_id=connection_id, as_of=plan.as_of, kinds=[_kind(k) for k in plan.kinds],
        branches=[BranchLineOut(external_ref=b.external_ref, external_name=b.external_name, branch_id=b.branch_id,
                                branch_name=b.branch_name, ignored=b.ignored) for b in plan.branches],
        users=plan.users)


@router.post("/connections/{connection_id}/move", response_model=MoveOut, status_code=status.HTTP_202_ACCEPTED,
             dependencies=MANAGE)
def post_move(connection_id: UUID, body: MoveIn, session: Session = DB_SESSION) -> object:
    """Bring the records over: one Data Import batch per kind, tagged with this connection, imported in the background.
    Customers, suppliers and products first, then stock and balances. Safe to run again: nothing is created twice."""
    move_id = move.start(session, connection_id, _options(body))
    return _move(move.status(session, move_id))


@router.get("/connections/{connection_id}/moves", response_model=list[MoveOut], dependencies=MANAGE)
def get_moves(connection_id: UUID, session: Session = DB_SESSION) -> object:
    """Earlier moves from this connection, newest first."""
    return [_move(m) for m in move.list_moves(session, connection_id)]


@router.get("/moves/{move_id}", response_model=MoveOut, dependencies=MANAGE)
def get_one_move(move_id: UUID, session: Session = DB_SESSION) -> object:
    """Progress of a move (poll it): each batch with its counts, and whether anything needs attention."""
    return _move(move.status(session, move_id))


@router.post("/moves/{move_id}/undo", response_model=MoveOut, dependencies=MANAGE)
def post_undo(move_id: UUID, body: UndoIn, session: Session = DB_SESSION) -> object:
    """Take back what can be taken back (opening balances, through Data Import's reverse). Products, customers,
    suppliers and stock cannot be deleted; switch unwanted ones off or adjust them in their own screens."""
    return _move(move.undo(session, move_id, body.reason))


@router.get("/move/suggestion", response_model=MoveSuggestionOut, dependencies=VIEW)
def get_suggestion(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Whether to offer "Ready to run on Ziira? Move your data" for this company."""
    check_company(session, company_id)
    suggest, connection_id = move.suggestion(session, company_id)
    return MoveSuggestionOut(suggest=suggest, connection_id=connection_id)


@router.get("/overlap", response_model=OverlapOut, dependencies=VIEW)
def get_overlap(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Areas that a connected system and Core units both cover, and whether the business still has to choose between
    pausing the connection and keeping both. Standalone checks stay silent where Core covers the same branch."""
    check_company(session, company_id)
    found, pending, concerned = overlap.overview(session, company_id)
    return OverlapOut(
        overlapping=pending, days=found.days,
        areas=[AreaOverlapOut(area=a.area, branch_ids=sorted((b for b in a.branch_ids if b is not None), key=str),  # type: ignore[arg-type]
                              company_wide=None in a.branch_ids, connection_ids=list(a.connection_ids))
               for a in found.areas],
        connections=[OverlapConnectionOut(id=i, name=n, status=s, kept_both=k) for i, n, s, k in concerned])


@router.post("/connections/{connection_id}/overlap-choice", response_model=OverlapOut, dependencies=MANAGE)
def post_overlap_choice(connection_id: UUID, body: OverlapChoiceIn, session: Session = DB_SESSION) -> object:
    """Remember "keep both" for this connection (its checks go on while Core covers the same areas), or ask again."""
    row = connections.get(session, connection_id, manage=True)
    overlap.set_choice(session, connection_id, body.choice)
    return get_overlap(row.company_id, session)

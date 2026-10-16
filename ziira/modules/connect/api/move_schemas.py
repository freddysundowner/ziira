"""Request and response shapes for "Move to Ziira Core" and for the overlap between a connected system and Core."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Kind = Literal["products", "customers", "suppliers", "opening_stock", "customer_balances", "supplier_balances"]


class MoveIn(BaseModel):
    kinds: list[Kind] = Field(min_length=1, description="What to bring over")
    as_of: date = Field(description="The go-live date: stock and balances are as at this day")
    unit: str | None = Field(default=None, max_length=20, description="Code of the unit of measure new products get")
    tax_code: str | None = Field(default=None, max_length=20, description="Code of the tax class new products get")
    locations: dict[UUID, str] = Field(default_factory=dict, description="Ziira branch -> stock location code")


class MoveReasonOut(BaseModel):
    status: Literal["exists", "skipped"]
    reason: str
    count: int
    examples: list[str]


class KindPlanOut(BaseModel):
    kind: Kind
    title: str
    selected: bool
    available: bool = Field(description="False when the unit that keeps this kind of record is switched off")
    allowed: bool = Field(description="False when the person may not create these records")
    needs: list[str] = Field(description="Units to switch on first (names)")
    candidates: int
    create: int
    exists: int
    skipped: int
    reasons: list[MoveReasonOut]
    sample: list[dict[str, str]]
    warnings: list[str]


class BranchLineOut(BaseModel):
    external_ref: str
    external_name: str | None
    branch_id: UUID | None
    branch_name: str | None
    ignored: bool


class PlanOut(BaseModel):
    connection_id: UUID
    as_of: date
    kinds: list[KindPlanOut]
    branches: list[BranchLineOut]
    users: int = Field(description="Users of the other system: they are not brought over; invite them under Users")


class BatchStateOut(BaseModel):
    kind: Kind
    title: str
    phase: int
    batch_id: UUID | None
    status: str = Field(description="The batch's status, or waiting / nothing_new / unavailable")
    staged: int
    counts: dict[str, int]
    reversible: bool
    reversal_note: str


class MoveOut(BaseModel):
    id: UUID
    connection_id: UUID
    company_id: UUID
    as_of: date
    state: Literal["running", "done"]
    needs_attention: bool
    batches: list[BatchStateOut]
    created_at: datetime
    finished_at: datetime | None


class UndoIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class LocationChoiceOut(BaseModel):
    code: str
    name: str


class BranchStockOut(BaseModel):
    branch_id: UUID
    branch_name: str | None
    locations: list[LocationChoiceOut]


class MoveKindOut(BaseModel):
    kind: Kind
    title: str
    available: bool
    allowed: bool
    needs: list[str]


class MoveOptionsOut(BaseModel):
    """What the first step of the wizard needs: which kinds can be brought, what the other system holds, and the
    defaults to choose."""

    connection_id: UUID
    as_of: date
    kinds: list[MoveKindOut]
    source_counts: dict[str, int]
    mapped_branches: list[BranchStockOut]
    unmapped_branches: int
    running_move_id: UUID | None
    last_move_id: UUID | None


class MoveSuggestionOut(BaseModel):
    suggest: bool = Field(description="True when data was read from a connected system and Core units that can take "
                                      "it are switched on, and nothing has been moved yet")
    connection_id: UUID | None


class AreaOverlapOut(BaseModel):
    area: Literal["sales", "receivables", "payables", "stock", "payments", "expenses", "journals"]
    branch_ids: list[UUID]
    company_wide: bool
    connection_ids: list[UUID]


class OverlapConnectionOut(BaseModel):
    id: UUID
    name: str
    status: str
    kept_both: bool


class OverlapOut(BaseModel):
    overlapping: bool = Field(description="True when something is covered twice and the business has not chosen yet")
    days: int
    areas: list[AreaOverlapOut]
    connections: list[OverlapConnectionOut]


class OverlapChoiceIn(BaseModel):
    choice: Literal["keep_both"] | None = Field(description="keep_both, or null to ask again")

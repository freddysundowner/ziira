"""Request and response shapes for the Connectors API. Secrets are write-only: no response ever carries one."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

Status = Literal["active", "paused", "error", "disconnected"]


class ConfigFieldOut(BaseModel):
    name: str
    label: str
    secret: bool
    required: bool
    help: str
    example: str


class FileFieldOut(BaseModel):
    name: str
    label: str
    required: bool
    help: str
    example: str
    aliases: list[str]


class ConnectorKindOut(BaseModel):
    kind: str
    title: str
    description: str
    group: str
    entities: list[str]
    config_fields: list[ConfigFieldOut]
    needs_oauth: bool
    freshness: Literal["live", "daily", "on_upload"]
    how_to: str
    file_fields: list[FileFieldOut]


class ConnectionIn(BaseModel):
    company_id: UUID
    kind: str = Field(max_length=60)
    name: str = Field(min_length=2, max_length=80)
    config: dict[str, Any] = Field(default_factory=dict,
        description="The settings of the kind; secrets are stored encrypted")
    auto_create_branches: bool = False
    sync_every_minutes: int | None = Field(default=None, ge=15, le=10080)


class ConnectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    config: dict[str, Any] | None = Field(default=None,
        description="Settings to change; a blank secret is kept as it is")
    auto_create_branches: bool | None = None
    sync_every_minutes: int | None = Field(default=None, ge=15, le=10080)


class EntityStatusOut(BaseModel):
    entity: str
    complete_at: datetime | None = Field(description="When the entity was last read to the end")
    data_through: datetime | None = None


class ConnectionOut(BaseModel):
    id: UUID
    company_id: UUID
    kind: str
    kind_title: str
    group: str
    name: str
    status: Status
    config: dict[str, Any]
    secrets_set: list[str]
    freshness: str
    entities: list[EntityStatusOut]
    auto_create_branches: bool
    sync_every_minutes: int
    last_sync_at: datetime | None
    last_success_at: datetime | None
    next_sync_at: datetime | None
    failures: int
    last_error: str | None
    needs_oauth: bool
    created_at: datetime


class ConnectionDetailOut(ConnectionOut):
    counts: dict[str, int]
    unmapped_branches: int


class TestOut(BaseModel):
    ok: bool
    message: str
    details: dict[str, Any]


class SyncIn(BaseModel):
    full: bool = Field(default=False, description="Read everything again from the start")


class SyncOut(BaseModel):
    queued: bool = Field(description="False when a read of this connection is already waiting")


class DisconnectIn(BaseModel):
    delete_data: bool = Field(default=False, description="Also delete everything read from the system")


class DisconnectOut(BaseModel):
    removed: dict[str, int]


class SyncRunOut(BaseModel):
    id: UUID
    entity: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    status: Literal["running", "ok", "partial", "failed"]
    records_read: int
    records_new: int
    records_changed: int
    records_skipped: int
    error: str | None
    notes: list[str]


class BranchMapOut(BaseModel):
    external_ref: str
    external_name: str | None
    branch_id: UUID | None
    branch_name: str | None
    ignored: bool


class BranchMapIn(BaseModel):
    external_ref: str = Field(min_length=1, max_length=300)
    branch_id: UUID | None = None
    ignored: bool = False
    create_branch: bool = Field(default=False, description="Make a new Ziira branch for it and map to that")


class FileSettingsIn(BaseModel):
    mapping: dict[str, str | None] = Field(description="field -> the file's column ('' means: not in my file)")
    decimal_separator: Literal[".", ",", "auto"] = "auto"
    date_format: Literal["iso", "dmy", "mdy", "auto"] = "auto"
    delimiter: Literal[",", ";", "\t", "|"] | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class RowIssueOut(BaseModel):
    row: int
    message: str


class FieldGuessOut(BaseModel):
    name: str
    label: str
    required: bool
    column: str | None
    examples: list[str]
    simple: bool


class ReviewRowOut(BaseModel):
    row: int
    problem: str
    cells: list[str]


class ScanOut(BaseModel):
    id: UUID
    status: Literal["queued", "reading", "ready", "failed"]
    pages: int
    pages_done: int
    error: str | None


class WrongKindOut(BaseModel):
    kind: str
    title: str


class PreviewOut(BaseModel):
    filename: str
    state: Literal["ready", "reading", "failed", "password_required", "wrong_password"]
    message: str
    source: Literal["csv", "excel", "pdf", "scan"]
    delimiter: str
    headers: list[str]
    warnings: list[str]
    mapping: dict[str, str | None]
    suggested: dict[str, str | None]
    settings: dict[str, Any]
    sample: list[dict[str, str]]
    total_rows: int
    valid_rows: int
    issues: list[RowIssueOut]
    issue_count: int
    missing: list[str]
    records: dict[str, int]
    first_moment: datetime | None
    last_moment: datetime | None
    confidence: float
    needs_check: bool
    check_reasons: list[str]
    date_ambiguous: bool
    date_examples: list[str]
    money_in: Decimal | None
    money_out: Decimal | None
    total: Decimal | None
    wrong_kind: WrongKindOut | None
    fields: list[FieldGuessOut]
    review_rows: list[ReviewRowOut]
    scan: ScanOut | None


class FileUploadOut(BaseModel):
    preview: PreviewOut
    committed: bool
    new: int
    changed: int
    skipped: int


class DetectOut(BaseModel):
    kind: str | None
    title: str
    confidence: float
    picture: bool
    alternatives: list[WrongKindOut]
    state: Literal["ready", "password_required", "wrong_password"]
    message: str


class OcrStatusOut(BaseModel):
    available: bool
    message: str


class CellFix(BaseModel):
    row: int = Field(ge=1, description="the line number shown in the problem list")
    column: int = Field(ge=0, le=200, description="position of the column")
    value: str = Field(max_length=500)


class ScanFixIn(BaseModel):
    fixes: list[CellFix] = Field(min_length=1, max_length=500)


class CoverageCheckOut(BaseModel):
    code: str
    title: str
    active: bool
    needs: list[str]
    connect: list[str]


class CoverageAreaOut(BaseModel):
    area: str
    active: int
    total: int
    checks: list[CoverageCheckOut]


class CoverageOut(BaseModel):
    connected: dict[str, int]
    areas: list[CoverageAreaOut]
    as_of: datetime

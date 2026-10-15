"""Request and response shapes for the Data Import API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ColumnOut(BaseModel):
    name: str
    required: bool
    description: str
    example: str
    total: str | None


class KindOut(BaseModel):
    kind: str
    title: str
    description: str
    permission: str
    reversible: bool
    reversal_note: str
    needs_go_live: bool
    whole_file: bool
    columns: list[ColumnOut]


class CountsOut(BaseModel):
    pending: int
    valid: int
    invalid: int
    imported: int
    skipped: int
    failed: int
    reverted: int


class OptionsOut(BaseModel):
    decimal_separator: str
    date_format: str
    as_of: date | None = None
    tolerance: Decimal = Decimal(0)
    confirmed: str | None = None


class FileCheckOut(BaseModel):
    """What was found wrong with a whole file taken together (a trial balance that does not balance)."""

    problems: list[str] = []
    confirm: str | None = None
    notes: list[str] = []


class BatchOut(BaseModel):
    id: UUID
    company_id: UUID
    kind: str
    kind_title: str
    filename: str
    status: Literal["uploaded", "validated", "committing", "done", "reverted"]
    delimiter: str
    headers: list[str]
    mapping: dict[str, str | None]
    options: OptionsOut
    file_check: FileCheckOut
    warnings: list[str]
    columns: list[ColumnOut]
    counts: CountsOut
    total_rows: int
    reversible: bool
    needs_go_live: bool
    whole_file: bool
    created_at: datetime
    committed_at: datetime | None
    finished_at: datetime | None
    reverted_at: datetime | None
    revert_reason: str | None


class MappingIn(BaseModel):
    columns: dict[str, str | None] = Field(description="Field name -> the file's column header (null: not in the file)")
    decimal_separator: Literal[".", ","] | None = Field(default=None, description="How the file writes decimals")
    date_format: Literal["iso", "dmy", "mdy"] | None = Field(default=None, description="How the file writes dates")


class RowOut(BaseModel):
    row_no: int
    status: Literal["pending", "valid", "invalid", "imported", "skipped", "failed", "reverted"]
    errors: list[str]
    raw: list[str]
    values: dict[str, str]
    record_id: UUID | None


class RowsOut(BaseModel):
    total: int
    rows: list[RowOut]


class TotalOut(BaseModel):
    label: str
    in_file: Decimal
    expected: Decimal
    in_ziira: Decimal
    not_imported: Decimal
    difference: Decimal
    matches: bool
    money: bool


class ReportOut(BaseModel):
    batch: BatchOut
    rows_in_file: int
    totals: list[TotalOut]
    problems: list[str]
    reconciled: bool


class ReverseIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500, description="Why the whole import is being undone")

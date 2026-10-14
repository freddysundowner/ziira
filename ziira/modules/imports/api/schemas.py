"""Request and response shapes for the Data Import API."""

from datetime import datetime
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
    columns: list[ColumnOut]


class CountsOut(BaseModel):
    pending: int
    valid: int
    invalid: int
    imported: int
    skipped: int
    failed: int


class OptionsOut(BaseModel):
    decimal_separator: str
    date_format: str


class BatchOut(BaseModel):
    id: UUID
    company_id: UUID
    kind: str
    kind_title: str
    filename: str
    status: Literal["uploaded", "validated", "committing", "done"]
    delimiter: str
    headers: list[str]
    mapping: dict[str, str | None]
    options: OptionsOut
    warnings: list[str]
    columns: list[ColumnOut]
    counts: CountsOut
    total_rows: int
    reversible: bool
    created_at: datetime
    committed_at: datetime | None
    finished_at: datetime | None


class MappingIn(BaseModel):
    columns: dict[str, str | None] = Field(description="Field name -> the file's column header (null: not in the file)")
    decimal_separator: Literal[".", ","] | None = Field(default=None, description="How the file writes decimals")
    date_format: Literal["iso", "dmy", "mdy"] | None = Field(default=None, description="How the file writes dates")


class RowOut(BaseModel):
    row_no: int
    status: Literal["pending", "valid", "invalid", "imported", "skipped", "failed"]
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

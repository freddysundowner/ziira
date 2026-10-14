"""Request and response shapes for the finance API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount, page_limit  # noqa: F401  (page_limit re-exported for routes)

Money = Annotated[Amount, Field(ge=0)]


class AccountIn(BaseModel):
    company_id: UUID
    code: str = Field(max_length=20, examples=["6700"])
    name: str = Field(max_length=200, examples=["Repairs and maintenance"])
    type: Literal["asset", "liability", "equity", "income", "expense"]
    subtype: str | None = Field(default=None, max_length=40)
    parent_id: UUID | None = None


class AccountUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    type: str
    subtype: str | None
    parent_id: UUID | None
    is_control: bool
    is_active: bool


class RuleIn(BaseModel):
    company_id: UUID
    doc_type: str = Field(max_length=40, examples=["stock_movement"])
    line_role: str = Field(max_length=40, examples=["shrinkage"])
    account_id: UUID
    side: Literal["debit", "credit"]
    conditions: dict[str, str] = Field(default_factory=dict, examples=[{"movement_type": "write_off"}])
    priority: int = Field(default=100, ge=1, le=1000)


class RuleUpdateIn(BaseModel):
    account_id: UUID


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    doc_type: str
    line_role: str
    account_id: UUID
    side: str
    conditions: dict[str, str]
    priority: int


class PeriodOpenIn(BaseModel):
    company_id: UUID
    day: date = Field(description="Any date in the month")


class PeriodStatusIn(BaseModel):
    status: Literal["open", "soft_closed", "locked"]


class PeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    start_date: date
    end_date: date
    status: str
    closed_by: UUID | None
    closed_at: datetime | None


class ChecklistOut(BaseModel):
    ready: bool
    problems: list[str]


class EntryLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    branch_id: UUID | None
    debit: Decimal
    credit: Decimal
    party_type: str | None
    party_id: UUID | None
    description: str | None


class EntrySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    number: str
    entry_date: date
    source_type: str | None
    source_id: UUID | None
    description: str | None
    is_manual: bool
    reversal_of_id: UUID | None
    posted_at: datetime


class EntryOut(EntrySummaryOut):
    approved_by: UUID | None
    reversed_by: UUID | None
    lines: list[EntryLineOut]


class ReverseIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    entry_date: date | None = Field(default=None, description="Defaults to today")


class ManualLineIn(BaseModel):
    account_id: UUID
    debit: Money = Decimal(0)
    credit: Money = Decimal(0)
    branch_id: UUID | None = None
    description: str | None = Field(default=None, max_length=500)


class ManualJournalIn(BaseModel):
    company_id: UUID
    entry_date: date
    description: str = Field(min_length=1, max_length=500)
    lines: list[ManualLineIn] = Field(min_length=2, max_length=200)


class ManualLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    line_no: int
    account_id: UUID
    branch_id: UUID | None
    debit: Decimal
    credit: Decimal
    description: str | None


class ManualJournalSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    number: str
    entry_date: date
    description: str
    status: str
    total: Decimal
    created_by: UUID | None
    entry_id: UUID | None


class ManualJournalOut(ManualJournalSummaryOut):
    approved_by: UUID | None
    lines: list[ManualLineOut]


class TrialBalanceLineOut(BaseModel):
    account_id: UUID
    code: str
    name: str
    type: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


class TrialBalanceOut(BaseModel):
    company_id: UUID
    as_of: date
    branch_id: UUID | None
    lines: list[TrialBalanceLineOut]
    total_debit: Decimal
    total_credit: Decimal
    balanced: bool


class LedgerLineOut(BaseModel):
    entry_id: UUID
    number: str
    entry_date: date
    description: str | None
    source_type: str | None
    branch_id: UUID | None
    debit: Decimal
    credit: Decimal
    balance: Decimal


class GeneralLedgerOut(BaseModel):
    account_id: UUID
    code: str
    name: str
    date_from: date
    date_to: date
    opening: Decimal
    closing: Decimal
    lines: list[LedgerLineOut]


# --------------------------------------------------------------------------- statements and exports
class StatementLineOut(BaseModel):
    account_id: UUID
    code: str
    name: str
    amount: Decimal


class LabelAmountOut(BaseModel):
    label: str
    amount: Decimal


class ProfitAndLossOut(BaseModel):
    income: list[StatementLineOut]
    total_income: Decimal
    cost_of_sales: list[StatementLineOut]
    total_cost_of_sales: Decimal
    gross_profit: Decimal
    expenses: list[StatementLineOut]
    total_expenses: Decimal
    net_profit: Decimal


class BranchProfitOut(BaseModel):
    branch_id: UUID | None
    branch_name: str
    statement: ProfitAndLossOut


class ProfitReportOut(BaseModel):
    company_id: UUID
    date_from: date
    date_to: date
    branch_id: UUID | None
    consolidated: ProfitAndLossOut
    branches: list[BranchProfitOut]


class BalanceSheetOut(BaseModel):
    company_id: UUID
    as_of: date
    branch_id: UUID | None
    assets: list[StatementLineOut]
    total_assets: Decimal
    liabilities: list[StatementLineOut]
    total_liabilities: Decimal
    equity: list[StatementLineOut]
    total_equity: Decimal
    accumulated_profit: Decimal
    total_liabilities_and_equity: Decimal
    balanced: bool


class CashFlowOut(BaseModel):
    company_id: UUID
    date_from: date
    date_to: date
    branch_id: UUID | None
    opening: Decimal
    movements: list[LabelAmountOut]
    net_movement: Decimal
    closing: Decimal
    reconciles: bool


class VatReportOut(BaseModel):
    company_id: UUID
    date_from: date
    date_to: date
    branch_id: UUID | None
    sales_net: Decimal
    output_vat: Decimal
    input_vat: Decimal
    net_payable: Decimal
    output_by_source: list[LabelAmountOut]
    input_by_source: list[LabelAmountOut]


class MappingIn(BaseModel):
    external_code: str | None = Field(default=None, max_length=40, examples=["4010"])
    external_name: str | None = Field(default=None, max_length=100, examples=["Sales - hardware"])


class MappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_id: UUID
    external_code: str | None
    external_name: str | None

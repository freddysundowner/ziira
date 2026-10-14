"""Request and response shapes for the payments API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount

Money = Annotated[Amount, Field(gt=0)]


class AccountIn(BaseModel):
    company_id: UUID
    branch_id: UUID | None = None
    kind: Literal["cash", "mobile_money", "bank", "card"]
    name: str = Field(min_length=1, max_length=200)
    shortcode: str | None = Field(default=None, max_length=20, description="The merchant or collection number")
    bank_account_masked: str | None = Field(default=None, max_length=40, examples=["****4821"])
    ledger_account_id: UUID | None = Field(default=None, description="The Finance account this one posts to")
    environment: Literal["sandbox", "production"] = "sandbox"
    provider: str = Field(default="daraja", max_length=40,
                          description="A registered payment provider; 'fake' is for development only")
    provider_config: dict[str, str] | None = Field(
        default=None, description="Provider settings, e.g. {'till_type': 'till'} for Daraja")


class AccountUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    ledger_account_id: UUID | None = None


class CredentialsIn(BaseModel):
    consumer_key: str = Field(min_length=1, max_length=200)
    consumer_secret: str = Field(min_length=1, max_length=200)
    passkey: str = Field(min_length=1, max_length=400)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    kind: str
    name: str
    shortcode: str | None
    bank_account_masked: str | None
    ledger_account_id: UUID | None
    is_active: bool
    provider: str


class CallbackTokenOut(BaseModel):
    token: str = Field(description="Shown once")
    urls: dict[str, str]


class PaymentIn(BaseModel):
    company_id: UUID
    branch_id: UUID | None = None
    method: Literal["cash", "mobile_money", "bank", "card", "cheque", "other"]
    direction: Literal["in", "out"] = "in"
    amount: Money
    payment_account_id: UUID | None = None
    business_date: date | None = None
    external_ref: str | None = Field(default=None, max_length=60, description="M-Pesa code, card or bank reference")
    phone: str | None = Field(default=None, max_length=30)
    party_type: Literal["customer", "supplier", "employee", "other"] | None = None
    party_id: UUID | None = None


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    doc_type: str
    doc_id: UUID
    amount: Decimal


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    number: str
    direction: str
    method: str
    payment_account_id: UUID
    amount: Decimal
    business_date: date
    party_type: str | None
    party_id: UUID | None
    external_ref: str | None
    status: str
    till_session_id: UUID | None


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ExternalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    payment_account_id: UUID
    source: str
    external_ref: str
    txn_time: datetime
    direction: str
    amount: Decimal
    fee: Decimal
    bill_ref: str | None
    counterparty_name: str | None
    counterparty_phone_masked: str | None
    match_status: str


class StatementIn(BaseModel):
    format: Literal["mpesa", "bank"]
    content: str = Field(min_length=1, description="The statement as CSV text")
    options: dict[str, str] = Field(default_factory=dict, description="Bank CSV column names, if not the usual ones")


class StatementResultOut(BaseModel):
    created: int
    duplicates: int
    skipped: list[str]


class IntentIn(BaseModel):
    payment_account_id: UUID
    amount: Money
    phone: str = Field(max_length=30, examples=["0712345678"])
    doc_type: str | None = Field(default=None, max_length=40)
    doc_id: UUID | None = None
    account_reference: str | None = Field(default=None, max_length=12)


class IntentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    payment_account_id: UUID
    kind: str
    amount: Decimal
    phone_masked: str
    status: str
    result_code: str | None
    doc_type: str | None
    doc_id: UUID | None
    expires_at: datetime | None
    receipt: str | None = None


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    external_transaction_id: UUID
    payment_id: UUID
    amount: Decimal
    stage: str
    rule_code: str | None
    confidence: Decimal | None
    status: str


class ManualMatchIn(BaseModel):
    external_transaction_id: UUID
    payment_id: UUID
    amount: Money | None = None


class MatchRunIn(BaseModel):
    payment_account_id: UUID | None = None


class MatchRunOut(BaseModel):
    applied: int
    proposed: int
    flagged: int


class SettlementIn(BaseModel):
    from_account_id: UUID
    to_account_id: UUID
    amount: Money
    fee: Annotated[Amount, Field(ge=0)] = Decimal(0)
    business_date: date | None = None
    reference: str = Field(min_length=1, max_length=60)


class CashDepositIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    bank_account_id: UUID
    amount: Money
    business_date: date | None = None
    reference: str = Field(min_length=1, max_length=60)


class IdOut(BaseModel):
    id: UUID


class CloseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID
    business_date: date
    status: str
    totals: dict[str, Any]
    variance: Decimal
    submitted_by: UUID | None
    submitted_at: datetime | None
    locked_at: datetime | None
    explanation: str | None
    cash_banked: Decimal | None


class ClosePreviewOut(BaseModel):
    close: CloseOut
    problems: list[str]
    totals: dict[str, Any]


class CloseSubmitIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    business_date: date
    cash_banked: Annotated[Amount, Field(ge=0)]
    explanation: str | None = Field(default=None, max_length=2000)

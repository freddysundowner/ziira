"""Public interface of the Payments and Reconciliation module.

Other units use these: POS records the money of a sale with `record_payment`, and a provider plugin (a mobile-money
service, a card or bank connector) implements the `PaymentProvider` contract for the "payments.provider" extension
point. The module knows no provider: request and callback formats, credential forms and statement formats belong to the
plugin.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

from ziira.modules.payments.domain.mobile_money import (
    C2BTransaction,
    StkResult,
    mask_phone,
    parse_amount,
    phone_fingerprint,
)
from ziira.modules.payments.domain.statements import (
    GENERIC_HEADER_WORDS,
    MAX_ROWS,
    ParsedStatement,
    StatementRow,
    column_key,
    csv_rows,
    statement_amount,
    statement_time,
)
from ziira.sdk import Session, ValidationFailed, normalise_phone

__all__ = [
    "GENERIC_HEADER_WORDS", "MAX_ROWS", "C2BTransaction", "FormField", "ParsedStatement", "PaymentProvider",
    "StatementReader", "StatementRow", "StkQuery", "StkRequest", "StkResponse", "StkResult", "column_key", "csv_rows",
    "mask_phone", "parse_amount", "phone_fingerprint", "statement_amount", "statement_time",
]

PROVIDER_EXTENSION = "payments.provider"
STATEMENT_EXTENSION = "payments.statement_format"
MANUAL_PROVIDER = "manual"           # an account with no integration: payments are recorded by hand or from statements


@dataclass(frozen=True)
class StkRequest:
    """A request to put a payment prompt on a customer's phone."""

    shortcode: str
    amount: Decimal
    msisdn: str                          # as the provider wants it (see PaymentProvider.normalize_phone)
    callback_url: str
    account_reference: str
    description: str
    credentials: dict[str, Any] = field(repr=False, default_factory=dict)
    environment: str = "sandbox"
    settings: dict[str, Any] = field(default_factory=dict)    # the account's provider settings (config_fields)


@dataclass(frozen=True)
class StkResponse:
    """What the provider said when asked to send the prompt."""

    accepted: bool
    provider_request_id: str | None
    message: str = ""
    permanent_failure: bool = False      # True: do not retry (bad credentials, invalid number)


@dataclass(frozen=True)
class StkQuery:
    shortcode: str
    provider_request_id: str
    credentials: dict[str, Any] = field(repr=False, default_factory=dict)
    environment: str = "sandbox"


@dataclass(frozen=True)
class FormField:
    """One field of a provider's credentials or settings form, described as data so the web app can draw the form."""

    key: str
    label: str
    secret: bool = False              # a credential: stored encrypted, never shown again
    required: bool = True
    kind: str = "text"                # "text" or "select"
    options: tuple[str, ...] = ()     # for "select"
    default: str | None = None
    help: str = ""


class StatementReader(ABC):
    """Contract of the "payments.statement_format" extension point: a statement format people upload (a provider's
    business statement, a bank's export). `name` is what the upload names; `source` is recorded on each line."""

    name: str = "format"
    label: str = ""
    source: str = "statement"

    @abstractmethod
    def parse(self, text: str) -> ParsedStatement:
        """Read the statement's text. Raises ValidationFailed when it is not this format."""


class PaymentProvider(ABC):
    """Contract of the "payments.provider" extension point: a way to ask customers for money, to read what the provider
    reports, and to describe its own settings. Only `stk_push` and `query_stk` are required."""

    name: str = "provider"
    title: str = ""
    development_only: ClassVar[bool] = False          # refused for a business running in production
    supports_prompts: ClassVar[bool] = True
    credential_fields: ClassVar[tuple[FormField, ...]] = ()     # the secret form (keys, passkeys), stored encrypted
    config_fields: ClassVar[tuple[FormField, ...]] = ()         # non-secret settings kept on the payment account
    c2b_source: ClassVar[str] = ""                    # `source` recorded for callbacks about customers paying us
    stk_source: ClassVar[str] = ""                    # `source` recorded for the outcome of a prompt
    callback_reply: ClassVar[dict[str, Any]] = {"status": "accepted"}   # what the provider expects back from a callback
    prompt_minimum: ClassVar[Decimal] = Decimal(1)
    prompt_maximum: ClassVar[Decimal | None] = None
    prompt_whole_amounts: ClassVar[bool] = False

    def normalize_phone(self, raw: str, calling_code: str | None) -> str:
        """The payer's number as this provider wants it (default: international digits)."""
        number = normalise_phone(raw, calling_code)
        if number is None:
            raise ValidationFailed("A phone number is required")
        return number

    @abstractmethod
    def stk_push(self, request: StkRequest) -> StkResponse:
        """Ask the provider to send the customer a payment prompt."""

    @abstractmethod
    def query_stk(self, query: StkQuery) -> StkResult:
        """Ask the provider what became of a prompt (when its callback never came)."""

    def parse_stk_callback(self, payload: dict[str, Any]) -> StkResult:
        """Read the provider's callback about a prompt. Raises ValidationFailed when it is not one."""
        raise ValidationFailed(f"{self.name} does not send prompt callbacks")

    def parse_c2b(self, payload: dict[str, Any]) -> C2BTransaction:
        """Read the provider's report of a customer paying one of our tills. Raises ValidationFailed if not one."""
        raise ValidationFailed(f"{self.name} does not send payment confirmations")


@dataclass(frozen=True)
class PaymentView:
    id: UUID
    number: str
    amount: Decimal
    method: str
    business_date: date


def record_payment(session: Session, **kwargs: Any) -> PaymentView:
    """Record money received or paid, normalised into the one payments model, and match it to documents. See
    services/payments.py: record_payment for the arguments."""
    from ziira.modules.payments.services.payments import record_payment as record

    payment = record(session, **kwargs)
    return PaymentView(payment.id, payment.number, payment.amount, payment.method, payment.business_date)


def cash_account_for_branch(session: Session, company_id: UUID, branch_id: UUID) -> UUID:
    """The branch's till-cash payment account (created the first time it is needed)."""
    from ziira.modules.payments.services.accounts import cash_account_for_branch as cash_account

    account_id: UUID = cash_account(session, company_id, branch_id).id
    return account_id


_KINDS = {"cash": ("cash",), "mobile_money": ("mobile_money",), "card": ("card",), "bank": ("bank",)}


def account_for_method(session: Session, company_id: UUID, branch_id: UUID | None, method: str) -> UUID | None:
    """The payment account a branch takes this method through (its own first, then the company's), or None."""
    from ziira.modules.payments.repository import payments_repo

    if method == "cash" and branch_id is not None:
        return cash_account_for_branch(session, company_id, branch_id)
    kinds = _KINDS.get(method)
    account = payments_repo.find_account_by_kinds(session, company_id, branch_id, kinds) if kinds else None
    return account.id if account else None


def reverse_payment(session: Session, payment_id: UUID, reason: str) -> None:
    """Cancel a payment because the document it belonged to was voided. The caller has checked the user may void."""
    from ziira.modules.payments.services.payments import reverse_payment as reverse

    reverse(session, payment_id, reason, authorised=True)


def day_is_locked(session: Session, branch_id: UUID, day: date) -> bool:
    """True when the branch's daily close for the date is locked (its payments can no longer change)."""
    from ziira.modules.payments.repository import payments_repo

    close = payments_repo.get_close(session, branch_id, day)
    return close is not None and close.status == "locked"


def cash_in_till_session(session: Session, till_session_id: UUID) -> Decimal:
    """Cash taken less cash paid out through a till session (what the drawer should hold above its float)."""
    from ziira.modules.payments.repository import payments_repo

    return payments_repo.cash_in_session(session, till_session_id)


@dataclass(frozen=True)
class DocumentPayment:
    """A payment allocated (wholly or in part) to a document, as other units may see it."""

    payment_id: UUID
    number: str
    method: str
    direction: str
    status: str
    business_date: date
    amount: Decimal              # what was allocated to the document
    reference: str | None = None  # the mobile-money code, bank reference or cheque number


def payments_for_document(session: Session, doc_type: str, doc_id: UUID) -> list[DocumentPayment]:
    """The payments allocated to a document (for example a supplier bill), oldest first."""
    from ziira.modules.payments.repository import payments_repo

    found = []
    for allocation, payment in payments_repo.payments_for_document(session, doc_type, doc_id):
        found.append(DocumentPayment(payment.id, payment.number, payment.method, payment.direction, payment.status,
                                     payment.business_date, allocation.amount, payment.external_ref))
    return found

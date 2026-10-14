"""Public interface of the Payments and Reconciliation module.

Other units use these: POS records the money of a sale with `record_payment`, and a plugin (an Airtel Money or bank
connector) can implement the `PaymentProvider` contract for the "payments.provider" extension point.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.payments.domain.mpesa import StkResult
from ziira.sdk import Session

PROVIDER_EXTENSION = "payments.provider"


@dataclass(frozen=True)
class StkRequest:
    """A request to put a payment prompt on a customer's phone."""

    shortcode: str
    till_type: str                       # "till" (buy goods) or "paybill"
    amount: Decimal
    msisdn: str                          # normalised, 2547XXXXXXXX
    callback_url: str
    account_reference: str
    description: str
    credentials: dict[str, Any] = field(repr=False, default_factory=dict)
    environment: str = "sandbox"
    party_b: str | None = None           # the till number to pay, when different from the shortcode


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


class PaymentProvider(ABC):
    """Contract of the "payments.provider" extension point: a way to ask customers for money."""

    name: str = "provider"

    @abstractmethod
    def stk_push(self, request: StkRequest) -> StkResponse:
        """Ask the provider to send the customer a payment prompt."""

    @abstractmethod
    def query_stk(self, query: StkQuery) -> StkResult:
        """Ask the provider what became of a prompt (when its callback never came)."""


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
    reference: str | None = None  # the M-Pesa code, bank reference or cheque number


def payments_for_document(session: Session, doc_type: str, doc_id: UUID) -> list[DocumentPayment]:
    """The payments allocated to a document (for example a supplier bill), oldest first."""
    from ziira.modules.payments.repository import payments_repo

    found = []
    for allocation, payment in payments_repo.payments_for_document(session, doc_type, doc_id):
        found.append(DocumentPayment(payment.id, payment.number, payment.method, payment.direction, payment.status,
                                     payment.business_date, allocation.amount, payment.external_ref))
    return found

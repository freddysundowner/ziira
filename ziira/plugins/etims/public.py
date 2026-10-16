"""The contract of the eTIMS plugin: what the integration with the tax authority must do. Not implemented yet.

A real implementation subscribes to `sale.posted`, `sale.returned`, `invoice.issued` and `invoice.cancelled`, queues a
submission with `@job`, keeps the outcome in `plg_etims.submission`, and flags failures with `flag_for_review`. Its
credentials (the business's PIN, branch and device details, keys) go through `store_credential(provider="etims")`.
See README.md and docs/parked/etims.md for the design and what is still undecided (arrangements with the authority, the
integrator certification).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

SUBMISSION_STATUSES = ("pending", "submitted", "failed")


@dataclass(frozen=True)
class SubmissionResult:
    """What the authority answered for one document."""

    accepted: bool
    authority_ref: str | None = None      # the invoice number it issued
    signature: str | None = None
    qr_data: str | None = None
    message: str = ""
    permanent_failure: bool = False       # True: do not retry (a rejected document); False: an outage, retry later


@dataclass(frozen=True)
class SaleDocument:
    """A sale or credit note as the authority needs it. Amounts are Decimal; tax codes are the authority's own."""

    doc_type: str                         # "sale" or "credit_note"
    number: str
    lines: list[dict[str, Any]]           # description, quantity, unit price, tax authority code, tax amount
    total: Decimal
    original_authority_ref: str | None = None     # for a credit note: the invoice it corrects


class AuthorityGateway(ABC):
    """The calls to the tax authority's system. One implementation per integration (sandbox, production)."""

    @abstractmethod
    def submit(self, document: SaleDocument, credentials: dict[str, Any]) -> SubmissionResult:
        """Send a sale or credit note; return what the authority said."""

    @abstractmethod
    def fetch_purchases(self, credentials: dict[str, Any], since: str) -> list[dict[str, Any]]:
        """The supplier invoices the authority holds for the business, to match with supplier bills."""

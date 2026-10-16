"""Public interface of the Connectors module: Intelligence on top of other systems ("standalone mode").

A business that keeps its current system (Odoo, ERPNext, Zoho Books, QuickBooks, a POS, spreadsheets, bank and
mobile-money statements) connects it here. A **connector** reads that system and turns what it finds into the
**canonical model** below (the same shapes whatever the source), which the connectors module stores read-only in its
own `connect.src_*` tables. Intelligence's standalone checks read only those tables, so one set of checks serves every
source. Nothing is
ever written back to the source system (read-only by default: the business can withdraw the key at any time).

To add a connector: subclass `Connector`, set `kind`, `title`, `config_fields` and the entities it can read, decorate
it with `@provides(CONNECTOR)` in your unit's (or plugin's) `hooks.py`, and list "connect.connector" under
`[extends] implements` (and "connect" under `optional`) in the manifest. The connectors module runs it on a schedule
through `pull`.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import httpx

from ziira.sdk import Session

CONNECTOR = "connect.connector"
OCR_ENGINE = "connect.ocr_engine"
CORE_COVERAGE = "connect.core_coverage"

# The business areas a connected system and Ziira Core can both cover. A connected system supplies an area through the
# entities it reads; a Core unit covers it by being switched on and in real use.
OVERLAP_AREAS = ("sales", "receivables", "payables", "stock", "payments", "expenses", "journals")

ENTITIES = ("branches", "parties", "products", "users", "sales", "payments", "stock_movements", "invoices",
            "expenses", "journal_entries")

__all__ = [
    "CONNECTOR", "CORE_COVERAGE", "OCR_ENGINE", "OVERLAP_AREAS", "AreaOverlap", "CoreCoverage", "OcrEngine", "OcrWord",
    "Overlap", "coverage_overlap", "ENTITIES", "Branch", "CanonicalBatch", "ConfigField",
    "Connector", "ConnectorError",
    "ConnectionCheck", "Expense", "Invoice", "JournalEntry", "JournalLine", "Party", "Payment", "Product", "Sale",
    "SaleLine", "SalePayment", "StockMovement", "User",
]


class ConnectorError(Exception):
    """A connector could not do what it was asked (bad credentials, the system is down, an unexpected reply).

    The message is shown to the business owner: plain words, no secrets. `retryable` says whether trying again
    later may work.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


# --------------------------------------------------------------------------- the canonical model
# Every record carries `ref`: the id of the record in the SOURCE system (text, stable). Records refer to each other
# by ref. Money is Decimal in the source's own currency; `currency` is given where the source says it.


@dataclass(frozen=True)
class Branch:
    ref: str
    name: str


@dataclass(frozen=True)
class Party:
    ref: str
    kind: Literal["customer", "supplier"]
    name: str
    phone: str | None = None
    email: str | None = None
    tax_id: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class Product:
    ref: str
    name: str
    sku: str | None = None
    category: str | None = None
    unit_cost: Decimal | None = None
    unit_price: Decimal | None = None


@dataclass(frozen=True)
class User:
    ref: str
    name: str
    role: str | None = None
    email: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class SaleLine:
    product_ref: str | None
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal = Decimal(0)           # money off this line (not a percentage)
    list_price: Decimal | None = None        # the normal price, when the source records it


@dataclass(frozen=True)
class SalePayment:
    method: str                              # "cash", "card", "mobile_money", "credit", "bank", "other"
    amount: Decimal
    reference: str | None = None             # a transaction code the payer's side also shows


@dataclass(frozen=True)
class Sale:
    ref: str
    occurred_at: datetime                    # timezone-aware
    total: Decimal
    status: Literal["posted", "voided", "refunded"] = "posted"
    number: str | None = None
    branch_ref: str | None = None
    cashier_ref: str | None = None
    customer_ref: str | None = None
    tax_total: Decimal = Decimal(0)
    discount_total: Decimal = Decimal(0)
    currency: str | None = None
    voided_by_ref: str | None = None
    lines: tuple[SaleLine, ...] = ()
    payments: tuple[SalePayment, ...] = ()
    entered_at: datetime | None = None       # when it was typed in, if the source records that (back-dating)


@dataclass(frozen=True)
class Payment:
    """Money in or out that the source (bank or mobile-money statement, payment system, the ERP's payments) shows:
    evidence."""

    ref: str
    occurred_at: datetime
    direction: Literal["in", "out"]
    amount: Decimal
    method: str = "other"                    # "cash", "bank", "mobile_money", "card", "other"
    reference: str | None = None             # the transaction code
    party_ref: str | None = None
    party_name: str | None = None            # the payer or payee as the statement shows it
    account: str | None = None               # which bank/mobile-money account or till it moved through
    branch_ref: str | None = None
    invoice_ref: str | None = None           # what it was applied to, if the source knows
    currency: str | None = None


@dataclass(frozen=True)
class StockMovement:
    ref: str
    occurred_at: datetime
    product_ref: str
    quantity: Decimal                        # + in, - out
    kind: Literal["sale", "purchase", "adjustment", "transfer_in", "transfer_out", "count", "return", "other"] = "other"
    branch_ref: str | None = None
    user_ref: str | None = None
    reason: str | None = None
    unit_cost: Decimal | None = None
    entered_at: datetime | None = None


@dataclass(frozen=True)
class Invoice:
    ref: str
    kind: Literal["customer", "supplier"]
    issue_date: date
    total: Decimal
    paid: Decimal = Decimal(0)
    due_date: date | None = None
    number: str | None = None
    party_ref: str | None = None
    branch_ref: str | None = None
    status: Literal["open", "paid", "cancelled", "draft"] = "open"
    created_by_ref: str | None = None
    approved_by_ref: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class Expense:
    ref: str
    occurred_at: datetime
    amount: Decimal
    category: str | None = None
    description: str | None = None
    branch_ref: str | None = None
    user_ref: str | None = None
    party_ref: str | None = None


@dataclass(frozen=True)
class JournalLine:
    account: str                             # the account's code or name as the source has it
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    party_ref: str | None = None


@dataclass(frozen=True)
class JournalEntry:
    ref: str
    entry_date: date
    lines: tuple[JournalLine, ...]
    number: str | None = None
    entered_at: datetime | None = None       # for back-dating checks
    created_by_ref: str | None = None
    approved_by_ref: str | None = None
    memo: str | None = None
    is_manual: bool = True


Record = Branch | Party | Product | User | Sale | Payment | StockMovement | Invoice | Expense | JournalEntry


@dataclass(frozen=True)
class CanonicalBatch:
    """A page of records of one entity, with where to carry on from. A connector yields batches until it has all."""

    entity: str                              # one of ENTITIES
    records: tuple[Record, ...]
    cursor: str | None = None                # opaque: handed back as `since` on the next pull
    complete: bool = True                    # False if more pages follow


@dataclass(frozen=True)
class ConfigField:
    """One thing the business must give to connect (a URL, a database name, an API key).

    `secret` fields are stored encrypted and never shown again.
    """

    name: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    example: str = ""


@dataclass(frozen=True)
class ConnectionCheck:
    ok: bool
    message: str                             # plain words for the owner
    details: dict[str, Any] = field(default_factory=dict)   # e.g. {"system": "ERPNext 15"}: never secrets


class Connector(ABC):
    """Reads one kind of system.

    Stateless: everything it needs is in `config`/`secrets`; what it remembers between pulls is the `cursor` it hands
    back. Reads only: it must never create, change or delete anything in the source system. Network access goes
    through an `httpx.Client` built by `self.client()` so tests can replace the transport.
    """

    kind: str                                # "erpnext", "odoo", "csv_sales", "mpesa_statement", ...
    title: str
    description: str = ""
    entities: tuple[str, ...] = ()           # which ENTITIES it can read
    config_fields: tuple[ConfigField, ...] = ()
    needs_oauth: bool = False                # True: the business authorises through a browser redirect
    freshness: str = "daily"                 # "live" | "daily" | "on_upload": what the business can expect
    how_to: str = ""                         # plain words: what access to create / which file to export, and where
    # Set by `pull`/`check` when the vendor rotated a secret (an OAuth refresh token): the sync engine must save this
    # dict over the connection's secrets (merge) if it is not None, even when the pull then fails. Reset by the
    # connector at the start of each pull/check. Instances are per-run, so this is safe.
    updated_secrets: dict[str, Any] | None = None
    # Replaced in tests with a factory returning an httpx.Client on a MockTransport.
    client_factory: Callable[[], httpx.Client] | None = None

    def client(self) -> httpx.Client:
        """The HTTP client to use for every request (tests inject a mock transport through `client_factory`)."""
        if self.client_factory is not None:
            return self.client_factory()
        return httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    @abstractmethod
    def check(self, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectionCheck:
        """Try the credentials with the lightest read the system offers. Never raises: `ok=False` with a reason."""

    @abstractmethod
    def pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
             limit: int | None = None) -> Iterator[CanonicalBatch]:
        """Yield batches of canonical records for `entity` newer than `since`.

        `since` is the cursor of the last complete pull (None: everything). Raise `ConnectorError` for failures.
        Must be safe to call twice with the same arguments.
        """


# --------------------------------------------------------------------------- reading pictures (OCR)
@dataclass(frozen=True)
class OcrWord:
    """One word read from a picture, with where it sits (pixels, origin top-left) and how sure the engine is (0-100)."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float = 100.0


class OcrEngine(ABC):
    """Reads the words out of a picture of a page. The default engine is a self-hosted Tesseract, so a business's
    statements never leave its server; plug in another with `@provides(OCR_ENGINE)` (an engine that sends pictures to
    a third party must say so in its `name` and be switched on deliberately)."""

    name: str = ""

    @abstractmethod
    def unavailable(self) -> str | None:
        """None when the engine can read; else why not, in plain words for the person who runs the server."""

    @abstractmethod
    def read(self, image_png: bytes) -> list[OcrWord]:
        """The words of one page image, with positions. Raises `ConnectorError` if the engine fails."""


# --------------------------------------------------------------------------- Core units that cover the same ground
class CoreCoverage(ABC):
    """Says which areas (`OVERLAP_AREAS`) a Core unit is really in use for, and where.

    A unit that runs part of the business (sales, stock, receivables...) plugs one in with
    `@provides(CORE_COVERAGE)` in its hooks.py, listing "connect.core_coverage" under `[extends] implements` and
    "connect" under `optional`. It returns, for each area it covers, the branches with real activity since a date (a
    posted sale, a stock movement that is not an opening balance); `None` stands for activity that names no branch.
    Opening balances brought in by a move never count: they are not the business running on Ziira. Reads only.
    """

    @abstractmethod
    def active(self, session: Session, company_id: UUID | None, since: date) -> dict[str, set[UUID | None]]:
        """area -> branches (None: no branch named) with real Core activity from `since` on. `company_id` None: all."""


@dataclass(frozen=True)
class AreaOverlap:
    """One area both a connected system and Core cover."""

    area: str
    branch_ids: frozenset[UUID | None]          # where Core is active (None: company-wide or no branch named)
    connection_ids: tuple[UUID, ...]            # the active connections that supply this area


@dataclass(frozen=True)
class Overlap:
    """Where a business is run twice: the areas that connected systems and Core units both cover."""

    areas: tuple[AreaOverlap, ...]
    days: int

    def covers(self, area: str, branch_id: UUID | None) -> bool:
        """Whether Core covers `area` at this branch (None: the company level, covered when Core is active anywhere)."""
        return any(found.area == area and (branch_id is None or branch_id in found.branch_ids) for found in self.areas)

    @property
    def overlapping(self) -> bool:
        return bool(self.areas)


def coverage_overlap(session: Session, company_id: UUID | None = None, *, days: int = 14,
                     honour_choice: bool = True) -> Overlap:
    """Which areas Core now covers that an active connected system also supplies, and at which branches. With
    `honour_choice` a connection the business chose to "keep both" for is left out (its standalone checks go on)."""
    from ziira.modules.connect.services import overlap

    return overlap.coverage_overlap(session, company_id, days=days, honour_choice=honour_choice)

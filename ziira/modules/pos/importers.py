"""Importing what customers owe at go-live: POS's `imports.importer` for `customer_balances`. One row per open invoice
(or per customer credit). Rows go through `services/opening_balances.py`, which makes opening invoices and credits and
lets Finance post them against opening balance equity."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.crm.public import CustomerView, find_customer_by_code
from ziira.modules.finance.public import party_amount_by_source
from ziira.modules.imports.public import ImportColumn, Importer, ImportRow
from ziira.modules.pos.permissions import RECEIVABLES_MANAGE
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.services import opening_balances as service
from ziira.modules.pos.services.common import unit_enabled
from ziira.sdk import Session, ValidationFailed

OWED, BOOKS = "customer balances", "posted to the books"


class _Row:
    """A row of the file after checking."""

    def __init__(self) -> None:
        self.customer: CustomerView | None = None
        self.amount = Decimal(0)
        self.invoice_date: date | None = None
        self.due_date: date | None = None
        self.reference = ""
        self.go_live: date | None = None

    @property
    def is_credit(self) -> bool:
        return self.amount < 0


class CustomerBalanceImporter(Importer):
    kind = "customer_balances"
    title = "Customer opening balances"
    description = ("What customers owe you on the go-live date: one row per open invoice with its original date, due "
                   "date and number, so ageing is right. A customer who has paid in advance is a negative amount. "
                   "Import your customers first. Amounts are posted against opening balance equity.")
    permission = RECEIVABLES_MANAGE
    columns = (
        ImportColumn("customer_code", True, "The customer's code in Ziira.", "C-001",
                     aliases=("customer", "customer code", "account", "account no", "code")),
        ImportColumn("reference", False, "The invoice's number in your old system (a credit may leave it empty).",
                     "INV-2025-118", aliases=("invoice", "invoice no", "invoice number", "document no")),
        ImportColumn("invoice_date", False, "The invoice's date (needed for what is owed; not for a credit).",
                     "2026-03-14", aliases=("date", "document date", "issue date", "inv date")),
        ImportColumn("due_date", False, "When it falls due. Left out: the invoice date plus the customer's terms.",
                     "2026-04-13", aliases=("due", "due on", "payment due")),
        ImportColumn("amount", True, "What is still owed on it. Negative: the customer is in credit.", "4500.00",
                     aliases=("balance", "outstanding", "amount due", "open amount"), total=OWED),
    )
    money_totals = (OWED, BOOKS)
    needs_go_live = True
    reversible = True
    reversal_note = ("Customer balances are taken out again by reversing the whole import; that is refused while any "
                     "of them has been paid.")

    def key(self, row: ImportRow) -> str | None:
        errors: list[str] = []
        day = row.day("invoice_date", errors)
        amount = row.number("amount", errors)
        fallback = f"CREDIT-{row.options.as_of}" if amount is not None and amount < 0 else f"OPENING-{day}"
        return f"{row.text('customer_code').upper()}|{service.clean_reference(row.text('reference'), fallback)}"

    def _read(self, session: Session, company_id: UUID, row: ImportRow, errors: list[str]) -> _Row:
        found = _Row()
        found.go_live = row.options.as_of
        if found.go_live is None:
            errors.append("Say the go-live date when uploading the file")
        else:
            self._ready(session, company_id, found.go_live, errors)
        code = row.text("customer_code").upper()
        customer = find_customer_by_code(session, company_id, code) if code and unit_enabled(session, "crm") else None
        if customer is None:
            errors.append(f"customer_code: no customer with code {code or '(empty)'}. Import the customers first")
        found.customer = customer
        amount = row.number("amount", errors)
        if amount is None:
            errors.append("amount: the balance is needed")
        elif amount == 0:
            errors.append("amount: a balance of zero is not brought in")
        elif amount != amount.quantize(service.CENT):
            errors.append("amount: at most 2 decimal places")
        found.amount = amount or Decimal(0)
        found.invoice_date = row.day("invoice_date", errors)
        found.due_date = row.day("due_date", errors)
        if found.is_credit:
            found.reference = service.clean_reference(row.text("reference"), f"CREDIT-{found.go_live}")
        else:
            if found.invoice_date is None and not row.text("invoice_date"):
                errors.append("invoice_date: the date of the invoice is needed (ageing counts from its due date)")
            if found.invoice_date and found.go_live and found.invoice_date > found.go_live:
                errors.append(f"invoice_date: {found.invoice_date} is after the go-live date {found.go_live}")
            if found.due_date is None and found.invoice_date is not None and customer is not None:
                found.due_date = found.invoice_date + timedelta(days=customer.payment_terms_days)
            if found.due_date and found.invoice_date and found.due_date < found.invoice_date:
                errors.append("due_date: the due date is before the invoice date")
            found.reference = service.clean_reference(row.text("reference"), f"OPENING-{found.invoice_date}")
        return found

    @staticmethod
    def _ready(session: Session, company_id: UUID, go_live: date, errors: list[str]) -> None:
        try:
            service.check_can_open(session, company_id, go_live)
        except ValidationFailed as error:
            errors.append(error.message)

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        self._read(session, company_id, row, errors)
        return errors

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        read = self._read(session, company_id, row, [])
        if read.customer is None:
            return None
        if service.opening_exists(session, read.customer.id, read.reference, credit=read.is_credit):
            return f"{read.customer.code} already has an opening balance {read.reference}"
        return None

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        errors: list[str] = []
        read = self._read(session, company_id, row, errors)
        if errors or read.customer is None or read.go_live is None:
            raise ValidationFailed("; ".join(errors) or "The row cannot be read")
        if read.is_credit:
            return service.create_opening_credit(
                session, customer=read.customer, reference=read.reference, amount=-read.amount,
                go_live_date=read.go_live).id
        assert read.invoice_date is not None and read.due_date is not None
        return service.create_opening_invoice(
            session, customer=read.customer, reference=read.reference, issue_date=read.invoice_date,
            due_date=read.due_date, amount=read.amount, go_live_date=read.go_live).id

    def totals(self, rows: Sequence[ImportRow]) -> dict[str, Decimal]:
        owed = super().totals(rows)[OWED]
        return {OWED: owed, BOOKS: owed}

    def imported_totals(self, session: Session, company_id: UUID, record_ids: list[UUID]) -> dict[str, Decimal]:
        """What the documents say customers owe, and what the books hold for the same documents."""
        invoices, receipts = pos_repo.opening_documents(session, set(record_ids))
        documents = sum((x.total for x in invoices), Decimal(0)) - sum((x.amount for x in receipts), Decimal(0))
        books = party_amount_by_source(session, company_id, "opening_receivable", set(record_ids), "customer")
        return {OWED: documents, BOOKS: books}

    def reverse(self, session: Session, company_id: UUID, record_ids: list[UUID], reason: str) -> int:
        return service.reverse_opening_documents(session, record_ids, reason)


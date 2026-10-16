"""Importing from a file, Purchasing's `imports.importer`s: suppliers, and what is owed to them at go-live. Bank details
are never imported: a supplier's bank account is the classic route for fraud, so it is proposed, confirmed by a second
person and approved in Ziira."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.finance.public import party_amount_by_source
from ziira.modules.imports.public import ExistingRecord, ImportColumn, Importer, ImportRow, attempt
from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import BILLS_MANAGE, SUPPLIERS_MANAGE
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import Supplier
from ziira.modules.purchasing.services import opening_balances as opening
from ziira.modules.purchasing.services.suppliers import create_supplier
from ziira.sdk import Session, ValidationFailed

PHONE_TAIL = 9          # phones are matched by their last digits: they are stored as typed


class SupplierImporter(Importer):
    kind = "suppliers"
    title = "Suppliers"
    description = ("Your supplier list: one row per supplier. Bank details are not imported (they need a second "
                   "person's confirmation); add them in Suppliers afterwards.")
    permission = SUPPLIERS_MANAGE
    columns = (
        ImportColumn("code", True, "Your supplier code.", "S-001", aliases=("supplier code", "vendor code", "account")),
        ImportColumn("name", True, "The supplier's name.", "Bamburi Distributors", aliases=("supplier", "vendor",
                                                                                           "supplier name")),
        ImportColumn("tax_id", False, "Tax number.", "P051234567X", aliases=("tax number", "pin", "vat number")),
        ImportColumn("phone", False, "Phone number.", "0722000111", aliases=("mobile", "telephone", "tel")),
        ImportColumn("email", False, "Email address.", "orders@example.com"),
        ImportColumn("payment_terms_days", False, "Days we have to pay.", "30", aliases=("terms", "payment terms")),
    )
    reversal_note = "Suppliers cannot be deleted. Put unwanted ones on hold in Suppliers."

    def key(self, row: ImportRow) -> str | None:
        return row.text("code").upper() or None

    def _read(self, row: ImportRow, errors: list[str]) -> dict[str, object]:
        terms = row.whole_number("payment_terms_days", errors) or 0
        return {
            "code": attempt(errors, lambda: rules.normalise_code(row.text("code"))),
            "name": attempt(errors, lambda: rules.check_name(row.text("name"))),
            "tax_id": attempt(errors, lambda: rules.check_tax_id(row.text("tax_id"))),
            "terms": attempt(errors, lambda: rules.check_terms(terms))}

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        self._read(row, errors)
        return errors

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        code = row.text("code").upper()
        found = session.execute(text("select 1 from purchasing.supplier where company_id = :c and code = :k"),
                                {"c": str(company_id), "k": code}).first()
        return f"Supplier {code} already exists" if found else None

    def find_match(self, session: Session, company_id: UUID, row: ImportRow) -> ExistingRecord | None:
        """The supplier already in Ziira with this code, tax number or phone (a move from another system). Phones are
        stored as typed, so they are compared by their last digits."""
        checks: list[tuple[str, str, str]] = []
        if row.text("code"):
            checks.append(("code = :v", "has the same supplier code", row.text("code").upper()))
        try:
            tax = rules.check_tax_id(row.text("tax_id"))
        except ValidationFailed:
            tax = None
        if tax:
            checks.append(("upper(tax_id) = :v", "has the same tax number", tax))
        digits = "".join(ch for ch in row.text("phone") if ch.isdigit())
        if len(digits) >= PHONE_TAIL:
            checks.append((f"right(regexp_replace(coalesce(phone, ''), '[^0-9]', '', 'g'), {PHONE_TAIL}) = :v",
                           "has the same phone number", digits[-PHONE_TAIL:]))
        for condition, why, value in checks:
            found = session.execute(text(
                f"select code, name from purchasing.supplier where company_id = :c and {condition} "
                "order by created_at limit 1"), {"c": str(company_id), "v": value}).first()
            if found:
                return ExistingRecord(found.code, f"{found.name} ({found.code}) {why}")
        return None

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        errors: list[str] = []
        read = self._read(row, errors)
        if errors:
            raise ValidationFailed("; ".join(errors))
        supplier = create_supplier(
            session, company_id=company_id, code=str(read["code"]), name=str(read["name"]),
            tax_id=row.text("tax_id") or None, phone=row.text("phone") or None, email=row.text("email") or None,
            payment_terms_days=int(read["terms"]))   # type: ignore[call-overload]
        return supplier.id


OWED, BOOKS = "supplier balances", "posted to the books"


class SupplierBalanceImporter(Importer):
    kind = "supplier_balances"
    title = "Supplier opening balances"
    description = ("What you owe suppliers on the go-live date: one row per open supplier invoice with its original "
                   "date, due date and number, so payables ageing is right. Import your suppliers first. Amounts are "
                   "posted against opening balance equity.")
    permission = BILLS_MANAGE
    columns = (
        ImportColumn("supplier_code", True, "The supplier's code in Ziira.", "S-001",
                     aliases=("supplier", "vendor", "vendor code", "account", "code")),
        ImportColumn("reference", True, "The supplier's invoice number.", "BD-77310",
                     aliases=("invoice", "invoice no", "invoice number", "bill", "bill no", "document no")),
        ImportColumn("invoice_date", True, "The invoice's date.", "2026-03-02",
                     aliases=("date", "bill date", "document date", "inv date")),
        ImportColumn("due_date", False, "When it falls due. Left out: the invoice date plus the supplier's terms.",
                     "2026-04-01", aliases=("due", "due on", "payment due")),
        ImportColumn("amount", True, "What is still owed on it.", "18500.00",
                     aliases=("balance", "outstanding", "amount due", "open amount"), total=OWED),
    )
    money_totals = (OWED, BOOKS)
    needs_go_live = True
    reversible = True
    reversal_note = ("Supplier balances are taken out again by reversing the whole import; that is refused while any "
                     "of them has been paid.")

    def key(self, row: ImportRow) -> str | None:
        return f"{row.text('supplier_code').upper()}|{row.text('reference')}"

    def _supplier(self, session: Session, company_id: UUID, row: ImportRow, errors: list[str]) -> Supplier | None:
        code = row.text("supplier_code").upper()
        found = repo.supplier_by_code(session, company_id, code) if code else None
        if found is None:
            errors.append(f"supplier_code: no supplier with code {code or '(empty)'}. Import the suppliers first")
        return found

    def _read(self, session: Session, company_id: UUID, row: ImportRow,
              errors: list[str]) -> tuple[Supplier | None, Decimal, date | None, date | None, str]:
        go_live = row.options.as_of
        if go_live is None:
            errors.append("Say the go-live date when uploading the file")
        else:
            try:
                opening.check_can_open(session, company_id, go_live)
            except ValidationFailed as error:
                errors.append(error.message)
        supplier = self._supplier(session, company_id, row, errors)
        amount = row.number("amount", errors)
        if amount is None:
            errors.append("amount: the balance is needed")
        elif amount <= 0:
            errors.append("amount: must be more than zero (an amount a supplier owes you is a credit note, entered in "
                          "Purchasing)")
        elif amount != amount.quantize(opening.CENT):
            errors.append("amount: at most 2 decimal places")
        reference = opening.clean_reference(row.text("reference"), "")
        if not reference:
            errors.append("reference: the supplier's invoice number is needed")
        bill_date = row.day("invoice_date", errors)
        if bill_date is None and not row.text("invoice_date"):
            errors.append("invoice_date: the date of the invoice is needed (ageing counts from its due date)")
        if bill_date and go_live and bill_date > go_live:
            errors.append(f"invoice_date: {bill_date} is after the go-live date {go_live}")
        due = row.day("due_date", errors)
        if due is None and bill_date is not None and supplier is not None:
            due = bill_date + timedelta(days=supplier.payment_terms_days)
        if due and bill_date and due < bill_date:
            errors.append("due_date: the due date is before the invoice date")
        return supplier, amount or Decimal(0), bill_date, due, reference

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        self._read(session, company_id, row, errors)
        return errors

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        supplier = self._supplier(session, company_id, row, [])
        reference = opening.clean_reference(row.text("reference"), "")
        if supplier is not None and reference and repo.bill_by_invoice(session, supplier.id, reference) is not None:
            return f"{supplier.code} invoice {reference} is already in Ziira"
        return None

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        errors: list[str] = []
        supplier, amount, bill_date, due, reference = self._read(session, company_id, row, errors)
        go_live = row.options.as_of
        if errors or supplier is None or bill_date is None or due is None or go_live is None:
            raise ValidationFailed("; ".join(errors) or "The row cannot be read")
        return opening.create_opening_bill(session, supplier=supplier, reference=reference, bill_date=bill_date,
                                           due_date=due, amount=amount, go_live_date=go_live).id

    def totals(self, rows: Sequence[ImportRow]) -> dict[str, Decimal]:
        owed = super().totals(rows)[OWED]
        return {OWED: owed, BOOKS: owed}

    def imported_totals(self, session: Session, company_id: UUID, record_ids: list[UUID]) -> dict[str, Decimal]:
        """What the opening bills say is owed, and what the books hold (as a positive amount) for the same bills."""
        bills = repo.opening_bills(session, set(record_ids))
        books = party_amount_by_source(session, company_id, "opening_payable", set(record_ids), "supplier")
        return {OWED: sum((b.total for b in bills), Decimal(0)), BOOKS: -books}

    def reverse(self, session: Session, company_id: UUID, record_ids: list[UUID], reason: str) -> int:
        return opening.reverse_opening_bills(session, record_ids, reason)

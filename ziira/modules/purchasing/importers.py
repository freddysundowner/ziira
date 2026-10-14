"""Importing suppliers from a file: Purchasing's `imports.importer`. Bank details are never imported: a supplier's
bank account is the classic route for fraud, so it is proposed, confirmed by a second person and approved in Ziira."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.imports.public import ImportColumn, Importer, ImportRow, attempt
from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import SUPPLIERS_MANAGE
from ziira.modules.purchasing.services.suppliers import create_supplier
from ziira.sdk import Session, ValidationFailed


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

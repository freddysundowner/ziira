"""Importing customers from a file: CRM's `imports.importer`. Rows go through `create_customer`, so codes come from the
number series when the file has none. Credit limits are not imported: raising credit needs a second person's approval
(see Customers > Credit)."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.crm.domain import rules
from ziira.modules.crm.permissions import CUSTOMERS_MANAGE
from ziira.modules.crm.services import phones
from ziira.modules.crm.services.customers import create_customer
from ziira.modules.imports.public import ExistingRecord, ImportColumn, Importer, ImportRow, attempt
from ziira.sdk import Session, ValidationFailed, ZiiraError


class CustomerImporter(Importer):
    kind = "customers"
    title = "Customers"
    description = ("Your customer list: one row per customer. Credit limits are not imported (they need approval); "
                   "set them in Customers afterwards.")
    permission = CUSTOMERS_MANAGE
    columns = (
        ImportColumn("name", True, "The customer's name.", "Mama Njeri Stores", aliases=("customer", "customer name")),
        ImportColumn("code", False, "Your customer code. Left out, Ziira numbers them.", "C-001",
                     aliases=("customer code", "account", "account no")),
        ImportColumn("kind", False, "business (default) or individual.", "business", aliases=("type",)),
        ImportColumn("phone", False, "Phone number; national numbers get the company's calling code.", "0712345678",
                     aliases=("mobile", "telephone", "tel")),
        ImportColumn("email", False, "Email address.", "njeri@example.com"),
        ImportColumn("tax_id", False, "Tax number.", "P051234567X", aliases=("tax number", "pin", "vat number")),
        ImportColumn("group", False, "Customer group (for group price lists).", "Wholesale",
                     aliases=("customer group", "category")),
        ImportColumn("payment_terms_days", False, "Days allowed to pay.", "30", aliases=("terms", "payment terms")),
    )
    reversal_note = "Customers cannot be deleted. Put unwanted ones on hold in Customers."

    def key(self, row: ImportRow) -> str | None:
        code = row.text("code").upper()
        return code or f"{row.text('name').lower()}|{''.join(ch for ch in row.text('phone') if ch.isdigit())}"

    def _read(self, session: Session, company_id: UUID, row: ImportRow, errors: list[str]) -> dict[str, object]:
        name = attempt(errors, lambda: rules.clean_name(row.text("name")))
        code = attempt(errors, lambda: rules.normalise_code(row.text("code"))) if row.text("code") else None
        kind = (row.text("kind") or "business").lower()
        if kind not in ("business", "individual"):
            errors.append("kind: write business or individual")
        terms = row.whole_number("payment_terms_days", errors) or 0
        attempt(errors, lambda: rules.check_credit(Decimal(0), terms))
        return {
            "name": name, "code": code, "kind": kind, "terms": terms,
            "phone": attempt(errors, lambda: phones.clean(session, company_id, row.text("phone"))),
            "email": attempt(errors, lambda: rules.clean_email(row.text("email"))),
            "tax_id": attempt(errors, lambda: rules.clean_tax_id(row.text("tax_id"))),
            "group": attempt(errors, lambda: rules.clean_group(row.text("group")))}

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        self._read(session, company_id, row, errors)
        return errors

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        code = row.text("code").upper()
        if code:
            found = session.execute(text("select 1 from crm.customer where company_id = :c and code = :k"),
                                    {"c": str(company_id), "k": code}).first()
            return f"Customer {code} already exists" if found else None
        phone = phones.clean(session, company_id, row.text("phone")) or ""
        found = session.execute(text(
            "select 1 from crm.customer where company_id = :c and lower(name) = lower(:n) "
            "and coalesce(phone, '') = :p"), {"c": str(company_id), "n": row.text("name"), "p": phone}).first()
        return f"A customer called {row.text('name')} with this phone already exists" if found else None

    def find_match(self, session: Session, company_id: UUID, row: ImportRow) -> ExistingRecord | None:
        """The customer already in Ziira with this code, tax number or phone (a move from another system)."""
        checks: list[tuple[str, str, str | None]] = []
        code = row.text("code").upper()
        if code:
            checks.append(("code = :v", "has the same customer code", code))
        try:
            tax = rules.clean_tax_id(row.text("tax_id"))
        except ZiiraError:
            tax = None
        if tax:
            checks.append(("upper(tax_id) = :v", "has the same tax number", tax))
        try:
            phone = phones.clean(session, company_id, row.text("phone"))
        except ZiiraError:
            phone = None
        if phone:
            checks.append(("phone = :v", "has the same phone number", phone))
        for condition, why, value in checks:
            found = session.execute(text(
                f"select code, name from crm.customer where company_id = :c and {condition} "
                "order by created_at limit 1"),
                {"c": str(company_id), "v": value}).first()
            if found:
                return ExistingRecord(found.code, f"{found.name} ({found.code}) {why}")
        return None

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        errors: list[str] = []
        read = self._read(session, company_id, row, errors)
        if errors:
            raise ValidationFailed("; ".join(errors))
        customer = create_customer(
            session, company_id=company_id, name=str(read["name"]), code=read["code"],  # type: ignore[arg-type]
            kind=str(read["kind"]), phone=row.text("phone") or None, email=row.text("email") or None,
            tax_id=row.text("tax_id") or None, customer_group=row.text("group") or None,
            payment_terms_days=int(read["terms"]))   # type: ignore[call-overload]
        return customer.id

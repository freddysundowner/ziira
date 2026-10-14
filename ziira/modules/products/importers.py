"""Importing products (with their selling prices) from a file: the Data Import module's `imports.importer` for
Products. Rows go through the same services as the product screens (create_product, set_price)."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.imports.public import ImportColumn, Importer, ImportRow, attempt
from ziira.modules.products.domain import rules
from ziira.modules.products.permissions import PRICES_MANAGE, PRODUCTS_MANAGE
from ziira.modules.products.repository import products_repo
from ziira.modules.products.services import pricing
from ziira.modules.products.services.create_product import create_product
from ziira.sdk import Session, ValidationFailed, current_context

PRICE_LIST_NAME = "Retail prices"


def _id(session: Session, table: str, code: str) -> UUID | None:
    found = session.execute(text(f"select id from products.{table} where code = :c"), {"c": code}).first()
    return found.id if found else None


def _price_list(session: Session, company_id: UUID) -> UUID:
    """The company's default price list (made on first use)."""
    for existing in products_repo.lists_for_branch(session, company_id, None):
        if existing.is_default and existing.branch_id is None:
            return existing.id
    return pricing.create_price_list(session, company_id=company_id, name=PRICE_LIST_NAME, is_default=True).id


class ProductImporter(Importer):
    kind = "products"
    title = "Products and prices"
    description = ("Your product list: one row per product with its unit and tax code (these must already exist under "
                   "Products > Setup), and optionally its tax-inclusive selling price.")
    permission = PRODUCTS_MANAGE
    money_totals = ("selling prices",)
    columns = (
        ImportColumn("sku", True, "Your product code. Letters, digits, - _ and . (stored in capitals).", "CEM-50",
                     aliases=("code", "item code", "product code", "item number")),
        ImportColumn("name", True, "What the product is called.", "Cement 50kg", aliases=("description", "item name",
                                                                                          "product name")),
        ImportColumn("unit", True, "Code of its unit of measure, as set up in Ziira.", "PCS",
                     aliases=("uom", "unit of measure", "base unit")),
        ImportColumn("tax_code", True, "Code of its tax class, as set up in Ziira.", "STD",
                     aliases=("tax", "vat", "vat code", "tax class")),
        ImportColumn("type", False, "stock (default), non_stock or service.", "stock", aliases=("product type",)),
        ImportColumn("batch_tracked", False, "yes if it is tracked by batch number (stock products only).", "no",
                     aliases=("batch", "batches")),
        ImportColumn("reorder_level", False, "Stock level at which to reorder (stock products).", "20",
                     aliases=("reorder", "min stock", "minimum stock")),
        ImportColumn("price", False, "Selling price including tax, put in the default price list.", "850.00",
                     aliases=("selling price", "unit price", "retail price"), total="selling prices"),
    )
    reversal_note = ("Products cannot be deleted once created. Switch unwanted ones off in Products, or fix them "
                     "there.")

    def key(self, row: ImportRow) -> str | None:
        return row.text("sku").upper() or None

    def _read(self, session: Session, row: ImportRow, errors: list[str]) -> dict[str, object]:
        sku = attempt(errors, lambda: rules.normalise_sku(row.text("sku")))
        name = attempt(errors, lambda: rules.check_name(row.text("name")))
        unit = attempt(errors, lambda: rules.normalise_uom_code(row.text("unit")))
        unit_id = _id(session, "uom", unit) if unit else None
        if unit and unit_id is None:
            errors.append(f"Unit '{unit}' is not set up. Add it under Products > Setup first.")
        tax = attempt(errors, lambda: rules.check_tax_code(row.text("tax_code")))
        tax_id = _id(session, "tax_code", tax) if tax else None
        if tax and tax_id is None:
            errors.append(f"Tax code '{tax}' is not set up. Add it under Products > Setup first.")
        kind = (row.text("type") or "stock").lower().replace(" ", "_").replace("-", "_")
        batch = row.yes_no("batch_tracked", errors) or False
        reorder = row.number("reorder_level", errors)
        price = row.number("price", errors, minimum=Decimal(0))
        if price is not None and price != price.quantize(Decimal("0.01")):
            errors.append("price: at most 2 decimal places")
        attempt(errors, lambda: rules.check_product_type(kind, batch))
        if reorder is not None:
            attempt(errors, lambda: rules.check_reorder_level(reorder, kind))
        return {"sku": sku, "name": name, "unit_id": unit_id, "tax_id": tax_id, "type": kind, "batch": batch,
                "reorder": reorder, "price": price}

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        read = self._read(session, row, errors)
        if read["price"] is not None and not current_context().can(PRICES_MANAGE, company_id=company_id):
            errors.append("price: you do not have permission to set prices")
        return errors

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        sku = row.text("sku").strip().upper()
        return f"Product {sku} already exists" if products_repo.sku_exists(session, company_id, sku) else None

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        errors: list[str] = []
        read = self._read(session, row, errors)
        if errors:
            raise ValidationFailed("; ".join(errors))
        product = create_product(
            session, company_id=company_id, sku=str(read["sku"]), name=str(read["name"]),
            base_uom_id=read["unit_id"], tax_code_id=read["tax_id"],  # type: ignore[arg-type]
            product_type=str(read["type"]), is_batch_tracked=bool(read["batch"]),
            reorder_level=read["reorder"])  # type: ignore[arg-type]
        if read["price"] is not None:
            pricing.set_price(session, _price_list(session, company_id), product_id=product.id,
                              price=read["price"])  # type: ignore[arg-type]
        return product.id

    def imported_totals(self, session: Session, company_id: UUID, record_ids: list[UUID]) -> dict[str, Decimal]:
        total = session.execute(text(
            "select coalesce(sum(price), 0) from products.price_list_item "
            "where product_id = any(:ids) and valid_to is null"), {"ids": [str(i) for i in record_ids]}).scalar_one()
        return {"selling prices": Decimal(total)}

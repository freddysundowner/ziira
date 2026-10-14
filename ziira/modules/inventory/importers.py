"""Importing opening stock from a file: Inventory's `imports.importer`. Each row is one product at one location with
its quantity and unit cost, posted through `post_opening_stock` (the same service the opening-stock screen uses), so the
stock ledger, weighted-average cost and the books see it exactly as if it had been typed in.

A product that already has stock history at the location is skipped (later corrections are adjustments, with a
reason). Each row is its own opening-stock document, so one bad row never holds back the others."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.imports.public import ImportColumn, Importer, ImportRow
from ziira.modules.inventory.domain import costing
from ziira.modules.inventory.permissions import STOCK_ADJUST
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.services.opening_stock import OpeningLine, post_opening_stock
from ziira.modules.products.public import find_product_by_sku
from ziira.sdk import Session, ValidationFailed, current_context


def _value(quantity: Decimal, cost: Decimal) -> Decimal:
    """What the stock ledger will record for the line (cost to 6 places, value to 2)."""
    return costing.round_value(quantity * costing.round_cost(cost))


class OpeningStockImporter(Importer):
    kind = "opening_stock"
    title = "Opening stock"
    description = ("The stock you hold on the day you start: one row per product per location, with quantity and unit "
                   "cost. Import your products first. Do this once; later corrections are stock adjustments.")
    permission = STOCK_ADJUST
    money_totals = ("stock value",)
    columns = (
        ImportColumn("sku", True, "The product's SKU, as in Ziira.", "CEM-50", aliases=("code", "item code",
                                                                                          "product code")),
        ImportColumn("location", True, "Code of the stock location (store or warehouse).", "MAIN",
                     aliases=("store", "warehouse", "location code")),
        ImportColumn("quantity", True, "How many you hold, in the product's unit.", "120", aliases=("qty", "on hand",
                                                                                                    "stock"),
                     total="quantity"),
        ImportColumn("unit_cost", True, "What one unit cost you (before tax).", "720.50",
                     aliases=("cost", "unit cost", "cost price", "average cost")),
        ImportColumn("batch_no", False, "Batch number (batch-tracked products only).", "B2025-01",
                     aliases=("batch", "lot")),
        ImportColumn("expiry_date", False, "Expiry date of the batch.", "2027-06-30", aliases=("expiry", "expires")),
        ImportColumn("as_of", False, "The date the stock count is as at (default: today).", "2026-01-31",
                     aliases=("date", "business date", "stock date")),
    )
    reversal_note = ("Opening stock cannot be taken back. If a figure is wrong, post a stock adjustment with a reason "
                     "(Stock > Adjustments).")

    def key(self, row: ImportRow) -> str | None:
        batch = row.text("batch_no").upper()
        return f"{row.text('sku').upper()} @ {row.text('location').upper()}" + (f" batch {batch}" if batch else "")

    def _location(self, session: Session, company_id: UUID, code: str) -> Any:
        return session.execute(text("select id, branch_id, code from inventory.location where company_id = :c "
                                    "and upper(code) = upper(:k) and is_active"),
                               {"c": str(company_id), "k": code}).first()

    def _read(self, session: Session, company_id: UUID, row: ImportRow, errors: list[str]) -> dict[str, Any]:
        quantity = row.number("quantity", errors)
        if quantity is None and not row.text("quantity"):
            errors.append("quantity: the quantity is needed")
        elif quantity is not None and quantity <= 0:
            errors.append("quantity: must be more than zero")
        cost = row.number("unit_cost", errors, minimum=Decimal(0))
        if cost is None and not row.text("unit_cost"):
            errors.append("unit_cost: the unit cost is needed")
        expiry = row.day("expiry_date", errors)
        as_of = row.day("as_of", errors)
        product = find_product_by_sku(session, company_id, row.text("sku")) if row.text("sku") else None
        if not row.text("sku"):
            errors.append("sku: the product code is needed")
        elif product is None:
            errors.append(f"sku: no product with code {row.text('sku').upper()}. Import or add the product first.")
        elif not product.is_active:
            errors.append(f"sku: {product.sku} is switched off")
        elif product.product_type != "stock":
            errors.append(f"sku: {product.sku} is not a stock product, so it has no stock")
        elif product.is_batch_tracked and not row.text("batch_no"):
            errors.append(f"batch_no: {product.sku} is batch-tracked, so a batch number is needed")
        elif not product.is_batch_tracked and row.text("batch_no"):
            errors.append(f"batch_no: {product.sku} is not batch-tracked")
        location = self._location(session, company_id, row.text("location")) if row.text("location") else None
        if not row.text("location"):
            errors.append("location: the location code is needed")
        elif location is None:
            errors.append(f"location: no active location with code {row.text('location').upper()}. "
                          "Add it under Stock > Locations first.")
        elif not current_context().can(STOCK_ADJUST, company_id=company_id, branch_id=location.branch_id):
            errors.append(f"location: you may not post stock at {location.code}")
        return {"product": product, "location": location, "quantity": quantity, "cost": cost, "expiry": expiry,
                "as_of": as_of}

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        self._read(session, company_id, row, errors)
        return errors

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        errors: list[str] = []
        read = self._read(session, company_id, row, errors)
        if read["product"] is not None and read["location"] is not None and inventory_repo.has_movements(
                session, read["location"].id, read["product"].id):
            return f"{read['product'].sku} already has stock history at {read['location'].code}"
        return None

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        errors: list[str] = []
        read = self._read(session, company_id, row, errors)
        if errors:
            raise ValidationFailed("; ".join(errors))
        as_of: date | None = read["as_of"]
        posted = post_opening_stock(
            session, company_id=company_id, location_id=read["location"].id, business_date=as_of,
            lines=[OpeningLine(read["product"].id, read["quantity"], read["cost"], row.text("batch_no") or None,
                               read["expiry"])])
        return posted[0].id

    def totals(self, rows: Any) -> dict[str, Decimal]:
        sums = super().totals(rows)
        value = Decimal(0)
        for row in rows:
            quantity, cost = row.number("quantity", []), row.number("unit_cost", [])
            if quantity is not None and cost is not None:
                value += _value(quantity, cost)
        sums["stock value"] = value
        return sums

    def imported_totals(self, session: Session, company_id: UUID, record_ids: list[UUID]) -> dict[str, Decimal]:
        found = session.execute(text(
            "select coalesce(sum(quantity), 0) as q, coalesce(sum(value), 0) as v from inventory.stock_movement "
            "where id = any(:ids)"), {"ids": [str(i) for i in record_ids]}).one()
        return {"quantity": Decimal(found.q), "stock value": Decimal(found.v)}

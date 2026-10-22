"""Use cases: read stock balances, movements and costs."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.domain.costing import round_value
from ziira.modules.inventory.permissions import STOCK_COST, STOCK_VIEW
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import Batch, Location, StockBalance, StockMovement
from ziira.modules.products.public import find_product, product_labels
from ziira.sdk import NotFound, Session, current_context


@dataclass(frozen=True)
class ProductStock:
    """A product's stock across a company's locations."""

    product_id: UUID
    company_id: UUID
    quantity: Decimal
    average_cost: Decimal | None      # None when the user may not see costs
    value: Decimal | None


def list_balances(session: Session, *, location_id: UUID | None = None, product_id: UUID | None = None,
                  branch_id: UUID | None = None, include_zero: bool = False, limit: int = 100,
                  offset: int = 0) -> list[tuple[StockBalance, Location, str | None, str | None]]:
    """Stock per location, product and batch, for the branches the user may see. Each row also has the
    product's SKU and name."""
    rows = inventory_repo.list_balances(
        session, current_context().scopes_with(STOCK_VIEW), location_id=location_id, product_id=product_id,
        branch_id=branch_id, include_zero=include_zero, limit=min(limit, 500), offset=offset)
    labels = product_labels(session, {balance.product_id for balance, _ in rows})
    return [(balance, location, *labels.get(balance.product_id, (None, None))) for balance, location in rows]


def expiring_stock(session: Session, *, days: int = 90,
                   limit: int = 100) -> list[tuple[StockBalance, Location, Batch, str | None, str | None]]:
    """Stock that expires within `days` days (or already has), earliest first, for the branches the user may see. Each
    row has the balance, its location and batch, and the product's SKU and name."""
    until = datetime.now(UTC).date() + timedelta(days=max(0, min(days, 3650)))
    scopes = current_context().scopes_with(STOCK_VIEW)
    rows = inventory_repo.expiring_balances(session, scopes, until, min(limit, 500))
    labels = product_labels(session, {balance.product_id for balance, _, _ in rows})
    return [(balance, location, batch, *labels.get(balance.product_id, (None, None)))
            for balance, location, batch in rows]


def list_movements(session: Session, *, location_id: UUID | None = None, product_id: UUID | None = None,
                   source_id: UUID | None = None, limit: int = 100, offset: int = 0) -> list[StockMovement]:
    """The stock ledger, newest first, for the branches the user may see."""
    return inventory_repo.list_movements(
        session, current_context().scopes_with(STOCK_VIEW), location_id=location_id, product_id=product_id,
        source_id=source_id, limit=min(limit, 500), offset=offset)


def can_see_cost(company_id: UUID, branch_id: UUID | None) -> bool:
    """True if the user may see what stock cost at this branch."""
    return current_context().can(STOCK_COST, company_id=company_id, branch_id=branch_id)


def product_stock(session: Session, product_id: UUID) -> ProductStock:
    """A product's stock at the locations the user may see. With 'stock.cost' it also gives the
    company's average cost and the value of that stock at the average."""
    ctx = current_context()
    product = find_product(session, product_id)
    companies = ctx.companies_with(STOCK_VIEW)
    if product is None or (companies is not None and product.company_id not in companies):
        raise NotFound("Product not found")
    quantity = inventory_repo.visible_on_hand(session, ctx.scopes_with(STOCK_VIEW), product_id)
    cost_companies = ctx.companies_with(STOCK_COST)
    if cost_companies is not None and product.company_id not in cost_companies:
        return ProductStock(product_id, product.company_id, quantity, None, None)
    cost = inventory_repo.get_cost(session, product.company_id, product_id)
    average = cost.average_cost if cost else Decimal(0)
    return ProductStock(product_id, product.company_id, quantity, average, round_value(quantity * average))

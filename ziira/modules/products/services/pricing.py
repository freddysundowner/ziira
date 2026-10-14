"""Use cases: price lists and the prices in them.

A price is tax-inclusive and has a start date. Setting a new price ends the current one the day before, so the history
of what a product sold for is kept and a sale on any past day can be priced again.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ziira.modules.products.permissions import PRICES_MANAGE, PRODUCTS_VIEW
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import PriceList, PriceListItem
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    publish,
)

NAIROBI = ZoneInfo("Africa/Nairobi")
MAX_PRICE = Decimal("100000000")


def today() -> date:
    return datetime.now(NAIROBI).date()


def create_price_list(session: Session, *, company_id: UUID, name: str, branch_id: UUID | None = None,
                      is_default: bool = False, customer_group: str | None = None) -> PriceList:
    """Create a price list. A default list prices every sale of the company (or of one branch); only one default is
    allowed for each. A list for a customer group prices what customers of that group buy (where it has a price; the
    default list covers the rest). Needs 'prices.manage' for the company."""
    ctx = current_context()
    ctx.require(PRICES_MANAGE, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    name = name.strip()
    if not name:
        raise ValidationFailed("A price list needs a name")
    group = " ".join(customer_group.split()) if customer_group else None
    if group and is_default:
        raise ValidationFailed("A list for a customer group is not a default list")
    if is_default and any(x.branch_id == branch_id for x in products_repo.lists_for_branch(session, company_id,
                                                                                         branch_id)):
        raise Conflict("There is already a default price list for that company or branch")
    currency = session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one()
    price_list = PriceList(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, name=name,
                           branch_id=branch_id, is_default=is_default, customer_group=group, currency=currency)
    products_repo.add_price(session, price_list)
    audit_record(session, "create", "products.price_list", price_list.id, {"name": name, "default": is_default})
    return price_list


def get_price_list(session: Session, price_list_id: UUID) -> PriceList:
    price_list = products_repo.get_price_list(session, price_list_id)
    if price_list is None or not current_context().can(PRODUCTS_VIEW, company_id=price_list.company_id):
        raise NotFound("Price list not found")
    return price_list


def list_price_lists(session: Session) -> list[PriceList]:
    return products_repo.list_price_lists(session, current_context().companies_with(PRODUCTS_VIEW))


def set_price(session: Session, price_list_id: UUID, *, product_id: UUID, price: Decimal,
              valid_from: date | None = None) -> PriceListItem:
    """Set a product's tax-inclusive price from a date (today by default), ending the price before it. Needs
    'prices.manage' for the list's company."""
    price_list = products_repo.get_price_list(session, price_list_id, lock=True)
    if price_list is None:
        raise NotFound("Price list not found")
    ctx = current_context()
    ctx.require(PRICES_MANAGE, company_id=price_list.company_id, branch_id=price_list.branch_id)
    product = products_repo.get_product(session, product_id)
    if product is None or product.company_id != price_list.company_id:
        raise ValidationFailed("Product not found in this company")
    if price < 0 or price > MAX_PRICE or price != price.quantize(Decimal("0.01")):
        raise ValidationFailed("A price is an amount of zero or more with at most 2 decimal places")
    start = valid_from or today()
    current = products_repo.open_price_item(session, price_list_id, product_id)
    if current is not None:
        if current.valid_from >= start:
            raise Conflict(f"A price already starts on {current.valid_from}: set the new one from a later date")
        current.valid_to = start - timedelta(days=1)
        session.flush()
    item = PriceListItem(tenant_id=ctx.tenant_id, created_by=ctx.user_id, price_list_id=price_list_id,
                         product_id=product_id, uom_id=product.base_uom_id, price=price, valid_from=start)
    products_repo.add_price(session, item)
    audit_record(session, "set_price", "products.price_list_item", item.id,
                 {"product_id": product_id, "price": price, "valid_from": start})
    publish(session, Event("price.changed", "products.product", product_id, {
        "company_id": price_list.company_id, "price_list_id": price_list_id, "price": price, "valid_from": start,
        "previous": current.price if current is not None else None}))
    return item


def list_prices(session: Session, price_list_id: UUID, product_id: UUID | None = None, limit: int = 100,
                offset: int = 0) -> list[PriceListItem]:
    get_price_list(session, price_list_id)
    return products_repo.price_items(session, price_list_id, product_id, min(limit, 500), offset)


def current_prices(session: Session, company_id: UUID, branch_id: UUID | None, product_ids: set[UUID],
                   day: date | None = None, customer_group: str | None = None) -> dict[UUID, Decimal]:
    """The tax-inclusive selling price of each product that has one on `day`: from a list for the customer's group if
    there is one, then the branch's default list, then the company's. Products without a price are absent."""
    day = day or today()
    prices: dict[UUID, Decimal] = {}
    for price_list in products_repo.lists_for_branch(session, company_id, branch_id, customer_group):
        wanted = product_ids - prices.keys()
        for product_id, item in products_repo.prices_on(session, price_list.id, wanted, day).items():
            prices[product_id] = item.price
    return prices

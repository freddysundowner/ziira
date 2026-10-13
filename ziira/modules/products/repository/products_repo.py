"""Database access for the products schema. Row-level security scopes every query to the tenant."""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ziira.modules.products.repository.models import PriceList, PriceListItem, Product, TaxCode, Uom


def add(session: Session, record: Uom | TaxCode | Product) -> None:
    """Insert a record and load its generated columns."""
    session.add(record)
    session.flush()
    session.refresh(record)


def list_uoms(session: Session) -> list[Uom]:
    return list(session.scalars(select(Uom).order_by(Uom.code)))


def list_tax_codes(session: Session) -> list[TaxCode]:
    return list(session.scalars(select(TaxCode).order_by(TaxCode.code)))


def uom_code_exists(session: Session, code: str) -> bool:
    return session.scalar(select(Uom.id).where(Uom.code == code)) is not None


def get_uom(session: Session, uom_id: UUID) -> Uom | None:
    return session.get(Uom, uom_id)


def get_tax_code(session: Session, tax_code_id: UUID) -> TaxCode | None:
    return session.get(TaxCode, tax_code_id)


def tax_code_exists(session: Session, code: str) -> bool:
    return session.scalar(select(TaxCode.id).where(TaxCode.code == code)) is not None


def sku_exists(session: Session, company_id: UUID, sku: str) -> bool:
    return session.scalar(
        select(Product.id).where(Product.company_id == company_id, Product.sku == sku)) is not None


def name_exists(session: Session, company_id: UUID, name: str) -> bool:
    """Case- and space-insensitive name check within a company."""
    return session.scalar(select(Product.id).where(
        Product.company_id == company_id,
        func.lower(func.trim(Product.name)) == name.strip().lower())) is not None


def get_products(session: Session, product_ids: set[UUID]) -> list[Product]:
    if not product_ids:
        return []
    return list(session.scalars(select(Product).where(Product.id.in_(product_ids))))


def get_product(session: Session, product_id: UUID) -> Product | None:
    return session.get(Product, product_id)


def list_products(session: Session, search: str | None, limit: int, offset: int,
                  company_ids: set[UUID] | None = None, only_active: bool = False) -> list[Product]:
    """Products by name; `company_ids` limits the companies (None = all)."""
    query = select(Product).order_by(Product.name, Product.id).limit(limit).offset(offset)
    if only_active:
        query = query.where(Product.is_active)
    if company_ids is not None:
        query = query.where(Product.company_id.in_(company_ids))
    if search:
        # % and _ in what the user typed are ordinary characters, not wildcards
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(Product.name.ilike(pattern, escape="\\") | Product.sku.ilike(pattern, escape="\\"))
    return list(session.scalars(query))


# --------------------------------------------------------------------------- price lists
def add_price(session: Session, record: PriceList | PriceListItem) -> None:
    session.add(record)
    session.flush()
    session.refresh(record)


def get_price_list(session: Session, price_list_id: UUID, *, lock: bool = False) -> PriceList | None:
    if lock:
        return session.scalars(select(PriceList).where(PriceList.id == price_list_id).with_for_update()).first()
    return session.get(PriceList, price_list_id)


def list_price_lists(session: Session, company_ids: set[UUID] | None) -> list[PriceList]:
    query = select(PriceList).order_by(PriceList.name)
    if company_ids is not None:
        query = query.where(PriceList.company_id.in_(company_ids))
    return list(session.scalars(query))


def lists_for_branch(session: Session, company_id: UUID, branch_id: UUID | None) -> list[PriceList]:
    """The lists that price a sale at a branch, most specific first: the branch's own, then the company's default."""
    query = select(PriceList).where(PriceList.company_id == company_id, PriceList.is_default.is_(True))
    if branch_id is not None:
        query = query.where(PriceList.branch_id.in_([branch_id]) | PriceList.branch_id.is_(None))
    else:
        query = query.where(PriceList.branch_id.is_(None))
    lists = list(session.scalars(query))
    return sorted(lists, key=lambda x: x.branch_id is None)


def prices_on(session: Session, price_list_id: UUID, product_ids: set[UUID], day: date) -> dict[UUID, PriceListItem]:
    """The price in force on `day` for each product (the latest start date wins)."""
    if not product_ids:
        return {}
    rows = session.scalars(select(PriceListItem).where(
        PriceListItem.price_list_id == price_list_id, PriceListItem.product_id.in_(product_ids),
        PriceListItem.valid_from <= day, (PriceListItem.valid_to.is_(None)) | (PriceListItem.valid_to >= day))
        .order_by(PriceListItem.valid_from))
    found: dict[UUID, PriceListItem] = {}
    for row in rows:
        found[row.product_id] = row                                  # later start dates overwrite earlier ones
    return found


def price_items(session: Session, price_list_id: UUID, product_id: UUID | None, limit: int,
                offset: int) -> list[PriceListItem]:
    query = select(PriceListItem).where(PriceListItem.price_list_id == price_list_id).order_by(
        PriceListItem.product_id, PriceListItem.valid_from.desc()).limit(limit).offset(offset)
    if product_id is not None:
        query = query.where(PriceListItem.product_id == product_id)
    return list(session.scalars(query))


def open_price_item(session: Session, price_list_id: UUID, product_id: UUID) -> PriceListItem | None:
    """The price with no end date (the current one), if any."""
    return session.scalars(select(PriceListItem).where(
        PriceListItem.price_list_id == price_list_id, PriceListItem.product_id == product_id,
        PriceListItem.valid_to.is_(None)).order_by(PriceListItem.valid_from.desc())).first()

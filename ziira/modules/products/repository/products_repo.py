"""Database access for the products schema. Row-level security scopes every query to the tenant."""

from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from ziira.modules.products.repository.models import PriceList, PriceListItem, Product, ProductBarcode, TaxCode, Uom


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
                  company_ids: set[UUID] | None = None, only_active: bool = False,
                  barcode: str | None = None) -> list[Product]:
    """Products by name; `company_ids` limits the companies (None = all); `barcode` keeps the product with that code."""
    query = select(Product).order_by(Product.name, Product.id).limit(limit).offset(offset)
    if barcode:
        query = query.where(Product.id.in_(select(ProductBarcode.product_id).where(ProductBarcode.barcode == barcode)))
    if only_active:
        query = query.where(Product.is_active)
    if company_ids is not None:
        query = query.where(Product.company_id.in_(company_ids))
    if search:
        # % and _ in what the user typed are ordinary characters, not wildcards
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        # a scanned code finds its product too, whatever the product is called
        by_code = Product.id.in_(select(ProductBarcode.product_id).where(ProductBarcode.barcode == search))
        by_text = Product.name.ilike(pattern, escape="\\") | Product.sku.ilike(pattern, escape="\\")
        query = query.where(by_text | by_code)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- barcodes
def barcodes_of(session: Session, product_ids: set[UUID]) -> dict[UUID, list[str]]:
    """The barcodes of each product (products without any are absent)."""
    found: dict[UUID, list[str]] = {}
    if not product_ids:
        return found
    for row in session.scalars(select(ProductBarcode).where(ProductBarcode.product_id.in_(product_ids))
                               .order_by(ProductBarcode.created_at, ProductBarcode.barcode)):
        found.setdefault(row.product_id, []).append(row.barcode)
    return found


def barcode_owner(session: Session, company_id: UUID, barcode: str) -> UUID | None:
    """The product of this company that has the code, if any."""
    return session.scalar(select(ProductBarcode.product_id).where(
        ProductBarcode.company_id == company_id, ProductBarcode.barcode == barcode))


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


def lists_for_branch(session: Session, company_id: UUID, branch_id: UUID | None,
                     customer_group: str | None = None) -> list[PriceList]:
    """The lists that price a sale, most specific first: lists for the customer's group (the branch's, then the
    company's), then the branch's default list, then the company's default."""
    where = [PriceList.company_id == company_id]
    if branch_id is not None:
        where.append(PriceList.branch_id.in_([branch_id]) | PriceList.branch_id.is_(None))
    else:
        where.append(PriceList.branch_id.is_(None))
    wanted: ColumnElement[bool] = PriceList.is_default.is_(True)
    if customer_group:
        wanted = or_(wanted, PriceList.customer_group == customer_group)
    lists = list(session.scalars(select(PriceList).where(*where, wanted).order_by(PriceList.name, PriceList.id)))

    def rank(x: PriceList) -> tuple[int, int]:
        grouped = bool(customer_group) and x.customer_group == customer_group
        return (0 if grouped else 1, 0 if x.branch_id is not None else 1)

    return sorted(lists, key=rank)


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


def replace_barcodes(session: Session, product: Product, add: list[str], remove: list[str], tenant_id: UUID,
                     user_id: UUID | None) -> None:
    """Delete the `remove` codes of the product and insert the `add` codes (removals first, so a code can move)."""
    if remove:
        for row in session.scalars(select(ProductBarcode).where(
                ProductBarcode.product_id == product.id, ProductBarcode.barcode.in_(remove))):
            session.delete(row)
        session.flush()
    for code in add:
        session.add(ProductBarcode(tenant_id=tenant_id, created_by=user_id, company_id=product.company_id,
                                   product_id=product.id, barcode=code))
    session.flush()

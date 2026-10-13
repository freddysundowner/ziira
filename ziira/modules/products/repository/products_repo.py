"""Database access for the products schema. Row-level security scopes every query to the tenant."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ziira.modules.products.repository.models import Product, TaxCode, Uom


def add(session: Session, record: Uom | TaxCode | Product) -> None:
    """Insert a record and load its generated columns."""
    session.add(record)
    session.flush()
    session.refresh(record)


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


def get_product(session: Session, product_id: UUID) -> Product | None:
    return session.get(Product, product_id)


def list_products(session: Session, search: str | None, limit: int, offset: int,
                  company_ids: set[UUID] | None = None) -> list[Product]:
    """Products by name; `company_ids` limits the companies (None = all)."""
    query = select(Product).order_by(Product.name).limit(limit).offset(offset)
    if company_ids is not None:
        query = query.where(Product.company_id.in_(company_ids))
    if search:
        pattern = f"%{search}%"
        query = query.where(Product.name.ilike(pattern) | Product.sku.ilike(pattern))
    return list(session.scalars(query))

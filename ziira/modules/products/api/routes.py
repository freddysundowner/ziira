"""HTTP endpoints for products. Routes only translate HTTP to service calls.

`require_permission` rejects users without the permission anywhere; the services check
the scope (which company) themselves.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from ziira.modules.products.api.schemas import (
    ProductIn,
    ProductOut,
    TaxCodeIn,
    TaxCodeOut,
    UomIn,
    UomOut,
)
from ziira.modules.products.permissions import PRODUCTS_MANAGE, PRODUCTS_VIEW
from ziira.modules.products.services.create_product import create_product
from ziira.modules.products.services.create_tax_code import create_tax_code
from ziira.modules.products.services.create_uom import create_uom
from ziira.modules.products.services.find_products import get_product, list_products, list_tax_codes, list_uoms
from ziira.modules.products.services.suggest_skus import suggest_skus
from ziira.sdk import Session, db_session, page_limit, page_offset, require_permission

router = APIRouter()
VIEW = [Depends(require_permission(PRODUCTS_VIEW))]
MANAGE = [Depends(require_permission(PRODUCTS_MANAGE))]


@router.post("/uoms", response_model=UomOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_uom(body: UomIn, session: Session = Depends(db_session)) -> object:
    return create_uom(session, body.code, body.name)


@router.get("/uoms", response_model=list[UomOut], dependencies=VIEW)
def get_uoms(session: Session = Depends(db_session)) -> object:
    return list_uoms(session)


@router.get("/tax-codes", response_model=list[TaxCodeOut], dependencies=VIEW)
def get_tax_codes(session: Session = Depends(db_session)) -> object:
    return list_tax_codes(session)


@router.post("/tax-codes", response_model=TaxCodeOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_tax_code(body: TaxCodeIn, session: Session = Depends(db_session)) -> object:
    return create_tax_code(session, body.code, body.name, body.vat_rate, body.etims_tax_type)


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_product(body: ProductIn, session: Session = Depends(db_session)) -> object:
    return create_product(session, **body.model_dump())


@router.get("/products", response_model=list[ProductOut], dependencies=VIEW)
def get_products(search: str | None = None, limit: int = page_limit(50), offset: int = page_offset(),
                 session: Session = Depends(db_session)) -> object:
    return list_products(session, search, limit, offset)


@router.get("/sku-suggestions", response_model=list[str], dependencies=MANAGE)
def get_sku_suggestions(company_id: UUID, name: str, session: Session = Depends(db_session)) -> object:
    """SKUs suggested for a new product name by the units enabled for this business."""
    return suggest_skus(session, company_id, name)


@router.get("/products/{product_id}", response_model=ProductOut, dependencies=VIEW)
def get_one_product(product_id: UUID, session: Session = Depends(db_session)) -> object:
    return get_product(session, product_id)

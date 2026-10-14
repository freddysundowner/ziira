"""HTTP endpoints for products. Routes only translate HTTP to service calls.

`require_permission` rejects users without the permission anywhere; the services check
the scope (which company) themselves.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from ziira.modules.products.api.schemas import (
    PriceIn,
    PriceListIn,
    PriceListOut,
    PriceOut,
    ProductIn,
    ProductOut,
    TaxCodeIn,
    TaxCodeOut,
    UomIn,
    UomOut,
)
from ziira.modules.products.permissions import PRICES_MANAGE, PRODUCTS_MANAGE, PRODUCTS_VIEW
from ziira.modules.products.services import pricing
from ziira.modules.products.services.create_product import create_product
from ziira.modules.products.services.create_tax_code import create_tax_code
from ziira.modules.products.services.create_uom import create_uom
from ziira.modules.products.services.find_products import get_product, list_products, list_tax_codes, list_uoms
from ziira.modules.products.services.suggest_skus import suggest_skus
from ziira.sdk import DB_SESSION, Session, page_limit, page_offset, require_permission

router = APIRouter()
VIEW = [Depends(require_permission(PRODUCTS_VIEW))]
MANAGE = [Depends(require_permission(PRODUCTS_MANAGE))]
PRICES = [Depends(require_permission(PRICES_MANAGE))]


@router.post("/uoms", response_model=UomOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_uom(body: UomIn, session: Session = DB_SESSION) -> object:
    return create_uom(session, body.code, body.name)


@router.get("/uoms", response_model=list[UomOut], dependencies=VIEW)
def get_uoms(session: Session = DB_SESSION) -> object:
    return list_uoms(session)


@router.get("/tax-codes", response_model=list[TaxCodeOut], dependencies=VIEW)
def get_tax_codes(session: Session = DB_SESSION) -> object:
    return list_tax_codes(session)


@router.post("/tax-codes", response_model=TaxCodeOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_tax_code(body: TaxCodeIn, session: Session = DB_SESSION) -> object:
    return create_tax_code(session, body.code, body.name, body.vat_rate, body.authority_code)


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_product(body: ProductIn, session: Session = DB_SESSION) -> object:
    return create_product(session, **body.model_dump())


@router.get("/products", response_model=list[ProductOut], dependencies=VIEW)
def get_products(search: str | None = None, limit: int = page_limit(50), offset: int = page_offset(),
                 session: Session = DB_SESSION) -> object:
    return list_products(session, search, limit, offset)


@router.get("/sku-suggestions", response_model=list[str], dependencies=MANAGE)
def get_sku_suggestions(company_id: UUID, name: str, session: Session = DB_SESSION) -> object:
    """SKUs suggested for a new product name by the units enabled for this business."""
    return suggest_skus(session, company_id, name)


@router.get("/products/{product_id}", response_model=ProductOut, dependencies=VIEW)
def get_one_product(product_id: UUID, session: Session = DB_SESSION) -> object:
    return get_product(session, product_id)


# --------------------------------------------------------------------------- price lists
@router.post("/price-lists", response_model=PriceListOut, status_code=status.HTTP_201_CREATED, dependencies=PRICES)
def post_price_list(body: PriceListIn, session: Session = DB_SESSION) -> object:
    return pricing.create_price_list(session, company_id=body.company_id, name=body.name, branch_id=body.branch_id,
                                     is_default=body.is_default, customer_group=body.customer_group)


@router.get("/price-lists", response_model=list[PriceListOut], dependencies=VIEW)
def get_price_lists(session: Session = DB_SESSION) -> object:
    return pricing.list_price_lists(session)


@router.put("/price-lists/{price_list_id}/prices", response_model=PriceOut, dependencies=PRICES)
def put_price(price_list_id: UUID, body: PriceIn, session: Session = DB_SESSION) -> object:
    """Set a product's tax-inclusive price from a date; the price before it ends the day before."""
    return pricing.set_price(session, price_list_id, product_id=body.product_id, price=body.price,
                             valid_from=body.valid_from)


@router.get("/price-lists/{price_list_id}/prices", response_model=list[PriceOut], dependencies=VIEW)
def get_prices(price_list_id: UUID, product_id: UUID | None = None, limit: int = page_limit(100),
               offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return pricing.list_prices(session, price_list_id, product_id, limit, offset)

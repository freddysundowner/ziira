"""Use case: create a product."""

from decimal import Decimal
from uuid import UUID

from ziira.modules.products.domain import rules
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import Product
from ziira.sdk import (
    Conflict,
    Event,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    publish,
)


def create_product(session: Session, *, company_id: UUID, sku: str, name: str,
                   base_uom_id: UUID, tax_code_id: UUID, product_type: str = "stock",
                   is_batch_tracked: bool = False, reorder_level: Decimal | None = None,
                   etims_item_class: str | None = None) -> Product:
    """Validate, save, audit and publish `product.created` in one transaction."""
    sku = rules.normalise_sku(sku)
    rules.check_product_type(product_type, is_batch_tracked)
    rules.check_reorder_level(reorder_level, product_type)
    if products_repo.get_uom(session, base_uom_id) is None:
        raise ValidationFailed("Base unit does not exist")
    if products_repo.get_tax_code(session, tax_code_id) is None:
        raise ValidationFailed("Tax code does not exist")
    if products_repo.sku_exists(session, company_id, sku):
        raise Conflict(f"SKU '{sku}' already exists in this company")

    ctx = current_context()
    product = Product(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, sku=sku,
        name=name.strip(), product_type=product_type, base_uom_id=base_uom_id,
        tax_code_id=tax_code_id, is_batch_tracked=is_batch_tracked,
        reorder_level=reorder_level, etims_item_class=etims_item_class)
    products_repo.add(session, product)

    audit_record(session, "create", "products.product", product.id,
                 {"sku": sku, "name": product.name, "product_type": product_type})
    publish(session, Event(type="product.created", aggregate_type="products.product",
                           aggregate_id=product.id,
                           payload={"sku": sku, "name": product.name, "company_id": company_id}))
    return product

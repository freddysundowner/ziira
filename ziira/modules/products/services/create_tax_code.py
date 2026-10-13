"""Use case: create a tax code (VAT class and eTIMS tax type)."""

from decimal import Decimal

from ziira.modules.products.domain import rules
from ziira.modules.products.permissions import PRODUCTS_MANAGE
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import TaxCode
from ziira.sdk import Conflict, Session, audit_record, current_context


def create_tax_code(session: Session, code: str, name: str, vat_rate: Decimal,
                    etims_tax_type: str) -> TaxCode:
    """Create a tax code. Codes are unique per tenant (so this needs a tenant-wide grant)."""
    current_context().require(PRODUCTS_MANAGE)
    code = rules.check_tax_code(code)
    name = rules.check_name(name)
    etims_tax_type = rules.check_etims_tax_type(etims_tax_type)
    rules.check_vat_rate(vat_rate)
    if products_repo.tax_code_exists(session, code):
        raise Conflict(f"Tax code '{code}' already exists")
    ctx = current_context()
    tax = TaxCode(tenant_id=ctx.tenant_id, created_by=ctx.user_id, code=code, name=name,
                  vat_rate=vat_rate, etims_tax_type=etims_tax_type)
    products_repo.add(session, tax)
    audit_record(session, "create", "products.tax_code", tax.id,
                 {"code": code, "vat_rate": str(vat_rate)})
    return tax

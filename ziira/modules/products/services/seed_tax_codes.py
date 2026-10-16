"""Use case: add the tax codes a country pack supplies. Idempotent and non-destructive: a code the business already has
(whatever it changed it to) is left alone, and nothing is ever removed."""

from uuid import UUID

from ziira.modules.products.domain import rules
from ziira.modules.products.public import TAX_CODE_SEED
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import TaxCode
from ziira.sdk import Session, audit_record, current_context, pack_providers


def seed_tax_codes(session: Session, company_id: UUID) -> int:
    """Add the pack's tax codes that the business lacks (they are shared by its companies). Returns how many."""
    ctx = current_context()
    added: list[str] = []
    for provider in pack_providers(session, TAX_CODE_SEED, company_id):
        for row in provider.tax_codes():
            code = rules.check_tax_code(row.code)
            if code in added or products_repo.tax_code_exists(session, code):
                continue
            rules.check_vat_rate(row.vat_rate)
            products_repo.add(session, TaxCode(
                tenant_id=ctx.tenant_id, created_by=ctx.user_id, code=code, name=rules.check_name(row.name),
                vat_rate=row.vat_rate, authority_code=rules.check_authority_code(row.authority_code)))
            added.append(code)
    if added:
        audit_record(session, "seed_tax_codes", "products.tax_code", None, {"codes": added})
    return len(added)

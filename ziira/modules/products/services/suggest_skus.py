"""Use case: suggest SKUs for a new product, from every enabled SKU_SUGGESTER implementation."""

from uuid import UUID

from ziira.modules.products.domain import rules
from ziira.modules.products.permissions import PRODUCTS_MANAGE
from ziira.modules.products.public import SKU_SUGGESTER
from ziira.modules.products.repository import products_repo
from ziira.sdk import Session, ValidationFailed, check_company, current_context, implementations


def suggest_skus(session: Session, company_id: UUID, name: str, limit: int = 5) -> list[str]:
    """Valid, unused SKUs suggested by the units enabled for this tenant (none if no unit suggests)."""
    current_context().require(PRODUCTS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    found: list[str] = []
    for suggester in implementations(session, SKU_SUGGESTER):
        for candidate in suggester.suggest(session, company_id, name):
            try:
                sku = rules.normalise_sku(candidate)
            except ValidationFailed:
                continue                      # ignore suggestions that break the SKU rules
            if sku not in found and not products_repo.sku_exists(session, company_id, sku):
                found.append(sku)
    return found[:limit]

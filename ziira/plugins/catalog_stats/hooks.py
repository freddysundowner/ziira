"""How a plugin plugs into another unit's sockets (declared under [extends] in manifest.toml).

- A validator on Products' PRODUCT_BEFORE_CREATE hook: blocks a second product with the same
  name in a company, which keeps the catalogue clean.
- An implementation of Products' SKU_SUGGESTER extension point: suggests a SKU from the name.
"""

import re
from uuid import UUID

from ziira.modules.products.public import (
    PRODUCT_BEFORE_CREATE,
    SKU_SUGGESTER,
    ProductDraft,
    SkuSuggester,
    product_name_exists,
)
from ziira.sdk import Session, ValidationFailed, provides, validate


@validate(PRODUCT_BEFORE_CREATE)
def unique_product_name(session: Session, draft: ProductDraft) -> None:
    """Block a product whose name is already used in the same company."""
    if product_name_exists(session, draft.company_id, draft.name):
        raise ValidationFailed(f"A product called '{draft.name}' already exists in this company")


@provides(SKU_SUGGESTER)
class InitialsSuggester(SkuSuggester):
    """'Cement 50kg bag' -> CEMENT-50KG-BAG and CEM-50KG-BAG."""

    def suggest(self, session: Session, company_id: UUID, name: str) -> list[str]:
        words = [w for w in re.split(r"[^A-Za-z0-9]+", name.upper()) if w]
        if not words:
            return []
        full = "-".join(words)[:40]
        short = "-".join([words[0][:3], *words[1:]])[:40]
        return [full, short]

"""Sockets the Products module offers to other units (see public.py for their contracts), and the one it plugs into."""

from uuid import UUID

from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.products.importers import ProductImporter
from ziira.modules.products.public import PRODUCT_BEFORE_CREATE, SKU_SUGGESTER, TAX_CODE_SEED, SkuSuggester, TaxCodeSeed
from ziira.modules.products.services.seed_tax_codes import seed_tax_codes
from ziira.modules.products.services.seed_uoms import seed_default_uoms
from ziira.sdk import (
    COUNTRY_SEEDER,
    CountrySeeder,
    Session,
    define_extension_point,
    define_validation_hook,
    provides,
)

define_validation_hook(
    PRODUCT_BEFORE_CREATE,
    "Runs before a product is saved, with a ProductDraft. Raise ValidationFailed to block it.")

define_extension_point(
    SKU_SUGGESTER, SkuSuggester,
    "Suggests SKUs for a new product name; Products shows every enabled unit's suggestions.")

provides(IMPORTS_IMPORTER)(ProductImporter)

define_extension_point(
    TAX_CODE_SEED, TaxCodeSeed,
    "Tax codes a country pack supplies; they are added to a business that switches the pack on.")


@provides(COUNTRY_SEEDER)
class ProductsCountrySeeder(CountrySeeder):
    """Adds the tax codes of the business's country pack."""

    name = "products.tax_codes"

    def seed(self, session: Session, company_id: UUID, country: str | None) -> int:
        return seed_tax_codes(session, company_id)


@provides(COUNTRY_SEEDER)
class ProductsDefaultsSeeder(CountrySeeder):
    """Gives a new business a minimal set of units of measure (data it can edit)."""

    name = "products.default_uoms"

    def seed(self, session: Session, company_id: UUID, country: str | None) -> int:
        return seed_default_uoms(session)

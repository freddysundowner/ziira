"""Sockets the Products module offers to other units (see public.py for their contracts), and the one it plugs into."""

from uuid import UUID

from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.products.importers import ProductImporter
from ziira.modules.products.public import PRODUCT_BEFORE_CREATE, SKU_SUGGESTER, TAX_CODE_SEED, SkuSuggester, TaxCodeSeed
from ziira.modules.products.repository import products_repo
from ziira.modules.products.services.seed_catalogue import seed_catalogue
from ziira.modules.products.services.seed_industry import hide, is_untouched, seed_services
from ziira.modules.products.services.seed_tax_codes import seed_tax_codes
from ziira.modules.products.services.seed_uoms import seed_default_uoms
from ziira.sdk import (
    ATTACHABLE_ENTITY,
    COUNTRY_SEEDER,
    CUSTOM_FIELD_ENTITY,
    INDUSTRY_SEEDER,
    AttachableEntity,
    Category,
    CountrySeeder,
    CustomFieldEntity,
    IndustrySeeder,
    PackData,
    SeedReport,
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


@provides(INDUSTRY_SEEDER)
class ProductsIndustrySeeder(IndustrySeeder):
    """Adds the service items (with a usual duration) and the catalogue (categories, units, example products with
    their custom-field values) an industry pack supplies."""

    name = "products.services"
    unit = "products"

    def seed(self, session: Session, pack: PackData, company_id: UUID) -> SeedReport:
        report = seed_services(session, pack, company_id)
        more = seed_catalogue(session, pack, company_id)
        report.added += more.added
        report.skipped += more.skipped
        report.notes += more.notes
        return report

    def untouched(self, session: Session, item_type: str, item_id: UUID) -> bool:
        return item_type == "product" and is_untouched(session, item_id)

    def remove(self, session: Session, item_type: str, item_id: UUID) -> None:
        hide(session, item_id)


@provides(CUSTOM_FIELD_ENTITY)
class ProductCustomFields(CustomFieldEntity):
    """Products and services can carry a business's own fields (a brand, a shelf, a skill level)."""

    entity_type = "products.product"
    label = "Product or service"
    view_permission = "products.view"
    edit_permission = "products.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        product = products_repo.get_product(session, entity_id)
        return None if product is None else (product.company_id, None)


@provides(ATTACHABLE_ENTITY)
class ProductFiles(AttachableEntity):
    """Products and services can carry pictures and documents (a product photo, a spec sheet)."""

    entity_type = "products.product"
    label = "Product or service"
    view_permission = "products.view"
    edit_permission = "products.manage"

    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        product = products_repo.get_product(session, entity_id)
        return None if product is None else (product.company_id, None)

    def categories(self, session: Session) -> list[Category]:
        return [Category("photo", "Photo"), Category("document", "Document")]

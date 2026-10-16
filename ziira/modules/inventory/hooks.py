"""Sockets the Inventory module plugs into (declared under [extends] in manifest.toml)."""

from uuid import UUID

from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.intel.public import INTEL_BASELINE_METRIC
from ziira.modules.inventory import pulse  # noqa: F401 - registers the Command Center figures
from ziira.modules.inventory.importers import OpeningStockImporter
from ziira.modules.inventory.intel_checks import controls  # noqa: F401 - registers the Intelligence checks
from ziira.modules.inventory.intel_checks.controls import AdjustmentValueByUser
from ziira.modules.inventory.services.seed_store import seed_default_stores
from ziira.modules.inventory.services.verify import verify_stock
from ziira.sdk import COUNTRY_SEEDER, CountrySeeder, IntegrityCheck, Session, provides


@provides("kernel.integrity_check")
class StockLedgerCheck(IntegrityCheck):
    """Stock balances and cost figures must equal what the movements add up to."""

    name = "stock ledger"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        return verify_stock(session, fix=fix)


@provides(COUNTRY_SEEDER)
class InventoryDefaultStoreSeeder(CountrySeeder):
    """Gives each branch with no stock location one store (name and code are data the business can edit)."""

    name = "inventory.default_store"

    def seed(self, session: Session, company_id: UUID, country: str | None) -> int:
        return seed_default_stores(session, company_id)


provides(INTEL_BASELINE_METRIC)(AdjustmentValueByUser)
provides(IMPORTS_IMPORTER)(OpeningStockImporter)

from ziira.modules.inventory import organisation as _organisation  # noqa: E402, F401, I001

from ziira.modules.inventory import ask_tools as _ask_tools  # noqa: E402, F401, I001 - registers the Ask Ziira tools

from ziira.modules.connect.public import CORE_COVERAGE  # noqa: E402, I001
from ziira.modules.inventory.core_coverage import InventoryCoverage  # noqa: E402, I001

provides(CORE_COVERAGE)(InventoryCoverage)  # tells Connectors what Core covers

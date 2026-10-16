"""Sockets the Finance module plugs into (declared under [extends] in manifest.toml)."""

from uuid import UUID

from ziira.modules.finance import intel_checks, pulse  # noqa: F401 - registers the checks and pulse figures
from ziira.modules.finance.action_providers import AskForReconciliation
from ziira.modules.finance.importers import AccountImporter, OpeningTrialBalanceImporter
from ziira.modules.finance.public import CHART_TEMPLATE, ChartTemplate
from ziira.modules.finance.services.books import seed_from_pack
from ziira.modules.finance.services.verify import verify_books
from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.intel.public import INTEL_ACTION
from ziira.sdk import (
    COUNTRY_SEEDER,
    CountrySeeder,
    IntegrityCheck,
    Session,
    define_extension_point,
    provides,
)


@provides("kernel.integrity_check")
class BooksCheck(IntegrityCheck):
    """Every entry balances, the inventory accounts equal the stock ledger, and every stock movement is posted."""

    name = "books"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        return verify_books(session, fix=fix)


define_extension_point(CHART_TEMPLATE, ChartTemplate,
                       "Accounts, journals and posting rules a country pack adds to the general chart of accounts.")


@provides(COUNTRY_SEEDER)
class FinanceCountrySeeder(CountrySeeder):
    """Brings an existing chart of accounts up to the business's country pack (adds only what is missing)."""

    name = "finance.chart"

    def seed(self, session: Session, company_id: UUID, country: str | None) -> int:
        return seed_from_pack(session, company_id)


provides(INTEL_ACTION)(AskForReconciliation)
provides(IMPORTS_IMPORTER)(AccountImporter)
provides(IMPORTS_IMPORTER)(OpeningTrialBalanceImporter)

from ziira.modules.finance import organisation as _organisation  # noqa: E402, F401, I001

from ziira.modules.finance import ask_tools as _ask_tools  # noqa: E402, F401, I001 - registers the Ask Ziira tools

from ziira.modules.connect.public import CORE_COVERAGE  # noqa: E402, I001
from ziira.modules.finance.core_coverage import FinanceCoverage  # noqa: E402, I001

provides(CORE_COVERAGE)(FinanceCoverage)  # tells Connectors what Core covers

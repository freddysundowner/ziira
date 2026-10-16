"""Sockets the People module plugs into (declared under [extends] in manifest.toml): Intelligence checks and baseline
metrics, the figures it adds to the Command Center, and the importer for employees."""

from uuid import UUID

from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.intel.public import INTEL_ACTION
from ziira.modules.people import intel_checks, pulse  # noqa: F401 - importing registers the implementations
from ziira.modules.people.action_providers import NudgeApprover
from ziira.modules.people.importers import EmployeeImporter
from ziira.modules.people.public import STATUTORY_TABLE_SEED, StatutoryTables
from ziira.modules.people.services.seed_statutory import seed_statutory_tables
from ziira.sdk import COUNTRY_SEEDER, CountrySeeder, Session, define_extension_point, provides

define_extension_point(STATUTORY_TABLE_SEED, StatutoryTables,
                       "Statutory rule tables (payroll taxes, contributions, levies) a country pack supplies as data.")


@provides(COUNTRY_SEEDER)
class PeopleCountrySeeder(CountrySeeder):
    """Adds the (unverified) statutory rule tables of the business's country pack."""

    name = "people.statutory_rules"

    def seed(self, session: Session, company_id: UUID, country: str | None) -> int:
        return seed_statutory_tables(session, company_id)


provides(IMPORTS_IMPORTER)(EmployeeImporter)
provides(INTEL_ACTION)(NudgeApprover)

from ziira.modules.people import privacy as _privacy  # noqa: E402, F401, I001 - registers personal-data provider

from ziira.modules.people import ask_tools as _ask_tools  # noqa: E402, F401, I001 - registers the Ask Ziira tools

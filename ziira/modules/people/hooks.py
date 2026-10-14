"""Sockets the People module plugs into (declared under [extends] in manifest.toml): Intelligence checks and baseline
metrics, the figures it adds to the Command Center, and the importer for employees."""

from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.people import intel_checks, pulse  # noqa: F401 - importing registers the implementations
from ziira.modules.people.importers import EmployeeImporter
from ziira.sdk import provides

provides(IMPORTS_IMPORTER)(EmployeeImporter)

from ziira.modules.people import privacy as _privacy  # noqa: E402, F401, I001 - registers personal-data provider

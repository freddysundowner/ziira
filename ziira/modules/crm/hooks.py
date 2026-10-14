"""Sockets the CRM module plugs into (declared under [extends] in manifest.toml): Intelligence checks, the figures
it adds to the Command Center, and the importer for customers."""

from ziira.modules.crm import intel_checks, privacy, pulse  # noqa: F401 - importing registers the implementations
from ziira.modules.crm.importers import CustomerImporter
from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.sdk import provides

provides(IMPORTS_IMPORTER)(CustomerImporter)

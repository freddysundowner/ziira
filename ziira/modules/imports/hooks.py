"""Sockets the Data Import module offers (declared in manifest.toml): the importers units supply."""

from ziira.modules.imports.public import IMPORTS_IMPORTER, Importer
from ziira.sdk import define_extension_point

define_extension_point(IMPORTS_IMPORTER, Importer, "Reads one kind of record from an uploaded file")

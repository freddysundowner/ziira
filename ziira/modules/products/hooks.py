"""Sockets the Products module offers to other units (see public.py for their contracts), and the one it plugs into."""

from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.products.importers import ProductImporter
from ziira.modules.products.public import PRODUCT_BEFORE_CREATE, SKU_SUGGESTER, SkuSuggester
from ziira.sdk import define_extension_point, define_validation_hook, provides

define_validation_hook(
    PRODUCT_BEFORE_CREATE,
    "Runs before a product is saved, with a ProductDraft. Raise ValidationFailed to block it.")

define_extension_point(
    SKU_SUGGESTER, SkuSuggester,
    "Suggests SKUs for a new product name; Products shows every enabled unit's suggestions.")

provides(IMPORTS_IMPORTER)(ProductImporter)

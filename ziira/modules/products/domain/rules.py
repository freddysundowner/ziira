"""Business rules for products. Pure Python: no database, no HTTP."""

import re
from decimal import Decimal

from ziira.sdk import ValidationFailed

SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-_.]{0,39}$")
UOM_PATTERN = re.compile(r"^[A-Z]{1,10}$")
PRODUCT_TYPES = ("stock", "non_stock", "service")


def normalise_sku(sku: str) -> str:
    """Trim and upper-case a SKU, and check it uses only letters, digits, - _ and ."""
    value = sku.strip().upper()
    if not SKU_PATTERN.match(value):
        raise ValidationFailed(
            "SKU must be 1-40 characters: letters, digits, '-', '_' or '.', starting with a letter or digit")
    return value


def normalise_uom_code(code: str) -> str:
    """Unit codes are 1-10 capital letters, e.g. PCS, CTN, KG."""
    value = code.strip().upper()
    if not UOM_PATTERN.match(value):
        raise ValidationFailed("Unit code must be 1-10 letters, e.g. PCS")
    return value


def check_vat_rate(rate: Decimal) -> Decimal:
    """VAT rate is a percentage between 0 and 100."""
    if rate < 0 or rate > 100:
        raise ValidationFailed("VAT rate must be between 0 and 100 percent")
    return rate


def check_product_type(product_type: str, is_batch_tracked: bool) -> None:
    """Only stock products can be batch-tracked."""
    if product_type not in PRODUCT_TYPES:
        raise ValidationFailed(f"Product type must be one of: {', '.join(PRODUCT_TYPES)}")
    if is_batch_tracked and product_type != "stock":
        raise ValidationFailed("Only stock products can be batch-tracked")


def check_reorder_level(level: Decimal | None, product_type: str) -> None:
    """Reorder level applies only to stock products and cannot be negative."""
    if level is None:
        return
    if product_type != "stock":
        raise ValidationFailed("Reorder level applies only to stock products")
    if level < 0:
        raise ValidationFailed("Reorder level cannot be negative")

"""Business rules for products. Pure Python: no database, no HTTP."""

import re
from decimal import Decimal

from ziira.sdk import ValidationFailed

SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-_.]{0,39}$")
UOM_PATTERN = re.compile(r"^[A-Z]{1,10}$")
PRODUCT_TYPES = ("stock", "non_stock", "service")
BARCODE_PATTERN = re.compile(r"^[\x21-\x7e]{1,64}$")
MAX_BARCODES = 20


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


MAX_NAME_LENGTH = 200


def check_name(name: str, what: str = "Name") -> str:
    """A name is required (not just spaces) and at most 200 characters. Returns it trimmed."""
    value = name.strip()
    if not value:
        raise ValidationFailed(f"{what} is required")
    if len(value) > MAX_NAME_LENGTH:
        raise ValidationFailed(f"{what} can be at most {MAX_NAME_LENGTH} characters")
    return value


def check_authority_code(code: str | None) -> str | None:
    """The code a tax authority uses for this tax, if there is one: up to 20 letters, digits, '-', '_' or '.'."""
    if code is None or not code.strip():
        return None
    value = code.strip().upper()
    if not re.match(r"^[A-Z0-9][A-Z0-9_.-]{0,19}$", value):
        raise ValidationFailed("An authority code is up to 20 letters, digits, '-', '_' or '.'")
    return value


def check_tax_code(code: str) -> str:
    """Tax codes are 1-20 capital letters, digits, '-' or '_', e.g. VAT16."""
    value = code.strip().upper()
    if not re.match(r"^[A-Z0-9][A-Z0-9_-]{0,19}$", value):
        raise ValidationFailed("Tax code must be 1-20 characters: letters, digits, '-' or '_'")
    return value


def clean_barcodes(codes: list[str]) -> list[str]:
    """Trim the codes a scanner reads, keep the first of any repeats, and check each is 1-64 visible characters (no
    spaces). Case is kept: some code types are case-sensitive."""
    cleaned: list[str] = []
    for raw in codes:
        code = raw.strip()
        if not BARCODE_PATTERN.match(code):
            raise ValidationFailed(f"Barcode '{code[:20]}' must be 1-64 characters with no spaces")
        if code not in cleaned:
            cleaned.append(code)
    if len(cleaned) > MAX_BARCODES:
        raise ValidationFailed(f"A product can have at most {MAX_BARCODES} barcodes")
    return cleaned

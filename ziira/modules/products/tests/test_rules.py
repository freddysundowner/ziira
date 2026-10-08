"""Unit tests for product rules (no database needed)."""

from decimal import Decimal

import pytest

from ziira.modules.products.domain import rules
from ziira.sdk import ValidationFailed


def test_sku_is_normalised() -> None:
    assert rules.normalise_sku("  cem-50kg ") == "CEM-50KG"


@pytest.mark.parametrize("bad", ["", "-ABC", "has space", "A" * 41, "semi;colon"])
def test_bad_sku_rejected(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        rules.normalise_sku(bad)


def test_vat_rate_range() -> None:
    assert rules.check_vat_rate(Decimal("16")) == Decimal("16")
    with pytest.raises(ValidationFailed):
        rules.check_vat_rate(Decimal("101"))


def test_only_stock_products_can_be_batch_tracked() -> None:
    rules.check_product_type("stock", True)
    with pytest.raises(ValidationFailed):
        rules.check_product_type("service", True)


def test_reorder_level_only_for_stock() -> None:
    rules.check_reorder_level(Decimal("10"), "stock")
    with pytest.raises(ValidationFailed):
        rules.check_reorder_level(Decimal("10"), "service")
    with pytest.raises(ValidationFailed):
        rules.check_reorder_level(Decimal("-1"), "stock")

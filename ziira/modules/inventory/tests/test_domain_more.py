"""More single-unit tests of Inventory's pure rules: documents, transfers, counts, locations, edges."""

from decimal import Decimal
from uuid import uuid4

import pytest

from ziira.modules.inventory.domain import counts, documents, locations, movements, transfers
from ziira.modules.inventory.domain.counts import VarianceLine
from ziira.sdk import Conflict, ValidationFailed

D = Decimal


# --------------------------------------------------------------------------- locations
@pytest.mark.parametrize(("raw", "clean"), [(" main ", "MAIN"), ("a-1", "A-1"), ("X" * 20, "X" * 20),
                                            ("1.2_3", "1.2_3")])
def test_location_codes(raw: str, clean: str) -> None:
    assert locations.normalise_location_code(raw) == clean


@pytest.mark.parametrize("bad", ["", "-A", "A B", "X" * 21, "é", "a/b", "A\x00"])
def test_bad_location_codes(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        locations.normalise_location_code(bad)


@pytest.mark.parametrize(("kind", "branch", "ok"), [("store", True, True), ("warehouse", True, True),
                                                    ("store", False, False), ("warehouse", False, False),
                                                    ("transit", False, True), ("virtual", False, True),
                                                    ("transit", True, False), ("virtual", True, False),
                                                    ("garage", True, False)])
def test_location_kinds_and_branches(kind: str, branch: bool, ok: bool) -> None:
    if ok:
        locations.check_location(kind, branch)
    else:
        with pytest.raises(ValidationFailed):
            locations.check_location(kind, branch)


# --------------------------------------------------------------------------- documents
def test_status_checks() -> None:
    documents.check_status("transfer", "draft", ("draft",), "dispatched")
    with pytest.raises(Conflict, match="pending approval, so it cannot be dispatched"):
        documents.check_status("transfer", "pending_approval", ("draft",), "dispatched")


def test_adjustment_lines() -> None:
    a, b, batch = uuid4(), uuid4(), uuid4()
    documents.check_adjustment_lines([(a, None, D("1")), (a, batch, D("-1")), (b, None, D("2"))])
    for lines in ([], [(a, None, D("0"))], [(a, None, D("1")), (a, None, D("2"))], [(a, None, D("0.00001"))],
                  [(a, None, D("1E+30"))]):
        with pytest.raises(ValidationFailed):
            documents.check_adjustment_lines(lines)


def test_adjustment_size_for_the_approval_matrix() -> None:
    assert documents.adjustment_amount([]) == 0
    assert documents.adjustment_amount([(D("-3"), D("100")), (D("2"), D("50.5"))]) == D("401.00")      # |q| x cost
    assert documents.adjustment_amount([(D("0.0001"), D("0.01"))]) == D("0.00")


# --------------------------------------------------------------------------- transfers
def test_transfer_locations() -> None:
    a, b = uuid4(), uuid4()
    transfers.check_transfer_locations(a, b, "store", "warehouse")
    with pytest.raises(ValidationFailed, match="two different"):
        transfers.check_transfer_locations(a, a, "store", "store")
    for kinds in (("transit", "store"), ("store", "transit")):
        with pytest.raises(ValidationFailed, match="in-transit"):
            transfers.check_transfer_locations(a, b, *kinds)


def test_transfer_lines() -> None:
    a, b, batch = uuid4(), uuid4(), uuid4()
    transfers.check_transfer_lines([(a, None, D("1")), (a, batch, D("2")), (b, None, D("0.0001"))])
    for lines in ([], [(a, None, D("0"))], [(a, None, D("-1"))], [(a, None, D("1")), (a, None, D("1"))]):
        with pytest.raises(ValidationFailed):
            transfers.check_transfer_lines(lines)


def test_received_quantities_and_differences() -> None:
    transfers.check_received_quantity(D("0"))
    transfers.check_received_quantity(D("12.3456"))
    for bad in (D("-1"), D("1.00001"), D("NaN"), D("1E+30")):
        with pytest.raises(ValidationFailed):
            transfers.check_received_quantity(bad)
    assert transfers.Receipt(D("10"), D("7")).difference == -3
    assert transfers.Receipt(D("10"), D("12")).difference == 2
    assert transfers.Receipt(D("10"), D("10")).difference == 0
    assert transfers.variance_value([(D("-3"), D("100")), (D("2"), D("0.505"))]) == D("301.01")
    assert transfers.variance_value([]) == 0


# --------------------------------------------------------------------------- counts
def test_counted_quantities() -> None:
    assert counts.check_counted_quantity(D("0")) == 0
    assert counts.check_counted_quantity(D("4.5")) == D("4.5")
    for bad in (D("-0.1"), D("1.00001"), D("NaN")):
        with pytest.raises(ValidationFailed):
            counts.check_counted_quantity(bad)


def test_variance_arithmetic() -> None:
    assert counts.expected_when_counted(D("100"), D("-5")) == 95
    assert counts.variance(D("93"), D("95")) == -2
    assert counts.variance(D("96"), D("95")) == 1
    assert counts.variance(D("95"), D("95")) == 0


def test_a_count_needs_reasons_only_for_differences() -> None:
    same = VarianceLine(D("0"), D("10"), has_reason=False)
    short = VarianceLine(D("-2"), D("10"), has_reason=True)
    counts.check_ready_to_submit([same, short])
    counts.check_ready_to_submit([])
    with pytest.raises(ValidationFailed, match="2 line"):
        counts.check_ready_to_submit([VarianceLine(D("1"), D("1"), False), VarianceLine(D("-1"), D("1"), False), same])
    assert counts.variance_amount([short, VarianceLine(D("3"), D("2.5"), False), same]) == D("27.50")
    assert counts.variance_amount([]) == 0


# --------------------------------------------------------------------------- movement edges
def test_non_finite_and_huge_numbers_are_refused() -> None:
    for bad in (D("NaN"), D("Infinity"), D("-Infinity"), D("1E+20"), D("99999999999999.99995")):
        with pytest.raises(ValidationFailed):
            movements.check_quantity(bad)
    movements.check_quantity(movements.MAX_QUANTITY)
    movements.check_quantity(-movements.MAX_QUANTITY)
    with pytest.raises(ValidationFailed, match="too large"):
        movements.check_movement("receipt", D("1"), unit_cost=movements.MAX_COST + D("0.000001"))
    movements.check_movement("receipt", D("1"), unit_cost=movements.MAX_COST)


def test_negative_stock_exactly_at_zero_is_not_negative() -> None:
    assert movements.check_negative_stock(D("0"), D("0"), allowed=False) is False
    assert movements.check_negative_stock(D("3"), D("-3"), allowed=False) is False
    assert movements.check_negative_stock(D("0"), D("-0.0001"), allowed=True) is True
    with pytest.raises(ValidationFailed):
        movements.check_negative_stock(D("0"), D("-0.0001"), allowed=False)

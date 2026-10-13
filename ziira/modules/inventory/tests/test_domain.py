"""Unit tests for inventory rules: movements, weighted average costing, negative stock, batches."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from ziira.modules.inventory.domain import costing, movements
from ziira.modules.inventory.domain.batches import BatchStock, pick_first_expiry_first_out
from ziira.modules.inventory.domain.costing import CostState, cost_movement
from ziira.sdk import ValidationFailed

D = Decimal

REASON = uuid4()


# --------------------------------------------------------------------------- movement rules
def test_quantity_cannot_be_zero_or_too_precise() -> None:
    with pytest.raises(ValidationFailed, match="zero"):
        movements.check_quantity(D("0"))
    with pytest.raises(ValidationFailed, match="4 decimal"):
        movements.check_quantity(D("1.00001"))
    assert movements.check_quantity(D("-2.5")) == D("-2.5")


@pytest.mark.parametrize(("kind", "quantity"), [
    ("receipt", D("-1")), ("opening", D("-1")), ("sale_return", D("-1")), ("transfer_in", D("-1")),
    ("sale", D("1")), ("purchase_return", D("1")), ("transfer_out", D("1")), ("write_off", D("1")),
])
def test_direction_follows_the_type(kind: str, quantity: Decimal) -> None:
    with pytest.raises(ValidationFailed, match="must be"):
        movements.check_movement(kind, quantity, reason_code_id=REASON, unit_cost=D("1"))


@pytest.mark.parametrize("kind", ["adjustment", "count_variance"])
def test_adjustments_and_counts_can_go_either_way(kind: str) -> None:
    movements.check_movement(kind, D("3"), reason_code_id=REASON)
    movements.check_movement(kind, D("-3"), reason_code_id=REASON)


@pytest.mark.parametrize("kind", ["adjustment", "count_variance", "write_off"])
def test_reason_is_required(kind: str) -> None:
    with pytest.raises(ValidationFailed, match="reason is required"):
        movements.check_movement(kind, D("-1"), reason_code_id=None)


@pytest.mark.parametrize("kind", ["receipt", "opening", "transfer_in"])
def test_cost_is_required_when_stock_comes_in_from_outside(kind: str) -> None:
    with pytest.raises(ValidationFailed, match="unit cost is required"):
        movements.check_movement(kind, D("1"))
    movements.check_movement(kind, D("1"), unit_cost=D("0"))


def test_unknown_type_and_negative_cost_are_refused() -> None:
    with pytest.raises(ValidationFailed, match="must be one of"):
        movements.check_movement("teleport", D("1"))
    with pytest.raises(ValidationFailed, match="negative"):
        movements.check_movement("receipt", D("1"), unit_cost=D("-1"))


def test_only_active_stock_products_hold_stock() -> None:
    movements.check_product_can_hold_stock("stock", True)
    with pytest.raises(ValidationFailed, match="stock products"):
        movements.check_product_can_hold_stock("service", True)
    with pytest.raises(ValidationFailed, match="inactive"):
        movements.check_product_can_hold_stock("stock", False)


# --------------------------------------------------------------------------- negative stock policy
def test_negative_stock_policy() -> None:
    assert movements.check_negative_stock(D("5"), D("-5"), allowed=False) is False
    assert movements.check_negative_stock(D("5"), D("2"), allowed=False) is False
    with pytest.raises(ValidationFailed, match="Not enough stock: 5 on hand, 6 needed"):
        movements.check_negative_stock(D("5"), D("-6"), allowed=False)
    assert movements.check_negative_stock(D("5"), D("-6"), allowed=True) is True      # allowed: flag for review
    assert movements.check_negative_stock(D("-1"), D("-1"), allowed=True) is True      # already negative


# --------------------------------------------------------------------------- costing
def test_receipts_average_the_cost() -> None:
    state = CostState()
    first = cost_movement(state, "receipt", D("10"), D("100"))
    assert (first.unit_cost, first.value) == (D("100.000000"), D("1000.00"))
    assert first.state == CostState(D("10"), D("1000.00"), D("100.000000"))
    second = cost_movement(first.state, "receipt", D("30"), D("120"))
    assert second.state.average_cost == D("115.000000")             # (1000 + 3600) / 40
    assert second.state.quantity == D("40") and second.state.value == D("4600.00")


def test_outbound_takes_the_current_average_and_leaves_it_unchanged() -> None:
    state = CostState(D("40"), D("4600.00"), D("115.000000"))
    sale = cost_movement(state, "sale", D("-5"))
    assert (sale.unit_cost, sale.value) == (D("115.000000"), D("-575.00"))
    assert sale.state == CostState(D("35"), D("4025.00"), D("115.000000"))


def test_selling_everything_leaves_no_rounding_crumbs() -> None:
    state = cost_movement(CostState(), "receipt", D("3"), D("10")).state
    state = cost_movement(state, "receipt", D("3"), D("11")).state       # 6 units, value 63.00, avg 10.5
    for _ in range(3):
        state = cost_movement(state, "sale", D("-1.3333")).state
    last = cost_movement(state, "sale", -state.quantity)
    assert last.state.quantity == 0 and last.state.value == 0
    assert last.value == -state.value


def test_average_survives_zero_stock_and_a_return_comes_back_at_its_cost() -> None:
    state = cost_movement(CostState(), "receipt", D("2"), D("50")).state
    state = cost_movement(state, "sale", D("-2")).state
    assert state == CostState(D("0"), D("0.00"), D("50.000000"))         # last average kept
    found = cost_movement(state, "adjustment", D("1"))                    # found stock: valued at the average
    assert (found.unit_cost, found.value) == (D("50.000000"), D("50.00"))
    back = cost_movement(found.state, "sale_return", D("1"), D("48"))     # return at the original sale cost
    assert back.state.average_cost == D("49.000000")


def test_transfers_do_not_change_the_company_figure() -> None:
    state = CostState(D("10"), D("1000.00"), D("100.000000"))
    out = cost_movement(state, "transfer_out", D("-4"))
    assert (out.unit_cost, out.value, out.state) == (D("100.000000"), D("-400.00"), state)
    into = cost_movement(state, "transfer_in", D("4"), out.unit_cost)
    assert (into.value, into.state) == (D("400.00"), state)


def test_a_transfer_leaving_transit_keeps_its_dispatch_cost() -> None:
    state = CostState(D("10"), D("1000.00"), D("100.000000"))
    carried = cost_movement(state, "transfer_out", D("-4"), D("90"))        # dispatched when the average was 90
    assert (carried.unit_cost, carried.value, carried.state) == (D("90.000000"), D("-360.00"), state)


def test_negative_stock_is_costed_at_the_last_average_then_corrected_by_the_next_receipt() -> None:
    state = cost_movement(CostState(), "receipt", D("2"), D("10")).state
    oversold = cost_movement(state, "sale", D("-5"))                      # 3 more than there is
    assert oversold.state == CostState(D("-3"), D("-30.00"), D("10.000000"))
    arrived = cost_movement(oversold.state, "receipt", D("10"), D("12"))
    assert arrived.state.quantity == D("7") and arrived.state.value == D("90.00")
    assert arrived.state.average_cost == D("12.857143")


def test_a_receipt_that_does_not_cover_the_shortage_keeps_the_old_average() -> None:
    state = CostState(D("-5"), D("-50.00"), D("10.000000"))
    after = cost_movement(state, "receipt", D("2"), D("30"))
    assert after.state.quantity == D("-3") and after.state.average_cost == D("10.000000")


def test_rebuild_matches_step_by_step_costing() -> None:
    steps = [("receipt", D("10"), D("100")), ("sale", D("-4"), None), ("receipt", D("6"), D("120")),
             ("transfer_out", D("-2"), None), ("transfer_in", D("2"), D("108")), ("write_off", D("-1"), None)]
    state, history = CostState(), []
    for kind, quantity, cost in steps:
        result = cost_movement(state, kind, quantity, cost)
        history.append((kind, quantity, result.value))
        state = result.state
    assert costing.rebuild(history) == state


def test_zero_quantity_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        cost_movement(CostState(), "sale", D("0"))


# --------------------------------------------------------------------------- batches
def test_first_expiry_first_out() -> None:
    a, b, c, d = (uuid4() for _ in range(4))
    stock = [BatchStock(a, D("5"), date(2027, 3, 1)), BatchStock(b, D("5"), date(2027, 1, 1)),
             BatchStock(c, D("5"), None), BatchStock(d, D("0"), date(2026, 12, 1))]
    picks, shortage = pick_first_expiry_first_out(stock, D("8"))
    assert [(p.batch_id, p.quantity) for p in picks] == [(b, D("5")), (a, D("3"))]
    assert shortage == 0
    picks, shortage = pick_first_expiry_first_out(stock, D("20"))
    assert [p.batch_id for p in picks] == [b, a, c]            # batches without expiry go last; empty batch skipped
    assert shortage == D("5")


def test_picking_needs_a_positive_quantity() -> None:
    with pytest.raises(ValueError):
        pick_first_expiry_first_out([], D("0"))

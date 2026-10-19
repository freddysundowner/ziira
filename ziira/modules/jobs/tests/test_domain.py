"""Unit tests for the rules of jobs: the stage workflow and the prices. No database."""

from datetime import date
from decimal import Decimal as D  # noqa: N817

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.jobs.domain import pricing, workflow
from ziira.modules.jobs.domain.workflow import Definition, StatusDef
from ziira.sdk import ValidationFailed


# --------------------------------------------------------------------------- workflow
def test_the_default_workflow_is_sound() -> None:
    workflow.check_definition(workflow.DEFAULT)
    roles = [s.role for s in workflow.DEFAULT.statuses if s.role]
    assert len(roles) == len(set(roles)) and "initial" in roles and "collected" in roles
    codes = {s.code for s in workflow.DEFAULT.statuses}
    assert {"received", "diagnosing", "quoted", "approved", "in_progress", "waiting_for_parts", "ready", "collected",
            "closed", "cancelled"} == codes
    leaving = {a for a, _ in workflow.DEFAULT.moves}
    assert "closed" not in leaving and "cancelled" not in leaving          # nothing leaves a finished job


def test_a_workflow_with_a_mistake_is_refused() -> None:
    ok = StatusDef("a", "A", "open", "initial")
    for bad in (
        Definition([]),
        Definition([ok, StatusDef("a", "Again", "open")]),                       # a code twice
        Definition([ok, StatusDef("b", "B", "open", "initial")]),                # a role twice
        Definition([StatusDef("a", "A", "sleeping")]),                           # unknown kind
        Definition([StatusDef("a", "A", "open", "boss")]),                       # unknown role
        Definition([StatusDef("a", " ", "open")]),                               # no name
        Definition([StatusDef("A b", "A", "open")]),                             # code with a space
        Definition([ok], [("a", "b")]),                                          # move to nowhere
        Definition([ok], [("a", "a")]),                                          # move to itself
    ):
        with pytest.raises(ValidationFailed):
            workflow.check_definition(bad)


def test_moves_are_pairs_of_stages() -> None:
    moves = {("a", "b"), ("b", "c")}
    assert workflow.can_move(moves, "a", "b") and not workflow.can_move(moves, "b", "a")
    assert not workflow.can_move(moves, "a", "c")


# --------------------------------------------------------------------------- prices
def test_lines_are_worth_quantity_times_price_to_the_cent() -> None:
    assert pricing.line_total(D("2"), D("116.00")) == D("232.00")
    assert pricing.line_total(D("1.5"), D("100.00")) == D("150.00")
    assert pricing.line_total(D("3"), D("33.335")) == D("100.01")                     # 100.005 rounds half up


def test_the_tax_inside_a_price_follows_the_rate() -> None:
    assert pricing.tax_inside(D("232.00"), D("16")) == D("32.00")                     # 232 x 16 / 116
    assert pricing.tax_inside(D("150.00"), D("16")) == D("20.69")                     # 20.6896...
    assert pricing.tax_inside(D("300.00"), D("16")) == D("41.38")                     # 41.3793...
    assert pricing.tax_inside(D("100.00"), D("0")) == D("0.00")


def test_totals_add_up_line_by_line() -> None:
    totals = pricing.add_up([(D("232.00"), D("32.00")), (D("150.00"), D("20.69"))])
    assert (totals.total, totals.tax, totals.net) == (D("382.00"), D("52.69"), D("329.31"))
    empty = pricing.add_up([])
    assert empty.total == 0 and empty.net == 0


@given(st.lists(st.tuples(st.decimals(min_value="0.01", max_value="500", places=2),
                          st.decimals(min_value="0", max_value="9999", places=2),
                          st.sampled_from([D("0"), D("8"), D("16"), D("20")])), max_size=12))
def test_net_plus_tax_is_always_the_total(lines: list[tuple[D, D, D]]) -> None:
    amounts = []
    for quantity, price, rate in lines:
        total = pricing.line_total(quantity, price)
        tax = pricing.tax_inside(total, rate)
        assert 0 <= tax <= total
        amounts.append((total, tax))
    result = pricing.add_up(amounts)
    assert result.net + result.tax == result.total == sum((t for t, _ in amounts), D(0))


def test_the_warranty_starts_when_the_item_is_collected() -> None:
    assert pricing.warranty_end(date(2026, 10, 1), 30) == date(2026, 10, 31)
    assert pricing.warranty_end(date(2026, 10, 1), 0) is None
    assert pricing.in_warranty(date(2026, 10, 31), date(2026, 10, 31))
    assert not pricing.in_warranty(date(2026, 10, 31), date(2026, 11, 1))
    assert not pricing.in_warranty(None, date(2026, 10, 1))

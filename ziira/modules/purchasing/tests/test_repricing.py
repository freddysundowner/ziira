"""Putting a selling price right after a cost rise: the arithmetic."""

from decimal import Decimal as D  # noqa: N817

from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.purchasing.action_providers import quantity_to_order
from ziira.modules.purchasing.domain.repricing import margin_percent, price_keeping_margin


def test_a_price_with_tax_that_keeps_the_margin() -> None:
    # 116.00 with 16% tax is 100.00; cost 80 leaves a 20% margin; cost 95 needs 95 / 0.8 = 118.75, then tax: 137.75
    assert margin_percent(D("116.00"), D(16), D(80)) == D(20)
    assert price_keeping_margin(D("116.00"), D(16), D(80), D(95)) == D("137.75")
    assert price_keeping_margin(D("116.00"), D(16), D(80), D(90)) == D("130.50")        # 90 / 0.8 = 112.5, x 1.16


def test_no_tax_and_rounding_to_the_cent() -> None:
    assert price_keeping_margin(D(100), D(0), D(50), D(60)) == D("120.00")              # 50% margin kept
    assert price_keeping_margin(D(100), D(0), D(70), D(71)) == D("101.43")              # 71 / 0.3 ... = 101.4285...


def test_nothing_to_keep_or_nothing_to_change() -> None:
    assert price_keeping_margin(D(100), D(0), D(100), D(120)) is None                    # no margin before
    assert price_keeping_margin(D(100), D(0), D(120), D(130)) is None                    # a loss before
    assert price_keeping_margin(D(100), D(0), D(50), D(50)) is None                      # cost did not rise
    assert price_keeping_margin(D(100), D(0), D(50), D(40)) is None                      # cost fell
    assert margin_percent(D(0), D(16), D(5)) is None


@given(price=st.decimals(min_value="100", max_value="100000", places=2),
       vat=st.sampled_from([D(0), D(8), D(16), D(20)]),
       before=st.decimals(min_value="0.5", max_value="50000", places=2),
       rise=st.decimals(min_value="0.01", max_value="5000", places=2))
def test_the_new_price_gives_the_new_cost_the_old_margin(price: D, vat: D, before: D, rise: D) -> None:
    new_price = price_keeping_margin(price, vat, before, before + rise)
    if new_price is None:
        return
    assert new_price > price
    old_margin = margin_percent(price, vat, before)
    new_margin = margin_percent(new_price, vat, before + rise)
    assert old_margin is not None and new_margin is not None
    assert abs(new_margin - old_margin) < D("0.05")                    # rounding to the cent moves it by a hair


def test_how_much_to_order() -> None:
    assert quantity_to_order(D(10), D(0), D(0)) == D(10)               # empty: back to the reorder level
    assert quantity_to_order(D(10), D(4), D(3)) == D(6)                # the gap is more than a month's sales
    assert quantity_to_order(D(10), D(4), D(25)) == D(25)              # a month's sales are more than the gap
    assert quantity_to_order(None, D(0), D(7)) == D(7)                 # no reorder level: sales only
    assert quantity_to_order(D(10), D(12), D(0)) == D(0)               # already above it

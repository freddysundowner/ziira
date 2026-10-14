"""Rules behind POS's Intelligence checks."""

from decimal import Decimal as D  # noqa: N817

from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.pos.domain.insights import paying_slower, rate, unusually_low


def test_a_day_is_unusually_low_only_when_far_below_a_well_known_normal() -> None:
    assert unusually_low(D(300), D(1000), D(100), 9)
    assert not unusually_low(D(800), D(1000), D(100), 9)            # only 20% down
    assert not unusually_low(D(600), D(1000), D(300), 9)            # 40% down: not enough
    assert not unusually_low(D(480), D(1000), D(300), 9)            # 52% down but within 2 deviations (400)
    assert not unusually_low(D(0), D(1000), D(0), 5)                # too little history
    assert not unusually_low(D(0), D(0), D(0), 20)                  # nothing is normally sold: nothing is low
    assert unusually_low(D(500), D(1000), D(0), 6)                  # exactly half is enough, at exactly 6 samples
    assert unusually_low(D(300), D(1000), D(100), 3, min_history=3)
    assert not unusually_low(D(300), D(1000), D(100), 9, drop_percent=80)


def test_paying_slower_needs_a_real_and_well_founded_rise() -> None:
    assert paying_slower(D(25), D(10), 3, 3)
    assert not paying_slower(D(14), D(10), 3, 3)                    # +40% and 4 days
    assert not paying_slower(D(7), D(3), 3, 3)                      # +133% but only 4 days
    assert not paying_slower(D(25), D(10), 2, 3)                    # too few recent invoices
    assert not paying_slower(D(25), D(10), 3, 2)                    # too few earlier invoices
    assert not paying_slower(D(10), D(25), 3, 3)                    # paying faster
    assert paying_slower(D(14), D(10), 3, 3, increase_percent=30, min_increase_days=3)
    assert not paying_slower(D(15), D(10), 3, 3)                    # exactly +50% is not "more than" 50%


def test_a_rate_needs_something_to_compare_with() -> None:
    assert rate(D(3), D(6)) == D("0.5")
    assert rate(D(3), D(0)) is None


@given(st.decimals(0, 10**6, places=2), st.decimals(0, 10**6, places=2), st.integers(0, 50))
def test_a_low_day_is_never_above_the_normal(value: D, mean: D, n: int) -> None:
    if unusually_low(value, mean, D(0), n):
        assert value < mean

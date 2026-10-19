"""Billing period rules, with the dates worked out by hand."""

from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.memberships.domain import periods


def test_a_month_after_the_31st_stops_at_the_end_of_a_shorter_month() -> None:
    assert periods.shift(date(2026, 1, 31), "month") == date(2026, 2, 28)
    assert periods.shift(date(2028, 1, 31), "month") == date(2028, 2, 29)       # a leap year
    assert periods.shift(date(2026, 11, 15), "quarter") == date(2027, 2, 15)
    assert periods.shift(date(2028, 2, 29), "year") == date(2029, 2, 28)
    assert periods.shift(date(2026, 3, 30), "week", 2) == date(2026, 4, 13)


def test_periods_are_counted_from_the_first_so_a_short_month_does_not_drift() -> None:
    first = date(2026, 1, 31)
    starts = [periods.nth_start(first, "month", 1, None, n) for n in range(5)]
    assert starts == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31)]
    assert periods.nth_start(first, "month", 2, None, 2) == date(2026, 5, 31)    # every second month


def test_due_periods_lists_every_period_that_has_started() -> None:
    due = periods.due_periods(date(2026, 1, 1), "month", 1, None, next_index=0, today=date(2026, 3, 15))
    assert [p.start for p in due.issue] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert [p.end for p in due.issue] == [date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1)]
    assert due.skipped == []
    again = periods.due_periods(date(2026, 1, 1), "month", 1, None, next_index=3, today=date(2026, 3, 15))
    assert again.issue == [] and again.skipped == []


def test_more_missed_periods_than_the_limit_are_skipped_oldest_first() -> None:
    due = periods.due_periods(date(2026, 1, 1), "month", 1, None, next_index=0, today=date(2026, 3, 15),
                              max_catch_up=2)
    assert [p.start for p in due.skipped] == [date(2026, 1, 1)]
    assert [p.start for p in due.issue] == [date(2026, 2, 1), date(2026, 3, 1)]


def test_the_end_date_and_the_run_limit_stop_further_periods() -> None:
    by_date = periods.due_periods(date(2026, 1, 1), "month", 1, None, next_index=0, today=date(2026, 6, 1),
                                  end_date=date(2026, 2, 10))
    assert [p.start for p in by_date.issue] == [date(2026, 1, 1), date(2026, 2, 1)]
    by_count = periods.due_periods(date(2026, 1, 1), "month", 1, None, next_index=0, today=date(2026, 6, 1),
                                   max_runs=2)
    assert [p.index for p in by_count.issue] == [0, 1]
    assert periods.schedule_finished(date(2026, 1, 1), "month", 1, None, next_index=2, end_date=None, max_runs=2)
    assert periods.schedule_finished(date(2026, 1, 1), "month", 1, None, next_index=2, end_date=date(2026, 2, 28),
                                     max_runs=None)
    assert not periods.schedule_finished(date(2026, 1, 1), "month", 1, None, next_index=1, end_date=date(2026, 2, 28),
                                         max_runs=None)


def test_a_membership_starting_mid_month_is_prorated_by_the_days_left() -> None:
    first = periods.first_period(date(2026, 1, 15), "month", prorate=True)
    assert first.end == date(2026, 2, 1) and first.fraction == Decimal(17) / Decimal(31)   # 15 Jan to 31 Jan
    assert periods.prorated_amount(Decimal("62.00"), first.fraction) == Decimal("34.00")
    assert periods.prorated_amount(Decimal("100.00"), first.fraction) == Decimal("54.84")  # 54.8387
    assert periods.prorated_credits(Decimal(10), first.fraction) == Decimal(5)              # 5.48 rounds to 5


def test_without_proration_a_membership_gets_a_full_period_from_its_start() -> None:
    first = periods.first_period(date(2026, 1, 15), "month", prorate=False)
    assert (first.end, first.fraction) == (date(2026, 2, 15), Decimal(1))
    on_the_first = periods.first_period(date(2026, 3, 1), "month", prorate=True)
    assert (on_the_first.end, on_the_first.fraction) == (date(2026, 4, 1), Decimal(1))


def test_a_quarter_is_prorated_over_the_days_of_that_calendar_quarter() -> None:
    first = periods.first_period(date(2026, 5, 16), "quarter", prorate=True)
    assert first.end == date(2026, 7, 1) and first.fraction == Decimal(46) / Decimal(91)    # 1 Apr to 30 Jun = 91 days
    year = periods.first_period(date(2026, 7, 1), "year", prorate=True)
    assert year.end == date(2027, 1, 1) and year.fraction == Decimal(184) / Decimal(365)    # 1 Jul to 31 Dec


@given(first=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
       interval=st.sampled_from(periods.INTERVALS), count=st.integers(1, 3),
       days_on=st.integers(0, 900), catch_up=st.integers(1, 6))
def test_due_periods_are_consecutive_started_and_split_by_the_catch_up_limit(
        first: date, interval: str, count: int, days_on: int, catch_up: int) -> None:
    today = date.fromordinal(first.toordinal() + days_on)
    due = periods.due_periods(first, interval, count, None, next_index=0, today=today, max_catch_up=catch_up)
    everything = due.skipped + due.issue
    assert [p.index for p in everything] == list(range(len(everything)))
    assert all(p.start <= today for p in everything)
    assert all(a.end == b.start for a, b in zip(everything, everything[1:], strict=False))
    assert all(p.end > p.start for p in everything)
    assert len(due.issue) <= catch_up
    assert periods.nth_start(first, interval, count, None, len(everything)) > today


@given(start=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
       interval=st.sampled_from(["month", "quarter", "year"]))
def test_the_prorated_part_is_a_fraction_of_a_whole_period(start, interval) -> None:  # type: ignore[no-untyped-def]
    first = periods.first_period(start, interval, prorate=True)
    assert Decimal(0) < first.fraction <= Decimal(1)
    assert first.end > start
    assert periods.prorated_amount(Decimal("100.00"), first.fraction) <= Decimal("100.00")

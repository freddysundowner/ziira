"""Rate resolution, rounding, grouping and retainers: hand-calculated, with properties where an invariant matters."""

from datetime import date, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ziira.modules.timebilling.domain import billing, budget, engagement, nudges, rates, retainer, timesheet

# a busy machine must not fail a property test on speed alone
settings.register_profile("timebilling", suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
settings.load_profile("timebilling")

P1, P2, C1, U1, U2, S1 = (uuid4() for _ in range(6))
D = date(2026, 3, 10)


def row(rate: str, *, kind: str = "bill", frm: date = date(2026, 1, 1), to: date | None = None, seq: int = 0,
        **named: Any) -> rates.RateRow:
    return rates.RateRow(id=uuid4(), kind=kind, rate=Dec(rate), effective_from=frm, effective_to=to, seq=seq,
                         **named)


def work(**kw: object) -> rates.WorkContext:
    return rates.WorkContext(day=D, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- rate precedence
def test_the_most_specific_row_wins() -> None:
    everyone = row("100")
    role = row("120", role_title="Senior")
    person = row("150", user_id=U1)
    client = row("160", client_id=C1)
    project = row("200", project_id=P1)
    all_rows = [everyone, role, person, client, project]
    ctx = work(project_id=P1, client_id=C1, user_id=U1, role_title="senior ")
    assert rates.resolve(all_rows, ctx) is project                               # 32
    assert rates.resolve(all_rows, work(client_id=C1, user_id=U1, role_title="Senior")) is client      # 16 beats 8, 2
    assert rates.resolve(all_rows, work(user_id=U1, role_title="Senior")) is person                    # 8 beats 2
    assert rates.resolve(all_rows, work(user_id=U2, role_title="Senior")) is role
    assert rates.resolve(all_rows, work(user_id=U2)) is everyone


def test_specificity_is_the_sum_of_the_weights_named() -> None:
    assert rates.specificity(row("1")) == 0
    assert rates.specificity(row("1", project_id=P1, role_title="Senior")) == 34
    assert rates.specificity(row("1", client_id=C1, user_id=U1, service_id=S1)) == 28


def test_a_row_naming_something_the_work_lacks_does_not_match() -> None:
    assert rates.resolve([row("100", project_id=P1)], work(project_id=P2)) is None
    assert rates.resolve([row("100", user_id=U1)], work()) is None


def test_project_and_role_beats_client_and_person() -> None:
    a = row("1", project_id=P1, role_title="Junior")          # 34
    b = row("2", client_id=C1, user_id=U1)                    # 24
    assert rates.resolve([b, a], work(project_id=P1, client_id=C1, user_id=U1, role_title="Junior")) is a


def test_only_rows_in_force_on_the_day_count_and_the_kinds_are_separate() -> None:
    old = row("100", frm=date(2025, 1, 1), to=date(2025, 12, 31))
    new = row("120", frm=date(2026, 1, 1))
    cost = row("40", kind="cost")
    assert rates.resolve([old, new, cost], work()) is new
    assert rates.resolve([old, new, cost], rates.WorkContext(day=date(2025, 6, 1))) is old
    assert rates.resolve([old, new, cost], work(), "cost") is cost
    assert rates.resolve([old], work()) is None                      # expired
    assert rates.resolve([row("1", frm=date(2026, 3, 11))], work()) is None   # not yet


def test_same_specificity_prefers_the_later_start_then_the_later_entry() -> None:
    a = row("100", frm=date(2026, 1, 1), seq=1)
    b = row("110", frm=date(2026, 2, 1), seq=0)
    c = row("120", frm=date(2026, 2, 1), seq=5)
    assert rates.resolve([a, b], work()) is b
    assert rates.resolve([a, b, c], work()) is c


def test_overlap_warning_is_for_identical_scopes_only() -> None:
    a = row("1", user_id=U1, frm=date(2026, 1, 1), to=date(2026, 6, 30))
    b = row("2", user_id=U1, frm=date(2026, 6, 30))
    c = row("2", user_id=U1, frm=date(2026, 7, 1))
    d = row("2", user_id=U2, frm=date(2026, 1, 1))
    assert rates.overlaps(a, b) and not rates.overlaps(a, c) and not rates.overlaps(a, d)


scopes = st.fixed_dictionaries({"project_id": st.sampled_from([None, P1, P2]), "client_id": st.sampled_from([None, C1]),
                                "user_id": st.sampled_from([None, U1, U2]), "service_id": st.sampled_from([None, S1]),
                                "role_title": st.sampled_from([None, "Senior", "Junior"])})


@given(st.lists(scopes, min_size=1, max_size=8), scopes)
def test_the_winner_matches_and_nothing_matching_is_more_specific(named: list[dict[str, Any]],
                                                                  asked: dict[str, Any]) -> None:
    all_rows = [row(str(i + 1), seq=i, **n) for i, n in enumerate(named)]
    ctx = work(**asked)
    best = rates.resolve(all_rows, ctx)
    matching = [r for r in all_rows if rates.matches(r, ctx)]
    if not matching:
        assert best is None
    else:
        assert best in matching
        assert all(rates.specificity(r) <= rates.specificity(best) for r in matching)


# --------------------------------------------------------------------------- rounding and weeks
@pytest.mark.parametrize(("minutes", "step", "mode", "expected"), [
    (7, 15, "up", 15), (15, 15, "up", 15), (16, 15, "up", 30), (7, 15, "nearest", 0 + 15), (22, 15, "nearest", 15),
    (23, 15, "nearest", 30), (22, 15, "down", 15), (14, 15, "down", 0), (10, 1, "up", 10), (0, 15, "up", 0),
    (3, 6, "nearest", 6), (2, 6, "nearest", 6), (61, 60, "nearest", 60)])
def test_rounding_to_a_step(minutes: int, step: int, mode: str, expected: int) -> None:
    assert timesheet.round_to_step(minutes, step, mode) == expected


@given(st.integers(0, 2000), st.sampled_from(timesheet.STEPS), st.sampled_from(timesheet.ROUND_MODES))
def test_rounding_gives_a_multiple_of_the_step_close_to_the_input(minutes: int, step: int, mode: str) -> None:
    out = timesheet.round_to_step(minutes, step, mode)
    assert out % step == 0 or step == 1
    assert abs(out - minutes) <= step
    if mode == "up":
        assert out >= minutes


def test_a_timer_that_ran_at_all_is_at_least_a_minute() -> None:
    assert timesheet.seconds_to_minutes(0, 15) == 0
    assert timesheet.seconds_to_minutes(10, 1) == 1
    assert timesheet.seconds_to_minutes(29, 1, "up") == 1
    assert timesheet.seconds_to_minutes(90, 1) == 2                   # 1.5 minutes: halves go up
    assert timesheet.seconds_to_minutes(20 * 60, 15, "up") == 30
    assert timesheet.seconds_to_minutes(20 * 60, 15, "nearest") == 15


def test_weeks_start_on_the_chosen_day() -> None:
    wed = date(2026, 3, 11)                                           # a Wednesday
    assert timesheet.week_start(wed, 1) == date(2026, 3, 9)
    assert timesheet.week_start(wed, 7) == date(2026, 3, 8)           # Sunday
    assert timesheet.week_start(date(2026, 3, 9), 1) == date(2026, 3, 9)
    assert timesheet.week_days(date(2026, 3, 9))[-1] == date(2026, 3, 15)
    with pytest.raises(ValueError):
        timesheet.week_start(wed, 8)


@given(st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 1, 1)), st.integers(1, 7))
def test_every_day_is_inside_its_own_week(day: date, starts_on: int) -> None:
    start = timesheet.week_start(day, starts_on)
    assert start <= day < start + timedelta(days=7) and start.isoweekday() == starts_on


def test_utilisation_and_hours() -> None:
    assert timesheet.utilisation(1800, 2400) == Dec("75.0")
    assert timesheet.utilisation(10, 0) == 0
    assert timesheet.hours(90) == Dec("1.50") and timesheet.hours(20) == Dec("0.33")


# --------------------------------------------------------------------------- billing lines
def entry(minutes: int, *, project: UUID = P1, user: UUID = U1, name: str = "Ann", task: str = "Design",
          day: date = D, rate: str | None = "100") -> billing.BillableEntry:
    return billing.BillableEntry(uuid4(), project, user, name, task, day, minutes, Dec(rate) if rate else None)


def test_lines_group_by_project_and_price_the_hours() -> None:
    lines = billing.build_lines([entry(90), entry(30, day=D + timedelta(days=1)), entry(60, rate="150")])
    assert [(line.raw_minutes, line.rate, line.amount) for line in lines] == [(120, Dec(100), Dec("200.00")),
                                                                              (60, Dec(150), Dec("150.00"))]
    assert lines[0].dates == (D, D + timedelta(days=1))


def test_grouping_by_person_and_by_task() -> None:
    es = [entry(60, user=U1, name="Ann", task="Design"), entry(60, user=U2, name="Bo", task="Design"),
          entry(30, user=U1, name="Ann", task="design "), entry(30, user=U1, name="Ann", task="Build")]
    by_person = billing.build_lines(es, "person")
    assert [(line.label, line.raw_minutes) for line in by_person] == [("Ann", 120), ("Bo", 60)]
    by_task = billing.build_lines(es, "task")
    assert sorted((line.label, line.raw_minutes) for line in by_task) == [("Build", 30), ("Design", 150)]


def test_rounding_is_applied_to_the_line_not_to_each_entry() -> None:
    es = [entry(7) for _ in range(10)]                                 # 70 minutes
    line = billing.build_lines(es, "project", round_minutes=15)[0]
    assert line.raw_minutes == 70 and line.minutes == 75 and line.amount == Dec("125.00")


def test_unpriced_time_makes_a_line_with_no_rate() -> None:
    line = billing.build_lines([entry(60, rate=None)])[0]
    assert line.rate is None and line.amount == 0


def test_amounts_markup_and_tax() -> None:
    assert billing.amount_for(20, Dec("100")) == Dec("33.33")
    assert billing.amount_for(50, Dec("85.50")) == Dec("71.25")
    assert billing.expense_amount(Dec("100.00"), Dec("10")) == Dec("110.00")
    assert billing.expense_amount(Dec("33.33"), Dec("15")) == Dec("38.33")          # 38.3295
    assert billing.gross_amount(Dec("200.00"), Dec("16"), False) == Dec("232.00")
    assert billing.gross_amount(Dec("200.00"), Dec("16"), True) == Dec("200.00")
    with pytest.raises(ValueError):
        billing.build_lines([], "week")


@given(st.lists(st.integers(1, 600), min_size=1, max_size=15), st.sampled_from([0, 5, 15, 30]))
def test_every_entry_is_in_exactly_one_line_and_minutes_never_shrink(minutes: list[int], step: int) -> None:
    es = [entry(m, day=D + timedelta(days=i % 3), rate=str(50 + i % 2 * 50)) for i, m in enumerate(minutes)]
    lines = billing.build_lines(es, "project", step)
    ids = [i for line in lines for i in line.entry_ids]
    assert sorted(map(str, ids)) == sorted(str(e.id) for e in es)
    assert sum(line.raw_minutes for line in lines) == sum(minutes)
    assert all(line.minutes >= line.raw_minutes for line in lines)


# --------------------------------------------------------------------------- retainers and budgets
def test_a_drawdown_never_goes_below_zero() -> None:
    assert retainer.draw_down(600, 90) == retainer.Drawdown(90, 0, 510)
    assert retainer.draw_down(60, 90) == retainer.Drawdown(60, 30, 0)
    assert retainer.draw_down(0, 45) == retainer.Drawdown(0, 45, 0)
    with pytest.raises(ValueError):
        retainer.draw_down(-1, 5)


@given(st.integers(0, 5000), st.integers(0, 5000))
def test_covered_plus_overage_is_the_work(balance: int, minutes: int) -> None:
    d = retainer.draw_down(balance, minutes)
    assert d.covered + d.overage == minutes and d.balance_after == balance - d.covered >= 0


def test_expiry_and_share_used() -> None:
    assert not retainer.is_expired(D, D) and retainer.is_expired(D, D + timedelta(days=1))
    assert not retainer.is_expired(None, D)
    assert retainer.share_used(600, 150) == 75 and retainer.share_used(0, 0) == 0


def test_budget_state() -> None:
    assert budget.percent_used(Dec(45), Dec(60)) == Dec("75.0")
    assert budget.percent_used(5, None) is None and budget.percent_used(5, 0) is None
    assert budget.state(None, 80) == "none" and budget.state(Dec("79.9"), 80) == "ok"
    assert budget.state(Dec("80.0"), 80) == "near" and budget.state(Dec("100.0"), 80) == "near"
    assert budget.state(Dec("100.1"), 80) == "over"


# --------------------------------------------------------------------------- capped fees
def test_a_cap_takes_the_excess_off_the_newest_lines() -> None:
    assert billing.cap_write_downs([Dec("400"), Dec("300"), Dec("500")], Dec("900")) == [Dec("0"), Dec("0"), Dec("300")]
    assert billing.cap_write_downs([Dec("400"), Dec("300")], Dec("1000")) == [Dec("0"), Dec("0")]
    assert billing.cap_write_downs([Dec("400"), Dec("300")], Dec("500")) == [Dec("0"), Dec("200")]
    assert billing.cap_write_downs([Dec("400"), Dec("300")], Dec("0")) == [Dec("400"), Dec("300")]
    assert billing.cap_write_downs([Dec("400")], Dec("-50")) == [Dec("400")]


@given(st.lists(st.integers(0, 100_000), min_size=0, max_size=10), st.integers(-1000, 400_000))
def test_a_cap_is_never_exceeded_and_never_writes_more_than_a_line_is_worth(cents: list[int], room: int) -> None:
    amounts = [Dec(c) / 100 for c in cents]
    downs = billing.cap_write_downs(amounts, Dec(room) / 100)
    assert all(0 <= d <= a for d, a in zip(downs, amounts, strict=True))
    billed = sum((a - d for d, a in zip(downs, amounts, strict=True)), Dec(0))
    assert billed <= max(Dec(0), Dec(room) / 100)
    assert billed == min(sum(amounts, Dec(0)), max(Dec(0), Dec(room) / 100))


# --------------------------------------------------------------------------- the narrative
def test_the_narrative_lists_notes_by_date_and_sums_the_silent_hours() -> None:
    def entry(day: int, who: str, minutes: int, note: str = "", task: str = "") -> billing.BillableEntry:
        return billing.BillableEntry(uuid4(), P1, uuid4(), who, task, date(2026, 3, day), minutes, Dec("100"), note)

    text = billing.narrative([entry(11, "Wanjiru", 90, "Drafted the lease"), entry(10, "Otieno", 60, task="Review call"),
                              entry(10, "Otieno", 30), entry(12, "Wanjiru", 15)])
    assert text == ("2026-03-10 Otieno: Review call (1.00 h)\n2026-03-11 Wanjiru: Drafted the lease (1.50 h)\n"
                    "Other work: 0.75 h")
    assert billing.narrative([]) == ""
    assert len(billing.narrative([entry(10, "A", 60, "x" * 500) for _ in range(30)], limit=300)) <= 300


# --------------------------------------------------------------------------- recurring work
def test_monthly_work_is_due_each_month_on_its_day_clamped_to_the_month_end() -> None:
    found = engagement.due_dates("monthly", 31, None, date(2026, 1, 1), None, date(2026, 1, 1), date(2026, 4, 30))
    assert found == [("2026-01", date(2026, 1, 31)), ("2026-02", date(2026, 2, 28)), ("2026-03", date(2026, 3, 31)),
                     ("2026-04", date(2026, 4, 30))]


def test_quarterly_and_annual_work_fall_in_their_months_and_respect_start_and_end() -> None:
    q = engagement.due_dates("quarterly", 20, 2, date(2026, 1, 1), None, date(2026, 1, 1), date(2026, 12, 31))
    assert [p for p, _ in q] == ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]
    assert [d.month for _, d in q] == [2, 5, 8, 11]
    a = engagement.due_dates("annual", 30, 6, date(2026, 7, 1), date(2028, 12, 31), date(2026, 1, 1), date(2029, 1, 1))
    assert a == [("2027", date(2027, 6, 30)), ("2028", date(2028, 6, 30))]      # 2026's June was before it started
    with pytest.raises(ValueError):
        engagement.due_dates("weekly", 1, None, D, None, D, D)


@given(st.sampled_from(["monthly", "quarterly", "annual"]), st.integers(1, 31), st.integers(1, 12),
       st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 1, 1)), st.integers(0, 900))
def test_due_dates_are_inside_the_window_unique_and_in_order(freq: str, day: int, month: int, start: date,
                                                             span: int) -> None:
    end = start + timedelta(days=span)
    found = engagement.due_dates(freq, day, month, date(2020, 1, 1), None, start, end)
    assert all(start <= d <= end for _, d in found)
    assert len({p for p, _ in found}) == len(found)
    assert [d for _, d in found] == sorted(d for _, d in found)


# --------------------------------------------------------------------------- reminders
def test_the_working_day_before_skips_the_weekend() -> None:
    monday, saturday = date(2026, 10, 19), date(2026, 10, 17)
    assert nudges.previous_working_day(monday, [1, 2, 3, 4, 5]) == date(2026, 10, 16)       # Friday
    assert nudges.previous_working_day(monday, [1, 2, 3, 4, 5, 6]) == saturday
    assert nudges.previous_working_day(monday, []) is None
    assert nudges.is_last_working_day(date(2026, 10, 16), [1, 2, 3, 4, 5])
    assert not nudges.is_last_working_day(date(2026, 10, 15), [1, 2, 3, 4, 5])
    assert nudges.short_of(60, 240) and not nudges.short_of(240, 240) and not nudges.short_of(0, 0)

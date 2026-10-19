"""Bookings rules: the availability engine (hand-calculated cases and properties), the appointment life, repeats."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.bookings.domain import availability as av
from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.domain import rules
from ziira.modules.bookings.domain.recurrence import MAX_OCCURRENCES, occurrence_dates
from ziira.sdk import ValidationFailed

UTC_ZONE = ZoneInfo("UTC")
NAIROBI = ZoneInfo("Africa/Nairobi")             # a fixture zone: +03:00 all year
MONDAY = date(2026, 10, 19)
NOW = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)


def at(h: int, m: int = 0, day: date = MONDAY, zone: ZoneInfo = UTC_ZONE) -> datetime:
    return datetime.combine(day, time(h, m), tzinfo=zone)


def cal(hours: list[tuple[int, time, time]] | None = None, off: list[av.Interval] | None = None,
        booked: list[av.Interval] | None = None, rid: UUID | None = None) -> av.ResourceCalendar:
    rows = hours if hours is not None else [(0, time(9), time(12))]
    return av.ResourceCalendar(rid or uuid4(), tuple(av.Hours(*r) for r in rows), tuple(off or ()), tuple(booked or ()))


def starts(slots: list[av.Slot], zone: ZoneInfo = UTC_ZONE) -> list[str]:
    return [s.start.astimezone(zone).strftime("%H:%M") for s in slots]


HOUR = av.ServiceShape(60)
FREE = av.Policy(60)


# --------------------------------------------------------------------------- hand-calculated
def test_an_open_morning_offers_each_hour_that_fits() -> None:
    slots = av.free_slots([cal()], HOUR, FREE, MONDAY, NOW, UTC_ZONE)
    assert starts(slots) == ["09:00", "10:00", "11:00"]               # a 60-minute service ending by 12:00
    assert slots[0].end == at(10)


def test_a_booking_blocks_its_time_and_the_buffers_around_it() -> None:
    held = av.blocked_interval(at(10), av.ServiceShape(60, 15, 15))          # 09:45 to 11:15
    assert (held.start, held.end) == (at(9, 45), at(11, 15))
    c = cal(booked=[held])
    shape = av.ServiceShape(30, 0, 0)
    assert starts(av.free_slots([c], shape, av.Policy(15), MONDAY, NOW, UTC_ZONE)) == [
        "09:00", "09:15", "11:15", "11:30"]                                    # 09:30 would run into the 09:45 hold


def test_a_service_buffer_must_not_touch_the_next_booking() -> None:
    c = cal(booked=[av.Interval(at(10), at(11))])
    shape = av.ServiceShape(60, 0, 30)                                          # needs 30 minutes to clean up after
    assert starts(av.free_slots([c], shape, FREE, MONDAY, NOW, UTC_ZONE)) == ["11:00"]   # 09:00 + 60 + 30 hits 10:00
    assert starts(av.free_slots([c], av.ServiceShape(30, 0, 30), av.Policy(30), MONDAY, NOW, UTC_ZONE)) == [
        "09:00", "11:00", "11:30"]


def test_one_booking_may_start_the_moment_another_ends() -> None:
    c = cal(booked=[av.Interval(at(9), at(10))])
    assert starts(av.free_slots([c], HOUR, FREE, MONDAY, NOW, UTC_ZONE)) == ["10:00", "11:00"]


def test_time_off_and_other_days_have_no_slots() -> None:
    c = cal(off=[av.Interval(at(8), at(10, 30))])
    assert starts(av.free_slots([c], HOUR, FREE, MONDAY, NOW, UTC_ZONE)) == ["11:00"]
    assert av.free_slots([cal()], HOUR, FREE, MONDAY + timedelta(days=1), NOW, UTC_ZONE) == []


def test_a_lunch_break_splits_the_day() -> None:
    c = cal([(0, time(9), time(12)), (0, time(13), time(15))])
    assert starts(av.free_slots([c], av.ServiceShape(90), av.Policy(30), MONDAY, NOW, UTC_ZONE)) == [
        "09:00", "09:30", "10:00", "10:30", "13:00", "13:30"]


def test_minimum_notice_and_how_far_ahead_apply_to_clients_only() -> None:
    now = at(8, 30, MONDAY)
    policy = av.Policy(60, min_notice_minutes=120, max_days_ahead=0)
    assert starts(av.free_slots([cal()], HOUR, policy, MONDAY, now, UTC_ZONE)) == ["11:00"]    # 10:30 is the earliest
    assert starts(av.free_slots([cal()], HOUR, policy, MONDAY, now, UTC_ZONE, enforce_policy=False)) == [
        "09:00", "10:00", "11:00"]
    assert av.free_slots([cal([(1, time(9), time(12))])], HOUR, policy, MONDAY + timedelta(days=1), now, UTC_ZONE) == []
    assert av.policy_problems(at(9, 0, MONDAY + timedelta(days=3)), av.Policy(15, 0, 2), now, UTC_ZONE) == [av.TOO_FAR]
    assert av.policy_problems(at(8, 45), av.Policy(15, 30, 9), now, UTC_ZONE) == [av.TOO_SOON]


def test_two_resources_any_lists_who_is_free_and_all_needs_both() -> None:
    a, b = cal(booked=[av.Interval(at(9), at(10))]), cal()
    any_slots = av.free_slots([a, b], HOUR, FREE, MONDAY, NOW, UTC_ZONE)
    assert starts(any_slots) == ["09:00", "10:00", "11:00"]
    assert any_slots[0].resource_ids == (b.resource_id,) and set(any_slots[1].resource_ids) == {a.resource_id, b.resource_id}
    both = av.free_slots([a, b], av.ServiceShape(60, mode="all"), FREE, MONDAY, NOW, UTC_ZONE)
    assert starts(both) == ["10:00", "11:00"] and all(len(s.resource_ids) == 2 for s in both)


def test_hours_are_wall_clock_in_the_company_zone() -> None:
    c = cal([(0, time(9), time(11))])
    slots = av.free_slots([c], HOUR, FREE, MONDAY, NOW, NAIROBI)
    assert starts(slots, NAIROBI) == ["09:00", "10:00"]
    assert slots[0].start == datetime(2026, 10, 19, 6, 0, tzinfo=UTC)         # 09:00 in Nairobi is 06:00 UTC


def test_a_clock_change_does_not_move_opening_time_or_invent_a_missing_hour() -> None:
    paris = ZoneInfo("Europe/Paris")               # clocks go forward on Sunday 29 March 2026 (02:00 becomes 03:00)
    sunday = date(2026, 3, 29)
    c = cal([(6, time(1), time(5))])
    got = av.free_slots([c], HOUR, FREE, sunday, datetime(2026, 3, 20, tzinfo=UTC), paris)
    assert starts(got, paris) == ["01:00", "03:00", "04:00"]
    assert "02:00" not in starts(got, paris)
    assert all(s.start.astimezone(paris).date() == sunday for s in got)


def test_the_midnight_end_time_means_until_midnight() -> None:
    c = cal([(0, time(22), time(23, 59))])
    assert starts(av.free_slots([c], HOUR, FREE, MONDAY, NOW, UTC_ZONE)) == ["22:00", "23:00"]


def test_problems_name_the_reason() -> None:
    c = cal(off=[av.Interval(at(10), at(11))], booked=[av.Interval(at(11), at(12))])
    assert av.problems(c, at(8), HOUR, UTC_ZONE) == [av.OUTSIDE_HOURS]
    assert av.problems(c, at(9, 30), HOUR, UTC_ZONE) == [av.TIME_OFF]
    assert av.problems(c, at(11), HOUR, UTC_ZONE) == [av.CONFLICT]
    assert av.problems(c, at(9), av.ServiceShape(30), UTC_ZONE) == []


# --------------------------------------------------------------------------- properties
windows = st.lists(
    st.tuples(st.integers(0, 6), st.integers(0, 22 * 60), st.integers(15, 360)).map(
        lambda t: (t[0], time(t[1] // 60, t[1] % 60), time(min(t[1] + t[2], 23 * 60 + 58) // 60,
                                                          min(t[1] + t[2], 23 * 60 + 58) % 60))),
    min_size=1, max_size=3)
intervals = st.lists(st.tuples(st.integers(0, 24 * 60 - 1), st.integers(5, 300)).map(
    lambda t: av.Interval(at(0) + timedelta(minutes=t[0]), at(0) + timedelta(minutes=t[0] + t[1]))), max_size=6)
shapes = st.builds(av.ServiceShape, st.sampled_from([15, 30, 45, 60, 90]), st.sampled_from([0, 10, 15]),
                   st.sampled_from([0, 10, 15]), st.sampled_from(["any", "all"]))
policies = st.builds(av.Policy, st.sampled_from([5, 10, 15, 30, 60]), st.sampled_from([0, 60, 600]), st.just(365))


def hours_ok(h: list[tuple[int, time, time]]) -> list[tuple[int, time, time]]:
    """Drop overlapping windows on one day (the rules refuse them)."""
    try:
        rules.check_hours([av.Hours(*r) for r in h])
    except ValidationFailed:
        return h[:1]
    return h


@given(h=windows, off=intervals, booked=intervals, shape=shapes, policy=policies)
@settings(max_examples=150, deadline=None)
def test_every_slot_is_valid_and_no_valid_start_is_missed(h, off, booked, shape, policy) -> None:  # type: ignore[no-untyped-def]
    c = cal(hours_ok(h), off, booked)
    slots = av.free_slots([c], shape, policy, MONDAY, NOW, UTC_ZONE)
    got = {s.start for s in slots}
    for s in slots:
        assert (s.start.hour * 60 + s.start.minute) % policy.granularity_minutes == 0
        assert av.problems(c, s.start, shape, UTC_ZONE) == [] and not av.policy_problems(s.start, policy, NOW, UTC_ZONE)
        held = av.blocked_interval(s.start, shape)
        assert not any(held.overlaps(x) for x in (*c.time_off, *c.booked))
    oracle = {at(0) + timedelta(minutes=m) for m in range(0, 24 * 60, policy.granularity_minutes)
              if not av.problems(c, at(0) + timedelta(minutes=m), shape, UTC_ZONE)
              and not av.policy_problems(at(0) + timedelta(minutes=m), policy, NOW, UTC_ZONE)}
    assert got == oracle


@given(h=windows, shape=shapes, picks=st.lists(st.integers(0, 1000), min_size=1, max_size=12))
@settings(max_examples=100, deadline=None)
def test_booking_free_slots_one_after_another_never_overlaps(h, shape, picks) -> None:  # type: ignore[no-untyped-def]
    one = av.ServiceShape(shape.duration_minutes, shape.buffer_before_minutes, shape.buffer_after_minutes, "any")
    held: list[av.Interval] = []
    rid = uuid4()
    for pick in picks:
        c = av.ResourceCalendar(rid, tuple(av.Hours(*r) for r in hours_ok(h)), (), tuple(held))
        slots = av.free_slots([c], one, av.Policy(15), MONDAY, NOW, UTC_ZONE)
        if not slots:
            break
        chosen = slots[pick % len(slots)]
        new = av.blocked_interval(chosen.start, one)
        assert not any(new.overlaps(x) for x in held)
        held.append(new)
    for i, a in enumerate(held):
        for b in held[i + 1:]:
            assert not a.overlaps(b)


# --------------------------------------------------------------------------- the life of an appointment
def test_the_allowed_moves() -> None:
    walk = [life.REQUESTED, life.CONFIRMED, life.CHECKED_IN, life.IN_SERVICE, life.COMPLETED]
    for a, b in zip(walk, walk[1:], strict=False):
        life.check_move(a, b)
    life.check_move(life.CONFIRMED, life.NO_SHOW)
    life.check_move(life.REQUESTED, life.CANCELLED)
    for a, b in ((life.REQUESTED, life.IN_SERVICE), (life.IN_SERVICE, life.CANCELLED), (life.COMPLETED, life.CANCELLED),
                 (life.CANCELLED, life.CONFIRMED), (life.NO_SHOW, life.CHECKED_IN), (life.CONFIRMED, life.COMPLETED)):
        with pytest.raises(ValidationFailed):
            life.check_move(a, b)


@given(st.sampled_from(life.STATUSES), st.sampled_from(life.STATUSES))
def test_a_finished_appointment_never_moves_and_every_status_is_reachable(a: str, b: str) -> None:
    if a in life.TERMINAL:
        with pytest.raises(ValidationFailed):
            life.check_move(a, b)
    reachable = {life.REQUESTED}
    frontier = [life.REQUESTED]
    while frontier:
        for nxt in life.NEXT[frontier.pop()]:
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    assert reachable | {life.CONFIRMED} >= set(life.STATUSES) - {life.REQUESTED}


def test_late_cancellation_is_inside_the_window() -> None:
    start = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    assert not life.is_late_cancellation(start, start - timedelta(hours=25), 24)
    assert not life.is_late_cancellation(start, start - timedelta(hours=24), 24)
    assert life.is_late_cancellation(start, start - timedelta(hours=23), 24)
    assert life.is_late_cancellation(start, start + timedelta(minutes=1), 0)


# --------------------------------------------------------------------------- repeating
def test_weekly_biweekly_and_monthly_dates() -> None:
    assert occurrence_dates(date(2026, 10, 19), "weekly", count=3) == [date(2026, 10, 19), date(2026, 10, 26),
                                                                      date(2026, 11, 2)]
    assert occurrence_dates(date(2026, 10, 19), "biweekly", until=date(2026, 11, 16)) == [
        date(2026, 10, 19), date(2026, 11, 2), date(2026, 11, 16)]
    assert occurrence_dates(date(2026, 1, 31), "monthly", count=4) == [date(2026, 1, 31), date(2026, 2, 28),
                                                                      date(2026, 3, 31), date(2026, 4, 30)]


def test_a_series_needs_an_end_and_has_a_limit() -> None:
    with pytest.raises(ValidationFailed):
        occurrence_dates(MONDAY, "weekly")
    with pytest.raises(ValidationFailed):
        occurrence_dates(MONDAY, "daily", count=2)
    with pytest.raises(ValidationFailed):
        occurrence_dates(MONDAY, "weekly", until=MONDAY + timedelta(days=7 * 80))
    assert len(occurrence_dates(MONDAY, "weekly", count=MAX_OCCURRENCES)) == MAX_OCCURRENCES


# --------------------------------------------------------------------------- what people type
def test_names_colours_hours() -> None:
    assert rules.check_name("  Chair   1 ") == "Chair 1"
    with pytest.raises(ValidationFailed):
        rules.check_name("   ")
    assert rules.check_colour("#1A73E8") == "#1a73e8" and rules.check_colour("") is None
    with pytest.raises(ValidationFailed):
        rules.check_colour("blue")
    assert rules.check_email(" A@B.co ") == "a@b.co"
    with pytest.raises(ValidationFailed):
        rules.check_hours([av.Hours(0, time(9), time(12)), av.Hours(0, time(11), time(13))])
    with pytest.raises(ValidationFailed):
        rules.check_hours([av.Hours(0, time(12), time(9))])
    assert rules.parse_time("09:30") == time(9, 30)

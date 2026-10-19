"""The door decision: pure rules, worked by hand."""

from datetime import date, time
from decimal import Decimal
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.memberships.domain import access as a

TODAY = date(2026, 10, 14)        # a Wednesday (weekday 2)


def facts(**kw: Any) -> a.Facts:
    base: dict[str, Any] = dict(today=TODAY, local_time=time(10, 0), weekday=2, branch_id="b1", grace_days=7)
    base.update(kw)
    return a.Facts(**base)


def membership(**kw: Any) -> a.MembershipFact:
    base: dict[str, Any] = dict(id="m1", number="MEM-1", plan_name="Monthly", status="active", start_date=date(2026, 9, 1),
                end_date=None, cancel_at=None, past_due_since=None)
    base.update(kw)
    return a.MembershipFact(**base)


def test_an_active_membership_lets_in() -> None:
    d = a.decide(facts(memberships=(membership(),)))
    assert d.outcome == a.ALLOW and d.allowed and d.entitlement and d.entitlement.holder_type == "membership"
    assert d.code == "ok"


def test_nothing_at_all_is_refused() -> None:
    d = a.decide(facts())
    assert d.outcome == a.DENY and d.code == a.NO_MEMBERSHIP and d.entitlement is None


def test_each_status_is_refused_with_its_own_reason() -> None:
    for status, code in (("paused", a.ON_HOLD), ("frozen", a.FROZEN), ("cancelled", a.ENDED), ("expired", a.ENDED)):
        d = a.decide(facts(memberships=(membership(status=status),)))
        assert d.outcome == a.DENY and d.code == code, status


def test_a_membership_that_has_not_started_or_has_ended_is_refused() -> None:
    assert a.decide(facts(memberships=(membership(start_date=date(2026, 10, 20)),))).code == a.NOT_STARTED
    assert a.decide(facts(memberships=(membership(end_date=date(2026, 10, 14)),))).code == a.ENDED
    assert a.decide(facts(memberships=(membership(cancel_at=date(2026, 10, 13)),))).code == a.ENDED
    soon = a.decide(facts(memberships=(membership(cancel_at=date(2026, 10, 20)),)))
    assert soon.outcome == a.ALLOW and any(r.code == a.CANCELLING for r in soon.reasons)


def test_late_payment_warns_inside_the_grace_days_and_refuses_after() -> None:
    inside = a.decide(facts(memberships=(membership(past_due_since=date(2026, 10, 9), arrears=Decimal("100")),)))
    assert inside.outcome == a.WARN and inside.allowed and inside.code == a.PAYMENT_LATE      # 5 days late, grace 7
    after = a.decide(facts(memberships=(membership(past_due_since=date(2026, 10, 1), arrears=Decimal("100")),)))
    assert after.outcome == a.DENY and after.code == a.PAYMENT_OVERDUE                         # 13 days late
    exact = a.decide(facts(memberships=(membership(past_due_since=date(2026, 10, 7), arrears=Decimal("100")),)))
    assert exact.outcome == a.WARN                                                           # exactly 7 days: still grace
    paid = a.decide(facts(memberships=(membership(past_due_since=date(2026, 10, 1), arrears=Decimal("0")),)))
    assert paid.outcome == a.ALLOW


def test_off_peak_windows_including_one_that_crosses_midnight() -> None:
    off_peak = ({"days": [0, 1, 2, 3, 4], "from": "10:00", "to": "16:00"},)
    m = membership(access_rules=off_peak)
    assert a.decide(facts(memberships=(m,), local_time=time(11, 0))).outcome == a.ALLOW
    d = a.decide(facts(memberships=(m,), local_time=time(17, 30)))
    assert d.outcome == a.DENY and d.code == a.OUTSIDE_HOURS and "Mon, Tue" in d.headline
    assert a.decide(facts(memberships=(m,), local_time=time(11, 0), weekday=5)).code == a.OUTSIDE_HOURS      # Saturday
    night = ({"days": [4], "from": "22:00", "to": "06:00"},)             # Friday night into Saturday morning
    assert a.window_allows(night, 4, time(23, 0)) and a.window_allows(night, 5, time(5, 59))
    assert not a.window_allows(night, 5, time(6, 0)) and not a.window_allows(night, 3, time(23, 0))
    assert a.window_allows((), 6, time(3, 0))


def test_branch_list_and_classes_only_plans() -> None:
    here = a.decide(facts(memberships=(membership(branch_ids=("b1", "b2")),)))
    assert here.outcome == a.ALLOW
    assert a.decide(facts(memberships=(membership(branch_ids=("b2",)),))).code == a.WRONG_BRANCH
    assert a.decide(facts(memberships=(membership(gym_access=False),))).code == a.CLASSES_ONLY


def test_visit_packs_pay_one_visit_and_warn_on_the_last() -> None:
    pack = a.PackageFact("p1", "10 visits", Decimal("5"), None)
    d = a.decide(facts(packages=(pack,)))
    assert d.outcome == a.ALLOW and d.entitlement == a.Entitlement("package", "p1", "10 visits", Decimal(1))
    last = a.decide(facts(packages=(a.PackageFact("p1", "10 visits", Decimal("1"), None),)))
    assert last.outcome == a.WARN and last.code == a.NO_CREDITS
    empty = a.decide(facts(packages=(a.PackageFact("p1", "10 visits", Decimal("0"), None),)))
    assert empty.outcome == a.DENY and empty.code == a.NO_CREDITS
    old = a.decide(facts(packages=(a.PackageFact("p1", "10 visits", Decimal("5"), date(2026, 10, 1)),)))
    assert old.outcome == a.DENY
    second_time_today = a.decide(facts(packages=(pack,), counted_today=True))
    assert second_time_today.entitlement and second_time_today.entitlement.consumes == 0
    other = a.decide(facts(packages=(a.PackageFact("p2", "Massage", Decimal("5"), None, pays_for_entry=False),)))
    assert other.outcome == a.DENY


def test_the_soonest_expiring_package_is_used_first() -> None:
    d = a.decide(facts(packages=(a.PackageFact("late", "A", Decimal("5"), date(2026, 12, 1)),
                                 a.PackageFact("soon", "B", Decimal("5"), date(2026, 11, 1)))))
    assert d.entitlement and d.entitlement.holder_id == "soon"


def test_a_membership_beats_a_package_and_a_clean_one_beats_a_late_one() -> None:
    late = membership(id="late", past_due_since=date(2026, 10, 10), arrears=Decimal("50"))
    clean = membership(id="clean", number="MEM-2")
    d = a.decide(facts(memberships=(late, clean), packages=(a.PackageFact("p", "Pack", Decimal("5"), None),)))
    assert d.outcome == a.ALLOW and d.entitlement and d.entitlement.holder_id == "clean"
    only_pack = a.decide(facts(memberships=(membership(status="expired"),),
                               packages=(a.PackageFact("p", "Pack", Decimal("5"), None),)))
    assert only_pack.entitlement and only_pack.entitlement.holder_type == "package" and only_pack.allowed


def test_a_blocked_member_and_a_missing_waiver_are_refused_whatever_else_is_true() -> None:
    blocked = a.decide(facts(memberships=(membership(),), blocked=True, block_reason="Fighting"))
    assert blocked.outcome == a.DENY and blocked.code == a.BLOCKED and "Fighting" in blocked.headline
    unsigned = a.decide(facts(memberships=(membership(),), waiver_required=True, waiver_accepted=False))
    assert unsigned.outcome == a.DENY and unsigned.code == a.WAIVER_MISSING and unsigned.entitlement
    assert a.decide(facts(memberships=(membership(),), waiver_required=False, waiver_accepted=False)).allowed


def test_a_fixed_term_ending_soon_warns() -> None:
    d = a.decide(facts(memberships=(membership(end_date=date(2026, 10, 18), plan_kind="pass", is_trial=True),)))
    assert d.outcome == a.WARN and {r.code for r in d.reasons} >= {a.EXPIRING, a.TRIAL}


@given(status=st.sampled_from(["active", "paused", "frozen", "cancelled", "expired"]),
       late=st.integers(min_value=-5, max_value=40), grace=st.integers(min_value=0, max_value=30),
       weekday=st.integers(min_value=0, max_value=6), hour=st.integers(min_value=0, max_value=23))
def test_a_decision_is_always_consistent(status: str, late: int, grace: int, weekday: int, hour: int) -> None:
    since = date.fromordinal(TODAY.toordinal() - late) if late > -5 else None
    m = membership(status=status, past_due_since=since, arrears=Decimal("10") if since else Decimal(0),
                   access_rules=({"days": [0, 1, 2], "from": "06:00", "to": "12:00"},))
    d = a.decide(facts(memberships=(m,), grace_days=grace, weekday=weekday, local_time=time(hour, 0)))
    assert d.outcome in (a.ALLOW, a.WARN, a.DENY)
    assert d.allowed == (d.outcome != a.DENY)
    assert d.allowed == bool(d.entitlement) or d.outcome == a.DENY
    if d.outcome == a.DENY:
        assert any(r.level == a.DENY for r in d.reasons)
    if status != "active":
        assert d.outcome == a.DENY

"""Which credits pay for a service, with the numbers worked out by hand."""

from datetime import date
from decimal import Decimal as D  # noqa: N817

from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.memberships.domain import credits
from ziira.modules.memberships.domain.credits import Holder, allocate
from ziira.modules.memberships.domain.quiet import is_quiet


def test_the_membership_is_used_first_then_the_package_that_expires_soonest() -> None:
    holders = [Holder("later", "package", D(10), expires_on=date(2027, 1, 1)),
               Holder("sooner", "package", D(10), expires_on=date(2026, 12, 1)),
               Holder("plan", "membership", D(3))]
    takes, left = allocate(holders, D(14), None)
    assert [(t.holder_id, t.quantity) for t in takes] == [("plan", D(3)), ("sooner", D(10)), ("later", D(1))]
    assert left == 0


def test_what_the_credits_cannot_cover_is_left_to_pay() -> None:
    takes, left = allocate([Holder("plan", "membership", D(2))], D(5), None)
    assert [(t.holder_id, t.quantity) for t in takes] == [("plan", D(2))] and left == 3


def test_a_holder_pays_only_for_the_services_it_covers() -> None:
    holders = [Holder("massage", "package", D(5), covers=("massage",)), Holder("any", "package", D(5))]
    takes, left = allocate(holders, D(2), "facial")
    assert [t.holder_id for t in takes] == ["any"] and left == 0
    takes, left = allocate(holders, D(2), "massage")
    assert [(t.holder_id, t.quantity) for t in takes] == [("any", D(2))]      # equal in order: the first id
    only, left = allocate([Holder("massage", "package", D(5), covers=("massage",))], D(2), None)
    assert only == [] and left == 2                     # no service named: a restricted package does not apply


def test_an_empty_or_negative_balance_pays_nothing() -> None:
    takes, left = allocate([Holder("a", "membership", D(0)), Holder("b", "package", D(-1))], D(2), None)
    assert takes == [] and left == 2


def test_overdraw_takes_the_rest_from_the_first_holder() -> None:
    holders = [Holder("plan", "membership", D(1)), Holder("pack", "package", D(0))]
    takes, left = allocate(holders, D(3), None, overdraw=True)
    assert [(t.holder_id, t.quantity) for t in takes] == [("plan", D(3))] and left == 0
    takes, left = allocate([Holder("pack", "package", D(0))], D(2), None, overdraw=True)
    assert [(t.holder_id, t.quantity) for t in takes] == [("pack", D(2))] and left == 0
    assert allocate([], D(2), None, overdraw=True) == ([], D(2))


quantities = st.decimals(min_value=D("0.01"), max_value=D(50), places=2)


@given(balances=st.lists(st.decimals(min_value=D(-5), max_value=D(30), places=2), max_size=5), want=quantities,
       overdraw=st.booleans())
def test_the_takes_and_what_is_left_always_add_up_to_the_request(balances, want, overdraw) -> None:  # type: ignore[no-untyped-def]
    holders = [Holder(str(i), credits.MEMBERSHIP if i % 2 == 0 else credits.PACKAGE, b) for i, b in enumerate(balances)]
    takes, left = allocate(holders, want, None, overdraw=overdraw)
    assert sum((t.quantity for t in takes), D(0)) + left == want
    assert left >= 0 and all(t.quantity > 0 for t in takes)
    if not overdraw:
        by_id = {h.id: h.balance for h in holders}
        assert all(t.quantity <= by_id[t.holder_id] for t in takes)             # nobody goes below zero
    elif holders:
        assert left == 0


def test_quiet_hours_may_cross_midnight() -> None:
    assert is_quiet(22, 21, 7) and is_quiet(3, 21, 7) and not is_quiet(7, 21, 7) and not is_quiet(12, 21, 7)
    assert is_quiet(13, 12, 14) and not is_quiet(14, 12, 14)
    assert not is_quiet(5, 8, 8)                                       # same hour: no quiet hours

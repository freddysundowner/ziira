"""Unit tests for Finance's pure rules: entries, periods, the chart template, recipes and posting rules."""

from datetime import date
from decimal import Decimal
from itertools import pairwise
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.finance.domain import chart, entries, periods, recipes, rules
from ziira.modules.finance.domain.entries import Line
from ziira.sdk import ValidationFailed

D = Decimal
A, B, C = uuid4(), uuid4(), uuid4()


# --------------------------------------------------------------------------- entries
def test_a_balanced_entry() -> None:
    assert entries.check_lines([Line(A, debit=D("10.50")), Line(B, credit=D("10.50"))]) == (D("10.50"), D("10.50"))
    entries.check_lines([Line(A, debit=D("10")), Line(B, credit=D("4")), Line(C, credit=D("6"))])


@pytest.mark.parametrize("lines", [
    [],
    [Line(A, debit=D("1"))],
    [Line(A, debit=D("1")), Line(B, credit=D("2"))],                                  # does not balance
    [Line(A, debit=D("1"), credit=D("1")), Line(B, credit=D("0"))],                    # both sides on one line
    [Line(A), Line(B, credit=D("1"))],                                                  # an empty line
    [Line(A, debit=D("-1")), Line(B, credit=D("-1"))],                                  # negative
    [Line(A, debit=D("1.005")), Line(B, credit=D("1.005"))],                            # fractions of a cent
    [Line(A, debit=D("NaN")), Line(B, credit=D("1"))],
    [Line(A, debit=D("Infinity")), Line(B, credit=D("Infinity"))],
    [Line(A, debit=D("1E+20")), Line(B, credit=D("1E+20"))],                            # too large to store
])
def test_bad_entries_are_refused(lines: list[Line]) -> None:
    with pytest.raises(ValidationFailed):
        entries.check_lines(lines)


def test_the_largest_amount_that_fits() -> None:
    entries.check_lines([Line(A, debit=entries.MAX_AMOUNT), Line(B, credit=entries.MAX_AMOUNT)])
    with pytest.raises(ValidationFailed, match="too large"):
        entries.check_amount(entries.MAX_AMOUNT + D("0.01"))


def test_reversal_swaps_the_sides_and_keeps_the_rest() -> None:
    branch, party = uuid4(), uuid4()
    original = [Line(A, debit=D("5"), branch_id=branch, party_type="customer", party_id=party, description="x"),
                Line(B, credit=D("5"))]
    mirrored = entries.mirror(original)
    assert [(x.debit, x.credit) for x in mirrored] == [(0, D("5")), (D("5"), 0)]
    assert mirrored[0].branch_id == branch and mirrored[0].party_id == party and mirrored[0].description == "x"
    assert entries.check_lines(mirrored) == (D("5"), D("5"))


@pytest.mark.parametrize(("kind", "debit", "credit", "balance"), [
    ("asset", "100", "30", "70"), ("expense", "100", "30", "70"), ("liability", "30", "100", "70"),
    ("equity", "0", "50", "50"), ("income", "10", "60", "50"), ("asset", "0", "20", "-20")])
def test_natural_balance(kind: str, debit: str, credit: str, balance: str) -> None:
    assert entries.natural_balance(kind, D(debit), D(credit)) == D(balance)


@given(st.lists(st.decimals(min_value=D("0.01"), max_value=D("100000"), places=2), min_size=1, max_size=8))
@settings(max_examples=200, deadline=None)
def test_any_split_of_an_amount_balances_and_its_mirror_does_too(parts: list[Decimal]) -> None:
    total = sum(parts, D(0))
    lines = [Line(A, debit=total)] + [Line(uuid4(), credit=p) for p in parts]
    assert entries.check_lines(lines) == (total, total)
    mirrored = entries.mirror(lines)
    assert entries.check_lines(mirrored) == (total, total)
    # the two together cancel on every account
    net: dict[UUID, Decimal] = {}
    for line in lines + mirrored:
        net[line.account_id] = net.get(line.account_id, D(0)) + line.debit - line.credit
    assert all(v == 0 for v in net.values())


# --------------------------------------------------------------------------- periods
def test_month_bounds() -> None:
    assert periods.month_bounds(date(2026, 10, 13)) == (date(2026, 10, 1), date(2026, 10, 31))
    assert periods.month_bounds(date(2028, 2, 29)) == (date(2028, 2, 1), date(2028, 2, 29))      # leap year
    assert periods.month_bounds(date(2027, 2, 1)) == (date(2027, 2, 1), date(2027, 2, 28))
    assert periods.month_bounds(date(2026, 12, 31)) == (date(2026, 12, 1), date(2026, 12, 31))


@pytest.mark.parametrize(("status", "automatic", "can_close", "policy", "expected"), [
    ("open", True, False, "reject", "post"), ("open", False, False, "reject", "post"),
    ("soft_closed", False, True, "reject", "post"),             # a person who may close periods can still post
    ("soft_closed", True, True, "redirect", "redirect"),        # a sale into a closed month follows the policy
    ("locked", True, False, "redirect", "redirect"),
])
def test_where_an_entry_goes(status: str, automatic: bool, can_close: bool, policy: str, expected: str) -> None:
    assert periods.decide(status, automatic=automatic, can_close=can_close, policy=policy) == expected


@pytest.mark.parametrize(("status", "automatic", "can_close", "policy", "message"), [
    ("soft_closed", False, False, "reject", "may post into it"),
    ("soft_closed", False, False, "redirect", "may post into it"),       # manual entries are never redirected
    ("soft_closed", True, False, "reject", "closed"),
    ("locked", False, True, "reject", "locked"),                         # not even with the close permission
    ("locked", True, True, "reject", "locked"),
])
def test_entries_that_are_refused(status: str, automatic: bool, can_close: bool, policy: str, message: str) -> None:
    with pytest.raises(ValidationFailed, match=message):
        periods.decide(status, automatic=automatic, can_close=can_close, policy=policy)


def test_closing_and_reopening() -> None:
    periods.check_status_change("open", "soft_closed", can_close=True)
    periods.check_status_change("soft_closed", "locked", can_close=True)
    periods.check_status_change("soft_closed", "open", can_close=True)
    for current, new, message in (("open", "locked", "cannot go"), ("locked", "open", "cannot be reopened"),
                                  ("locked", "soft_closed", "cannot be reopened"), ("open", "open", "already"),
                                  ("open", "weird", "Status must be")):
        with pytest.raises(ValidationFailed, match=message):
            periods.check_status_change(current, new, can_close=True)
    with pytest.raises(ValidationFailed, match="period.close"):
        periods.check_status_change("open", "soft_closed", can_close=False)


# --------------------------------------------------------------------------- the chart template
def test_the_template_is_consistent() -> None:
    codes = [a.code for a in chart.CHART]
    assert len(codes) == len(set(codes))                                     # codes are unique
    assert all(a.type in entries.ACCOUNT_TYPES for a in chart.CHART)
    assert codes == sorted(codes)
    subtypes = [a.subtype for a in chart.CHART if a.subtype]
    assert len(subtypes) == len(set(subtypes))
    control = {a.code for a in chart.CHART if a.is_control}
    assert {"1100", "1200", "1210", "2000", "2900", "1030", "2100"} <= control


def test_every_default_rule_points_at_a_template_account_with_a_sensible_side() -> None:
    by_code = {a.code: a for a in chart.CHART}
    for doc_type, role, code, side in chart.DEFAULT_RULES:
        assert code in by_code, (doc_type, role)
        assert side in ("debit", "credit")
    keys = [(d, r) for d, r, _, _ in chart.DEFAULT_RULES]
    assert len(keys) == len(set(keys))
    # every role a recipe can ask for has a default rule
    asked = set()
    for movement in ("receipt", "opening", "sale", "sale_return", "purchase_return", "adjustment",
                     "count_variance", "write_off", "transfer_in", "transfer_out"):
        for value in (D("5"), D("-5")):
            for kind in ("store", "transit"):
                asked |= {("stock_movement", x.role) for x in recipes.stock_movement(movement, value, kind)}
    for lines, doc in ((recipes.sale(D("100"), D("16"), [("cash", D("50")), ("mobile_money", D("30")), ("card", D("10")),
                                                         ("credit", D("20")), ("voucher", D("6"))]), "sale"),
                       (recipes.sale_return(D("100"), D("16"), [("cash", D("116"))]), "sale_return")):
        asked |= {(doc, x.role) for x in lines}
    assert asked <= set(keys), asked - set(keys)


# --------------------------------------------------------------------------- recipes
def shape(lines: list[recipes.RecipeLine]) -> list[tuple[str, str, Decimal]]:
    return [(x.role, x.side, x.amount) for x in lines]


@pytest.mark.parametrize(("movement", "value", "expected"), [
    ("receipt", "100", [("inventory", "debit", "100"), ("grni", "credit", "100")]),
    ("opening", "100", [("inventory", "debit", "100"), ("opening_equity", "credit", "100")]),
    ("sale", "-40", [("inventory", "credit", "40"), ("cogs", "debit", "40")]),
    ("sale_return", "40", [("inventory", "debit", "40"), ("cogs", "credit", "40")]),
    ("purchase_return", "-7", [("inventory", "credit", "7"), ("grni", "debit", "7")]),
    ("write_off", "-3", [("inventory", "credit", "3"), ("shrinkage", "debit", "3")]),
    ("adjustment", "-3", [("inventory", "credit", "3"), ("shrinkage", "debit", "3")]),
    ("adjustment", "3", [("inventory", "debit", "3"), ("shrinkage", "credit", "3")]),
    ("count_variance", "-2", [("inventory", "credit", "2"), ("shrinkage", "debit", "2")]),
    ("count_variance", "2", [("inventory", "debit", "2"), ("shrinkage", "credit", "2")]),
    ("transfer_out", "-9", [("inventory", "credit", "9"), ("transfer_clearing", "debit", "9")]),
    ("transfer_in", "9", [("inventory", "debit", "9"), ("transfer_clearing", "credit", "9")]),
])
def test_stock_movement_recipes(movement: str, value: str, expected: list[tuple[str, str, str]]) -> None:
    assert shape(recipes.stock_movement(movement, D(value), "store")) == [(r, s, D(a)) for r, s, a in expected]


def test_the_in_transit_location_uses_its_own_inventory_role() -> None:
    lines = recipes.stock_movement("transfer_in", D("9"), "transit")
    assert [x.role for x in lines] == ["inventory_in_transit", "transfer_clearing"]


def test_worthless_movements_post_nothing_and_unknown_types_are_refused() -> None:
    assert recipes.stock_movement("receipt", D("0"), "store") == []
    assert recipes.stock_movement("sale", D("-0.004"), "store") == []                # rounds to nothing
    with pytest.raises(ValidationFailed, match="No posting recipe"):
        recipes.stock_movement("teleport", D("5"), "store")


def test_a_dated_transfer_pair_nets_to_zero_on_the_clearing_account() -> None:
    out = recipes.stock_movement("transfer_out", D("-50"), "store")
    into = recipes.stock_movement("transfer_in", D("50"), "transit")
    clearing = [x for x in out + into if x.role == "transfer_clearing"]
    assert sum((x.amount if x.side == "debit" else -x.amount for x in clearing), D(0)) == 0


def test_a_cash_sale() -> None:
    lines = recipes.sale(D("100"), D("16"), [("cash", D("116"))])
    assert shape(lines) == [("cash", "debit", D("116")), ("sales", "credit", D("100")),
                            ("vat_output", "credit", D("16"))]


def test_a_sale_paid_several_ways_and_partly_on_credit() -> None:
    customer = uuid4()
    lines = recipes.sale(D("200"), D("32"), [("cash", D("100")), ("mobile_money", D("82")), ("credit", D("50"))],
                         party=customer)
    assert [(x.role, x.amount) for x in lines[:3]] == [("cash", D("100")), ("mobile_money", D("82")), ("credit", D("50"))]
    credit = lines[2]
    assert credit.party_type == "customer" and credit.party_id == customer
    assert lines[0].party_id is None
    debits = sum(x.amount for x in lines if x.side == "debit")
    credits = sum(x.amount for x in lines if x.side == "credit")
    assert debits == credits == D("232")


def test_unknown_payment_methods_go_to_other_and_zero_vat_is_left_out() -> None:
    lines = recipes.sale(D("50"), D("0"), [("voucher", D("50"))])
    assert [x.role for x in lines] == ["other", "sales"]


@pytest.mark.parametrize(("net", "tax", "money", "message"), [
    ("100", "16", [("cash", "100")], "add up to 100"),                       # underpaid
    ("100", "16", [("cash", "200")], "add up to 200"),
    ("100", "16", [("cash", "-116"), ("cash", "232")], "positive"),
    ("-1", "0", [("cash", "-1")], "negative"),
])
def test_sales_must_be_paid_for_exactly(net: str, tax: str, money: list[tuple[str, str]], message: str) -> None:
    with pytest.raises(ValidationFailed, match=message):
        recipes.sale(D(net), D(tax), [(m, D(a)) for m, a in money])


def test_a_free_sale_posts_nothing() -> None:
    assert recipes.sale(D("0"), D("0"), []) == []


def test_a_return_is_the_sale_the_other_way_round() -> None:
    sale = recipes.sale(D("100"), D("16"), [("mobile_money", D("116"))])
    back = recipes.sale_return(D("100"), D("16"), [("mobile_money", D("116"))])
    assert shape(back) == [("mobile_money", "credit", D("116")), ("sales_returns", "debit", D("100")),
                           ("vat_output", "debit", D("16"))]
    assert {x.amount for x in sale} == {x.amount for x in back}


@given(st.decimals(min_value=D("0"), max_value=D("1000000"), places=2),
       st.decimals(min_value=D("0"), max_value=D("160000"), places=2),
       st.integers(1, 4))
@settings(max_examples=200, deadline=None)
def test_every_sale_recipe_balances(net: Decimal, tax: Decimal, parts: int) -> None:
    total = net + tax
    if total == 0:
        return
    share = (total / parts).quantize(D("0.01"))
    money = [("cash", share)] * (parts - 1) + [("mobile_money", total - share * (parts - 1))]
    if any(amount <= 0 for _, amount in money):
        return
    for lines in (recipes.sale(net, tax, money), recipes.sale_return(net, tax, money)):
        debits = sum(x.amount for x in lines if x.side == "debit")
        credits = sum(x.amount for x in lines if x.side == "credit")
        assert debits == credits == total


# --------------------------------------------------------------------------- posting rules
def rule(role: str, conditions: dict | None = None, priority: int = 100, doc: str = "stock_movement"):  # type: ignore[no-untyped-def,type-arg]
    return rules.PostingRule(doc, role, uuid4(), conditions or {}, priority)


def test_the_most_specific_rule_wins_then_priority() -> None:
    plain, specific, urgent = rule("shrinkage"), rule("shrinkage", {"movement_type": "write_off"}), \
        rule("shrinkage", {"movement_type": "write_off"}, priority=10)
    pool = [plain, specific, urgent]
    pick = rules.resolve_account
    assert pick(pool, "stock_movement", "shrinkage", {"movement_type": "adjustment"}) == plain.account_id
    assert pick(pool, "stock_movement", "shrinkage", {"movement_type": "write_off"}) == urgent.account_id
    assert rules.resolve_account([plain, specific], "stock_movement", "shrinkage",
                                 {"movement_type": "write_off"}) == specific.account_id


def test_conditions_must_all_match_and_missing_rules_are_named() -> None:
    both = rule("cogs", {"movement_type": "sale", "branch": "THK"})
    fallback = rule("cogs")
    ctx = {"movement_type": "sale", "branch": "JUJA"}
    assert rules.resolve_account([both, fallback], "stock_movement", "cogs", ctx) == fallback.account_id
    with pytest.raises(ValidationFailed, match="No posting rule for 'cogs' on 'stock_movement'"):
        rules.resolve_account([both], "stock_movement", "cogs", ctx)
    with pytest.raises(ValidationFailed):
        rules.resolve_account([fallback], "sale", "cogs", {})                 # another document type
    with pytest.raises(ValidationFailed):
        rules.resolve_account([], "stock_movement", "cogs", {})


def test_the_template_chain_is_ordered() -> None:
    assert all(a < b for a, b in pairwise(a.code for a in chart.CHART))

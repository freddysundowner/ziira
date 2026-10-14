"""Payroll golden cases: every figure below was worked out by hand from the rules, not by running the code.

The rules are written out in this file as a business would define them (the numbers are the test's own; they say nothing
about any country's law). The cases prove the arithmetic and the ordering; a business's accountant checks its own rules.
"""

from datetime import date
from decimal import Decimal as D  # noqa: N817
from typing import Any
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.people.domain import payroll as p
from ziira.modules.people.domain import rules as r
from ziira.sdk import ValidationFailed

PENSION = {"name": "Pension", "kind": "contribution", "order": 10, "base": "gross", "reduces_taxable": True,
           "employee": {"method": "rate", "rate": "0.06", "base_maximum": "72000"},
           "employer": {"method": "rate", "rate": "0.06", "base_maximum": "72000"}}
HOUSING = {"name": "Housing levy", "kind": "levy", "order": 15, "base": "gross", "reduces_taxable": True,
           "employee": {"method": "rate", "rate": "0.015"}, "employer": {"method": "rate", "rate": "0.015"}}
HEALTH = {"name": "Health cover", "kind": "contribution", "order": 20, "base": "gross", "reduces_taxable": True,
          "employee": {"method": "rate", "rate": "0.0275", "minimum": "300"}}
TAX = {"name": "Income tax", "kind": "tax", "order": 30, "base": "taxable", "applies_to": "resident",
       "employee": {"method": "bands", "credit": "2400", "bands": [
           {"up_to": "24000", "rate": "0.10"}, {"up_to": "32333", "rate": "0.25"}, {"up_to": "500000", "rate": "0.30"},
           {"up_to": "800000", "rate": "0.325"}, {"up_to": None, "rate": "0.35"}]}}
FOREIGN_TAX = {"name": "Income tax (non-resident)", "kind": "tax", "order": 30, "base": "taxable",
               "applies_to": "non_resident", "employee": {"method": "rate", "rate": "0.30"}}


def active(*definitions: tuple[str, dict[str, Any]]) -> list[r.ActiveRule]:
    rows = [r.RuleRow(uuid4(), code, date(2020, 1, 1), None, d, True) for code, d in definitions]
    return r.in_force(rows, date(2026, 6, 30))


RULES = active(("PENSION", PENSION), ("HOUSING", HOUSING), ("HEALTH", HEALTH), ("TAX", TAX),
               ("TAX_NR", FOREIGN_TAX))


def pay(basic: str, rules: list[r.ActiveRule] | None = None, **kw) -> p.PayResult:  # type: ignore[no-untyped-def]
    return p.calculate(p.PayInput(basic=D(basic), **kw), RULES if rules is None else rules)


def amount(x: p.PayResult, code: str) -> D:
    found = x.rule(code)
    return found.employee if found else D(-1)


def figures(x: p.PayResult) -> tuple[D, ...]:
    return amount(x, "PENSION"), amount(x, "HEALTH"), amount(x, "HOUSING"), x.taxable_pay, amount(x, "TAX"), x.net_pay


# --------------------------------------------------------------------------- golden cases
def test_a_middle_salary() -> None:
    # pension 6% of 50000 = 3000; health 2.75% = 1375; housing 1.5% = 750; taxable 50000-5125 = 44875
    # tax 2400 + 8333*.25 (2083.25) + 12542*.30 (3762.60) = 8245.85; less credit 2400 = 5845.85
    x = pay("50000")
    assert figures(x) == (D("3000.00"), D("1375.00"), D("750.00"), D("44875.00"), D("5845.85"), D("39029.15"))
    tax = x.rule("TAX")
    assert tax and tax.before_credit == D("8245.85") and tax.credit == D("2400") and tax.base == D("44875.00")
    assert x.total_deductions == D("10970.85") and x.employer_statutory == x.employer_cost == D("3750.00")
    assert x.gross_cash == x.gross_pay == D("50000") and x.rule("TAX_NR") is None       # not for residents


def test_a_low_salary_pays_no_tax_because_of_the_credit() -> None:
    # pension 480 + 720 = 1200; health 550; housing 300; taxable 17950; tax 1795 is less than the credit
    x = pay("20000")
    assert figures(x) == (D("1200.00"), D("550.00"), D("300.00"), D("17950.00"), D("0.00"), D("17950.00"))
    tax = x.rule("TAX")
    assert tax and tax.before_credit == D("1795.00") and tax.credit == D("1795.00")      # only what was needed


def test_the_minimum_applies_to_very_low_pay() -> None:
    # pension 6% of 6000 = 360; health 165, so the minimum 300; housing 90
    x = pay("6000")
    assert figures(x) == (D("360.00"), D("300.00"), D("90.00"), D("5250.00"), D("0.00"), D("5250.00"))


def test_a_high_salary_hits_the_base_cap_and_the_30_percent_band() -> None:
    # pension capped at 72000 * 6% = 4320; health 5500; housing 3000; taxable 187180
    # tax 2400 + 2083.25 + 154847*.30 (46454.10) = 50937.35; less 2400 = 48537.35
    x = pay("200000")
    assert figures(x) == (D("4320.00"), D("5500.00"), D("3000.00"), D("187180.00"), D("48537.35"), D("138642.65"))
    assert x.employer_cost == D("7320.00")


def test_a_very_high_salary_reaches_the_top_band() -> None:
    # taxable 1000000 - (4320 + 27500 + 15000) = 953180; tax 2400 + 2083.25 + 140300.10 + 97500 + 153180*.35 (53613)
    x = pay("1000000")
    tax = x.rule("TAX")
    assert x.taxable_pay == D("953180.00") and tax and tax.before_credit == D("295896.35")
    assert tax.employee == D("293496.35") and x.net_pay == D("659683.65")


def test_allowances_benefits_deductions_and_employer_items() -> None:
    x = pay("40000",
            earnings=(p.Item("HOUSE", "House allowance", D("10000")), p.Item("TRAVEL", "Travel refund", D("3000"), False)),
            benefits=(p.Item("CAR", "Company car", D("5000")),),
            deductions=(p.Item("LOAN", "Staff loan", D("2000")),),
            employer_items=(p.Item("PENS2", "Employer top-up", D("1000")),))
    # cash 53000, of which 3000 is a refund; the base is 50000: pension 3000, health 1375, housing 750
    # taxable 50000 + 5000 (car) - 5125 = 49875; tax 2400 + 2083.25 + 17542*.30 (5262.60) = 9745.85; less 2400 = 7345.85
    assert x.gross_cash == D("53000.00") and x.statutory_base == D("50000.00") and x.benefits == D("5000.00")
    assert x.gross_pay == D("58000.00") and x.taxable_pay == D("49875.00") and amount(x, "TAX") == D("7345.85")
    assert x.total_deductions == D("14470.85") and x.net_pay == D("38529.15")           # the car is not paid out
    assert x.employer_cost == D("4750.00")                                              # 3000 + 750 + 1000


def test_unpaid_leave_reduces_pay_before_everything_else() -> None:
    leave = p.unpaid_leave_amount(D("60000"), D("3"), 30)                                # 60000 / 30 * 3
    assert leave == D("6000.00")
    # pay 54000: pension 3240, health 1485, housing 810; taxable 48465; tax 2400 + 2083.25 + 16132*.30 = 9322.85 - 2400
    x = pay("60000", unpaid_leave=leave)
    assert x.gross_cash == D("54000.00") and amount(x, "TAX") == D("6922.85") and x.net_pay == D("41542.15")
    assert [ln.amount for ln in x.lines if ln.code == "UNPAID_LEAVE"] == [D("-6000.00")]


def test_a_rule_for_non_residents_replaces_the_resident_one() -> None:
    x = pay("50000", resident=False)                                                     # 44875 * 30%, no credit
    assert x.rule("TAX") is None and amount(x, "TAX_NR") == D("13462.50")
    assert x.net_pay == D("50000") - D("3000") - D("1375") - D("750") - D("13462.50")


def test_nothing_to_pay_and_no_rules_at_all() -> None:
    zero = pay("0")
    assert (zero.gross_cash, zero.net_pay, zero.employer_cost, zero.statutory_employee) == (D(0),) * 4
    bare = pay("50000", rules=[])
    assert bare.net_pay == D("50000") and bare.rules == [] and bare.taxable_pay == D("50000")   # a country with no rules


def test_deductions_larger_than_the_pay_leave_a_negative_net_for_review() -> None:
    assert pay("10000", deductions=(p.Item("ADV", "Advance", D("20000")),)).net_pay < 0


def test_the_lines_of_a_payslip_add_up() -> None:
    x = pay("50000", earnings=(p.Item("HOUSE", "House", D("5000")),), deductions=(p.Item("SACCO", "Sacco", D("1000")),))
    earnings = sum(ln.amount for ln in x.lines if ln.kind == "earning")
    deductions = sum(ln.amount for ln in x.lines if ln.kind == "deduction")
    assert earnings == x.gross_cash and deductions == x.total_deductions and earnings - deductions == x.net_pay
    assert {ln.code for ln in x.lines if ln.table_id} == {"PENSION", "HOUSING", "HEALTH", "TAX", "PENSION_ER",
                                                          "HOUSING_ER"}


def test_overtime_and_proration() -> None:
    assert p.overtime_pay(D("45000"), D("10"), D("1.5"), D("225")) == D("3000.00")
    assert p.prorate(D("62000"), 21, 31) == D("42000.00")                                # joined on the 11th
    assert p.prorate(D("62000"), 31, 31) == D("62000") and p.prorate(D("62000"), 40, 31) == D("62000")
    assert p.prorate(D("62000"), -3, 31) == D("0.00")
    assert p.unpaid_leave_amount(D("1000"), D("40"), 30) == D("1000")                    # never more than the basic


# --------------------------------------------------------------------------- what a business can define
def test_a_fixed_amount_a_threshold_and_a_basic_pay_base() -> None:
    levy = {"name": "Training levy", "kind": "levy", "order": 1, "employer": {"method": "fixed", "amount": "50"}}
    threshold = {"name": "Surcharge", "order": 2, "base": "basic",
                 "employee": {"method": "rate", "rate": "0.01", "base_minimum": "30000", "maximum": "400"}}
    rules = active(("TRAIN", levy), ("SURCH", threshold))
    rich = pay("60000", rules=rules, earnings=(p.Item("BONUS", "Bonus", D("20000")),))
    assert amount(rich, "SURCH") == D("400.00")                                         # 1% of basic 600, capped at 400
    train = rich.rule("TRAIN")
    assert train and train.employer == D("50.00") and train.employee == D(0) and rich.employer_cost == D("50.00")
    assert amount(pay("29999", rules=rules), "SURCH") == D(0)                            # under the threshold
    assert pay("0", rules=rules).rule("TRAIN").employer == D(0)                          # type: ignore[union-attr]
    assert [ln.code for ln in rich.lines if ln.kind == "employer_contribution"] == ["TRAIN_ER"]


def test_a_rule_that_does_not_reduce_taxable_pay_leaves_it_alone() -> None:
    insurance = {**HEALTH, "reduces_taxable": False}
    x = pay("50000", rules=active(("HEALTH", insurance), ("TAX", TAX)))
    assert x.taxable_pay == D("50000") and amount(x, "HEALTH") == D("1375.00")


def test_order_decides_which_rules_reduce_the_base_of_a_taxable_rule() -> None:
    late_pension = {**PENSION, "order": 40}                                               # after the tax: too late
    x = pay("50000", rules=active(("PENSION", late_pension), ("TAX", TAX)))
    tax = x.rule("TAX")
    assert tax and tax.base == D("50000") and x.taxable_pay == D("47000.00")             # tax saw nothing deducted yet


def test_an_exempt_employee_skips_the_rule() -> None:
    x = pay("50000", exempt=frozenset({"PENSION"}))
    assert x.rule("PENSION") is None and x.taxable_pay == D("47875.00") and x.employer_cost == D("750.00")


def test_a_deduction_is_limited_to_the_pay_available_and_flagged() -> None:
    heavy = {"name": "Heavy", "order": 1, "employee": {"method": "fixed", "amount": "800"}}
    x = pay("500", rules=active(("HEAVY", heavy)))
    heavy_result = x.rule("HEAVY")
    assert heavy_result and heavy_result.employee == D("500.00") and heavy_result.capped and x.net_pay == D(0)


def test_the_rule_in_force_is_the_latest_one_that_has_started_and_not_ended() -> None:
    def row(code: str, start: date, end: date | None, rate: str) -> r.RuleRow:
        return r.RuleRow(uuid4(), code, start, end, {**HEALTH, "employee": {"method": "rate", "rate": rate}}, False)

    old, new = row("H", date(2025, 1, 1), date(2025, 12, 31), "0.02"), row("H", date(2026, 1, 1), None, "0.03")
    other = row("X", date(2027, 1, 1), None, "0.01")
    assert [a.row for a in r.in_force([old, new, other], date(2025, 12, 31))] == [old]
    assert [a.row for a in r.in_force([old, new, other], date(2026, 1, 1))] == [new]
    assert r.in_force([old, new, other], date(2024, 12, 31)) == []
    with pytest.raises(ValidationFailed):
        r.check_new([old, new], "H", date(2026, 1, 1), None)
    with pytest.raises(ValidationFailed):
        r.check_new([old, new], "H", date(2027, 1, 1), date(2026, 1, 1))
    r.check_new([old, new], "H", date(2027, 1, 1), None)


@pytest.mark.parametrize("definition", [
    [], {}, {"name": "x"}, {"name": "x", "employee": {"method": "magic"}}, {"name": "x", "employee": {"method": "rate"}},
    {"name": "x", "employee": {"method": "rate", "rate": "1.5"}}, {"name": "x", "employee": {"method": "rate", "rate": "-1"}},
    {"name": "x", "employee": {"method": "rate", "rate": "0.1", "base_minimum": "9", "base_maximum": "1"}},
    {"name": "x", "employee": {"method": "rate", "rate": "0.1", "minimum": "9", "maximum": "1"}},
    {"name": "x", "employee": {"method": "fixed", "amount": "abc"}}, {"name": "x", "employee": {"method": "bands"}},
    {"name": "x", "employee": {"method": "bands", "bands": [{"up_to": "5", "rate": "0.1"}]}},
    {"name": "x", "employee": {"method": "bands", "bands": [{"up_to": None, "rate": "0.1"}, {"up_to": None, "rate": "0.2"}]}},
    {"name": "x", "employee": {"method": "bands", "bands": [{"up_to": "9", "rate": "0.1"}, {"up_to": "4", "rate": "0.2"},
                                                            {"up_to": None, "rate": "0.3"}]}},
    {"name": "x", "base": "net", "employee": {"method": "fixed", "amount": "1"}},
    {"name": "x", "applies_to": "aliens", "employee": {"method": "fixed", "amount": "1"}},
    {"name": "x", "kind": "bribe", "employee": {"method": "fixed", "amount": "1"}},
    {"name": "x", "order": -1, "employee": {"method": "fixed", "amount": "1"}},
    {"name": "x", "order": True, "employee": {"method": "fixed", "amount": "1"}},
    {"name": "x", "reduces_taxable": True, "employer": {"method": "fixed", "amount": "1"}},
    {"name": "x", "reduces_taxable": True, "base": "taxable", "employee": {"method": "fixed", "amount": "1"}},
    {"name": "x", "reduces_taxable": "yes", "employee": {"method": "fixed", "amount": "1"}},
    {"name": " ", "employee": {"method": "fixed", "amount": "1"}},
])
def test_bad_definitions_are_refused(definition) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed):
        r.parse_rule("X", definition)


# --------------------------------------------------------------------------- properties
money = st.decimals(min_value=0, max_value=2_000_000, places=2)


@given(money)
def test_pay_never_goes_wrong_for_any_basic(basic: D) -> None:
    x = pay(str(basic))
    assert x.taxable_pay >= 0 and all(res.employee >= 0 and res.employer >= 0 for res in x.rules)
    assert x.net_pay == x.gross_cash - x.total_deductions and x.net_pay >= 0
    assert x.total_deductions == x.statutory_employee == sum((res.employee for res in x.rules), D(0))
    tax = x.rule("TAX")
    assert tax is None or tax.employee <= tax.before_credit


@given(money, st.decimals(min_value=0, max_value=1000, places=2))
def test_more_basic_never_means_less_net_pay(basic: D, extra: D) -> None:
    assert pay(str(basic + extra)).net_pay >= pay(str(basic)).net_pay


@given(st.lists(st.tuples(st.integers(1, 100000), st.decimals(min_value=0, max_value=1, places=2)), min_size=1,
                max_size=6), st.integers(0, 150000))
def test_tax_by_bands_matches_a_slow_calculation(pairs, taxable) -> None:  # type: ignore[no-untyped-def]
    limits = sorted({lim for lim, _ in pairs})
    bands = tuple(r.Band(D(lim), rate) for lim, (_, rate) in zip(limits, pairs, strict=False)) + (r.Band(None, D("0.4")),)
    method = r.Method("bands", bands=bands)
    expected, floor = D(0), D(0)
    for band in bands:
        top = band.up_to if band.up_to is not None else D(taxable)
        if D(taxable) > floor:
            expected += (min(top, D(taxable)) - floor) * band.rate
        floor = top
    assert r.apply_method(method, D(taxable))[0] == r.money(expected)

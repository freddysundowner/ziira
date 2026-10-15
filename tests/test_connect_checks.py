"""The standalone checks, run through the real Intelligence engine on records planted the way a connector stores them.

Every check has a flagged case, a silent case, the 'entity not connected' silence, tuned limits and (for states) the
finding closing by itself. Expected numbers are worked out by hand in the comments."""

from datetime import date, datetime, timedelta
from decimal import Decimal as D  # noqa: N817
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.connect_helpers import CONNECT, TODAY, Planter, at, make_connect_shop, new_connection, rows
from tests.stock_helpers import system
from ziira.modules.connect.public import (
    Expense,
    Invoice,
    JournalEntry,
    JournalLine,
    Party,
    Payment,
    Product,
    Sale,
    SaleLine,
    SalePayment,
    StockMovement,
    User,
)
from ziira.modules.connect.standalone_checks import CHECKS, METRICS
from ziira.modules.intel.services import baselines, engine

INTEL = "/api/v1/intel"
D0 = TODAY - timedelta(days=1)          # Tuesday 13 October 2026
TZ_MIDNIGHT = at(TODAY + timedelta(days=1), 0)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.command.hooks  # noqa: F401
    import ziira.modules.intel.hooks  # noqa: F401

    return make_connect_shop(client, registry, "Checks Co")


@pytest.fixture(autouse=True)
def clean(shop) -> None:  # type: ignore[no-untyped-def]
    """Every test starts from an empty business: no connections (and so no records), findings or baselines."""
    with system(shop) as s:
        for sql in ("delete from intel.finding_event", "delete from intel.finding", "delete from intel.baseline",
                    "delete from intel.check_setting", "delete from connect.connection"):
            s.execute(text(sql))


def plant(client, shop, kind: str = "csv_sales", name: str = "Planted", through: datetime | None = None) -> Planter:  # type: ignore[no-untyped-def]
    return Planter(shop, UUID(new_connection(client, shop, kind, name)["id"]), through)


def learn(shop, today: date = TODAY) -> None:  # type: ignore[no-untyped-def]
    """Learn what is normal from the history planted so far (no check is run)."""
    with system(shop) as s:
        baselines.refresh_company(s, shop["company_id"], today)


def clear_findings(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))


def run(shop, code: str, today: date = TODAY):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=today, only={code})


def found(shop, code: str, status: str | None = None) -> list[Any]:  # type: ignore[no-untyped-def]
    extra = "" if status is None else " and status = :s"
    return rows(shop, "select summary, severity, amount, status, branch_id, value, period_start from intel.finding "
                      f"where check_code = :c{extra} order by summary", c=code, s=status)


def tune(client, shop, code: str, **params: Any) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"{INTEL}/checks/{code}", headers=shop["owner"], json={"params": params})
    assert r.status_code == 200, r.text


def S(ref: str, day: date, hour: int = 10, total: str = "100", status: str = "posted", branch: str | None = "HQ",  # noqa: N802
      cashier: str | None = None, method: str | None = None, reference: str | None = None, lines: tuple[SaleLine, ...] = (),
      entered: datetime | None = None, minute: int = 0, discount: str = "0", voided_by: str | None = None) -> Sale:
    pay = (SalePayment(method, D(total), reference),) if method else ()
    return Sale(ref=ref, occurred_at=at(day, hour, minute), total=D(total), status=status,  # type: ignore[arg-type]
                number=f"N-{ref}", branch_ref=branch, cashier_ref=cashier, entered_at=entered, lines=lines,
                payments=pay, discount_total=D(discount), voided_by_ref=voided_by)


def P(ref: str, day: date, hour: int, amount: str, *, direction: str = "in", method: str = "mobile_money",  # noqa: N802
      reference: str | None = None, branch: str | None = None, minute: int = 0, name: str | None = None,
      account: str | None = "ACC1", invoice_ref: str | None = None, party_ref: str | None = None) -> Payment:
    return Payment(ref=ref, occurred_at=at(day, hour, minute), direction=direction, amount=D(amount),  # type: ignore[arg-type]
                   method=method, reference=reference, party_name=name, account=account, branch_ref=branch,
                   invoice_ref=invoice_ref, party_ref=party_ref)


def money(summary: str) -> bool:
    return bool(summary)


# --------------------------------------------------------------------------- the machinery
def test_every_check_is_registered_with_a_unique_code_and_says_what_it_needs() -> None:
    codes = [c.code for c in CHECKS]
    assert len(codes) == len(set(codes)) and all(c.startswith("standalone.") for c in codes)
    assert all(c.requires and c.title and c.description and c.area for c in CHECKS)
    assert {m.code for m in METRICS} == {"standalone.cashier_void_rate", "standalone.cashier_refund_rate",
                                         "standalone.cashier_discount_rate", "standalone.branch_daily_sales",
                                         "standalone.expense_by_category"}


def test_nothing_runs_for_a_business_with_no_connections_and_the_engine_survives_every_check(client, shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = engine.run_company(s, shop["company_id"], today=TODAY)
    assert result.failed == []
    assert rows(shop, "select count(*) as n from intel.finding where check_code like 'standalone.%'")[0].n == 0
    with system(shop) as s:
        defined = {r.code for r in s.execute(text("select code from intel.check_definition"))}
    assert {c.code for c in CHECKS} <= defined


def test_a_check_whose_entity_was_never_connected_stays_silent_even_with_other_data(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Only invoices are connected: the sales and payment checks say nothing, however odd the invoices."""
    p = plant(client, shop, "csv_invoices")
    p.put("invoices", [Invoice("i1", "customer", TODAY - timedelta(days=100), D("500"), due_date=TODAY - timedelta(days=60),
                               party_ref="c1")])
    with system(shop) as s:
        result = engine.run_company(s, shop["company_id"], today=TODAY)
    assert result.failed == []
    codes = {r.check_code for r in rows(shop, "select check_code from intel.finding where check_code like 'standalone.%'")}
    assert codes == {"standalone.customer_overdue"}


def test_a_connection_that_was_never_read_to_the_end_supplies_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    p.put("sales", [S("a", D0, 3, "500", status="voided", cashier="c1")], mark=False)      # stored, but never marked read
    run(shop, "standalone.large_exception")
    assert found(shop, "standalone.large_exception") == []
    tune(client, shop, "standalone.large_exception", min_void="100")
    p.mark("sales")
    run(shop, "standalone.large_exception")
    assert len(found(shop, "standalone.large_exception")) == 1


# --------------------------------------------------------------------------- cash and sales
def test_sale_without_payment_flags_unmatched_electronic_sales_per_branch_and_day(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    d12, d13 = date(2026, 10, 12), date(2026, 10, 13)
    p.put("sales", [
        S("s1", d12, 10, "1000", method="mobile_money", reference="QX1"),          # matched by code (case ignored)
        S("s2", d12, 11, "2000", method="mobile_money", reference="QX2"),          # nothing on the statement
        S("s3", d12, 12, "3000", method="bank"),                                   # matched by amount, 30 minutes apart
        S("s4", d12, 13, "500", method="cash"),                                    # cash is not on a statement
        S("s5", d13, 15, "700", method="mobile_money"),                            # a payment 5 hours later: too far
        S("s6", TODAY, 9, "900", method="mobile_money"),                           # today: inside the 24-hour grace
        S("s7", d12, 14, "4000", method="mobile_money", branch="JUJA")])           # Juja: nothing either
    bank = plant(client, shop, "mobile_money_statement", "Till statement")
    bank.put("payments", [P("p1", d12, 10, "1000", reference="qx1", minute=5), P("p2", d12, 12, "3000", minute=30),
                          P("p3", d13, 20, "700")])
    run(shop, "standalone.sale_without_payment")
    items = {(f.period_start, f.branch_id): f for f in found(shop, "standalone.sale_without_payment")}
    assert set(items) == {(d12, shop["branch_id"]), (d13, shop["branch_id"]), (d12, shop["juja"])}
    hq12 = items[(d12, shop["branch_id"])]
    assert D(hq12.amount) == D("2000.00") and hq12.severity == "medium"
    assert "1 sale at Head office on 2026-10-12 worth KES 2,000.00" in hq12.summary
    assert D(items[(d13, shop["branch_id"])].amount) == D("700.00")
    assert D(items[(d12, shop["juja"])].amount) == D("4000.00")


def test_sale_without_payment_is_silent_without_statements_waits_for_them_and_closes_when_they_arrive(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    d12 = date(2026, 10, 12)
    p.put("sales", [S("s1", d12, 10, "2000", method="mobile_money", reference="QX2")])
    run(shop, "standalone.sale_without_payment")
    assert found(shop, "standalone.sale_without_payment") == []                    # no statement connected: silent
    bank = plant(client, shop, "mobile_money_statement", "Statement", through=at(d12, 8))
    bank.put("payments", [P("p0", d12, 7, "50")])
    run(shop, "standalone.sale_without_payment")
    assert found(shop, "standalone.sale_without_payment") == []                    # the statement ends before the sale
    bank.mark("payments", through=TZ_MIDNIGHT)
    run(shop, "standalone.sale_without_payment")
    assert len(found(shop, "standalone.sale_without_payment", "new")) == 1
    bank.put("payments", [P("p1", d12, 10, "2000", reference="QX2", minute=2)])
    result = run(shop, "standalone.sale_without_payment")
    assert result.resolved == 1 and len(found(shop, "standalone.sale_without_payment", "resolved")) == 1


def test_sale_without_payment_can_be_tuned_and_says_high_when_many(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    d12 = date(2026, 10, 12)
    p.put("sales", [S(f"m{i}", d12, 9 + i, "100", method="mobile_money") for i in range(5)])
    plant(client, shop, "mobile_money_statement", "Statement").put("payments", [P("p9", d12, 3, "999")])
    run(shop, "standalone.sale_without_payment")
    only = found(shop, "standalone.sale_without_payment")[0]
    assert only.severity == "high" and D(only.amount) == D("500.00") and "5 sales" in only.summary
    tune(client, shop, "standalone.sale_without_payment", high_count=6)
    run(shop, "standalone.sale_without_payment")
    assert found(shop, "standalone.sale_without_payment")[0].severity == "medium"
    tune(client, shop, "standalone.sale_without_payment", methods="bank")
    assert run(shop, "standalone.sale_without_payment").resolved == 1


def test_cash_deposit_gap_compares_cash_sales_with_deposits_per_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Window: 5-11 October (7 days ending 2 days before yesterday). HQ took 10,000+10,000+5,000 = 25,000 in cash and
    banked 18,000: a gap of 7,000 (more than 10%); Juja took 8,000 and banked nothing."""
    p = plant(client, shop, "csv_sales")
    p.put("sales", [S("c1", date(2026, 10, 6), 10, "10000", method="cash"), S("c2", date(2026, 10, 7), 10, "10000", method="cash"),
                    S("c3", date(2026, 10, 8), 10, "5000", method="cash"),
                    S("c4", date(2026, 10, 9), 10, "8000", method="cash", branch="JUJA"),
                    S("c5", date(2026, 10, 12), 10, "99999", method="cash"),                # after the window
                    S("c6", date(2026, 10, 7), 11, "4000", method="mobile_money")])        # not cash
    bank = plant(client, shop, "bank_statement", "Bank")
    bank.put("payments", [P("d1", date(2026, 10, 9), 11, "18000", method="cash", branch="HQ", reference="DEP1")])
    run(shop, "standalone.cash_deposit_gap")
    by_branch = {f.branch_id: f for f in found(shop, "standalone.cash_deposit_gap")}
    assert set(by_branch) == {shop["branch_id"], shop["juja"]}
    hq, juja = by_branch[shop["branch_id"]], by_branch[shop["juja"]]
    assert D(hq.amount) == D("7000.00") and hq.severity == "medium"
    assert "took KES 25,000.00 in cash" in hq.summary and "deposits of only KES 18,000.00" in hq.summary
    assert D(juja.amount) == D("8000.00") and juja.severity == "high"
    bank.put("payments", [P("d2", date(2026, 10, 10), 11, "7000", method="cash", branch="HQ", reference="DEP2"),
                          P("d3", date(2026, 10, 10), 12, "8000", method="cash", branch="JUJA", reference="DEP3")])
    assert run(shop, "standalone.cash_deposit_gap").resolved == 2


def test_cash_deposit_gap_tolerance_company_level_and_a_statement_that_does_not_reach_yet(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Cash taken 20,000 + 13,000 = 33,000. Deposits that name no branch are compared with the whole business: 31,000 is
    a 2,000 (6%) gap, inside the 10% tolerance; 28,000 is a 5,000 (15%) gap."""
    p = plant(client, shop, "csv_sales")
    p.put("sales", [S("c1", date(2026, 10, 6), 10, "20000", method="cash"),
                    S("c2", date(2026, 10, 7), 10, "13000", method="cash", branch="JUJA")])
    bank = plant(client, shop, "bank_statement", "Bank")
    bank.put("payments", [P("d1", date(2026, 10, 8), 11, "31000", method="cash", reference="D1")])
    run(shop, "standalone.cash_deposit_gap")
    assert found(shop, "standalone.cash_deposit_gap") == []
    bank.put("payments", [P("d1", date(2026, 10, 8), 11, "28000", method="cash", reference="D1")])
    run(shop, "standalone.cash_deposit_gap")
    (gap,) = found(shop, "standalone.cash_deposit_gap")
    assert gap.branch_id is None and D(gap.amount) == D("5000.00")
    assert gap.summary.startswith("The business took KES 33,000.00 in cash")
    tune(client, shop, "standalone.cash_deposit_gap", tolerance_percent=20)
    assert run(shop, "standalone.cash_deposit_gap").resolved == 1
    tune(client, shop, "standalone.cash_deposit_gap", tolerance_percent=10)
    run(shop, "standalone.cash_deposit_gap")
    plant(client, shop, "bank_statement", "Late bank", through=at(date(2026, 10, 10), 0)).mark("payments")   # one ends too early
    assert run(shop, "standalone.cash_deposit_gap").resolved == 1


def test_branch_sales_low_judges_yesterday_against_the_weekday_normal(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Eight Tuesdays at 10,000 +/- (mean 10,000, deviation 187.08). Yesterday (a Tuesday) HQ sold 2,000: 80% down and
    far under mean - 2 deviations (9,625.8), and under a quarter of normal, so high."""
    p = plant(client, shop, "csv_sales")
    tuesdays = [date(2026, 8, 18) + timedelta(days=7 * i) for i in range(8)]
    totals = ["10000", "10200", "9800", "10100", "9900", "10000", "10300", "9700"]
    p.put("sales", [S(f"t{i}", d, 11, t) for i, (d, t) in enumerate(zip(tuesdays, totals, strict=True))])
    learn(shop)                          # learn from history, before yesterday
    p.put("sales", [S("low", D0, 11, "2000")])
    run(shop, "standalone.branch_sales_low")
    (f,) = found(shop, "standalone.branch_sales_low")
    assert f.severity == "high" and D(f.amount) == D("8000.00") and f.branch_id == shop["branch_id"]
    assert "Head office sold KES 2,000.00 on 2026-10-13 (Tuesday)" in f.summary and "about KES 10,000.00" in f.summary


def test_branch_sales_low_silent_cases_boundaries_and_incomplete_days(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    tuesdays = [date(2026, 8, 18) + timedelta(days=7 * i) for i in range(8)]
    totals = ["10000", "10200", "9800", "10100", "9900", "10000", "10300", "9700"]
    p.put("sales", [S(f"t{i}", d, 11, t) for i, (d, t) in enumerate(zip(tuesdays, totals, strict=True))])
    learn(shop)
    p.put("sales", [S("ok", D0, 11, "7000")])                                       # 30% down only
    run(shop, "standalone.branch_sales_low")
    assert found(shop, "standalone.branch_sales_low") == []
    p.put("sales", [S("ok", D0, 11, "5000")])                                       # exactly 50% down and under 9,625.8
    run(shop, "standalone.branch_sales_low")
    assert [f.severity for f in found(shop, "standalone.branch_sales_low")] == ["medium"]
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    tune(client, shop, "standalone.branch_sales_low", drop_percent=60)
    run(shop, "standalone.branch_sales_low")
    assert found(shop, "standalone.branch_sales_low") == []                         # 5,000 is not 60% down
    tune(client, shop, "standalone.branch_sales_low", drop_percent=50)
    plant(client, shop, "csv_sales", "Late sales", through=at(D0, 0)).mark("sales")        # yesterday not fully read yet
    run(shop, "standalone.branch_sales_low")
    assert found(shop, "standalone.branch_sales_low") == []


def test_sales_outside_trading_hours_in_the_company_time_zone(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    d12 = date(2026, 10, 12)
    p.put("sales", [S("n1", d12, 3, "100", minute=30), S("n2", d12, 5, "200", minute=59), S("n3", d12, 6, "300"),
                    S("n4", d12, 21, "400", minute=59), S("n5", d12, 22, "500"), S("n6", d12, 23, "600", minute=10),
                    S("n7", d12, 12, "700", branch="JUJA")])
    run(shop, "standalone.out_of_hours_sales")
    (f,) = found(shop, "standalone.out_of_hours_sales")
    # 03:30, 05:59 (before 06:00) and 22:00, 23:10 (from 22:00 on) are out; 06:00 and 21:59 are in
    assert D(f.amount) == D("1400.00") and f.severity == "low" and f.branch_id == shop["branch_id"]
    assert "made 4 sales worth KES 1,400.00 on 2026-10-12 outside 06:00-22:00, the first at 03:30" in f.summary
    tune(client, shop, "standalone.out_of_hours_sales", open_hour=0, close_hour=24)
    run(shop, "standalone.out_of_hours_sales")
    assert len(found(shop, "standalone.out_of_hours_sales")) == 1                   # an event stays until a person deals with it
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    run(shop, "standalone.out_of_hours_sales")
    assert found(shop, "standalone.out_of_hours_sales") == []


def test_sales_entered_days_after_their_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    p.put("sales", [S("l1", date(2026, 10, 8), 10, "100", cashier="u1", entered=at(date(2026, 10, 13), 9)),     # 5 days late
                    S("l2", date(2026, 10, 1), 10, "200", cashier="u1", entered=at(date(2026, 10, 9), 9)),      # 8 days late
                    S("l3", date(2026, 10, 12), 10, "300", entered=at(date(2026, 10, 13), 9)),                   # 1 day: fine
                    S("l4", date(2026, 10, 5), 10, "400"),                                                       # no entry time
                    S("l5", date(2026, 9, 1), 10, "500", entered=at(date(2026, 9, 20), 9))])                     # long ago
    p.put("users", [User("u1", "Wambui")])
    run(shop, "standalone.late_entered_sales")
    items = {D(f.amount): f for f in found(shop, "standalone.late_entered_sales")}
    assert set(items) == {D("100.00"), D("200.00")}
    assert items[D("100.00")].severity == "low" and items[D("200.00")].severity == "medium"
    assert ("Sale N-l2 by Wambui for KES 200.00 is dated 2026-10-01 but was entered on 2026-10-09, 8 days later."
            in items[D("200.00")].summary)
    tune(client, shop, "standalone.late_entered_sales", min_days_late=6)
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    run(shop, "standalone.late_entered_sales")
    assert [D(f.amount) for f in found(shop, "standalone.late_entered_sales")] == [D("200.00")]


# --------------------------------------------------------------------------- cashier habits
def history(p: Planter, who: str, kind: str, *, flagged_days: tuple[int, ...]) -> None:
    """Fourteen days (29 September to 12 October) of ten 100-sales a day for one cashier. On the `flagged_days` (4 of
    them) one sale is odd: voided (kind 'void'), refunded ('refund') or sold at 60 against a list price of 100
    ('discount'). So the rates are 0.1 / 0.1 / 0.04 on 4 days and 0 on 10: mean 0.02857 / 0.02857 / 0.011428."""
    sales = []
    for n in range(14):
        day = date(2026, 9, 29) + timedelta(days=n)
        for i in range(10):
            odd = i == 0 and n in flagged_days
            status = "voided" if odd and kind == "void" else "refunded" if odd and kind == "refund" else "posted"
            price = "60" if odd and kind == "discount" else "100"
            sales.append(S(f"{who}-{n}-{i}", day, 10 + i % 5, price, status=status, cashier=who,
                           lines=(SaleLine("p1", D(1), D(price), D(0), D(100)),)))
    p.put("sales", sales)


def yesterday_sales(p: Planter, who: str, kind: str, odd: int) -> None:
    sales = []
    for i in range(10):
        is_odd = i < odd
        status = "voided" if is_odd and kind == "void" else "refunded" if is_odd and kind == "refund" else "posted"
        price = "60" if is_odd and kind == "discount" else "100"
        sales.append(S(f"{who}-y-{i}", D0, 10 + i % 5, price, status=status, cashier=who,
                       lines=(SaleLine("p1", D(1), D(price), D(0), D(100)),)))
    p.put("sales", sales)


@pytest.mark.parametrize(("kind", "code", "odd", "amount", "flag"), [
    # void: three voids of ten = 0.30, above mean + 3 deviations (0.1641) and above the 95th percentile (0.1): flagged
    ("void", "standalone.cashier_void_rate", 3, "300.00", True),
    # one void of ten = 0.10: not above the 95th percentile of their own days (0.1)
    ("void", "standalone.cashier_void_rate", 1, "100.00", False),
    # refund: three refunded sales of 100 against 700 posted = 0.43; one against 900 posted = 0.11 which is above 0.1
    # (the baseline's own p95 is 100/900) -> not above its own 95th percentile
    ("refund", "standalone.cashier_refund_rate", 3, "300.00", True),
    ("refund", "standalone.cashier_refund_rate", 1, "100.00", False),
    # discount: three sales at 60 on a list of 100 = 120 given away of 1,000 list value = 0.12; one = 0.04, under the 5% floor
    ("discount", "standalone.cashier_discount_rate", 3, "120.00", True),
    ("discount", "standalone.cashier_discount_rate", 1, "40.00", False),
])
def test_cashier_habits_are_judged_against_their_own_baseline(client, shop, kind, code, odd, amount, flag) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    history(p, "u1", kind, flagged_days=(2, 5, 8, 11))
    learn(shop)
    yesterday_sales(p, "u1", kind, odd)
    run(shop, code)
    items = found(shop, code)
    if not flag:
        assert items == []
        return
    (f,) = items
    assert D(f.amount) == D(amount) and f.severity == "medium" and f.branch_id == shop["branch_id"]
    assert f"On {D0}" in f.summary and "over 10 sales" in f.summary
    if kind == "void":
        assert "u1's void rate was 30% over 10 sales (KES 300.00); their usual is about 3%." in f.summary


def test_cashier_rates_need_enough_history_and_sales_and_a_named_cashier(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    yesterday_sales(p, "u1", "void", 5)                                              # no history at all: nothing is unusual
    learn(shop)
    assert found(shop, "standalone.cashier_void_rate") == []
    history(p, "u2", "void", flagged_days=(2, 5, 8, 11))
    learn(shop)
    p.put("sales", [S(f"few{i}", D0, 10, "100", status="voided", cashier="u2") for i in range(4)])    # only 4 sales (min 5)
    run(shop, "standalone.cashier_void_rate")
    assert found(shop, "standalone.cashier_void_rate") == []
    p.put("sales", [S(f"anon{i}", D0, 10, "100", status="voided", cashier=None) for i in range(9)])    # no cashier named
    run(shop, "standalone.cashier_void_rate")
    assert found(shop, "standalone.cashier_void_rate") == []
    tune(client, shop, "standalone.cashier_void_rate", min_sales=4)
    run(shop, "standalone.cashier_void_rate")
    assert len(found(shop, "standalone.cashier_void_rate")) == 1


def test_large_voids_refunds_and_discounts(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    p.put("users", [User("u1", "Achieng"), User("boss", "Mr Boss")])
    d12 = date(2026, 10, 12)
    p.put("sales", [
        S("v1", d12, 10, "5000", status="voided", cashier="u1", voided_by="boss"),     # voided by the manager
        S("v2", d12, 11, "1500", status="voided", cashier="u1"),                       # under the 2,000 limit
        S("r1", d12, 12, "2500", status="refunded", cashier="u1"),
        S("d1", d12, 13, "2900", cashier="u1", lines=(SaleLine("p1", D(3), D(800), D(500), D(1000)),)),   # 3 x 200 + 500
        S("d2", d12, 14, "950", cashier="u1", lines=(SaleLine("p1", D(1), D(950), D(0), D(1000)),)),      # only 50 off
        S("d3", d12, 15, "900", cashier="u1", discount="1200")])                        # no lines: the sale-level discount
    run(shop, "standalone.large_exception")
    items = {f.summary.split(" ")[1]: f for f in found(shop, "standalone.large_exception")}
    assert set(items) == {"N-v1", "N-r1", "N-d1", "N-d3"}
    assert "voided by Mr Boss" in items["N-v1"].summary and D(items["N-v1"].amount) == D("5000.00")
    assert "refunded" in items["N-r1"].summary and D(items["N-r1"].amount) == D("2500.00")
    assert D(items["N-d1"].amount) == D("1100.00") and D(items["N-d3"].amount) == D("1200.00")
    tune(client, shop, "standalone.large_exception", min_void="6000", min_refund="3000", min_discount="1150")
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    run(shop, "standalone.large_exception")
    assert [f.summary.split(" ")[1] for f in found(shop, "standalone.large_exception")] == ["N-d3"]


# --------------------------------------------------------------------------- customers
def inv(ref: str, issued: date, total: str, *, due: date | None = None, paid: str = "0", status: str = "open",
        party: str | None = "c1", kind: str = "customer", number: str | None = None, branch: str | None = None,
        by: str | None = None, approved: str | None = None) -> Invoice:
    return Invoice(ref=ref, kind=kind, issue_date=issued, total=D(total), paid=D(paid), due_date=due,  # type: ignore[arg-type]
                   number=number or f"INV-{ref}", party_ref=party, branch_ref=branch, status=status,  # type: ignore[arg-type]
                   created_by_ref=by, approved_by_ref=approved)


def test_customer_overdue_flags_by_age_and_clears_when_paid(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_invoices")
    p.put("parties", [Party("c1", "customer", "Mama Njeri Shop"), Party("c2", "customer", "Kamau Hardware")])
    p.put("invoices", [
        inv("a", TODAY - timedelta(days=80), "1000", due=TODAY - timedelta(days=40), paid="200", party="c1"),   # owes 800, 40 days
        inv("b", TODAY - timedelta(days=60), "500", due=TODAY - timedelta(days=20), party="c1"),                # owes 500, 20 days
        inv("c", TODAY - timedelta(days=150), "3000", due=TODAY - timedelta(days=100), party="c2"),             # 100 days: high
        inv("d", TODAY - timedelta(days=30), "900", due=TODAY - timedelta(days=10), party="c3"),                 # only 10 days
        inv("e", TODAY - timedelta(days=90), "700", due=TODAY - timedelta(days=50), party="c4", status="paid", paid="700"),
        inv("f", TODAY - timedelta(days=90), "700", due=TODAY - timedelta(days=50), party="c5", kind="supplier"),
        inv("g", TODAY - timedelta(days=90), "700", due=TODAY - timedelta(days=50), party="c6", status="cancelled")])
    run(shop, "standalone.customer_overdue")
    items = {f.value: f for f in found(shop, "standalone.customer_overdue")}
    assert set(items) == {D("40"), D("100")}
    njeri, kamau = items[D("40")], items[D("100")]
    assert njeri.summary == "Mama Njeri Shop owes KES 1,300.00 past due on 2 invoices; the oldest is 40 days overdue."
    assert D(njeri.amount) == D("1300.00") and njeri.severity == "medium"
    assert kamau.severity == "high" and D(kamau.amount) == D("3000.00")
    tune(client, shop, "standalone.customer_overdue", min_days_overdue=5)
    run(shop, "standalone.customer_overdue")
    assert len(found(shop, "standalone.customer_overdue")) == 3                    # the 10-day-old one now counts
    p.put("invoices", [inv("c", TODAY - timedelta(days=150), "3000", due=TODAY - timedelta(days=100), party="c2",
                           status="paid", paid="3000")])
    assert run(shop, "standalone.customer_overdue").resolved == 1


def test_customers_paying_slower_uses_the_payments_that_name_their_invoices(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Three invoices paid in the 90 days before the last 90 took 10 days each; the three paid recently took 30 days:
    +20 days (200%), which is at least 5 days and more than 50%."""
    def paid_pairs(prefix: str, party: str, paid_on: list[date], took: int) -> tuple[list[Invoice], list[Payment]]:
        invoices = [inv(f"{prefix}{i}", d - timedelta(days=took), "1000", due=d, status="paid", paid="1000", party=party)
                    for i, d in enumerate(paid_on)]
        payments = [P(f"pay-{prefix}{i}", d, 12, "1000", invoice_ref=f"{prefix}{i}") for i, d in enumerate(paid_on)]
        return invoices, payments
    old = [date(2026, 6, 1), date(2026, 6, 10), date(2026, 6, 20)]
    new = [date(2026, 9, 1), date(2026, 9, 10), date(2026, 9, 20)]
    steady = [date(2026, 9, 2), date(2026, 9, 11), date(2026, 9, 21)]
    invoices, payments = [], []
    for prefix, party, dates, took in (("o", "c1", old, 10), ("n", "c1", new, 30), ("so", "c2", old, 10),
                                       ("sn", "c2", steady, 12)):
        i, pay = paid_pairs(prefix, party, dates, took)
        invoices += i
        payments += pay
    p = plant(client, shop, "csv_invoices")
    p.put("parties", [Party("c1", "customer", "Slow Payer Ltd"), Party("c2", "customer", "Steady Ltd")])
    p.put("invoices", invoices + [inv("open1", TODAY - timedelta(days=5), "400", due=TODAY + timedelta(days=25), party="c1")])
    plant(client, shop, "bank_statement", "Bank").put("payments", payments)
    run(shop, "standalone.customer_paying_slower")
    (f,) = found(shop, "standalone.customer_paying_slower")
    assert f.severity == "medium" and D(f.amount) == D("400.00")
    assert f.summary == ("Slow Payer Ltd now takes 30 days on average to pay, up from 10 days in the 90 days before; "
                         "they currently owe KES 400.00.")
    tune(client, shop, "standalone.customer_paying_slower", min_invoices=4)
    assert run(shop, "standalone.customer_paying_slower").resolved == 1


def test_customers_paying_slower_is_silent_without_payment_evidence(client, shop) -> None:  # type: ignore[no-untyped-def]
    plant(client, shop, "csv_invoices").put("invoices", [inv("x", date(2026, 6, 1), "10", status="paid", paid="10")])
    run(shop, "standalone.customer_paying_slower")
    assert found(shop, "standalone.customer_paying_slower") == []


def test_credit_given_to_a_customer_who_was_already_overdue(client, shop) -> None:  # type: ignore[no-untyped-def]
    """c1 owed 5,000 due on 1 September. A new invoice on 10 October (39 days after) is flagged; one on 1 October is
    outside the 7-day window; c2 owed nothing overdue."""
    p = plant(client, shop, "csv_invoices")
    p.put("parties", [Party("c1", "customer", "Late Payer")])
    p.put("invoices", [inv("old", date(2026, 8, 1), "5000", due=date(2026, 9, 1), party="c1"),
                       inv("new", date(2026, 10, 10), "2000", due=date(2026, 11, 10), party="c1", branch="JUJA"),
                       inv("early", date(2026, 10, 1), "1500", due=date(2026, 11, 1), party="c1"),
                       inv("clean", date(2026, 10, 11), "900", due=date(2026, 11, 11), party="c2"),
                       inv("fresh", date(2026, 10, 12), "800", due=date(2026, 10, 30), party="c3"),
                       inv("fresh2", date(2026, 10, 12), "800", due=date(2026, 11, 30), party="c3")])
    run(shop, "standalone.credit_to_overdue_customer")
    (f,) = found(shop, "standalone.credit_to_overdue_customer")
    assert f.severity == "medium" and D(f.amount) == D("2000.00") and f.branch_id == shop["juja"]
    assert ("Invoice INV-new for KES 2,000.00 was issued on 2026-10-10 to Late Payer, who still owes KES 5,000.00 on 1 "
            "older invoice that was already overdue (the oldest by 39 days).") in f.summary
    tune(client, shop, "standalone.credit_to_overdue_customer", days=14, high_days_overdue=30)
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    run(shop, "standalone.credit_to_overdue_customer")
    assert {f.severity for f in found(shop, "standalone.credit_to_overdue_customer")} == {"high"}
    assert len(found(shop, "standalone.credit_to_overdue_customer")) == 2


# --------------------------------------------------------------------------- suppliers
def buy(ref: str, day: date, cost: str, product: str = "x1", qty: str = "10", **kw: Any) -> StockMovement:
    return StockMovement(ref=ref, occurred_at=at(day), product_ref=product, quantity=D(qty), kind="purchase",
                         unit_cost=D(cost), **kw)


def test_supplier_price_rise_compares_the_latest_purchase_with_earlier_ones(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Earlier purchases at 100, 102, 100 average 100.667; the latest, at 125, is 24.17% dearer: high (over 20%)."""
    p = plant(client, shop, "csv_stock")
    p.put("products", [Product("x1", "Cement 50kg"), Product("x2", "Paint")])
    p.put("stock_movements", [
        buy("b1", date(2026, 6, 1), "100"), buy("b2", date(2026, 7, 1), "102"), buy("b3", date(2026, 8, 1), "100"),
        buy("b4", date(2026, 10, 10), "125"),
        buy("c1", date(2026, 7, 1), "50", product="x2"), buy("c2", date(2026, 8, 1), "50", product="x2"),
        buy("c3", date(2026, 10, 9), "52", product="x2"),                                # 4%: fine
        buy("d1", date(2026, 8, 1), "10", product="x3"), buy("d2", date(2026, 10, 9), "30", product="x3")])   # one earlier only
    run(shop, "standalone.supplier_price_rise")
    (f,) = found(shop, "standalone.supplier_price_rise")
    assert f.severity == "high" and D(f.amount) == D("24.33")
    assert "Cement 50kg was last bought on 2026-10-10 at KES 125.00 a unit, 24% above the KES 100.67 it cost on average" in f.summary
    tune(client, shop, "standalone.supplier_price_rise", rise_percent=30)
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    run(shop, "standalone.supplier_price_rise")
    assert found(shop, "standalone.supplier_price_rise") == []
    tune(client, shop, "standalone.supplier_price_rise", rise_percent=3, min_earlier=1)
    run(shop, "standalone.supplier_price_rise")
    assert len(found(shop, "standalone.supplier_price_rise")) == 3


def test_duplicate_supplier_invoices_by_number_or_by_date_and_clears_when_one_is_cancelled(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_invoices")
    p.put("parties", [Party("s1", "supplier", "Bidco Supplies")])
    p.put("invoices", [
        inv("a", date(2026, 10, 1), "5000", party="s1", kind="supplier", number="INV-77"),
        inv("b", date(2026, 10, 20), "5000", party="s1", kind="supplier", number="inv-77"),        # same number, any date
        inv("c", date(2026, 9, 1), "800", party="s1", kind="supplier", number="X1"),
        inv("d", date(2026, 9, 3), "800", party="s1", kind="supplier", number="X2"),                # 2 days apart
        inv("e", date(2026, 8, 1), "650", party="s1", kind="supplier", number="Y1"),
        inv("f", date(2026, 8, 10), "650", party="s1", kind="supplier", number="Y2"),               # 9 days apart: fine
        inv("g", date(2026, 9, 1), "800", party="s2", kind="supplier", number="X3"),                # other supplier
        inv("h", date(2026, 9, 2), "800", party="s1", kind="supplier", number="X4", status="cancelled"),
        inv("i", date(2026, 9, 2), "800", party="s9", kind="customer", number="X5"),                # a customer invoice
        inv("j", date(2026, 9, 2), "800", party="s9", kind="customer", number="X6")])
    run(shop, "standalone.duplicate_supplier_invoice")
    items = found(shop, "standalone.duplicate_supplier_invoice")
    assert sorted(D(f.amount) for f in items) == [D("800.00"), D("5000.00")]
    big = next(f for f in items if D(f.amount) == D("5000.00"))
    assert big.summary == ("Invoices INV-77 (2026-10-01) and inv-77 (2026-10-20) from Bidco Supplies are both for "
                           "KES 5,000.00: one may be a duplicate.")
    tune(client, shop, "standalone.duplicate_supplier_invoice", days_apart=1)
    assert run(shop, "standalone.duplicate_supplier_invoice").resolved == 1          # the 2-day pair is no longer one
    p.put("invoices", [inv("b", date(2026, 10, 20), "5000", party="s1", kind="supplier", number="inv-77",
                           status="cancelled")])
    assert run(shop, "standalone.duplicate_supplier_invoice").resolved == 1
    assert found(shop, "standalone.duplicate_supplier_invoice", "new") == []


def test_duplicate_payments_to_the_same_payee_close_together(client, shop) -> None:  # type: ignore[no-untyped-def]
    d12 = date(2026, 10, 12)
    out = plant(client, shop, "bank_statement", "Bank")
    out.put("payments", [
        P("a1", d12, 8, "2500", direction="out", method="bank", name="Bidco Ltd"),
        P("a2", d12, 14, "2500", direction="out", method="bank", name="bidco ltd"),                      # 6 hours later
        P("b1", d12, 9, "900", direction="out", method="bank", name="Unga Ltd"),
        P("b2", date(2026, 10, 9), 9, "900", direction="out", method="bank", name="Unga Ltd"),           # 3 days apart
        P("c1", d12, 9, "700", direction="out", method="bank", name="Mabati", reference="TX1"),
        P("c2", d12, 10, "700", direction="out", method="bank", name="Mabati", reference="TX2"),         # two real transfers
        P("f1", d12, 9, "650", direction="out", method="bank", name="Nakumatt", reference="TX5"),
        P("f2", d12, 11, "650", direction="out", method="bank", name="Nakumatt", reference="TX5"),       # the same one twice
        P("d1", d12, 9, "300", direction="out", method="bank", name="Nation", invoice_ref="I1"),
        P("d2", d12, 10, "300", direction="out", method="bank", name="Nation", invoice_ref="I2"),        # different invoices
        P("e1", d12, 9, "400", direction="in", name="Customer"), P("e2", d12, 10, "400", direction="in", name="Customer")])
    run(shop, "standalone.duplicate_payment")
    amounts = sorted(D(f.amount) for f in found(shop, "standalone.duplicate_payment"))
    assert amounts == [D("700.00"), D("2500.00")]      # Bidco; and the two Mabati transfers with different codes
    big = next(f for f in found(shop, "standalone.duplicate_payment") if D(f.amount) == D("2500.00"))
    assert "Two payments of KES 2,500.00 went to Bidco Ltd, on 2026-10-12 08:00 and 2026-10-12 14:00" in big.summary
    tune(client, shop, "standalone.duplicate_payment", hours_apart=96)
    run(shop, "standalone.duplicate_payment")
    assert sorted(D(f.amount) for f in found(shop, "standalone.duplicate_payment")) == [D("700.00"), D("900.00"), D("2500.00")]


# --------------------------------------------------------------------------- stock
def adj(ref: str, day: date, qty: str, *, hour: int = 10, product: str = "x1", cost: str | None = "50",
        entered: datetime | None = None, user: str | None = "u1", reason: str | None = None, kind: str = "adjustment",
        branch: str | None = "HQ") -> StockMovement:
    return StockMovement(ref=ref, occurred_at=at(day, hour), product_ref=product, quantity=D(qty), kind=kind,  # type: ignore[arg-type]
                         unit_cost=D(cost) if cost else None, entered_at=entered, user_ref=user, reason=reason,
                         branch_ref=branch)


def test_stock_adjustments_large_odd_hours_or_back_dated(client, shop) -> None:  # type: ignore[no-untyped-def]
    d12 = date(2026, 10, 12)
    p = plant(client, shop, "csv_stock")
    p.put("products", [Product("x1", "Cement 50kg", unit_cost=D(50)), Product("x9", "Bolts")])
    p.put("users", [User("u1", "Otieno")])
    p.put("stock_movements", [
        adj("a1", d12, "-120", reason="damaged"),                                  # 120 x 50 = 6,000: large
        adj("a2", d12, "-10"),                                                     # 500: fine
        adj("a3", d12, "-4", hour=2),                                              # 200 but at 02:00
        adj("a4", d12, "-4", entered=at(date(2026, 10, 13), 10)),                  # 1 day late: fine
        adj("a5", d12, "-4", entered=at(date(2026, 10, 7), 10)),                   # dated 5 days before it was entered? entered earlier -> negative
        adj("a6", date(2026, 10, 5), "-4", entered=at(d12, 10)),                   # 7 days late
        adj("a7", d12, "150", product="x9", cost=None),                            # no cost: 150 units
        adj("a8", d12, "30", product="x9", cost=None),                             # no cost: 30 units, fine
        adj("a9", d12, "-500", kind="sale"),                                       # not an adjustment
        adj("b1", date(2026, 9, 1), "-900")])                                      # long ago
    run(shop, "standalone.stock_adjustment")
    items = {f.summary: f for f in found(shop, "standalone.stock_adjustment")}
    texts = " | ".join(items)
    assert len(items) == 4
    assert "Otieno adjusted Cement 50kg by -120 on 2026-10-12: worth KES 6,000.00. Reason given: damaged." in texts
    assert "entered at 02:00, outside trading hours" in texts and "entered 7 days after its date" in texts
    assert "150 units" in texts and all(f.severity == "medium" for f in items.values())
    tune(client, shop, "standalone.stock_adjustment", min_value="7000", min_quantity="200", backdate_days=10, open_hour=0)
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    run(shop, "standalone.stock_adjustment")
    assert found(shop, "standalone.stock_adjustment") == []


def test_stock_adjustment_with_two_reasons_is_high(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_stock")
    p.put("stock_movements", [adj("z1", date(2026, 10, 12), "-200", hour=23)])
    run(shop, "standalone.stock_adjustment")
    (f,) = found(shop, "standalone.stock_adjustment")
    assert f.severity == "high" and D(f.amount) == D("10000.00")
    assert "worth KES 10,000.00; entered at 23:00" in f.summary


def test_shrinkage_by_product_adds_up_the_write_offs_and_clears_when_the_limit_moves(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_stock")
    p.put("products", [Product("x1", "Cement 50kg"), Product("x2", "Nails")])
    p.put("stock_movements", [
        adj("s1", date(2026, 10, 1), "-30", cost="200"), adj("s2", date(2026, 10, 9), "-25", cost="200", kind="count"),   # 55 x 200
        adj("s3", date(2026, 10, 9), "-5", product="x2", cost="100"),                                                     # 500
        adj("s4", date(2026, 10, 9), "20", cost="200"),                                                                    # a gain
        adj("s5", date(2026, 7, 1), "-900", cost="200"),                                                                   # old
        adj("s6", date(2026, 10, 9), "-15", product="x3", cost=None),                                                      # no cost, 15 units
        adj("s7", date(2026, 10, 9), "-8", product="x4", cost=None)])                                                      # no cost, 8 units
    run(shop, "standalone.shrinkage_by_product")
    items = {f.summary: f for f in found(shop, "standalone.shrinkage_by_product")}
    assert len(items) == 2
    cement = next(f for s, f in items.items() if "Cement" in s)
    assert D(cement.amount) == D("11000.00") and cement.severity == "medium"
    assert "55 units of Cement 50kg were written off or counted missing at Head office in 30 days worth KES 11,000.00." in cement.summary
    assert any("15 units of x3" in s for s in items)
    tune(client, shop, "standalone.shrinkage_by_product", min_loss="12000", min_units="20")
    assert run(shop, "standalone.shrinkage_by_product").resolved == 2


def test_negative_stock_needs_movements_in_and_clears_when_stock_is_received(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_stock")
    p.put("products", [Product("x1", "Cement 50kg")])

    def move(ref: str, qty: str, product: str = "x1", kind: str = "purchase") -> StockMovement:
        return StockMovement(ref=ref, occurred_at=at(date(2026, 9, 1)), product_ref=product, quantity=D(qty), kind=kind,  # type: ignore[arg-type]
                             branch_ref="HQ")
    p.put("stock_movements", [move("m1", "10"), move("m2", "-8", kind="sale"), move("m3", "-5", kind="sale"),     # -3
                              move("n1", "10", "x2"), move("n2", "-10", "x2", "sale"),                              # exactly 0
                              move("o1", "-4", "x3", "sale")])                                                      # never received
    run(shop, "standalone.negative_stock")
    (f,) = found(shop, "standalone.negative_stock")
    assert f.summary.startswith("Cement 50kg at Head office has gone 3 units below zero")
    p.put("stock_movements", [move("m4", "5")])
    assert run(shop, "standalone.negative_stock").resolved == 1
    tune(client, shop, "standalone.negative_stock", min_units="10")
    p.put("stock_movements", [move("m5", "-7", kind="sale")])                                                       # -2 again
    run(shop, "standalone.negative_stock")
    assert found(shop, "standalone.negative_stock", "new") == []


# --------------------------------------------------------------------------- books
def jv(ref: str, entry: date, amount: str, *, entered: datetime | None = None, by: str | None = None,
       approved: str | None = None, manual: bool = True) -> JournalEntry:
    return JournalEntry(ref=ref, entry_date=entry, number=f"J-{ref}", entered_at=entered, created_by_ref=by,
                        approved_by_ref=approved, memo="adjust", is_manual=manual,
                        lines=(JournalLine("Suspense", debit=D(amount)), JournalLine("Cash", credit=D(amount))))


def test_manual_journals_with_the_usual_signs_of_trouble(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_expenses")
    p.put("users", [User("u1", "Fatuma")])
    d12 = date(2026, 10, 12)
    p.put("journal_entries", [
        # large + round + odd hour (23:30) + 9 days back-dated + same person = 5 reasons
        jv("j1", date(2026, 10, 3), "250000", entered=at(d12, 23, 30), by="u1", approved="u1"),
        jv("j2", d12, "1234.50", entered=at(d12, 11)),                                            # nothing odd
        jv("j3", d12, "120000", entered=at(d12, 11)),                                             # large + round
        jv("j4", d12, "777", entered=at(d12, 11), by="u2", approved="u2"),                        # same person only
        jv("j5", d12, "900000", entered=at(d12, 11), manual=False),                               # system generated
        jv("j6", date(2026, 8, 1), "500000")])                                                    # long ago, no entry time
    run(shop, "standalone.manual_journal")
    items = {f.summary.split(" ")[2]: f for f in found(shop, "standalone.manual_journal")}
    assert set(items) == {"J-j1", "J-j3", "J-j4"}
    assert items["J-j1"].severity == "high" and D(items["J-j1"].amount) == D("250000.00")
    assert ("a large amount, an exactly round amount, entered at 23:00, dated 9 days before it was entered, "
            "created and approved by the same person") in items["J-j1"].summary and "by Fatuma" in items["J-j1"].summary
    assert items["J-j3"].severity == "medium" and items["J-j4"].severity == "medium"
    tune(client, shop, "standalone.manual_journal", large_amount="300000", round_step="50000")
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    run(shop, "standalone.manual_journal")
    assert {f.summary.split(" ")[2] for f in found(shop, "standalone.manual_journal")} == {"J-j1", "J-j4"}


def test_an_expense_far_above_its_category_normal(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Twenty fuel expenses: ten at 1,000, five at 1,100, five at 900 (mean 1,000, deviation 70.71, 95th percentile
    1,100). 5,000 is far above; 1,150 is above the percentile but not 3 deviations (1,212) over the mean."""
    p = plant(client, shop, "csv_expenses")
    amounts = ["1000"] * 10 + ["1100"] * 5 + ["900"] * 5
    p.put("expenses", [Expense(f"h{i}", at(date(2026, 9, 1) + timedelta(days=i)), D(a), category="Fuel") for i, a in enumerate(amounts)])
    learn(shop)
    p.put("expenses", [Expense("big", at(date(2026, 10, 12)), D("5000"), category="Fuel", description="generator",
                               branch_ref="JUJA"),
                       Expense("mid", at(date(2026, 10, 12), 11), D("1150"), category="Fuel"),
                       Expense("other", at(date(2026, 10, 12), 12), D("9000"), category="Rent")])     # no history for Rent
    run(shop, "standalone.expense_unusually_high")
    (f,) = found(shop, "standalone.expense_unusually_high")
    assert f.branch_id == shop["juja"] and D(f.amount) == D("4000.00")
    assert f.summary == ("An expense of KES 5,000.00 (generator) on 2026-10-12 in 'Fuel' is far above the usual "
                         "KES 1,000.00 for that category.")
    tune(client, shop, "standalone.expense_unusually_high", min_amount="6000")
    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
    run(shop, "standalone.expense_unusually_high")
    assert found(shop, "standalone.expense_unusually_high") == []


def test_money_received_that_matches_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    d8 = date(2026, 10, 8)
    bank = plant(client, shop, "bank_statement", "Bank")
    bank.put("payments", [
        P("u1", d8, 10, "4321", method="bank", reference="FT100"),                 # matches nothing
        P("u2", d8, 11, "999", method="bank", reference="FT101"),                  # matches an invoice by total
        P("u3", d8, 12, "555", method="mobile_money", reference="QRS1"),           # matches a sale by code
        P("u4", d8, 13, "6000", method="cash", reference="DEP"),                   # a cash deposit: left out
        P("u5", d8, 14, "250", method="bank", reference="FT102", invoice_ref="INV-9"),   # names an invoice
        P("u6", TODAY, 9, "321", method="bank", reference="FT103"),                # today: inside the grace
        P("u7", d8, 15, "88", direction="out", method="bank")])                    # money out
    run(shop, "standalone.unmatched_receipt")
    assert found(shop, "standalone.unmatched_receipt") == []                       # nothing to compare with: silent
    plant(client, shop, "csv_invoices", "Invoices").put("invoices", [
        inv("i1", d8, "999", due=d8 + timedelta(days=30)), inv("i2", d8, "250", due=d8, number="INV-9")])
    plant(client, shop, "csv_sales", "Sales").put("sales", [S("q1", d8, 12, "555", method="mobile_money", reference="QRS1")])
    run(shop, "standalone.unmatched_receipt")
    (f,) = found(shop, "standalone.unmatched_receipt")
    assert D(f.amount) == D("4321.00") and f.severity == "low" and f.period_start == d8
    assert f.summary == "1 payment received on 2026-10-08 worth KES 4,321.00 matches no sale or invoice."
    bank.put("payments", [P("u8", d8, 16, "4321", method="bank", reference="FT104")])       # a second one, same day
    run(shop, "standalone.unmatched_receipt")
    assert D(found(shop, "standalone.unmatched_receipt")[0].amount) == D("8642.00")
    plant(client, shop, "csv_invoices", "More invoices").put("invoices", [inv("i3", d8, "4321", due=d8)])
    assert run(shop, "standalone.unmatched_receipt").resolved == 1


# --------------------------------------------------------------------------- people
def test_a_new_user_in_the_connected_system(client, shop) -> None:  # type: ignore[no-untyped-def]
    p = plant(client, shop, "csv_sales")
    p.put("users", [User("u1", "Newbie Hire", "Cashier", created_at=at(date(2026, 10, 10))),
                    User("u2", "Veteran", "Admin", created_at=at(date(2026, 1, 5))),
                    User("u3", "Unknown Age", "Admin")])
    run(shop, "standalone.new_user")
    (f,) = found(shop, "standalone.new_user")
    assert f.summary == "Newbie Hire was added as a user (Cashier) on 2026-10-10." and f.severity == "low"
    tune(client, shop, "standalone.new_user", days=2)
    assert run(shop, "standalone.new_user").created == 0
    assert len(found(shop, "standalone.new_user")) == 1                              # an event stays until dealt with


# --------------------------------------------------------------------------- the Command Center and coverage
def test_pulse_figures_and_the_coverage_note_follow_what_is_connected(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.command.public import PulseSource
    from ziira.modules.connect.pulse import ConnectPulse

    def figures() -> dict[tuple[str, UUID | None], D]:
        with system(shop) as s:
            return {(f.metric, f.branch_id): D(f.value) for f in ConnectPulse().figures(s, shop["company_id"], D0)}
    assert issubclass(ConnectPulse, PulseSource) and figures() == {}                  # nothing connected: no figures
    cov = client.get(f"{CONNECT}/coverage", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    assert cov["connected"] == {} and all(a["active"] == 0 for a in cov["areas"])
    p = plant(client, shop, "csv_sales")
    p.put("sales", [S("p1", D0, 10, "1000"), S("p2", D0, 11, "500", branch="JUJA"), S("p3", D0, 12, "300", status="voided"),
                    S("p4", D0 - timedelta(days=1), 12, "9999")])
    out = figures()
    assert out[("connect.sales_total", None)] == D("1500") and out[("connect.sales_count", None)] == D("2")
    assert out[("connect.sales_total", shop["branch_id"])] == D("1000") and out[("connect.sales_total", shop["juja"])] == D("500")
    assert not any(m.startswith("connect.payments") for m, _ in out)
    plant(client, shop, "bank_statement", "Bank").put("payments", [P("r1", D0, 10, "700"), P("r2", D0, 11, "40", direction="out")])
    plant(client, shop, "csv_invoices", "Inv").put("invoices", [
        inv("o1", date(2026, 8, 1), "900", due=date(2026, 9, 1), paid="100"), inv("o2", date(2026, 8, 1), "50", due=TODAY + timedelta(days=5))])
    plant(client, shop, "csv_expenses", "Exp").put("expenses", [Expense("e1", at(D0), D("220"), branch_ref="HQ")])
    plant(client, shop, "csv_stock", "Stock").put("stock_movements", [adj("k1", D0, "-2"), adj("k2", D0, "-3", kind="count"),
                                                                       adj("k3", D0, "-1", kind="sale")])
    out = figures()
    assert out[("connect.payments_received", None)] == D("700") and out[("connect.overdue_receivables", None)] == D("800")
    assert out[("connect.expenses_total", None)] == D("220") and out[("connect.stock_adjustments", None)] == D("2")
    cov = client.get(f"{CONNECT}/coverage", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    assert set(cov["connected"]) >= {"sales", "payments", "invoices", "expenses", "stock_movements"}
    areas = {a["area"]: a for a in cov["areas"]}
    cash = {c["code"]: c for c in areas["cash_sales"]["checks"]}
    assert cash["standalone.sale_without_payment"]["active"] is True
    assert areas["books"]["total"] >= 3
    jc = next(c for c in areas["books"]["checks"] if c["code"] == "standalone.manual_journal")
    assert jc["active"] is False and jc["needs"] == ["journal_entries"]
    people = next(c for c in areas["people"]["checks"] if c["code"] == "standalone.new_user")
    assert people["active"] is False and people["needs"] == ["users"]

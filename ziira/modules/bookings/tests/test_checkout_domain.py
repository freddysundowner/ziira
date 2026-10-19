"""Checkout arithmetic: hand-calculated cases and properties (every split adds up exactly)."""

from decimal import Decimal
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.bookings.domain import checkout as co


def line(q: str, price: str, discount: str = "0", credit: str = "0") -> co.Line:
    return co.Line(Decimal(q), Decimal(price), Decimal(discount), Decimal(credit))


def test_a_bill_with_a_line_discount_and_an_order_discount() -> None:
    lines = [line("1", "1000", "100"), line("2", "250")]            # 900 + 500
    t = co.totals(lines, Decimal("140"))
    assert t.subtotal == Decimal("1500")
    assert t.line_discounts == Decimal("100")
    assert t.order_discount == Decimal("140")
    assert t.total == Decimal("1260")
    assert t.shares == (Decimal("90.00"), Decimal("50.00"))                      # 140 in proportion 900:500


def test_a_unit_paid_with_credit_is_not_charged_but_has_a_value() -> None:
    lines = [line("1", "1500", credit="1"), line("1", "600")]
    t = co.totals(lines)
    assert t.total == Decimal("600")
    assert t.credit_value == Decimal("1500")
    assert t.subtotal == Decimal("2100")


def test_part_of_a_quantity_can_be_paid_with_credit() -> None:
    t = co.totals([line("3", "100", credit="2")])
    assert t.total == Decimal("100") and t.credit_value == Decimal("200")


def test_the_order_discount_never_makes_the_bill_negative() -> None:
    assert co.totals([line("1", "100")], Decimal("500")).total == Decimal("0")
    assert co.order_discount_amount([line("1", "100")], "percent", Decimal("10")) == Decimal("10.00")
    assert co.order_discount_amount([line("1", "100")], "amount", Decimal("500")) == Decimal("100")


def test_a_line_discount_cannot_exceed_the_line() -> None:
    assert co.totals([line("1", "100", "250")]).total == Decimal("0")


def test_leftover_cents_go_to_the_largest_remainders() -> None:
    shares = co.spread([Decimal("10"), Decimal("10"), Decimal("10")], Decimal("1.00"))
    assert sum(shares) == Decimal("1.00") and sorted(shares) == [Decimal("0.33"), Decimal("0.33"), Decimal("0.34")]


def test_the_patient_pays_the_copay_and_the_insurer_the_rest() -> None:
    parts = co.split_payer([Decimal("3000"), Decimal("1000")], Decimal("800"))
    assert parts == [(Decimal("600.00"), Decimal("2400.00")), (Decimal("200.00"), Decimal("800.00"))]
    assert co.split_payer([Decimal("100")], Decimal("999")) == [(Decimal("100.00"), Decimal("0.00"))]          # a co-pay above the bill


def test_tax_is_taken_out_of_an_inclusive_amount() -> None:
    assert co.net_of_tax(Decimal("116"), Decimal("16")) == Decimal("100.00")
    assert co.net_of_tax(Decimal("100"), Decimal("0")) == Decimal("100")


def test_the_most_specific_commission_rule_wins() -> None:
    anna, cut = UUID(int=1), UUID(int=2)
    general = co.Rule(UUID(int=10), "service", "percent", Decimal("30"))
    for_cut = co.Rule(UUID(int=11), "service", "percent", Decimal("40"), offer_id=cut)
    for_anna = co.Rule(UUID(int=12), "service", "percent", Decimal("50"), resource_id=anna)
    senior = co.Rule(UUID(int=13), "service", "percent", Decimal("45"), level="Senior")
    rules = [general, for_cut, for_anna, senior]
    assert co.pick_rule(rules, applies_to="service", resource_id=anna, level="Senior", offer_id=cut) == for_anna
    assert co.pick_rule(rules, applies_to="service", resource_id=UUID(int=3), level="Senior", offer_id=cut) == for_cut
    assert co.pick_rule(rules, applies_to="service", resource_id=UUID(int=3), level="senior", offer_id=UUID(int=9)) == senior
    assert co.pick_rule(rules, applies_to="service", resource_id=UUID(int=3), level=None) == general
    assert co.pick_rule(rules, applies_to="product", resource_id=anna, level=None) is None


def test_commission_is_a_percent_or_a_fixed_amount() -> None:
    pct = co.Rule(UUID(int=1), "service", "percent", Decimal("35"))
    fixed = co.Rule(UUID(int=2), "product", "fixed", Decimal("50"))
    assert co.commission_amount(pct, Decimal("1000")) == Decimal("350.00")
    assert co.commission_amount(fixed, Decimal("999"), Decimal("2")) == Decimal("100.00")
    assert co.commission_amount(pct, Decimal("0")) == Decimal("0")


def test_fees_and_deposits_follow_the_business_percents() -> None:
    assert co.fee_due(True, False, Decimal("50"), Decimal("100"), Decimal("1000")) == Decimal("500.00")
    assert co.fee_due(True, True, Decimal("50"), Decimal("100"), Decimal("1000")) == Decimal("1000.00")
    assert co.fee_due(False, False, Decimal("50"), Decimal("100"), Decimal("1000")) == Decimal("0")
    assert co.deposit_due(Decimal("1000"), Decimal("0"), Decimal("25")) == Decimal("250.00")
    assert co.deposit_due(Decimal("1000"), Decimal("300"), Decimal("25")) == Decimal("300.00")
    assert co.deposit_due(Decimal("100"), Decimal("500"), Decimal("0")) == Decimal("100")


money = st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"), places=2)
qty = st.decimals(min_value=Decimal("0.5"), max_value=Decimal("10"), places=1)


@settings(max_examples=150, deadline=None)
@given(amounts=st.lists(money, min_size=1, max_size=8), total=money)
def test_a_spread_always_adds_up_and_never_exceeds_a_line(amounts: list[Decimal], total: Decimal) -> None:
    shares = co.spread(amounts, total)
    assert sum(shares) == min(total, sum(amounts))
    assert all(0 <= s <= a for s, a in zip(shares, amounts, strict=True))


@settings(max_examples=150, deadline=None)
@given(amounts=st.lists(money, min_size=1, max_size=8), copay=money)
def test_patient_and_payer_always_add_up_to_each_line(amounts: list[Decimal], copay: Decimal) -> None:
    parts = co.split_payer(amounts, copay)
    assert all(p + q == a for (p, q), a in zip(parts, amounts, strict=True))
    assert sum(p for p, _ in parts) == min(copay, sum(amounts))


@settings(max_examples=150, deadline=None)
@given(specs=st.lists(st.tuples(qty, money, money), min_size=1, max_size=6), order=money)
def test_the_invoice_lines_add_up_to_the_total(specs: list[tuple[Decimal, Decimal, Decimal]], order: Decimal) -> None:
    lines = [co.Line(q, p, d) for q, p, d in specs]
    t = co.totals(lines, order)
    discounts = co.invoice_discounts(lines, order)
    billed = sum((co.cents(x.quantity * x.unit_price) - d for x, d in zip(lines, discounts, strict=True)), Decimal(0))
    assert billed == t.total
    assert t.total >= 0

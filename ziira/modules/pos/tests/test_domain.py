"""POS business rules: line money, payments and change, refunds in parts, numbering."""

from decimal import Decimal as D  # noqa: N817

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.pos.domain import sales as rules
from ziira.sdk import ValidationFailed

VAT = D("16")


def test_a_lines_vat_is_taken_out_of_the_price() -> None:
    a = rules.price_line(D("1"), D("116.00"), D("0"), VAT)
    assert (a.before_discount, a.gross, a.tax, a.net) == (D("116.00"), D("116.00"), D("16.00"), D("100.00"))
    b = rules.price_line(D("3"), D("116.00"), D("0"), VAT)
    assert (b.gross, b.tax, b.net) == (D("348.00"), D("48.00"), D("300.00"))
    zero = rules.price_line(D("2"), D("100.00"), D("0"), D("0"))                # a zero-rated product
    assert zero.tax == 0 and zero.net == 200


def test_a_discount_comes_off_before_the_vat() -> None:
    a = rules.price_line(D("2"), D("116.00"), D("32.00"), VAT)
    assert (a.before_discount, a.discount, a.gross, a.tax, a.net) == (D("232.00"), D("32.00"), D("200.00"),
                                                                       D("27.59"), D("172.41"))


def test_quantities_prices_and_discounts_are_limited() -> None:
    for quantity in (D("0"), D("-1"), D("0.00001"), D("1000001")):
        with pytest.raises(ValidationFailed):
            rules.price_line(quantity, D("10"), D("0"), VAT)
    for price in (D("-1"), D("10.005"), D("100000001")):
        with pytest.raises(ValidationFailed):
            rules.price_line(D("1"), price, D("0"), VAT)
    with pytest.raises(ValidationFailed, match="more than the line"):
        rules.price_line(D("1"), D("10"), D("10.01"), VAT)
    assert rules.price_line(D("1"), D("10"), D("10"), VAT).gross == 0                # a free line is fine on its own


def test_cash_change_is_given_only_on_cash() -> None:
    legs = rules.settle(D("116"), [("cash", D("200"))])
    assert [(x.method, x.amount, x.change) for x in legs] == [("cash", D("116"), D("84"))]
    split = rules.settle(D("500"), [("mpesa", D("300")), ("cash", D("1000"))])
    assert [(x.method, x.amount, x.change) for x in split] == [("mpesa", D("300"), D("0")), ("cash", D("200"),
                                                                                           D("800"))]
    exact = rules.settle(D("500"), [("cash", D("200")), ("card", D("300"))])
    assert {x.method: x.amount for x in exact} == {"card": D("300"), "cash": D("200")}
    assert sum(x.change for x in exact) == 0


def test_payments_must_cover_the_total_exactly() -> None:
    with pytest.raises(ValidationFailed, match="short"):
        rules.settle(D("116"), [("cash", D("100"))])
    with pytest.raises(ValidationFailed, match="more than is still owed"):
        rules.settle(D("116"), [("mpesa", D("200"))])
    with pytest.raises(ValidationFailed, match="more than is still owed"):
        rules.settle(D("116"), [("mpesa", D("100")), ("card", D("100"))])
    for bad in ([], [("credit", D("116"))], [("cash", D("0"))], [("cash", D("-5"))], [("cash", D("1.005"))]):
        with pytest.raises(ValidationFailed):
            rules.settle(D("116"), bad)
    with pytest.raises(ValidationFailed):
        rules.settle(D("0"), [("cash", D("1"))])


@given(total=st.decimals(min_value="0.01", max_value="1000000", places=2),
       extra=st.decimals(min_value="0", max_value="5000", places=2),
       share=st.decimals(min_value="0", max_value="1", places=2))
def test_whatever_is_handed_over_the_applied_money_equals_the_total(total: D, extra: D, share: D) -> None:
    mpesa = (total * share).quantize(D("0.01"))
    offered = ([("mpesa", mpesa)] if mpesa > 0 else []) + [("cash", total - mpesa + extra)] \
        if total - mpesa + extra > 0 else [("mpesa", mpesa)]
    legs = rules.settle(total, offered)
    assert sum(x.amount for x in legs) == total
    assert all(x.change == 0 for x in legs if x.method != "cash")
    assert sum(x.change for x in legs) == (sum(a for _, a in offered) - total)


@given(sold=st.integers(1, 40), price=st.decimals(min_value="0.01", max_value="50000", places=2),
       discount_pct=st.integers(0, 100), parts=st.lists(st.integers(1, 40), min_size=1, max_size=10))
def test_returning_a_line_in_parts_gives_back_exactly_what_it_sold_for(
        sold: int, price: D, discount_pct: int, parts: list[int]) -> None:
    quantity = D(sold)
    before = rules.cents(quantity * price)
    discount = rules.cents(before * discount_pct / 100)
    amounts = rules.price_line(quantity, price, discount, VAT)
    # take units back in the given parts until all are back
    remaining, back_before = sold, D(0)
    gross_sum, tax_sum = D(0), D(0)
    for part in parts:
        take = min(part, remaining)
        if take == 0:
            break
        gross, tax = rules.return_amounts(amounts.gross, amounts.tax, quantity, back_before, D(take))
        assert gross >= 0 and tax >= 0
        gross_sum, tax_sum, back_before, remaining = gross_sum + gross, tax_sum + tax, back_before + take, remaining - take
    if remaining:
        gross, tax = rules.return_amounts(amounts.gross, amounts.tax, quantity, back_before, D(remaining))
        gross_sum, tax_sum = gross_sum + gross, tax_sum + tax
    assert (gross_sum, tax_sum) == (amounts.gross, amounts.tax)


def test_a_line_cannot_be_returned_more_than_it_sold() -> None:
    with pytest.raises(ValidationFailed, match="Only 1"):
        rules.return_amounts(D("232"), D("32"), D("2"), D("1"), D("2"))
    with pytest.raises(ValidationFailed):
        rules.return_amounts(D("232"), D("32"), D("2"), D("0"), D("0"))


def test_drawer_arithmetic_and_numbers() -> None:
    assert rules.till_expected_cash(D("1000"), D("350")) == D("1350")
    assert rules.till_expected_cash(D("1000"), D("-200")) == D("800")
    prefix = rules.device_prefix("HQ", "D1")
    assert prefix == "POS-HQ-D1" and rules.server_number(prefix, 42) == "POS-HQ-D1-000042"
    assert rules.check_offline_number("pos-hq-d1-l000123", prefix) == "POS-HQ-D1-L000123"
    for bad in ("POS-HQ-D1-000123", "POS-HQ-D2-L000123", "POS-HQ-D1-L", "x", "POS-HQ-D1-L12;DROP", ""):
        with pytest.raises(ValidationFailed):
            rules.check_offline_number(bad, prefix)

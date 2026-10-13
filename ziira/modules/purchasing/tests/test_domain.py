"""Purchasing rules: costs and VAT, the three-way match, order status, ageing, validation."""

from datetime import date
from decimal import Decimal as D  # noqa: N817

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.purchasing.domain import rules
from ziira.sdk import ValidationFailed


def test_costs_exclude_vat_and_vat_is_added_on_top() -> None:
    a = rules.line_amounts(D("10"), D("50.00"), D("16"))
    assert (a.net, a.tax, a.gross) == (D("500.00"), D("80.00"), D("580.00"))
    odd = rules.line_amounts(D("3"), D("33.333333"), D("16"))
    assert odd.net == D("100.00") and odd.tax == D("16.00")
    assert rules.line_amounts(D("2"), D("10"), D("0")).tax == 0


def test_quantities_and_costs_are_limited() -> None:
    for q in (D("0"), D("-1"), D("0.00001"), D("100000000")):
        with pytest.raises(ValidationFailed):
            rules.line_amounts(q, D("1"), D("16"))
    for c in (D("-1"), D("0.0000001"), D("100000001")):
        with pytest.raises(ValidationFailed):
            rules.line_amounts(D("1"), c, D("16"))


@given(q=st.decimals(min_value="0.0001", max_value="1000", places=4), c=st.decimals(min_value="0", max_value="9999", places=6),
       r=st.sampled_from([D("0"), D("8"), D("16")]))
def test_a_lines_gross_is_net_plus_tax_to_the_cent(q: D, c: D, r: D) -> None:
    a = rules.line_amounts(q, c, r)
    assert a.gross == a.net + a.tax and a.net == a.net.quantize(D("0.01")) and a.tax >= 0
    assert abs(a.tax - a.net * r / 100) <= D("0.005")


def test_an_order_is_received_when_every_line_is() -> None:
    assert rules.order_status([(D("10"), D("0"))], "approved") == "approved"
    assert rules.order_status([(D("10"), D("4")), (D("5"), D("5"))], "approved") == "part_received"
    assert rules.order_status([(D("10"), D("10")), (D("5"), D("6"))], "sent") == "received"
    assert rules.order_status([(D("10"), D("10"))], "cancelled") == "cancelled"
    assert rules.order_status([(D("10"), D("3"))], "closed") == "closed"


def test_receiving_more_than_was_ordered_is_refused() -> None:
    rules.check_receipt_quantity(D("10"), D("4"), D("6"))
    with pytest.raises(ValidationFailed, match="Only 6 more"):
        rules.check_receipt_quantity(D("10"), D("4"), D("7"))


def test_the_three_way_match() -> None:
    ok = rules.match_problems(label="Cement", billed_qty=D("10"), billed_cost=D("50"), received_qty=D("10"),
                              already_billed=D("0"), received_cost=D("50"), ordered_cost=D("50"),
                              tolerance_percent=D("2"))
    assert ok == []
    within = rules.match_problems(label="Cement", billed_qty=D("10"), billed_cost=D("50.90"), received_qty=D("10"),
                                  already_billed=D("0"), received_cost=D("50"), ordered_cost=D("50"),
                                  tolerance_percent=D("2"))
    assert within == []                                                           # 1.8% off
    dear = rules.match_problems(label="Cement", billed_qty=D("10"), billed_cost=D("52"), received_qty=D("10"),
                                already_billed=D("0"), received_cost=D("50"), ordered_cost=D("50"),
                                tolerance_percent=D("2"))
    assert len(dear) == 1 and "4.00% away from the order" in dear[0]
    more = rules.match_problems(label="Cement", billed_qty=D("8"), billed_cost=D("50"), received_qty=D("10"),
                                already_billed=D("5"), received_cost=D("50"), ordered_cost=None,
                                tolerance_percent=D("2"))
    assert len(more) == 1 and "only 5 of the 10" in more[0]
    both = rules.match_problems(label="X", billed_qty=D("8"), billed_cost=D("60"), received_qty=D("10"),
                                already_billed=D("5"), received_cost=D("50"), ordered_cost=None,
                                tolerance_percent=D("0"))
    assert len(both) == 2
    free = rules.match_problems(label="X", billed_qty=D("1"), billed_cost=D("0"), received_qty=D("1"),
                                already_billed=D("0"), received_cost=D("0"), ordered_cost=D("0"),
                                tolerance_percent=D("2"))
    assert free == []


def test_ageing_buckets() -> None:
    today = date(2026, 10, 31)
    expected = {date(2026, 11, 5): "not_due", date(2026, 10, 31): "not_due", date(2026, 10, 30): "1_30",
                date(2026, 10, 1): "1_30", date(2026, 9, 30): "31_60", date(2026, 8, 31): "61_90",
                date(2026, 8, 2): "61_90", date(2026, 8, 1): "over_90", date(2026, 7, 31): "over_90"}
    for due, bucket in expected.items():
        assert rules.ageing_bucket(due, today) == bucket, due


def test_validation_of_codes_pins_numbers_and_accounts() -> None:
    assert rules.normalise_code(" total01 ") == "TOTAL01"
    for bad in ("", "a b", "x" * 21, "-x", "a;b"):
        with pytest.raises(ValidationFailed):
            rules.normalise_code(bad)
    assert rules.check_kra_pin("p051234567a") == "P051234567A" and rules.check_kra_pin(" ") is None
    for bad in ("12345", "P05123456A", "X051234567A", "P051234567"):
        with pytest.raises(ValidationFailed):
            rules.check_kra_pin(bad)
    assert rules.check_invoice_no(" INV/2026-001 ") == "INV/2026-001"
    for bad in ("", "  ", "x" * 61, "<script>"):
        with pytest.raises(ValidationFailed):
            rules.check_invoice_no(bad)
    for days in (-1, 366):
        with pytest.raises(ValidationFailed):
            rules.check_terms(days)
    assert rules.mask_account("0123 4567 8901") == "********8901"
    assert rules.check_account_number("bank", "0123-4567 89") == "0123456789"
    assert rules.check_account_number("mpesa", "0712 345 678") == "0712345678"
    for method, bad in (("bank", "12"), ("bank", "ab;c"), ("mpesa", "12345"), ("mpesa", "0212345678")):
        with pytest.raises(ValidationFailed):
            rules.check_account_number(method, bad)


def test_numbers_in_messages_have_no_trailing_zeros() -> None:
    assert rules.plain(D("6.0000")) == "6" and rules.plain(D("2.50")) == "2.5" and rules.plain(D("100")) == "100"
    assert rules.plain(D("0.0500")) == "0.05" and rules.plain(D("1234.5678")) == "1234.5678"
    with pytest.raises(ValidationFailed, match="Only 6 more"):
        rules.check_receipt_quantity(D("10.0000"), D("4.0000"), D("7"))

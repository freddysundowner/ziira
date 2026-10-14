"""Rules behind Purchasing's Intelligence checks."""

from datetime import date
from decimal import Decimal as D  # noqa: N817
from uuid import uuid4

from ziira.modules.purchasing.domain.watch import (
    BillStub,
    PaymentStub,
    duplicate_bills,
    duplicate_payments,
    normalise_reference,
    price_rise,
)


def test_price_rise_compares_the_latest_with_the_average_of_the_earlier_ones() -> None:
    latest, average, pct = price_rise([D(100), D(110), D(132)], 2) or (0, 0, 0)
    assert (latest, average, pct) == (D(132), D(105), D(132 - 105) / D(105) * 100)


def test_price_rise_needs_enough_history_and_a_positive_average() -> None:
    assert price_rise([D(100), D(150)], 2) is None
    assert price_rise([D(0), D(0), D(5)], 2) is None
    assert price_rise([D(5)], 1) is None


def test_references_compare_without_punctuation_or_case() -> None:
    assert normalise_reference(" inv-001 ") == normalise_reference("INV 001") == "INV001"
    assert normalise_reference(None) == ""


def test_duplicate_bills_by_number_or_by_amount_and_date() -> None:
    s, other = uuid4(), uuid4()
    a = BillStub(uuid4(), s, "INV-1", date(2026, 10, 1), D(500))
    b = BillStub(uuid4(), s, "inv 1", date(2026, 10, 20), D(700))
    c = BillStub(uuid4(), s, "X9", date(2026, 10, 3), D(500))
    d = BillStub(uuid4(), other, "INV-1", date(2026, 10, 1), D(500))
    e = BillStub(uuid4(), s, "Z", date(2026, 10, 15), D(500))
    found = {(x.id, y.id): why for x, y, why in duplicate_bills([a, b, c, d, e], 7)}
    assert found == {(a.id, b.id): "the same supplier invoice number",
                     (a.id, c.id): "the same amount within days of each other"}


def test_duplicate_payments_by_reference_or_amount_and_date() -> None:
    s = uuid4()
    p1 = PaymentStub(uuid4(), uuid4(), s, "PAY-1", date(2026, 10, 1), D(100), "REF1")
    p2 = PaymentStub(uuid4(), uuid4(), s, "PAY-2", date(2026, 10, 2), D(100), None)
    p3 = PaymentStub(uuid4(), uuid4(), s, "PAY-3", date(2026, 10, 30), D(250), "ref-1")
    found = {(x.number, y.number): why for x, y, why in duplicate_payments([p1, p2, p3], 3)}
    assert found == {("PAY-1", "PAY-2"): "the same amount within days of each other",
                     ("PAY-1", "PAY-3"): "the same payment reference"}

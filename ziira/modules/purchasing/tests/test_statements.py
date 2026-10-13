"""Reading a supplier's statement: dates, amounts, kinds, references and csv."""

from datetime import date
from decimal import Decimal as D  # noqa: N817

import pytest

from ziira.modules.purchasing.domain import statements as rules
from ziira.sdk import ValidationFailed


def test_references_are_compared_loosely() -> None:
    assert rules.normalise_reference("INV/2026-001") == rules.normalise_reference(" inv 2026 001 ") == "INV2026001"
    assert rules.normalise_reference("a.b_c") == "ABC"


def test_dates_amounts_and_kinds() -> None:
    assert rules.parse_day("2026-10-31") == date(2026, 10, 31) and rules.parse_day("31/10/2026") == date(2026, 10, 31)
    assert rules.parse_day("31-10-2026") == date(2026, 10, 31) and rules.parse_day("31.10.2026") == date(2026, 10, 31)
    for bad in ("", "tomorrow", "2026-13-01", "32/01/2026"):
        with pytest.raises(ValidationFailed):
            rules.parse_day(bad)
    assert rules.parse_amount("KES 1,234.50") == D("1234.50") and rules.parse_amount("(500.00)") == D("500.00")
    assert rules.parse_amount("10") == D("10")
    for bad in ("", "abc", "0", "-5", "10.005", "NaN", "1e20", "99999999999"):
        with pytest.raises(ValidationFailed):
            rules.parse_amount(bad)
    assert rules.parse_kind("Credit Note") == "credit" and rules.parse_kind("INV") == "invoice"
    assert rules.parse_kind("receipt") == "payment"
    with pytest.raises(ValidationFailed):
        rules.parse_kind("gift")
    assert rules.effect("invoice", D("10")) == 10 and rules.effect("credit", D("10")) == -10
    assert rules.effect("payment", D("10")) == -10


def test_csv_with_and_without_a_header() -> None:
    with_header = rules.parse_csv("Amount,Date,Kind,Reference\n1160.00,2026-10-01,invoice,INV-9\n"
                                  "500,05/10/2026,payment,EFT-1\n\n")
    assert [(x.day, x.reference, x.kind, x.amount) for x in with_header] == [
        (date(2026, 10, 1), "INV-9", "invoice", D("1160.00")), (date(2026, 10, 5), "EFT-1", "payment", D("500"))]
    plain = rules.parse_csv("2026-10-01,INV-9,invoice,1160.00")
    assert plain[0].reference == "INV-9"
    for bad in ("", "  \n ", "2026-10-01,INV-9,invoice", "2026-10-01,INV-9,gift,10", "oops,INV-9,invoice,10",
                "2026-10-01,INV-9,invoice,ten", "2026-10-01,,invoice,10"):
        with pytest.raises(ValidationFailed):
            rules.parse_csv(bad)
    with pytest.raises(ValidationFailed, match="Line 2"):
        rules.parse_csv("2026-10-01,A,invoice,10\n2026-10-02,B,invoice,x")
    with pytest.raises(ValidationFailed, match="at most"):
        rules.parse_csv("\n".join(f"2026-10-01,A{i},invoice,10" for i in range(2001)))

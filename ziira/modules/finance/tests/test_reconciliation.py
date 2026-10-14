"""Reading statements and matching them to the ledger: pure rules."""

from datetime import date, timedelta
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.finance.domain import reconciliation as r
from ziira.sdk import ValidationFailed

D = date(2026, 10, 10)


def test_csv_with_a_signed_amount() -> None:
    items = r.parse_csv("date,reference,description,amount\n2026-10-02,CAP1,Capital,\"5,000.00\"\n"
                        "03/10/2026,CHG,Bank charge,(50.00)\n")
    assert [(i.day, i.reference, i.amount) for i in items] == [(date(2026, 10, 2), "CAP1", Dec(5000)),
                                                               (date(2026, 10, 3), "CHG", Dec(-50))]


def test_csv_with_money_in_and_out_columns() -> None:
    items = r.parse_csv("Date,Reference,Details,Paid In,Withdrawn\n2026-10-02,A1,Deposit,100.00,\n"
                        "2026-10-03,A2,Cheque,,40.50\n")
    assert [i.amount for i in items] == [Dec(100), Dec("-40.50")] and items[1].description == "Cheque"


def test_csv_without_a_header_is_date_reference_description_amount() -> None:
    items = r.parse_csv("2026-10-02,R1,Rent,-800\n2026-10-03,R2,Sale,1200.00")
    assert [i.amount for i in items] == [Dec(-800), Dec(1200)] and items[0].reference == "R1"


@pytest.mark.parametrize("text", ["", "date,reference,amount\n2026-10-02,A,abc", "2026-13-45,A,x,10",
                                  "2026-10-02,A,x,0", "2026-10-02,A,x,10.555", "2026-10-02,A,x,1e30",
                                  "date,amount\n2026-10-02,NaN", "2026-10-02,A,x"])
def test_bad_csv_is_refused_with_the_line_number(text: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        r.parse_csv(text)
    assert error.value.message


def test_a_bad_line_names_its_number() -> None:
    with pytest.raises(ValidationFailed) as error:
        r.parse_csv("2026-10-02,A,x,10\n2026-10-03,B,x,oops")
    assert "Line 2" in error.value.message
    with pytest.raises(ValidationFailed):
        r.parse_csv("\n".join(f"2026-10-02,A{i},x,1" for i in range(r.MAX_LINES + 1)))


def ledger(amount: str, days: int = 0, number: str = "GEN-1", description: str = "") -> r.LedgerItem:
    return r.LedgerItem(uuid4(), D + timedelta(days=days), number, description, Dec(amount))


def line(amount: str, days: int = 0, reference: str = "X") -> r.StatementItem:
    return r.StatementItem(D + timedelta(days=days), reference, "", Dec(amount))


def test_matches_are_by_amount_then_reference_then_date() -> None:
    near, far = ledger("500", 1), ledger("500", 4)
    out = r.suggest_matches([line("500", 0)], [far, near])
    assert [s.line_id for s in out] == [near.line_id] and "1 day" in out[0].reason
    by_ref = ledger("500", 4, description="Payment REF12345")
    pick = r.suggest_matches([line("500", 0, "ref-12345")], [near, by_ref])
    assert [s.line_id for s in pick] == [by_ref.line_id] and pick[0].reason == "Same reference and amount"
    assert r.suggest_matches([line("500", 0)], [ledger("500", 6)]) == []                  # outside the window
    assert r.suggest_matches([line("500", 0)], [ledger("-500", 0)]) == []                 # money in is not money out
    assert r.suggest_matches([line("500", 0, "AB")], [ledger("500", 3, description="AB")])[0].reason.startswith("Same amount")


@given(st.lists(st.tuples(st.integers(-5, 5), st.integers(-3, 3)), max_size=15),
       st.lists(st.tuples(st.integers(-5, 5), st.integers(-3, 3)), max_size=15))
def test_every_ledger_line_is_used_at_most_once(statement, books) -> None:  # type: ignore[no-untyped-def]
    items = [line(str(a * 100 or 1), d, f"S{i}") for i, (a, d) in enumerate(statement)]
    entries = [ledger(str(a * 100 or 1), d, f"GEN-{i}") for i, (a, d) in enumerate(books)]
    out = r.suggest_matches(items, entries)
    assert len({s.line_id for s in out}) == len(out) and len({s.item_index for s in out}) == len(out)
    by_id = {e.line_id: e for e in entries}
    for s in out:
        assert items[s.item_index].amount == by_id[s.line_id].amount
        assert abs((items[s.item_index].day - by_id[s.line_id].day).days) <= r.WINDOW_DAYS or "reference" in s.reason


def test_difference() -> None:
    assert r.difference(Dec(5000), Dec(4200)) == 800 and r.difference(Dec(-10), Dec(-10)) == 0

"""Rules for opening balances: which accounts take one, and how the entry is made to balance."""

from decimal import Decimal as Dec  # noqa: N817

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.finance.domain import opening
from ziira.sdk import ValidationFailed


def test_only_balance_sheet_accounts_take_an_opening_balance() -> None:
    assert opening.classify("asset", "bank", False) == opening.PLAIN
    assert opening.classify("equity", "equity", False) == opening.PLAIN
    for kind in ("income", "expense"):
        with pytest.raises(ValidationFailed, match="balance sheet accounts"):
            opening.classify(kind, "sales", False)


def test_control_accounts_are_checked_against_their_records_or_refused() -> None:
    assert opening.classify("asset", "receivable", True) == opening.RECEIVABLE
    assert opening.classify("liability", "payable", True) == opening.PAYABLE
    assert opening.classify("asset", "inventory", True) == opening.INVENTORY
    for subtype in ("mobile_money_clearing", "grni", "transfer_clearing", "payroll_net", "inventory_in_transit"):
        with pytest.raises(ValidationFailed, match="kept by its own records"):
            opening.classify("asset", subtype, True)


def test_the_equity_lines_cancel_the_controlled_balances_and_carry_only_the_difference() -> None:
    # plain accounts net a debit of 1,599.75, the control lines a credit of 1,599.75: the file balances
    pos = opening.position(Dec("1599.75"), Dec("-1599.75"))
    assert pos.difference == 0
    assert opening.equity_lines(pos) == [("credit", Dec("1599.75"), opening.equity_lines(pos)[0][2])]
    # a file out by 100.00 more debits than credits: the difference is credited too
    out = opening.position(Dec("1000"), Dec("0"))
    assert [(side, amount) for side, amount, _ in opening.equity_lines(out)] == [("credit", Dec("1000"))]
    assert out.difference == Dec("1000")


@given(plain=st.integers(-10**9, 10**9), controlled=st.integers(-10**9, 10**9))
def test_the_entry_always_nets_to_zero(plain: int, controlled: int) -> None:
    pos = opening.position(Dec(plain) / 100, Dec(controlled) / 100)
    equity = sum((a if side == "debit" else -a for side, a, _ in opening.equity_lines(pos)), Dec(0))
    assert Dec(plain) / 100 + equity == 0
    assert pos.difference == (Dec(plain) + Dec(controlled)) / 100


def test_mismatches_name_every_party_that_differs() -> None:
    file_net = {"a": Dec("10"), "b": Dec("5")}
    books = {"a": Dec("10"), "b": Dec("6"), "c": Dec("1")}
    assert opening.mismatches(file_net, books) == [("b", Dec("5"), Dec("6")), ("c", Dec("0"), Dec("1"))]

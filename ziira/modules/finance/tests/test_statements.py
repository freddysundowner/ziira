"""Statements and CSV are pure arithmetic over account totals; these rules must hold for any books."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.finance.domain import statements as s
from ziira.modules.finance.domain.exports import JournalRow, journal_csv, safe, to_csv

TYPES = ["asset", "liability", "equity", "income", "expense"]
SUBTYPES = [None, "cogs", "shrinkage", "rent", "sales", "vat_output", "vat_input", "cash", "bank"]
money = st.decimals(min_value=0, max_value=100000, places=2)


def total(kind: str, debit: Dec, credit: Dec, subtype: str | None = None, code: str = "1") -> s.AccountTotal:
    return s.AccountTotal(uuid4(), code, f"Account {code}", kind, subtype, debit, credit)


def test_profit_and_loss_by_hand() -> None:
    pnl = s.profit_and_loss([
        total("income", Dec(0), Dec(1000), "sales", "4000"), total("income", Dec(100), Dec(0), "sales_returns", "4100"),
        total("expense", Dec(400), Dec(0), "cogs", "5000"), total("expense", Dec(50), Dec(0), "shrinkage", "5100"),
        total("expense", Dec(120), Dec(20), "rent", "6000"), total("asset", Dec(9), Dec(0), "cash", "1010")])
    assert pnl.total_income == 900 - 0 and pnl.total_income == Dec(900)         # 1000 sales less 100 returns shown negative
    assert [x.amount for x in pnl.income] == [Dec(1000), Dec(-100)]
    assert pnl.total_cost_of_sales == 450 and pnl.gross_profit == 450
    assert pnl.total_expenses == 100 and pnl.net_profit == 350                  # an asset never reaches the P&L


@given(st.lists(st.tuples(st.sampled_from(TYPES), money, money, st.sampled_from(SUBTYPES)), max_size=25))
def test_the_balance_sheet_balances_whenever_the_books_do(rows) -> None:  # type: ignore[no-untyped-def]
    totals = [total(kind, d, c, sub, str(i)) for i, (kind, d, c, sub) in enumerate(rows)]
    gap = sum((t.debit for t in totals), Dec(0)) - sum((t.credit for t in totals), Dec(0))
    plug = total("asset", max(-gap, Dec(0)), max(gap, Dec(0)), None, "9999")      # a balanced book: debits = credits
    sheet = s.balance_sheet([*totals, plug])
    assert sheet.balanced
    pnl = s.profit_and_loss([*totals, plug])
    assert sheet.accumulated_profit == pnl.net_profit
    assert pnl.net_profit == pnl.total_income - pnl.total_cost_of_sales - pnl.total_expenses


@given(money, money, st.dictionaries(st.sampled_from([None, "sale", "supplier_payment", "expense", "other"]),
                                     st.decimals(min_value=-5000, max_value=5000, places=2), max_size=5))
def test_cash_flow_reconciles_when_the_movements_explain_the_change(opening, extra, moves) -> None:  # type: ignore[no-untyped-def]
    closing = opening + sum(moves.values(), Dec(0))
    flow = s.cash_flow(opening, closing, moves)
    assert flow.reconciles and flow.net_movement == closing - opening
    assert not s.cash_flow(opening, closing + Dec("0.01"), moves).reconciles
    assert all(m != 0 for _, m in flow.movements) and extra >= 0


def test_vat_summary() -> None:
    vat = s.vat_summary([total("income", Dec(0), Dec(1000), "sales"), total("liability", Dec(0), Dec(160), "vat_output"),
                         total("asset", Dec(48), Dec(0), "vat_input")], {"sale": Dec(160)}, {None: Dec(48)})
    assert vat.sales_net == 1000 and vat.output_vat == 160 and vat.input_vat == 48 and vat.net_payable == 112
    assert vat.output_by_source == [("Sales", Dec(160))] and vat.input_by_source == [("Manual journals", Dec(48))]
    refund = s.vat_summary([total("asset", Dec(80), Dec(0), "vat_input")], {}, {})
    assert refund.net_payable == -80


def test_cells_are_defused_against_spreadsheet_formulas() -> None:
    for bad in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tx", "\rx"):
        assert safe(bad) == "'" + bad
    assert safe("Rent") == "Rent" and safe(None) == "" and safe(Dec("-5.50")) == "-5.50"      # numbers stay numbers
    text = to_csv(["a", "b"], [["=HYPERLINK(\"x\")", Dec("1.00")], ["has,comma", 'has "quote"']])
    assert text.splitlines()[0] == "a,b" and "'=HYPERLINK" in text and '"has,comma"' in text and '"has ""quote"""' in text


def test_journal_layouts() -> None:
    from datetime import date

    rows = [JournalRow("GEN-1", date(2026, 10, 5), None, "Rent", "6000", "Rent", "HQ", Dec(300), Dec(0), "7100",
                       "Office rent"),
            JournalRow("GEN-1", date(2026, 10, 5), None, "Rent", "1020", "Bank", None, Dec(0), Dec(300))]
    generic = journal_csv(rows, "generic").splitlines()
    assert generic[0].startswith("Entry,Date,Source") and generic[1].startswith("GEN-1,2026-10-05,manual,6000,Rent,HQ")
    qb = journal_csv(rows, "quickbooks").splitlines()
    assert qb[0].startswith("*JournalNo,*JournalDate,*AccountName") and qb[1].startswith("GEN-1,05/10/2026,Office rent,300")
    assert qb[2].startswith("GEN-1,05/10/2026,1020 Bank,,300")
    sage = journal_csv(rows, "sage").splitlines()
    assert sage[1].startswith("JD,,7100,,05/10/2026,GEN-1") and sage[2].startswith("JC,,1020,,05/10/2026,GEN-1")
    import pytest

    with pytest.raises(ValueError):
        journal_csv(rows, "xero")

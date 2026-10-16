"""The Kenya pack's data files read, merge and parse with the units' own rules (so a typo fails here, not in a business)."""

from datetime import date
from decimal import Decimal

from ziira.modules.finance.public import check_chart_template
from ziira.modules.people.public import check_statutory_tables
from ziira.modules.products.public import check_tax_codes
from ziira.plugins.pack_ke.hooks import KenyaChart, KenyaPayrollTables, KenyaTaxCodes


def test_the_tax_codes_are_valid_and_the_standard_rate_is_there() -> None:
    rows = KenyaTaxCodes().tax_codes()
    check_tax_codes(rows)
    by_code = {r.code: r for r in rows}
    assert by_code["VAT16"].vat_rate == Decimal("16") and by_code["VAT16"].authority_code == "B"
    assert {r.vat_rate for r in rows if r.code in ("ZERO", "EXEMPT", "NONVAT")} == {Decimal(0)}


def test_the_chart_merges_with_the_general_chart() -> None:
    chart = KenyaChart()
    total = check_chart_template(chart)
    assert total > 30 and {a.code for a in chart.accounts()} >= {"1030", "2311", "2312", "2313", "2314"}


def test_the_payroll_tables_are_readable_unverified_examples() -> None:
    tables = KenyaPayrollTables().tables()
    check_statutory_tables(tables)
    assert {t.code for t in tables} == {"NSSF", "SHIF", "AHL", "PAYE"}
    assert all(t.effective_from == date(2025, 1, 1) for t in tables)                    # a placeholder date
    assert all("verify" in t.source_reference.lower() and "example" in t.source_reference.lower() for t in tables)
    paye = next(t for t in tables if t.code == "PAYE").definition["employee"]
    assert paye["bands"][-1] == {"rate": "0.35"} and len(paye["bands"]) == 5            # the last band has no upper limit

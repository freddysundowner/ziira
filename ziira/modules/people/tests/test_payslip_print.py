"""Payslip layouts: text fits the paper, HTML escapes everything a user wrote."""

from decimal import Decimal as D  # noqa: N817

import pytest

from ziira.modules.people.domain.payslip_print import PayslipDocument, render_html, render_text

DOC = PayslipDocument(
    header=["Acme <Ltd> & Sons Trading Company Limited"], title="Payslip", period="2026-09-01 to 2026-09-30",
    employee=[("Name", "<script>alert(1)</script> Wanjiku Mwangi-Kariuki of Nairobi County"), ("No", "E1")],
    earnings=[("Basic pay", D("1234567.5")), ("A very long allowance name that will not fit on a narrow strip", D("5"))],
    benefits=[("Car", D("100"))], deductions=[("Tax", D("-0.5"))],
    totals=[("Gross pay", D("1234572.50")), ("NET PAY", D("1.00"))], notes=["Note <b>x</b>"], copy=True)


@pytest.mark.parametrize("width", [32, 40, 48, 80])
def test_text_fits_the_paper(width: int) -> None:
    text = render_text(DOC, width)
    assert all(len(row) <= width for row in text.splitlines()) and "NET PAY" in text and "*** COPY ***" in text
    assert "1,234,567.50" in text


def test_a_width_that_no_printer_has_is_refused() -> None:
    with pytest.raises(ValueError):
        render_text(DOC, 10)


def test_html_escapes_what_users_wrote() -> None:
    html = render_html(DOC)
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;Ltd&gt;" in html
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html

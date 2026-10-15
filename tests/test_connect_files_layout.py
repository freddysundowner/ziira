"""The pure parts of reading statements, without a database: rebuilding rows from words with positions (the same code
reads text PDFs and OCR output), balance reconciliation, date and number detection, and the real OCR engine when the
program is installed."""

import shutil
from decimal import Decimal as D  # noqa: N817

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests import connect_file_fixtures as F  # noqa: N812
from ziira.modules.connect.connectors.statements import BankStatement
from ziira.modules.connect.domain import layout, reconcile, tabular, words
from ziira.modules.connect.domain.words import Word


def line(y: float, cells: list[tuple[str, float]]) -> list[Word]:
    """Words of one line: (text, left edge); every character is 6 wide and the text 10 high."""
    return [Word(t, x, x + 6 * len(t), y, y + 10) for t, x in cells]


VOCAB = BankStatement().vocabulary()


def test_words_with_positions_become_rows_under_their_headers_across_pages() -> None:
    builder = words.TableBuilder(VOCAB)
    page1 = [*line(50, [("Date", 40), ("Details", 120), ("Paid", 300), ("In", 330), ("Withdrawn", 380), ("Balance", 470)]),
             *line(70, [("14/10/2026", 40), ("Sale", 120), ("to", 150), ("Jane", 170), ("1,000.00", 290), ("11,000.00", 450)]),
             *line(90, [("15/10/2026", 40), ("Rent", 120), ("500.00", 400), ("10,500.00", 450)]),
             *line(110, [("of", 120), ("March", 140)])]
    page2 = [*line(70, [("16/10/2026", 40), ("Fuel", 120), ("200.00", 400), ("10,300.00", 450)])]   # no header repeated
    builder.feed(page1, 1)
    builder.feed(page2, 2)
    got = builder.result()
    assert got[0].cells == ["Date", "Details", "Paid In", "Withdrawn", "Balance"]
    assert got[1].cells == ["14/10/2026", "Sale to Jane", "1,000.00", "", "11,000.00"]
    assert got[2].cells == ["15/10/2026", "Rent", "", "500.00", "10,500.00"]
    assert got[3].cells == ["", "of March", "", "", ""] and got[3].page == 1                # a wrapped end of a detail
    assert got[4].cells == ["16/10/2026", "Fuel", "", "200.00", "10,300.00"] and got[4].page == 2


def test_lines_without_any_header_are_read_by_shape_and_the_direction_comes_from_the_balance() -> None:
    lines = [(1, "13/10/2026 QWE101 Customer Payment from JANE W 300.00 10,300.00", 99.0),
             (1, "13/10/2026 QWE102 Payment to supplier 2,000.00 8,300.00", 99.0),
             (1, "which continues here", 99.0),
             (1, "14/10/2026 QWE103 Customer Payment 1,500.50 9,800.50", 99.0)]
    got = words.rows_from_text(lines)
    assert got[0].cells == ["Date", "Reference", "Details", "Amount", "Balance"]
    assert got[1].cells[:5] == ["13/10/2026", "QWE101", "Customer Payment from JANE W", "300.00", "10,300.00"]
    assert got[2].cells[3] == "-2,000.00"                                      # the balance fell by 2,000.00
    assert got[3].cells[:3] == ["", "", "which continues here"]
    assert got[4].cells[3] == "1,500.50"


def test_a_running_balance_that_does_not_follow_flags_the_misread_lines_in_either_order() -> None:
    ok = [(i, D(a), D(b)) for i, (a, b) in enumerate([("300", "10300"), ("-2000", "8300"), ("1500.50", "9800.50"),
                                                      ("-500", "9300.50")], 1)]
    assert reconcile.suspects(ok) == [] and reconcile.suspects(ok[::-1]) == []
    wrong = [*ok[:2], (3, D("1500.50"), D("9600.50")), (4, D("-500"), D("9300.50")), (5, D("12000"), D("21300.50"))]
    assert reconcile.suspects(wrong) == [3, 4]
    assert reconcile.suspects([(i, D(1), D(i * 7)) for i in range(1, 6)]) == []        # nothing adds up: no verdict


@given(st.lists(st.integers(min_value=-5000, max_value=5000).filter(lambda v: v != 0), min_size=2, max_size=30),
       st.booleans())
def test_a_consistent_statement_is_never_flagged(moves: list[int], newest_first: bool) -> None:
    balance, entries = D(10_000), []
    for number, move in enumerate(moves, 1):
        balance += move
        entries.append((number, D(move), balance))
    assert reconcile.suspects(entries[::-1] if newest_first else entries) == []


@pytest.mark.parametrize(("values", "expected"), [
    (["13/10/2026", "14/10/2026"], ("dmy", False)), (["10/13/2026", "10/14/2026"], ("mdy", False)),
    (["03/04/2026", "05/04/2026"], ("dmy", True)), (["2026-10-13", "2026-10-14 09:00"], ("iso", False)),
    (["13-Oct-2026"], ("iso", False)), (["13/10/26", "01/02/26"], ("dmy", False))])
def test_date_order_is_read_from_the_numbers_and_ambiguity_is_reported(values: list[str], expected: tuple) -> None:  # type: ignore[type-arg]
    assert layout.detect_dates(values) == expected


def test_file_kinds_are_told_apart_by_their_first_bytes() -> None:
    assert tabular.sniff(F.pdf_signed()) == "pdf" and tabular.sniff(F.xlsx_in_out()) == "excel"
    assert tabular.sniff(F.csv_in_out()) == "csv" and tabular.sniff(F.png_bytes(F.render_page([], ["a"], [10]))) == "image"
    assert tabular.sniff(F.png_bytes(F.render_page([], ["a"], [10]), "JPEG")) == "image"
    assert tabular.sniff(b"BMW,Model\n1,2\n") == "csv"


def test_the_columns_are_found_by_what_they_contain_when_the_names_are_unknown() -> None:
    table = tabular.RawTable([tabular.RawRow(1, ["Foo", "Bar", "Baz", "Qux", "Quux"])] + [
        tabular.RawRow(i + 2, [F.dmy(t.day), t.code, t.details, F.money(abs(t.amount)) if t.amount > 0 else "",
                               F.money(abs(t.amount)) if t.amount < 0 else ""])
        for i, t in enumerate(F.TRANSACTIONS)], "excel")
    shaped = layout.shape(table, VOCAB, lenient=True)
    assert shaped.header_found is False and shaped.headers[0] == "column 1"
    guess = layout.guess_mapping(shaped, [(f.name, f.aliases) for f in BankStatement().fields])
    assert guess.mapping["date"] == "column 1" and guess.mapping["reference"] == "column 2"
    assert guess.mapping["description"] == "column 3"
    assert (guess.mapping["money_in"], guess.mapping["money_out"]) == ("column 4", "column 5")
    assert guess.how["money_in"] == 0.7


# --------------------------------------------------------------------------- the real OCR engine, when installed
needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="the tesseract program is not installed")


@needs_tesseract
def test_a_tilted_noisy_photo_of_a_statement_is_read_by_the_real_engine() -> None:
    from ziira.modules.connect.ocr import pages
    from ziira.modules.connect.ocr.tesseract import TesseractEngine
    engine = TesseractEngine()
    assert engine.unavailable() is None, engine.unavailable()
    header, xs, table = F.scan_rows()
    photo = F.png_bytes(F.render_page(table, header, xs, tilt=1.2, noise=True), "JPEG")
    read = pages.read_pictures(photo, "image", engine, VOCAB, max_pages=5)
    shaped = layout.shape(read, VOCAB, lenient=True, skip_phrases=BankStatement.skip_phrases)
    assert shaped.headers[:2] == ["Date", "Details"] and shaped.kinds.count("data") >= 5
    wanted = {F.money(abs(t.amount)) for t in F.TRANSACTIONS}
    found = {c for row in read.rows for c in row.cells}
    assert len(wanted & found) >= 5, f"read {len(wanted & found)} of 6 amounts exactly"

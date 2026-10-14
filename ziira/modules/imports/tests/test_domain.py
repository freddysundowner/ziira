"""Domain rules of the Data Import module: reading files, numbers, dates and column suggestions. No database."""

import contextlib
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.imports.domain import files, mapping, values


# --------------------------------------------------------------------------- numbers
@pytest.mark.parametrize("text,separator,expected", [
    ("1234.50", ".", "1234.50"), ("1,234.50", ".", "1234.50"), ("1,234,567", ".", "1234567"),
    ("1234,50", ",", "1234.50"), ("1.234,50", ",", "1234.50"), ("1 234,50", ",", "1234.50"),
    ("1 234,5", ",", "1234.5"), ("(12.00)", ".", "-12.00"), ("-3", ".", "-3"), ("+7", ".", "7"),
    (" 15 ", ".", "15"), (".5", ".", "0.5"), ("10.", ".", "10"), ("0", ",", "0"),
])
def test_numbers_are_read_with_the_files_separator(text: str, separator: str, expected: str) -> None:
    assert values.parse_decimal(text, separator) == Decimal(expected)


@pytest.mark.parametrize("text,separator", [
    ("1.5", ","),            # ambiguous: a point in a comma-decimal file is not guessed
    ("1,5", "."),            # same the other way
    ("1,23,456", "."), ("12abc", "."), ("", "."), ("-", "."), ("1e5", "."), ("1.2.3", "."), ("NaN", "."),
    ("9" * 25, "."),
])
def test_numbers_that_could_be_read_two_ways_are_refused(text: str, separator: str) -> None:
    with pytest.raises(ValueError):
        values.parse_decimal(text, separator)


@given(st.text(max_size=40), st.sampled_from([".", ","]))
def test_reading_a_number_never_fails_any_other_way(text: str, separator: str) -> None:
    try:
        number = values.parse_decimal(text, separator)
    except ValueError:
        return
    assert number.is_finite()


@given(st.decimals(min_value=Decimal("0"), max_value=Decimal("999999999.99"), places=2), st.sampled_from([".", ","]))
def test_a_written_number_reads_back(number: Decimal, separator: str) -> None:
    written = f"{number:f}".replace(".", separator)
    assert values.parse_decimal(written, separator) == number


def test_dates_and_yes_no() -> None:
    assert values.parse_date("2026-01-31") == date(2026, 1, 31)
    assert values.parse_date("31/01/2026", "dmy") == date(2026, 1, 31)
    assert values.parse_date("01/31/2026", "mdy") == date(2026, 1, 31)
    assert values.parse_date("2026-1-5", "dmy") == date(2026, 1, 5)
    for bad, fmt in (("31/01/2026", "iso"), ("31/02/2026", "dmy"), ("soon", "iso"), ("", "iso")):
        with pytest.raises(ValueError):
            values.parse_date(bad, fmt)
    assert [values.parse_bool(x) for x in ("Yes", "n", "TRUE", "0", " x ")] == [True, False, True, False, True]
    with pytest.raises(ValueError):
        values.parse_bool("maybe")


# --------------------------------------------------------------------------- files
def test_a_byte_order_mark_and_semicolons() -> None:
    data = "﻿Code;Name;Price\r\nA1;Bolt;1,50\r\nA2;Nut;2,00\r\n".encode()
    parsed = files.parse_file(data)
    assert parsed.delimiter == ";" and parsed.headers == ["Code", "Name", "Price"]
    assert parsed.rows == [(2, ["A1", "Bolt", "1,50"]), (3, ["A2", "Nut", "2,00"])]


def test_quoted_commas_line_breaks_and_trailing_spaces() -> None:
    data = b'sku,name,notes\n  A1 ,"Bolt, 10mm  ","two\nlines"\n\n,,\nA2,Nut,\n'
    parsed = files.parse_file(data)
    assert parsed.delimiter == ","
    assert parsed.rows == [(2, ["A1", "Bolt, 10mm", "two\nlines"]), (5, ["A2", "Nut", ""])]


def test_tabs_bars_and_short_or_long_rows() -> None:
    assert files.parse_file(b"a\tb\n1\t2\n").delimiter == "\t"
    assert files.parse_file(b"a|b\n1|2\n").delimiter == "|"
    parsed = files.parse_file(b"a,b,c\n1\n1,2,3,4\n")
    assert parsed.rows == [(2, ["1", "", ""]), (3, ["1", "2", "3"])]
    assert "Row 3" in parsed.warnings[0]


def test_headers_are_cleaned() -> None:
    parsed = files.parse_file(b"Name, ,name,\n1,2,3,4\n")
    assert parsed.headers == ["Name", "column 2", "name (2)", "column 4"]


def test_other_encodings() -> None:
    utf16 = "﻿sku,name\nA1,Café\n".encode("utf-16")
    assert files.parse_file(utf16).rows == [(2, ["A1", "Café"])]
    latin = "sku,name\nA1,Café\n".encode("cp1252")
    parsed = files.parse_file(latin)
    assert parsed.rows == [(2, ["A1", "Café"])] and "Windows-1252" in parsed.warnings[0]


def test_our_own_formula_guard_is_removed_when_a_downloaded_file_comes_back() -> None:
    parsed = files.parse_file(b"phone,qty\n'+254700000001,'-5\n")
    assert parsed.rows == [(2, ["+254700000001", "-5"])]


@pytest.mark.parametrize("data,message", [
    (b"", "empty"), (b"   \n\n", "empty"), (b"PK\x03\x04rest", "Excel"), (b"a,b\n", "no data rows"),
    (b"\n\n", "empty"), (b"a,b\x00\n1,2\n", "CSV"),
])
def test_unusable_files_are_refused_in_plain_words(data: bytes, message: str) -> None:
    with pytest.raises(files.ImportFileError, match=message):
        files.parse_file(data)


def test_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "MAX_ROWS", 3)
    with pytest.raises(files.ImportFileError, match="more than 3 rows"):
        files.parse_file(b"a\n1\n2\n3\n4\n")
    monkeypatch.setattr(files, "MAX_BYTES", 10)
    with pytest.raises(files.ImportFileError, match="larger"):
        files.parse_file(b"a,b\n" + b"1,2\n" * 10)
    monkeypatch.setattr(files, "MAX_BYTES", 5_000_000)
    monkeypatch.setattr(files, "MAX_CELL", 5)
    with pytest.raises(files.ImportFileError, match="longer"):
        files.parse_file(b"a\n123456\n")


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=2000))
def test_reading_arbitrary_bytes_never_crashes(data: bytes) -> None:
    try:
        parsed = files.parse_file(data)
    except files.ImportFileError:
        return
    assert parsed.headers and parsed.rows
    assert all(len(cells) == len(parsed.headers) for _, cells in parsed.rows)


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=500), st.sampled_from([None, ",", ";", "\t", "|"]))
def test_reading_arbitrary_text_never_crashes(text: str, delimiter: str | None) -> None:
    with contextlib.suppress(files.ImportFileError):
        files.parse_file(text.encode(), delimiter=delimiter)


# --------------------------------------------------------------------------- suggesting columns
FIELDS = [("sku", ("code", "item code")), ("name", ("description",)), ("unit", ("uom",)), ("price", ())]


def test_columns_are_suggested_by_name() -> None:
    suggested = mapping.suggest_mapping(["Item Code", "Description", "UOM", "Unit Price (KES)", "Notes"], FIELDS)
    assert suggested == {"sku": "Item Code", "name": "Description", "unit": "UOM", "price": "Unit Price (KES)"}


def test_a_close_spelling_matches_and_a_header_is_used_once() -> None:
    suggested = mapping.suggest_mapping(["SKUs", "Nme", "Units", "Prise"], FIELDS)
    assert suggested == {"sku": "SKUs", "name": "Nme", "unit": "Units", "price": "Prise"}
    assert mapping.suggest_mapping(["Code"], [("sku", ("code",)), ("barcode", ("code",))]) == {
        "sku": "Code", "barcode": None}


def test_nothing_is_guessed_from_unrelated_headers() -> None:
    assert mapping.suggest_mapping(["Colour", "Weight"], FIELDS) == {k: None for k, _ in FIELDS}

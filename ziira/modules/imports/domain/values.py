"""Reading the values people type into spreadsheets: numbers (with either decimal separator), dates, yes/no.

Strict on purpose: a value that could be read two ways ("1.5" in a file that uses commas for decimals) is refused with a
plain message instead of being guessed, because a wrongly read price or quantity is worse than a rejected row.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

DECIMAL_SEPARATORS = (".", ",")
DATE_FORMATS = ("iso", "dmy", "mdy")
MAX_DIGITS = 20
_SPACES = "    '’"
_PLAIN = {".": re.compile(r"^\d*\.?\d*$"), ",": re.compile(r"^\d*,?\d*$")}
_GROUPED = {".": re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$"), ",": re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")}
_BOOLS = {"yes": True, "y": True, "true": True, "1": True, "x": True, "no": False, "n": False, "false": False,
          "0": False}


def parse_decimal(text: str, decimal_separator: str = ".") -> Decimal:
    """A number as typed: `1234.50`, `1,234.50`, `1 234,50` (with comma decimals), `(12.00)` for minus 12."""
    if decimal_separator not in DECIMAL_SEPARATORS:
        raise ValueError("The decimal separator must be '.' or ','")
    value = text.strip()
    negative = False
    if value.startswith("(") and value.endswith(")"):
        negative, value = True, value[1:-1].strip()
    if value.startswith(("+", "-")):
        negative = negative or value[0] == "-"
        value = value[1:].strip()
    for ch in _SPACES:
        value = value.replace(ch, "")
    if not re.search(r"\d", value):
        raise ValueError(f"'{text.strip()}' is not a number")
    thousands = "," if decimal_separator == "." else "."
    if _PLAIN[decimal_separator].match(value):
        digits = value.replace(decimal_separator, ".")
    elif _GROUPED[decimal_separator].match(value):
        digits = value.replace(thousands, "").replace(decimal_separator, ".")
    else:
        written = "a comma" if decimal_separator == "," else "a point"
        raise ValueError(f"'{text.strip()}' is not a number this file can be read with (decimals are written with "
                         f"{written})")
    if len(digits.replace(".", "")) > MAX_DIGITS:
        raise ValueError(f"'{text.strip()}' has too many digits")
    try:
        number = Decimal(digits)
    except InvalidOperation as error:
        raise ValueError(f"'{text.strip()}' is not a number") from error
    return -number if negative else number


def parse_date(text: str, date_format: str = "iso") -> date:
    """A date: always `YYYY-MM-DD`; also `DD/MM/YYYY` (dmy) or `MM/DD/YYYY` (mdy) when the file uses that."""
    value = text.strip()
    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    parts = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", value)
    try:
        if iso:
            return date(int(iso[1]), int(iso[2]), int(iso[3]))
        if parts and date_format == "dmy":
            return date(int(parts[3]), int(parts[2]), int(parts[1]))
        if parts and date_format == "mdy":
            return date(int(parts[3]), int(parts[1]), int(parts[2]))
    except ValueError as error:
        raise ValueError(f"'{value}' is not a real date") from error
    shape = {"iso": "YYYY-MM-DD", "dmy": "DD/MM/YYYY", "mdy": "MM/DD/YYYY"}.get(date_format, "YYYY-MM-DD")
    raise ValueError(f"'{value}' is not a date (write it as {shape})")


def parse_bool(text: str) -> bool:
    """Yes/no as people write it: yes, y, true, 1, x / no, n, false, 0."""
    try:
        return _BOOLS[text.strip().lower()]
    except KeyError:
        raise ValueError(f"'{text.strip()}' is not yes or no") from None

"""Reading the values found in exports and statements: numbers (either decimal separator, currency words, brackets or
a trailing minus for negatives), dates and times in the common layouts, yes/no. No country is assumed anywhere.

Strict where a wrong reading would be silent (a number that could be read two ways is refused unless the file's
settings say how decimals are written); tolerant of decoration (a currency word, spaces, a thousands separator).
"""

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

DECIMAL_SEPARATORS = (".", ",")
DATE_FORMATS = ("iso", "dmy", "mdy")
MAX_DIGITS = 20
_SPACES = "    '’"
_PLAIN = {".": re.compile(r"^\d*\.?\d*$"), ",": re.compile(r"^\d*,?\d*$")}
_GROUPED = {".": re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$"), ",": re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")}
_WORD = re.compile(r"^[A-Za-z]{1,5}\.?\s*(?=[\d(+\-.,])|(?<=\d)\s*[A-Za-z]{1,5}\.?$|(?<=\))\s*[A-Za-z]{1,5}\.?$")
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_BOOLS = {"yes": True, "y": True, "true": True, "1": True, "x": True, "no": False, "n": False, "false": False,
          "0": False}


def parse_decimal(text: str, decimal_separator: str = ".") -> Decimal:
    """A number as typed: `1234.50`, `1,234.50`, `1 234,50` (comma decimals), `(12.00)` or `12.00-` for minus 12,
    `KES 1,200.00` and `1200 DR` (a currency word is ignored; DR means negative, CR positive)."""
    if decimal_separator not in DECIMAL_SEPARATORS:
        raise ValueError("The decimal separator must be '.' or ','")
    value = text.strip()
    negative = False
    suffix = re.search(r"\s*(dr|cr)\.?$", value, re.IGNORECASE)
    if suffix:
        negative = suffix[1].lower() == "dr"
        value = value[:suffix.start()].strip()
    for _ in range(2):                                 # a currency word may sit on either side
        stripped = _WORD.sub("", value).strip()
        value = stripped
    if value.startswith("(") and value.endswith(")"):
        negative, value = True, value[1:-1].strip()
    if value.endswith("-"):
        negative, value = True, value[:-1].strip()
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


def _real_date(year: int, month: int, day: int, original: str) -> date:
    try:
        return date(year, month, day)
    except ValueError as error:
        raise ValueError(f"'{original}' is not a real date") from error


def _year(text: str) -> int:
    """A year as written: four digits, or two digits (20xx)."""
    return int(text) if len(text) == 4 else 2000 + int(text)


def parse_date(text: str, date_format: str = "iso") -> date:
    """A date: `YYYY-MM-DD` always; `DD/MM/YYYY` (dmy) or `MM/DD/YYYY` (mdy) when the file says so; also
    `14-Oct-2026` and `14 October 2026` whatever the format."""
    value = text.strip()
    iso = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", value)
    parts = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})", value)
    named = re.fullmatch(r"(\d{1,2})[ \-/]([A-Za-z]{3,9})\.?[ \-/,]+(\d{4}|\d{2})", value)
    if iso:
        return _real_date(int(iso[1]), int(iso[2]), int(iso[3]), value)
    if named and named[2][:3].lower() in _MONTHS:
        return _real_date(_year(named[3]), _MONTHS[named[2][:3].lower()], int(named[1]), value)
    if parts and date_format == "dmy":
        return _real_date(_year(parts[3]), int(parts[2]), int(parts[1]), value)
    if parts and date_format == "mdy":
        return _real_date(_year(parts[3]), int(parts[1]), int(parts[2]), value)
    shape = {"iso": "YYYY-MM-DD", "dmy": "DD/MM/YYYY", "mdy": "MM/DD/YYYY"}.get(date_format, "YYYY-MM-DD")
    raise ValueError(f"'{value}' is not a date (write it as {shape})")


def parse_time(text: str) -> time:
    """`13:45`, `13:45:02`, `1:45 PM`."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*([AaPp][Mm])?", text.strip())
    if not match:
        raise ValueError(f"'{text.strip()}' is not a time")
    hour, minute, second = int(match[1]), int(match[2]), int(match[3] or 0)
    if match[4]:
        if not 1 <= hour <= 12:
            raise ValueError(f"'{text.strip()}' is not a time")
        hour = hour % 12 + (12 if match[4].lower() == "pm" else 0)
    try:
        return time(hour, minute, second)
    except ValueError as error:
        raise ValueError(f"'{text.strip()}' is not a time") from error


def parse_datetime(text: str, date_format: str, zone: str, extra_time: str = "") -> datetime:
    """A moment, as a timezone-aware datetime. `text` may hold the date alone, or date and time (`2026-10-14 13:45`,
    `14/10/2026 1:45 PM`, `2026-10-14T13:45:02+03:00`); `extra_time` is a separate time column. A date with no time is
    taken at 12:00 (noon) so it falls on that day in any nearby time zone. No offset in the text: `zone` (the
    company's) is used."""
    value = text.strip()
    iso = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*(Z|[+-]\d{2}:?\d{2})?", value)
    if iso:
        try:
            moment = datetime.fromisoformat(f"{iso[1]}T{iso[2]}")
        except ValueError as error:
            raise ValueError(f"'{value}' is not a real date and time") from error
        if iso[3]:
            offset = "+00:00" if iso[3] == "Z" else (iso[3] if ":" in iso[3] else iso[3][:3] + ":" + iso[3][3:])
            return datetime.fromisoformat(f"{iso[1]}T{iso[2]}{offset}")
        return moment.replace(tzinfo=ZoneInfo(zone))
    split = re.match(r"^(.*?)[ T]+(\d{1,2}:\d{2}.*)$", value)
    if split and extra_time == "":
        day, clock = parse_date(split[1], date_format), parse_time(split[2])
    else:
        day = parse_date(value, date_format)
        clock = parse_time(extra_time) if extra_time.strip() else time(12, 0)
    return datetime.combine(day, clock, tzinfo=ZoneInfo(zone))


def parse_bool(text: str) -> bool:
    try:
        return _BOOLS[text.strip().lower()]
    except KeyError:
        raise ValueError(f"'{text.strip()}' is not yes or no") from None

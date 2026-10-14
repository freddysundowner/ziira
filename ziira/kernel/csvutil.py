"""CSV for spreadsheets: every text cell is made safe against formulas.

A cell that starts with = + - @ (or a tab or return) would be run as a formula when the file is opened, so it is
prefixed with an apostrophe. Numbers and dates are not text and are written plainly.
"""

import csv
import io
from datetime import date
from decimal import Decimal

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def safe(value: object) -> str:
    """A cell's text, defused against spreadsheet formulas."""
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, date):
        return value.isoformat()
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def to_csv(header: list[str], rows: list[list[object]]) -> str:
    """The rows as CSV text (comma separated, CRLF line ends, quoted where needed)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe(x) for x in row])
    return out.getvalue()

"""What a piece of text looks like: a date, a time, an amount, a transaction code. Shapes, never country rules."""

import re
from decimal import Decimal

from ziira.modules.connect.domain import values

DATE_RE = (r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.](?:\d{4}|\d{2})"
           r"|\d{1,2}[ \-/][A-Za-z]{3,9}\.?[ \-/,]+(?:\d{4}|\d{2}))")
TIME_RE = r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:\s?[AaPp][Mm])?"
_DATE = re.compile(rf"^{DATE_RE}(?:[T ,]+{TIME_RE})?$")
_TIME = re.compile(rf"^{TIME_RE}$")
_AMOUNT = re.compile(r"^\(?[-+]?[A-Za-z]{0,4}\.?\s?\d[\d,.' ]*\)?-?(?:\s?(?:CR|DR|Cr|Dr|cr|dr))?$")
_MONEY = re.compile(r"^\(?[-+]?\d[\d,.']*[.,]\d{1,2}\)?-?$")
_CODE = re.compile(r"^(?=[A-Za-z0-9\-_/]*\d)[A-Za-z0-9\-_/]{5,24}$")
_DIRECTION = {"cr", "dr", "credit", "debit", "c", "d", "in", "out"}


def is_date(text: str) -> bool:
    return bool(_DATE.match(text.strip()))


def is_time(text: str) -> bool:
    return bool(_TIME.match(text.strip()))


def is_amount(text: str) -> bool:
    """A number as a statement writes it (thousands separators, brackets, a trailing minus, DR/CR)."""
    value = text.strip()
    return bool(value) and bool(_AMOUNT.match(value)) and not is_date(value) and any(ch.isdigit() for ch in value)


def is_money(text: str) -> bool:
    """An amount written with decimals (1,234.50 / 12,00): safe to take as money in running text."""
    return bool(_MONEY.match(re.sub(r"\s*(?:cr|dr)\.?$", "", text.strip(), flags=re.IGNORECASE)))


def is_code(text: str) -> bool:
    """A transaction code or reference: one token of letters and digits, at least one digit."""
    return bool(_CODE.match(text.strip())) and not is_date(text)


def is_direction(text: str) -> bool:
    return text.strip().lower().rstrip(".") in _DIRECTION


def number(text: str, decimal_separator: str = ".") -> Decimal | None:
    try:
        return values.parse_decimal(text, decimal_separator)
    except ValueError:
        return None

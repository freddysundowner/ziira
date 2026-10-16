"""Phone numbers as international digits (E.164 without the plus), for any country.

A number written with a leading '+' or '00' is international as given. A national number (a leading 0, or just the
subscriber digits) takes the company's calling code, which is a company setting: the kernel knows no country.
"""

import re

from ziira.kernel.errors import ValidationFailed

MIN_DIGITS, MAX_DIGITS = 8, 15              # E.164 allows at most 15 digits in all
MIN_SUBSCRIBER = 6                          # the number after the country code has at least this many digits
CALLING_CODE = re.compile(r"^[1-9]\d{0,2}$")


def check_calling_code(code: str) -> str:
    """A country calling code: 1 to 3 digits, no plus or leading zero ('44', '1', '353')."""
    cleaned = code.strip().lstrip("+")
    if cleaned and not CALLING_CODE.match(cleaned):
        raise ValidationFailed("A calling code is 1 to 3 digits, such as 44 or 1")
    return cleaned


def normalise_phone(value: str | None, country_code: str | None) -> str | None:
    """The number as international digits, or None when empty. `country_code` is the company's calling code (it may be
    empty, in which case only numbers written with '+' or '00' are accepted)."""
    if value is None or not value.strip():
        return None
    text = re.sub(r"[\s\-().]", "", value.strip())
    code = check_calling_code(country_code or "")
    if not re.fullmatch(r"\+?\d+", text):
        raise ValidationFailed("A phone number has only digits (and a leading + for international numbers)")
    if text.startswith("+"):
        digits = text[1:]
    elif text.startswith("00"):
        digits = text[2:]
    elif not code:
        raise ValidationFailed("Write the number with its country code (+...), or set the company's phone country code")
    elif text.startswith("0"):
        digits = code + text[1:]
    elif text.startswith(code) and MIN_DIGITS <= len(text) <= MAX_DIGITS:
        digits = text
    else:
        digits = code + text
    if not MIN_DIGITS <= len(digits) <= MAX_DIGITS or digits.startswith("0"):
        raise ValidationFailed("That does not look like a phone number")
    if code and digits.startswith(code) and len(digits) - len(code) < MIN_SUBSCRIBER:
        raise ValidationFailed("That number is too short")
    return digits

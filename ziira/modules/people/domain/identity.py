"""Checking what a person's record holds: identifiers, phone, email, account numbers. Pure Python.

Nothing here assumes a country. Phone numbers are normalised to international digits using the company's calling code
(its own setting); tax and registration numbers are kept as entered (letters, digits, '-', '/', '.'), because their
formats differ by country and by body.
"""

import re

from ziira.sdk import ValidationFailed, normalise_phone

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9/\-. ]{2,29}$")
NATIONAL_ID = re.compile(r"^[A-Z0-9]{4,25}$")


def tax_id(value: str | None) -> str | None:
    """A tax number: 3 to 30 letters, digits, '-', '/' or '.', as the tax authority writes it."""
    if value is None or not value.strip():
        return None
    number = " ".join(value.strip().upper().split())
    if not IDENTIFIER.match(number):
        raise ValidationFailed("A tax number is 3 to 30 letters, digits, '-', '/' or '.'")
    return number


def national_id(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    number = re.sub(r"[\s\-]", "", value.strip()).upper()
    if not NATIONAL_ID.match(number):
        raise ValidationFailed("An ID or passport number is 4 to 25 letters and digits")
    return number


def registrations(values: dict[str, str] | None) -> dict[str, str]:
    """Numbers with the bodies that collect contributions, by rule code: {'PENSION': '123456'}."""
    clean: dict[str, str] = {}
    for code, number in (values or {}).items():
        key = str(code).strip().upper()
        value = tax_id(number)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,19}", key):
            raise ValidationFailed(f"'{code}' is not a rule code")
        if value:
            clean[key] = value
    if len(clean) > 30:
        raise ValidationFailed("Too many registration numbers")
    return clean


def phone(value: str | None, country_code: str) -> str | None:
    """A phone number as international digits, using the company's calling code for national numbers."""
    return normalise_phone(value, country_code)


def email(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    address = value.strip().lower()
    if len(address) > 200 or not EMAIL.match(address):
        raise ValidationFailed("That email address does not look right")
    return address


def mask(value: str, keep: int = 3) -> str:
    """Show only the last few characters of something private."""
    return "*" * max(len(value) - keep, 0) + value[-keep:]


def account_number(method: str, value: str, country_code: str) -> str:
    """A bank account number (digits or letters, 4 to 34 characters, as an IBAN may be) or the mobile money number."""
    if method == "mobile_money":
        cleaned = phone(value, country_code)
        if cleaned is None:
            raise ValidationFailed("A mobile money number is required")
        return cleaned
    text = re.sub(r"[\s\-]", "", value.strip()).upper()
    if not re.fullmatch(r"[A-Z0-9]{4,34}", text):
        raise ValidationFailed("A bank account number is 4 to 34 letters and digits")
    return text

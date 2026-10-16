"""Provider-neutral mobile-money values: amounts, masked and fingerprinted phone numbers, and the shapes a provider
plugin turns its own callbacks into. Pure Python. Nothing here knows any provider's or country's format."""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ziira.sdk import ValidationFailed

SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")


def parse_amount(value: Any, what: str = "Amount") -> Decimal:
    """A positive amount with at most 2 decimal places."""
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise ValidationFailed(f"{what} is not a number") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailed(f"{what} must be a positive amount with at most 2 decimal places")
    return amount


def check_prompt_amount(amount: Decimal, *, minimum: Decimal, maximum: Decimal | None, whole: bool) -> Decimal:
    """A payment prompt's amount against what the provider accepts (`whole`: no cents; `maximum` None: no ceiling)."""
    if whole and amount != amount.quantize(Decimal("1")):
        raise ValidationFailed("A payment prompt is for a whole amount (no cents)")
    if amount < minimum or (maximum is not None and amount > maximum):
        bounds = f"at least {minimum}" if maximum is None else f"between {minimum} and {maximum}"
        raise ValidationFailed(f"A payment prompt is for {bounds}")
    return amount


def mask_phone(msisdn: str) -> str:
    """The first four and last three digits (4479xxxx...): enough for a person to recognise, not enough to call."""
    if SHA256_HEX.match(msisdn):
        return "hashed"
    return f"{msisdn[:4]}****{msisdn[-3:]}" if len(msisdn) >= 8 else "****"


def phone_fingerprint(msisdn: str) -> str:
    """SHA-256 of a number in international digits. Some providers send payers' numbers only in this form, so a payment
    recorded with the number and a callback that carries the hash can be compared without either storing the number.
    An already-hashed value is kept. Normalise the number first (the provider or `ziira.sdk.normalise_phone`)."""
    if SHA256_HEX.match(msisdn):
        return msisdn.lower()
    digits = re.sub(r"\D", "", msisdn)
    if not 8 <= len(digits) <= 15:
        raise ValidationFailed("That does not look like a phone number")
    return hashlib.sha256(digits.encode()).hexdigest()


@dataclass(frozen=True)
class C2BTransaction:
    """A customer paying a till or paybill, as a provider reports it."""

    ref: str
    amount: Decimal
    time: datetime
    shortcode: str
    bill_ref: str | None
    payer_name: str | None
    msisdn: str | None
    transaction_type: str | None


@dataclass(frozen=True)
class StkResult:
    """The result of a payment prompt, from the provider's callback or a status query. The provider's own code is kept
    in `result_code`; `outcome` is what it means ('succeeded', 'cancelled' by the customer, 'failed', or 'pending'
    while the provider is still waiting). Left empty, code 0 means succeeded and anything else failed."""

    checkout_request_id: str
    merchant_request_id: str | None
    result_code: int
    description: str
    receipt: str | None = None
    amount: Decimal | None = None
    phone: str | None = None
    time: datetime | None = None
    outcome: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome == "succeeded" or (not self.outcome and self.result_code == 0)

    @property
    def cancelled(self) -> bool:
        return self.outcome == "cancelled"

    @property
    def pending(self) -> bool:
        return self.outcome == "pending"

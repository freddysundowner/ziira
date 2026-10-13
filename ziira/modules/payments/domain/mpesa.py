"""M-Pesa (Safaricom Daraja) data: phone numbers, timestamps and the shapes of requests and callbacks. Pure Python.

The formats follow Safaricom's Daraja documentation as we know it; they must be confirmed against Safaricom's sandbox
before going live (see docs/payments.md).
"""

import base64
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ziira.sdk import ValidationFailed

EAT = timezone(timedelta(hours=3))
MIN_AMOUNT = Decimal("1")
MAX_STK_AMOUNT = Decimal("150000")
SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")


# --------------------------------------------------------------------------- phone numbers
def normalize_phone(raw: str) -> str:
    """A Kenyan mobile number as 254XXXXXXXXX (07.., 01.., +254.., 254.. and 7../1.. are accepted)."""
    digits = re.sub(r"[ \-()]", "", raw.strip())
    if digits.startswith("+"):
        digits = digits[1:]
    if re.fullmatch(r"0[17]\d{8}", digits):
        digits = "254" + digits[1:]
    elif re.fullmatch(r"[17]\d{8}", digits):
        digits = "254" + digits
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise ValidationFailed("Phone number is not a valid Kenyan mobile number")
    return digits


def mask_phone(msisdn: str) -> str:
    """2547****678: enough for a person to recognise, not enough to call."""
    if SHA256_HEX.match(msisdn):
        return "hashed"
    return f"{msisdn[:4]}****{msisdn[-3:]}" if len(msisdn) >= 8 else "****"


def phone_fingerprint(msisdn: str) -> str:
    """SHA-256 of the normalised number. Safaricom sends payers' numbers in this form, so a payment we recorded with the
    number and a callback that carries the hash can be compared without either storing the number."""
    if SHA256_HEX.match(msisdn):
        return msisdn.lower()
    return hashlib.sha256(normalize_phone(msisdn).encode()).hexdigest()


# --------------------------------------------------------------------------- times and amounts
def parse_daraja_time(value: str) -> datetime:
    """Daraja times are YYYYMMDDHHMMSS in East Africa Time."""
    try:
        return datetime.strptime(str(value).strip(), "%Y%m%d%H%M%S").replace(tzinfo=EAT)
    except ValueError:
        raise ValidationFailed("The transaction time is not in the form YYYYMMDDHHMMSS") from None


def daraja_timestamp(now: datetime | None = None) -> str:
    """The timestamp Daraja wants in an STK request, in East Africa Time."""
    return (now or datetime.now(UTC)).astimezone(EAT).strftime("%Y%m%d%H%M%S")


def stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    """base64(shortcode + passkey + timestamp), as Daraja asks for."""
    return base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()


def parse_amount(value: Any, what: str = "Amount") -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise ValidationFailed(f"{what} is not a number") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailed(f"{what} must be a positive amount with at most 2 decimal places")
    return amount


def check_stk_amount(amount: Decimal, limit: Decimal = MAX_STK_AMOUNT) -> Decimal:
    """STK push amounts are whole shillings within the limit."""
    if amount != amount.quantize(Decimal("1")):
        raise ValidationFailed("An M-Pesa prompt is for a whole number of shillings")
    if not MIN_AMOUNT <= amount <= limit:
        raise ValidationFailed(f"An M-Pesa prompt is for between {MIN_AMOUNT} and {limit} shillings")
    return amount


# --------------------------------------------------------------------------- what Safaricom sends us
@dataclass(frozen=True)
class C2BTransaction:
    """A customer paying a till or paybill (the C2B confirmation)."""

    ref: str
    amount: Decimal
    time: datetime
    shortcode: str
    bill_ref: str | None
    payer_name: str | None
    msisdn: str | None
    transaction_type: str | None


def parse_c2b(payload: dict[str, Any]) -> C2BTransaction:
    """Read a C2B confirmation. Raises ValidationFailed when the essentials are missing."""
    ref = str(payload.get("TransID") or "").strip()
    if not ref:
        raise ValidationFailed("The confirmation has no TransID")
    name = " ".join(str(payload.get(k) or "").strip() for k in ("FirstName", "MiddleName", "LastName")).split()
    return C2BTransaction(
        ref=ref.upper(), amount=parse_amount(payload.get("TransAmount"), "TransAmount"),
        time=parse_daraja_time(str(payload.get("TransTime") or "")),
        shortcode=str(payload.get("BusinessShortCode") or ""),
        bill_ref=(str(payload.get("BillRefNumber") or "").strip() or None), payer_name=" ".join(name) or None,
        msisdn=(str(payload.get("MSISDN") or "").strip() or None),
        transaction_type=(str(payload.get("TransactionType") or "").strip() or None))


@dataclass(frozen=True)
class StkResult:
    """The result of an STK push, from the callback or a status query."""

    checkout_request_id: str
    merchant_request_id: str | None
    result_code: int
    description: str
    receipt: str | None = None
    amount: Decimal | None = None
    phone: str | None = None
    time: datetime | None = None

    @property
    def succeeded(self) -> bool:
        return self.result_code == 0

    @property
    def cancelled(self) -> bool:
        return self.result_code == 1032                  # the customer dismissed the prompt


def parse_stk_callback(payload: dict[str, Any]) -> StkResult:
    """Read an STK callback ({"Body": {"stkCallback": {...}}}). Raises ValidationFailed when it is not one."""
    body = (payload.get("Body") or {}).get("stkCallback") if isinstance(payload.get("Body"), dict) else None
    if not isinstance(body, dict) or not body.get("CheckoutRequestID"):
        raise ValidationFailed("This is not an STK push callback")
    try:
        code = int(str(body.get("ResultCode")))
    except ValueError:
        raise ValidationFailed("The callback has no ResultCode") from None
    items = {i.get("Name"): i.get("Value") for i in (body.get("CallbackMetadata") or {}).get("Item", [])
             if isinstance(i, dict)}
    when = items.get("TransactionDate")
    return StkResult(
        checkout_request_id=str(body["CheckoutRequestID"]), merchant_request_id=body.get("MerchantRequestID"),
        result_code=code, description=str(body.get("ResultDesc") or ""),
        receipt=(str(items["MpesaReceiptNumber"]).upper() if items.get("MpesaReceiptNumber") else None),
        amount=parse_amount(items["Amount"]) if items.get("Amount") is not None else None,
        phone=(str(items["PhoneNumber"]) if items.get("PhoneNumber") is not None else None),
        time=parse_daraja_time(str(when)) if when else None)

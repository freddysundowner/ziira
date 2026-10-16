"""M-Pesa (Safaricom Daraja) data: phone numbers, timestamps and the shapes of requests and callbacks. Pure Python.

The formats follow Safaricom's Daraja documentation as we know it; they must be confirmed against Safaricom's sandbox
before going live (see this plugin's README).
"""

import base64
import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from ziira.modules.payments.public import C2BTransaction, StkResult, parse_amount
from ziira.sdk import ValidationFailed

EAT = timezone(timedelta(hours=3))
MIN_AMOUNT = Decimal("1")
MAX_STK_AMOUNT = Decimal("150000")
CANCELLED_BY_CUSTOMER = 1032       # the customer dismissed the prompt
STILL_WAITING = 1037               # no answer from the customer's phone yet: the prompt may still be answered


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


# --------------------------------------------------------------------------- what Safaricom sends us
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


def outcome_of(code: int) -> str:
    """What a Daraja result code means for the payment prompt."""
    if code == 0:
        return "succeeded"
    if code == CANCELLED_BY_CUSTOMER:
        return "cancelled"
    if code == STILL_WAITING or code < 0:
        return "pending"
    return "failed"


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
        result_code=code, description=str(body.get("ResultDesc") or ""), outcome=outcome_of(code),
        receipt=(str(items["MpesaReceiptNumber"]).upper() if items.get("MpesaReceiptNumber") else None),
        amount=parse_amount(items["Amount"]) if items.get("Amount") is not None else None,
        phone=(str(items["PhoneNumber"]) if items.get("PhoneNumber") is not None else None),
        time=parse_daraja_time(str(when)) if when else None)

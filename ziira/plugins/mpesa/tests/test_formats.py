"""Unit tests for the M-Pesa plugin's pure parts: phone numbers, Daraja times, callbacks and the statement format."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ziira.modules.payments.public import MAX_ROWS
from ziira.plugins.mpesa import formats
from ziira.plugins.mpesa.statement import parse_mpesa_statement
from ziira.sdk import ValidationFailed

D = Decimal


# --------------------------------------------------------------------------- phone numbers
@pytest.mark.parametrize("raw", ["0712345678", "712345678", "+254712345678", "254712345678", " 0712 345-678 ",
                                 "0112345678", "(0712) 345678"])
def test_phone_numbers_are_normalised(raw: str) -> None:
    assert formats.normalize_phone(raw) in ("254712345678", "254112345678")


@pytest.mark.parametrize("bad", ["", "123", "0812345678", "25471234567", "2547123456789", "abcdefghij", "0712345678x",
                                 "+1 555 123 4567", "07123456789"])
def test_bad_phone_numbers(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        formats.normalize_phone(bad)


# --------------------------------------------------------------------------- times and amounts
def test_daraja_times() -> None:
    t = formats.parse_daraja_time("20261013101530")
    assert (t.hour, t.minute, t.second) == (10, 15, 30) and t.utcoffset() == timedelta(hours=3)
    for bad in ("", "2026-10-13", "20261313101530", "abc"):
        with pytest.raises(ValidationFailed):
            formats.parse_daraja_time(bad)
    assert formats.daraja_timestamp(datetime(2026, 10, 13, 7, 15, 30, tzinfo=UTC)) == "20261013101530"


def test_the_stk_password() -> None:
    assert formats.stk_password("174379", "PASSKEY", "20261013101530") == "MTc0Mzc5UEFTU0tFWTIwMjYxMDEzMTAxNTMw"


# --------------------------------------------------------------------------- what Safaricom sends
C2B = {"TransactionType": "Pay Bill", "TransID": "rkq1abc23", "TransTime": "20261013101530", "TransAmount": "116.00",
       "BusinessShortCode": "600638", "BillRefNumber": "POS-THK-01-000451", "MSISDN": "254712345678",
       "FirstName": "Jane", "MiddleName": "", "LastName": "Wanjiru"}


def test_a_c2b_confirmation() -> None:
    t = formats.parse_c2b(C2B)
    assert (t.ref, t.amount, t.bill_ref, t.payer_name, t.shortcode) == ("RKQ1ABC23", D("116.00"), "POS-THK-01-000451",
                                                                       "Jane Wanjiru", "600638")
    assert t.time.hour == 10 and t.msisdn == "254712345678"
    bare = formats.parse_c2b({**C2B, "BillRefNumber": "", "FirstName": "", "LastName": "", "MSISDN": ""})
    assert bare.bill_ref is None and bare.payer_name is None and bare.msisdn is None


@pytest.mark.parametrize("change", [{"TransID": ""}, {"TransAmount": "-1"}, {"TransAmount": "x"},
                                    {"TransTime": "yesterday"}, {"TransAmount": None}])
def test_a_bad_c2b_confirmation(change: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationFailed):
        formats.parse_c2b({**C2B, **change})


def stk(code: int = 0, **extra):  # type: ignore[no-untyped-def]
    items = [{"Name": "Amount", "Value": 116.0}, {"Name": "MpesaReceiptNumber", "Value": "rkq1abc23"},
             {"Name": "TransactionDate", "Value": 20261013101530}, {"Name": "PhoneNumber", "Value": 254712345678}]
    callback = {"MerchantRequestID": "m-1", "CheckoutRequestID": "ws_CO_1", "ResultCode": code,
                "ResultDesc": "The service request is processed successfully.", **extra}
    if code == 0:
        callback["CallbackMetadata"] = {"Item": items}
    return {"Body": {"stkCallback": callback}}


def test_a_successful_stk_callback() -> None:
    r = formats.parse_stk_callback(stk())
    assert r.succeeded and not r.cancelled and r.checkout_request_id == "ws_CO_1"
    assert (r.receipt, r.amount, r.phone) == ("RKQ1ABC23", D("116.0"), "254712345678")
    assert r.time is not None and r.time.hour == 10


def test_failed_and_cancelled_stk_callbacks() -> None:
    cancelled = formats.parse_stk_callback(stk(1032, ResultDesc="Request cancelled by user"))
    assert cancelled.cancelled and not cancelled.succeeded and cancelled.receipt is None
    assert formats.parse_stk_callback(stk(1)).succeeded is False


@pytest.mark.parametrize("payload", [{}, {"Body": {}}, {"Body": "x"}, {"Body": {"stkCallback": {}}},
                                     {"Body": {"stkCallback": {"CheckoutRequestID": "x"}}},
                                     {"Body": {"stkCallback": {"CheckoutRequestID": "x", "ResultCode": "abc"}}}])
def test_things_that_are_not_stk_callbacks(payload: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationFailed):
        formats.parse_stk_callback(payload)



def test_the_provider_decides_what_a_callback_means() -> None:
    assert formats.outcome_of(0) == "succeeded" and formats.outcome_of(1032) == "cancelled"
    assert formats.outcome_of(1037) == "pending" and formats.outcome_of(-1) == "pending"
    assert formats.outcome_of(2001) == "failed" and formats.outcome_of(1) == "failed"
    assert formats.parse_stk_callback(stk(1037)).pending is True


# --------------------------------------------------------------------------- statements
MPESA_CSV = """Statement for 600638
Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance
RKQ1ABC23,2026-10-13 10:15:30,Funds received from 2547****678 - JANE WANJIRU,Completed,"1,160.00",,5000.00
RKQ1ABC24,2026-10-13 10:20:00,Business Payment to 254722000000,Completed,,300.00,4700.00
RKQ1ABC25,2026-10-13 10:25:00,Funds received from 2547****111 - JOHN,Failed,500.00,,4700.00
RKQ1ABC26,not a time,Funds received,Completed,10.00,,4710.00
,2026-10-13 11:00:00,No receipt,Completed,10.00,,4720.00
RKQ1ABC27,2026-10-13 11:05:00,Both sides,Completed,10.00,10.00,4720.00
"""


def test_an_mpesa_statement() -> None:
    parsed = parse_mpesa_statement(MPESA_CSV)
    assert [(r.ref, r.direction, r.amount) for r in parsed.rows] == [
        ("RKQ1ABC23", "in", D("1160.00")), ("RKQ1ABC24", "out", D("300.00"))]
    assert parsed.rows[0].payer_name == "JANE WANJIRU" and parsed.rows[0].payer_phone == "2547****678"
    assert parsed.rows[1].payer_name is None and parsed.rows[1].payer_phone == "254722000000"
    assert len(parsed.skipped) == 3 and all(s.startswith("line ") for s in parsed.skipped)   # failed rows are ignored


def test_statements_that_are_not_statements() -> None:
    for text in ("", "just words", "a,b,c\n1,2,3"):
        with pytest.raises(ValidationFailed):
            parse_mpesa_statement(text)
    with pytest.raises(ValidationFailed, match="Receipt No"):
        parse_mpesa_statement("Date,Description,Amount\n2026-10-13,x,5")


def test_statements_have_a_size_limit() -> None:
    rows = "\n".join(f"R{i},2026-10-13 10:00:00,x,Completed,1,," for i in range(MAX_ROWS + 1))
    with pytest.raises(ValidationFailed, match="at most"):
        header = "Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn\n"
        parse_mpesa_statement(header + rows)

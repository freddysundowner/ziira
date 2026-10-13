"""Unit tests for Payments' pure rules: M-Pesa data, statements and the matching engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.payments.domain import matching, mpesa, statements
from ziira.modules.payments.domain.matching import Pay, Txn
from ziira.sdk import ValidationFailed

D = Decimal


# --------------------------------------------------------------------------- phone numbers
@pytest.mark.parametrize("raw", ["0712345678", "712345678", "+254712345678", "254712345678", " 0712 345-678 ",
                                 "0112345678", "(0712) 345678"])
def test_phone_numbers_are_normalised(raw: str) -> None:
    assert mpesa.normalize_phone(raw) in ("254712345678", "254112345678")


@pytest.mark.parametrize("bad", ["", "123", "0812345678", "25471234567", "2547123456789", "abcdefghij", "0712345678x",
                                 "+1 555 123 4567", "07123456789"])
def test_bad_phone_numbers(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        mpesa.normalize_phone(bad)


def test_masking_and_fingerprints() -> None:
    assert mpesa.mask_phone("254712345678") == "2547****678"
    assert mpesa.mask_phone("a" * 64) == "hashed" and mpesa.mask_phone("123") == "****"
    a, b = mpesa.phone_fingerprint("0712345678"), mpesa.phone_fingerprint("+254 712 345 678")
    assert a == b and len(a) == 64 and "254712345678" not in a
    assert mpesa.phone_fingerprint(a.upper()) == a                                # an already-hashed number is kept
    assert mpesa.phone_fingerprint("0722000000") != a


# --------------------------------------------------------------------------- times and amounts
def test_daraja_times() -> None:
    t = mpesa.parse_daraja_time("20261013101530")
    assert (t.hour, t.minute, t.second) == (10, 15, 30) and t.utcoffset() == timedelta(hours=3)
    for bad in ("", "2026-10-13", "20261313101530", "abc"):
        with pytest.raises(ValidationFailed):
            mpesa.parse_daraja_time(bad)
    assert mpesa.daraja_timestamp(datetime(2026, 10, 13, 7, 15, 30, tzinfo=UTC)) == "20261013101530"


def test_the_stk_password() -> None:
    assert mpesa.stk_password("174379", "PASSKEY", "20261013101530") == "MTc0Mzc5UEFTU0tFWTIwMjYxMDEzMTAxNTMw"


@pytest.mark.parametrize(("value", "ok"), [("100", True), ("100.50", True), ("1,500", True), (250, True),
                                           ("0", False), ("-5", False), ("1.005", False), ("NaN", False),
                                           ("abc", False), ("", False), ("Infinity", False)])
def test_amounts(value: object, ok: bool) -> None:
    if ok:
        assert mpesa.parse_amount(value) > 0
    else:
        with pytest.raises(ValidationFailed):
            mpesa.parse_amount(value)


def test_stk_amount_limits() -> None:
    assert mpesa.check_stk_amount(D("1")) == 1 and mpesa.check_stk_amount(D("150000")) == 150000
    for bad in (D("0"), D("150001"), D("10.50"), D("-5")):
        with pytest.raises(ValidationFailed):
            mpesa.check_stk_amount(bad)
    assert mpesa.check_stk_amount(D("200000"), limit=D("250000")) == 200000


# --------------------------------------------------------------------------- what Safaricom sends
C2B = {"TransactionType": "Pay Bill", "TransID": "rkq1abc23", "TransTime": "20261013101530", "TransAmount": "116.00",
       "BusinessShortCode": "600638", "BillRefNumber": "POS-THK-01-000451", "MSISDN": "254712345678",
       "FirstName": "Jane", "MiddleName": "", "LastName": "Wanjiru"}


def test_a_c2b_confirmation() -> None:
    t = mpesa.parse_c2b(C2B)
    assert (t.ref, t.amount, t.bill_ref, t.payer_name, t.shortcode) == ("RKQ1ABC23", D("116.00"), "POS-THK-01-000451",
                                                                       "Jane Wanjiru", "600638")
    assert t.time.hour == 10 and t.msisdn == "254712345678"
    bare = mpesa.parse_c2b({**C2B, "BillRefNumber": "", "FirstName": "", "LastName": "", "MSISDN": ""})
    assert bare.bill_ref is None and bare.payer_name is None and bare.msisdn is None


@pytest.mark.parametrize("change", [{"TransID": ""}, {"TransAmount": "-1"}, {"TransAmount": "x"},
                                    {"TransTime": "yesterday"}, {"TransAmount": None}])
def test_a_bad_c2b_confirmation(change: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationFailed):
        mpesa.parse_c2b({**C2B, **change})


def stk(code: int = 0, **extra):  # type: ignore[no-untyped-def]
    items = [{"Name": "Amount", "Value": 116.0}, {"Name": "MpesaReceiptNumber", "Value": "rkq1abc23"},
             {"Name": "TransactionDate", "Value": 20261013101530}, {"Name": "PhoneNumber", "Value": 254712345678}]
    callback = {"MerchantRequestID": "m-1", "CheckoutRequestID": "ws_CO_1", "ResultCode": code,
                "ResultDesc": "The service request is processed successfully.", **extra}
    if code == 0:
        callback["CallbackMetadata"] = {"Item": items}
    return {"Body": {"stkCallback": callback}}


def test_a_successful_stk_callback() -> None:
    r = mpesa.parse_stk_callback(stk())
    assert r.succeeded and not r.cancelled and r.checkout_request_id == "ws_CO_1"
    assert (r.receipt, r.amount, r.phone) == ("RKQ1ABC23", D("116.0"), "254712345678")
    assert r.time is not None and r.time.hour == 10


def test_failed_and_cancelled_stk_callbacks() -> None:
    cancelled = mpesa.parse_stk_callback(stk(1032, ResultDesc="Request cancelled by user"))
    assert cancelled.cancelled and not cancelled.succeeded and cancelled.receipt is None
    assert mpesa.parse_stk_callback(stk(1)).succeeded is False


@pytest.mark.parametrize("payload", [{}, {"Body": {}}, {"Body": "x"}, {"Body": {"stkCallback": {}}},
                                     {"Body": {"stkCallback": {"CheckoutRequestID": "x"}}},
                                     {"Body": {"stkCallback": {"CheckoutRequestID": "x", "ResultCode": "abc"}}}])
def test_things_that_are_not_stk_callbacks(payload: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationFailed):
        mpesa.parse_stk_callback(payload)


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
    parsed = statements.parse_mpesa_statement(MPESA_CSV)
    assert [(r.ref, r.direction, r.amount) for r in parsed.rows] == [
        ("RKQ1ABC23", "in", D("1160.00")), ("RKQ1ABC24", "out", D("300.00"))]
    assert parsed.rows[0].payer_name == "JANE WANJIRU" and parsed.rows[0].payer_phone == "2547****678"
    assert parsed.rows[1].payer_name is None and parsed.rows[1].payer_phone == "254722000000"
    assert len(parsed.skipped) == 3 and all(s.startswith("line ") for s in parsed.skipped)   # failed rows are ignored


def test_statements_that_are_not_statements() -> None:
    for text in ("", "just words", "a,b,c\n1,2,3"):
        with pytest.raises(ValidationFailed):
            statements.parse_mpesa_statement(text)
    with pytest.raises(ValidationFailed, match="Receipt No"):
        statements.parse_mpesa_statement("Date,Description,Amount\n2026-10-13,x,5")


BANK_CSV = """Date,Description,Reference,Debit,Credit
13/10/2026,MPESA SETTLEMENT,ST123,,"58,000.00"
14/10/2026,BANK CHARGES,,250.00,
15/10/2026,Mystery,,,
bad date,Oops,,10.00,
"""


def test_a_bank_statement_with_debit_and_credit_columns() -> None:
    parsed = statements.parse_bank_statement(BANK_CSV)
    assert [(r.direction, r.amount) for r in parsed.rows] == [("in", D("58000.00")), ("out", D("250.00"))]
    assert parsed.rows[0].ref == "ST123" and parsed.rows[1].ref.startswith("B") and len(parsed.skipped) == 2
    again = statements.parse_bank_statement(BANK_CSV)
    assert [r.ref for r in again.rows] == [r.ref for r in parsed.rows]      # stable references: re-upload is safe


def test_a_bank_statement_with_a_signed_amount_column() -> None:
    csv_text = "Date,Description,Amount\n2026-10-13,Deposit,100.50\n2026-10-14,Fee,-20\n"
    parsed = statements.parse_bank_statement(csv_text, amount_column="Amount", reference_column=None)
    assert [(r.direction, r.amount) for r in parsed.rows] == [("in", D("100.50")), ("out", D("20"))]
    with pytest.raises(ValidationFailed, match="no 'Posted' column"):
        statements.parse_bank_statement(csv_text, date_column="Posted")


def test_statements_have_a_size_limit() -> None:
    rows = "\n".join(f"R{i},2026-10-13 10:00:00,x,Completed,1,," for i in range(statements.MAX_ROWS + 1))
    with pytest.raises(ValidationFailed, match="at most"):
        header = "Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn\n"
        statements.parse_mpesa_statement(header + rows)


# --------------------------------------------------------------------------- matching
T0 = datetime(2026, 10, 13, 10, 0, tzinfo=mpesa.EAT)
ACC = uuid4()


def txn(ref: str = "R1", amount: str = "116", minutes: int = 0, bill: str | None = None,
        phone: str | None = None, account: UUID = ACC, direction: str = "in") -> Txn:
    return Txn(uuid4(), account, ref, D(amount), T0 + timedelta(minutes=minutes), bill, phone, direction)


def pay(amount: str = "116", minutes: int = 0, ref: str | None = None, number: str | None = None,
        phone: str | None = None, account: UUID = ACC, direction: str = "in") -> Pay:
    return Pay(uuid4(), account, D(amount), T0 + timedelta(minutes=minutes), ref, number, phone, direction)


def test_stage_one_exact_reference() -> None:
    t, p = txn("rkq1abc23"), pay(ref=" RKQ1ABC23 ", minutes=999)               # time does not matter here
    [m] = matching.match_all([t], [p])
    assert (m.stage, m.apply, m.confidence, m.amount) == ("exact_reference", True, D("1"), D("116"))


def test_stage_two_account_number() -> None:
    t, p = txn("X9", bill="pos-thk-01-000451"), pay(number="POS-THK-01-000451", minutes=999)
    [m] = matching.match_all([t], [p])
    assert (m.stage, m.apply, m.confidence) == ("account_number", True, D("0.98"))


def test_stage_three_needs_a_confident_score_to_apply() -> None:
    phone = "a" * 64
    t = txn("X9", phone=phone, minutes=2)
    strong = pay(phone=phone, minutes=0)                                       # same amount, phone, within 5 minutes
    [m] = matching.match_all([t], [strong])
    assert m.stage == "rule" and m.apply and m.confidence == D("1.0") and m.rule_code == "amount_account_phone_time"
    weak = pay(minutes=0)                                                      # no phone to compare
    [m] = matching.match_all([txn("X9", minutes=2)], [weak])
    assert m.stage == "rule" and not m.apply and m.confidence == D("0.7")      # proposed, not applied
    late = pay(minutes=20)                                                     # amount fits, but 20 minutes apart
    [m] = matching.match_all([txn("X9", minutes=0)], [late])
    assert not m.apply and m.confidence == D("0.6")


def test_things_that_must_not_match() -> None:
    t = txn("X9", phone="a" * 64)
    assert matching.match_all([t], [pay(phone="b" * 64)]) == []                # a different payer
    assert matching.match_all([txn("X9")], [pay(amount="115")]) == []          # a different amount
    assert matching.match_all([txn("X9")], [pay(account=uuid4())]) == []       # another account
    assert matching.match_all([txn("X9")], [pay(minutes=45)]) == []            # too far apart
    assert matching.match_all([txn("X9")], [pay(direction="out")]) == []       # money the other way
    assert matching.match_all([txn(ref="R5", direction="out")], [pay(ref="R5")]) == []


def test_two_equally_good_candidates_are_left_to_a_person() -> None:
    assert matching.match_all([txn("X9")], [pay(minutes=1), pay(minutes=1)]) == []
    [m] = matching.match_all([txn("X9")], [pay(minutes=1), pay(minutes=14)])   # one is clearly closer
    assert m.confidence == D("0.7")


def test_each_stage_runs_only_on_what_the_last_left() -> None:
    first, second = txn("R1", amount="100"), txn("R2", amount="50")
    paid_by_ref, paid_by_rule = pay(amount="100", ref="R1"), pay(amount="50", minutes=1)
    stages = {m.txn_id: m.stage for m in matching.match_all([first, second], [paid_by_ref, paid_by_rule])}
    assert stages == {first.id: "exact_reference", second.id: "rule"}


def test_one_transaction_can_pay_several_payments_and_several_transactions_one_payment() -> None:
    big = txn("R1", amount="300")
    one, two, three = (pay(amount="100", ref="R1", minutes=m) for m in (0, 1, 2))
    proposals = matching.match_all([big], [one, two, three])
    assert sum(m.amount for m in proposals) == 300 and len(proposals) == 3      # one payment for three invoices
    invoice = pay(amount="300", ref="R1")
    halves = [txn("R1", amount="100", minutes=m) for m in (0, 1, 2)]
    proposals = matching.match_all(halves, [invoice])
    assert sum(m.amount for m in proposals) == 300 and len(proposals) == 3      # part payments


def test_amounts_already_matched_are_not_matched_again() -> None:
    t = Txn(uuid4(), ACC, "R1", D("40"), T0)                                   # only 40 of it is still unmatched
    p = Pay(uuid4(), ACC, D("100"), T0, "R1")
    [m] = matching.match_all([t], [p])
    assert m.amount == 40
    assert matching.match_all([Txn(uuid4(), ACC, "R1", D("0"), T0)], [p]) == []


@given(st.lists(st.tuples(st.integers(1, 5), st.integers(0, 20), st.sampled_from(["R1", "R2", "R3", None])),
                min_size=1, max_size=8),
       st.lists(st.tuples(st.integers(1, 5), st.integers(0, 20), st.sampled_from(["R1", "R2", "R3", None])),
                min_size=1, max_size=8))
@settings(max_examples=300, deadline=None)
def test_matching_never_uses_more_than_there_is(t_spec, p_spec) -> None:  # type: ignore[no-untyped-def]
    txns = [txn(ref=r or "NOREF", amount=str(a * 10), minutes=m) for a, m, r in t_spec]
    pays = [pay(amount=str(a * 10), minutes=m, ref=r) for a, m, r in p_spec]
    proposals = matching.match_all(txns, pays)
    used_t: dict = {}  # type: ignore[type-arg]
    used_p: dict = {}  # type: ignore[type-arg]
    for m in (m for m in proposals if m.apply):
        used_t[m.txn_id] = used_t.get(m.txn_id, D(0)) + m.amount
        used_p[m.pay_id] = used_p.get(m.pay_id, D(0)) + m.amount
        assert m.amount > 0
    assert all(used_t[t.id] <= t.unmatched for t in txns if t.id in used_t)
    assert all(used_p[p.id] <= p.unmatched for p in pays if p.id in used_p)
    assert matching.match_all(list(reversed(txns)), list(reversed(pays))) == matching.match_all(txns, pays)

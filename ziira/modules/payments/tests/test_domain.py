"""Unit tests for Payments' pure rules: amounts, phone fingerprints, bank statements and the matching engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.payments.domain import matching, mobile_money, statements
from ziira.modules.payments.domain.matching import Pay, Txn
from ziira.sdk import ValidationFailed

D = Decimal


# --------------------------------------------------------------------------- phone numbers and amounts
def test_masking_and_fingerprints() -> None:
    assert mobile_money.mask_phone("254712345678") == "2547****678"
    assert mobile_money.mask_phone("a" * 64) == "hashed" and mobile_money.mask_phone("123") == "****"
    a, b = mobile_money.phone_fingerprint("254712345678"), mobile_money.phone_fingerprint("+254 712 345 678")
    assert a == b and len(a) == 64 and "254712345678" not in a
    assert mobile_money.phone_fingerprint(a.upper()) == a                                # an already-hashed number is kept
    assert mobile_money.phone_fingerprint("0722000000") != a


@pytest.mark.parametrize(("value", "ok"), [("100", True), ("100.50", True), ("1,500", True), (250, True),
                                           ("0", False), ("-5", False), ("1.005", False), ("NaN", False),
                                           ("abc", False), ("", False), ("Infinity", False)])
def test_amounts(value: object, ok: bool) -> None:
    if ok:
        assert mobile_money.parse_amount(value) > 0
    else:
        with pytest.raises(ValidationFailed):
            mobile_money.parse_amount(value)


def test_prompt_amount_limits() -> None:
    check = partial(mobile_money.check_prompt_amount, minimum=D("1"), maximum=D("150000"), whole=True)
    assert check(D("1")) == 1
    assert check(D("150000")) == 150000
    for bad in (D("0"), D("150001"), D("10.50"), D("-5")):
        with pytest.raises(ValidationFailed):
            check(bad)
    assert mobile_money.check_prompt_amount(D("10.50"), minimum=D("1"), maximum=None, whole=False) == D("10.50")
    assert mobile_money.check_prompt_amount(D("999999"), minimum=D("1"), maximum=None, whole=False) == 999999


def test_statement_amounts_ignore_a_leading_currency_word() -> None:
    assert statements.statement_amount("USD 1,200.50") == D("1200.50") and statements.statement_amount("-") == 0
    for bad in ("NaN", "Infinity", "-5", "1.2.3"):
        with pytest.raises(ValueError):
            statements.statement_amount(bad)


# --------------------------------------------------------------------------- statements
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
    rows = "\n".join(f"2026-10-13,x,R{i},,1" for i in range(statements.MAX_ROWS + 1))
    with pytest.raises(ValidationFailed, match="at most"):
        statements.parse_bank_statement("Date,Description,Reference,Debit,Credit\n" + rows)


def test_a_bank_statement_is_read_in_the_time_zone_given() -> None:
    from zoneinfo import ZoneInfo

    csv_text = "Date,Description,Reference,Debit,Credit\n2026-10-13 23:30:00,Deposit,R1,,10\n"
    nairobi = statements.parse_bank_statement(csv_text, tz=ZoneInfo("Africa/Nairobi")).rows[0].time
    assert nairobi.utcoffset() == timedelta(hours=3) and nairobi.astimezone(UTC).hour == 20


# --------------------------------------------------------------------------- matching
T0 = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)
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

"""Intelligence checks and Command Center figures of Payments, run through the real engine on real payments."""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.payments_helpers import PAY, make_payments_shop, record
from tests.stock_helpers import system
from ziira.modules.intel.services import engine
from ziira.modules.payments.pulse import PaymentsPulse

INTEL = "/api/v1/intel"
TODAY = date(2026, 10, 14)


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_payments_shop(client, registry, "Pay Intel Co")
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "command")
    s["juja_till"] = client.post(f"{PAY}/accounts", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "branch_id": str(s["juja"]), "kind": "mobile_money",
        "name": "Juja till", "shortcode": "700001", "provider": "fake", "provider_config": {"till_type": "till"}}).json()["id"]
    return s


def run(shop, *codes):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=TODAY, only=set(codes))


def found(client, shop, code, status=None):  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params={"check_code": code, **(
        {"status": status} if status else {})})
    assert r.status_code == 200, r.text
    return r.json()


def detail(client, shop, finding):  # type: ignore[no-untyped-def]
    return client.get(f"{INTEL}/findings/{finding['id']}", headers=shop["owner"]).json()


def sql(shop, statement, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text(statement), {"t": str(shop["tenant_id"]), "c": str(shop["company_id"]), **params})


def tune(client, shop, code, **params):  # type: ignore[no-untyped-def]
    run(shop, code)                                   # makes sure the check is known to the business
    r = client.patch(f"{INTEL}/checks/{code}", headers=shop["owner"], json={"params": params})
    assert r.status_code == 200, r.text


def pay(client, shop, amount, day, *, age_hours=48, account=None, ref=None, **kw):  # type: ignore[no-untyped-def]
    """Record a payment through the API and make it `age_hours` old."""
    r = record(client, shop, amount=amount, business_date=day, payment_account_id=account or shop["till"],
               external_ref=ref, **kw)
    assert r.status_code == 201, r.text
    sql(shop, "update payments.payment set created_at = now() - make_interval(hours => :h) where id = :i",
        h=age_hours, i=r.json()["id"])
    return r.json()


def txn(shop, account, ref, amount, days_ago, status="unmatched", direction="in"):  # type: ignore[no-untyped-def]
    sql(shop, "insert into payments.external_transaction (tenant_id, payment_account_id, source, external_ref, "
              "txn_time, direction, amount, raw, match_status) values (:t, :a, 'daraja_c2b', :r, "
              "now() - make_interval(days => :d), :dir, :amt, '{}', :s)",
        a=account, r=ref, d=days_ago, amt=amount, s=status, dir=direction)


def intents(shop, account, status, n, branch=None, fixed_day=False):  # type: ignore[no-untyped-def]
    """Payment prompts: created now, or on the fixed test day (for checks run as of that day)."""
    for _ in range(n):
        sql(shop, "insert into payments.payment_intent (tenant_id, payment_account_id, kind, amount, phone_masked, "
                  "status, company_id, branch_id, created_at) values (:t, :a, 'stk_push', 100, '2547****1', :s, :c, :b, "
                  "coalesce(cast(:at as timestamptz), now()))",
            a=account, s=status, b=str(branch or shop["branch_id"]),
            at=f"{TODAY.isoformat()} 09:00+00" if fixed_day else None)


def close_row(shop, day, variance, status="locked", branch=None, explanation=None):  # type: ignore[no-untyped-def]
    return sql(shop, "insert into payments.daily_close (tenant_id, company_id, branch_id, business_date, status, "
                     "variance, explanation) values (:t, :c, :b, :d, :s, :v, :e) returning id",
               b=str(branch or shop["branch_id"]), d=day, s=status, v=variance, e=explanation).scalar_one()


# --------------------------------------------------------------------------- unlinked receipts
def test_unlinked_receipts_group_per_day_and_account_and_ignore_linked_or_recent(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.unlinked_receipts"
    pay(client, shop, "300.00", "2026-10-10")
    pay(client, shop, "200.00", "2026-10-10")
    pay(client, shop, "70.00", "2026-10-11")
    pay(client, shop, "999.00", "2026-10-10", party_type="customer", party_id=str(uuid4()))      # explained
    pay(client, shop, "888.00", "2026-10-10", age_hours=1)                                      # too recent
    pay(client, shop, "500.00", "2026-10-10", account=shop["cash"], method="cash", party_type="customer",
        party_id=str(uuid4()))
    run(shop, code)
    items = {f["period_start"]: f for f in found(client, shop, code)}
    assert set(items) == {"2026-10-10", "2026-10-11"}
    big = items["2026-10-10"]
    assert Dec(big["amount"]) == 500 and big["severity"] == "medium" and big["branch_id"] == str(shop["branch_id"])
    assert "2 payments" in big["summary"] and "500.00" in big["summary"] and "HQ M-Pesa till" in big["summary"]
    d = detail(client, shop, big)
    assert len(d["records"]) == 2 and d["records"][0]["type"] == "payments.payment"
    assert Dec(items["2026-10-11"]["amount"]) == 70
    # linking the payments clears the finding (it is a state)
    sql(shop, "update payments.payment set party_type = 'customer', party_id = :p where business_date = '2026-10-10'",
        p=str(uuid4()))
    run(shop, code)
    assert [f["period_start"] for f in found(client, shop, code)] == ["2026-10-11"]
    assert found(client, shop, code, "resolved")[0]["period_start"] == "2026-10-10"


def test_unlinked_receipts_waiting_time_is_tunable(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.unlinked_receipts"
    pay(client, shop, "41.00", "2026-10-12", age_hours=20)
    run(shop, code)
    assert not [f for f in found(client, shop, code) if f["period_start"] == "2026-10-12"]
    tune(client, shop, code, hours=12)
    run(shop, code)
    assert [f for f in found(client, shop, code) if f["period_start"] == "2026-10-12"]


# --------------------------------------------------------------------------- unmatched transactions
def test_unmatched_transactions_after_the_waiting_days(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.unmatched_transactions"
    txn(shop, shop["till"], "UM1", "120.00", 5)
    txn(shop, shop["till"], "UM2", "80.00", 5, status="proposed")
    txn(shop, shop["till"], "UM3", "999.00", 5, status="matched")      # matched: silent
    txn(shop, shop["till"], "UM4", "999.00", 0)                        # too recent: silent
    txn(shop, shop["till"], "UM5", "999.00", 5, direction="out")       # money out: not a receipt
    run(shop, code)
    items = found(client, shop, code)
    assert len(items) == 1
    f = items[0]
    assert Dec(f["amount"]) == 200 and f["severity"] == "medium" and f["branch_id"] == str(shop["branch_id"])
    assert "2 transactions" in f["summary"] and "200.00" in f["summary"]
    assert {r["label"] for r in detail(client, shop, f)["records"]} == {"Transaction UM1", "Transaction UM2"}
    sql(shop, "update payments.external_transaction set match_status = 'matched' where external_ref in ('UM1', 'UM2')")
    run(shop, code)
    assert found(client, shop, code) == []


def test_unmatched_transactions_waiting_days_are_tunable(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.unmatched_transactions"
    txn(shop, shop["till"], "UM6", "15.00", 1)
    run(shop, code)
    assert found(client, shop, code) == []
    tune(client, shop, code, unmatched_days=0)
    run(shop, code)
    assert any(Dec(f["amount"]) == 15 for f in found(client, shop, code))


# --------------------------------------------------------------------------- close variance and missing close
def test_close_variance_beyond_the_limit(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.close_variance"
    big = close_row(shop, "2026-10-01", "-750.00", explanation="Float given out")     # over by 750 (5x the limit)
    close_row(shop, "2026-10-02", "300.00")                                           # short by 300
    close_row(shop, "2026-10-03", "100.00")                                           # exactly the limit: silent
    close_row(shop, "2026-10-04", "-99.99")                                           # inside: silent
    close_row(shop, "2026-10-05", "5000.00", status="open")                           # not closed yet: silent
    run(shop, code)
    items = {f["period_start"]: f for f in found(client, shop, code)}
    assert set(items) == {"2026-10-01", "2026-10-02"}
    assert items["2026-10-01"]["severity"] == "high" and Dec(items["2026-10-01"]["amount"]) == 750
    assert "over" in items["2026-10-01"]["summary"] and "Float given out" in items["2026-10-01"]["summary"]
    assert items["2026-10-02"]["severity"] == "medium" and "short" in items["2026-10-02"]["summary"]
    assert "No explanation" in items["2026-10-02"]["summary"]
    assert items["2026-10-02"]["branch_id"] == str(shop["branch_id"])
    assert detail(client, shop, items["2026-10-01"])["records"][0]["id"] == str(big)
    shown = detail(client, shop, items["2026-10-01"])
    assert shown["check_title"] == "Daily close with a variance" and shown["value_kind"] == "money"   # for the Details card
    # an event: it stays when the data no longer shows it, and a higher limit only affects new runs
    sql(shop, "update payments.daily_close set variance = 0 where id = :i", i=str(big))
    run(shop, code)
    assert "2026-10-01" in {f["period_start"] for f in found(client, shop, code)}
    tune(client, shop, code, variance_limit="400.00")
    close_row(shop, "2026-10-06", "350.00")
    run(shop, code)
    assert "2026-10-06" not in {f["period_start"] for f in found(client, shop, code)}


def test_missing_close_flags_a_day_with_takings_and_no_close(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.missing_close"
    pay(client, shop, "60.00", "2026-10-08")                       # HQ, no close
    pay(client, shop, "40.00", "2026-10-08")
    pay(client, shop, "25.00", "2026-10-09")
    close_row(shop, "2026-10-09", "0")                            # closed: silent
    pay(client, shop, "30.00", "2026-10-10")
    close_row(shop, "2026-10-10", "0", status="reopened")         # reopened is not closed
    pay(client, shop, "77.00", "2026-10-14")                       # today: the day is not over
    pay(client, shop, "55.00", "2026-10-12", account=shop["juja_till"], branch_id=str(shop["juja"]))
    run(shop, code)
    items = {(f["period_start"], f["branch_id"]): f for f in found(client, shop, code)}
    hq = str(shop["branch_id"])
    assert {("2026-10-08", hq), ("2026-10-10", hq), ("2026-10-12", str(shop["juja"]))} <= set(items)
    assert not {("2026-10-09", hq), ("2026-10-14", hq)} & set(items)       # closed, and a day not yet over
    first = items[("2026-10-08", str(shop["branch_id"]))]
    assert Dec(first["amount"]) == 100 and first["severity"] == "medium"
    assert "100.00" in first["summary"] and "2 payments" in first["summary"] and "Head office" in first["summary"]
    # making the close clears it
    close_row(shop, "2026-10-08", "0")
    run(shop, code)
    assert ("2026-10-08", str(shop["branch_id"])) not in {(f["period_start"], f["branch_id"]) for f in found(client, shop, code)}
    # the grace period is tunable: with 5 days' grace only days up to 10-09 count
    tune(client, shop, code, grace_days=5)
    run(shop, code)
    assert found(client, shop, code) == []


# --------------------------------------------------------------------------- settlement
def test_settlement_missing_short_or_more_than_received(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.settlement_mismatch"
    acc = shop["juja_till"]
    txn(shop, acc, "S1", "600.00", 10)
    txn(shop, acc, "S2", "400.00", 8)
    txn(shop, acc, "S3", "9000.00", 1)                           # inside the grace days: not counted yet
    run(shop, code)
    f = next(x for x in found(client, shop, code) if x["entity_id"] == acc)
    assert Dec(f["amount"]) == 1000 and "1,000.00" in f["summary"] and f["branch_id"] == str(shop["juja"])
    # settle 1000 less a 20 fee: the settled total (paid out) is 1000 -> agrees
    r = client.post(f"{PAY}/settlements", headers=shop["owner"], json={
        "from_account_id": acc, "to_account_id": shop["bank"], "amount": "980.00", "fee": "20.00",
        "business_date": "2026-10-09", "reference": "SET-1"})
    assert r.status_code in (200, 201), r.text
    run(shop, code)
    assert not [x for x in found(client, shop, code) if x["entity_id"] == acc]
    assert [x for x in found(client, shop, code, "resolved") if x["entity_id"] == acc]
    # a settlement that falls well short of what was received
    sql(shop, "update payments.payment set amount = 700 where external_ref = 'SET-1' and direction = 'out'")
    run(shop, code)
    short = next(x for x in found(client, shop, code) if x["entity_id"] == acc)
    assert Dec(short["amount"]) == 300 and "only" in short["summary"] and short["status"] != "resolved"
    assert detail(client, shop, short)["records"][0]["label"].startswith("Settlement")
    # more settled than received
    sql(shop, "update payments.payment set amount = 1500 where external_ref = 'SET-1' and direction = 'out'")
    run(shop, code)
    more = next(x for x in found(client, shop, code) if x["entity_id"] == acc)
    assert Dec(more["amount"]) == 500 and "more than" in more["summary"]
    # tolerance: a 60% tolerance accepts a difference of 500 on 1000
    tune(client, shop, code, tolerance_percent="60.0")
    run(shop, code)
    assert not [x for x in found(client, shop, code) if x["entity_id"] == acc]


def test_settlement_check_is_silent_for_an_account_with_no_activity(client, shop) -> None:  # type: ignore[no-untyped-def]
    quiet = client.post(f"{PAY}/accounts", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "kind": "mobile_money", "name": "Quiet till", "shortcode": "700002",
        "provider": "fake", "provider_config": {"till_type": "till"}}).json()["id"]
    run(shop, "payments.settlement_mismatch")
    assert not [x for x in found(client, shop, "payments.settlement_mismatch") if x["entity_id"] == quiet]


# --------------------------------------------------------------------------- duplicates
def test_possible_duplicate_payments(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.possible_duplicates"
    a = pay(client, shop, "250.00", "2026-10-07", age_hours=100, phone="0712000111", ref="DUP-A")
    b = pay(client, shop, "250.00", "2026-10-07", age_hours=100, phone="0712000111", ref="DUP-B")
    c = pay(client, shop, "250.00", "2026-10-07", age_hours=100, phone="0712000222", ref="DUP-C")   # other payer
    d = pay(client, shop, "260.00", "2026-10-07", age_hours=100, phone="0712000111", ref="DUP-D")   # other amount
    e = pay(client, shop, "250.00", "2026-10-07", age_hours=60, phone="0712000111", ref="DUP-E")    # hours apart
    run(shop, code)
    items = found(client, shop, code)
    assert len(items) == 1
    f = items[0]
    assert Dec(f["amount"]) == 250 and f["severity"] == "medium" and f["branch_id"] == str(shop["branch_id"])
    assert {r["id"] for r in detail(client, shop, f)["records"]} == {a["id"], b["id"]}
    assert "250.00" in f["summary"] and a["number"] in f["summary"] and b["number"] in f["summary"]
    assert {c["id"], d["id"], e["id"]}.isdisjoint({r["id"] for r in detail(client, shop, f)["records"]})
    # a wider window pulls the later payment in
    tune(client, shop, code, window_minutes=60 * 50)
    run(shop, code)
    assert len(found(client, shop, code)) == 3          # A-B, A-E, B-E


# --------------------------------------------------------------------------- failing prompts
def test_failing_prompts_need_volume_and_a_high_rate(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.failing_prompts"
    intents(shop, shop["till"], "failed", 3, fixed_day=True)
    intents(shop, shop["till"], "timeout", 2, fixed_day=True)
    intents(shop, shop["till"], "succeeded", 5, fixed_day=True)                    # 5 of 10 failed: 50%
    intents(shop, shop["till"], "pending", 20, fixed_day=True)                     # still waiting: not counted
    intents(shop, shop["juja_till"], "failed", 3, fixed_day=True)                  # too few attempts: silent
    run(shop, code)
    items = found(client, shop, code)
    assert len(items) == 1
    f = items[0]
    assert f["entity_id"] == shop["till"] and f["severity"] == "medium" and Dec(f["value"]) == 50
    assert "5 of 10" in f["summary"] and "50%" in f["summary"] and f["branch_id"] == str(shop["branch_id"])
    tune(client, shop, code, failure_percent="60.0")
    sql(shop, "delete from intel.finding_event where finding_id in "
              "(select id from intel.finding where check_code = 'payments.failing_prompts')")
    sql(shop, "delete from intel.finding where check_code = 'payments.failing_prompts'")
    run(shop, code)
    assert found(client, shop, code) == []
    tune(client, shop, code, failure_percent="40.0", min_attempts=11)
    run(shop, code)
    assert found(client, shop, code) == []


def test_failing_prompts_are_not_flagged_when_that_is_normal_for_the_account(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.intel.domain.model import Baseline
    from ziira.modules.intel.public import CheckContext
    from ziira.modules.payments.intel_checks import FailingPaymentPrompts, PromptFailureRate

    ctx_args = dict(company_id=shop["company_id"], today=TODAY, params={"min_attempts": 5, "failure_percent": "50.0",
                                                                         "days": 3})
    check = FailingPaymentPrompts()
    key = f"{PromptFailureRate.code}"
    normal = Baseline(mean=Dec(60), stddev=Dec(5), p95=Dec(70), sample_size=30)
    unusual = Baseline(mean=Dec(5), stddev=Dec(3), p95=Dec(12), sample_size=30)
    young = Baseline(mean=Dec(5), stddev=Dec(3), p95=Dec(12), sample_size=3)
    with system(shop) as s:
        quiet = check.run(s, CheckContext(**ctx_args, baseline=lambda m, k: normal if m == key else None))
        loud = check.run(s, CheckContext(**ctx_args, baseline=lambda m, k: unusual if m == key else None))
        young_history = check.run(s, CheckContext(**ctx_args, baseline=lambda m, k: young if m == key else None))
    assert quiet == [] and len(loud) == 1 and len(young_history) == 1


def test_prompt_failure_baseline_samples(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.payments.intel_checks import PromptFailureRate

    with system(shop) as s:
        samples = PromptFailureRate().samples(s, shop["company_id"], date(2000, 1, 1), date(2100, 1, 1))
    by_key = {x.key: x.value for x in samples}
    assert by_key[shop["till"]] == 50 and shop["juja_till"] in by_key


# --------------------------------------------------------------------------- reversed after match
def test_payment_reversed_after_it_was_matched(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.reversed_after_match"
    p = pay(client, shop, "310.00", "2026-09-27", ref="REV-1")
    q = pay(client, shop, "120.00", "2026-09-27", ref="REV-2")                 # reversed but never matched: silent
    kept = pay(client, shop, "99.00", "2026-09-27", ref="REV-3")               # matched and kept: silent
    txn(shop, shop["till"], "REV-1", "310.00", 3, status="matched")
    txn(shop, shop["till"], "REV-3", "99.00", 3, status="matched")
    for ref, pid in (("REV-1", p["id"]), ("REV-3", kept["id"])):
        sql(shop, "insert into payments.match (tenant_id, external_transaction_id, payment_id, amount, stage, status) "
                  "select :t, t.id, :p, t.amount, 'exact_reference', 'applied' from payments.external_transaction t "
                  "where t.external_ref = :r", p=pid, r=ref)
    for pid in (p["id"], q["id"]):
        # undo any match first, as the service requires, then reverse
        sql(shop, "update payments.match set status = 'undone', undone_at = now() where payment_id = :p", p=pid)
        r = client.post(f"{PAY}/payments/{pid}/reverse", headers=shop["owner"], json={"reason": "customer disputed"})
        assert r.status_code == 200, r.text
    run(shop, code)
    items = found(client, shop, code)
    assert len(items) == 1
    f = items[0]
    assert Dec(f["amount"]) == 310 and f["severity"] == "medium" and f["branch_id"] == str(shop["branch_id"])
    assert "REV-1" in f["summary"] and "310.00" in f["summary"]
    assert detail(client, shop, f)["records"][0]["id"] == p["id"]
    sql(shop, "update payments.payment set status = 'posted' where id = :p", p=p["id"])
    run(shop, code)
    assert [x["id"] for x in found(client, shop, code)] == [f["id"]]            # an event: it stays


# --------------------------------------------------------------------------- manual payments with no evidence
def test_manual_payment_without_provider_evidence(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "payments.manual_without_evidence"
    big = pay(client, shop, "2500.00", "2026-09-28", ref="MAN-1")
    pay(client, shop, "1000.00", "2026-09-28", ref="MAN-2")                    # exactly the limit: flagged
    pay(client, shop, "999.99", "2026-09-28", ref="MAN-3")                     # under the limit: silent
    pay(client, shop, "5000.00", "2026-09-28", ref="MAN-4", age_hours=2)       # too recent: silent
    pay(client, shop, "5000.00", "2026-09-28", method="cash", account=shop["cash"])        # cash: out of scope
    backed = pay(client, shop, "4000.00", "2026-09-28", ref="MAN-5")           # has a matched provider transaction
    txn(shop, shop["till"], "MAN-5", "4000.00", 3, status="matched")
    sql(shop, "insert into payments.match (tenant_id, external_transaction_id, payment_id, amount, stage, status) "
              "select :t, id, :p, amount, 'exact_reference', 'applied' from payments.external_transaction "
              "where external_ref = 'MAN-5'", p=backed["id"])
    run(shop, code)
    items = {f["summary"].split()[1]: f for f in found(client, shop, code)}
    assert len(items) == 2
    f = items[big["number"]]
    assert Dec(f["amount"]) == 2500 and f["severity"] == "medium" and f["branch_id"] == str(shop["branch_id"])
    assert "2,500.00" in f["summary"] and "mobile money" in f["summary"]
    assert detail(client, shop, f)["records"][0]["id"] == big["id"]
    # evidence arrives and is matched: the finding closes
    txn(shop, shop["till"], "MAN-1", "2500.00", 1, status="matched")
    sql(shop, "insert into payments.match (tenant_id, external_transaction_id, payment_id, amount, stage, status) "
              "select :t, id, :p, amount, 'manual', 'applied' from payments.external_transaction "
              "where external_ref = 'MAN-1'", p=big["id"])
    run(shop, code)
    assert big["number"] not in {f["summary"].split()[1] for f in found(client, shop, code)}
    tune(client, shop, code, amount_limit="1001.00")
    run(shop, code)
    assert found(client, shop, code) == []


# --------------------------------------------------------------------------- the Command Center figures
# (the source is called directly: storing figures is the Command Center's job and is tested there)
def test_pulse_figures_company_wide_and_per_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = "2026-09-20"
    # HQ: 300 mobile (unlinked), 150 mobile (linked), 100 bank (unlinked), 40 cash (linked)
    pay(client, shop, "300.00", day)
    pay(client, shop, "150.00", day, party_type="customer", party_id=str(uuid4()))
    pay(client, shop, "100.00", day, method="bank", account=shop["bank"], branch_id=str(shop["branch_id"]))
    pay(client, shop, "40.00", day, method="cash", account=shop["cash"], party_type="customer", party_id=str(uuid4()))
    # Juja: 70 mobile (unlinked)
    pay(client, shop, "70.00", day, account=shop["juja_till"], branch_id=str(shop["juja"]))
    # a settlement and a payment out are not takings
    r = client.post(f"{PAY}/settlements", headers=shop["owner"], json={
        "from_account_id": shop["till"], "to_account_id": shop["bank"], "amount": "200.00", "fee": "0",
        "business_date": day, "reference": "PULSE-SET"})
    assert r.status_code in (200, 201), r.text
    client.post(f"{PAY}/payments", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "method": "mobile_money",
        "direction": "out", "amount": "55.00", "payment_account_id": shop["till"], "business_date": day})
    # failed prompts created now (the pulse day is today in the company's zone for these)
    with system(shop) as s:
        before = {(f.metric, f.branch_id): f.value for f in PaymentsPulse().figures(s, shop["company_id"], date.today())}
    intents(shop, shop["till"], "failed", 2)
    intents(shop, shop["juja_till"], "timeout", 1, branch=shop["juja"])
    with system(shop) as s:
        figures = PaymentsPulse().figures(s, shop["company_id"], date(2026, 9, 20))
    got = {(f.metric, f.branch_id): f.value for f in figures}
    hq, juja = shop["branch_id"], shop["juja"]
    assert got[("payments.received", None)] == 660 and got[("payments.received", hq)] == 590
    assert got[("payments.received", juja)] == 70
    assert got[("payments.received_mobile_money", None)] == 520 and got[("payments.received_mobile_money", hq)] == 450
    assert got[("payments.received_bank", None)] == 100 and got[("payments.received_bank", juja)] == 0
    assert got[("payments.unmatched_amount", None)] == 470 and got[("payments.unmatched_amount", hq)] == 400
    assert got[("payments.unmatched_count", None)] == 3 and got[("payments.unmatched_count", juja)] == 1
    assert got[("payments.failed_prompts", None)] == 0           # none created on that day
    with system(shop) as s:
        today = {(f.metric, f.branch_id): f.value for f in PaymentsPulse().figures(s, shop["company_id"], date.today())}
    failed = "payments.failed_prompts"
    assert today[(failed, None)] - before[(failed, None)] == 3
    assert today[(failed, hq)] - before[(failed, hq)] == 2 and today[(failed, juja)] - before[(failed, juja)] == 1

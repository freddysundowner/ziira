"""Purchasing's Intelligence checks and Command Center figures, run through the real engine on real purchases."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.purchasing_helpers import PUR, approved_order, bill_for, make_purchasing_shop, receive
from tests.stock_helpers import P, system
from ziira.modules.intel.services import engine
from ziira.modules.purchasing.pulse import PurchasingPulse

INTEL = "/api/v1/intel"
TODAY = datetime.now(ZoneInfo("Africa/Nairobi")).date()          # the day Purchasing itself stamps new records with
ISO = TODAY.isoformat()


def setup_shop(client, registry, name: str):  # type: ignore[no-untyped-def]
    import ziira.modules.command.hooks  # noqa: F401
    import ziira.modules.intel.hooks  # noqa: F401
    import ziira.modules.purchasing.hooks  # noqa: F401

    s = make_purchasing_shop(client, registry, name)
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "command")
    return s


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = setup_shop(client, registry, "Buy Intel Co")
    lst = client.post(f"{P}/price-lists", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "name": "Retail", "is_default": True}).json()["id"]
    r = client.put(f"{P}/price-lists/{lst}/prices", headers=s["owner"], json={
        "product_id": s["cement"], "price": "116.00", "valid_from": "2026-01-01"})        # 100.00 before 16% VAT
    assert r.status_code == 200, r.text
    s["currency"] = one(s, "select base_currency from kernel.company where id = :c", c=str(s["company_id"]))
    return s


# --------------------------------------------------------------------------- helpers
def view(shop, sid: str):  # type: ignore[no-untyped-def]
    """The shop, buying from another supplier."""
    return {**shop, "supplier": sid}


def new_supplier(client, shop, name: str) -> str:  # type: ignore[no-untyped-def]
    r = client.post(f"{PUR}/suppliers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": uuid4().hex[:8], "name": name, "payment_terms_days": 30})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def seed(shop, sid: str, cost: str, days_ago: int) -> None:  # type: ignore[no-untyped-def]
    """An earlier price the supplier charged (as a past receipt would have left it)."""
    with system(shop) as s:
        s.execute(text(
            "insert into purchasing.supplier_price (tenant_id, supplier_id, product_id, unit_cost, effective_date, "
            "source_type, source_id) values (:t, :s, :p, :c, :d, 'goods_receipt', :i)"),
            {"t": str(shop["tenant_id"]), "s": sid, "p": shop["cement"], "c": cost, "d": TODAY - timedelta(days=days_ago),
             "i": str(uuid4())})


def deliver(client, shop, sid: str, cost: str, qty: str = "10"):  # type: ignore[no-untyped-def]
    order = approved_order(client, view(shop, sid), qty=qty, cost=cost)
    receipt = receive(client, view(shop, sid), order)
    assert receipt.status_code == 201, receipt.text
    return order, receipt.json()


def posted_bill(client, shop, sid: str, invoice: str, qty: str = "10", cost: str = "50.00"):  # type: ignore[no-untyped-def]
    """A posted bill for goods just received (qty x cost plus 16% tax)."""
    _, receipt = deliver(client, shop, sid, cost, qty)
    bill = bill_for(client, view(shop, sid), receipt, invoice=invoice, bill_date=ISO).json()
    done = client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["owner"])
    assert done.status_code == 200 and done.json()["status"] == "posted", done.text
    return done.json(), receipt


def pay(client, shop, bill, amount: str):  # type: ignore[no-untyped-def]
    r = client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"], json={"amount": amount, "method": "cash"})
    assert r.status_code == 200, r.text


def run_check(shop, code: str):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=TODAY, only={code})


def findings(shop, code: str, sid: str | None = None) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        rows = s.execute(text(
            "select id, entity_id, severity, amount, branch_id, status, summary, value, expected_value, evidence "
            "from intel.finding where check_code = :c order by first_seen_at"), {"c": code}).all()
    return [r for r in rows if sid is None or str(r.entity_id) == sid]


def only_one(shop, code: str, sid: str):  # type: ignore[no-untyped-def]
    found = findings(shop, code, sid)
    assert len(found) == 1, [f.summary for f in found]
    return found[0]


def record_ids(finding) -> set[str]:  # type: ignore[no-untyped-def]
    return {r["id"] for r in finding.evidence["records"]}


def tune(client, shop, code: str, **params: str | int) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"{INTEL}/checks/{code}", headers=shop["owner"], json={"params": params})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- supplier price rise
def test_a_price_well_above_the_earlier_ones_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.supplier_price_rise"
    risen, steep, small, thin = (new_supplier(client, shop, n) for n in ("Risen", "Steep", "Small", "Thin"))
    for sid in (risen, steep, small):
        for days in (60, 40, 20):
            seed(shop, sid, "100", days)
    seed(shop, thin, "100", 20)                                                      # only one earlier price
    _, receipt = deliver(client, shop, risen, "125")                                 # 25% above the 100 average
    deliver(client, shop, steep, "140")                                              # 40%
    deliver(client, shop, small, "105")                                              # 5%: normal
    deliver(client, shop, thin, "200")                                               # too little history to say
    run_check(shop, code)
    f = only_one(shop, code, risen)
    cur = shop["currency"]
    assert (f.severity, f.amount, str(f.branch_id), f.status) == ("medium", Dec("250.00"), str(shop["branch_id"]), "new")
    assert f"{cur} 125.00" in f.summary and f"{cur} 100.00" in f.summary and "25.0%" in f.summary
    assert f"{cur} 250.00 more" in f.summary and "Risen" in f.summary
    assert (f.value, f.expected_value) == (Dec(125), Dec(100))
    assert receipt["id"] in record_ids(f) and risen in record_ids(f)
    assert (only_one(shop, code, steep).severity, only_one(shop, code, steep).amount) == ("high", Dec("400.00"))
    assert findings(shop, code, small) == [] and findings(shop, code, thin) == []


def test_a_price_rise_closes_when_the_limit_is_raised_and_comes_back_when_it_is_lowered(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.supplier_price_rise"
    sid = new_supplier(client, shop, "Tuned")
    for days in (50, 30, 10):
        seed(shop, sid, "100", days)
    deliver(client, shop, sid, "120")
    run_check(shop, code)
    assert only_one(shop, code, sid).status == "new"
    tune(client, shop, code, rise_percent="30.0")                                    # 20% is now normal
    assert run_check(shop, code).resolved >= 1
    assert only_one(shop, code, sid).status == "resolved"
    tune(client, shop, code, rise_percent="10.0")
    assert run_check(shop, code).reopened >= 1
    assert only_one(shop, code, sid).status != "resolved"
    tune(client, shop, code, days=5)                                                 # the earlier prices fall outside
    run_check(shop, code)
    assert only_one(shop, code, sid).status == "resolved"
    tune(client, shop, code, days=90)


# --------------------------------------------------------------------------- order above the usual price
def test_an_open_order_priced_above_the_usual_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.order_above_usual_price"
    dear, fair, thin = (new_supplier(client, shop, n) for n in ("Dear", "Fair", "Newcomer"))
    for sid in (dear, fair):
        for days in (90, 60, 30):
            seed(shop, sid, "50", days)
    seed(shop, thin, "50", 30)
    order = approved_order(client, view(shop, dear), qty="10", cost="70.00")        # 40% above 50
    approved_order(client, view(shop, fair), qty="10", cost="52.00")                  # 4%
    approved_order(client, view(shop, thin), qty="10", cost="90.00")                  # nothing to compare with
    run_check(shop, code)
    f = only_one(shop, code, order["id"])
    cur = shop["currency"]
    assert (f.severity, f.amount, str(f.branch_id)) == ("high", Dec("200.00"), str(shop["branch_id"]))
    assert f"{cur} 70.00" in f.summary and f"{cur} 50.00" in f.summary and "40.0%" in f.summary
    assert order["number"] in f.summary and dear in record_ids(f)
    assert len(findings(shop, code)) == 1
    tune(client, shop, code, above_percent="50.0")
    assert run_check(shop, code).resolved == 1
    tune(client, shop, code, above_percent="10.0")
    assert run_check(shop, code).reopened == 1
    assert client.post(f"{PUR}/orders/{order['id']}/cancel", headers=shop["owner"]).status_code == 200
    assert run_check(shop, code).resolved == 1                                       # a cancelled order is no longer open


# --------------------------------------------------------------------------- margin squeeze
def test_a_cost_rise_that_leaves_a_thin_margin_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.margin_squeeze"
    thin, fine, loss, edge = (new_supplier(client, shop, n) for n in ("Thin", "Fine", "Loss", "Edge"))
    for sid, base in ((thin, "60"), (fine, "60"), (loss, "100"), (edge, "100")):
        seed(shop, sid, base, 40)
        seed(shop, sid, base, 20)
    deliver(client, shop, thin, "92")        # +53%; sells at 116 with 16% tax = 100 before tax: margin 8%
    deliver(client, shop, fine, "80")        # +33%; margin 20%
    deliver(client, shop, loss, "125")       # +25%; margin -25%
    deliver(client, shop, edge, "105")       # exactly +5%: not above the 5% limit
    run_check(shop, code)
    by_supplier = {r["id"] for x in findings(shop, code) for r in x.evidence["records"]}
    assert thin in by_supplier and loss in by_supplier and fine not in by_supplier and edge not in by_supplier
    mine = next(x for x in findings(shop, code) if thin in record_ids(x))
    assert (mine.severity, mine.value, mine.expected_value, mine.branch_id) == ("medium", Dec("8.00"), Dec(10), None)
    assert "8.0%" in mine.summary and f"{shop['currency']} 92.00" in mine.summary 
    worse = next(x for x in findings(shop, code) if loss in record_ids(x))
    assert (worse.severity, worse.value) == ("high", Dec("-25.00"))
    tune(client, shop, code, min_margin_percent="5.0")                               # 8% is now acceptable
    run_check(shop, code)
    assert next(x for x in findings(shop, code) if thin in record_ids(x)).status == "resolved"
    assert next(x for x in findings(shop, code) if loss in record_ids(x)).status == "new"
    tune(client, shop, code, min_margin_percent="10.0")


# --------------------------------------------------------------------------- duplicate bills
def test_bills_that_look_entered_twice_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.duplicate_supplier_bill"
    same_amount, same_number, distinct = (new_supplier(client, shop, n) for n in ("Twice", "Renamed", "Distinct"))

    def draft(sid: str, invoice: str, cost: str) -> dict[str, Any]:
        _, receipt = deliver(client, shop, sid, cost)
        r = bill_for(client, view(shop, sid), receipt, invoice=invoice, bill_date=ISO)
        assert r.status_code == 201, r.text
        return r.json()  # type: ignore[no-any-return]

    a1, a2 = draft(same_amount, "INV-A", "50.00"), draft(same_amount, "INV-B", "50.00")
    b1, b2 = draft(same_number, "ABC-1", "50.00"), draft(same_number, "abc 1", "60.00")
    draft(distinct, "D-1", "50.00"), draft(distinct, "D-2", "70.00")
    run_check(shop, code)
    flagged = {frozenset(record_ids(f)) for f in findings(shop, code)}
    assert flagged == {frozenset({a1["id"], a2["id"]}), frozenset({b1["id"], b2["id"]})}
    by_amount = next(f for f in findings(shop, code) if a1["id"] in record_ids(f))
    assert (by_amount.severity, by_amount.amount, str(by_amount.branch_id)) == ("medium", Dec("580.00"),
                                                                              str(shop["branch_id"]))
    assert "the same amount within days" in by_amount.summary and a1["number"] in by_amount.summary
    by_number = next(f for f in findings(shop, code) if b1["id"] in record_ids(f))
    assert "the same supplier invoice number" in by_number.summary
    # the same amount ten days apart is not close enough, until the limit is widened
    with system(shop) as s:
        s.execute(text("update purchasing.supplier_bill set bill_date = :d where id = :i"),
                  {"d": TODAY - timedelta(days=10), "i": a1["id"]})
    assert run_check(shop, code).resolved == 1
    tune(client, shop, code, within_days=30)
    assert run_check(shop, code).reopened == 1
    assert client.post(f"{PUR}/bills/{a2['id']}/cancel", headers=shop["owner"]).status_code == 200
    assert run_check(shop, code).resolved == 1                                       # a cancelled bill is not a duplicate
    tune(client, shop, code, within_days=7)


def test_a_duplicate_that_was_already_paid_is_serious(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.duplicate_supplier_bill"
    sid = new_supplier(client, shop, "Paidtwice")
    first, _ = posted_bill(client, shop, sid, "PT-1")
    second, _ = posted_bill(client, shop, sid, "PT-2")
    pay(client, shop, second, "580.00")
    run_check(shop, code)
    f = next(x for x in findings(shop, code) if first["id"] in record_ids(x))
    assert f.severity == "high" and "already been paid" in f.summary


# --------------------------------------------------------------------------- duplicate payments
def test_paying_a_supplier_the_same_amount_twice_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.duplicate_supplier_payment"
    twice, fine = new_supplier(client, shop, "Twice paid"), new_supplier(client, shop, "Once paid")
    t1, _ = posted_bill(client, shop, twice, "TP-1")
    t2, _ = posted_bill(client, shop, twice, "TP-2")
    pay(client, shop, t1, "580.00")
    pay(client, shop, t2, "580.00")
    f1, f2 = posted_bill(client, shop, fine, "FP-1")[0], posted_bill(client, shop, fine, "FP-2")[0]
    pay(client, shop, f1, "580.00")
    pay(client, shop, f2, "200.00")
    old = new_supplier(client, shop, "Old pair")
    for invoice in ("OP-1", "OP-2"):
        bill, _ = posted_bill(client, shop, old, invoice)
        pay(client, shop, bill, "580.00")
        with system(shop) as s:
            s.execute(text("update purchasing.supplier_bill set bill_date = :d where id = :i"),
                      {"d": TODAY - timedelta(days=100), "i": bill["id"]})
    run_check(shop, code)
    f = only_one(shop, code, twice)
    assert (f.severity, f.amount, str(f.branch_id)) == ("high", Dec("580.00"), str(shop["branch_id"]))
    assert "the same amount within days" in f.summary and f"{shop['currency']} 580.00" in f.summary
    assert {t1["id"], t2["id"]} & record_ids(f) and len(f.evidence["records"]) == 3
    assert findings(shop, code, fine) == []
    assert findings(shop, code, old) == []                                           # those bills are 100 days old
    tune(client, shop, code, days=120)
    assert run_check(shop, code).created == 1
    assert only_one(shop, code, old).amount == Dec("580.00")
    tune(client, shop, code, days=60)


# --------------------------------------------------------------------------- bank details changed
def test_new_bank_details_are_flagged_and_more_so_once_money_has_gone_out(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.supplier_bank_changed"
    changed, first_only = new_supplier(client, shop, "Moved bank"), new_supplier(client, shop, "First bank")

    def set_details(sid: str, number: str) -> None:
        path = f"{PUR}/suppliers/{sid}/bank-accounts"
        proposed = client.post(path, headers=shop["fm"], json={
            "method": "bank", "bank_name": "KCB", "account_name": "Supplier", "account_no": number})
        assert proposed.status_code == 201, proposed.text
        done = client.post(f"{PUR}/bank-accounts/{proposed.json()['id']}/confirm", headers=shop["fm2"],
                           json={"confirmation_method": "phone_callback"})
        assert done.status_code == 200 and done.json()["status"] == "active", done.text

    set_details(first_only, "1111222233")                                            # a first set of details is no change
    set_details(changed, "2222333344")
    set_details(changed, "3333444455")
    run_check(shop, code)
    f = only_one(shop, code, changed)
    assert (f.severity, f.amount) == ("medium", None) and "No payment has gone" in f.summary
    assert findings(shop, code, first_only) == []
    bill, _ = posted_bill(client, shop, changed, "MB-1")
    pay(client, shop, bill, "100.00")
    run_check(shop, code)
    f = only_one(shop, code, changed)
    assert (f.severity, f.amount) == ("high", Dec("100.00"))
    assert "1 payment(s) worth" in f.summary and f"{shop['currency']} 100.00" in f.summary
    assert changed in record_ids(f)
    with system(shop) as s:                                                          # the change was a month ago
        s.execute(text("update purchasing.supplier_bank_account set valid_from = valid_from - interval '30 days' "
                       "where supplier_id = :s and status = 'active'"), {"s": changed})
    assert run_check(shop, code).resolved == 1
    tune(client, shop, code, days=60)
    assert run_check(shop, code).reopened == 1
    tune(client, shop, code, days=14)


# --------------------------------------------------------------------------- paid but not received
def test_paying_for_goods_that_came_back_or_never_came_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.paid_without_receipt"
    sent_back, missing, fine = (new_supplier(client, shop, n) for n in ("Sent back", "Missing", "Fine"))
    b1, r1 = posted_bill(client, shop, sent_back, "SB-1")                              # 10 x 50 + tax = 580
    pay(client, shop, b1, "580.00")
    back = client.post(f"{PUR}/receipts/{r1['id']}/returns", headers=shop["owner"], json={
        "lines": [{"receipt_line_id": r1["lines"][0]["id"], "quantity": "4"}],
        "reason_code_id": shop["reasons"]["purchase_return"], "note": "Cracked"})
    assert back.status_code == 201, back.text
    b2, r2 = posted_bill(client, shop, missing, "MI-1")
    pay(client, shop, b2, "300.00")
    b3, _ = posted_bill(client, shop, fine, "OK-1")
    pay(client, shop, b3, "580.00")
    with system(shop) as s:                                                          # the receipt turns out to be void
        s.execute(text("update purchasing.goods_receipt set status = 'reversed' where id = :i"), {"i": r2["id"]})
    run_check(shop, code)
    f1 = only_one(shop, code, b1["id"])
    assert (f1.severity, f1.amount, str(f1.branch_id)) == ("medium", Dec("200.00"), str(shop["branch_id"]))
    assert "4 unit(s) billed beyond the 6 received" in f1.summary and f"{shop['currency']} 580.00" in f1.summary
    f2 = only_one(shop, code, b2["id"])
    assert (f2.severity, f2.amount) == ("high", Dec("300.00"))                       # all of what was paid is at stake
    assert "10 unit(s) billed beyond the 0 received" in f2.summary
    assert findings(shop, code, b3["id"]) == []
    with system(shop) as s:
        s.execute(text("update purchasing.goods_receipt set status = 'posted' where id = :i"), {"i": r2["id"]})
    assert run_check(shop, code).resolved == 1
    with system(shop) as s:                                                          # the bill is old news now
        s.execute(text("update purchasing.supplier_bill set bill_date = :d where id = :i"),
                  {"d": TODAY - timedelta(days=100), "i": b1["id"]})
    assert run_check(shop, code).resolved == 1


# --------------------------------------------------------------------------- overdue bills
def test_overdue_bills_are_one_finding_per_supplier(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.overdue_supplier_bills"
    late, mild, ontime = (new_supplier(client, shop, n) for n in ("Very late", "Late", "Recent"))
    due = {}
    for sid, invoice, days in ((late, "L-1", 20), (late, "L-2", 70), (mild, "M-1", 20), (ontime, "R-1", 10)):
        bill, _ = posted_bill(client, shop, sid, invoice)
        due[invoice] = bill
        with system(shop) as s:
            s.execute(text("update purchasing.supplier_bill set due_date = :d where id = :i"),
                      {"d": TODAY - timedelta(days=days), "i": bill["id"]})
    run_check(shop, code)
    f = only_one(shop, code, late)
    assert (f.severity, f.amount, f.value, f.branch_id) == ("high", Dec("1160.00"), Dec(70), None)
    assert "2 bill(s)" in f.summary and "70 days overdue" in f.summary and f"{shop['currency']} 1,160.00" in f.summary
    assert {due["L-1"]["id"], due["L-2"]["id"]} == record_ids(f)
    m = only_one(shop, code, mild)
    assert (m.severity, m.amount) == ("medium", Dec("580.00"))
    assert findings(shop, code, ontime) == []
    tune(client, shop, code, overdue_days=5)                                         # 10 days late now counts
    run_check(shop, code)
    assert only_one(shop, code, ontime).amount == Dec("580.00")
    tune(client, shop, code, overdue_days=14)
    assert run_check(shop, code).resolved == 1
    pay(client, shop, due["M-1"], "80.00")                                            # part paid: the finding shrinks
    run_check(shop, code)
    assert only_one(shop, code, mild).amount == Dec("500.00")
    pay(client, shop, due["M-1"], "500.00")
    assert run_check(shop, code).resolved == 1


# --------------------------------------------------------------------------- bills waiting on a mismatch
def test_a_bill_that_does_not_match_and_has_waited_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = "purchasing.bill_mismatch_waiting"
    sid = new_supplier(client, shop, "Mismatch")
    _, receipt = deliver(client, shop, sid, "50.00", "4")
    bill = bill_for(client, view(shop, sid), receipt, cost="70.00", invoice="MM-1", bill_date=ISO, who="fm").json()
    sub = client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["fm"]).json()
    assert sub["match_status"] == "exception"
    _, ok_receipt = deliver(client, shop, sid, "50.00", "4")
    ok = bill_for(client, view(shop, sid), ok_receipt, invoice="MM-2", bill_date=ISO).json()
    assert client.post(f"{PUR}/bills/{ok['id']}/submit", headers=shop["owner"]).json()["status"] == "posted"
    run_check(shop, code)
    assert findings(shop, code, bill["id"]) == []                                    # only just entered: not waiting yet
    with system(shop) as s:
        s.execute(text("update purchasing.supplier_bill set created_at = now() - interval '5 days' where id = :i"),
                  {"i": bill["id"]})
    run_check(shop, code)
    f = only_one(shop, code, bill["id"])
    assert (f.severity, str(f.branch_id)) == ("medium", str(shop["branch_id"]))
    assert f.amount == Dec(sub["total"]) and bill["number"] in f.summary
    assert "has not matched its order and receipt" in f.summary
    assert "cost per unit" in f.summary                                              # the first problem is quoted
    assert findings(shop, code, ok["id"]) == []
    tune(client, shop, code, waiting_days=10)
    assert run_check(shop, code).resolved == 1
    tune(client, shop, code, waiting_days=3)
    assert run_check(shop, code).reopened == 1
    rejected = client.post(f"{PUR}/bills/{bill['id']}/reject-exception", headers=shop["fm2"], json={"note": "Wrong price"})
    assert rejected.status_code == 200
    assert run_check(shop, code).resolved == 1                                       # decided: no longer waiting


# --------------------------------------------------------------------------- the engine runs all of them
def test_all_purchasing_checks_run_together_without_failing(client, shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = engine.run_company(s, shop["company_id"], today=TODAY)
    assert not result.failed
    codes = {c["code"] for c in client.get(f"{INTEL}/checks", headers=shop["owner"]).json()}
    assert {c for c in codes if c.startswith("purchasing.")} == {
        "purchasing.supplier_price_rise", "purchasing.order_above_usual_price", "purchasing.margin_squeeze",
        "purchasing.duplicate_supplier_bill", "purchasing.duplicate_supplier_payment",
        "purchasing.supplier_bank_changed", "purchasing.paid_without_receipt", "purchasing.overdue_supplier_bills",
        "purchasing.bill_mismatch_waiting"}


# --------------------------------------------------------------------------- Command Center figures
def figures(shop, day: date) -> dict[tuple[str, UUID | None], Dec]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        made = PurchasingPulse().figures(s, shop["company_id"], day)
    return {(f.metric, f.branch_id): f.value for f in made}


def test_pulse_figures_are_the_payables_and_the_days_receipts(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = setup_shop(client, registry, "Buy Pulse Co")
    day = datetime.now(UTC).date()                                                   # the company's time zone is UTC
    sid = shop["supplier"]
    bill_a, _ = posted_bill(client, shop, sid, "PU-A")                               # 10 x 50 received: 500, owes 580
    order_b = approved_order(client, shop, qty="10", cost="25.00")
    assert receive(client, shop, order_b, qty="4").status_code == 201                # 4 x 25 = 100; order still open
    bill_c, _ = posted_bill(client, shop, sid, "PU-C", qty="4", cost="25.00")      # 4 x 25 received: 100, owes 116
    bill_d, _ = posted_bill(client, shop, sid, "PU-D", qty="2", cost="50.00")      # 2 x 50 received: 100, owes 116
    approved_order(client, shop, qty="3", cost="40.00")                              # open, nothing received
    pay(client, shop, bill_a, "80.00")                                               # A now owes 500
    for bill, offset in ((bill_a, 3), (bill_c, -5), (bill_d, 30)):
        with system(shop) as s:
            s.execute(text("update purchasing.supplier_bill set due_date = :d where id = :i"),
                      {"d": day + timedelta(days=offset), "i": bill["id"]})
    hq = shop["branch_id"]
    got = figures(shop, day)
    for branch in (None, hq):                                                        # everything happened at HQ
        assert got[("purchasing.payables_outstanding", branch)] == Dec(500 + 116 + 116)
        assert got[("purchasing.bills_due_7_days", branch)] == Dec(500)
        assert got[("purchasing.bills_overdue", branch)] == Dec(116)
        assert got[("purchasing.goods_received_value", branch)] == Dec(500 + 100 + 100 + 100)
        assert got[("purchasing.open_purchase_orders", branch)] == Dec(2)
    assert ("purchasing.payables_outstanding", UUID(str(shop["juja"]))) not in got       # JUJA bought nothing
    before = figures(shop, day - timedelta(days=10))                                 # as seen ten days earlier
    assert before[("purchasing.goods_received_value", None)] == 0
    assert before[("purchasing.bills_overdue", None)] == 0
    assert before[("purchasing.bills_due_7_days", None)] == 116                      # C, due 5 days before today

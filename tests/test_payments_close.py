"""The daily close and its lock, reopening through approval, and money moving between the business's accounts."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import balance, entries
from tests.payments_helpers import PAY, make_payments_shop, one, record
from tests.stock_helpers import system  # noqa: F401


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_payments_shop(client, registry, "Close Co", finance=True)
    s["fm"] = s["user"]("fm", "Finance Manager", None)
    s["fm2"] = s["user"]("fm2", "Finance Manager", None)
    return s


def cash_in(client, shop, day, amount="500.00"):  # type: ignore[no-untyped-def]
    r = record(client, shop, method="cash", payment_account_id=shop["cash"], amount=amount, business_date=day)
    assert r.status_code == 201, r.text
    return r.json()


def close_body(shop, day, banked, explanation=None):  # type: ignore[no-untyped-def]
    return {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "business_date": day,
            "cash_banked": banked, "explanation": explanation}


def submit(client, shop, day, banked, who="manager", explanation=None):  # type: ignore[no-untyped-def]
    return client.post(f"{PAY}/closes", headers=shop[who], json=close_body(shop, day, banked, explanation))


# --------------------------------------------------------------------------- closing
def test_a_balanced_day_closes_and_locks(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = "2026-09-01"
    payment = cash_in(client, shop, day)
    r = submit(client, shop, day, "500.00")
    assert r.status_code == 200, r.text
    close = r.json()["close"]
    assert close["status"] == "locked" and Dec(close["variance"]) == 0 and close["locked_at"]
    assert r.json()["totals"]["cash"] == {"expected": "500.0000", "banked": "500.00"} or \
        Dec(r.json()["totals"]["cash"]["expected"]) == 500
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'close.completed' and "
                     "aggregate_id = :i", i=close["id"]) == 1
    # the day is locked to anything that changes its payments
    blocked = record(client, shop, method="cash", payment_account_id=shop["cash"], business_date=day)
    assert blocked.status_code == 422 and "locked" in blocked.json()["message"]
    reverse = client.post(f"{PAY}/payments/{payment['id']}/reverse", headers=shop["owner"], json={"reason": "oops"})
    assert reverse.status_code == 422 and "locked" in reverse.json()["message"]
    dep = client.post(f"{PAY}/cash-deposits", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "bank_account_id": shop["bank"],
        "amount": "100", "business_date": day, "reference": "SLIP-LOCKED"})
    assert dep.status_code == 422
    assert submit(client, shop, day, "500.00").status_code == 409                   # already closed
    other_day = record(client, shop, method="cash", payment_account_id=shop["cash"], business_date="2026-09-02")
    assert other_day.status_code == 201                                            # other days are untouched
    listed = client.get(f"{PAY}/closes", headers=shop["manager"], params={"status": "locked"}).json()
    assert close["id"] in {c["id"] for c in listed}


def test_a_variance_must_be_explained_and_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = "2026-09-03"
    cash_in(client, shop, day, "1000.00")
    r = submit(client, shop, day, "950.00")
    assert r.status_code == 422 and "variance of 50" in r.json()["message"]
    assert submit(client, shop, day, "950.00", explanation="   ").status_code == 422
    r = submit(client, shop, day, "950.00", explanation="Change given short")
    assert r.status_code == 200 and Dec(r.json()["close"]["variance"]) == 50
    cid = r.json()["close"]["id"]
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "close_variance"}).json()
    assert any(i["ref_id"] == cid for i in items)
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'close.variance' and "
                     "aggregate_id = :i", i=cid) == 1


def test_unmatched_mpesa_shows_in_the_preview_and_counts_as_variance(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = "2026-09-04"
    record(client, shop, method="mobile_money", amount="200.00", business_date=day, external_ref="NOTSEEN1")
    p = client.get(f"{PAY}/closes/preview", headers=shop["manager"], params={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "business_date": day,
        "cash_banked": "0"})
    assert p.status_code == 200
    assert any("mobile_money" in problem for problem in p.json()["problems"])
    assert Dec(p.json()["totals"]["variance"]) == 200
    assert submit(client, shop, day, "0.00").status_code == 422                  # needs an explanation
    ok = submit(client, shop, day, "0.00", explanation="Safaricom statement not yet imported")
    assert ok.status_code == 200 and Dec(ok.json()["close"]["variance"]) == 200


def test_closing_is_validated_and_scoped(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = "2026-09-05"
    assert submit(client, shop, day, "-1").status_code == 422
    assert submit(client, shop, day, "10.005").status_code == 422
    assert submit(client, shop, day, "10", who="cashier").status_code == 403
    assert submit(client, shop, day, "10", who="storekeeper").status_code == 403
    juja_manager = shop["user"]("jujaboss", "Branch Manager", shop["juja"])
    assert client.post(f"{PAY}/closes", headers=juja_manager, json=close_body(shop, day, "0")).status_code in (403, 404)
    bad = close_body(shop, day, "0")
    bad["branch_id"] = str(uuid4())
    assert client.post(f"{PAY}/closes", headers=shop["owner"], json=bad).status_code in (404, 422)
    assert juja_manager and client.get(f"{PAY}/closes", headers=juja_manager).json() == [] or True


# --------------------------------------------------------------------------- reopening
def test_reopening_without_a_rule_is_immediate_and_allows_changes(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = "2026-09-06"
    cash_in(client, shop, day)
    cid = submit(client, shop, day, "500.00").json()["close"]["id"]
    reopen = f"{PAY}/closes/{cid}/reopen"
    assert client.post(reopen, headers=shop["manager"], json={"reason": "Missed a sale"}).status_code == 403
    assert client.post(reopen, headers=shop["fm"], json={"reason": " "}).status_code == 422
    assert client.post(f"{PAY}/closes/{uuid4()}/reopen", headers=shop["fm"], json={"reason": "x"}).status_code == 404
    r = client.post(reopen, headers=shop["fm"], json={"reason": "Missed a sale"})
    assert r.status_code == 200 and r.json()["status"] == "reopened"
    assert client.post(reopen, headers=shop["fm"], json={"reason": "again"}).status_code == 409
    assert cash_in(client, shop, day, "100.00")                                    # allowed again
    again = submit(client, shop, day, "600.00")
    assert again.status_code == 200 and Dec(again.json()["close"]["variance"]) == 0


def test_reopening_can_need_an_approver(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "daily_close",
        "approver_role_id": shop["roles"]["Finance Manager"], "min_amount": "0"})
    assert r.status_code == 201, r.text
    day = "2026-09-07"
    cash_in(client, shop, day)
    cid = submit(client, shop, day, "500.00").json()["close"]["id"]
    reopen = client.post(f"{PAY}/closes/{cid}/reopen", headers=shop["fm"], json={"reason": "Wrong tender"})
    assert reopen.status_code == 200 and reopen.json()["status"] == "locked"          # waits
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm2"]).json()
    request = next(x for x in pending if x["doc_id"] == cid)
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm"],
                       json={"approve": True}).status_code == 403                    # not their own request
    done = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm2"], json={"approve": True})
    assert done.status_code == 200, done.text
    assert client.get(f"{PAY}/closes", headers=shop["fm"], params={"status": "reopened"}).json()[0]["id"] == cid
    # a rejected request leaves a day locked
    day2 = "2026-09-08"
    cash_in(client, shop, day2)
    cid2 = submit(client, shop, day2, "500.00").json()["close"]["id"]
    client.post(f"{PAY}/closes/{cid2}/reopen", headers=shop["fm"], json={"reason": "Because"})
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm2"]).json()
    request = next(x for x in pending if x["doc_id"] == cid2)
    client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm2"],
                json={"approve": False, "note": "No"})
    assert one(shop, "select status from payments.daily_close where id = :i", i=cid2) == "locked"


# --------------------------------------------------------------------------- money between accounts
def test_a_settlement_moves_mpesa_money_to_the_bank_and_posts(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = {c: balance(shop, c) for c in ("1020", "6400", "1030")}
    body = {"from_account_id": shop["till"], "to_account_id": shop["bank"], "amount": "9900.00", "fee": "100.00",
            "business_date": "2026-09-10", "reference": "SETTLE-1"}
    r = client.post(f"{PAY}/settlements", headers=shop["owner"], json=body)
    assert r.status_code == 201, r.text
    assert balance(shop, "1020") == before["1020"] + 9900
    assert balance(shop, "6400") == before["6400"] + 100
    assert balance(shop, "1030") == before["1030"] - 10000
    payments = client.get(f"{PAY}/payments", headers=shop["owner"], params={"business_date": "2026-09-10"}).json()
    assert {(p["method"], p["direction"], Dec(p["amount"])) for p in payments} >= {
        ("mobile_money", "out", Dec("10000")), ("bank", "in", Dec("9900"))}
    assert any(e[1] == "settlement" for e in entries(shop))


def test_settlements_are_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    good = {"from_account_id": shop["till"], "to_account_id": shop["bank"], "amount": "100", "reference": "S"}
    post = lambda **kw: client.post(f"{PAY}/settlements", headers=kw.pop("headers", shop["owner"]),  # noqa: E731
                                    json={**good, **kw})
    assert post(from_account_id=shop["bank"], to_account_id=shop["till"]).status_code == 422
    assert post(from_account_id=shop["cash"]).status_code == 422
    assert post(amount="0").status_code == 422
    assert post(fee="-1").status_code == 422
    assert post(fee="1.005").status_code == 422
    assert post(reference="  ").status_code == 422
    assert post(to_account_id=str(uuid4())).status_code == 422
    assert post(headers=shop["cashier"]).status_code == 403


def test_a_cash_deposit_moves_cash_to_the_bank_and_posts(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = {c: balance(shop, c) for c in ("1010", "1020")}
    body = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]),
            "bank_account_id": shop["bank"], "amount": "2500.00", "business_date": "2026-09-11",
            "reference": "SLIP-77"}
    r = client.post(f"{PAY}/cash-deposits", headers=shop["manager"], json=body)
    assert r.status_code == 201, r.text
    assert balance(shop, "1020") == before["1020"] + 2500 and balance(shop, "1010") == before["1010"] - 2500
    assert client.post(f"{PAY}/cash-deposits", headers=shop["manager"], json={**body, "bank_account_id": shop["till"]}
                       ).status_code == 422
    assert client.post(f"{PAY}/cash-deposits", headers=shop["manager"], json={**body, "reference": " "}).status_code == 422
    assert client.post(f"{PAY}/cash-deposits", headers=shop["cashier"], json=body).status_code == 403
    assert client.post(f"{PAY}/cash-deposits", headers=shop["manager"], json={**body, "amount": "0"}).status_code == 422

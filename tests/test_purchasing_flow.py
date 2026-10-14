"""Buying: receiving goods, supplier bills and the three-way match, payment, and the books at every step."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import balance
from tests.payments_helpers import PAY, one
from tests.purchasing_helpers import (
    PUR,
    approved_order,
    bill_for,
    make_purchasing_shop,
    new_order,
    receive,
    stock_of,
)
from tests.stock_helpers import P


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_purchasing_shop(client, registry, "Buy Flow Co")
    books = client.post(f"/api/v1/finance/companies/{s['company_id']}/books", headers=s["owner"]).json()
    s["expense"] = next(a["id"] for a in books if a["code"] == "6200")
    return s


CODES = ("1200", "2100", "2000", "1300", "5200", "1010", "1020", "1030", "6200")


def snapshot(shop):  # type: ignore[no-untyped-def]
    return {c: balance(shop, c) for c in CODES}


def moved(before, after):  # type: ignore[no-untyped-def]
    return {c: after[c] - before[c] for c in CODES if after[c] != before[c]}


# --------------------------------------------------------------------------- receiving
def test_receiving_part_of_an_order_then_the_rest(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="10", cost="50.00")
    before, stock0 = snapshot(shop), stock_of(shop)
    first = receive(client, shop, order, qty="4")
    assert first.status_code == 201, first.text
    assert first.json()["number"].startswith("GRN-HQ-") and first.json()["status"] == "posted"
    assert stock_of(shop) == stock0 + 4
    assert moved(before, snapshot(shop)) == {"1200": Dec(200), "2100": Dec(-200)}      # stock in, owed-for-goods up
    detail = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()
    assert detail["status"] == "part_received" and Dec(detail["lines"][0]["qty_received"]) == 4
    over = receive(client, shop, order, qty="7")
    assert over.status_code == 422 and "Only 6 more" in over.json()["message"]
    assert receive(client, shop, order, qty="6").status_code == 201
    done = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()
    assert done["status"] == "received" and stock_of(shop) == stock0 + 10
    assert receive(client, shop, order, qty="1").status_code == 422                       # nothing left to receive
    assert {r["id"] for r in client.get(f"{PUR}/receipts", headers=shop["owner"],
                                        params={"order_id": order["id"]}).json()} >= {first.json()["id"]}
    assert client.post(f"{PUR}/orders/{order['id']}/cancel", headers=shop["owner"]).status_code == 409


def test_goods_are_costed_at_the_orders_cost_and_the_average_follows(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="5", cost="80.00", product="paint")
    line = order["lines"][0]
    dear = client.post(f"{PUR}/receipts", headers=shop["owner"], json={
        "order_id": order["id"], "lines": [{"order_line_id": line["id"], "quantity": "5", "unit_cost": "99",
                                            "batch_no": "L1"}]})
    assert dear.status_code == 422 and "costed at the order's cost" in dear.json()["message"]
    no_batch = receive(client, shop, order)
    assert no_batch.status_code == 422 and "batch" in no_batch.json()["message"]
    ok = client.post(f"{PUR}/receipts", headers=shop["owner"], json={
        "order_id": order["id"], "lines": [{"order_line_id": line["id"], "quantity": "5", "batch_no": "L1",
                                            "expiry_date": "2030-01-01"}]})
    assert ok.status_code == 201, ok.text
    assert one(shop, "select count(*) from inventory.batch where batch_no = 'L1'") == 1


def test_goods_without_an_order_and_landed_cost(client, shop) -> None:  # type: ignore[no-untyped-def]
    before, stock0 = snapshot(shop), stock_of(shop)
    r = client.post(f"{PUR}/receipts", headers=shop["owner"], json={
        "supplier_id": shop["supplier"], "location_id": shop["main"], "delivery_note_no": "DN-77",
        "landed_cost": "60.00", "lines": [{"product_id": shop["cement"], "quantity": "10", "unit_cost": "40"}]})
    assert r.status_code == 201, r.text
    assert stock_of(shop) == stock0 + 10
    assert moved(before, snapshot(shop)) == {"1200": Dec(460), "2100": Dec(-460)}      # 400 + 60 landed
    for bad in ({"lines": [{"product_id": shop["cement"], "quantity": "1"}]},                       # no cost
                {"lines": [{"quantity": "1", "unit_cost": "5"}]},                                    # no product
                {"location_id": None}, {"landed_cost": "-1"}, {"landed_cost": "1.005"},
                {"supplier_id": str(uuid4())}, {"location_id": str(uuid4())},
                {"lines": [{"product_id": shop["delivery"], "quantity": "1", "unit_cost": "5"}]}):   # a service
        body = {"supplier_id": shop["supplier"], "location_id": shop["main"],
                "lines": [{"product_id": shop["cement"], "quantity": "1", "unit_cost": "5"}], **bad}
        assert client.post(f"{PUR}/receipts", headers=shop["owner"], json=body).status_code == 422, bad


def test_who_may_receive_goods(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="3")
    assert receive(client, shop, order, qty="1", who="cashier").status_code == 403
    assert receive(client, shop, order, qty="1", who="clerk").status_code == 403           # an accountant does not receive
    assert receive(client, shop, order, qty="1", who="storekeeper").status_code == 201
    juja = shop["user"]("jujakeeper2", "Storekeeper", shop["juja"])
    assert receive(client, shop, order, qty="1", who="storekeeper").status_code == 201
    assert client.post(f"{PUR}/receipts", headers=juja, json={
        "order_id": order["id"], "lines": [{"order_line_id": order["lines"][0]["id"], "quantity": "1"}]
    }).status_code in (403, 404)                                                          # not that branch's order
    unapproved = new_order(client, shop, qty="3")
    r = receive(client, shop, unapproved, qty="1")
    assert r.status_code == 422 and "draft" in r.json()["message"]


def test_a_suppliers_prices_are_remembered_and_changes_announced(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = shop["supplier"]
    for cost in ("10.00", "10.00", "12.00"):
        client.post(f"{PUR}/receipts", headers=shop["owner"], json={
            "supplier_id": sup, "location_id": shop["main"],
            "lines": [{"product_id": shop["cement"], "quantity": "1", "unit_cost": cost}]})
    prices = client.get(f"{PUR}/suppliers/{sup}/prices", headers=shop["owner"],
                        params={"product_id": shop["cement"], "limit": 3}).json()
    assert [Dec(p["unit_cost"]) for p in prices] == [Dec(12), Dec(10), Dec(10)]
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'supplier.price_changed'") >= 1


# --------------------------------------------------------------------------- bills
def test_a_bill_that_matches_posts_and_clears_goods_received_not_invoiced(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="10", cost="50.00")
    receipt = receive(client, shop, order).json()
    before = snapshot(shop)
    created = bill_for(client, shop, receipt, invoice="MATCH-1", who="clerk")
    assert created.status_code == 201, created.text
    bill = created.json()
    assert bill["status"] == "draft" and Dec(bill["total"]) == 580 and Dec(bill["tax_total"]) == 80
    assert bill["due_date"] == "2026-11-12"                                                # 30 days terms
    assert moved(before, snapshot(shop)) == {}                                             # a draft books nothing
    posted = client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["clerk"])
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted" and posted.json()["match_status"] == "matched"
    assert moved(before, snapshot(shop)) == {"2100": Dec(500), "1300": Dec(80), "2000": Dec(-580)}
    line = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()["lines"][0]
    assert Dec(line["qty_billed"]) == 10
    assert client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["clerk"]).status_code == 409
    assert client.put(f"{PUR}/bills/{bill['id']}", headers=shop["clerk"], json={"due_date": "2026-12-01"}
                      ).status_code == 409
    assert bill_for(client, shop, receipt, invoice="MATCH-1").status_code == 409            # the invoice no. is used


def test_a_small_price_difference_is_booked_as_variance(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="10", cost="50.00")
    receipt = receive(client, shop, order).json()
    before = snapshot(shop)
    bill = bill_for(client, shop, receipt, cost="51.00", invoice="VAR-1").json()                  # 2% dearer: allowed
    posted = client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["owner"]).json()
    assert posted["status"] == "posted" and posted["match_status"] == "matched"
    assert Dec(posted["total"]) == Dec("591.60")
    assert moved(before, snapshot(shop)) == {"2100": Dec(500), "5200": Dec(10), "1300": Dec("81.60"),
                                             "2000": Dec("-591.60")}


def test_a_bill_that_does_not_match_needs_someone_else_to_accept_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="10", cost="50.00")
    receipt = receive(client, shop, order, qty="6").json()
    before = snapshot(shop)
    bill = bill_for(client, shop, receipt, cost="60.00", qty="6", invoice="EXC-1", who="clerk").json()   # 20% dearer
    sub = client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["clerk"])
    assert sub.status_code == 200 and sub.json()["status"] == "pending_approval"
    assert sub.json()["match_status"] == "exception" and "20.00% away from the order" in sub.json()["match_notes"][0]
    assert moved(before, snapshot(shop)) == {}                                              # nothing booked yet
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "bill_match_exception"}).json()
    assert any(i["ref_id"] == bill["id"] for i in items)
    approve = f"{PUR}/bills/{bill['id']}/approve-exception"
    body = {"reason_code_id": shop["reasons"]["bill_exception"], "note": "Agreed by phone with the supplier"}
    assert client.post(approve, headers=shop["clerk"], json=body).status_code == 403          # no bills.approve
    assert client.post(approve, headers=shop["fm"], json={"reason_code_id": shop["reasons"]["stock_adjustment"]}
                       ).status_code == 422                                                   # wrong list of reasons
    assert client.post(approve, headers=shop["fm"], json={}).status_code == 422
    done = client.post(approve, headers=shop["fm"], json=body)
    assert done.status_code == 200 and done.json()["status"] == "posted"
    assert moved(before, snapshot(shop)) == {"2100": Dec(300), "5200": Dec(60), "1300": Dec("57.60"),
                                             "2000": Dec("-417.60")}                           # 6 x 60 + VAT
    assert client.post(approve, headers=shop["fm"], json=body).status_code == 409


def test_the_person_who_entered_an_exception_cannot_approve_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="4", cost="50.00")
    receipt = receive(client, shop, order).json()
    bill = bill_for(client, shop, receipt, cost="70.00", invoice="EXC-2", who="fm").json()
    client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["fm"])
    r = client.post(f"{PUR}/bills/{bill['id']}/approve-exception", headers=shop["fm"], json={
        "reason_code_id": shop["reasons"]["bill_exception"]})
    assert r.status_code == 403
    rejected = client.post(f"{PUR}/bills/{bill['id']}/reject-exception", headers=shop["fm2"], json={"note": "Wrong price"})
    assert rejected.status_code == 200 and rejected.json()["status"] == "draft"
    fixed = client.put(f"{PUR}/bills/{bill['id']}", headers=shop["fm"], json={"lines": [
        {"receipt_line_id": receipt["lines"][0]["id"], "quantity": "4", "unit_cost": "50.00"}]})
    assert fixed.status_code == 200
    assert client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["fm"]).json()["status"] == "posted"


def test_billing_more_than_was_received_or_billed_twice_is_an_exception(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="10", cost="50.00")
    receipt = receive(client, shop, order, qty="5").json()
    first = bill_for(client, shop, receipt, qty="3", invoice="PART-1").json()
    assert client.post(f"{PUR}/bills/{first['id']}/submit", headers=shop["owner"]).json()["status"] == "posted"
    second = bill_for(client, shop, receipt, qty="3", invoice="PART-2").json()                       # only 2 left
    sub = client.post(f"{PUR}/bills/{second['id']}/submit", headers=shop["owner"]).json()
    assert sub["match_status"] == "exception" and "only 2 of the 5" in sub["match_notes"][0]
    ok = bill_for(client, shop, receipt, qty="2", invoice="PART-3").json()
    assert client.post(f"{PUR}/bills/{ok['id']}/submit", headers=shop["owner"]).json()["status"] == "posted"
    line = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()["lines"][0]
    assert Dec(line["qty_billed"]) == 5


def test_a_cancelled_bill_frees_the_invoice_number(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="2")
    receipt = receive(client, shop, order).json()
    bill = bill_for(client, shop, receipt, invoice="CANCEL-1").json()
    assert client.post(f"{PUR}/bills/{bill['id']}/cancel", headers=shop["owner"]).json()["status"] == "cancelled"
    assert client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["owner"]).status_code == 409
    again = bill_for(client, shop, receipt, invoice="CANCEL-1")
    assert again.status_code == 201
    posted = client.post(f"{PUR}/bills/{again.json()['id']}/submit", headers=shop["owner"])
    assert posted.json()["status"] == "posted"
    assert client.post(f"{PUR}/bills/{again.json()['id']}/cancel", headers=shop["owner"]).status_code == 409


def test_an_expense_bill_needs_no_goods(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = snapshot(shop)
    body = {"supplier_id": shop["supplier"], "supplier_invoice_no": "ELEC/2026/10", "bill_date": "2026-10-10",
            "lines": [{"quantity": "1", "unit_cost": "5000.00", "expense_account_id": shop["expense"],
                       "description": "October electricity", "tax_code_id": shop["tax"]}]}
    bill = client.post(f"{PUR}/bills", headers=shop["owner"], json=body)
    assert bill.status_code == 201, bill.text
    assert Dec(bill.json()["total"]) == 5800
    posted = client.post(f"{PUR}/bills/{bill.json()['id']}/submit", headers=shop["owner"]).json()
    assert posted["status"] == "posted" and posted["match_status"] == "not_required"
    assert moved(before, snapshot(shop)) == {"6200": Dec(5000), "1300": Dec(800), "2000": Dec(-5800)}
    for bad in ({"expense_account_id": None}, {"description": " "}, {"expense_account_id": str(uuid4())}):
        line = {**body["lines"][0], **bad}
        r = client.post(f"{PUR}/bills", headers=shop["owner"], json={**body, "supplier_invoice_no": "X-1", "lines": [line]})
        assert r.status_code == 422, bad


def test_bill_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="2")
    receipt = receive(client, shop, order).json()
    line = {"receipt_line_id": receipt["lines"][0]["id"], "quantity": "1", "unit_cost": "50"}
    base = {"supplier_id": shop["supplier"], "supplier_invoice_no": "VAL-1", "bill_date": "2026-10-10", "lines": [line]}
    assert client.post(f"{PUR}/bills", headers=shop["owner"], json={**base, "supplier_invoice_no": "VAL-0"}
                       ).status_code == 201
    for name, change in {
        "no lines": {"lines": []}, "bad invoice no": {"supplier_invoice_no": "<b>"},
        "due before bill": {"due_date": "2026-10-01"}, "future": {"bill_date": "2030-01-01"},
        "unknown supplier": {"supplier_id": str(uuid4())},
        "other goods": {"lines": [{**line, "receipt_line_id": str(uuid4())}]},
        "twice": {"lines": [line, line]}, "negative": {"lines": [{**line, "unit_cost": "-1"}]},
        "goods and expense": {"lines": [{**line, "expense_account_id": shop["expense"]}]},
    }.items():
        r = client.post(f"{PUR}/bills", headers=shop["owner"], json={**base, "supplier_invoice_no": "VAL-2", **change}
                        if "supplier_invoice_no" not in change else {**base, **change})
        assert r.status_code == 422, name
    assert client.post(f"{PUR}/bills", headers=shop["buyer"], json=base).status_code == 403   # a buyer does not bill
    other = client.post(f"{PUR}/suppliers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": "OTHER", "name": "Other"}).json()
    wrong = client.post(f"{PUR}/bills", headers=shop["owner"], json={**base, "supplier_id": other["id"],
                                                                     "supplier_invoice_no": "VAL-3"})
    assert wrong.status_code == 422 and "did not deliver" in wrong.json()["message"]


def test_a_large_bill_waits_for_an_approver(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "supplier_bill",
        "approver_role_id": shop["roles"]["Finance Manager"], "min_amount": "100000"})
    order = approved_order(client, shop, qty="100", cost="2000.00")
    receipt = receive(client, shop, order).json()
    before = snapshot(shop)
    bill = bill_for(client, shop, receipt, invoice="BIG-1", who="clerk").json()
    sub = client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["clerk"]).json()
    assert sub["status"] == "pending_approval" and sub["match_status"] == "matched"
    assert moved(before, snapshot(shop)) == {}
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm"]).json()
    request = next(x for x in pending if x["doc_id"] == bill["id"])
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm"],
                       json={"approve": True}).status_code == 200
    assert client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()["status"] == "posted"
    assert moved(before, snapshot(shop))["2000"] == Dec(-232000)


# --------------------------------------------------------------------------- paying
def posted_bill(client, shop, invoice, qty="10", cost="50.00"):  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty=qty, cost=cost)
    receipt = receive(client, shop, order).json()
    bill = bill_for(client, shop, receipt, invoice=invoice).json()
    return client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["owner"]).json()


def test_paying_a_bill_in_parts(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = posted_bill(client, shop, "PAY-1")                                              # 580
    pay = f"{PUR}/bills/{bill['id']}/pay"
    before = snapshot(shop)
    r = client.post(pay, headers=shop["fm"], json={"amount": "200.00", "method": "cash"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "part_paid" and Dec(r.json()["amount_paid"]) == 200
    assert moved(before, snapshot(shop)) == {"2000": Dec(200), "1010": Dec(-200)}
    rest = client.post(pay, headers=shop["fm"], json={"amount": "380.00", "method": "bank",
                                                       "payment_account_id": shop["bank"], "external_ref": "EFT-1"})
    assert rest.status_code == 200 and rest.json()["status"] == "paid"
    assert moved(before, snapshot(shop)) == {"2000": Dec(580), "1010": Dec(-200), "1020": Dec(-380)}
    payments = client.get(f"{PAY}/payments", headers=shop["owner"], params={"direction": "out"}).json()
    assert {Dec(p["amount"]) for p in payments} >= {Dec(200), Dec(380)}
    assert client.post(pay, headers=shop["fm"], json={"amount": "1.00", "method": "cash"}).status_code == 409


def test_payment_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    bill = posted_bill(client, shop, "PAY-2", qty="2")                                      # 116
    pay = f"{PUR}/bills/{bill['id']}/pay"
    for body in ({"amount": "0", "method": "cash"}, {"amount": "-5", "method": "cash"},
                 {"amount": "1.005", "method": "cash"}, {"amount": "116.01", "method": "cash"},
                 {"amount": "10", "method": "bitcoin"}, {"amount": "10", "method": "bank"},      # needs an account
                 {"amount": "10", "method": "mobile_money", "payment_account_id": shop["bank"]}):
        assert client.post(pay, headers=shop["fm"], json=body).status_code == 422, body
    ok = {"amount": "10", "method": "cash"}
    assert client.post(pay, headers=shop["clerk"], json=ok).status_code == 403            # an accountant does not pay
    assert client.post(pay, headers=shop["buyer"], json=ok).status_code == 403
    client.patch(f"{PUR}/suppliers/{shop['supplier']}", headers=shop["owner"], json={"status": "on_hold"})
    held = client.post(pay, headers=shop["fm"], json=ok)
    assert held.status_code == 422 and "on hold" in held.json()["message"]
    client.patch(f"{PUR}/suppliers/{shop['supplier']}", headers=shop["owner"], json={"status": "active"})
    assert client.post(pay, headers=shop["fm"], json=ok).status_code == 200
    draft = bill_for(client, shop, receive(client, shop, approved_order(client, shop, qty="1")).json(),
                     invoice="PAY-3").json()
    assert client.post(f"{PUR}/bills/{draft['id']}/pay", headers=shop["fm"], json=ok).status_code == 409


def test_what_is_owed_to_suppliers_by_age(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = approved_order(client, shop, qty="10", cost="100.00")
    receipt = receive(client, shop, order).json()
    bill = client.post(f"{PUR}/bills", headers=shop["owner"], json={
        "supplier_id": shop["supplier"], "supplier_invoice_no": "AGE-1", "bill_date": "2026-06-01",
        "due_date": "2026-06-30", "lines": [{"receipt_line_id": receipt["lines"][0]["id"], "quantity": "10",
                                              "unit_cost": "100.00"}]}).json()
    client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["owner"])
    report = client.get(f"{PUR}/payables", headers=shop["fm"], params={"as_of": "2026-10-13"}).json()
    row = next(r for r in report["suppliers"] if r["supplier_id"] == shop["supplier"])
    assert Dec(row["over_90"]) >= Dec(1160) and Dec(report["total"]) >= Dec(1160)
    assert Dec(report["buckets"]["over_90"]) == sum(Dec(r["over_90"]) for r in report["suppliers"])
    early = client.get(f"{PUR}/payables", headers=shop["fm"], params={"as_of": "2026-06-15"}).json()
    assert early["suppliers"] == [] or all(Dec(r["over_90"]) == 0 for r in early["suppliers"])
    listed = client.get(f"{PUR}/bills", headers=shop["fm"], params={"status": "posted", "due_before": "2026-06-30"}).json()
    assert [b["supplier_invoice_no"] for b in listed] == ["AGE-1"]
    assert client.get(f"{PUR}/payables", headers=shop["cashier"]).status_code == 403


def test_the_books_stay_balanced_and_the_stock_equals_the_ledger(client, shop) -> None:  # type: ignore[no-untyped-def]
    tb = client.get("/api/v1/finance/reports/trial-balance", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "as_of": "2099-01-01"}).json()
    assert tb["balanced"]
    assert one(shop, "select coalesce(sum(value), 0) from inventory.stock_movement") == balance(shop, "1200")
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'bill.posted'") > 5
    assert P and PUR

"""Putting things right: reversing payments and bills, sending goods back, supplier credit notes, landed-cost invoices."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.finance_helpers import balance
from tests.payments_helpers import PAY, one
from tests.purchasing_helpers import PUR, bill_for, make_purchasing_shop, new_order, receive, stock_of
from tests.stock_helpers import P, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_purchasing_shop(client, registry, "Buy Fix Co")
    books = client.post(f"/api/v1/finance/companies/{s['company_id']}/books", headers=s["owner"]).json()
    s["expense"] = next(a["id"] for a in books if a["code"] == "6200")
    # a product only these tests touch, so its average cost is exactly what was paid
    made = client.post(f"{P}/products", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "sku": "BOLT", "name": "Bolts", "base_uom_id": s["uom"],
        "tax_code_id": s["tax"]})
    assert made.status_code == 201, made.text
    s["bolt"] = made.json()["id"]
    s["transport"] = client.post(f"{PUR}/suppliers", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "code": "FREIGHT", "name": "Fast Freight"}).json()["id"]
    return s


CODES = ("1200", "2100", "2000", "1300", "5200", "1010", "1020", "6200")


def snapshot(shop):  # type: ignore[no-untyped-def]
    return {c: balance(shop, c) for c in CODES}


def moved(before, after):  # type: ignore[no-untyped-def]
    return {c: after[c] - before[c] for c in CODES if after[c] != before[c]}


def order_receipt(client, shop, qty="10", cost="50.00", **kw):  # type: ignore[no-untyped-def]
    order = new_order(client, shop, qty=qty, cost=cost, product="bolt")
    assert client.post(f"{PUR}/orders/{order['id']}/submit", headers=shop["owner"]).json()["status"] == "approved"
    order = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()
    r = receive(client, shop, order, **kw)
    assert r.status_code == 201, r.text
    return order, r.json()


def post_bill(client, shop, receipt, invoice, **kw):  # type: ignore[no-untyped-def]
    bill = bill_for(client, shop, receipt, invoice=invoice, **kw)
    assert bill.status_code == 201, bill.text
    done = client.post(f"{PUR}/bills/{bill.json()['id']}/submit", headers=shop["owner"])
    assert done.status_code == 200 and done.json()["status"] == "posted", done.text
    return done.json()


def back(client, shop, receipt, qty, who="owner"):  # type: ignore[no-untyped-def]
    return client.post(f"{PUR}/receipts/{receipt['id']}/returns", headers=shop[who], json={
        "lines": [{"receipt_line_id": receipt["lines"][0]["id"], "quantity": qty}],
        "reason_code_id": shop["reasons"]["purchase_return"], "note": "Cracked"})


# --------------------------------------------------------------------------- reversing a payment
def test_a_reversed_payment_makes_the_bill_owed_again(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop)
    bill = post_bill(client, shop, receipt, "REVPAY-1")                                    # 580
    pay = client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"], json={"amount": "300.00", "method": "cash"})
    assert pay.json()["status"] == "part_paid"
    payments = client.get(f"{PUR}/bills/{bill['id']}/payments", headers=shop["fm"]).json()
    assert len(payments) == 1 and Dec(payments[0]["amount"]) == 300 and payments[0]["status"] == "posted"
    before = snapshot(shop)
    path = f"{PUR}/bills/{bill['id']}/reverse-payment"
    assert client.post(path, headers=shop["clerk"], json={"payment_id": payments[0]["payment_id"], "reason": "x"}
                       ).status_code == 403
    assert client.post(path, headers=shop["fm"], json={"payment_id": str(uuid4()), "reason": "x"}).status_code == 404
    assert client.post(path, headers=shop["fm"], json={"payment_id": payments[0]["payment_id"], "reason": ""}
                       ).status_code == 422
    r = client.post(path, headers=shop["fm"], json={"payment_id": payments[0]["payment_id"],
                                                     "reason": "Paid the wrong supplier"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "posted" and Dec(r.json()["amount_paid"]) == 0
    assert moved(before, snapshot(shop)) == {"2000": Dec(-300), "1010": Dec(300)}            # owed again, cash back
    assert client.get(f"{PUR}/bills/{bill['id']}/payments", headers=shop["fm"]).json()[0]["status"] == "reversed"
    assert client.post(path, headers=shop["fm"], json={"payment_id": payments[0]["payment_id"], "reason": "again"}
                       ).status_code == 409                                                  # already reversed in Payments


def test_a_payment_reversed_in_payments_updates_the_bill_too(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop, qty="2")
    bill = post_bill(client, shop, receipt, "REVPAY-2")                                      # 116
    client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"], json={"amount": "116.00", "method": "cash"})
    assert client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()["status"] == "paid"
    before = snapshot(shop)
    payment = client.get(f"{PUR}/bills/{bill['id']}/payments", headers=shop["fm"]).json()[0]["payment_id"]
    assert client.post(f"{PAY}/payments/{payment}/reverse", headers=shop["fm"], json={"reason": "Bounced"}
                       ).status_code == 200
    now = client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()
    assert now["status"] == "posted" and Dec(now["amount_paid"]) == 0
    assert moved(before, snapshot(shop)) == {"2000": Dec(-116), "1010": Dec(116)}


# --------------------------------------------------------------------------- reversing a bill
def test_reversing_a_bill_undoes_everything(client, shop) -> None:  # type: ignore[no-untyped-def]
    order, receipt = order_receipt(client, shop)
    before = snapshot(shop)
    bill = post_bill(client, shop, receipt, "REVBILL-1", cost="51.00")                       # with a price variance
    assert moved(before, snapshot(shop)) != {}
    path = f"{PUR}/bills/{bill['id']}/reverse"
    assert client.post(path, headers=shop["clerk"], json={"reason": "Wrong"}).status_code == 403
    assert client.post(path, headers=shop["fm"], json={"reason": " "}).status_code == 422
    r = client.post(path, headers=shop["fm"], json={"reason": "Entered against the wrong delivery"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reversed" and r.json()["reverse_reason"].startswith("Entered")
    assert moved(before, snapshot(shop)) == {}                                               # every account is back
    line = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()["lines"][0]
    assert Dec(line["qty_billed"]) == 0
    assert client.post(path, headers=shop["fm"], json={"reason": "again"}).status_code == 409
    again = post_bill(client, shop, receipt, "REVBILL-1")                                    # the number is free again
    assert again["status"] == "posted" and Dec(again["total"]) == 580


def test_a_bill_with_payments_or_credits_is_not_reversed(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop, qty="4")
    bill = post_bill(client, shop, receipt, "REVBILL-2")
    client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"], json={"amount": "50.00", "method": "cash"})
    refused = client.post(f"{PUR}/bills/{bill['id']}/reverse", headers=shop["fm"], json={"reason": "Wrong"})
    assert refused.status_code == 422 and "payments" in refused.json()["message"]
    draft = bill_for(client, shop, receipt, invoice="REVBILL-3", qty="1")
    assert client.post(f"{PUR}/bills/{draft.json()['id']}/reverse", headers=shop["fm"], json={"reason": "x"}
                       ).status_code == 409                                                  # a draft is cancelled instead


def test_reversing_expense_and_landed_bills_mirrors_them(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = snapshot(shop)
    r = client.post(f"{PUR}/bills", headers=shop["owner"], json={
        "supplier_id": shop["supplier"], "supplier_invoice_no": "REVEXP-1", "bill_date": "2026-10-10",
        "lines": [{"quantity": "1", "unit_cost": "1000.00", "expense_account_id": shop["expense"],
                   "description": "Water", "tax_code_id": shop["tax"]}]}).json()
    client.post(f"{PUR}/bills/{r['id']}/submit", headers=shop["owner"])
    assert moved(before, snapshot(shop)) == {"6200": Dec(1000), "1300": Dec(160), "2000": Dec(-1160)}
    assert client.post(f"{PUR}/bills/{r['id']}/reverse", headers=shop["fm"], json={"reason": "Duplicate"}
                       ).status_code == 200
    assert moved(before, snapshot(shop)) == {}


# --------------------------------------------------------------------------- sending goods back
def test_returning_goods_takes_the_stock_out_and_reopens_the_order(client, shop) -> None:  # type: ignore[no-untyped-def]
    order, receipt = order_receipt(client, shop)                                              # 10 bolts at 50
    stock0, before = stock_of(shop, "bolt"), snapshot(shop)
    r = back(client, shop, receipt, "4")
    assert r.status_code == 201, r.text
    ret = r.json()
    assert ret["number"].startswith("PRT-HQ-") and Dec(ret["lines"][0]["stock_value"]) == 200
    assert stock_of(shop, "bolt") == stock0 - 4
    assert moved(before, snapshot(shop)) == {"1200": Dec(-200), "2100": Dec(200)}             # stock out, no longer owed
    detail = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()
    assert detail["status"] == "part_received" and Dec(detail["lines"][0]["qty_received"]) == 6
    replacement = receive(client, shop, detail, qty="4")                                      # the replacement comes
    assert replacement.status_code == 201
    assert client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()["status"] == "received"
    assert client.get(f"{PUR}/returns/{ret['id']}", headers=shop["owner"]).json()["lines"][0]["quantity"]
    assert ret["id"] in {x["id"] for x in client.get(f"{PUR}/returns", headers=shop["owner"],
                                                       params={"supplier_id": shop["supplier"]}).json()}


def test_goods_sent_back_before_billing_are_not_billed(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop)
    assert back(client, shop, receipt, "4").status_code == 201
    too_much = bill_for(client, shop, receipt, invoice="RET-BILL-1", qty="10").json()
    sub = client.post(f"{PUR}/bills/{too_much['id']}/submit", headers=shop["owner"]).json()
    assert sub["match_status"] == "exception" and "only 6 of the 6 received" in sub["match_notes"][0]
    client.post(f"{PUR}/bills/{too_much['id']}/cancel", headers=shop["owner"])
    ok = bill_for(client, shop, receipt, invoice="RET-BILL-2", qty="6").json()
    assert client.post(f"{PUR}/bills/{ok['id']}/submit", headers=shop["owner"]).json()["status"] == "posted"


def test_return_validation_and_permissions(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop, qty="5")
    line = receipt["lines"][0]["id"]
    path = f"{PUR}/receipts/{receipt['id']}/returns"
    good = {"lines": [{"receipt_line_id": line, "quantity": "1"}], "reason_code_id": shop["reasons"]["purchase_return"]}
    for name, change in {
        "too many": {"lines": [{"receipt_line_id": line, "quantity": "6"}]},
        "zero": {"lines": [{"receipt_line_id": line, "quantity": "0"}]},
        "twice": {"lines": [{"receipt_line_id": line, "quantity": "1"}] * 2},
        "another line": {"lines": [{"receipt_line_id": str(uuid4()), "quantity": "1"}]},
        "no reason": {"reason_code_id": None}, "wrong reason list": {"reason_code_id": shop["reasons"]["bill_exception"]},
        "no lines": {"lines": []},
    }.items():
        r = client.post(path, headers=shop["owner"], json={**good, **change})
        assert r.status_code == 422, name
    assert client.post(path, headers=shop["cashier"], json=good).status_code == 403
    assert client.post(path, headers=shop["clerk"], json=good).status_code == 403
    assert client.post(f"{PUR}/receipts/{uuid4()}/returns", headers=shop["owner"], json=good).status_code == 404
    assert client.post(path, headers=shop["storekeeper"], json=good).status_code == 201
    assert client.post(path, headers=shop["owner"], json={**good, "lines": [{"receipt_line_id": line,
                                                                           "quantity": "4.5"}]}).status_code == 422


def test_goods_that_are_no_longer_in_stock_cannot_be_returned(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop, qty="3")
    stock_now = stock_of(shop, "bolt")
    away = client.post("/api/v1/inventory/adjustments", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"],
        "reason_code_id": shop["reasons"]["stock_adjustment"],
        "lines": [{"product_id": shop["bolt"], "qty_change": str(-stock_now)}]})
    assert away.status_code in (200, 201), away.text
    client.post(f"/api/v1/inventory/adjustments/{away.json()['id']}/submit", headers=shop["owner"])
    n = one(shop, "select count(*) from purchasing.purchase_return")
    r = back(client, shop, receipt, "1")
    assert r.status_code == 422
    assert one(shop, "select count(*) from purchasing.purchase_return") == n


# --------------------------------------------------------------------------- credit notes
def credit(client, shop, bill, return_line, qty, cost="50.00", no="CN-1", who="fm", **kw):  # type: ignore[no-untyped-def]
    return client.post(f"{PUR}/bills/{bill['id']}/credit-notes", headers=shop[who], json={
        "supplier_credit_no": no, "credit_date": "2026-10-13",
        "lines": [{"return_line_id": return_line, "quantity": qty, "unit_cost": cost}], **kw})


def test_a_credit_note_for_goods_sent_back_after_billing(client, shop) -> None:  # type: ignore[no-untyped-def]
    order, receipt = order_receipt(client, shop)
    bill = post_bill(client, shop, receipt, "CRED-1")                                         # 580 owed
    before = snapshot(shop)
    ret = back(client, shop, receipt, "4").json()
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "return_needs_credit_note"}).json()
    assert any(i["ref_id"] == ret["id"] for i in items)                                        # not forgotten
    assert moved(before, snapshot(shop)) == {"1200": Dec(-200), "2100": Dec(200)}             # GRNI now debited
    line = ret["lines"][0]["id"]
    r = credit(client, shop, bill, line, "4")
    assert r.status_code == 201, r.text
    note = r.json()
    assert Dec(note["subtotal"]) == 200 and Dec(note["tax_total"]) == 32 and Dec(note["total"]) == 232
    assert note["number"].startswith("CRN-")
    assert moved(before, snapshot(shop)) == {"1200": Dec(-200), "2000": Dec(232), "1300": Dec(-32)}   # owed less, VAT back
    fresh = client.get(f"{PUR}/bills/{bill['id']}", headers=shop["fm"]).json()
    assert Dec(fresh["credited"]) == 232
    ordered = client.get(f"{PUR}/orders/{order['id']}", headers=shop["owner"]).json()["lines"][0]
    assert Dec(ordered["qty_billed"]) == 6 and Dec(ordered["qty_received"]) == 6
    assert Dec(client.get(f"{PUR}/returns/{ret['id']}", headers=shop["owner"]).json()["lines"][0]["qty_credited"]) == 4
    # only 348 is still owed: pay it and the bill is paid
    pay = client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"], json={"amount": "348.00", "method": "cash"})
    assert pay.status_code == 200 and pay.json()["status"] == "paid"
    assert client.post(f"{PUR}/bills/{bill['id']}/pay", headers=shop["fm"], json={"amount": "1", "method": "cash"}
                       ).status_code == 409
    listed = client.get(f"{PUR}/credit-notes", headers=shop["fm"], params={"bill_id": bill["id"]}).json()
    assert [x["id"] for x in listed] == [note["id"]]
    assert client.get(f"{PUR}/credit-notes/{note['id']}", headers=shop["fm"]).json()["lines"][0]["return_line_id"] == line


def test_a_credit_at_another_price_goes_to_variance(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop)
    bill = post_bill(client, shop, receipt, "CRED-2")
    ret = back(client, shop, receipt, "4").json()
    before = snapshot(shop)
    r = credit(client, shop, bill, ret["lines"][0]["id"], "4", cost="45.00", no="CN-2")      # supplier credits 45 not 50
    assert r.status_code == 201, r.text
    assert Dec(r.json()["total"]) == Dec("208.80")
    assert moved(before, snapshot(shop)) == {"2000": Dec("208.80"), "2100": Dec(-200), "5200": Dec(20),
                                             "1300": Dec("-28.80")}


def test_credit_note_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop)
    bill = post_bill(client, shop, receipt, "CRED-3")
    ret = back(client, shop, receipt, "4").json()
    line = ret["lines"][0]["id"]
    for name, response in {
        "more than returned": credit(client, shop, bill, line, "5", no="C-A"),
        "unknown line": credit(client, shop, bill, str(uuid4()), "1", no="C-B"),
        "clerk": credit(client, shop, bill, line, "1", no="C-C", who="clerk"),
        "buyer": credit(client, shop, bill, line, "1", no="C-D", who="buyer"),
        "bad number": credit(client, shop, bill, line, "1", no="<x>"),
        "more than owed": credit(client, shop, bill, line, "4", cost="500.00", no="C-E"),
    }.items():
        assert response.status_code in (403, 422), (name, response.text)
    assert credit(client, shop, bill, line, "2", no="C-OK").status_code == 201
    assert credit(client, shop, bill, line, "2", no="C-OK").status_code == 409                # same supplier credit no.
    assert credit(client, shop, bill, line, "3", no="C-F").status_code == 422                # only 2 left to credit
    assert credit(client, shop, bill, line, "2", no="C-G").status_code == 201
    unrelated = new_order(client, shop, qty="2", product="bolt")
    client.post(f"{PUR}/orders/{unrelated['id']}/submit", headers=shop["owner"])
    other_receipt = receive(client, shop, client.get(f"{PUR}/orders/{unrelated['id']}", headers=shop["owner"]).json()
                            ).json()
    other_back = back(client, shop, other_receipt, "1").json()
    mismatch = credit(client, shop, bill, other_back["lines"][0]["id"], "1", no="C-H")
    assert mismatch.status_code == 422 and "not billed on this bill" in mismatch.json()["message"]
    draft = bill_for(client, shop, other_receipt, invoice="CRED-DRAFT").json()
    assert credit(client, shop, draft, other_back["lines"][0]["id"], "1", no="C-I").status_code == 409


def test_an_allowance_on_an_expense_bill(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{PUR}/bills", headers=shop["owner"], json={
        "supplier_id": shop["supplier"], "supplier_invoice_no": "ALLOW-1", "bill_date": "2026-10-10",
        "lines": [{"quantity": "1", "unit_cost": "5000.00", "expense_account_id": shop["expense"],
                   "description": "Electricity", "tax_code_id": shop["tax"]}]}).json()
    client.post(f"{PUR}/bills/{r['id']}/submit", headers=shop["owner"])                      # 5800
    before = snapshot(shop)
    note = client.post(f"{PUR}/bills/{r['id']}/credit-notes", headers=shop["fm"], json={
        "supplier_credit_no": "ALLOW-CN", "credit_date": "2026-10-13",
        "lines": [{"quantity": "1", "unit_cost": "500.00", "expense_account_id": shop["expense"],
                   "description": "Billing error", "tax_code_id": shop["tax"]}]})
    assert note.status_code == 201, note.text
    assert moved(before, snapshot(shop)) == {"2000": Dec(580), "6200": Dec(-500), "1300": Dec(-80)}
    assert Dec(client.get(f"{PUR}/bills/{r['id']}", headers=shop["fm"]).json()["credited"]) == 580


# --------------------------------------------------------------------------- landed cost
def test_a_transport_invoice_clears_the_landed_cost_of_a_receipt(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = snapshot(shop)
    r = client.post(f"{PUR}/receipts", headers=shop["owner"], json={
        "supplier_id": shop["supplier"], "location_id": shop["main"], "landed_cost": "60.00",
        "lines": [{"product_id": shop["bolt"], "quantity": "10", "unit_cost": "40"}]}).json()
    assert moved(before, snapshot(shop)) == {"1200": Dec(460), "2100": Dec(-460)}
    goods = post_bill(client, shop, r, "LAND-GOODS")                                          # clears 400
    assert Dec(goods["total"]) == 464
    mid = snapshot(shop)
    body = {"supplier_id": shop["transport"], "supplier_invoice_no": "FREIGHT-1", "bill_date": "2026-10-12",
            "lines": [{"quantity": "1", "unit_cost": "60.00", "landed_receipt_id": r["id"], "tax_code_id": shop["tax"]}]}
    bill = client.post(f"{PUR}/bills", headers=shop["owner"], json=body)
    assert bill.status_code == 201, bill.text
    done = client.post(f"{PUR}/bills/{bill.json()['id']}/submit", headers=shop["owner"]).json()
    assert done["status"] == "posted" and done["match_status"] == "matched" and Dec(done["total"]) == Dec("69.60")
    assert moved(mid, snapshot(shop)) == {"2100": Dec(60), "1300": Dec("9.60"), "2000": Dec("-69.60")}
    assert -balance(shop, "2100") + 0 >= 0
    # the freight is billed: a second invoice for the same freight is an exception
    again = client.post(f"{PUR}/bills", headers=shop["owner"], json={**body, "supplier_invoice_no": "FREIGHT-2"}).json()
    sub = client.post(f"{PUR}/bills/{again['id']}/submit", headers=shop["owner"]).json()
    assert sub["match_status"] == "exception" and "landed cost" in sub["match_notes"][0]


def test_landed_cost_lines_are_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{PUR}/receipts", headers=shop["owner"], json={
        "supplier_id": shop["supplier"], "location_id": shop["main"], "landed_cost": "10.00",
        "lines": [{"product_id": shop["bolt"], "quantity": "1", "unit_cost": "40"}]}).json()
    base = {"supplier_id": shop["transport"], "supplier_invoice_no": "FREIGHT-X", "bill_date": "2026-10-12"}
    for name, line in {
        "quantity": {"quantity": "2", "unit_cost": "5", "landed_receipt_id": r["id"]},
        "unknown receipt": {"quantity": "1", "unit_cost": "5", "landed_receipt_id": str(uuid4())},
        "and expense": {"quantity": "1", "unit_cost": "5", "landed_receipt_id": r["id"],
                        "expense_account_id": shop["expense"]},
        "and goods": {"quantity": "1", "unit_cost": "5", "landed_receipt_id": r["id"],
                      "receipt_line_id": r["lines"][0]["id"]},
    }.items():
        assert client.post(f"{PUR}/bills", headers=shop["owner"], json={**base, "lines": [line]}).status_code == 422, name
    no_landed = client.post(f"{PUR}/receipts", headers=shop["owner"], json={
        "supplier_id": shop["supplier"], "location_id": shop["main"],
        "lines": [{"product_id": shop["bolt"], "quantity": "1", "unit_cost": "40"}]}).json()
    bill = client.post(f"{PUR}/bills", headers=shop["owner"], json={**base, "supplier_invoice_no": "FREIGHT-Y", "lines": [
        {"quantity": "1", "unit_cost": "5", "landed_receipt_id": no_landed["id"]}]}).json()
    sub = client.post(f"{PUR}/bills/{bill['id']}/submit", headers=shop["owner"]).json()
    assert sub["match_status"] == "exception"
    ok = client.post(f"{PUR}/bills/{bill['id']}/approve-exception", headers=shop["fm"], json={
        "reason_code_id": shop["reasons"]["bill_exception"]})
    assert ok.status_code == 200 and ok.json()["status"] == "posted"
    assert client.post(f"{PUR}/bills/{bill['id']}/reverse", headers=shop["fm"], json={"reason": "Not ours"}
                       ).status_code == 200


# --------------------------------------------------------------------------- the record is guarded
def test_returns_and_credit_notes_cannot_be_rewritten(client, shop) -> None:  # type: ignore[no-untyped-def]
    _, receipt = order_receipt(client, shop, qty="4")
    bill = post_bill(client, shop, receipt, "GUARD-2")
    ret = back(client, shop, receipt, "2").json()
    credit(client, shop, bill, ret["lines"][0]["id"], "1", no="GUARD-CN")
    attempts = [
        "update purchasing.purchase_return_line set quantity = 9", "delete from purchasing.purchase_return_line",
        "update purchasing.purchase_return_line set qty_credited = 0 where qty_credited > 0",
        "update purchasing.purchase_return_line set qty_credited = 99",
        "update purchasing.purchase_return set note = 'x'", "delete from purchasing.purchase_return",
        "update purchasing.supplier_credit_note set total = 1", "delete from purchasing.supplier_credit_note",
        "update purchasing.supplier_credit_note_line set quantity = 9",
        "delete from purchasing.supplier_credit_note_line",
    ]
    for sql in attempts:
        with pytest.raises(DBAPIError), system(shop) as s:
            s.execute(text(sql))


def test_the_books_still_balance_and_agree_with_stock(client, shop) -> None:  # type: ignore[no-untyped-def]
    tb = client.get("/api/v1/finance/reports/trial-balance", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "as_of": "2099-01-01"}).json()
    assert tb["balanced"]
    assert one(shop, "select coalesce(sum(value), 0) from inventory.stock_movement") == balance(shop, "1200")
    owed = one(shop, "select coalesce(sum(total - amount_paid - credited), 0) from purchasing.supplier_bill "
                     "where status in ('posted', 'part_paid')")
    assert -balance(shop, "2000") == owed

"""Business customers: quotation -> order -> delivery and invoice -> payment, with credit notes and cancellations."""

from datetime import date, timedelta
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import balance
from tests.payments_helpers import one
from tests.pos_helpers import POS, credit_customer, line, make_sales_shop, stock
from tests.stock_helpers import P


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Docs Co", stock="500")
    s["rep"] = s["user"]("rep", "Sales Rep", s["branch_id"])
    return s


def doc_lines(shop, *items):  # type: ignore[no-untyped-def]
    return [{"product_id": shop[p], "quantity": q, **extra} for p, q, extra in items]


def quote(client, shop, customer, items=None, who="rep", **kw):  # type: ignore[no-untyped-def]
    items = items or [("cement", "10", {})]
    r = client.post(f"{POS}/quotations", headers=shop[who], json={
        "customer_id": customer["id"], "location_id": shop["main"], "lines": doc_lines(shop, *items), **kw})
    assert r.status_code == 201, r.text
    return r.json()


def confirmed_order(client, shop, customer, items=None, who="rep"):  # type: ignore[no-untyped-def]
    q = quote(client, shop, customer, items, who)
    client.post(f"{POS}/quotations/{q['id']}/send", headers=shop[who])
    order = client.post(f"{POS}/quotations/{q['id']}/accept", headers=shop[who]).json()
    done = client.post(f"{POS}/orders/{order['id']}/submit", headers=shop[who])
    assert done.status_code == 200 and done.json()["status"] == "confirmed", done.text
    return done.json()


def snapshot(shop):  # type: ignore[no-untyped-def]
    return {c: balance(shop, c) for c in ("1100", "4000", "2200", "5000", "1200", "1010", "1030")}


# --------------------------------------------------------------------------- quotation to payment
def test_the_whole_business_flow(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Kamau Builders", limit="50000", terms=30, customer_group="Contractors")
    # contractors get a better price on cement
    lst = client.post(f"{P}/price-lists", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": "Contractor prices", "customer_group": "Contractors"}).json()
    client.put(f"{P}/price-lists/{lst['id']}/prices", headers=shop["owner"], json={
        "product_id": shop["cement"], "price": "104.40", "valid_from": "2026-01-01"})
    q = quote(client, shop, cust, [("cement", "10", {}), ("paint", "2", {})])
    assert q["number"].startswith("QUO-HQ-") and q["status"] == "draft" and q["valid_until"]
    assert Dec(q["lines"][0]["unit_price"]) == Dec("104.40") and Dec(q["lines"][1]["unit_price"]) == 232   # group, default
    assert Dec(q["total"]) == Dec("1044.00") + 464 and Dec(q["tax_total"]) == Dec("144.00") + 64
    client.put(f"{P}/price-lists/{lst['id']}/prices", headers=shop["owner"], json={
        "product_id": shop["cement"], "price": "150.00", "valid_from": str(date.today() + timedelta(days=1))})
    assert client.post(f"{POS}/quotations/{q['id']}/send", headers=shop["rep"]).json()["status"] == "sent"
    order = client.post(f"{POS}/quotations/{q['id']}/accept", headers=shop["rep"]).json()
    assert order["doc_kind"] == "order" and order["number"].startswith("SO-HQ-") and order["status"] == "draft"
    assert order["source_quotation_id"] == q["id"] and Dec(order["total"]) == Dec(q["total"])
    assert client.get(f"{POS}/quotations/{q['id']}", headers=shop["rep"]).json()["status"] == "confirmed"
    assert client.post(f"{POS}/orders/{order['id']}/deliver", headers=shop["rep"], json={}).status_code == 409   # not confirmed
    assert client.post(f"{POS}/orders/{order['id']}/submit", headers=shop["rep"]).json()["status"] == "confirmed"

    # first delivery: 4 of the 10 cement
    cement_line = next(x for x in order["lines"] if x["product_id"] == shop["cement"])
    before, stock0 = snapshot(shop), stock(shop)
    first = client.post(f"{POS}/orders/{order['id']}/deliver", headers=shop["rep"], json={
        "lines": [{"order_line_id": cement_line["id"], "quantity": "4"}]})
    assert first.status_code == 201, first.text
    inv = first.json()
    assert inv["kind"] == "invoice" and inv["sales_order_id"] == order["id"] and Dec(inv["total"]) == Dec("417.60")
    assert inv["due_date"] == str(date.today() + timedelta(days=30)) and inv["status"] == "issued"
    assert Dec(inv["lines"][0]["unit_price"]) == Dec("104.40")                     # the agreed price, not today's list
    assert stock(shop) == stock0 - 4
    after = snapshot(shop)
    assert after["1100"] - before["1100"] == Dec("417.60") and after["5000"] - before["5000"] == 200
    assert client.get(f"{POS}/orders/{order['id']}", headers=shop["rep"]).json()["status"] == "confirmed"
    # the rest
    rest = client.post(f"{POS}/orders/{order['id']}/deliver", headers=shop["rep"], json={})
    assert rest.status_code == 201 and Dec(rest.json()["total"]) == Dec("626.40") + 464
    done = client.get(f"{POS}/orders/{order['id']}", headers=shop["rep"]).json()
    assert done["status"] == "fulfilled" and all(Dec(x["qty_delivered"]) == Dec(x["quantity"]) for x in done["lines"])
    assert client.post(f"{POS}/orders/{order['id']}/deliver", headers=shop["rep"], json={}).status_code == 409
    assert Dec(client.get(f"{POS}/invoices/{inv['id']}", headers=shop["rep"]).json()["total"]) == Dec("417.60")

    # the customer pays the first invoice by M-Pesa and the second part by bank, oldest first
    pay = client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "417.60", "method": "mobile_money", "branch_id": str(shop["branch_id"]),
        "external_ref": "KAMAU001"})
    assert pay.status_code == 201 and pay.json()["allocations"][0]["invoice_id"] == inv["id"]
    assert client.get(f"{POS}/invoices/{inv['id']}", headers=shop["fm"]).json()["status"] == "paid"
    owed = one(shop, "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice where "
                     "customer_id = :c and status in ('issued', 'part_paid')", c=cust["id"])
    assert owed == Dec("1090.40")
    assert balance(shop, "1100") - before["1100"] == Dec("417.60") + Dec("1090.40") - Dec("417.60")


def test_a_quotation_can_be_changed_expires_and_is_cancelled(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Quote Changes", limit="50000")
    q = quote(client, shop, cust, [("cement", "2", {})])
    changed = client.put(f"{POS}/quotations/{q['id']}", headers=shop["rep"], json={
        "lines": doc_lines(shop, ("cement", "5", {}), ("delivery", "1", {})), "notes": "Delivery included"})
    assert changed.status_code == 200 and len(changed.json()["lines"]) == 2
    assert Dec(changed.json()["total"]) == 580 + 58
    client.post(f"{POS}/quotations/{q['id']}/send", headers=shop["rep"])
    assert client.put(f"{POS}/quotations/{q['id']}", headers=shop["rep"], json={"notes": "x"}).status_code == 409
    assert client.post(f"{POS}/quotations/{q['id']}/cancel", headers=shop["rep"]).json()["status"] == "cancelled"
    assert client.post(f"{POS}/quotations/{q['id']}/accept", headers=shop["rep"]).status_code == 409
    old = quote(client, shop, cust, valid_until=str(date.today()))
    from sqlalchemy import text

    from tests.stock_helpers import system

    with system(shop) as s:
        s.execute(text("update pos.sales_document set valid_until = current_date - 1 where id = :i"), {"i": old["id"]})
    assert client.get(f"{POS}/quotations/{old['id']}", headers=shop["rep"]).json()["status"] == "expired"
    expired = client.post(f"{POS}/quotations/{old['id']}/accept", headers=shop["rep"])
    assert expired.status_code == 409 and "expired" in expired.json()["message"]
    assert client.post(f"{POS}/quotations", headers=shop["rep"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "valid_until": "2020-01-01",
        "lines": doc_lines(shop, ("cement", "1", {}))}).status_code == 422


def test_quotation_and_order_validation_and_permissions(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Validates", limit="50000")
    base = {"customer_id": cust["id"], "location_id": shop["main"], "lines": doc_lines(shop, ("cement", "1", {}))}
    for name, change in {
        "no lines": {"lines": []}, "bad qty": {"lines": doc_lines(shop, ("cement", "0", {}))},
        "service has no stock location": {"location_id": None, "branch_id": None},
        "unknown customer": {"customer_id": str(uuid4())}, "unknown location": {"location_id": str(uuid4())},
        "bad terms": {"terms_days": 400},
        "discount without right": {"lines": doc_lines(shop, ("cement", "1", {"discount": "10"}))},
    }.items():
        assert client.post(f"{POS}/quotations", headers=shop["rep"], json={**base, **change}).status_code in (
            403, 422), name
    assert client.post(f"{POS}/quotations", headers=shop["cashier"], json=base).status_code == 403
    assert client.post(f"{POS}/quotations", headers=shop["storekeeper"], json=base).status_code == 403
    assert client.get(f"{POS}/quotations", headers=shop["storekeeper"]).status_code == 403
    juja_rep = shop["user"]("jujarep", "Sales Rep", shop["juja"])
    assert client.post(f"{POS}/quotations", headers=juja_rep, json=base).status_code == 403          # not that branch
    made = quote(client, shop, cust)
    assert client.get(f"{POS}/quotations/{made['id']}", headers=juja_rep).status_code == 404
    assert client.get(f"{POS}/orders/{made['id']}", headers=shop["rep"]).status_code == 404            # it is a quotation
    discounted = client.post(f"{POS}/quotations", headers=shop["manager"], json={
        **base, "lines": doc_lines(shop, ("cement", "1", {"discount": "10", "reason_code_id":
                                                           shop["reasons"]["price_override"]}))})
    assert discounted.status_code == 201 and Dec(discounted.json()["total"]) == 106
    on_hold = credit_customer(client, shop, name="Inactive One")
    client.patch(f"/api/v1/crm/customers/{on_hold['id']}", headers=shop["owner"], json={"status": "inactive"})
    assert client.post(f"{POS}/quotations", headers=shop["rep"], json={**base, "customer_id": on_hold["id"]}
                       ).status_code == 422


def test_a_large_order_waits_for_an_approver_and_orders_can_be_cancelled(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Big Orders", limit="500000")
    rule = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "sales_order",
        "approver_role_id": shop["roles"]["Finance Manager"], "min_amount": "5000"})
    assert rule.status_code == 201, rule.text
    small = client.post(f"{POS}/orders", headers=shop["rep"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "lines": doc_lines(shop, ("cement", "5", {}))}).json()
    assert client.post(f"{POS}/orders/{small['id']}/submit", headers=shop["rep"]).json()["status"] == "confirmed"
    big = client.post(f"{POS}/orders", headers=shop["rep"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "lines": doc_lines(shop, ("cement", "100", {}))}).json()
    assert client.post(f"{POS}/orders/{big['id']}/submit", headers=shop["rep"]).json()["status"] == "pending_approval"
    assert client.post(f"{POS}/orders/{big['id']}/deliver", headers=shop["rep"], json={}).status_code == 409
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm"]).json()
    request = next(x for x in pending if x["doc_id"] == big["id"])
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm"],
                       json={"approve": True}).status_code == 200
    assert client.get(f"{POS}/orders/{big['id']}", headers=shop["rep"]).json()["status"] == "confirmed"
    # cancel: fine until something is delivered
    cancelled = client.post(f"{POS}/orders/{small['id']}/cancel", headers=shop["rep"])
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(f"{POS}/orders/{small['id']}/cancel", headers=shop["rep"]).status_code == 409
    part = client.post(f"{POS}/orders/{big['id']}/deliver", headers=shop["rep"], json={
        "lines": [{"order_line_id": big["lines"][0]["id"], "quantity": "1"}]})
    assert part.status_code == 201
    assert client.post(f"{POS}/orders/{big['id']}/cancel", headers=shop["rep"]).status_code == 409


def test_delivery_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Delivery Rules", limit="500")
    order = confirmed_order(client, shop, cust, [("cement", "3", {})])                        # 348, under the limit
    lid = order["lines"][0]["id"]
    path = f"{POS}/orders/{order['id']}/deliver"
    for body in ({"lines": [{"order_line_id": lid, "quantity": "4"}]}, {"lines": [{"order_line_id": str(uuid4()),
                                                                              "quantity": "1"}]},
                 {"lines": [{"order_line_id": lid, "quantity": "1"}] * 2}, {"lines": []},
                 {"location_id": str(uuid4())}):
        assert client.post(path, headers=shop["rep"], json=body).status_code == 422, body
    assert client.post(path, headers=shop["cashier"], json={}).status_code == 403
    assert client.post(path, headers=shop["rep"], json={"lines": [{"order_line_id": lid, "quantity": "3"}]}
                       ).status_code == 201
    over = confirmed_order(client, shop, cust, [("cement", "3", {})])                         # another 348: 696 > 500
    refused = client.post(f"{POS}/orders/{over['id']}/deliver", headers=shop["rep"], json={})
    assert refused.status_code == 422 and "credit limit" in refused.json()["message"]
    assert client.get(f"{POS}/orders/{over['id']}", headers=shop["rep"]).json()["status"] == "confirmed"


def test_the_discount_on_an_order_line_is_shared_out_across_deliveries(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Discounted Order", limit="100000")
    q = client.post(f"{POS}/quotations", headers=shop["manager"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "lines": doc_lines(
            shop, ("cement", "7", {"discount": "50.00", "reason_code_id": shop["reasons"]["price_override"]}))}).json()
    assert Dec(q["total"]) == 812 - 50
    order = client.post(f"{POS}/quotations/{q['id']}/accept", headers=shop["manager"]).json()
    client.post(f"{POS}/orders/{order['id']}/submit", headers=shop["manager"])
    totals = []
    for qty in ("3", "3", "1"):
        r = client.post(f"{POS}/orders/{order['id']}/deliver", headers=shop["manager"], json={
            "lines": [{"order_line_id": order["lines"][0]["id"], "quantity": qty}]})
        assert r.status_code == 201, r.text
        totals.append(Dec(r.json()["total"]))
    assert sum(totals) == 762                                                                  # exactly the order's total
    assert client.get(f"{POS}/orders/{order['id']}", headers=shop["manager"]).json()["status"] == "fulfilled"


# --------------------------------------------------------------------------- invoices directly, credit notes, cancelling
def direct_invoice(client, shop, cust, qty="4", who="rep", **kw):  # type: ignore[no-untyped-def]
    r = client.post(f"{POS}/invoices", headers=shop[who], json={
        "customer_id": cust["id"], "location_id": shop["main"], "lines": doc_lines(shop, ("cement", qty, {})), **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_an_invoice_without_an_order_and_a_credit_note_for_goods_taken_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Direct Invoice", limit="50000", terms=7)
    inv = direct_invoice(client, shop, cust, "4")                                              # 464
    assert Dec(inv["total"]) == 464 and inv["due_date"] == str(date.today() + timedelta(days=7))
    before, stock0 = snapshot(shop), stock(shop)
    line_id = inv["lines"][0]["id"]
    path = f"{POS}/invoices/{inv['id']}/returns"
    body = {"lines": [{"invoice_line_id": line_id, "quantity": "1"}], "reason_code_id": shop["reasons"]["sale_return"]}
    assert client.post(path, headers=shop["rep"], json={**body, "refund_method": "credit_note"}).status_code == 403
    cash = client.post(path, headers=shop["manager"], json={**body, "refund_method": "cash"})
    assert cash.status_code == 422 and "credit note" in cash.json()["message"]                  # still owed: not cash
    ok = client.post(path, headers=shop["manager"], json={**body, "refund_method": "credit_note"})
    assert ok.status_code == 201 and ok.json()["original_invoice_id"] == inv["id"], ok.text
    got = client.get(f"{POS}/invoices/{inv['id']}", headers=shop["fm"]).json()
    assert Dec(got["credited"]) == 116 and got["status"] == "part_paid"
    assert stock(shop) == stock0 + 1
    after = snapshot(shop)
    assert after["1100"] - before["1100"] == -116 and after["4000"] == before["4000"]
    assert Dec(client.get(f"{POS}/returns/{ok.json()['id']}", headers=shop["manager"]).json()["total"]) == 116
    too_much = client.post(path, headers=shop["manager"], json={
        **body, "lines": [{"invoice_line_id": line_id, "quantity": "4"}], "refund_method": "credit_note"})
    assert too_much.status_code == 422
    # pay the rest, then a further return is refunded in cash
    client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "348.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    from tests.pos_helpers import ensure_till

    ensure_till(client, shop, "manager")
    assert client.post(path, headers=shop["manager"], json={**body, "refund_method": "credit_note"}).status_code == 422
    refund = client.post(path, headers=shop["manager"], json={**body, "refund_method": "cash"})
    assert refund.status_code == 201, refund.text
    assert client.post(f"{POS}/invoices/{inv['id']}/cancel", headers=shop["rep"], json={"reason": "x"}
                       ).status_code in (409, 422)                                              # paid and returned on


def test_cancelling_an_invoice_puts_the_goods_and_the_books_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Cancelled Invoice", limit="50000")
    order = confirmed_order(client, shop, cust, [("cement", "3", {})])
    inv = client.post(f"{POS}/orders/{order['id']}/deliver", headers=shop["rep"], json={}).json()
    before, stock0 = snapshot(shop), stock(shop)
    path = f"{POS}/invoices/{inv['id']}/cancel"
    assert client.post(path, headers=shop["cashier"], json={"reason": "x"}).status_code == 403
    assert client.post(path, headers=shop["rep"], json={"reason": " "}).status_code == 422
    done = client.post(path, headers=shop["rep"], json={"reason": "Customer changed their mind"})
    assert done.status_code == 200 and done.json()["status"] == "cancelled"
    assert stock(shop) == stock0 + 3
    after = snapshot(shop)
    assert after["1100"] - before["1100"] == -348 and after["5000"] - before["5000"] == -150
    assert one(shop, "select count(*) from pos.sales_invoice where id = :i and status = 'cancelled'", i=inv["id"]) == 1
    # the order can be delivered again: what was delivered is back to deliver
    again = client.get(f"{POS}/orders/{order['id']}", headers=shop["rep"]).json()
    assert Dec(again["lines"][0]["qty_delivered"]) == 0 and again["status"] == "fulfilled"
    assert client.post(path, headers=shop["rep"], json={"reason": "again"}).status_code == 409
    paid = direct_invoice(client, shop, cust, "1")
    client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "10.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    refused = client.post(f"{POS}/invoices/{paid['id']}/cancel", headers=shop["rep"], json={"reason": "x"})
    assert refused.status_code == 409 and "reverse its payments" in refused.json()["message"]


def test_direct_invoice_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = credit_customer(client, shop, name="Direct Rules", limit="300")
    base = {"customer_id": cust["id"], "location_id": shop["main"], "lines": doc_lines(shop, ("cement", "1", {}))}
    for name, change in {
        "no lines": {"lines": []}, "over the limit": {"lines": doc_lines(shop, ("cement", "3", {}))},
        "no location for stock": {"location_id": None}, "unknown customer": {"customer_id": str(uuid4())},
        "bad terms": {"terms_days": 999}, "discount without right": {"lines": doc_lines(shop, ("cement", "1",
                                                                                           {"discount": "5"}))},
        "unknown product": {"lines": [{"product_id": str(uuid4()), "quantity": "1"}]},
    }.items():
        assert client.post(f"{POS}/invoices", headers=shop["rep"], json={**base, **change}).status_code in (
            403, 422), name
    assert client.post(f"{POS}/invoices", headers=shop["cashier"], json=base).status_code == 403
    juja_keeper = shop["user"]("jujainvoice", "Sales Rep", shop["juja"])
    assert client.post(f"{POS}/invoices", headers=juja_keeper, json=base).status_code == 403
    service = client.post(f"{POS}/invoices", headers=shop["rep"], json={
        "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "lines": doc_lines(shop, ("delivery", "1", {}))})
    assert service.status_code == 201 and Dec(service.json()["total"]) == 58                 # a service needs no stock
    assert client.get(f"{POS}/invoices", headers=shop["storekeeper"]).status_code == 403
    listed = client.get(f"{POS}/invoices", headers=shop["rep"], params={"customer_id": cust["id"]}).json()
    assert service.json()["id"] in {x["id"] for x in listed}
    assert client.get(f"{POS}/invoices/{uuid4()}", headers=shop["rep"]).status_code == 404
    by_number = client.get(f"{POS}/invoices", headers=shop["rep"], params={"number": service.json()["number"].lower()})
    assert [x["id"] for x in by_number.json()] == [service.json()["id"]]


def test_issued_invoices_cannot_be_rewritten(client, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from tests.stock_helpers import system

    cust = credit_customer(client, shop, name="Guarded", limit="50000")
    inv = direct_invoice(client, shop, cust, "2")
    for sql in ("update pos.sales_invoice set total = 1 where id = :i", "update pos.sales_invoice set number = 'X' "
                "where id = :i", "delete from pos.sales_invoice where id = :i",
                "update pos.sales_invoice set amount_paid = 99999 where id = :i",
                "update pos.sales_invoice_line set quantity = 9 where invoice_id = :i",
                "delete from pos.sales_invoice_line where invoice_id = :i",
                "update pos.sales_invoice_line set cost_amount = 1 where invoice_id = :i"):
        with pytest.raises(DBAPIError), system(shop) as s:
            s.execute(text(sql), {"i": inv["id"]})
    assert line is not None

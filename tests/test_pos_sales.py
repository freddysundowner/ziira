"""Selling at the till: pricing, VAT, payments, stock, overrides, voids, returns, and who may do what."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.payments_helpers import PAY, fresh_ref, one
from tests.pos_helpers import POS, ensure_till, line, make_pos_shop, open_till, sell, stock
from tests.stock_helpers import P, system
from tests.test_lifecycle_more import together


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_pos_shop(client, registry, "Pos Sales Co", stock="200")
    s["noprice"] = client.post(f"{P}/products", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "sku": "NOPRICE", "name": "No price", "base_uom_id": s["uom"],
        "tax_code_id": s["tax"], "product_type": "non_stock"}).json()["id"]
    return s


def sale_count(shop) -> int:  # type: ignore[no-untyped-def]
    return one(shop, "select count(*) from pos.sale")


def payments_of(client, shop, sale):  # type: ignore[no-untyped-def]
    return [client.get(f"{PAY}/payments/{p['payment_id']}", headers=shop["owner"]).json() for p in sale["payments"]]


# --------------------------------------------------------------------------- a sale
def test_a_cash_sale_takes_stock_records_the_payment_and_the_cost(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = stock(shop)
    r = sell(client, shop, lines=[line(shop, "cement", "2")], payments=[{"method": "cash", "amount": "232.00"}])
    assert r.status_code == 201, r.text
    sale = r.json()
    assert Dec(sale["total"]) == 232 and Dec(sale["tax_total"]) == 32 and Dec(sale["subtotal"]) == 232
    assert sale["number"].startswith("POS-HQ-D1-") and sale["status"] == "posted" and not sale["synced_offline"]
    [l1] = sale["lines"]
    assert Dec(l1["unit_price"]) == 116 == Dec(l1["list_price"]) and Dec(l1["cost_amount"]) == 100   # 2 x cost 50
    assert stock(shop) == before - 2
    [pay] = payments_of(client, shop, sale)
    assert pay["method"] == "cash" and pay["direction"] == "in" and Dec(pay["amount"]) == 232
    assert pay["till_session_id"] == sale["till_session_id"] and pay["business_date"] == sale["business_date"]
    assert client.get(f"{POS}/sales/{sale['id']}", headers=shop["cashier"]).json()["lines"][0]["id"] == l1["id"]


def test_numbers_run_on_per_device(client, shop) -> None:  # type: ignore[no-untyped-def]
    first, second = (sell(client, shop).json()["number"] for _ in range(2))
    assert int(second.rsplit("-", 1)[1]) == int(first.rsplit("-", 1)[1]) + 1


def test_cash_change_is_not_recorded_as_takings(client, shop) -> None:  # type: ignore[no-untyped-def]
    sale = sell(client, shop, payments=[{"method": "cash", "amount": "200.00"}]).json()
    assert Dec(sale["change"]) == 84 and Dec(sale["payments"][0]["amount"]) == 116 and Dec(sale["total"]) == 116


def test_an_mpesa_sale_needs_its_code_and_reaches_the_matching_queue(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert sell(client, shop, payments=[{"method": "mobile_money", "amount": "116.00"}]).status_code == 422
    ref = fresh_ref()
    r = sell(client, shop, payments=[{"method": "mobile_money", "amount": "116.00", "external_ref": ref}])
    assert r.status_code == 201, r.text
    [pay] = payments_of(client, shop, r.json())
    assert pay["method"] == "mobile_money" and pay["external_ref"] == ref and pay["payment_account_id"] == shop["till"]
    again = sell(client, shop, payments=[{"method": "mobile_money", "amount": "116.00", "external_ref": ref}])
    assert again.status_code == 409                                       # the same code cannot pay twice


def test_a_split_payment_and_several_lines_with_a_service_and_a_batch_product(client, shop) -> None:  # type: ignore[no-untyped-def]
    cement, paint = stock(shop, "cement"), stock(shop, "paint")
    r = sell(client, shop,
             lines=[line(shop, "cement", "1"), line(shop, "paint", "2"), line(shop, "delivery", "1")],
             payments=[{"method": "card", "amount": "300.00", "external_ref": "SLIP9"},
                       {"method": "cash", "amount": "1000.00"}])
    assert r.status_code == 201, r.text
    sale = r.json()
    assert Dec(sale["total"]) == 116 + 464 + 58 and Dec(sale["tax_total"]) == Dec("16.00") + Dec("64.00") + Dec("8.00")
    assert {p["method"]: Dec(p["amount"]) for p in sale["payments"]} == {"card": 300, "cash": 338}
    assert stock(shop, "cement") == cement - 1 and stock(shop, "paint") == paint - 2          # the service moved nothing
    assert one(shop, "select count(*) from inventory.stock_movement where source_id = :s", s=sale["id"]) == 2


def test_the_sale_is_refused_whole_when_stock_is_short(client, shop) -> None:  # type: ignore[no-untyped-def]
    n, s_before = sale_count(shop), stock(shop)
    payments_before = one(shop, "select count(*) from payments.payment")
    r = sell(client, shop, lines=[line(shop, "cement", "100000")], payments=[{"method": "cash", "amount": "11600000"}])
    assert r.status_code == 422
    assert sale_count(shop) == n and stock(shop) == s_before
    assert one(shop, "select count(*) from payments.payment") == payments_before          # nothing half-recorded


# --------------------------------------------------------------------------- validation
def test_a_sale_is_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = ensure_till(client, shop)
    bad = [
        {"lines": [], "payments": [{"method": "cash", "amount": "1"}]},
        {"lines": [line(shop, qty="0")], "payments": [{"method": "cash", "amount": "1"}]},
        {"lines": [line(shop, qty="-1")], "payments": [{"method": "cash", "amount": "1"}]},
        {"lines": [line(shop, qty="1.00001")], "payments": [{"method": "cash", "amount": "1"}]},
        {"lines": [line(shop)], "payments": []},
        {"lines": [line(shop)], "payments": [{"method": "cash", "amount": "100"}]},                  # short
        {"lines": [line(shop)], "payments": [{"method": "credit", "amount": "116"}]},
        {"lines": [line(shop)], "payments": [{"method": "cash", "amount": "0"}]},
        {"lines": [line(shop)], "payments": [{"method": "cash", "amount": "116.005"}]},
        {"lines": [line(shop)], "payments": [{"method": "mobile_money", "amount": "500", "external_ref": "X"}]},   # over
        {"lines": [line(shop)] * 201, "payments": [{"method": "cash", "amount": "99999"}]},
    ]
    for body in bad:
        r = client.post(f"{POS}/sales", headers=shop["cashier"], json={"till_session_id": till, **body})
        assert r.status_code == 422, (body, r.text)
    unknown = sell(client, shop, lines=[{"product_id": str(uuid4()), "quantity": "1"}])
    assert unknown.status_code == 422 and "not found" in unknown.json()["message"]
    assert sell(client, shop, till=str(uuid4())).status_code == 404
    assert one(shop, "select count(*) from pos.sale where total <= 0") == 0


def test_a_product_without_a_price_cannot_be_sold_by_a_cashier(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = sell(client, shop, lines=[{"product_id": shop["noprice"], "quantity": "1"}])
    assert r.status_code == 422 and "no price" in r.json()["message"]
    r = sell(client, shop, lines=[{"product_id": shop["noprice"], "quantity": "1", "unit_price": "50.00"}])
    assert r.status_code == 403                                             # a price from nowhere is an override


# --------------------------------------------------------------------------- price overrides
def test_changing_a_price_or_discounting_needs_permission_and_a_reason(client, shop) -> None:  # type: ignore[no-untyped-def]
    reason = shop["reasons"]["price_override"]
    discounted = [line(shop, "cement", "2", discount="32.00", reason_code_id=reason)]
    pay = [{"method": "cash", "amount": "200.00"}]
    assert sell(client, shop, lines=[line(shop, "cement", "2", discount="32.00")], payments=pay).status_code == 403
    assert sell(client, shop, lines=discounted, payments=pay).status_code == 403                 # a cashier may not
    manager_till = ensure_till(client, shop, "manager")
    no_reason = sell(client, shop, who="manager", till=manager_till,
                     lines=[line(shop, "cement", "2", discount="32.00")], payments=pay)
    assert no_reason.status_code == 422
    r = sell(client, shop, who="manager", till=manager_till, lines=discounted, payments=pay)
    assert r.status_code == 201, r.text
    sale = r.json()
    assert Dec(sale["total"]) == 200 and Dec(sale["discount_total"]) == 32 and Dec(sale["tax_total"]) == Dec("27.59")
    assert Dec(sale["lines"][0]["list_price"]) == 116
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'discount.override' and "
                     "aggregate_id = :i", i=sale["id"]) == 1
    price = sell(client, shop, who="manager", till=manager_till, lines=[line(shop, "cement", "1", unit_price="100.00",
                                                                         reason_code_id=reason)],
                 payments=[{"method": "cash", "amount": "100"}])
    assert price.status_code == 201 and Dec(price.json()["lines"][0]["unit_price"]) == 100
    wrong_list = sell(client, shop, who="manager", till=manager_till,
                      lines=[line(shop, "cement", "1", discount="1", reason_code_id=shop["reasons"]["void"])],
                      payments=[{"method": "cash", "amount": "115"}])
    assert wrong_list.status_code == 422                                  # a reason from the wrong list
    open_price = sell(client, shop, who="manager", till=manager_till, lines=[
        {"product_id": shop["noprice"], "quantity": "1", "unit_price": "50.00", "reason_code_id": reason}],
        payments=[{"method": "cash", "amount": "50"}])
    assert open_price.status_code == 201


# --------------------------------------------------------------------------- who, which till
def test_who_may_sell_and_on_which_till(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = ensure_till(client, shop)
    assert sell(client, shop, who="storekeeper", till=till).status_code == 403                 # no sales permission
    assert sell(client, shop, who="manager", till=till).status_code == 403                     # another cashier's till
    juja = shop["user"]("jujacashier", "Cashier", shop["juja"])
    assert sell(client, shop, who="cashier", till=till).status_code == 201
    r = client.post(f"{POS}/sales", headers=juja, json={"till_session_id": till, "lines": [line(shop)],
                                                         "payments": [{"method": "cash", "amount": "116"}]})
    assert r.status_code == 403
    assert client.get(f"{POS}/sales", headers=juja).json() == []                               # sees only its branch
    sale_id = client.get(f"{POS}/sales", headers=shop["cashier"]).json()[0]["id"]
    assert client.get(f"{POS}/sales/{sale_id}", headers=juja).status_code == 404
    assert client.get(f"{POS}/sales/{uuid4()}", headers=shop["cashier"]).status_code == 404
    assert client.get(f"{POS}/sales", headers=shop["storekeeper"]).status_code == 403


def test_a_closed_till_and_a_blocked_device_cannot_sell(client, shop, registry) -> None:  # type: ignore[no-untyped-def]
    cashier2 = shop["user"]("cashier2", "Cashier", shop["branch_id"])
    dev = client.post(f"{POS}/devices", headers=shop["owner"], json={
        "branch_id": str(shop["branch_id"]), "code": "X2", "name": "Counter X2", "location_id": shop["main"]}).json()
    shop["cashier2"] = cashier2
    till = open_till(client, shop, "cashier2", device=dev["id"]).json()
    close = client.post(f"{POS}/tills/{till['id']}/close", headers=cashier2, json={"counted_cash": "1000.00"})
    assert close.status_code == 200, close.text
    r = client.post(f"{POS}/sales", headers=cashier2, json={"till_session_id": till["id"], "lines": [line(shop)],
                                                             "payments": [{"method": "cash", "amount": "116"}]})
    assert r.status_code == 409 and "closed" in r.json()["message"]
    reopened = open_till(client, shop, "cashier2", device=dev["id"]).json()
    client.patch(f"{POS}/devices/{dev['id']}/status", headers=shop["owner"], json={"status": "blocked"})
    r = client.post(f"{POS}/sales", headers=cashier2, json={"till_session_id": reopened["id"], "lines": [line(shop)],
                                                             "payments": [{"method": "cash", "amount": "116"}]})
    assert r.status_code == 422 and "blocked" in r.json()["message"]
    client.post(f"{POS}/tills/{reopened['id']}/close", headers=cashier2, json={"counted_cash": "1000.00"})


# --------------------------------------------------------------------------- retries
def test_a_retried_sale_is_recorded_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    local = str(uuid4())
    before, n = stock(shop), sale_count(shop)
    first = sell(client, shop, local_id=local)
    again = sell(client, shop, local_id=local)
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["id"] == again.json()["id"] and again.json()["replayed"] is True
    assert stock(shop) == before - 1 and sale_count(shop) == n + 1
    key = {"Idempotency-Key": "till-1-sale-77"}
    till = ensure_till(client, shop)
    body = {"till_session_id": till, "lines": [line(shop)], "payments": [{"method": "cash", "amount": "116"}]}
    a = client.post(f"{POS}/sales", headers={**shop["cashier"], **key}, json=body)
    b = client.post(f"{POS}/sales", headers={**shop["cashier"], **key}, json=body)
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]


def test_the_same_sale_arriving_at_once_is_recorded_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    local, till = str(uuid4()), ensure_till(client, shop)
    body = {"till_session_id": till, "local_id": local, "lines": [line(shop)],
            "payments": [{"method": "cash", "amount": "116"}]}
    before = stock(shop)
    results = together([lambda: client.post(f"{POS}/sales", headers=shop["cashier"], json=body) for _ in range(6)])
    assert sorted(r.status_code for r in results) == [200] * 5 + [201]
    assert len({r.json()["id"] for r in results}) == 1 and stock(shop) == before - 1


# --------------------------------------------------------------------------- voids
def test_voiding_a_sale_puts_everything_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    manager_till = ensure_till(client, shop, "manager")
    sale = sell(client, shop, who="manager", till=manager_till, lines=[line(shop, "cement", "3")],
                payments=[{"method": "cash", "amount": "348.00"}]).json()
    before = stock(shop)
    reason = shop["reasons"]["void"]
    assert client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["cashier"],
                       json={"reason_code_id": reason}).status_code == 403
    assert client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"], json={}).status_code == 422
    wrong = client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"],
                        json={"reason_code_id": shop["reasons"]["price_override"]})
    assert wrong.status_code == 422
    r = client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"], json={"reason_code_id": reason})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "voided" and stock(shop) == before + 3
    [pay] = payments_of(client, shop, sale)
    assert pay["status"] == "reversed"
    assert client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"],
                       json={"reason_code_id": reason}).status_code == 409
    movement = one(shop, "select count(*) from inventory.stock_movement where source_type = 'sale_return' and "
                         "source_id = :s", s=sale["id"])
    assert movement == 1
    assert one(shop, "select sum(value) from inventory.stock_movement where source_id = :s", s=sale["id"]) == 0


def test_a_sale_on_a_closed_till_is_returned_not_voided(client, shop) -> None:  # type: ignore[no-untyped-def]
    cashier3 = shop["user"]("cashier3", "Cashier", shop["branch_id"])
    dev = client.post(f"{POS}/devices", headers=shop["owner"], json={
        "branch_id": str(shop["branch_id"]), "code": "X3", "name": "Counter X3", "location_id": shop["main"]}).json()
    shop["cashier3"] = cashier3
    till = open_till(client, shop, "cashier3", device=dev["id"]).json()
    sale = sell(client, shop, who="cashier3", till=till["id"]).json()
    client.post(f"{POS}/tills/{till['id']}/close", headers=cashier3, json={
        "counted_cash": "1116.00"})
    r = client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"],
                    json={"reason_code_id": shop["reasons"]["void"]})
    assert r.status_code == 422 and "return" in r.json()["message"]


# --------------------------------------------------------------------------- returns
def return_body(shop, sale, qty="1", method="cash", **kw):  # type: ignore[no-untyped-def]
    return {"lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": qty}],
            "reason_code_id": shop["reasons"]["sale_return"], "refund_method": method, **kw}


def test_a_return_refunds_what_the_line_sold_for_and_restocks(client, shop) -> None:  # type: ignore[no-untyped-def]
    manager_till = ensure_till(client, shop, "manager")
    sale = sell(client, shop, who="manager", till=manager_till, lines=[line(shop, "cement", "2")],
                payments=[{"method": "cash", "amount": "232.00"}]).json()
    before = stock(shop)
    assert client.post(f"{POS}/sales/{sale['id']}/returns", headers=shop["cashier"],
                       json=return_body(shop, sale)).status_code == 403
    r = client.post(f"{POS}/sales/{sale['id']}/returns", headers=shop["manager"], json=return_body(shop, sale, "1"))
    assert r.status_code == 201, r.text
    ret = r.json()
    assert ret["status"] == "posted" and Dec(ret["total"]) == 116 and ret["number"].startswith("RET-HQ-")
    assert stock(shop) == before + 1
    out = [p for p in client.get(f"{PAY}/payments", headers=shop["owner"], params={"method": "cash"}).json()
           if p["direction"] == "out" and Dec(p["amount"]) == 116]
    assert out and out[0]["till_session_id"] == manager_till
    second = client.post(f"{POS}/sales/{sale['id']}/returns", headers=shop["manager"], json=return_body(shop, sale, "1"))
    assert second.status_code == 201 and stock(shop) == before + 2
    over = client.post(f"{POS}/sales/{sale['id']}/returns", headers=shop["manager"], json=return_body(shop, sale, "1"))
    assert over.status_code == 422 and "Only 0" in over.json()["message"]
    assert client.post(f"{POS}/sales/{sale['id']}/void", headers=shop["manager"],
                       json={"reason_code_id": shop["reasons"]["void"]}).status_code == 422       # returned already
    got = client.get(f"{POS}/returns/{ret['id']}", headers=shop["manager"]).json()
    assert got["lines"][0]["sale_line_id"] == sale["lines"][0]["id"]
    assert ret["id"] in {x["id"] for x in client.get(f"{POS}/returns", headers=shop["manager"]).json()}


def test_return_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    manager_till = ensure_till(client, shop, "manager")
    sale = sell(client, shop, who="manager", till=manager_till).json()
    base = return_body(shop, sale)
    path = f"{POS}/sales/{sale['id']}/returns"
    for body in ({**base, "lines": []}, {**base, "refund_method": "credit_note"}, {**base, "reason_code_id": str(uuid4())},
                 {**base, "lines": [{"sale_line_id": str(uuid4()), "quantity": "1"}]},
                 {**base, "lines": base["lines"] * 2}, {**base, "restock_location_id": str(uuid4())}):
        assert client.post(path, headers=shop["manager"], json=body).status_code == 422, body
    assert client.post(f"{POS}/sales/{uuid4()}/returns", headers=shop["manager"], json=base).status_code == 404
    ex = client.post(path, headers=shop["manager"], json=return_body(shop, sale, method="exchange"))
    assert ex.status_code == 201 and ex.json()["status"] == "posted"


def test_a_large_refund_waits_for_an_approver(client, shop) -> None:  # type: ignore[no-untyped-def]
    rule = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "sales_return",
        "approver_role_id": shop["roles"]["Finance Manager"], "min_amount": "200"})
    assert rule.status_code == 201, rule.text
    manager_till = ensure_till(client, shop, "manager")
    sale = sell(client, shop, who="manager", till=manager_till, lines=[line(shop, "cement", "3")],
                payments=[{"method": "cash", "amount": "348.00"}]).json()
    before = stock(shop)
    small = client.post(f"{POS}/sales/{sale['id']}/returns", headers=shop["manager"], json=return_body(shop, sale, "1"))
    assert small.json()["status"] == "posted"                                                    # below 200
    big = client.post(f"{POS}/sales/{sale['id']}/returns", headers=shop["manager"], json=return_body(shop, sale, "2"))
    assert big.status_code == 201 and big.json()["status"] == "pending_approval"
    assert stock(shop) == before + 1                                                             # nothing moved yet
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm"]).json()
    request = next(x for x in pending if x["doc_id"] == big.json()["id"])
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm"],
                       json={"approve": True}).status_code == 200
    assert client.get(f"{POS}/returns/{big.json()['id']}", headers=shop["manager"]).json()["status"] == "posted"
    assert stock(shop) == before + 3
    # a rejected one never moves anything
    sale2 = sell(client, shop, who="manager", till=manager_till, lines=[line(shop, "cement", "3")],
                 payments=[{"method": "cash", "amount": "348.00"}]).json()
    before = stock(shop)
    waiting = client.post(f"{POS}/sales/{sale2['id']}/returns", headers=shop["manager"],
                          json=return_body(shop, sale2, "3")).json()
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm"]).json()
    request = next(x for x in pending if x["doc_id"] == waiting["id"])
    client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm"],
                json={"approve": False, "note": "No"})
    assert client.get(f"{POS}/returns/{waiting['id']}", headers=shop["manager"]).json()["status"] == "rejected"
    assert stock(shop) == before


# --------------------------------------------------------------------------- the record cannot be rewritten
def test_a_posted_sale_cannot_be_edited_or_deleted(client, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import DBAPIError

    sale = sell(client, shop).json()
    attempts = [
        "update pos.sale set total = 1 where id = :s", "update pos.sale set number = 'X-1' where id = :s",
        "delete from pos.sale where id = :s", "update pos.sale_line set quantity = 9 where sale_id = :s",
        "update pos.sale_line set unit_price = 1 where sale_id = :s", "delete from pos.sale_line where sale_id = :s",
        "update pos.sale_payment set amount = 1 where sale_id = :s", "delete from pos.sale_payment where sale_id = :s",
        "update pos.sale_line set cost_amount = 1 where sale_id = :s",           # the cost was filled in at posting
    ]
    for sql in attempts:
        with pytest.raises(DBAPIError), system(shop) as s:
            s.execute(text(sql), {"s": sale["id"]})

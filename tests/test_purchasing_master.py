"""Suppliers, their bank details, purchase requests and orders: validation, approvals and who may do what."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.purchasing_helpers import PUR, make_purchasing_shop, new_order
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_purchasing_shop(client, registry, "Buy Master Co")


def decide(client, shop, doc_id, who, approve=True, note=None):  # type: ignore[no-untyped-def]
    pending = client.get("/api/v1/approvals/pending", headers=shop[who]).json()
    request = next((x for x in pending if x["doc_id"] == doc_id), None)
    assert request is not None, f"{who} sees nothing pending for {doc_id}"
    return client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop[who],
                       json={"approve": approve, "note": note})


def rule(client, shop, doc_type, min_amount="0"):  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": doc_type,
        "approver_role_id": shop["roles"]["Finance Manager"], "min_amount": min_amount})
    assert r.status_code == 201, r.text


# --------------------------------------------------------------------------- suppliers
def test_creating_and_changing_suppliers(client, shop) -> None:  # type: ignore[no-untyped-def]
    co, owner = str(shop["company_id"]), shop["owner"]
    body = {"company_id": co, "code": "kenol-1", "name": "  Kenol   Fuels ", "tax_id": "p000111222z",
            "phone": "0711000111", "email": "sales@kenol.test", "payment_terms_days": 14}
    r = client.post(f"{PUR}/suppliers", headers=owner, json=body)
    assert r.status_code == 201, r.text
    sup = r.json()
    assert sup["code"] == "KENOL-1" and sup["name"] == "Kenol Fuels" and sup["tax_id"] == "P000111222Z"
    assert client.post(f"{PUR}/suppliers", headers=owner, json=body).status_code == 409
    for bad in ({"code": "a b"}, {"code": ""}, {"name": " "}, {"tax_id": "!!"}, {"payment_terms_days": -1},
                {"payment_terms_days": 400}, {"company_id": str(uuid4())}):
        assert client.post(f"{PUR}/suppliers", headers=owner, json={**body, "code": "OK2", **bad}).status_code in (
            403, 404, 422), bad
    changed = client.patch(f"{PUR}/suppliers/{sup['id']}", headers=owner, json={
        "name": "Kenol Kobil", "payment_terms_days": 45, "status": "on_hold"}).json()
    assert changed["name"] == "Kenol Kobil" and changed["payment_terms_days"] == 45 and changed["status"] == "on_hold"
    assert client.patch(f"{PUR}/suppliers/{sup['id']}", headers=owner, json={"status": "gone"}).status_code == 422
    assert client.patch(f"{PUR}/suppliers/{sup['id']}", headers=owner, json={"tax_id": "!"}).status_code == 422
    listed = client.get(f"{PUR}/suppliers", headers=owner, params={"search": "kenol"}).json()
    assert [s["code"] for s in listed] == ["KENOL-1"]
    assert client.get(f"{PUR}/suppliers", headers=owner, params={"status": "on_hold"}).json()[0]["id"] == sup["id"]
    assert client.get(f"{PUR}/suppliers/{uuid4()}", headers=owner).status_code == 404
    assert client.get(f"{PUR}/suppliers", headers=owner, params={"search": "%"}).json() == []


def test_who_may_manage_and_see_suppliers(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    body = {"company_id": co, "code": "ROLE1", "name": "Role test"}
    for who in ("cashier", "storekeeper", "manager"):
        assert client.post(f"{PUR}/suppliers", headers=shop[who], json=body).status_code == 403, who
    assert client.post(f"{PUR}/suppliers", headers=shop["clerk"], json=body).status_code == 201     # an accountant may
    assert client.get(f"{PUR}/suppliers", headers=shop["manager"]).status_code == 200                # a buyer may look
    assert client.get(f"{PUR}/suppliers", headers=shop["storekeeper"]).status_code == 200
    assert client.get(f"{PUR}/suppliers", headers=shop["cashier"]).status_code == 403                # a cashier may not


# --------------------------------------------------------------------------- bank details
def test_bank_details_need_a_second_person_and_are_never_shown_in_full(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = shop["supplier"]
    path = f"{PUR}/suppliers/{sup}/bank-accounts"
    proposed = client.post(path, headers=shop["fm"], json={
        "method": "bank", "bank_name": "KCB", "account_name": "Total Supplies", "account_no": "0123 4567 8901"})
    assert proposed.status_code == 201, proposed.text
    bank = proposed.json()
    assert bank["status"] == "pending_confirmation" and bank["account_no_masked"] == "********8901"
    assert "0123" not in proposed.text and "ciphertext" not in proposed.text
    secret = one(shop, "select convert_from(account_no_ciphertext, 'UTF8') from purchasing.supplier_bank_account "
                       "where id = :i", i=bank["id"])
    assert "01234567" not in secret and secret != "012345678901"                  # stored encrypted
    # nothing changes yet; only one change at a time
    assert client.get(path, headers=shop["fm"]).json()[0]["status"] == "pending_confirmation"
    again = client.post(path, headers=shop["fm"], json={"method": "mobile_money", "account_no": "0712345678"})
    assert again.status_code == 409
    confirm = f"{PUR}/bank-accounts/{bank['id']}/confirm"
    body = {"confirmation_method": "phone_callback", "note": "Called the number on file"}
    assert client.post(confirm, headers=shop["fm"], json=body).status_code == 403          # not the proposer
    assert client.post(confirm, headers=shop["fm2"], json={"confirmation_method": "email"}).status_code == 422
    assert client.post(confirm, headers=shop["cashier"], json=body).status_code == 403
    done = client.post(confirm, headers=shop["fm2"], json=body)
    assert done.status_code == 200 and done.json()["status"] == "active"                  # no approval rule: active now
    assert done.json()["confirmed_by"] and done.json()["confirmation_method"] == "phone_callback"
    assert client.post(confirm, headers=shop["fm2"], json=body).status_code == 409         # already done
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'supplier.bank_changed'") == 1


def test_changing_details_again_keeps_history_and_can_need_approval(client, shop) -> None:  # type: ignore[no-untyped-def]
    sup = shop["supplier"]
    path = f"{PUR}/suppliers/{sup}/bank-accounts"
    rule(client, shop, "supplier_bank_change")
    new = client.post(path, headers=shop["fm"], json={"method": "mobile_money", "account_no": "0733445566"}).json()
    assert client.post(f"{PUR}/bank-accounts/{new['id']}/confirm", headers=shop["fm2"],
                       json={"confirmation_method": "in_person"}).json()["status"] == "pending_approval"
    active = [b for b in client.get(path, headers=shop["fm"]).json() if b["status"] == "active"]
    assert len(active) == 1 and active[0]["id"] != new["id"]                              # the old ones still apply
    assert decide(client, shop, new["id"], "fm").status_code == 200
    states = {b["id"]: b["status"] for b in client.get(path, headers=shop["fm"]).json()}
    assert states[new["id"]] == "active" and list(states.values()).count("superseded") == 1
    assert one(shop, "select count(*) from purchasing.supplier_bank_account where status = 'active'") == 1


def test_proposed_details_can_be_withdrawn_and_are_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    path = f"{PUR}/suppliers/{shop['supplier']}/bank-accounts"
    for bad in ({"method": "bank", "account_no": "12"}, {"method": "bank", "account_no": "123456789"},
                {"method": "mobile_money", "account_no": "12345"}, {"method": "card", "account_no": "123456"},
                {"method": "bank", "account_no": "ab;cd1234", "bank_name": "KCB"}):
        assert client.post(path, headers=shop["fm"], json=bad).status_code == 422, bad
    assert client.post(path, headers=shop["clerk"], json={"method": "mobile_money", "account_no": "0700111222"}
                       ).status_code == 403                                                # needs supplier.bank_edit
    mine = client.post(path, headers=shop["fm"], json={"method": "mobile_money", "account_no": "0700111222"}).json()
    assert client.post(f"{PUR}/bank-accounts/{mine['id']}/reject", headers=shop["cashier"]).status_code == 403
    r = client.post(f"{PUR}/bank-accounts/{mine['id']}/reject", headers=shop["fm2"])
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post(f"{PUR}/bank-accounts/{mine['id']}/confirm", headers=shop["fm2"],
                       json={"confirmation_method": "in_person"}).status_code == 409
    assert client.get(f"{PUR}/suppliers/{uuid4()}/bank-accounts", headers=shop["fm"]).status_code == 404


# --------------------------------------------------------------------------- requests and orders
def test_a_request_becomes_an_order(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    req = client.post(f"{PUR}/requests", headers=shop["buyer"], json={
        "company_id": co, "branch_id": str(shop["branch_id"]),
        "lines": [{"product_id": shop["cement"], "quantity": "20", "note": "Low stock"}]})
    assert req.status_code == 201 and req.json()["status"] == "draft" and req.json()["number"].startswith("PRQ-")
    rid = req.json()["id"]
    early = client.post(f"{PUR}/orders", headers=shop["owner"], json={
        "company_id": co, "supplier_id": shop["supplier"], "request_id": rid,
        "lines": [{"product_id": shop["cement"], "quantity": "20", "unit_cost": "50"}]})
    assert early.status_code == 422 and "approved request" in early.json()["message"]
    sub = client.post(f"{PUR}/requests/{rid}/submit", headers=shop["buyer"])
    assert sub.status_code == 200 and sub.json()["status"] == "approved"
    assert client.post(f"{PUR}/requests/{rid}/submit", headers=shop["buyer"]).status_code == 409
    order = new_order(client, shop, qty="20", request_id=rid)
    assert client.get(f"{PUR}/requests/{rid}", headers=shop["buyer"]).json()["status"] == "ordered"
    again = client.post(f"{PUR}/orders", headers=shop["owner"], json={
        "company_id": co, "supplier_id": shop["supplier"], "request_id": rid,
        "lines": [{"product_id": shop["cement"], "quantity": "20", "unit_cost": "50"}]})
    assert again.status_code == 422                                                     # one order per request
    assert order["status"] == "draft"
    for bad in ({"lines": []}, {"lines": [{"product_id": shop["cement"], "quantity": "0"}]},
                {"lines": [{"product_id": str(uuid4()), "quantity": "1"}]}):
        assert client.post(f"{PUR}/requests", headers=shop["buyer"], json={
            "company_id": co, "branch_id": str(shop["branch_id"]), **bad}).status_code == 422
    assert client.post(f"{PUR}/requests", headers=shop["cashier"], json={
        "company_id": co, "branch_id": str(shop["branch_id"]),
        "lines": [{"product_id": shop["cement"], "quantity": "1"}]}).status_code == 403


def test_order_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    co, owner = str(shop["company_id"]), shop["owner"]
    base = {"company_id": co, "supplier_id": shop["supplier"], "deliver_to_location_id": shop["main"],
            "lines": [{"product_id": shop["cement"], "quantity": "5", "unit_cost": "10"}]}
    ok = client.post(f"{PUR}/orders", headers=owner, json=base)
    assert ok.status_code == 201 and ok.json()["number"].startswith("PO-HQ-")
    cases = {
        "service product": {"lines": [{"product_id": shop["delivery"], "quantity": "1", "unit_cost": "10"}]},
        "unknown product": {"lines": [{"product_id": str(uuid4()), "quantity": "1", "unit_cost": "10"}]},
        "bad quantity": {"lines": [{"product_id": shop["cement"], "quantity": "0", "unit_cost": "10"}]},
        "negative cost": {"lines": [{"product_id": shop["cement"], "quantity": "1", "unit_cost": "-1"}]},
        "no lines": {"lines": []},
        "unknown supplier": {"supplier_id": str(uuid4())},
        "unknown location": {"deliver_to_location_id": str(uuid4())},
        "unknown tax": {"lines": [{"product_id": shop["cement"], "quantity": "1", "unit_cost": "10",
                                   "tax_code_id": str(uuid4())}]},
        "expected before order": {"order_date": "2026-10-10", "expected_date": "2026-10-01"},
    }
    for name, change in cases.items():
        assert client.post(f"{PUR}/orders", headers=owner, json={**base, **change}).status_code == 422, name
    client.patch(f"{PUR}/suppliers/{shop['supplier']}", headers=owner, json={"status": "on_hold"})
    held = client.post(f"{PUR}/orders", headers=owner, json=base)
    assert held.status_code == 422 and "on hold" in held.json()["message"]
    client.patch(f"{PUR}/suppliers/{shop['supplier']}", headers=owner, json={"status": "active"})
    assert client.post(f"{PUR}/orders", headers=shop["cashier"], json=base).status_code == 403
    juja = shop["user"]("jujabuyer", "Branch Manager", shop["juja"])
    assert client.post(f"{PUR}/orders", headers=juja, json=base).status_code == 403            # not their branch
    assert client.get(f"{PUR}/orders/{ok.json()['id']}", headers=juja).status_code == 404


def test_a_draft_order_can_be_changed_until_it_is_submitted(client, shop) -> None:  # type: ignore[no-untyped-def]
    order = new_order(client, shop, qty="2", cost="100")
    assert Dec(order["total"]) == 232
    r = client.put(f"{PUR}/orders/{order['id']}", headers=shop["owner"], json={
        "lines": [{"product_id": shop["cement"], "quantity": "5", "unit_cost": "100"},
                  {"product_id": shop["paint"], "quantity": "1", "unit_cost": "200", "tax_code_id": shop["tax"]}],
        "expected_date": "2026-12-01"})
    assert r.status_code == 200, r.text
    assert Dec(r.json()["subtotal"]) == 700 and Dec(r.json()["tax_total"]) == 112 and len(r.json()["lines"]) == 2
    assert client.put(f"{PUR}/orders/{order['id']}", headers=shop["owner"], json={"expected_date": "2020-01-01"}
                      ).status_code == 422
    submitted = client.post(f"{PUR}/orders/{order['id']}/submit", headers=shop["owner"])
    assert submitted.json()["status"] == "approved"
    assert client.put(f"{PUR}/orders/{order['id']}", headers=shop["owner"], json={"expected_date": "2026-12-02"}
                      ).status_code == 409
    assert client.post(f"{PUR}/orders/{order['id']}/submit", headers=shop["owner"]).status_code == 409
    assert client.post(f"{PUR}/orders/{order['id']}/send", headers=shop["owner"]).json()["status"] == "sent"
    assert client.post(f"{PUR}/orders/{order['id']}/send", headers=shop["owner"]).status_code == 409
    assert client.post(f"{PUR}/orders/{order['id']}/close", headers=shop["owner"]).status_code == 409
    cancelled = client.post(f"{PUR}/orders/{order['id']}/cancel", headers=shop["owner"])
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(f"{PUR}/orders/{order['id']}/cancel", headers=shop["owner"]).status_code == 409
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'po.approved' and "
                     "aggregate_id = :i", i=order["id"]) == 1


def test_a_large_order_waits_for_an_approver(client, shop) -> None:  # type: ignore[no-untyped-def]
    rule(client, shop, "purchase_order", "10000")
    small = client.post(f"{PUR}/orders/{new_order(client, shop, qty='1', cost='100')['id']}/submit",
                        headers=shop["buyer"])
    assert small.json()["status"] == "approved"
    big = new_order(client, shop, qty="500", cost="100", who="buyer")
    waiting = client.post(f"{PUR}/orders/{big['id']}/submit", headers=shop["buyer"])
    assert waiting.json()["status"] == "pending_approval"
    assert decide(client, shop, big["id"], "fm").status_code == 200
    assert client.get(f"{PUR}/orders/{big['id']}", headers=shop["buyer"]).json()["status"] == "approved"
    other = new_order(client, shop, qty="500", cost="100", who="buyer")
    client.post(f"{PUR}/orders/{other['id']}/submit", headers=shop["buyer"])
    assert decide(client, shop, other["id"], "fm", approve=False, note="Too much").status_code == 200
    assert client.get(f"{PUR}/orders/{other['id']}", headers=shop["buyer"]).json()["status"] == "draft"
    third = new_order(client, shop, qty="500", cost="100", who="buyer")
    client.post(f"{PUR}/orders/{third['id']}/submit", headers=shop["buyer"])
    pending = client.get("/api/v1/approvals/pending", headers=shop["buyer"]).json()
    assert not any(x["doc_id"] == third["id"] for x in pending)                           # not an approver
    with system(shop) as s:
        s.execute(text("select 1"))
    assert one(shop, "select count(*) from purchasing.purchase_order where status = 'pending_approval'") >= 1

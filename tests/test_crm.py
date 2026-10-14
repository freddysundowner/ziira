"""Customers, credit limits that need approval, leads and follow-ups."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.crm_helpers import CRM, make_crm_shop, new_customer
from tests.payments_helpers import one


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_crm_shop(client, registry, "Crm Co")


# --------------------------------------------------------------------------- customers
def test_a_customer_is_created_with_a_code_and_no_credit(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = new_customer(client, shop, name="  Mama  Mboga ", phone="0722 111 222", email="Mama@Mboga.ke",
                     tax_id="a123456789z", customer_group="Retail", kind="individual", payment_terms_days=14)
    assert c["code"].startswith("CUS-") and c["name"] == "Mama Mboga" and c["phone"] == "254722111222"
    assert c["email"] == "mama@mboga.ke" and c["tax_id"] == "A123456789Z" and c["status"] == "active"
    assert Dec(c["credit_limit"]) == 0 and c["payment_terms_days"] == 14 and c["owner_user_id"]
    second = new_customer(client, shop, name="Another")
    assert second["code"] != c["code"]
    history = client.get(f"{CRM}/customers/{c['id']}/credit", headers=shop["owner"]).json()
    assert [(h["status"], Dec(h["credit_limit"])) for h in history] == [("active", Dec(0))]
    chosen = new_customer(client, shop, name="Coded", code="kiosk-1")
    assert chosen["code"] == "KIOSK-1"
    assert client.post(f"{CRM}/customers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": "Dup", "code": "KIOSK-1"}).status_code == 409


def test_customer_validation_and_permissions(client, shop) -> None:  # type: ignore[no-untyped-def]
    base = {"company_id": str(shop["company_id"]), "name": "Valid"}
    for bad in ({"name": " "}, {"phone": "123"}, {"email": "nope"}, {"tax_id": "X1"}, {"payment_terms_days": 400},
                {"kind": "alien"}, {"code": "bad code"}, {"owner_user_id": str(uuid4())},
                {"company_id": str(uuid4())}):
        assert client.post(f"{CRM}/customers", headers=shop["owner"], json={**base, **bad}).status_code in (
            403, 404, 422), bad
    assert client.post(f"{CRM}/customers", headers=shop["cashier"], json=base).status_code == 403
    assert client.post(f"{CRM}/customers", headers=shop["storekeeper"], json=base).status_code == 403
    assert client.post(f"{CRM}/customers", headers=shop["rep"], json=base).status_code == 201     # a branch-level rep
    assert client.get(f"{CRM}/customers", headers=shop["cashier"]).status_code == 200            # may look one up
    assert client.get(f"{CRM}/customers", headers=shop["storekeeper"]).status_code == 403
    assert client.get(f"{CRM}/customers/{uuid4()}", headers=shop["owner"]).status_code == 404


def test_finding_and_changing_customers(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = new_customer(client, shop, name="Findable Ltd", phone="0733000111", customer_group="Wholesale")
    by_name = client.get(f"{CRM}/customers", headers=shop["owner"], params={"search": "findable"}).json()
    by_phone = client.get(f"{CRM}/customers", headers=shop["owner"], params={"search": "733000111"}).json()
    by_group = client.get(f"{CRM}/customers", headers=shop["owner"], params={"group": "Wholesale"}).json()
    assert [x["id"] for x in by_name] == [x["id"] for x in by_phone] == [c["id"]] and c["id"] in {x["id"] for x in by_group}
    assert client.get(f"{CRM}/customers", headers=shop["owner"], params={"search": "%"}).json() == []
    r = client.patch(f"{CRM}/customers/{c['id']}", headers=shop["rep"], json={
        "name": "Findable Limited", "status": "on_hold", "phone": "0744555666"})
    assert r.status_code == 200 and r.json()["status"] == "on_hold" and r.json()["phone"] == "254744555666"
    assert client.patch(f"{CRM}/customers/{c['id']}", headers=shop["owner"], json={"status": "bogus"}
                        ).status_code == 422
    assert client.patch(f"{CRM}/customers/{c['id']}", headers=shop["cashier"], json={"name": "X"}).status_code == 403
    on_hold = client.get(f"{CRM}/customers", headers=shop["owner"], params={"status": "on_hold"}).json()
    assert c["id"] in {x["id"] for x in on_hold}


def test_contacts_of_a_business(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = new_customer(client, shop, name="Contacts Ltd")
    path = f"{CRM}/customers/{c['id']}/contacts"
    made = client.post(path, headers=shop["owner"], json={"name": "Peter Otieno", "phone": "0700123456",
                                                           "role": "Accountant"})
    assert made.status_code == 201 and made.json()["phone"] == "254700123456"
    assert client.post(path, headers=shop["owner"], json={"name": "x", "phone": "1"}).status_code == 422
    assert client.post(path, headers=shop["cashier"], json={"name": "No"}).status_code == 403
    assert [x["name"] for x in client.get(path, headers=shop["cashier"]).json()] == ["Peter Otieno"]
    assert client.delete(f"{path}/{uuid4()}", headers=shop["owner"]).status_code == 404
    assert client.delete(f"{path}/{made.json()['id']}", headers=shop["owner"]).status_code == 204
    assert client.get(path, headers=shop["owner"]).json() == []


# --------------------------------------------------------------------------- credit
def test_lowering_credit_or_changing_terms_takes_effect_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = new_customer(client, shop, name="Credit Lowering")
    up = client.post(f"{CRM}/customers/{c['id']}/credit", headers=shop["fm"], json={
        "credit_limit": "50000", "payment_terms_days": 30, "reason": "Good references"})
    assert up.status_code == 201 and up.json()["status"] == "active"
    down = client.post(f"{CRM}/customers/{c['id']}/credit", headers=shop["rep"], json={
        "credit_limit": "20000", "payment_terms_days": 14, "reason": "Late payments"})
    assert down.status_code == 201 and down.json()["status"] == "active"
    now = client.get(f"{CRM}/customers/{c['id']}", headers=shop["owner"]).json()
    assert Dec(now["credit_limit"]) == 20000 and now["payment_terms_days"] == 14
    terms = client.post(f"{CRM}/customers/{c['id']}/credit", headers=shop["rep"], json={
        "credit_limit": "20000", "payment_terms_days": 7, "reason": "Shorter terms"})
    assert terms.status_code == 201
    history = client.get(f"{CRM}/customers/{c['id']}/credit", headers=shop["owner"]).json()
    assert [h["status"] for h in history].count("active") == 1 and len(history) == 4
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'customer.credit_limit_changed' "
                     "and aggregate_id = :c", c=c["id"]) == 3


def test_a_salesperson_cannot_raise_a_limit_without_an_approver(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = new_customer(client, shop, name="Credit Raise")
    path = f"{CRM}/customers/{c['id']}/credit"
    body = {"credit_limit": "10000", "payment_terms_days": 30, "reason": "Asked nicely"}
    r = client.post(path, headers=shop["rep"], json=body)
    assert r.status_code == 403 and "finance manager" in r.json()["message"]
    assert Dec(client.get(f"{CRM}/customers/{c['id']}", headers=shop["owner"]).json()["credit_limit"]) == 0
    assert client.post(path, headers=shop["fm"], json=body).status_code == 201             # holds credit.approve


def test_a_raise_can_wait_for_an_approval_rule(client, shop) -> None:  # type: ignore[no-untyped-def]
    rule = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "credit_limit_change",
        "approver_role_id": shop["roles"]["Finance Manager"], "min_amount": "0"})
    assert rule.status_code == 201, rule.text
    c = new_customer(client, shop, name="Credit Wait")
    path = f"{CRM}/customers/{c['id']}/credit"
    waiting = client.post(path, headers=shop["rep"], json={"credit_limit": "75000", "payment_terms_days": 30,
                                                            "reason": "Big contract"})
    assert waiting.status_code == 201 and waiting.json()["status"] == "pending_approval"
    assert Dec(client.get(f"{CRM}/customers/{c['id']}", headers=shop["owner"]).json()["credit_limit"]) == 0
    assert client.post(path, headers=shop["rep"], json={"credit_limit": "80000", "payment_terms_days": 30,
                                                         "reason": "Again"}).status_code == 409
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm"]).json()
    request = next(x for x in pending if x["doc_id"] == waiting.json()["id"])
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm"],
                       json={"approve": True}).status_code == 200
    now = client.get(f"{CRM}/customers/{c['id']}", headers=shop["owner"]).json()
    assert Dec(now["credit_limit"]) == 75000 and now["payment_terms_days"] == 30
    # a rejected raise changes nothing
    second = client.post(path, headers=shop["rep"], json={"credit_limit": "200000", "payment_terms_days": 30,
                                                          "reason": "More"}).json()
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm"]).json()
    request = next(x for x in pending if x["doc_id"] == second["id"])
    client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm"],
                json={"approve": False, "note": "Too risky"})
    assert Dec(client.get(f"{CRM}/customers/{c['id']}", headers=shop["owner"]).json()["credit_limit"]) == 75000
    statuses = [h["status"] for h in client.get(path, headers=shop["owner"]).json()]
    assert statuses.count("rejected") == 1 and statuses.count("active") == 1


def test_credit_change_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = new_customer(client, shop, name="Credit Bad")
    path = f"{CRM}/customers/{c['id']}/credit"
    for bad in ({"credit_limit": "-1"}, {"credit_limit": "1.005"}, {"credit_limit": "99999999999"},
                {"payment_terms_days": -1}, {"payment_terms_days": 400}, {"reason": " "}, {"reason": ""}):
        body = {"credit_limit": "100", "payment_terms_days": 7, "reason": "ok", **bad}
        assert client.post(path, headers=shop["fm"], json=body).status_code == 422, bad
    same = client.post(path, headers=shop["fm"], json={"credit_limit": "0", "payment_terms_days": 0, "reason": "x"})
    assert same.status_code == 422 and "already" in same.json()["message"]
    assert client.post(path, headers=shop["cashier"], json={"credit_limit": "0", "payment_terms_days": 1,
                                                             "reason": "x"}).status_code == 403


# --------------------------------------------------------------------------- leads
def test_a_lead_becomes_a_customer(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    src = client.post(f"{CRM}/lead-sources", headers=shop["rep"], json={"name": "Referral"})
    assert src.status_code == 201
    assert client.post(f"{CRM}/lead-sources", headers=shop["rep"], json={"name": "referral"}).status_code == 409
    lead = client.post(f"{CRM}/leads", headers=shop["rep"], json={
        "company_id": co, "name": "John Kamau", "business_name": "Kamau Builders", "phone": "0711222333",
        "source_id": src.json()["id"]})
    assert lead.status_code == 201 and lead.json()["status"] == "new" and lead.json()["owner_user_id"]
    lid = lead.json()["id"]
    assert client.post(f"{CRM}/leads/{lid}/convert", headers=shop["rep"], json={}).status_code == 422     # still new
    assert client.post(f"{CRM}/leads/{lid}/status", headers=shop["rep"], json={"status": "contacted"}
                       ).status_code == 200
    assert client.post(f"{CRM}/leads/{lid}/status", headers=shop["rep"], json={"status": "new"}).status_code == 422
    done = client.post(f"{CRM}/leads/{lid}/convert", headers=shop["rep"], json={"customer_group": "Contractors"})
    assert done.status_code == 200, done.text
    customer = done.json()["customer"]
    assert done.json()["lead"]["status"] == "converted" and done.json()["lead"]["converted_customer_id"] == customer["id"]
    assert customer["name"] == "Kamau Builders" and customer["kind"] == "business" and customer["phone"] == "254711222333"
    contacts = client.get(f"{CRM}/customers/{customer['id']}/contacts", headers=shop["rep"]).json()
    assert [c["name"] for c in contacts] == ["John Kamau"]
    assert client.post(f"{CRM}/leads/{lid}/convert", headers=shop["rep"], json={}).status_code == 409
    assert client.patch(f"{CRM}/leads/{lid}", headers=shop["rep"], json={"name": "X"}).status_code == 409
    assert one(shop, "select count(*) from kernel.event_outbox where event_type in ('lead.created', 'lead.converted')"
               ) >= 2


def test_lead_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    base = {"company_id": co, "name": "Prospect", "phone": "0700000001"}
    assert client.post(f"{CRM}/leads", headers=shop["rep"], json={"company_id": co, "name": "No contact"}
                       ).status_code == 422
    for bad in ({"source_id": str(uuid4())}, {"owner_user_id": str(uuid4())}, {"customer_kind": "alien"},
                {"phone": "12"}, {"name": " "}):
        assert client.post(f"{CRM}/leads", headers=shop["rep"], json={**base, **bad}).status_code == 422, bad
    assert client.post(f"{CRM}/leads", headers=shop["cashier"], json=base).status_code == 403
    lead = client.post(f"{CRM}/leads", headers=shop["rep"], json=base).json()
    path = f"{CRM}/leads/{lead['id']}/status"
    assert client.post(path, headers=shop["rep"], json={"status": "lost"}).status_code == 422          # why?
    lost = client.post(path, headers=shop["rep"], json={"status": "lost", "lost_reason": "Went to a competitor"})
    assert lost.status_code == 200 and lost.json()["status"] == "lost"
    assert client.post(f"{CRM}/leads/{lead['id']}/convert", headers=shop["rep"], json={}).status_code == 422
    assert client.post(path, headers=shop["rep"], json={"status": "contacted"}).json()["status"] == "contacted"
    assert client.post(path, headers=shop["rep"], json={"status": "converted"}).status_code == 422
    listed = client.get(f"{CRM}/leads", headers=shop["rep"], params={"status": "contacted", "search": "prospect"}).json()
    assert lead["id"] in {x["id"] for x in listed}
    assert client.get(f"{CRM}/leads/{uuid4()}", headers=shop["rep"]).status_code == 404


# --------------------------------------------------------------------------- follow-ups
def test_follow_ups(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = new_customer(client, shop, name="Follow Up Ltd")
    due = "2026-10-20T09:00:00+03:00"
    made = client.post(f"{CRM}/activities", headers=shop["rep"], json={
        "related_type": "customer", "related_id": c["id"], "kind": "call", "due_at": due, "note": "Ask about the order"})
    assert made.status_code == 201 and made.json()["done_at"] is None
    aid = made.json()["id"]
    mine = client.get(f"{CRM}/activities", headers=shop["rep"], params={"mine": True, "open_only": True}).json()
    assert aid in {a["id"] for a in mine}
    about = client.get(f"{CRM}/activities", headers=shop["owner"], params={
        "related_type": "customer", "related_id": c["id"]}).json()
    assert [a["id"] for a in about] == [aid]
    assert client.get(f"{CRM}/activities", headers=shop["rep"]).status_code == 422                # name a record or mine
    for bad in ({"kind": "email"}, {"related_type": "supplier"}, {"related_id": str(uuid4())},
                {"owner_user_id": str(uuid4())}):
        body = {"related_type": "customer", "related_id": c["id"], "kind": "call", **bad}
        assert client.post(f"{CRM}/activities", headers=shop["rep"], json=body).status_code in (404, 422), bad
    assert client.post(f"{CRM}/activities", headers=shop["cashier"], json={
        "related_type": "customer", "related_id": c["id"], "kind": "call"}).status_code == 403
    assert client.post(f"{CRM}/activities/{aid}/done", headers=shop["cashier"], json={}).status_code == 403
    done = client.post(f"{CRM}/activities/{aid}/done", headers=shop["rep"], json={"note": "Will order Friday"})
    assert done.status_code == 200 and done.json()["done_at"] and "Friday" in done.json()["note"]
    assert client.post(f"{CRM}/activities/{aid}/done", headers=shop["rep"], json={}).status_code == 409
    assert client.get(f"{CRM}/activities", headers=shop["rep"], params={"mine": True, "open_only": True}
                      ).json() == [] or aid not in {a["id"] for a in client.get(
        f"{CRM}/activities", headers=shop["rep"], params={"mine": True, "open_only": True}).json()}

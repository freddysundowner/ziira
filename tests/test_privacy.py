"""Data protection: data subject requests (access, correction, erasure) and retention, through the API.

One business holds a person ("Mama Mboga", phone 0712345678) in many units: a CRM customer with a contact and a lead, sales
and an invoice and a receipt in POS, a mobile money payment from her number, a supplier record, a message sent to her.
The tests find her, export exactly what is held, erase her (with a second person's approval) and check that the books
did not move, and then cover employees whose payroll must be kept, other tenants, permissions, audit and retention.
"""

from datetime import date, timedelta
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from tests.finance_helpers import entries
from tests.payments_helpers import c2b, eat_now, fresh_ref, post_c2b
from tests.people_helpers import PEOPLE, new_employee
from tests.pos_helpers import POS, credit_customer, credit_sale, make_sales_shop, sell
from tests.stock_helpers import system

PRIV = "/api/v1/privacy"
PHONE = "0712345678"
DIGITS = "254712345678"


def settings(client, shop, **changes):  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"], json=changes)
    assert r.status_code == 200, r.text
    return r.json()


def new_request(client, shop, subject=PHONE, kind="access", who="owner", **kw):  # type: ignore[no-untyped-def]
    r = client.post(f"{PRIV}/requests", headers=shop[who], json={
        "company_id": str(shop["company_id"]), "request_type": kind, "subject": subject, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def searched(client, shop, subject=PHONE, kind="access", who="owner"):  # type: ignore[no-untyped-def]
    req = new_request(client, shop, subject, kind, who)
    r = client.post(f"{PRIV}/requests/{req['id']}/search", headers=shop[who])
    assert r.status_code == 200, r.text
    return r.json()


def kinds(request_json):  # type: ignore[no-untyped-def]
    return sorted((f["source"], f["kind"]) for f in request_json["found"])


def rows(shop, sql, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text(sql), params).all()


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Privacy Co", stock="500")
    registry.enable(s["tenant_id"], "people")
    registry.enable(s["tenant_id"], "purchasing")
    co = str(s["company_id"])
    s["company"] = co
    s["hr"] = s["user"]("hr", "HR", None)
    s["owner2"] = s["user"]("owner2", "Owner", None)
    # the person: a customer with a contact and a lead on the same number, follow-ups, sales, an invoice, a receipt
    mama = credit_customer(client, s, name="Mama Mboga", limit="5000", terms=14, kind="individual", phone=PHONE,
                           email="mama@example.test", tax_id="A001234567B")
    s["mama"] = mama
    s["bystander"] = credit_customer(client, s, name="Other Person", limit="0", terms=0, phone="0799999999",
                                     email="other@example.test")
    assert client.post(f"/api/v1/crm/customers/{mama['id']}/contacts", headers=s["owner"], json={
        "name": "Peter Mboga", "phone": PHONE, "role": "son"}).status_code == 201
    lead = client.post("/api/v1/crm/leads", headers=s["owner"], json={
        "company_id": co, "name": "Mama M", "phone": PHONE, "customer_kind": "individual"})
    assert lead.status_code == 201, lead.text
    s["lead"] = lead.json()["id"]
    for related, rid in (("customer", mama["id"]), ("lead", s["lead"])):
        a = client.post("/api/v1/crm/activities", headers=s["owner"], json={
            "related_type": related, "related_id": rid, "kind": "call", "note": "Her mother Susan lives in Karen"})
        assert a.status_code == 201, a.text
    s["credit_sale"] = credit_sale(client, s, mama).json()
    s["cash_sale"] = sell(client, s, customer_id=mama["id"]).json()
    inv = client.post(f"{POS}/invoices", headers=s["owner"], json={
        "customer_id": mama["id"], "location_id": s["main"], "notes": "Deliver to the blue gate",
        "lines": [{"product_id": s["cement"], "quantity": "1"}]})
    assert inv.status_code == 201, inv.text
    receipt = client.post(f"{POS}/receipts", headers=s["owner"], json={
        "customer_id": mama["id"], "amount": "50.00", "method": "cash", "branch_id": str(s["branch_id"])})
    assert receipt.status_code == 201, receipt.text
    # a mobile money payment from her number (the provider reports her name), and a message to her
    assert post_c2b(client, s, c2b(fresh_ref(), phone=DIGITS, when=eat_now())).status_code == 200
    from ziira.sdk import send_notification

    with system(s) as ses:
        send_notification(ses, company_id=s["company_id"], channel="sms", recipient=PHONE, body="Your order is ready")
        send_notification(ses, company_id=s["company_id"], channel="email", recipient="mama@example.test",
                          subject="Receipt", body="Thanks Mama")
    # a supplier on the same number (an individual) with bank details
    sup = client.post("/api/v1/purchasing/suppliers", headers=s["owner"], json={
        "company_id": co, "code": "MAMA01", "name": "Mama Mboga Vegetables", "phone": PHONE, "tax_id": "P0987654321Z"})
    assert sup.status_code == 201, sup.text
    s["supplier"] = sup.json()["id"]
    assert client.post(f"/api/v1/purchasing/suppliers/{s['supplier']}/bank-accounts", headers=s["owner"], json={
        "method": "bank", "account_no": "0011223344", "bank_name": "First Bank", "account_name": "Mama Mboga"
    }).status_code == 201
    return s


# --------------------------------------------------------------------------- permission and settings
def test_only_privacy_managers_can_use_the_endpoints(client, shop) -> None:  # type: ignore[no-untyped-def]
    for who in ("cashier", "manager", "fm", "hr", "boss"):
        body = {"company_id": str(shop["company_id"]), "request_type": "access", "subject": PHONE}
        assert client.post(f"{PRIV}/requests", headers=shop[who], json=body).status_code == 403, who
        assert client.get(f"{PRIV}/requests", headers=shop[who]).status_code == 403, who
        assert client.get(f"{PRIV}/retention", headers=shop[who],
                          params={"company_id": str(shop["company_id"])}).status_code == 403, who
    assert client.get(f"{PRIV}/requests").status_code == 401
    perms = client.get("/api/v1/roles", headers=shop["owner"]).json()
    holders = [r["name"] for r in perms if "privacy.manage" in r["permissions"]]
    assert holders == ["Owner"]                                                  # nobody else has it by default


def test_defaults_and_validation_of_the_privacy_settings(client, shop) -> None:  # type: ignore[no-untyped-def]
    now = client.get(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"]).json()
    assert now["privacy_response_days"] == 30 and now["privacy_erasure_needs_approval"] is True
    assert now["retention_notifications_days"] == 0 and now["retention_audit_years"] == 7
    assert now["retention_employee_records_years"] == 7 and now["retention_inactive_customers_years"] == 0
    for bad in ({"privacy_response_days": 0}, {"retention_audit_years": 0}, {"retention_notifications_days": -1},
                {"retention_employee_records_years": 101}, {"privacy_erasure_needs_approval": "perhaps"}):
        assert client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                            json=bad).status_code == 422, bad


# --------------------------------------------------------------------------- creating requests
def test_a_request_gets_a_number_and_a_due_date_from_the_setting(client, shop) -> None:  # type: ignore[no-untyped-def]
    first = new_request(client, shop, "mama@example.test")
    assert first["number"].startswith("DSR-") and first["status"] == "open"
    assert first["due_date"] == str(date.today() + timedelta(days=30)) and first["overdue"] is False
    assert first["subject_masked"] == "m***@example.test"
    try:
        settings(client, shop, privacy_response_days=10)
        second = new_request(client, shop, "mama@example.test", received_on=str(date.today() - timedelta(days=3)))
        assert second["due_date"] == str(date.today() + timedelta(days=7))
    finally:
        settings(client, shop, privacy_response_days=30)
    assert second["number"] != first["number"]


def test_bad_requests_are_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    base = {"company_id": str(shop["company_id"]), "request_type": "access", "subject": PHONE}
    for change in ({"request_type": "delete"}, {"subject": "ab"}, {"subject": "a@b@c"}, {"subject": "12"},
                   {"received_on": str(date.today() + timedelta(days=2))}, {"unknown": 1}, {"notes": "x" * 3000}):
        assert client.post(f"{PRIV}/requests", headers=shop["owner"], json={**base, **change}).status_code == 422, change
    assert client.post(f"{PRIV}/requests", headers=shop["owner"],
                       json={**base, "company_id": str(uuid4())}).status_code in (403, 422)
    assert client.get(f"{PRIV}/requests/{uuid4()}", headers=shop["owner"]).status_code == 404
    listed = client.get(f"{PRIV}/requests", headers=shop["owner"], params={"status": "open"}).json()
    assert listed and all(r["status"] == "open" for r in listed)
    assert client.get(f"{PRIV}/requests", headers=shop["owner"], params={"status": "bogus"}).status_code == 422


# --------------------------------------------------------------------------- access: find and export
def test_a_phone_number_finds_the_person_in_every_unit(client, shop) -> None:  # type: ignore[no-untyped-def]
    found = searched(client, shop)
    assert found["status"] == "in_progress"
    assert kinds(found) == [
        ("crm", "contact"), ("crm", "customer"), ("crm", "lead"), ("kernel.notifications", "message_history"),
        ("payments", "mobile_money_payer"), ("payments", "party_payments"), ("pos", "customer_documents"),
        ("purchasing", "supplier")]
    assert {f["match"] for f in found["found"]} == {"exact"}
    labels = {f["source"] + "/" + f["kind"]: f["label"] for f in found["found"]}
    assert labels["crm/customer"] == "Mama Mboga" and "5 " not in labels["pos/customer_documents"][:2]
    assert "unpaid" in labels["pos/customer_documents"]
    assert all("ref" not in f for f in found["found"])                               # private pointers stay private
    assert not any(f["label"].startswith("Other Person") for f in found["found"])    # the bystander is not swept in


def test_email_tax_id_and_name_searches(client, shop) -> None:  # type: ignore[no-untyped-def]
    by_email = searched(client, shop, "MAMA@example.test")
    assert ("crm", "customer") in kinds(by_email) and ("kernel.notifications", "message_history") in kinds(by_email)
    assert ("purchasing", "supplier") not in kinds(by_email)
    by_tax = searched(client, shop, "a001234567b")
    assert kinds(by_tax) == [("crm", "customer"), ("payments", "party_payments"), ("pos", "customer_documents")]
    assert searched(client, shop, "A00-1234567-B")["found"][0]["match"] == "exact"
    by_name = searched(client, shop, "mboga")
    assert {f["match"] for f in by_name["found"]} == {"possible"}
    assert ("crm", "customer") in kinds(by_name) and ("purchasing", "supplier") in kinds(by_name)
    assert ("crm", "contact") in kinds(by_name)
    nothing = searched(client, shop, "0700000099")
    assert nothing["found"] == [] and nothing["status"] == "in_progress"


def test_the_export_holds_exactly_what_is_stored(client, shop) -> None:  # type: ignore[no-untyped-def]
    req = searched(client, shop)
    r = client.post(f"{PRIV}/requests/{req['id']}/export", headers=shop["owner"])
    assert r.status_code == 200, r.text
    bundle = r.json()
    assert bundle["request"]["number"] == req["number"] and bundle["subject"] == PHONE
    by = {(x["source"], x["kind"]): x for x in bundle["records"]}
    assert set(by) == set(map(tuple, kinds(req)))
    customer = by[("crm", "customer")]["data"]
    assert set(customer["customer"]) == {"id", "created_at", "updated_at", "company_id", "code", "name", "kind", "phone",
                                         "email", "tax_id", "customer_group", "credit_limit", "payment_terms_days",
                                         "status"}
    assert customer["customer"]["name"] == "Mama Mboga" and customer["customer"]["phone"] == DIGITS
    assert customer["customer"]["email"] == "mama@example.test" and customer["customer"]["tax_id"] == "A001234567B"
    assert [c["name"] for c in customer["contacts"]] == ["Peter Mboga"]
    assert [a["note"] for a in customer["follow_ups"]] == ["Her mother Susan lives in Karen"]
    assert Dec(customer["credit_history"][-1]["credit_limit"]) == 5000
    assert "owner_user_id" not in customer["customer"] and "tenant_id" not in customer["customer"]
    docs = by[("pos", "customer_documents")]["data"]
    assert len(docs["sales"]) == 2 and len(docs["invoices"]) == 2 and len(docs["receipts"]) == 1
    assert docs["invoices"][0]["notes"] == "Deliver to the blue gate" and Dec(docs["receipts"][0]["amount"]) == 50
    assert {s["number"] for s in docs["sales"]} == {shop["credit_sale"]["number"], shop["cash_sale"]["number"]}
    payer = by[("payments", "mobile_money_payer")]["data"]
    assert len(payer["transactions"]) == 1 and payer["transactions"][0]["name"] == "Jane Wanjiru"
    assert payer["transactions"][0]["phone"] == "2547****678"
    assert "phone_hash" not in str(payer)
    messages = by[("kernel.notifications", "message_history")]["data"]["messages"]
    assert [m["text"] for m in messages] == ["Your order is ready"] and messages[0]["to"] == DIGITS
    supplier = by[("purchasing", "supplier")]["data"]
    assert supplier["supplier"]["name"] == "Mama Mboga Vegetables"
    assert supplier["payment_details"][0]["account_name"] == "Mama Mboga"
    assert supplier["payment_details"][0]["account_no_masked"].endswith("3344")
    assert "account_no_ciphertext" not in str(supplier) and "0011223344" not in str(supplier)
    # exporting is itself recorded, as a data export, with no personal data in the entry
    entry = rows(shop, "select action, entity_type, changes from kernel.audit_log where action = 'data_export' "
                       "and entity_id = :i", i=req["id"])
    assert len(entry) == 1 and entry[0].entity_type == "kernel.privacy_request"
    assert entry[0].changes["data_export"] is True and entry[0].changes["records"] == 8
    assert entry[0].changes["sources"]["crm"] == 3
    assert "Mama" not in str(entry[0].changes) and DIGITS not in str(entry[0].changes) and PHONE not in str(entry[0].changes)
    again = client.post(f"{PRIV}/requests/{req['id']}/export", headers=shop["owner"])
    assert again.status_code == 200
    assert len(rows(shop, "select 1 from kernel.audit_log where action = 'data_export' and entity_id = :i",
                    i=req["id"])) == 2                                                    # every export is its own entry
    assert len(client.get(f"{PRIV}/requests/{req['id']}", headers=shop["owner"]).json()["outcome"]["exports"]) == 2


def test_a_possible_match_is_exported_only_when_chosen(client, shop) -> None:  # type: ignore[no-untyped-def]
    req = searched(client, shop, "Mama Mboga")
    path = f"{PRIV}/requests/{req['id']}/export"
    refused = client.post(path, headers=shop["owner"])
    assert refused.status_code == 422 and "No records selected" in refused.json()["message"]
    customer = next(f for f in req["found"] if f["source"] == "crm" and f["kind"] == "customer")
    assert customer["match"] == "possible"
    ok = client.post(path, headers=shop["owner"], json={"record_ids": [customer["record_id"]]})
    assert ok.status_code == 200 and [x["source"] for x in ok.json()["records"]] == ["crm"]
    stranger = client.post(path, headers=shop["owner"], json={"record_ids": [str(uuid4())]})
    assert stranger.status_code == 422


def test_a_request_can_be_closed_by_hand(client, shop) -> None:  # type: ignore[no-untyped-def]
    req = new_request(client, shop, "mama@example.test", kind="correction")
    path = f"{PRIV}/requests/{req['id']}/close"
    assert client.post(path, headers=shop["owner"], json={"outcome": "completed", "note": " "}).status_code == 422
    done = client.post(path, headers=shop["owner"], json={"outcome": "completed", "note": "Email corrected by phone"})
    assert done.status_code == 200 and done.json()["status"] == "completed" and done.json()["completed_at"]
    assert client.post(path, headers=shop["owner"], json={"outcome": "refused", "note": "x"}).status_code == 409
    assert client.post(f"{PRIV}/requests/{req['id']}/search", headers=shop["owner"]).status_code == 409
    assert rows(shop, "select 1 from kernel.audit_log where action = 'completed' and entity_id = :i", i=req["id"])


# --------------------------------------------------------------------------- erasure
def books(shop):  # type: ignore[no-untyped-def]
    """The figures that must not move: sale and invoice numbers and totals, and the ledger."""
    sales = rows(shop, "select number, total, tax_total, status, customer_id from pos.sale order by number")
    invoices = rows(shop, "select number, total, amount_paid, status from pos.sales_invoice order by number")
    receipts = rows(shop, "select number, amount, status from pos.customer_receipt order by number")
    ledger = [(e[0], e[1], e[2]) for e in entries(shop)]
    return sales, invoices, receipts, ledger


def test_erasure_needs_the_right_confirmation_reason_and_an_approval_rule(client, shop) -> None:  # type: ignore[no-untyped-def]
    req = searched(client, shop, kind="erasure")
    path = f"{PRIV}/requests/{req['id']}/erase"
    body = {"confirm_subject": PHONE, "reason": "Customer asked us to erase her data"}
    assert client.post(path, headers=shop["owner"], json={**body, "confirm_subject": "0700000000"}).status_code == 422
    assert client.post(path, headers=shop["owner"], json={**body, "reason": "no"}).status_code == 422
    assert client.post(path, headers=shop["cashier"], json=body).status_code == 403
    no_rule = client.post(path, headers=shop["owner"], json=body)
    assert no_rule.status_code == 422 and "privacy.erasure" in no_rule.json()["message"]
    access = searched(client, shop)                                                     # not an erasure request
    wrong_type = client.post(f"{PRIV}/requests/{access['id']}/erase", headers=shop["owner"], json=body)
    assert wrong_type.status_code == 422 and "erasure" in wrong_type.json()["message"]
    assert rows(shop, "select name from crm.customer where id = :i", i=shop["mama"]["id"])[0].name == "Mama Mboga"
    shop["erasure_request"] = req["id"]


def test_erasure_waits_for_a_second_person_and_then_changes_only_identifying_fields(client, shop) -> None:  # type: ignore[no-untyped-def]
    rule = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "privacy.erasure",
        "approver_role_id": shop["roles"]["Owner"]})
    assert rule.status_code == 201, rule.text
    before = books(shop)
    path = f"{PRIV}/requests/{shop['erasure_request']}/erase"
    waiting = client.post(path, headers=shop["owner"], json={
        "confirm_subject": "  0712345678 ", "reason": "Customer asked us to erase her data"})
    assert waiting.status_code == 200, waiting.text
    assert waiting.json()["awaiting_approval"] is True and waiting.json()["status"] == "in_progress"
    assert client.post(path, headers=shop["owner"], json={
        "confirm_subject": PHONE, "reason": "Customer asked us to erase her data"}).status_code == 409
    assert rows(shop, "select name from crm.customer where id = :i", i=shop["mama"]["id"])[0].name == "Mama Mboga"
    pending = client.get("/api/v1/approvals/pending", headers=shop["owner2"]).json()
    request = next(x for x in pending if x["doc_id"] == shop["erasure_request"])
    assert request["doc_type"] == "privacy.erasure"
    own = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["owner"], json={"approve": True})
    assert own.status_code == 403                                                    # separation of duties
    decided = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["owner2"], json={"approve": True})
    assert decided.status_code == 200, decided.text

    done = client.get(f"{PRIV}/requests/{shop['erasure_request']}", headers=shop["owner"]).json()
    assert done["status"] == "completed" and done["awaiting_approval"] is False and done["completed_at"]
    assert done["subject"] == done["subject_masked"] == "0712****678" and PHONE not in str(done)
    assert all(f["label"] == "(erased)" for f in done["found"])
    results = {(r["source"], r["kind"]): r for r in done["outcome"]["erasure"]["results"]}
    assert {r["status"] for r in results.values()} == {"anonymised"} and len(results) == 8
    assert done["outcome"]["erasure"]["approved_by"] and done["outcome"]["erasure"]["requested_by"]
    assert all(r["kept"] for r in results.values())
    assert any("accounting" in k["why"] or "financial" in k["why"] for k in results[("pos", "customer_documents")]["kept"]
               + results[("crm", "customer")]["kept"])

    # the customer is a placeholder, but the credit position, code and every document stay
    c = rows(shop, "select code, name, phone, email, tax_id, credit_limit, kind from crm.customer where id = :i",
             i=shop["mama"]["id"])[0]
    assert c.name == f"[erased] customer {c.code}" and c.phone is None and c.email is None and c.tax_id is None
    assert c.credit_limit == 5000 and c.kind == "individual"
    assert rows(shop, "select name, phone, role from crm.customer_contact") == [("[erased] contact", None, None)]
    lead = rows(shop, "select name, phone, email from crm.lead where id = :i", i=shop["lead"])[0]
    assert lead.name == "[erased] lead" and lead.phone is None and lead.email is None
    assert {r.note for r in rows(shop, "select note from crm.activity")} == {"[removed]"}
    assert rows(shop, "select notes from pos.sales_invoice where customer_id = :i", i=shop["mama"]["id"])[0].notes is None
    assert books(shop) == before                                                      # sales, invoices, receipts, ledger
    with system(shop) as s:
        net = s.execute(text("select coalesce(sum(debit - credit), 0) from finance.journal_line")).scalar_one()
    assert net == 0                                                                   # the ledger still balances
    txn = rows(shop, "select counterparty_name, counterparty_phone_masked, phone_hash, external_ref, amount "
                     "from payments.external_transaction")[0]
    assert txn.counterparty_name is None and txn.phone_hash is None and txn.counterparty_phone_masked == "erased"
    assert txn.amount == Dec("116.00") and txn.external_ref                            # the provider's receipt stays
    sup = rows(shop, "select name, phone, tax_id, status from purchasing.supplier where id = :i", i=shop["supplier"])[0]
    assert sup.name == "[erased] supplier MAMA01" and sup.phone is None and sup.tax_id is None
    assert sup.status == "inactive"
    bank = rows(shop, "select account_name, bank_name, account_no_ciphertext, account_no_masked "
                      "from purchasing.supplier_bank_account")
    assert all(b == (None, None, None, None) for b in bank)
    msgs = rows(shop, "select recipient, subject, body, status, redacted_at from kernel.notification "
                      "where company_id = :c and body like '[erased%'", c=str(shop["company_id"]))
    assert len(msgs) == 1 and msgs[0].recipient == "25471****678" and msgs[0].redacted_at is not None
    assert msgs[0].status == "skipped"                                                # it had not been sent yet

    # the audit trail records what happened, with no personal data
    audit = rows(shop, "select changes from kernel.audit_log where action = 'erase' and entity_id = :i",
                 i=shop["erasure_request"])
    assert len(audit) == 1 and audit[0].changes["approved_by"] and audit[0].changes["subject"] == "0712****678"
    assert "Mama" not in str(audit[0].changes) and PHONE not in str(audit[0].changes)
    assert rows(shop, "select 1 from kernel.audit_log where action = 'erase_requested' and entity_id = :i",
                i=shop["erasure_request"])

    # afterwards nothing identifiable is found or exported, and a repeat is refused
    for subject in (PHONE, "A001234567B", "Mama Mboga"):
        assert searched(client, shop, subject)["found"] == [], subject
    # messages sent to her email address are found by that address (each identifier is searched on its own)
    by_email = searched(client, shop, "mama@example.test", kind="erasure")
    assert kinds(by_email) == [("kernel.notifications", "message_history")]
    cleared = client.post(f"{PRIV}/requests/{by_email['id']}/erase", headers=shop["owner"], json={
        "confirm_subject": "mama@example.test", "reason": "Same person: her email address"})
    assert cleared.status_code == 200 and cleared.json()["awaiting_approval"] is True
    pending = client.get("/api/v1/approvals/pending", headers=shop["owner2"]).json()
    waiting = next(x for x in pending if x["doc_id"] == by_email["id"])
    assert client.post(f"/api/v1/approvals/{waiting['id']}/decision", headers=shop["owner2"],
                       json={"approve": True}).status_code == 200
    assert searched(client, shop, "mama@example.test")["found"] == []
    mail = rows(shop, "select recipient, subject, body from kernel.notification where body like '[erased%'")
    assert len(mail) == 2 and {m.recipient for m in mail} == {"25471****678", "m***@example.test"}
    exported = client.post(f"{PRIV}/requests/{shop['erasure_request']}/export", headers=shop["owner"])
    assert exported.status_code == 409
    assert client.post(f"{PRIV}/requests/{shop['erasure_request']}/erase", headers=shop["owner"], json={
        "confirm_subject": PHONE, "reason": "again please"}).status_code == 409


def test_a_rejected_erasure_changes_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = credit_customer(client, shop, name="Keep Me", limit="0", terms=0, phone="0733000444", kind="individual")
    req = searched(client, shop, "0733000444", kind="erasure")
    r = client.post(f"{PRIV}/requests/{req['id']}/erase", headers=shop["owner"], json={
        "confirm_subject": "0733000444", "reason": "Asked to be erased"})
    assert r.status_code == 200 and r.json()["awaiting_approval"] is True
    request = next(x for x in client.get("/api/v1/approvals/pending", headers=shop["owner2"]).json()
                   if x["doc_id"] == req["id"])
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["owner2"],
                       json={"approve": False}).status_code == 422                       # a reason is required
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["owner2"],
                       json={"approve": False, "note": "Not verified yet"}).status_code == 200
    after = client.get(f"{PRIV}/requests/{req['id']}", headers=shop["owner"]).json()
    assert after["status"] == "in_progress" and after["awaiting_approval"] is False
    assert rows(shop, "select name from crm.customer where id = :i", i=c["id"])[0].name == "Keep Me"
    assert rows(shop, "select 1 from kernel.audit_log where action = 'erase_rejected' and entity_id = :i", i=req["id"])
    # it can be asked again
    again = client.post(f"{PRIV}/requests/{req['id']}/erase", headers=shop["owner"], json={
        "confirm_subject": "0733000444", "reason": "Identity now verified"})
    assert again.status_code == 200 and again.json()["awaiting_approval"] is True


def test_with_approval_switched_off_an_erasure_runs_at_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = credit_customer(client, shop, name="Quick Erase", limit="0", terms=0, phone="0733000555", kind="individual")
    settings(client, shop, privacy_erasure_needs_approval=False)
    try:
        req = searched(client, shop, "0733000555", kind="erasure")
        done = client.post(f"{PRIV}/requests/{req['id']}/erase", headers=shop["owner"], json={
            "confirm_subject": "0733000555", "reason": "Customer request"})
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "completed" and done.json()["outcome"]["erasure"]["approved_by"] is None
    finally:
        settings(client, shop, privacy_erasure_needs_approval=True)
    assert rows(shop, "select name from crm.customer where id = :i", i=c["id"])[0].name.startswith("[erased] customer")


# --------------------------------------------------------------------------- employees
def payslip(shop, employee_id, period_end):  # type: ignore[no-untyped-def]
    """A paid payroll run with one payslip for the employee (inserted directly: the payroll flow is tested elsewhere)."""
    run_id = uuid4()
    with system(shop) as s:
        s.execute(text(
            "insert into people.payroll_run (id, tenant_id, company_id, period_start, period_end, pay_date, status, "
            "totals, exceptions) values (:r, :t, :c, :ps, :pe, :pe, 'paid', '{}', '[]')"),
            {"r": str(run_id), "t": str(shop["tenant_id"]), "c": str(shop["company_id"]),
             "ps": period_end - timedelta(days=29), "pe": period_end})
        s.execute(text(
            "insert into people.payslip (tenant_id, run_id, employee_id, gross_pay, taxable_pay, total_deductions, "
            "net_pay, employer_cost, status, detail) values (:t, :r, :e, 50000, 50000, 5000, 45000, 50000, 'paid', "
            "'{}')"), {"t": str(shop["tenant_id"]), "r": str(run_id), "e": employee_id})


def erase_now(client, shop, subject, who="owner"):  # type: ignore[no-untyped-def]
    req = searched(client, shop, subject, kind="erasure", who=who)
    r = client.post(f"{PRIV}/requests/{req['id']}/erase", headers=shop[who], json={
        "confirm_subject": subject, "reason": "Former employee asked us to erase their data"})
    assert r.status_code == 200, r.text
    return r.json()


def test_an_employee_is_found_by_every_identifier_and_exported_with_their_id(client, shop) -> None:  # type: ignore[no-untyped-def]
    e = new_employee(client, shop, "Zawadi Achieng", national_id="12345678", tax_id="A111222333X", phone="0722000111",
                     email="zawadi@example.test", registrations={"PENSION": "PEN-555"})
    shop["employee"] = e["id"]
    bank = client.post(f"{PEOPLE}/employees/{e['id']}/bank-accounts", headers=shop["hr"], json={
        "method": "bank", "account_no": "99887766", "bank_name": "First Bank"})
    assert bank.status_code == 201, bank.text
    for subject in ("0722000111", "zawadi@example.test", "A111222333X", "12345678", "PEN-555"):
        found = searched(client, shop, subject)
        assert ("people", "employee") in kinds(found), subject
    export = client.post(f"{PRIV}/requests/{searched(client, shop, '12345678')['id']}/export", headers=shop["owner"])
    data = next(x for x in export.json()["records"] if x["source"] == "people")["data"]
    assert data["profile"]["full_name"] == "Zawadi Achieng" and data["profile"]["national_id"] == "12345678"
    assert data["profile"]["tax_id"] == "A111222333X" and data["profile"]["registrations"] == {"PENSION": "PEN-555"}
    assert "national_id_ciphertext" not in data["profile"]
    assert data["payment_details"][0]["account_no_masked"].endswith("7766")
    assert "99887766" not in str(data) and "account_no_ciphertext" not in str(data)
    assert data["payslips"] == []


def test_a_current_employee_cannot_be_erased(client, shop) -> None:  # type: ignore[no-untyped-def]
    settings(client, shop, privacy_erasure_needs_approval=False)
    try:
        result = erase_now(client, shop, "0722000111")
        assert result["status"] == "refused"
        r = result["outcome"]["erasure"]["results"][0]
        assert r["status"] == "refused" and "still employed" in r["message"]
        assert result["subject"] == "0722000111"                                   # still findable: nothing was erased
        name = rows(shop, "select full_name from people.employee where id = :i", i=shop["employee"])[0].full_name
        assert name == "Zawadi Achieng"
    finally:
        settings(client, shop, privacy_erasure_needs_approval=True)


def test_payroll_records_are_kept_for_the_retention_period_then_anonymised(client, shop) -> None:  # type: ignore[no-untyped-def]
    ended = date.today() - timedelta(days=60)
    assert client.post(f"{PEOPLE}/employees/{shop['employee']}/terminate", headers=shop["hr"],
                       json={"termination_date": str(ended)}).status_code == 200
    payslip(shop, shop["employee"], ended)
    settings(client, shop, privacy_erasure_needs_approval=False)
    try:
        partial = erase_now(client, shop, "0722000111")
        res = partial["outcome"]["erasure"]["results"][0]
        assert partial["status"] == "completed" and res["status"] == "partial"
        until = date(ended.year + 7, ended.month, ended.day if (ended.month, ended.day) != (2, 29) else 28)
        assert all(str(until) in k["why"] for k in res["kept"]) and "retention_employee_records_years" in res["kept"][0]["why"]
        assert "phone removed" in res["changed"] and "email removed" in res["changed"]
        e = rows(shop, "select full_name, phone, email, tax_id, national_id_ciphertext from people.employee where id = :i",
                 i=shop["employee"])[0]
        assert e.full_name == "Zawadi Achieng" and e.phone is None and e.email is None
        assert e.tax_id == "A111222333X" and e.national_id_ciphertext is not None
        assert partial["subject"] == "0722000111"                                  # a record still holds the data
    finally:
        settings(client, shop, privacy_erasure_needs_approval=True)


def test_an_erased_employee_keeps_the_pay_figures(client, shop) -> None:  # type: ignore[no-untyped-def]
    settings(client, shop, privacy_erasure_needs_approval=False, retention_employee_records_years=0)
    try:
        done = erase_now(client, shop, "A111222333X")
        res = done["outcome"]["erasure"]["results"][0]
        assert res["status"] == "anonymised" and done["status"] == "completed"
        e = rows(shop, "select employee_no, full_name, phone, email, tax_id, national_id_ciphertext, registrations "
                       "from people.employee where id = :i", i=shop["employee"])[0]
        assert e.full_name == f"[erased] employee {e.employee_no}" and e.tax_id is None
        assert e.national_id_ciphertext is None and e.registrations == {}
        bank = rows(shop, "select bank_name, account_no_ciphertext, account_no_masked from people.employee_bank_account "
                          "where employee_id = :i", i=shop["employee"])
        assert bank == [(None, None, None)]
        slip = rows(shop, "select gross_pay, net_pay, total_deductions from people.payslip where employee_id = :i",
                    i=shop["employee"])
        assert [(s.gross_pay, s.net_pay, s.total_deductions) for s in slip] == [(Dec(50000), Dec(45000), Dec(5000))]
        assert any("payslips" in k["what"] for k in res["kept"])
        assert searched(client, shop, "zawadi@example.test")["found"] == []
    finally:
        settings(client, shop, privacy_erasure_needs_approval=True, retention_employee_records_years=7)


# --------------------------------------------------------------------------- users
def test_a_user_can_be_erased_but_not_oneself_or_the_only_owner(client, shop) -> None:  # type: ignore[no-untyped-def]
    code = shop["code"]
    leaver = client.post("/api/v1/users", headers=shop["owner"], json={
        "full_name": "Lee Leaver", "email": f"leaver@{code}.test", "password": "leaver-pass-1"}).json()
    sign_in(client, code, f"leaver@{code}.test", "leaver-pass-1")
    settings(client, shop, privacy_erasure_needs_approval=False)
    try:
        found = searched(client, shop, f"leaver@{code}.test")
        assert ("kernel.users", "user") in kinds(found)
        export = client.post(f"{PRIV}/requests/{found['id']}/export", headers=shop["owner"]).json()
        user = next(x for x in export["records"] if x["source"] == "kernel.users")["data"]
        assert user["profile"]["email"] == f"leaver@{code}.test" and "password_hash" not in str(user)
        assert len(user["sign_in_devices"]) == 1
        done = erase_now(client, shop, f"leaver@{code}.test")
        assert done["status"] == "completed"
        row = rows(shop, "select full_name, email, phone, password_hash, status from kernel.app_user where id = :i",
                   i=leaver["id"])[0]
        assert row == ("Erased user", None, None, None, "disabled")
        assert rows(shop, "select revoked_at, device_name from kernel.user_session where user_id = :i",
                    i=leaver["id"])[0].revoked_at is not None
        signin = client.post("/api/v1/auth/sign-in", json={"login": f"leaver@{code}.test", "password": "leaver-pass-1",
                                                           "device_id": "d"})
        assert signin.status_code in (401, 403)
        # your own account is refused
        mine = erase_now(client, shop, f"owner@{code}.test")
        assert mine["status"] == "refused"
        assert "signed in with" in mine["outcome"]["erasure"]["results"][0]["message"]
    finally:
        settings(client, shop, privacy_erasure_needs_approval=True)


# --------------------------------------------------------------------------- tenants
def test_another_business_never_sees_or_touches_the_request(client, shop, registry) -> None:  # type: ignore[no-untyped-def]
    other = make_tenant("Privacy Other")
    registry.enable(other["tenant_id"], "crm")
    owner = sign_in(client, "privacy-other", "owner@privacy-other.test").headers
    theirs = client.post("/api/v1/crm/customers", headers=owner, json={
        "company_id": str(other["company_id"]), "name": "Mama Mboga", "phone": PHONE, "email": "mama@example.test"})
    assert theirs.status_code == 201, theirs.text
    mine = searched(client, shop)
    assert all(f["label"] != "Mama Mboga" or f["record_id"] != theirs.json()["id"] for f in mine["found"])
    # their own search finds only their customer
    req = client.post(f"{PRIV}/requests", headers=owner, json={
        "company_id": str(other["company_id"]), "request_type": "access", "subject": PHONE}).json()
    found = client.post(f"{PRIV}/requests/{req['id']}/search", headers=owner).json()
    assert [(f["source"], f["record_id"]) for f in found["found"]] == [("crm", theirs.json()["id"])]
    # requests, exports and retention are not readable across businesses
    assert client.get(f"{PRIV}/requests/{req['id']}", headers=shop["owner"]).status_code == 404
    assert client.post(f"{PRIV}/requests/{req['id']}/export", headers=shop["owner"]).status_code == 404
    assert client.get(f"{PRIV}/requests/{mine['id']}", headers=owner).status_code == 404
    assert client.get(f"{PRIV}/retention", headers=owner, params={"company_id": str(shop["company_id"])}).status_code in (
        403, 404)
    assert client.post(f"{PRIV}/requests", headers=owner, json={
        "company_id": str(shop["company_id"]), "request_type": "access", "subject": PHONE}).status_code in (403, 422)
    assert [r["id"] for r in client.get(f"{PRIV}/requests", headers=owner).json()] == [req["id"]]


# --------------------------------------------------------------------------- retention
def test_the_retention_view_lists_what_each_unit_keeps(client, shop) -> None:  # type: ignore[no-untyped-def]
    view = client.get(f"{PRIV}/retention", headers=shop["owner"], params={"company_id": str(shop["company_id"])})
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["settings"] == {"retention_notifications_days": 0, "retention_audit_years": 7,
                                "retention_employee_records_years": 7, "retention_inactive_customers_years": 0}
    by = {(r["unit"], r["code"]): r for r in body["rules"]}
    for key in (("kernel", "notifications"), ("kernel", "audit"), ("kernel", "users"), ("crm", "customers"),
                ("people", "employees"), ("pos", "sales_documents"), ("purchasing", "suppliers"),
                ("payments", "payers")):
        assert key in by, key
    assert by[("kernel", "audit")]["at_end"] == "keep" and by[("people", "employees")]["setting"] == (
        "retention_employee_records_years")
    assert "audit log" in body["never_deleted"] and "journal entries and lines" in body["never_deleted"]
    assert client.get(f"{PRIV}/retention", headers=shop["owner"]).status_code == 422


def old_message(shop, recipient, body, days, status="sent"):  # type: ignore[no-untyped-def]
    from ziira.sdk import send_notification

    with system(shop) as s:
        n = send_notification(s, company_id=shop["company_id"], channel="email", recipient=recipient, body=body,
                              subject="Hello")
        s.execute(text("update kernel.notification set status = :st, created_at = now() - make_interval(days => :d) "
                       "where id = :i"), {"st": status, "d": days, "i": str(n)})
    return n


def test_the_retention_job_masks_old_notifications_only(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    old = old_message(shop, "olduser@example.test", "Statement for old user", 90)
    old_queued = old_message(shop, "stuck@example.test", "Still waiting", 90, status="queued")
    recent = old_message(shop, "newuser@example.test", "Statement for new user", 5)
    run = lambda: jobs.run_periodic(shop["tenant_id"], only="privacy.apply_retention", force=True)  # noqa: E731
    assert run() == 1
    assert rows(shop, "select body, recipient from kernel.notification where id = :i", i=str(old))[0].body == (
        "Statement for old user")                                                  # period 0: nothing is masked
    try:
        settings(client, shop, retention_notifications_days=30)
        assert run() == 1
    finally:
        settings(client, shop, retention_notifications_days=0)
    gone = rows(shop, "select recipient, subject, body, redacted_at, status from kernel.notification where id = :i",
                i=str(old))[0]
    assert gone.recipient == "o***@example.test" and gone.body == "[removed after retention period]"
    assert gone.subject == "[removed after retention period]" and gone.redacted_at is not None
    assert gone.status == "sent"                                                   # the fact it was sent stays
    kept = rows(shop, "select recipient, body, redacted_at from kernel.notification where id = :i", i=str(recent))[0]
    assert kept.recipient == "newuser@example.test" and kept.body == "Statement for new user" and kept.redacted_at is None
    waiting = rows(shop, "select recipient, redacted_at from kernel.notification where id = :i", i=str(old_queued))[0]
    assert waiting.recipient == "stuck@example.test" and waiting.redacted_at is None   # a message still to be sent
    entry = rows(shop, "select changes from kernel.audit_log where action = 'retention_mask' order by id desc limit 1")[0]
    assert entry.changes["messages_masked"] >= 1 and entry.changes["older_than_days"] == 30
    assert "olduser" not in str(entry.changes)
    # a masked message cannot be edited again, and a live one still cannot be edited by hand
    with pytest.raises(Exception, match="cannot be edited"), system(shop) as s:
        s.execute(text("update kernel.notification set body = 'again' where id = :i"), {"i": str(old)})
    with pytest.raises(Exception, match="cannot be edited"), system(shop) as s:
        s.execute(text("update kernel.notification set body = 'edited' where id = :i"), {"i": str(recent)})


def test_the_job_never_touches_the_immutable_tables(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    last = rows(shop, "select max(id) from kernel.audit_log")[0][0]
    snapshot = lambda: (rows(shop, "select md5(string_agg(hash, '' order by id)) from kernel.audit_log "  # noqa: E731
                             "where id <= :m", m=last)[0][0],
                        rows(shop, "select count(*) from finance.journal_line")[0][0],
                        rows(shop, "select count(*) from inventory.stock_movement")[0][0])
    before = snapshot()
    settings(client, shop, retention_notifications_days=1)
    try:
        jobs.run_periodic(shop["tenant_id"], only="privacy.apply_retention", force=True)
    finally:
        settings(client, shop, retention_notifications_days=0)
    assert snapshot() == before


def test_overdue_requests_and_inactive_customers_are_flagged_for_a_person(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    late = new_request(client, shop, "late@example.test", received_on=str(date.today() - timedelta(days=45)))
    assert late["overdue"] is True and late["due_date"] < str(date.today())
    old = credit_customer(client, shop, name="Long Gone", limit="0", terms=0, phone="0733000666", kind="individual")
    with system(shop) as s:
        s.execute(text("update crm.customer set status = 'inactive', created_at = now() - interval '5 years', "
                       "updated_at = now() - interval '5 years' where id = :i"), {"i": old["id"]})
    settings(client, shop, retention_inactive_customers_years=3)
    try:
        jobs.run_periodic(shop["tenant_id"], only="privacy.apply_retention", force=True)
    finally:
        settings(client, shop, retention_inactive_customers_years=0)
    items = rows(shop, "select kind, severity, message, ref_id from kernel.exception_item "
                       "where kind in ('privacy_request_overdue', 'retention_review')")
    kinds_ = {i.kind for i in items}
    assert kinds_ == {"privacy_request_overdue", "retention_review"}
    overdue = next(i for i in items if i.kind == "privacy_request_overdue")
    assert late["number"] in overdue.message and overdue.severity == "high"
    review = next(i for i in items if i.kind == "retention_review")
    assert "1 record" in review.message and "Long Gone" not in review.message
    count = len(items)
    jobs.run_periodic(shop["tenant_id"], only="privacy.apply_retention", force=True)       # running again adds nothing
    assert len(rows(shop, "select 1 from kernel.exception_item where kind in "
                          "('privacy_request_overdue', 'retention_review')")) == count


# --------------------------------------------------------------------------- the contract
def test_subject_reading_and_masking() -> None:
    from ziira.kernel.errors import ValidationFailed
    from ziira.kernel.personal_data import mask_text, parse_subject

    s = parse_subject("+254 712-345 678", "")
    assert s.phone == "254712345678" and s.email is None and s.name is None
    assert parse_subject("0712 345 678", "254").phone == "254712345678"
    assert parse_subject("Jane@Example.COM", "").email == "jane@example.com"
    n = parse_subject("  Jane   Wanjiru ", "")
    assert n.name == "Jane Wanjiru" and n.phone is None and n.identifier is None
    assert parse_subject("a-123 456/7", "").identifier == "A123456/7"
    assert mask_text("jane.doe@example.com") == "j***@example.com"
    assert mask_text("254712345678") == "2547****678" and mask_text("Jane Doe") == "J*** D**"
    for bad in ("", "  ", "ab", "@@@", "12", "123"):
        with pytest.raises(ValidationFailed):
            parse_subject(bad, "")


def test_the_socket_is_declared_and_implemented_by_the_units_that_hold_people() -> None:
    from ziira.kernel import extensions

    point = extensions.extension_points()["kernel.personal_data"]
    assert point.owner == "kernel"
    assert {unit for unit, _ in point.implementations} == {
        "kernel", "connect", "crm", "people", "pos", "purchasing", "payments", "intel"}

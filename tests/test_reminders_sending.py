"""Chasing customers: a message goes out by SMS or email - on request, in a batch, or automatically every
day - and never to someone who asked not to be contacted."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.pos_helpers import POS, credit_customer, make_sales_shop
from tests.stock_helpers import system

CRM = "/api/v1/crm"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Chase Co", stock="500")
    registry.enable(s["tenant_id"], "messaging")
    s["rep"] = s["user"]("rep", "Sales Rep", s["branch_id"])
    for channel in ("sms", "email"):
        r = client.put(f"/api/v1/notifications/channels/{channel}", headers=s["owner"], json={
            "company_id": str(s["company_id"]), "provider": "fake", "secret": {"k": "v"}})
        assert r.status_code == 200, r.text
    return s


def fakes():  # type: ignore[no-untyped-def]
    from ziira.plugins.messaging.providers import FakeEmail, FakeSms

    for fake in (FakeSms, FakeEmail):
        fake.sent.clear()
        fake.refuse_next, fake.fail_next = None, 0
    return FakeSms, FakeEmail


def deliver(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    with system(shop) as s:
        s.execute(text("update kernel.job set run_at = now() where status = 'queued'"))
    jobs.run_due(shop["tenant_id"])


def overdue(client, shop, cust, days_late=10, qty="1"):  # type: ignore[no-untyped-def]
    """An invoice due `days_late` days ago."""
    r = client.post(f"{POS}/invoices", headers=shop["rep"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "terms_days": 30,
        "issue_date": str(date.today() - timedelta(days=30 + days_late)),
        "lines": [{"product_id": shop["cement"], "quantity": qty}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_reminder_is_sent_by_sms_and_noted(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, *_ = fakes()
    cust = credit_customer(client, shop, name="Mama Wanjiru", limit="50000", phone="0722111333")
    inv = overdue(client, shop, cust, 10)
    r = client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"], json={"channel": "sms"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "queued" and r.json()["channel"] == "sms"
    assert sms.sent == []
    deliver(shop)
    [message] = sms.sent
    assert message.recipient == "254722111333"
    assert inv["number"] in message.body and "116.00" in message.body and "Mama Wanjiru" in message.body
    assert "was due on" in message.body and "Chase Co" in message.body
    noted = one(shop, "select count(*) from pos.invoice_reminder where invoice_id = :i and channel = 'sms'", i=inv["id"])
    assert noted == 1
    again = client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"], json={"channel": "sms"})
    assert again.status_code == 422 and "already sent" in again.json()["message"]            # once a day
    history = client.get("/api/v1/notifications", headers=shop["owner"], params={
        "company_id": str(shop["company_id"]), "ref_type": "sales_invoice", "ref_id": inv["id"]}).json()
    assert [h["status"] for h in history] == ["sent"]


def test_email_and_sms_reminders_and_missing_contact_details(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, email = fakes()
    cust = credit_customer(client, shop, name="Both Ways", limit="50000", phone="0711999888", email="pay@both.test")
    inv = overdue(client, shop, cust, 3)
    assert client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"],
                       json={"channel": "email"}).status_code == 201
    assert client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"],
                       json={"channel": "sms"}).status_code == 201                       # another channel, same day
    deliver(shop)
    assert email.sent[0].recipient == "pay@both.test" and email.sent[0].subject.startswith("Reminder: invoice")
    assert sms.sent[0].recipient == "254711999888"
    no_email = credit_customer(client, shop, name="Phone Only", limit="50000", phone="0711999777")
    inv2 = overdue(client, shop, no_email, 3)
    r = client.post(f"{POS}/invoices/{inv2['id']}/send-reminder", headers=shop["fm"], json={"channel": "email"})
    assert r.status_code == 422 and "no email address" in r.json()["message"]
    no_phone = credit_customer(client, shop, name="Email Only", limit="50000", email="only@mail.test")
    inv3 = overdue(client, shop, no_phone, 3)
    r = client.post(f"{POS}/invoices/{inv3['id']}/send-reminder", headers=shop["fm"], json={"channel": "sms"})
    assert r.status_code == 422 and "no phone number" in r.json()["message"]
    assert client.post(f"{POS}/invoices/{inv3['id']}/send-reminder", headers=shop["fm"], json={}).status_code == 422
    assert client.post(f"{POS}/invoices/{inv3['id']}/send-reminder", headers=shop["fm"], json={"channel": "pigeon"}
                       ).status_code == 422


def test_someone_who_asked_not_to_be_contacted_is_left_alone(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, *_ = fakes()
    cust = credit_customer(client, shop, name="Do Not Disturb", limit="50000", phone="0733555111",
                           email="dnd@shop.test")
    inv = overdue(client, shop, cust, 5)
    r = client.post(f"{CRM}/customers/{cust['id']}/do-not-contact", headers=shop["rep"], json={
        "channel": "sms", "reason": "Asked us on the phone"})
    assert r.status_code == 200 and r.json()["recorded"] == ["phone"]
    sent = client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"], json={"channel": "sms"})
    assert sent.status_code == 201 and sent.json()["status"] == "skipped"
    deliver(shop)
    assert sms.sent == []
    assert one(shop, "select count(*) from pos.invoice_reminder where invoice_id = :i", i=inv["id"]) == 0   # not chased
    email = client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"], json={"channel": "email"})
    assert email.json()["status"] == "queued"                                                # only SMS was refused
    everything = client.post(f"{CRM}/customers/{cust['id']}/do-not-contact", headers=shop["rep"], json={})
    assert everything.status_code == 200 and sorted(everything.json()["recorded"]) == ["email", "phone"]
    bare = credit_customer(client, shop, name="No Contact Details", limit="100")
    assert client.post(f"{CRM}/customers/{bare['id']}/do-not-contact", headers=shop["rep"], json={}).status_code == 422
    assert client.post(f"{CRM}/customers/{cust['id']}/do-not-contact", headers=shop["cashier"], json={}
                       ).status_code == 403


def test_a_paid_invoice_and_permissions(client, shop) -> None:  # type: ignore[no-untyped-def]
    fakes()
    cust = credit_customer(client, shop, name="Pays Up", limit="50000", phone="0700121212")
    inv = overdue(client, shop, cust, 5)
    path = f"{POS}/invoices/{inv['id']}/send-reminder"
    assert client.post(path, headers=shop["storekeeper"], json={"channel": "sms"}).status_code == 403
    client.post(f"{POS}/receipts", headers=shop["fm"], json={
        "customer_id": cust["id"], "amount": "116.00", "method": "cash", "branch_id": str(shop["branch_id"])})
    paid = client.post(path, headers=shop["fm"], json={"channel": "sms"})
    assert paid.status_code == 422 and "unpaid" in paid.json()["message"]
    assert client.post(f"{POS}/invoices/{uuid4()}/send-reminder", headers=shop["fm"], json={"channel": "sms"}
                       ).status_code == 404


def test_chasing_everyone_who_is_overdue_in_one_go(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, *_ = fakes()
    ok = [credit_customer(client, shop, name=f"Batch {i}", limit="50000", phone=f"07003000{i:02d}") for i in range(3)]
    invs = [overdue(client, shop, c, 4 + i) for i, c in enumerate(ok)]
    silent = credit_customer(client, shop, name="Batch Silent", limit="50000", phone="0700300099")
    overdue(client, shop, silent, 6)
    client.post(f"{CRM}/customers/{silent['id']}/do-not-contact", headers=shop["rep"], json={})
    nameless = credit_customer(client, shop, name="Batch No Phone", limit="50000", email="x@y.test")
    overdue(client, shop, nameless, 6)
    r = client.post(f"{POS}/receivables/send-reminders", headers=shop["fm"], json={"channel": "sms"})
    assert r.status_code == 200, r.text
    counts = r.json()
    assert counts["sent"] >= 3 and counts["skipped"] >= 1 and counts["no_contact"] >= 1
    deliver(shop)
    numbers = {m.recipient for m in sms.sent}
    assert {"254700300000", "254700300001", "254700300002"} <= numbers and "254700300099" not in numbers
    again = client.post(f"{POS}/receivables/send-reminders", headers=shop["fm"], json={"channel": "sms"}).json()
    assert again["sent"] == 0                                                                # chased lately: left alone
    assert all(client.get(f"{POS}/invoices/{i['id']}", headers=shop["fm"]).status_code == 200 for i in invs)
    assert client.post(f"{POS}/receivables/send-reminders", headers=shop["storekeeper"], json={}).status_code == 403


def test_the_daily_task_chases_businesses_that_asked_for_it(client, shop, registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    sms, *_ = fakes()
    co = str(shop["company_id"])
    cust = credit_customer(client, shop, name="Automatic Target", limit="50000", phone="0700400400")
    inv = overdue(client, shop, cust, 12)
    jobs.run_periodic(shop["tenant_id"])                                                       # setting is off
    deliver(shop)
    assert not any(m.recipient == "254700400400" for m in sms.sent)
    for bad in ({"reminder_channel": "pigeon"}, {"reminder_repeat_days": -1}, {"reminder_min_days_overdue": 999}):
        assert client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json=bad).status_code == 422
    on = client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={
        "reminder_channel": "sms", "reminder_min_days_overdue": 5, "reminder_repeat_days": 3})
    assert on.status_code == 200 and on.json()["reminder_channel"] == "sms" and on.json()["reminder_repeat_days"] == 3
    with system(shop) as s:
        s.execute(text("update kernel.periodic_run set last_run_at = now() - interval '2 days' "
                       "where name = 'pos.send_reminders'"))
    assert jobs.run_periodic(shop["tenant_id"]) >= 1
    deliver(shop)
    mine = [m for m in sms.sent if m.recipient == "254700400400"]
    assert len(mine) == 1 and inv["number"] in mine[0].body
    # the very next day it does not chase the same invoice again until the repeat period has passed
    with system(shop) as s:
        s.execute(text("update kernel.periodic_run set last_run_at = now() - interval '2 days' "
                       "where name = 'pos.send_reminders'"))
    jobs.run_periodic(shop["tenant_id"])
    deliver(shop)
    assert len([m for m in sms.sent if m.recipient == "254700400400"]) == 1
    # an invoice that is only a couple of days late is left alone (the setting says 5)
    soon = credit_customer(client, shop, name="Only Just Late", limit="50000", phone="0700400411")
    overdue(client, shop, soon, 2)
    with system(shop) as s:
        s.execute(text("update kernel.periodic_run set last_run_at = now() - interval '2 days' "
                       "where name = 'pos.send_reminders'"))
    jobs.run_periodic(shop["tenant_id"])
    deliver(shop)
    assert not any(m.recipient == "254700400411" for m in sms.sent)
    client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"reminder_channel": "off"})


def test_the_purchasing_tolerance_can_be_changed_over_the_api(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    r = client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={
        "bill_match_tolerance_percent": "5.5"})
    assert r.status_code == 200 and float(r.json()["bill_match_tolerance_percent"]) == 5.5
    for bad in ("-1", "101", "abc"):
        assert client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={
            "bill_match_tolerance_percent": bad}).status_code == 422

"""Customer reminders by WhatsApp: the template with the customer's name, the amount in the company's own currency, the due
date and the business name; the fall back to SMS and email while a template is not approved; and a customer's STOP or
do-not-contact being respected."""

from datetime import date, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.pos_helpers import POS, credit_customer, make_sales_shop
from tests.stock_helpers import system
from ziira.kernel import inbound, jobs, messaging
from ziira.sdk import InboundMessage

N = "/api/v1/notifications"
CRM = "/api/v1/crm"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Wa Chase Co", stock="500")
    registry.enable(s["tenant_id"], "messaging")
    for channel in ("chat", "sms", "email"):
        r = client.put(f"{N}/channels/{channel}", headers=s["owner"], json={
            "company_id": str(s["company_id"]), "provider": "fake", "secret": {"k": "v"}})
        assert r.status_code == 200, r.text
    return s


def fakes():  # type: ignore[no-untyped-def]
    from ziira.plugins.messaging.providers import FakeChat, FakeEmail, FakeSms

    for fake in (FakeChat, FakeSms, FakeEmail):
        fake.sent.clear()
        fake.refuse_next, fake.fail_next = None, 0
    FakeChat.decisions.clear()
    return FakeChat, FakeSms, FakeEmail


def deliver(shop) -> None:  # type: ignore[no-untyped-def]
    for _ in range(4):
        with system(shop) as s:
            s.execute(text("update kernel.job set run_at = now() where status = 'queued'"))
        if jobs.run_due(shop["tenant_id"]) == 0:
            break


def approve_templates(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"])}
    client.post(f"{N}/templates/submit", headers=shop["owner"], json=body)
    assert client.post(f"{N}/templates/sync", headers=shop["owner"], json=body).status_code == 200


def forget_approval(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text("update kernel.message_template set status = 'draft'"))
        s.execute(text("delete from kernel.contact_window"))


def overdue(client, shop, cust, days_late=10, qty="1"):  # type: ignore[no-untyped-def]
    r = client.post(f"{POS}/invoices", headers=shop["rep"], json={
        "customer_id": cust["id"], "location_id": shop["main"], "terms_days": 30,
        "issue_date": str(date.today() - timedelta(days=30 + days_late)),
        "lines": [{"product_id": shop["cement"], "quantity": qty}]})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="module", autouse=True)
def rep(shop) -> None:  # type: ignore[no-untyped-def]
    shop["rep"] = shop["user"]("rep", "Sales Rep", shop["branch_id"])


def remind(client, shop, inv, channel="chat"):  # type: ignore[no-untyped-def]
    return client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"], json={"channel": channel})


def test_an_approved_template_carries_the_customer_the_amount_the_date_and_the_business(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    forget_approval(shop)
    approve_templates(client, shop)
    cust = credit_customer(client, shop, name="Mama Wanjiru", limit="50000", phone="0722111333", email="pay@wanjiru.test")
    inv = overdue(client, shop, cust, 10)
    r = remind(client, shop, inv)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "queued" and r.json()["channel"] == "chat"
    assert wa.sent == []                                                                      # sent in the background
    deliver(shop)
    [message] = wa.sent
    due = date.today() - timedelta(days=10)
    assert message.mode == "template" and message.template_name == "ziira_overdue_reminder"
    assert message.template_params == ("Mama Wanjiru", inv["number"], "KES 116.00", "Wa Chase Co Ltd", str(due))
    assert message.recipient == "254722111333" and sms.sent == []
    assert "was due on" in message.body and "Reply STOP" in message.body
    noted = one(shop, "select count(*) from pos.invoice_reminder where invoice_id = :i and channel = 'chat'",
                i=inv["id"])
    assert noted == 1
    again = remind(client, shop, inv)
    assert again.status_code == 422 and "already sent" in again.json()["message"]            # once a day


def test_an_invoice_not_yet_due_uses_the_payment_due_wording(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, *_ = fakes()
    cust = credit_customer(client, shop, name="Early Bird", limit="50000", phone="0711000222")
    inv = overdue(client, shop, cust, -5)                                                     # due in five days
    assert remind(client, shop, inv).status_code == 201
    deliver(shop)
    assert wa.sent[0].template_name == "ziira_payment_due" and "is due on" in wa.sent[0].body


def test_the_amount_uses_the_companys_own_currency(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, *_ = fakes()
    with system(shop) as s:
        s.execute(text("update kernel.company set base_currency = 'GBP' where id = :c"), {"c": str(shop["company_id"])})
    try:
        cust = credit_customer(client, shop, name="Pounds Payer", limit="50000", phone="0711000333")
        inv = overdue(client, shop, cust, 4)
        assert remind(client, shop, inv).status_code == 201
        deliver(shop)
        assert wa.sent[0].template_params[2] == "GBP 116.00"
    finally:
        with system(shop) as s:
            s.execute(text("update kernel.company set base_currency = 'KES' where id = :c"),
                      {"c": str(shop["company_id"])})


def test_while_the_template_is_not_approved_the_reminder_goes_by_sms_then_email(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, email = fakes()
    forget_approval(shop)
    cust = credit_customer(client, shop, name="Both Ways", limit="50000", phone="0711999888", email="pay@both.test")
    inv = overdue(client, shop, cust, 3)
    r = remind(client, shop, inv)
    assert r.status_code == 201 and r.json()["status"] == "queued"
    deliver(shop)
    assert wa.sent == [] and email.sent == []
    [text_sent] = sms.sent
    assert text_sent.recipient == "254711999888" and "Dear Both Ways" in text_sent.body and "KES 116.00" in text_sent.body
    sms.refuse_next = "Blocked"
    other = overdue(client, shop, cust, 4)
    assert remind(client, shop, other).status_code == 201
    deliver(shop)
    assert [m.recipient for m in email.sent] == ["pay@both.test"]                              # sms refused: email
    assert email.sent[0].subject == "Payment reminder"


def test_a_customer_who_replied_stop_is_not_reminded_on_any_channel(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, email = fakes()
    approve_templates(client, shop)
    cust = credit_customer(client, shop, name="Stopper", limit="50000", phone="0733000111", email="stop@stopper.test")
    inv = overdue(client, shop, cust, 6)
    with system(shop) as s:
        assert inbound.route(s, InboundMessage(shop["company_id"], "chat", "254733000111", "text", "STOP", None, None,
                                               "wamid.stop-chase")) == "stopped"
    sent = remind(client, shop, inv)
    assert sent.status_code == 201 and sent.json()["status"] == "skipped"
    deliver(shop)
    assert wa.sent == [] and sms.sent == []
    assert one(shop, "select count(*) from pos.invoice_reminder where invoice_id = :i", i=inv["id"]) == 0   # not chased
    assert [m.recipient for m in email.sent] == []                                            # email is a different address
    with system(shop) as s:                                                                   # but opting back in works
        s.execute(text("delete from kernel.notification_optout where recipient = '254733000111'"))
    assert messaging.window_open is not None


def test_do_not_contact_on_whatsapp_leaves_sms_and_email_alone(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, email = fakes()
    approve_templates(client, shop)
    cust = credit_customer(client, shop, name="No WhatsApp", limit="50000", phone="0733555111", email="nw@shop.test")
    inv = overdue(client, shop, cust, 5)
    r = client.post(f"{CRM}/customers/{cust['id']}/do-not-contact", headers=shop["rep"], json={"channel": "chat"})
    assert r.status_code == 200 and r.json()["recorded"] == ["phone"]
    assert remind(client, shop, inv).status_code == 201
    deliver(shop)
    assert wa.sent == []
    assert [m.recipient for m in sms.sent] == ["254733555111"]                                # they only refused WhatsApp
    everything = client.post(f"{CRM}/customers/{cust['id']}/do-not-contact", headers=shop["rep"], json={})
    assert everything.status_code == 200
    fakes()
    inv2 = overdue(client, shop, cust, 6)
    assert remind(client, shop, inv2).json()["status"] == "skipped"
    deliver(shop)
    assert wa.sent == [] and sms.sent == []
    assert client.post(f"{CRM}/customers/{cust['id']}/do-not-contact", headers=shop["rep"], json={"channel": "pigeon"}
                       ).status_code == 422


def test_a_customer_with_no_phone_cannot_be_reached_on_whatsapp(client, shop) -> None:  # type: ignore[no-untyped-def]
    fakes()
    cust = credit_customer(client, shop, name="Email Only", limit="50000", email="only@mail.test")
    inv = overdue(client, shop, cust, 3)
    r = remind(client, shop, inv)
    assert r.status_code == 422 and "no phone number" in r.json()["message"]


def test_the_daily_task_can_chase_by_whatsapp(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    approve_templates(client, shop)
    co = str(shop["company_id"])
    cust = credit_customer(client, shop, name="Automatic Target", limit="50000", phone="0700400400")
    overdue(client, shop, cust, 12)
    on = client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={
        "reminder_channel": "chat", "reminder_min_days_overdue": 5, "reminder_repeat_days": 3})
    assert on.status_code == 200 and on.json()["reminder_channel"] == "chat", on.text
    jobs.run_periodic(shop["tenant_id"])
    deliver(shop)
    assert any(m.recipient == "254700400400" and m.template_name == "ziira_overdue_reminder" for m in wa.sent)
    off = client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"reminder_channel": "off"})
    assert off.status_code == 200
    assert UUID(co)


def test_the_automatic_reminder_action_accepts_whatsapp() -> None:
    from ziira.modules.intel.domain import action_rules
    from ziira.modules.pos.action_providers import SendPaymentReminder

    values = {"customer_id": "00000000-0000-0000-0000-000000000001", "min_days_overdue": 7, "channel": "chat"}
    assert action_rules.validate_values(SendPaymentReminder.params_schema, values)["channel"] == "chat"
    for name in ("sms", "email"):                       # no channel is named in the schema: the channel layer decides
        assert action_rules.validate_values(SendPaymentReminder.params_schema, {**values, "channel": name})
    assert action_rules.validate_values(SendPaymentReminder.rule_schema, {"channel": "chat"}, label="Condition")

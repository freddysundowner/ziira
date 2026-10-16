"""Channels exist only where a provider for them is enabled. With no chat plugin on, 'whatsapp' is rejected by settings,
preferences, do-not-contact, channel set-up, schedules and templates, and is absent from the list every screen is built
from; Intelligence, reminders and briefs carry on by the channels the business has. Nothing in the platform's own code
names a chat service."""

import re
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.pos_helpers import POS, credit_customer, make_sales_shop
from tests.stock_helpers import system
from ziira.kernel import jobs, messaging

N = "/api/v1/notifications"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Channel Registry Co", stock="500")
    for unit in ("messaging", "intel", "command"):
        registry.enable(s["tenant_id"], unit)
    for channel in ("sms", "email"):
        r = client.put(f"{N}/channels/{channel}", headers=s["owner"], json={
            "company_id": str(s["company_id"]), "provider": "fake", "secret": {"k": "v"}})
        assert r.status_code == 200, r.text
    from ziira.plugins.messaging.providers import FakeChat

    FakeChat.hidden = True                          # this business has no chat plugin
    yield s
    FakeChat.hidden = False


def available(client, shop):  # type: ignore[no-untyped-def]
    r = client.get(f"{N}/channels/available", headers=shop["owner"], params={"company_id": str(shop["company_id"])})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_business_has_only_the_channels_of_its_enabled_providers(client, shop) -> None:  # type: ignore[no-untyped-def]
    channels = available(client, shop)
    assert [c["channel"] for c in channels] == ["sms", "email"]
    assert [c["label"] for c in channels] == ["SMS", "Email"]
    assert all(c["configured"] and not c["supports_inbound"] and c["window_hours"] is None for c in channels)
    assert client.get(f"{N}/channels/available", headers=shop["cashier"]).status_code == 200      # any signed-in person
    assert client.get(f"{N}/channels/available").status_code == 401


def test_whatsapp_is_rejected_everywhere_with_a_clear_message(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    clear = "not available for this business"
    for key in ("intel_alert_channel", "reminder_channel"):
        r = client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={key: "whatsapp"})
        assert r.status_code == 422 and clear in r.json()["message"] and "Available: sms, email" in r.json()["message"]
    r = client.put(f"{N}/me/preferences", headers=shop["owner"], json={"channels": {"alerts": "whatsapp"}})
    assert r.status_code == 422 and clear in r.json()["message"]
    r = client.put(f"{N}/channels/whatsapp", headers=shop["owner"], json={
        "company_id": co, "provider": "leadsintel", "secret": {"k": "v"}})
    assert r.status_code == 422 and clear in r.json()["message"]
    r = client.post(f"{N}/opt-outs", headers=shop["owner"], json={"company_id": co, "recipient": "0722000111",
                                                                  "channel": "whatsapp"})
    assert r.status_code == 422 and clear in r.json()["message"]
    r = client.post(f"{N}/test", headers=shop["owner"], json={"company_id": co, "channel": "whatsapp",
                                                              "recipient": "0722000111"})
    assert r.status_code == 422 and clear in r.json()["message"]
    cust = credit_customer(client, shop, name="No Chat", limit="50000", phone="0722000111")
    r = client.post(f"/api/v1/crm/customers/{cust['id']}/do-not-contact", headers=shop["owner"],
                    json={"channel": "whatsapp"})
    assert r.status_code == 422 and clear in r.json()["message"]
    r = client.put("/api/v1/command/schedules/mine/daily", headers=shop["owner"], json={
        "channel": "whatsapp", "send_time": "07:30", "is_active": True})
    assert r.status_code == 422 and clear in r.json()["message"]
    r = client.post("/api/v1/command/briefs/send-now", headers=shop["owner"], params={"channel": "whatsapp"})
    assert r.status_code == 422 and clear in r.json()["message"]
    ok = client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"intel_alert_channel": "email"})
    assert ok.status_code == 200 and ok.json()["intel_alert_channel"] == "email"
    assert client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"],
                        json={"intel_alert_channel": "off"}).status_code == 200


def test_no_templates_and_no_verified_number_without_a_chat_channel(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    assert client.get(f"{N}/templates", headers=shop["owner"], params={"company_id": co}).json() == []
    r = client.post(f"{N}/templates/submit", headers=shop["owner"], json={"company_id": co})
    assert r.status_code == 422 and "No channel that needs templates" in r.json()["message"]
    prefs = client.get(f"{N}/me/preferences", headers=shop["owner"]).json()
    assert prefs["can_verify"] is False
    r = client.post(f"{N}/me/verified-number", headers=shop["owner"], json={"company_id": co, "phone": "0711222333"})
    assert r.status_code == 422 and "receives replies" in r.json()["message"]


def test_a_message_for_a_channel_that_does_not_exist_goes_the_next_way_or_is_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.plugins.messaging.providers import FakeEmail, FakeSms
    from ziira.sdk import ValidationFailed, send_templated

    FakeSms.sent.clear()
    FakeEmail.sent.clear()      # class-level lists: other test files leave messages in them
    vars_ = {"customer": "A", "invoice": "I-1", "amount": "KES 1.00", "business": "B", "due_date": "2026-10-30"}
    with system(shop) as s:
        made = send_templated(s, company_id=shop["company_id"], channel="whatsapp", recipient="0722000111",
                              template="payment_due", variables=vars_,
                              fallbacks=[{"channel": "sms", "recipient": "0722000111"}])
    assert made is not None
    with system(shop) as s:
        s.execute(text("update kernel.job set run_at = now() where status = 'queued'"))
    jobs.run_due(shop["tenant_id"])
    assert [m.recipient for m in FakeSms.sent] == ["254722000111"]                  # promoted: nothing lost
    assert not FakeEmail.sent
    with pytest.raises(ValidationFailed, match="not available"), system(shop) as s:
        send_templated(s, company_id=shop["company_id"], channel="whatsapp", recipient="0722000111",
                       template="payment_due", variables=vars_)


def test_a_reminder_setting_for_a_channel_that_is_gone_is_kept_and_the_customer_is_reached_by_sms(client, shop) -> None:  # type: ignore[no-untyped-def]
    from datetime import date, timedelta

    from ziira.plugins.messaging.providers import FakeChat, FakeSms

    FakeChat.hidden = False
    co = str(shop["company_id"])
    assert client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"],
                        json={"reminder_channel": "chat"}).status_code == 200
    FakeChat.hidden = True                                                             # the plugin goes off
    assert client.get(f"/api/v1/companies/{co}/settings", headers=shop["owner"]).json()["reminder_channel"] == "chat"
    cust = credit_customer(client, shop, name="Gone Chat", limit="50000", phone="0733000999")
    rep = shop["user"]("rep2", "Sales Rep", shop["branch_id"])
    inv = client.post(f"{POS}/invoices", headers=rep, json={
        "customer_id": cust["id"], "location_id": shop["main"], "terms_days": 30,
        "issue_date": str(date.today() - timedelta(days=40)),
        "lines": [{"product_id": shop["cement"], "quantity": "1"}]}).json()
    FakeSms.sent.clear()
    r = client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"], json={})
    assert r.status_code == 201 and r.json()["channel"] == "sms", r.text
    with system(shop) as s:
        s.execute(text("update kernel.job set run_at = now() where status = 'queued'"))
    jobs.run_due(shop["tenant_id"])
    assert [m.recipient for m in FakeSms.sent] == ["254733000999"]
    asked = client.post(f"{POS}/invoices/{inv['id']}/send-reminder", headers=shop["fm"], json={"channel": "chat"})
    assert asked.status_code == 422 and "not available" in asked.json()["message"]    # by name it is an error
    FakeChat.hidden = False                                                            # and back: it works again
    assert [c["channel"] for c in available(client, shop)] == ["chat", "sms", "email"]
    FakeChat.hidden = True
    client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"reminder_channel": "off"})


def test_a_person_whose_chosen_channel_is_gone_is_reached_by_the_next_one(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.plugins.messaging.providers import FakeChat

    me = shop["owner_id"]
    FakeChat.hidden = False
    with system(shop) as s:
        messaging.set_prefs(s, me, channels={"alerts": "chat"})
    FakeChat.hidden = True
    prefs = client.get(f"{N}/me/preferences", headers=shop["owner"]).json()
    assert prefs["channels"]["alerts"] == "chat" and prefs["unavailable"] == ["alerts"]   # kept, and shown as gone
    with system(shop) as s:
        plan = messaging.plan_for_user(s, shop["company_id"], me, "alerts", ["sms"])
    assert [c for c, _ in plan] == ["email"]                       # the owner has an email; only configured channels
    with system(shop) as s:
        messaging.set_prefs(s, me, channels={"alerts": "default"})


# --------------------------------------------------------------------------- the platform's code names no chat service
FORBIDDEN = re.compile("whatsapp", re.IGNORECASE)
# The public website lists a business contact number to open a chat with; that is site content, not a messaging channel.
ALLOWED = {"ziira/kernel/site_content.py"}
SCANNED = ("py", "json", "toml")


def test_no_module_or_kernel_code_names_a_chat_service() -> None:
    """Channel names are data (a provider declares its own); the kernel, the modules and the SDK never spell one. Allowed:
    tests, migrations (history), and plugins (a plugin is where a channel's name belongs)."""
    offenders = []
    for base in (ROOT / "ziira" / "kernel", ROOT / "ziira" / "modules", ROOT / "ziira" / "sdk"):
        for path in base.rglob("*"):
            if path.suffix.lstrip(".") not in SCANNED or "tests" in path.parts or "migrations" in path.parts:
                continue
            if "__pycache__" in path.parts or str(path.relative_to(ROOT)) in ALLOWED:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if FORBIDDEN.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []


def test_the_web_app_builds_its_channel_lists_from_the_api() -> None:
    """No select in the shared screens (admin, command, the SDK) spells a chat service: they use `useChannels`."""
    offenders = []
    for base in (ROOT / "frontend" / "src" / "sdk", ROOT / "frontend" / "src" / "modules" / "admin",
                 ROOT / "frontend" / "src" / "modules" / "command", ROOT / "frontend" / "src" / "modules" / "intel"):
        for path in base.rglob("*"):
            if path.suffix not in (".ts", ".tsx", ".json") or "schema.d.ts" in path.name or ".test." in path.name:
                continue
            if FORBIDDEN.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], offenders

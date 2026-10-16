"""The channel layer: WhatsApp as a channel with message templates and their approval, the 24-hour window, falling back to
the next way of reaching someone, each person's channel and quiet-hours choices, verified WhatsApp numbers, STOP, and what
happens to a reply from someone the business does not know."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import inbound, jobs, messaging, notifications
from ziira.sdk import InboundMessage

N = "/api/v1/notifications"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Chan Co")
    registry.enable(s["tenant_id"], "messaging")
    co = str(s["company_id"])
    for channel in ("chat", "sms", "email"):
        r = client.put(f"{N}/channels/{channel}", headers=s["owner"], json={
            "company_id": co, "provider": "fake", "secret": {"k": "v"}, "config": {}})
        assert r.status_code == 200, r.text
    with system(s) as session:
        rows = session.execute(text("select id, email from kernel.app_user")).all()
    s["users"] = {r.email.split("@")[0]: r.id for r in rows}
    return s


def fakes():  # type: ignore[no-untyped-def]
    from ziira.plugins.messaging.providers import FakeChat, FakeEmail, FakeSms

    for fake in (FakeChat, FakeSms, FakeEmail):
        fake.sent.clear()
        fake.refuse_next, fake.fail_next = None, 0
    FakeChat.submitted.clear()
    FakeChat.decisions.clear()
    return FakeChat, FakeSms, FakeEmail


def run(shop) -> int:  # type: ignore[no-untyped-def]
    """Send what is queued, and what falling back queues in turn."""
    total = 0
    for _ in range(5):
        with system(shop) as s:
            s.execute(text("update kernel.job set run_at = now() where status = 'queued' "
                           "and job_type = 'kernel.send_notification' and run_at < now() + interval '1 minute'"))
        done = jobs.run_due(shop["tenant_id"])
        total += done
        if done == 0:
            break
    return total


def row(shop, notification_id):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select status, error, provider_ref, channel from kernel.notification where id = :i"),
                         {"i": str(notification_id)}).one()


def reset_templates(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text("update kernel.message_template set status = 'draft', provider_template_id = null, "
                       "rejection_reason = null where company_id = :c"), {"c": str(shop["company_id"])})
        s.execute(text("delete from kernel.contact_window"))


def approve_all(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"])}
    assert client.post(f"{N}/templates/submit", headers=shop["owner"], json=body).status_code == 200
    assert client.post(f"{N}/templates/sync", headers=shop["owner"], json=body).status_code == 200


def customer_reminder(shop, **kw):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return messaging.send_templated(
            s, company_id=shop["company_id"], channel="chat", recipient="0722000111", template="payment_due",
            variables={"customer": "Juma", "invoice": "INV-1", "amount": "KES 800.00", "business": "Chan Co",
                       "due_date": "2026-10-20"}, language=kw.get("language"),
            fallbacks=[{"channel": "sms", "recipient": "0722000111"}], **{k: v for k, v in kw.items() if k != "language"})


# --------------------------------------------------------------------------- templates and their approval
def test_the_business_gets_every_shipped_template_as_a_draft_per_language(client, shop) -> None:  # type: ignore[no-untyped-def]
    reset_templates(shop)
    r = client.get(f"{N}/templates", headers=shop["owner"], params={"company_id": str(shop["company_id"])})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 12 and {x["status"] for x in rows} == {"draft"}                      # 6 templates x en, sw
    assert {x["language"] for x in rows} == {"en", "sw"}
    proposal = next(x for x in rows if x["code"] == "action_proposal" and x["language"] == "sw")
    assert proposal["buttons"] == [["approve", "Idhinisha"], ["reject", "Kataa"], ["why", "Kwa nini?"]]
    assert proposal["variables"] == ["business", "description"]
    assert client.get(f"{N}/templates", headers=shop["cashier"],
                      params={"company_id": str(shop["company_id"])}).status_code == 403


def test_submitting_and_syncing_moves_templates_through_the_approval_states(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, *_ = fakes()
    reset_templates(shop)
    wa.decisions["ziira_urgent_alert"] = "rejected"
    body = {"company_id": str(shop["company_id"])}
    sub = client.post(f"{N}/templates/submit", headers=shop["owner"], json=body)
    assert sub.status_code == 200, sub.text
    assert sub.json()["counts"] == {"submitted": 12, "approved": 0, "failed": 0}
    assert {t["status"] for t in sub.json()["templates"]} == {"submitted"}
    spec = next(s for s in wa.submitted if s.name == "ziira_action_proposal" and s.language == "en")
    assert spec.body == "{{1}}: Ziira suggests: {{2}} It needs your decision." and spec.buttons == (
        "Approve", "Reject", "Why?")
    assert spec.variables == ("business", "description") and spec.category == "utility"
    assert client.post(f"{N}/templates/submit", headers=shop["owner"], json=body).json()["counts"]["submitted"] == 0
    synced = client.post(f"{N}/templates/sync", headers=shop["owner"], json=body).json()
    assert synced["counts"] == {"approved": 10, "rejected": 2, "waiting": 0, "failed": 0}
    states = {(t["code"], t["language"]): t for t in synced["templates"]}
    assert states[("daily_brief", "en")]["status"] == "approved"
    assert states[("urgent_alert", "sw")]["status"] == "rejected"
    assert states[("urgent_alert", "sw")]["rejection_reason"] == "Not allowed by the fake provider"
    wa.decisions.clear()                                                                      # fixed, and submitted again
    assert client.post(f"{N}/templates/submit", headers=shop["owner"], json=body).json()["counts"]["submitted"] == 2
    again = client.post(f"{N}/templates/sync", headers=shop["owner"], json=body).json()
    assert {t["status"] for t in again["templates"]} == {"approved"}


def test_the_recurring_task_picks_up_the_providers_decisions(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, *_ = fakes()
    reset_templates(shop)
    wa.decisions["ziira_daily_brief"] = "rejected"
    body = {"company_id": str(shop["company_id"])}
    assert client.post(f"{N}/templates/submit", headers=shop["owner"], json=body).status_code == 200
    assert jobs.run_periodic(shop["tenant_id"], only="kernel.sync_templates", force=True) == 1
    rows = client.get(f"{N}/templates", headers=shop["owner"], params=body).json()
    assert {(t["code"], t["status"]) for t in rows if t["language"] == "en"} == {
        ("daily_brief", "rejected"), ("urgent_alert", "approved"), ("overdue_reminder", "approved"),
        ("payment_due", "approved"), ("action_proposal", "approved"), ("verification_code", "approved")}


def test_a_template_message_is_refused_until_approved_and_falls_back_to_sms(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    reset_templates(shop)
    first = customer_reminder(shop)
    run(shop)
    assert wa.sent == []                                                                      # nothing went by WhatsApp
    [text_sent] = sms.sent
    assert text_sent.recipient == "254722000111" and "invoice INV-1 of KES 800.00" in text_sent.body
    original = row(shop, first)
    assert original.status == "skipped" and "not approved yet" in original.error and "sent by sms instead" in original.error
    flagged = one(shop, "select count(*) from kernel.exception_item where ref_id = :i", i=str(first))
    assert flagged == 0                                                                       # the customer was reached
    approve_all(client, shop)
    fakes()
    second = customer_reminder(shop, dedupe_key="again")
    run(shop)
    assert row(shop, second).status == "sent"


def test_an_approved_template_is_sent_with_its_parameters_in_the_order_of_its_variables(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    reset_templates(shop)
    approve_all(client, shop)
    customer_reminder(shop, language="sw", dedupe_key="sw-1")
    run(shop)
    [sent] = wa.sent
    assert sent.mode == "template" and sent.template_name == "ziira_payment_due" and sent.template_language == "sw"
    assert sent.template_params == ("Juma", "INV-1", "KES 800.00", "Chan Co", "2026-10-20")
    assert sent.recipient == "254722000111" and sms.sent == []
    assert "Mpendwa Juma" in sent.body                                                        # the same wording, in Swahili


def test_inside_the_24_hour_window_a_free_form_message_needs_no_template(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    reset_templates(shop)                                                                     # nothing approved
    with system(shop) as s:
        messaging.record_inbound_contact(s, shop["company_id"], "chat", "254722000111")
    customer_reminder(shop, dedupe_key="win-1")
    run(shop)
    [sent] = wa.sent
    assert sent.mode == "text" and sent.template_name == "" and sms.sent == []
    with system(shop) as s:                                                                   # 25 hours since they wrote
        s.execute(text("update kernel.contact_window set last_inbound_at = now() - interval '25 hours'"))
    customer_reminder(shop, dedupe_key="win-2")
    run(shop)
    assert len(wa.sent) == 1 and len(sms.sent) == 1                                           # closed: template, unapproved, sms
    with system(shop) as s:
        s.execute(text("update kernel.contact_window set last_inbound_at = now() - interval '23 hours'"))
        assert messaging.window_open(s, shop["company_id"], "chat", "254722000111")
        assert not messaging.window_open(s, shop["company_id"], "chat", "254799999999")   # another person's window
        assert not messaging.window_open(s, shop["company_id"], "sms", "254722000111")        # another channel's


def test_a_message_with_no_template_and_no_window_goes_the_next_way(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    reset_templates(shop)
    with system(shop) as s:
        made = notifications.queue(s, company_id=shop["company_id"], channel="chat", recipient="0722000111",
                                   body="Hello", fallbacks=[{"channel": "sms", "recipient": "0722000111"}])
    run(shop)
    assert wa.sent == [] and [m.body for m in sms.sent] == ["Hello"]
    assert "24-hour window" in row(shop, made).error
    with system(shop) as s:                                                                   # no fallback: skipped and flagged
        alone = notifications.queue(s, company_id=shop["company_id"], channel="chat", recipient="0722000111",
                                    body="Hello again")
    run(shop)
    assert row(shop, alone).status == "skipped"
    assert one(shop, "select count(*) from kernel.exception_item where ref_id = :i", i=str(alone)) == 1


def test_a_refusal_by_the_provider_moves_on_to_the_next_channel_in_order(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, email = fakes()
    reset_templates(shop)
    with system(shop) as s:
        messaging.record_inbound_contact(s, shop["company_id"], "chat", "254733111222")
        made = notifications.queue(
            s, company_id=shop["company_id"], channel="chat", recipient="0733111222", body="Pay please",
            subject="Reminder", fallbacks=[{"channel": "sms", "recipient": "0733111222"},
                                          {"channel": "email", "recipient": "pay@x.test"}])
    wa.refuse_next = "The number is not on WhatsApp"
    sms.refuse_next = "Blocked"
    run(shop)
    run(shop)
    assert wa.sent == [] and sms.sent == [] and [m.body for m in email.sent] == ["Pay please"]
    assert email.sent[0].subject == "Reminder"
    assert row(shop, made).status == "skipped" and "not on WhatsApp" in row(shop, made).error


def test_stop_stops_every_channel_and_the_fallbacks_too(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    with system(shop) as s:
        outcome = inbound.route(s, InboundMessage(shop["company_id"], "chat", "254744555666", "text", " Stop. ", None,
                                                  None, "wamid.stop1"))
    assert outcome == "stopped"
    for word, number in (("ACHA", "254744555667"), ("unsubscribe", "254744555668")):
        with system(shop) as s:
            assert inbound.route(s, InboundMessage(shop["company_id"], "chat", number, "text", word, None, None,
                                                   f"w-{word}")) == "stopped"
    with system(shop) as s:
        assert notifications.is_opted_out(s, shop["company_id"], "chat", "254744555666")
        assert notifications.is_opted_out(s, shop["company_id"], "sms", "254744555666")
        made = messaging.send_templated(
            s, company_id=shop["company_id"], channel="chat", recipient="0744555666", template="payment_due",
            variables={"customer": "A", "invoice": "I", "amount": "KES 1", "business": "B", "due_date": "d"},
            fallbacks=[{"channel": "sms", "recipient": "0744555666"}])
    run(shop)
    assert row(shop, made).status == "skipped" and wa.sent == [] and sms.sent == []
    with system(shop) as s:                                                                   # "stop" inside a sentence is not STOP
        outcome = inbound.route(s, InboundMessage(shop["company_id"], "chat", "254744555999", "text",
                                                  "please do not stop the delivery", None, None, "wamid.x"))
        assert not notifications.is_opted_out(s, shop["company_id"], "sms", "254744555999")
    assert outcome == "unknown"


# --------------------------------------------------------------------------- people, preferences and quiet hours
def test_default_preferences_then_a_person_chooses_a_channel_and_quiet_hours(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{N}/me/preferences", headers=shop["manager"])
    assert r.status_code == 200, r.text
    assert r.json() == {"channels": {"alerts": "default", "brief": "default", "approvals": "default"},
                        "unavailable": [], "can_verify": True, "quiet_enabled": False, "quiet_start": "21:00", "quiet_end": "07:00",
                        "quiet_critical_ok": False, "language": "en", "verified_number": None,
                        "number_verified": False, "number_pending": False}
    put = client.put(f"{N}/me/preferences", headers=shop["manager"], json={
        "channels": {"alerts": "chat", "approvals": "email"}, "quiet_enabled": True, "quiet_start": "22:30",
        "quiet_end": "06:15", "language": "sw"})
    assert put.status_code == 200, put.text
    assert put.json()["channels"] == {"alerts": "chat", "brief": "default", "approvals": "email"}
    assert put.json()["quiet_start"] == "22:30" and put.json()["quiet_end"] == "06:15" and put.json()["language"] == "sw"
    assert client.get(f"{N}/me/preferences", headers=shop["cashier"]).json()["quiet_enabled"] is False   # only mine
    for bad in ({"channels": {"alerts": "pigeon"}}, {"quiet_start": "25:00"}, {"quiet_start": "7pm"}, {"language": "x"}):
        assert client.put(f"{N}/me/preferences", headers=shop["manager"], json=bad).status_code == 422, bad
    same = client.put(f"{N}/me/preferences", headers=shop["manager"], json={"quiet_start": "06:15"})
    assert same.status_code == 422                                                            # start equals end
    reset = client.put(f"{N}/me/preferences", headers=shop["manager"], json={
        "channels": {"alerts": "default"}, "quiet_enabled": False, "language": "en"})
    assert reset.json()["channels"]["alerts"] == "default"


def test_a_staff_member_is_reached_on_their_own_channel_with_fallbacks_in_order(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, email = fakes()
    reset_templates(shop)
    approve_all(client, shop)
    fakes()
    me = shop["users"]["manager"]
    with system(shop) as s:
        s.execute(text("update kernel.app_user set phone = '0755100200' where id = :u"), {"u": str(me)})
        messaging.set_prefs(s, me, channels={"alerts": "sms"})
        plan = messaging.plan_for_user(s, shop["company_id"], me, "alerts", ["email"])
    assert plan == [("sms", "0755100200"), ("email", "manager@chan-co.test")]               # own choice, then the rest
    with system(shop) as s:
        messaging.set_prefs(s, me, channels={"approvals": "default"})
        messaging.set_prefs(s, me, channels={"alerts": "app"})
        assert messaging.plan_for_user(s, shop["company_id"], me, "alerts", ["email"]) == []   # the app only
        messaging.set_prefs(s, me, channels={"alerts": "default"})
        assert messaging.plan_for_user(s, shop["company_id"], me, "alerts", ["email"]) == [
            ("email", "manager@chan-co.test")]                                                 # the business's default
        assert messaging.plan_for_user(s, shop["company_id"], me, "approvals", [],
                                       capability="buttons") == []                            # no verified number


def test_a_message_in_quiet_hours_is_deferred_not_dropped(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, email = fakes()
    me = shop["users"]["owner"]
    nairobi_midnight = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)               # 00:00 in Nairobi (UTC+3)
    nairobi_noon = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)                    # 12:00 in Nairobi
    with system(shop) as s:
        messaging.set_prefs(s, me, quiet_enabled=True)                         # default 21:00 to 07:00
        late = messaging.deliver_at(s, shop["company_id"], me, now=nairobi_midnight)
        midday = messaging.deliver_at(s, shop["company_id"], me, now=nairobi_noon)
        critical = messaging.deliver_at(s, shop["company_id"], me, critical=True, now=nairobi_midnight)
        messaging.set_prefs(s, me, quiet_critical_ok=True)
        passes = messaging.deliver_at(s, shop["company_id"], me, critical=True, now=nairobi_midnight)
        not_critical = messaging.deliver_at(s, shop["company_id"], me, now=nairobi_midnight)
    assert late == datetime(2026, 10, 15, 4, 0, tzinfo=UTC)                    # 07:00 Nairobi, in the company's zone
    assert midday is None and critical == late and passes is None and not_critical == late
    with system(shop) as s:
        messaging.set_prefs(s, me, quiet_critical_ok=False)
        made = messaging.notify_user(s, company_id=shop["company_id"], user_id=me, kind="alerts", body="Cash is short",
                                     subject="Alert", default_channels=["email"], dedupe_key="quiet-1")
        # Pretend it is the middle of the night for this one: the same call with an explicit time.
        deferred = notifications.queue(s, company_id=shop["company_id"], channel="email", recipient="owner@chan-co.test",
                                       body="Later", subject="Later", deliver_at=datetime.now(UTC) + timedelta(hours=6))
    assert made is not None and deferred is not None
    with system(shop) as s:
        due = s.execute(text("select run_at > now() + interval '5 hours' as later from kernel.job "
                             "where dedupe_key = :k"), {"k": f"notify:{deferred}"}).scalar_one()
        assert due is True
        s.execute(text("update kernel.job set run_at = now() where status = 'queued' and dedupe_key = :k"),
                  {"k": f"notify:{made}"})
    jobs.run_due(shop["tenant_id"])
    assert [m.body for m in email.sent] == ["Cash is short"]                  # the deferred one is still waiting
    with system(shop) as s:
        s.execute(text("update kernel.job set run_at = now() where dedupe_key = :k"), {"k": f"notify:{deferred}"})
    jobs.run_due(shop["tenant_id"])
    assert [m.body for m in email.sent] == ["Cash is short", "Later"]         # delivered when its time came
    with system(shop) as s:
        messaging.set_prefs(s, me, quiet_enabled=False)


# --------------------------------------------------------------------------- verified WhatsApp numbers
def code_from(message) -> str:  # type: ignore[no-untyped-def]
    return next(w for w in message.body.replace(".", " ").split() if w.isdigit() and len(w) == 6)


def test_a_number_counts_only_after_its_owner_types_back_the_code(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    reset_templates(shop)                                                                     # no approved template: SMS
    co = str(shop["company_id"])
    start = client.post(f"{N}/me/verified-number", headers=shop["manager"], json={"company_id": co, "phone": "0711 222 333"})
    assert start.status_code == 202, start.text
    assert start.json()["verified_number"] == "25471****333" and start.json()["number_verified"] is False
    assert start.json()["number_pending"] is True and "0711" not in start.text and "254711222333" not in start.text
    run(shop)
    [sent] = sms.sent
    assert sent.recipient == "254711222333" and "Your Ziira verification code" in sent.body
    code = code_from(sent)
    with system(shop) as s:                                                                   # unverified: nobody
        assert messaging.user_for_phone(s, "254711222333") is None
        assert messaging.contact_for(s, shop["users"]["manager"], "chat") is None
    wrong = "000000" if code != "000000" else "111111"
    assert client.post(f"{N}/me/verified-number/verify", headers=shop["manager"], json={"code": wrong}).status_code == 422
    assert client.post(f"{N}/me/verified-number", headers=shop["manager"], json={"company_id": co, "phone": "0711222333"}
                       ).status_code == 422                                                   # too soon for another code
    ok = client.post(f"{N}/me/verified-number/verify", headers=shop["manager"], json={"code": code})
    assert ok.status_code == 200 and ok.json()["number_verified"] is True and ok.json()["number_pending"] is False
    with system(shop) as s:
        assert messaging.user_for_phone(s, "254711222333") == shop["users"]["manager"]
        assert messaging.contact_for(s, shop["users"]["manager"], "chat") == "+254711222333"
    # Someone else cannot take a verified number.
    taken = client.post(f"{N}/me/verified-number", headers=shop["cashier"], json={"company_id": co, "phone": "0711222333"})
    assert taken.status_code == 422 and "already registered" in taken.json()["message"]
    assert client.delete(f"{N}/me/verified-number", headers=shop["manager"]).json()["verified_number"] is None
    with system(shop) as s:
        assert messaging.user_for_phone(s, "254711222333") is None


def test_wrong_codes_are_counted_and_an_old_or_exhausted_code_stops_working(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    co = str(shop["company_id"])
    assert client.post(f"{N}/me/verified-number", headers=shop["cashier"], json={"company_id": co, "phone": "0711444555"}
                       ).status_code == 202
    run(shop)
    code = code_from(sms.sent[0])
    wrong = "123456" if code != "123456" else "654321"
    for _ in range(messaging.CODE_TRIES):
        assert client.post(f"{N}/me/verified-number/verify", headers=shop["cashier"], json={"code": wrong}).status_code == 422
    exhausted = client.post(f"{N}/me/verified-number/verify", headers=shop["cashier"], json={"code": code})
    assert exhausted.status_code == 422 and "Too many" in exhausted.json()["message"]       # even the right one now
    with system(shop) as s:
        s.execute(text("update kernel.user_phone set attempts = 0, code_expires_at = now() - interval '1 minute' "
                       "where user_id = :u"), {"u": str(shop["users"]["cashier"])})
    expired = client.post(f"{N}/me/verified-number/verify", headers=shop["cashier"], json={"code": code})
    assert expired.status_code == 422 and "expired" in expired.json()["message"]


# --------------------------------------------------------------------------- strangers, staff and delivery reports
def test_a_message_from_a_number_nobody_verified_gets_no_reply(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    before = one(shop, "select count(*) from kernel.notification")
    with system(shop) as s:
        outcome = inbound.route(s, InboundMessage(shop["company_id"], "chat", "254788000111", "button", "Approve",
                                                  "approve:00000000-0000-0000-0000-000000000001", None, "wamid.s1"))
    assert outcome == "unknown"
    assert one(shop, "select count(*) from kernel.notification") == before                    # no reply, no hint
    assert one(shop, "select count(*) from kernel.audit_log where action = 'channel.command'") == 0
    # ...but they did write, so a reply to them is now allowed for 24 hours.
    with system(shop) as s:
        assert messaging.window_open(s, shop["company_id"], "chat", "254788000111")


def test_a_verified_user_with_no_handler_for_their_message_gets_a_short_help_text(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, sms, _ = fakes()
    with system(shop) as s:
        s.execute(text("insert into kernel.user_phone (tenant_id, user_id, phone, verified_at) values "
                       "(kernel.current_tenant(), :u, '254700123123', now()) on conflict do nothing"),
                  {"u": str(shop["users"]["boss"])})
        outcome = inbound.route(s, InboundMessage(shop["company_id"], "chat", "254700123123", "other", "", None,
                                                  None, "wamid.help1"))
    assert outcome == "help"
    run(shop)
    [reply] = wa.sent
    assert reply.recipient == "254700123123" and "did not understand" in reply.body and reply.mode == "text"
    audit = one(shop, "select channel from kernel.audit_log where action = 'channel.command' order by id desc limit 1")
    assert audit == "chat"


def test_commands_are_rate_limited_per_person(client, shop) -> None:  # type: ignore[no-untyped-def]
    fakes()
    with system(shop) as s:
        s.execute(text("insert into kernel.user_phone (tenant_id, user_id, phone, verified_at) values "
                       "(kernel.current_tenant(), :u, '254700456456', now()) on conflict do nothing"),
                  {"u": str(shop["users"]["storekeeper"])})
    outcomes = []
    for i in range(inbound.COMMANDS_PER_WINDOW + 3):                  # each message arrives in its own request
        with system(shop) as s:
            outcomes.append(inbound.route(s, InboundMessage(shop["company_id"], "chat", "254700456456", "other", "",
                                                            None, None, f"wamid.rl{i}")))
    assert outcomes[:inbound.COMMANDS_PER_WINDOW] == ["help"] * inbound.COMMANDS_PER_WINDOW
    assert outcomes[inbound.COMMANDS_PER_WINDOW:] == ["limited"] * 3


def test_delivery_reports_only_move_a_message_forward(client, shop) -> None:  # type: ignore[no-untyped-def]
    wa, *_ = fakes()
    with system(shop) as s:
        messaging.record_inbound_contact(s, shop["company_id"], "chat", "254722000111")
        made = notifications.queue(s, company_id=shop["company_id"], channel="chat", recipient="0722000111",
                                   body="Hello", dedupe_key="dr-1")
    run(shop)
    ref = row(shop, made).provider_ref
    assert row(shop, made).status == "sent" and ref.startswith("fake-")

    def report(status, error=None):  # type: ignore[no-untyped-def]
        with system(shop) as s:
            return notifications.record_delivery(s, provider="fake", provider_ref=ref, status=status, error=error)

    assert report("delivered") is True and row(shop, made).status == "delivered"
    assert report("delivered") is False                                                      # a repeat changes nothing
    assert report("sent") is False and row(shop, made).status == "delivered"                 # never backwards
    assert report("read") is True and row(shop, made).status == "read"
    assert report("failed", "late") is False and row(shop, made).status == "read"            # read is final
    assert report("nonsense") is False
    with system(shop) as s:
        assert notifications.record_delivery(s, provider="fake", provider_ref="unknown", status="read") is False
        assert notifications.record_delivery(s, provider="other", provider_ref=ref, status="read") is False


def test_a_failure_reported_by_the_provider_is_flagged_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    fakes()
    with system(shop) as s:
        messaging.record_inbound_contact(s, shop["company_id"], "chat", "254722000222")
        made = notifications.queue(s, company_id=shop["company_id"], channel="chat", recipient="0722000222",
                                   body="Hello", dedupe_key="dr-2")
    run(shop)
    ref = row(shop, made).provider_ref
    with system(shop) as s:
        assert notifications.record_delivery(s, provider="fake", provider_ref=ref, status="failed", error="Not on WhatsApp")
    assert row(shop, made).status == "failed" and row(shop, made).error == "Not on WhatsApp"
    assert one(shop, "select count(*) from kernel.exception_item where ref_id = :i", i=str(made)) == 1


def test_channel_lists_never_show_keys_and_other_businesses_see_nothing_of_ours(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{N}/channels", headers=shop["owner"], params={"company_id": str(shop["company_id"])})
    assert r.status_code == 200 and "secret" not in r.text and {c["channel"] for c in r.json()} == {
        "chat", "sms", "email"}
    assert client.get(f"{N}/templates", headers=shop["owner"], params={"company_id": str(UUID(int=5))}).status_code in (
        403, 404, 422)

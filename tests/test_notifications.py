"""Messages to people outside the system: queued with the change that asked for them, sent in the background through the
business's channel, retried when a gateway is down, and never sent to someone who asked not to be contacted."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.stock_helpers import make_stock_shop, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Notify Co")
    registry.enable(s["tenant_id"], "messaging")
    co = str(s["company_id"])
    for channel in ("sms", "email"):
        r = client.put(f"/api/v1/notifications/channels/{channel}", headers=s["owner"], json={
            "company_id": co, "provider": "fake", "secret": {"api_key": "k"}, "config": {}})
        assert r.status_code == 200, r.text
    return s


def providers():  # type: ignore[no-untyped-def]
    from ziira.plugins.messaging.providers import FakeEmail, FakeSms

    for fake in (FakeSms, FakeEmail):
        fake.sent.clear()
        fake.refuse_next, fake.fail_next = None, 0
    return FakeSms, FakeEmail


def queue(shop, channel="sms", to="0712345678", body="Hello", **kw):  # type: ignore[no-untyped-def]
    from ziira.sdk import send_notification

    with system(shop) as s:
        return send_notification(s, company_id=shop["company_id"], channel=channel, recipient=to, body=body,
                                 subject="Subject" if channel == "email" else None, **kw)


def run(shop) -> int:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs

    with system(shop) as s:
        s.execute(text("update kernel.job set run_at = now() where status = 'queued'"))
    return jobs.run_due(shop["tenant_id"])


def status_of(shop, notification_id):  # type: ignore[no-untyped-def]
    return one(shop, "select status from kernel.notification where id = :i", i=str(notification_id))


def test_a_message_is_sent_in_the_background(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, email = providers()
    first = queue(shop, "sms", "0712 345 678", "Your invoice is due")
    assert status_of(shop, first) == "queued" and sms.sent == []                    # nothing happens in the request
    assert run(shop) >= 1
    assert status_of(shop, first) == "sent" and [m.recipient for m in sms.sent] == ["254712345678"]
    assert one(shop, "select provider from kernel.notification where id = :i", i=str(first)) == "fake"
    assert one(shop, "select provider_ref from kernel.notification where id = :i", i=str(first)).startswith("fake-")
    queue(shop, "email", "Mama@Shop.test", "Statement attached")
    run(shop)
    assert email.sent[0].recipient == "mama@shop.test" and email.sent[0].subject == "Subject"
    run(shop)
    assert len(sms.sent) == 1                                                        # nothing is sent twice


def test_the_same_request_twice_makes_one_message(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, *_ = providers()
    a = queue(shop, "sms", "0712345678", "Reminder", dedupe_key="inv-1-reminder-1")
    b = queue(shop, "sms", "0712345678", "Reminder", dedupe_key="inv-1-reminder-1")
    assert a is not None and b is None
    run(shop)
    assert len(sms.sent) == 1


def test_recipients_and_messages_are_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import ValidationFailed

    for channel, to in (("sms", "12345"), ("sms", "abc"), ("email", "nope"), ("email", "a@b"),
                        ("whatsapp", "0712345678"), ("pigeon", "0712345678")):
        with pytest.raises(ValidationFailed):
            queue(shop, channel, to)
    with pytest.raises(ValidationFailed):
        queue(shop, "sms", "0712345678", "   ")
    with pytest.raises(ValidationFailed):
        queue(shop, "sms", "0712345678", "x" * 1001)
    with pytest.raises(ValidationFailed, match="subject"):
        from ziira.sdk import send_notification

        with system(shop) as s:
            send_notification(s, company_id=shop["company_id"], channel="email", recipient="a@b.test", body="Hi")


def test_someone_who_asked_not_to_be_contacted_is_not_messaged(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, email = providers()
    co = str(shop["company_id"])
    made = client.post("/api/v1/notifications/opt-outs", headers=shop["owner"], json={
        "company_id": co, "recipient": "0733000444", "channel": "sms", "reason": "Asked on the phone"})
    assert made.status_code == 201 and "0733" not in made.text and made.json()["recipient"] == "25473****444"
    skipped = queue(shop, "sms", "0733000444", "Reminder")
    assert status_of(shop, skipped) == "skipped"
    run(shop)
    assert sms.sent == []
    other_channel = queue(shop, "email", "mama@shop.test", "Reminder")                # only SMS was refused
    assert status_of(shop, other_channel) == "queued"
    everywhere = client.post("/api/v1/notifications/opt-outs", headers=shop["owner"], json={
        "company_id": co, "recipient": "stop@shop.test"}).json()
    assert status_of(shop, queue(shop, "email", "stop@shop.test", "Hello")) == "skipped"
    assert client.get("/api/v1/notifications/opt-outs", headers=shop["owner"], params={"company_id": co}).status_code == 200
    assert client.delete(f"/api/v1/notifications/opt-outs/{everywhere['id']}", headers=shop["owner"],
                         params={"company_id": co}).status_code == 204
    assert status_of(shop, queue(shop, "email", "stop@shop.test", "Hello again")) == "queued"
    assert client.delete(f"/api/v1/notifications/opt-outs/{uuid4()}", headers=shop["owner"],
                         params={"company_id": co}).status_code == 404
    bad = client.post("/api/v1/notifications/opt-outs", headers=shop["owner"], json={"company_id": co,
                                                                                      "recipient": "nonsense"})
    assert bad.status_code == 422


def test_a_gateway_that_is_down_is_retried_and_one_that_refuses_is_not(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, *_ = providers()
    sms.fail_next = 2
    n = queue(shop, "sms", "0711000001", "Retry me")
    for _ in range(4):
        run(shop)
    assert status_of(shop, n) == "sent" and one(shop, "select attempts from kernel.notification where id = :i",
                                                 i=str(n)) == 3
    sms.refuse_next = "Number blocked"
    refused = queue(shop, "sms", "0711000002", "Nope")
    run(shop)
    assert status_of(shop, refused) == "failed"
    assert one(shop, "select error from kernel.notification where id = :i", i=str(refused)) == "Number blocked"
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "notification_failed"}).json()
    assert any(i["ref_id"] == str(refused) for i in items)
    run(shop)
    assert len(sms.sent) == 1                                                        # the refused one was not retried


def test_it_gives_up_after_five_tries(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, *_ = providers()
    sms.fail_next = 99
    n = queue(shop, "sms", "0711000003", "Hopeless")
    for _ in range(8):
        run(shop)
    assert status_of(shop, n) == "failed" and one(shop, "select attempts from kernel.notification where id = :i",
                                                   i=str(n)) == 5
    assert "Gave up after 5 tries" in one(shop, "select error from kernel.notification where id = :i", i=str(n))
    sms.fail_next = 0


def test_a_business_without_a_channel_has_its_messages_skipped_and_flagged(client, registry) -> None:  # type: ignore[no-untyped-def]
    other = make_stock_shop(client, registry, "Notify Nothing Co")
    registry.enable(other["tenant_id"], "messaging")
    n = queue(other, "sms", "0712000000", "Anyone there?")
    run(other)
    assert status_of(other, n) == "skipped"
    assert "No sms channel is set up" in one(other, "select error from kernel.notification where id = :i", i=str(n))
    items = client.get("/api/v1/exceptions", headers=other["owner"], params={"kind": "notification_skipped"}).json()
    assert len(items) == 1
    # a provider that is not installed
    client.put("/api/v1/notifications/channels/sms", headers=other["owner"], json={
        "company_id": str(other["company_id"]), "provider": "carrier_pigeon", "secret": {"k": "v"}})
    m = queue(other, "sms", "0712000000", "Again")
    run(other)
    assert "'carrier_pigeon' is not installed" in one(other, "select error from kernel.notification where id = :i",
                                                      i=str(m))


def test_channels_are_set_up_and_shown_without_their_keys(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    listed = client.get("/api/v1/notifications/channels", headers=shop["owner"], params={"company_id": co})
    assert listed.status_code == 200 and {c["channel"] for c in listed.json()} >= {"sms", "email"}
    assert "api_key" not in listed.text and all(c["provider"] == "fake" for c in listed.json() if c["status"] == "active")
    replaced = client.put("/api/v1/notifications/channels/sms", headers=shop["owner"], json={
        "company_id": co, "provider": "fake", "secret": {"api_key": "new"}, "label": "Second"})
    assert replaced.status_code == 200 and replaced.json()["label"] == "Second"
    active = [c for c in client.get("/api/v1/notifications/channels", headers=shop["owner"],
                                    params={"company_id": co}).json() if c["channel"] == "sms" and c["status"] == "active"]
    assert len(active) == 1 and active[0]["label"] == "Second"                      # the old keys stopped being used
    secret = one(shop, "select convert_from(secret_ciphertext, 'UTF8') from kernel.integration_credential "
                       "where status = 'active' and provider = 'sms'")
    assert "new" not in secret
    assert client.put("/api/v1/notifications/channels/sms", headers=shop["owner"], json={
        "company_id": co, "provider": "fake", "secret": {}}).status_code == 422
    assert client.put("/api/v1/notifications/channels/telegram", headers=shop["owner"], json={
        "company_id": co, "provider": "x", "secret": {"a": "b"}}).status_code == 422
    assert client.delete("/api/v1/notifications/channels/email", headers=shop["owner"],
                         params={"company_id": co}).status_code == 204
    assert client.delete("/api/v1/notifications/channels/email", headers=shop["owner"],
                         params={"company_id": co}).status_code == 404


def test_the_record_and_a_test_message(client, shop) -> None:  # type: ignore[no-untyped-def]
    sms, *_ = providers()
    co = str(shop["company_id"])
    sent = client.post("/api/v1/notifications/test", headers=shop["owner"], json={
        "company_id": co, "channel": "sms", "recipient": "0799888777"})
    assert sent.status_code == 201 and sent.json()["status"] == "queued" and "0799" not in sent.text
    run(shop)
    assert any("test message" in m.body for m in sms.sent)
    history = client.get("/api/v1/notifications", headers=shop["owner"], params={
        "company_id": co, "status": "sent", "channel": "sms", "ref_type": "test"}).json()
    assert history and all(h["status"] == "sent" and "0799" not in h["recipient"] for h in history)
    assert client.get("/api/v1/notifications", headers=shop["owner"], params={"company_id": co, "status": "bogus"}
                      ).status_code == 422
    assert client.post("/api/v1/notifications/test", headers=shop["owner"], json={
        "company_id": co, "channel": "sms", "recipient": "12"}).status_code == 422
    one_row = client.get("/api/v1/notifications", headers=shop["owner"], params={"company_id": co, "limit": 1}).json()
    assert len(one_row) == 1


def test_who_may_manage_messaging(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    for who in ("cashier", "storekeeper", "manager"):
        assert client.get("/api/v1/notifications", headers=shop[who], params={"company_id": co}).status_code == 403
        assert client.put("/api/v1/notifications/channels/sms", headers=shop[who], json={
            "company_id": co, "provider": "fake", "secret": {"k": "v"}}).status_code == 403
        assert client.post("/api/v1/notifications/test", headers=shop[who], json={
            "company_id": co, "channel": "sms", "recipient": "0712345678"}).status_code == 403
    assert client.get("/api/v1/notifications", headers=shop["owner"], params={"company_id": str(uuid4())}
                      ).status_code == 422


def test_the_record_cannot_be_rewritten(client, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import DBAPIError

    n = queue(shop, "sms", "0711000009", "Original text")
    for sql in ("update kernel.notification set body = 'Changed' where id = :i",
                "update kernel.notification set recipient = '254700000000' where id = :i",
                "delete from kernel.notification where id = :i"):
        with pytest.raises(DBAPIError), system(shop) as s:
            s.execute(text(sql), {"i": str(n)})
    assert timedelta(0) is not None

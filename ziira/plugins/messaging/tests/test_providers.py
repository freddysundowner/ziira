"""The messaging providers against pretend gateways: request shapes, success, refusals and outages."""

import smtplib
from typing import Any
from uuid import uuid4

import httpx
import pytest

from ziira.plugins.messaging.providers import AfricasTalkingSms, FakeSms, SmtpEmail, WhatsAppCloud
from ziira.sdk import Outgoing

MESSAGE = Outgoing(uuid4(), uuid4(), "254712345678", "Invoice due", "Your invoice INV-1 of KES 116 is due.")


def gateway(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def sms(handler: Any, **config: Any):  # type: ignore[no-untyped-def]
    AfricasTalkingSms.client_factory = staticmethod(lambda: gateway(handler))
    return AfricasTalkingSms().send(MESSAGE, {"api_key": "KEY"}, {"username": "myshop", **config})


# --------------------------------------------------------------------------- Africa's Talking
def test_sms_is_sent_as_the_gateway_expects() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"SMSMessageData": {"Message": "Sent to 1/1", "Recipients": [
            {"statusCode": 101, "number": "+254712345678", "status": "Success", "messageId": "ATXid_1"}]}})

    result = sms(handler, sender_id="MYSHOP")
    assert result.accepted and result.provider_ref == "ATXid_1"
    request = seen[0]
    assert str(request.url) == "https://api.africastalking.com/version1/messaging"
    assert request.headers["apiKey"] == "KEY" and request.headers["accept"] == "application/json"
    body = request.content.decode()
    assert "username=myshop" in body and "to=%2B254712345678" in body and "from=MYSHOP" in body
    assert "invoice+INV-1" in body or "invoice%20INV-1" in body
    sms(handler, sandbox=True)
    assert str(seen[1].url).startswith("https://api.sandbox.africastalking.com/")


def test_sms_refusals_are_permanent_and_outages_are_retried() -> None:
    refused = sms(lambda r: httpx.Response(201, json={"SMSMessageData": {"Recipients": [
        {"statusCode": 403, "status": "InvalidPhoneNumber", "number": "+254"}]}}))
    assert not refused.accepted and refused.permanent_failure and "InvalidPhoneNumber" in refused.message
    bad_key = sms(lambda r: httpx.Response(401, text="The supplied authentication is invalid"))
    assert not bad_key.accepted and bad_key.permanent_failure and "refused the API key" in bad_key.message
    garbage = sms(lambda r: httpx.Response(200, text="<html>not json</html>"))
    assert not garbage.accepted and garbage.permanent_failure
    for status in (500, 503, 429):
        with pytest.raises(httpx.HTTPStatusError):
            sms(lambda r, s=status: httpx.Response(s, text="busy"))

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(httpx.ConnectError):
        sms(down)


# --------------------------------------------------------------------------- WhatsApp
def whatsapp(handler: Any, **config: Any):  # type: ignore[no-untyped-def]
    WhatsAppCloud.client_factory = staticmethod(lambda: gateway(handler))
    return WhatsAppCloud().send(MESSAGE, {"access_token": "TOK"}, {"phone_number_id": "1055", **config})


def test_whatsapp_text_and_template_messages() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.ABC"}]})

    plain = whatsapp(handler)
    assert plain.accepted and plain.provider_ref == "wamid.ABC"
    assert str(seen[0].url) == "https://graph.facebook.com/v20.0/1055/messages"
    assert seen[0].headers["authorization"] == "Bearer TOK"
    import json

    body = json.loads(seen[0].content)
    assert body["type"] == "text" and body["to"] == "254712345678" and body["text"]["body"].startswith("Your invoice")
    templated = whatsapp(handler, template="invoice_reminder", language="en_GB", api_version="v21.0")
    assert templated.accepted
    sent = json.loads(seen[1].content)
    assert sent["type"] == "template" and sent["template"]["name"] == "invoice_reminder"
    assert sent["template"]["language"] == {"code": "en_GB"}
    assert sent["template"]["components"][0]["parameters"][0]["text"].startswith("Your invoice")
    assert "/v21.0/" in str(seen[1].url)


def test_whatsapp_errors() -> None:
    refused = whatsapp(lambda r: httpx.Response(400, json={"error": {"message": "Re-engagement message",
                                                                     "code": 131047}}))
    assert not refused.accepted and refused.permanent_failure and "Re-engagement" in refused.message
    with pytest.raises(httpx.HTTPStatusError):
        whatsapp(lambda r: httpx.Response(503, text="down"))
    odd = whatsapp(lambda r: httpx.Response(200, text="ok"))
    assert not odd.accepted


# --------------------------------------------------------------------------- SMTP
class FakeSmtp:
    log: list[str] = []
    fail_login: bool = False
    refuse_to: bool = False

    def __init__(self, host: str, port: int, timeout: int = 0, context: Any = None) -> None:
        self.log.append(f"connect {host}:{port}")

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *args: Any) -> None:
        self.log.append("quit")

    def starttls(self, context: Any = None) -> None:
        self.log.append("starttls")

    def login(self, user: str, password: str) -> None:
        if self.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.log.append(f"login {user}")

    def send_message(self, message: Any) -> None:
        if self.refuse_to:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})
        self.log.append(f"send {message['To']} | {message['Subject']} | {message['From']}")


@pytest.fixture()
def smtp():  # type: ignore[no-untyped-def]
    FakeSmtp.log, FakeSmtp.fail_login, FakeSmtp.refuse_to = [], False, False
    SmtpEmail.smtp_factory = staticmethod(FakeSmtp)
    SmtpEmail.smtp_ssl_factory = staticmethod(FakeSmtp)
    yield FakeSmtp


def test_email_through_smtp(smtp) -> None:  # type: ignore[no-untyped-def]
    mail = Outgoing(uuid4(), uuid4(), "mama@shop.test", "Statement", "Please find your statement.")
    secret = {"host": "smtp.example.test", "port": 587, "username": "billing@myshop.test", "password": "pw"}
    result = SmtpEmail().send(mail, secret, {"from_address": "billing@myshop.test", "from_name": "My Shop"})
    assert result.accepted
    assert smtp.log == ["connect smtp.example.test:587", "starttls", "login billing@myshop.test",
                        "send mama@shop.test | Statement | My Shop <billing@myshop.test>", "quit"]
    smtp.log.clear()
    SmtpEmail().send(mail, {**secret, "port": 465}, {})
    assert "starttls" not in smtp.log and smtp.log[0] == "connect smtp.example.test:465"
    assert "send mama@shop.test | Statement | billing@myshop.test" in smtp.log


def test_email_failures(smtp) -> None:  # type: ignore[no-untyped-def]
    mail = Outgoing(uuid4(), uuid4(), "mama@shop.test", "Statement", "Hello")
    secret = {"host": "smtp.example.test", "username": "u", "password": "p"}
    smtp.fail_login = True
    bad = SmtpEmail().send(mail, secret, {"from_address": "a@b.test"})
    assert not bad.accepted and bad.permanent_failure and "username or password" in bad.message
    smtp.fail_login, smtp.refuse_to = False, True
    gone = SmtpEmail().send(mail, secret, {"from_address": "a@b.test"})
    assert not gone.accepted and gone.permanent_failure and "refused the address" in gone.message
    nobody = SmtpEmail().send(mail, {"host": "h"}, {})
    assert not nobody.accepted and "no sender" in nobody.message


def test_the_fake_channel_records_and_can_be_scripted() -> None:
    FakeSms.sent.clear()
    FakeSms.refuse_next, FakeSms.fail_next = None, 0
    assert FakeSms().send(MESSAGE, {}, {}).accepted and FakeSms.sent == [MESSAGE]
    FakeSms.refuse_next = "Blocked number"
    refused = FakeSms().send(MESSAGE, {}, {})
    assert not refused.accepted and refused.permanent_failure and FakeSms.refuse_next is None
    FakeSms.fail_next = 1
    with pytest.raises(ConnectionError):
        FakeSms().send(MESSAGE, {}, {})
    assert FakeSms().send(MESSAGE, {}, {}).accepted
    FakeSms.sent.clear()

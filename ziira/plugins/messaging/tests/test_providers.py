"""The messaging providers against pretend gateways: request shapes, success, refusals and outages."""

import smtplib
from typing import Any
from uuid import uuid4

import httpx
import pytest

from ziira.plugins.messaging.providers import (
    AfricasTalkingSms,
    BlessedTextsSms,
    BrevoEmail,
    FakeSms,
    ResendEmail,
    SendGridEmail,
    SmtpEmail,
)
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


# --------------------------------------------------------------------------- BlessedTexts
def blessed(handler: Any, **config: Any):  # type: ignore[no-untyped-def]
    BlessedTextsSms.client_factory = staticmethod(lambda: gateway(handler))
    return BlessedTextsSms().send(MESSAGE, {"api_key": "KEY"}, {"sender_id": "23107", **config})


def test_blessedtexts_sms_is_sent_as_documented() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"status_code": "1000", "status_desc": "Success",
                                          "message_id": "6496cc3d541ef109508440", "phone": "254712345678",
                                          "message_cost": "0.5"}])

    result = blessed(handler)
    assert result.accepted and result.provider_ref == "6496cc3d541ef109508440"
    request = seen[0]
    assert str(request.url) == "https://sms.blessedtexts.com/api/sms/v1/sendsms"
    assert request.method == "POST" and request.headers["accept"] == "application/json"
    import json
    assert json.loads(request.content) == {"api_key": "KEY", "sender_id": "23107", "message": MESSAGE.body,
                                           "phone": "254712345678"}


def test_blessedtexts_refusals_are_permanent_and_outages_are_retried() -> None:
    refused = blessed(lambda r: httpx.Response(200, json=[{"status_code": "1001", "status_desc": "Invalid sender"}]))
    assert not refused.accepted and refused.permanent_failure and "Invalid sender" in refused.message
    single = blessed(lambda r: httpx.Response(200, json={"status_code": "1002", "status_desc": "No credit"}))
    assert not single.accepted and "No credit" in single.message
    garbage = blessed(lambda r: httpx.Response(200, text="<html>no</html>"))
    assert not garbage.accepted and garbage.permanent_failure
    with pytest.raises(httpx.HTTPStatusError):
        blessed(lambda r: httpx.Response(503, text="down"))


# --------------------------------------------------------------------------- email APIs
MAIL = Outgoing(uuid4(), uuid4(), "mama@shop.test", "Statement", "Please find your statement.")


def api_mail(provider: Any, handler: Any, config: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
    provider.client_factory = staticmethod(lambda: gateway(handler))
    return provider().send(MAIL, {"api_key": "KEY"}, {"from_address": "billing@myshop.test", "from_name": "My Shop",
                                                      **(config or {})})


def test_brevo_resend_and_sendgrid_requests() -> None:
    import json
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = request
        if "brevo" in request.url.host:
            return httpx.Response(201, json={"messageId": "<brevo-1@x>"})
        if "resend" in request.url.host:
            return httpx.Response(200, json={"id": "resend-1"})
        return httpx.Response(202, headers={"X-Message-Id": "sg-1"})

    refs = [api_mail(p, handler).provider_ref for p in (BrevoEmail, ResendEmail, SendGridEmail)]
    assert refs == ["<brevo-1@x>", "resend-1", "sg-1"]
    brevo = seen["api.brevo.com"]
    assert str(brevo.url) == "https://api.brevo.com/v3/smtp/email" and brevo.headers["api-key"] == "KEY"
    assert json.loads(brevo.content) == {"sender": {"email": "billing@myshop.test", "name": "My Shop"},
                                         "to": [{"email": "mama@shop.test"}], "subject": "Statement",
                                         "textContent": "Please find your statement."}
    resend = seen["api.resend.com"]
    assert str(resend.url) == "https://api.resend.com/emails" and resend.headers["authorization"] == "Bearer KEY"
    assert json.loads(resend.content) == {"from": "My Shop <billing@myshop.test>", "to": ["mama@shop.test"],
                                          "subject": "Statement", "text": "Please find your statement."}
    grid = seen["api.sendgrid.com"]
    assert str(grid.url) == "https://api.sendgrid.com/v3/mail/send" and grid.headers["authorization"] == "Bearer KEY"
    assert json.loads(grid.content) == {
        "personalizations": [{"to": [{"email": "mama@shop.test"}]}],
        "from": {"email": "billing@myshop.test", "name": "My Shop"}, "subject": "Statement",
        "content": [{"type": "text/plain", "value": "Please find your statement."}]}
    plain = api_mail(ResendEmail, handler, {"from_name": None})
    assert plain.accepted and json.loads(seen["api.resend.com"].content)["from"] == "billing@myshop.test"


@pytest.mark.parametrize("provider", [BrevoEmail, ResendEmail, SendGridEmail])
def test_email_api_failures(provider: Any) -> None:
    bad_key = api_mail(provider, lambda r: httpx.Response(401, json={"message": "Invalid key"}))
    assert not bad_key.accepted and bad_key.permanent_failure and "refused the API key" in bad_key.message
    refused = api_mail(provider, lambda r: httpx.Response(400, json={"message": "Sender not verified"}))
    assert not refused.accepted and refused.permanent_failure and "Sender not verified" in refused.message
    odd = api_mail(provider, lambda r: httpx.Response(422, text="<html>"))
    assert not odd.accepted and odd.permanent_failure
    nobody = api_mail(provider, lambda r: httpx.Response(200), {"from_address": ""})
    assert not nobody.accepted and "no sender" in nobody.message
    with pytest.raises(httpx.HTTPStatusError):
        api_mail(provider, lambda r: httpx.Response(503, text="down"))
    with pytest.raises(httpx.HTTPStatusError):
        api_mail(provider, lambda r: httpx.Response(429, text="slow down"))

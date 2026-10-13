"""Ways of sending a message: SMTP email, Africa's Talking SMS and the WhatsApp Cloud API (and a fake one for tests).

**The SMS and WhatsApp request formats were written from the gateways' public documentation and have not been run
against the real services.** Try them with the gateway's sandbox or a test number before relying on them; the same goes
for the details of their error replies, which decide whether a failure is retried.

A provider is chosen by the business's channel credential: its config names the provider, for example
{"provider": "africastalking"}, and its secret holds the keys.
"""

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, ClassVar

import httpx

from ziira.sdk import NotificationChannel, Outgoing, SendResult, ValidationFailed, is_production

TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class SmtpEmail(NotificationChannel):
    """Email through any SMTP server. Secret: {host, port, username, password}. Config: {from_address, from_name?}."""

    channel = "email"
    name = "smtp"
    smtp_factory: ClassVar[Any] = staticmethod(smtplib.SMTP)
    smtp_ssl_factory: ClassVar[Any] = staticmethod(smtplib.SMTP_SSL)

    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        sender = str(config.get("from_address") or secret.get("username") or "")
        if not sender:
            return SendResult(False, message="The email channel has no sender address", permanent_failure=True)
        email = EmailMessage()
        email["From"] = f"{config['from_name']} <{sender}>" if config.get("from_name") else sender
        email["To"] = message.recipient
        email["Subject"] = message.subject or "Message"
        email.set_content(message.body)
        host, port = str(secret["host"]), int(secret.get("port", 587))
        try:
            if port == 465:
                client = self.smtp_ssl_factory(host, port, timeout=20, context=ssl.create_default_context())
            else:
                client = self.smtp_factory(host, port, timeout=20)
            with client:
                if port != 465 and config.get("starttls", True):
                    client.starttls(context=ssl.create_default_context())
                if secret.get("username"):
                    client.login(str(secret["username"]), str(secret.get("password", "")))
                client.send_message(email)
        except smtplib.SMTPAuthenticationError:
            return SendResult(False, message="The email server refused the username or password",
                              permanent_failure=True)
        except smtplib.SMTPRecipientsRefused:
            return SendResult(False, message="The email server refused the address", permanent_failure=True)
        except smtplib.SMTPSenderRefused:
            return SendResult(False, message="The email server refused the sender address", permanent_failure=True)
        return SendResult(True, provider_ref=None)


class _HttpChannel(NotificationChannel):
    """Shared by the gateways that are called over HTTPS; `client_factory` lets tests replace the network."""

    client_factory: ClassVar[Any] = staticmethod(lambda: httpx.Client(timeout=TIMEOUT))

    @staticmethod
    def server_failed(response: httpx.Response) -> bool:
        return response.status_code >= 500 or response.status_code == 429

    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:  # pragma: no cover
        raise NotImplementedError


class AfricasTalkingSms(_HttpChannel):
    """SMS through Africa's Talking. Secret: {api_key}. Config: {username, sender_id?, sandbox?}."""

    channel = "sms"
    name = "africastalking"

    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        sandbox = bool(config.get("sandbox"))
        url = ("https://api.sandbox.africastalking.com" if sandbox else "https://api.africastalking.com") \
            + "/version1/messaging"
        data = {"username": config.get("username") or ("sandbox" if sandbox else ""), "to": f"+{message.recipient}",
                "message": message.body}
        if config.get("sender_id"):
            data["from"] = str(config["sender_id"])
        with self.client_factory() as client:
            response = client.post(url, data=data, headers={"apiKey": str(secret["api_key"]),
                                                            "Accept": "application/json"})
        if self.server_failed(response):
            response.raise_for_status()
        if response.status_code in (401, 403):
            return SendResult(False, message="Africa's Talking refused the API key or username", permanent_failure=True)
        try:
            recipients = response.json()["SMSMessageData"]["Recipients"]
            first = recipients[0]
        except (ValueError, KeyError, IndexError):
            return SendResult(False, message=f"Unexpected reply from Africa's Talking ({response.status_code})",
                              permanent_failure=response.status_code < 500)
        if str(first.get("status")) == "Success" or first.get("statusCode") in (100, 101, 102):
            return SendResult(True, provider_ref=first.get("messageId"))
        return SendResult(False, message=f"Africa's Talking: {first.get('status', 'not sent')}",
                          permanent_failure=True)


class BlessedTextsSms(_HttpChannel):
    """SMS through BlessedTexts. Secret: {api_key}. Config: {sender_id}. One JSON POST per message; a reply is a list
    with one entry per phone, and status_code "1000" means accepted."""

    channel = "sms"
    name = "blessedtexts"
    url = "https://sms.blessedtexts.com/api/sms/v1/sendsms"

    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        payload = {"api_key": str(secret["api_key"]), "sender_id": str(config.get("sender_id", "")),
                   "message": message.body, "phone": message.recipient}
        with self.client_factory() as client:
            response = client.post(self.url, json=payload, headers={"Accept": "application/json"})
        if self.server_failed(response):
            response.raise_for_status()
        try:
            body = response.json()
            first = body[0] if isinstance(body, list) else body
            code, description = str(first["status_code"]), str(first.get("status_desc", "not sent"))
        except (ValueError, KeyError, IndexError, TypeError):
            return SendResult(False, message=f"Unexpected reply from BlessedTexts ({response.status_code})",
                              permanent_failure=response.status_code < 500)
        if code == "1000":
            return SendResult(True, provider_ref=first.get("message_id"))
        return SendResult(False, message=f"BlessedTexts: {description}"[:300], permanent_failure=True)


class WhatsAppCloud(_HttpChannel):
    """WhatsApp through the Cloud API. Secret: {access_token}. Config: {phone_number_id, api_version?, template?,
    language?}. A business may start a conversation only with an approved *template*; give its name in the config and
    the message text is sent as the template's single body parameter. Without a template the message is sent as plain
    text, which WhatsApp delivers only to someone who messaged the business in the last 24 hours."""

    channel = "whatsapp"
    name = "whatsapp_cloud"

    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        version = str(config.get("api_version") or "v20.0")
        url = f"https://graph.facebook.com/{version}/{config['phone_number_id']}/messages"
        payload: dict[str, Any] = {"messaging_product": "whatsapp", "to": message.recipient}
        if config.get("template"):
            payload.update(type="template", template={
                "name": config["template"], "language": {"code": config.get("language") or "en"},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": message.body[:1000]}]}]})
        else:
            payload.update(type="text", text={"body": message.body})
        with self.client_factory() as client:
            response = client.post(url, json=payload, headers={"Authorization": f"Bearer {secret['access_token']}"})
        if self.server_failed(response):
            response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            return SendResult(False, message=f"Unexpected reply from WhatsApp ({response.status_code})",
                              permanent_failure=True)
        if response.status_code < 300 and body.get("messages"):
            return SendResult(True, provider_ref=body["messages"][0].get("id"))
        error = body.get("error", {})
        return SendResult(False, message=f"WhatsApp: {error.get('message', 'not sent')}"[:300],
                          permanent_failure=True)


class _Fake(NotificationChannel):
    """For development and tests: records what it was asked to send and says yes (or what the test scripted)."""

    sent: ClassVar[list[Outgoing]]
    refuse_next: ClassVar[str | None] = None
    fail_next: ClassVar[int] = 0              # raise this many times, as if the gateway were down

    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        if is_production():
            raise ValidationFailed("The fake messaging channel is for development only")
        cls = type(self)
        if cls.fail_next > 0:
            cls.fail_next -= 1
            raise ConnectionError("The gateway is down")
        if cls.refuse_next is not None:
            reason, cls.refuse_next = cls.refuse_next, None
            return SendResult(False, message=reason, permanent_failure=True)
        cls.sent.append(message)
        return SendResult(True, provider_ref=f"fake-{len(cls.sent)}")


class FakeEmail(_Fake):
    channel, name, sent = "email", "fake", []                  # noqa: RUF012


class FakeSms(_Fake):
    channel, name, sent = "sms", "fake", []                    # noqa: RUF012


class FakeWhatsApp(_Fake):
    channel, name, sent = "whatsapp", "fake", []               # noqa: RUF012

"""Ways of sending a message: email (SMTP, Brevo, Resend, SendGrid), SMS (BlessedTexts, Africa's Talking), and a fake
one for tests.

**The HTTP request formats were written from the gateways' public documentation and have not been run
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

from ziira.sdk import (
    NotificationChannel,
    Outgoing,
    SendResult,
    TemplateSpec,
    TemplateState,
    ValidationFailed,
    is_production,
)

TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class SmtpEmail(NotificationChannel):
    """Email through any SMTP server. Secret: {host, port, username, password}. Config: {from_address, from_name?,
    reply_to?, security?}. `security` is "starttls", "ssl" or "none"; without it port 465 means SSL, anything else
    STARTTLS (unless `starttls` is false)."""

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
        if config.get("reply_to"):
            email["Reply-To"] = str(config["reply_to"])
        email.set_content(message.body)
        host, port = str(secret["host"]), int(secret.get("port", 587))
        try:
            security = str(config.get("security") or ("ssl" if port == 465 else
                                                      "starttls" if config.get("starttls", True) else "none"))
            if security == "ssl":
                client = self.smtp_ssl_factory(host, port, timeout=20, context=ssl.create_default_context())
            else:
                client = self.smtp_factory(host, port, timeout=20)
            with client:
                if security == "starttls":
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


class _ApiEmail(_HttpChannel):
    """Email through a provider's HTTPS API. Secret: {api_key}. Config: {from_address, from_name?}. A subclass says
    where to post, how to authenticate and how to read the reply; refusals (bad key, unverified sender, bad address) are
    permanent and outages are retried."""

    channel = "email"
    label = "The email provider"
    url = ""

    def request(self, message: Outgoing, sender: str, name: str | None, key: str) -> dict[str, Any]:
        """The JSON body and headers: {"json": ..., "headers": ...}."""
        raise NotImplementedError

    def add_reply_to(self, body: dict[str, Any], address: str) -> None:
        """Put the reply-to address into the request body (the providers each spell it differently)."""
        body["reply_to"] = address

    def accepted(self, response: httpx.Response) -> SendResult | None:
        """A SendResult when the reply says the mail was taken, else None."""
        raise NotImplementedError

    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        sender = str(config.get("from_address") or "")
        if not sender:
            return SendResult(False, message="The email channel has no sender address", permanent_failure=True)
        call = self.request(message, sender, config.get("from_name"), str(secret["api_key"]))
        if config.get("reply_to"):
            self.add_reply_to(call["json"], str(config["reply_to"]))
        with self.client_factory() as client:
            response = client.post(self.url, **call)
        if self.server_failed(response):
            response.raise_for_status()
        taken = self.accepted(response)
        if taken is not None:
            return taken
        if response.status_code in (401, 403):
            return SendResult(False, message=f"{self.label} refused the API key", permanent_failure=True)
        try:
            body = response.json()
            detail = body.get("message") or body.get("error") or body.get("errors", [{}])[0].get("message")
        except (ValueError, AttributeError, IndexError, TypeError):
            detail = None
        return SendResult(False, message=f"{self.label}: {detail or f'not sent ({response.status_code})'}"[:300],
                          permanent_failure=True)


class BrevoEmail(_ApiEmail):
    """Email through Brevo's transactional API. The sender address must be a verified sender in Brevo."""

    name = "brevo"
    label = "Brevo"
    url = "https://api.brevo.com/v3/smtp/email"

    def add_reply_to(self, body: dict[str, Any], address: str) -> None:
        body["replyTo"] = {"email": address}

    def request(self, message: Outgoing, sender: str, name: str | None, key: str) -> dict[str, Any]:
        who: dict[str, str] = {"email": sender, **({"name": name} if name else {})}
        return {"headers": {"api-key": key, "Accept": "application/json"}, "json": {
            "sender": who, "to": [{"email": message.recipient}], "subject": message.subject or "Message",
            "textContent": message.body}}

    def accepted(self, response: httpx.Response) -> SendResult | None:
        if response.status_code in (200, 201):
            try:
                return SendResult(True, provider_ref=response.json().get("messageId"))
            except ValueError:
                return SendResult(True)
        return None


class ResendEmail(_ApiEmail):
    """Email through Resend. The sender's domain must be verified in Resend."""

    name = "resend"
    label = "Resend"
    url = "https://api.resend.com/emails"

    def request(self, message: Outgoing, sender: str, name: str | None, key: str) -> dict[str, Any]:
        return {"headers": {"Authorization": f"Bearer {key}"}, "json": {
            "from": f"{name} <{sender}>" if name else sender, "to": [message.recipient],
            "subject": message.subject or "Message", "text": message.body}}

    def accepted(self, response: httpx.Response) -> SendResult | None:
        if response.status_code == 200:
            try:
                return SendResult(True, provider_ref=response.json().get("id"))
            except ValueError:
                return SendResult(True)
        return None


class SendGridEmail(_ApiEmail):
    """Email through SendGrid. The sender must be a verified single sender or on an authenticated domain."""

    name = "sendgrid"
    label = "SendGrid"
    url = "https://api.sendgrid.com/v3/mail/send"

    def add_reply_to(self, body: dict[str, Any], address: str) -> None:
        body["reply_to"] = {"email": address}

    def request(self, message: Outgoing, sender: str, name: str | None, key: str) -> dict[str, Any]:
        who: dict[str, str] = {"email": sender, **({"name": name} if name else {})}
        return {"headers": {"Authorization": f"Bearer {key}"}, "json": {
            "personalizations": [{"to": [{"email": message.recipient}]}], "from": who,
            "subject": message.subject or "Message", "content": [{"type": "text/plain", "value": message.body}]}}

    def accepted(self, response: httpx.Response) -> SendResult | None:
        if response.status_code == 202:
            return SendResult(True, provider_ref=response.headers.get("X-Message-Id"))
        return None


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


class _Fake(NotificationChannel):
    """For development and tests: records what it was asked to send and says yes (or what the test scripted)."""

    sent: ClassVar[list[Outgoing]]
    development_only = True                   # never offered in production
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



class FakeChat(_Fake):
    """A chat channel for development and tests (conversation window, templates, reply buttons, replies): a submitted
    template is 'submitted' until the provider 'decides' (`decisions[name]` = approved or rejected; approved by
    default)."""

    channel, name, sent = "chat", "fake", []                   # noqa: RUF012
    channel_label = "Chat (test)"
    supports_templates = True
    supports_buttons = True
    supports_inbound = True
    window_hours = 24
    submitted: ClassVar[list[TemplateSpec]] = []
    decisions: ClassVar[dict[str, str]] = {}

    def submit_template(self, spec: TemplateSpec, secret: dict[str, Any], config: dict[str, Any]) -> TemplateState:
        type(self).submitted.append(spec)
        return TemplateState("submitted", f"fake-{spec.name}-{spec.language}")

    def template_state(self, spec: TemplateSpec, provider_template_id: str | None, secret: dict[str, Any],
                       config: dict[str, Any]) -> TemplateState:
        decision = type(self).decisions.get(spec.name, "approved")
        return TemplateState(decision, provider_template_id, "Not allowed by the fake provider"
                             if decision == "rejected" else "")

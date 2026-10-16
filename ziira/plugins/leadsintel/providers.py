"""WhatsApp through Lead Intel, as a provider for the kernel's notification channels.

The kernel decides *what* to send (free text, reply buttons, or an approved template, by the 24-hour window) and hands
the provider an `Outgoing` that says so; the provider turns it into Lead Intel's request and reads the answer:

* Lead Intel replies 202 `{messageId, status: "accepted"}`: accepted, not delivered. Delivery arrives later on the
  webhook (`webhook.py`) and moves the message to delivered/read/failed.
* The `Idempotency-Key` is made from the notification's id and the mode, so a retry after a timeout can never send
  twice,
  and the same key is never reused with different content.
* Errors: an outage, a rate limit or a 5xx is raised (the kernel retries later); a refusal that will not pass (wrong
  key,
  connection gone or inactive, a message Lead Intel will not take) is returned as a permanent failure so the kernel
  tries the person's next channel. 502 `send_failed` on a free-form message usually means the 24-hour window is closed.

The credentials: `secret = {"platform_key", "webhook_secret"}`, `config = {"provider": "leadsintel", "tenant_ref",
"connection_id"}`. They are read here only to make the call and are never returned or logged.
"""

import logging
from typing import Any

from ziira.plugins.leadsintel import unverified
from ziira.plugins.leadsintel.client import LeadIntelClient, LeadIntelError
from ziira.sdk import NotificationChannel, Outgoing, SendResult, TemplateSpec, TemplateState

log = logging.getLogger("ziira.leadsintel")
TEXT_MAX = 4000
BUTTON_BODY_MAX = 1024
BUTTON_TITLE_MAX = 20
BUTTONS_MAX = 3
PERMANENT = {
    400: "Lead Intel refused the message",
    401: "Lead Intel refused the platform key: check it in Settings",
    403: "Lead Intel refused the platform key: check it in Settings",
    404: "The Lead Intel connection was not found: reconnect it in Settings",
    409: "The Lead Intel connection is not active (or the message was already sent differently)",
}


def client_for(secret: dict[str, Any], config: dict[str, Any]) -> LeadIntelClient:
    key = str(secret.get("platform_key") or "")
    if not key:
        raise ValueError("No Lead Intel platform key is stored for this business")
    return LeadIntelClient(key, str(config.get("base_url") or "") or _default_base())


def _default_base() -> str:
    from ziira.plugins.leadsintel.client import BASE_URL

    return BASE_URL


def whatsapp_body(message: Outgoing) -> dict[str, Any]:
    """The request body for one WhatsApp message, by the mode the kernel chose."""
    if message.mode == "template":
        components: list[dict[str, Any]] = []
        if message.template_params:
            components.append({"type": "body", "parameters": [{"type": "text", "text": p}
                                                               for p in message.template_params]})   # UNVERIFIED shape
        for index, (button_id, _title) in enumerate(message.buttons[:BUTTONS_MAX]):
            components.append({"type": "button", "sub_type": "quick_reply", "index": str(index),
                               "parameters": [{"type": "payload", "payload": button_id}]})            # UNVERIFIED shape
        return {"to": message.recipient, "type": "template", "name": message.template_name,
                "language": message.template_language, "components": components}
    if message.mode == "buttons" and message.buttons:
        body = message.body if len(message.body) <= BUTTON_BODY_MAX else message.body[:BUTTON_BODY_MAX - 1] + "…"
        return {"to": message.recipient, "type": "buttons", "body": body,
                "buttons": [{"id": button_id[:256], "title": title[:BUTTON_TITLE_MAX]}
                            for button_id, title in message.buttons[:BUTTONS_MAX]]}
    return {"to": message.recipient, "type": "text", "text": message.body[:TEXT_MAX]}


def idempotency_key(message: Outgoing) -> str:
    """The same for every try of the same message and mode; different when the mode (and so the content) differs."""
    return f"ziira-{message.notification_id}-{message.mode}"[:200]


def interpret(error: LeadIntelError, *, free_form: bool) -> SendResult:
    """A refusal as the kernel understands it. Retryable errors are raised by the caller instead."""
    if error.status == 502 and error.code == "send_failed" and free_form:
        return SendResult(False, permanent_failure=True,
                          message="Lead Intel could not send a free-form message: the 24-hour window may be closed")
    base = PERMANENT.get(error.status, f"Lead Intel replied {error.status}")
    extra = f": {error.detail}" if error.detail else (f" ({error.code})" if error.code else "")
    return SendResult(False, message=f"{base}{extra}"[:300], permanent_failure=True)


class LeadIntelWhatsApp(NotificationChannel):
    """WhatsApp messages through a number connected in Lead Intel."""

    channel = "whatsapp"
    name = "leadsintel"
    channel_label = "WhatsApp"
    supports_templates = True
    supports_buttons = True
    supports_inbound = True
    window_hours = 24

    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        client = client_for(secret, config)
        try:
            reply = client.send_whatsapp(str(config["tenant_ref"]), str(config["connection_id"]),
                                         whatsapp_body(message), idempotency_key(message))
        except LeadIntelError as error:
            free_form = message.mode != "template"
            if error.retryable and not (error.status == 502 and error.code == "send_failed" and free_form):
                raise
            return interpret(error, free_form=free_form)
        return SendResult(True, provider_ref=str(reply.get("messageId") or "") or None)

    def submit_template(self, spec: TemplateSpec, secret: dict[str, Any], config: dict[str, Any]) -> TemplateState:
        return unverified.submit_template(client_for(secret, config), str(config["tenant_ref"]),
                                          str(config["connection_id"]), spec)

    def template_state(self, spec: TemplateSpec, provider_template_id: str | None, secret: dict[str, Any],
                       config: dict[str, Any]) -> TemplateState:
        return unverified.template_state(client_for(secret, config), str(config["tenant_ref"]),
                                         str(config["connection_id"]), spec, provider_template_id)

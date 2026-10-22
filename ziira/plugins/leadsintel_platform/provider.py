"""The platform's chat bot through Lead Intel (https://leadsintel.net/developers.html, read 2026-10-21).

Only the calls that page documents are used. Anything the page does not say is marked `# UNVERIFIED` and listed in
docs/ai.md section 15. Nothing here has been run against the real service: use `scripts/live_check.py chat` with your
own
key, and a number you can lose, before relying on it.

The platform key goes only in the `Authorization` header: never in an address, a log line or an error message.
The base address is fixed; only the environment variable `ZIIRA_LEADSINTEL_PLATFORM_BASE_URL` can change it (for tests).
"""

import os
from typing import Any

import httpx

from ziira.plugins.leadsintel_platform import common
from ziira.sdk import (
    ChatConnectionInfo,
    ChatConnectRequest,
    ChatConnectState,
    ChatContext,
    ChatDelivery,
    ChatError,
    ChatReply,
    ConnectionTest,
    PlatformChatProvider,
    SettingField,
)

BASE_URL = "https://app.leadsintel.net/api"
WA = "/external-platform/whatsapp"
TEXT_MAX = 4000
BUTTON_TITLE_MAX = 20
CLAIM_PREFIX = "claim:"
INBOUND_TIMEOUT_MS = 10000


def base_url() -> str:
    return (os.environ.get("ZIIRA_LEADSINTEL_PLATFORM_BASE_URL") or BASE_URL).rstrip("/")


def _detail(response: httpx.Response) -> tuple[str, str, dict[str, Any]]:
    try:
        body = response.json()
    except ValueError:
        body = {}
    data = body if isinstance(body, dict) else {}
    code = str(data.get("error") or data.get("code") or "")[:80]
    detail = str(data.get("detail") or data.get("message") or data.get("errorMessage") or "")[:200]
    return code, detail, data


def plain_error(response: httpx.Response, *, key: str) -> ChatError:
    """A Lead Intel refusal as words for the platform owner. Never repeats the request (so no key can leak)."""
    status = response.status_code
    code, detail, data = _detail(response)
    if status in (401, 403):
        return ChatError("Lead Intel did not accept the key. Check it and paste it again.", code="key_rejected")
    if status == 404:
        return ChatError("Lead Intel could not find that. It may have been removed there.", code="not_found")
    if status == 409 and "already" in code.lower():
        return ChatError(
            'That number is already connected on Lead Intel. Use "Number already on Lead Intel" to take it over.',
            code="number_in_use",
        )
    if status == 409:
        return ChatError(
            "Lead Intel says this clashes with something already set up there." + (f" ({detail})" if detail else ""),
            code="conflict",
        )
    if status == 429:
        retry = response.headers.get("Retry-After", "")
        return ChatError(
            "Lead Intel asked us to slow down. Wait a minute and try again.",
            code="rate_limited",
            retryable=True,
            retry_after=int(retry) if retry.isdigit() else None,
        )
    if status == 502 and code == "send_failed":
        return ChatError(
            "Lead Intel could not deliver the message. A free-form message only works within 24 hours of "
            "the person's last message.",
            code="refused",
        )
    if status >= 500:
        return ChatError(
            "Lead Intel is not answering properly right now. Try again in a minute.", code="unavailable", retryable=True
        )
    left = data.get("attemptsLeft")
    if left is not None and str(left).isdigit():
        return ChatError(f"That code is not right. {left} tries left.", code="bad_code")
    return ChatError("Lead Intel refused the request" + (f": {detail}" if detail else "."), code="refused")


def request(
    ctx: ChatContext, method: str, path: str, body: dict[str, Any] | None = None, *, idempotency_key: str | None = None
) -> dict[str, Any]:
    """One call. Returns the JSON reply ({} when empty). Raises ChatError."""
    key = ctx.secrets.get("api_key", "")
    if not key:
        raise ChatError("Paste the Lead Intel key first", code="no_key")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key[:200]
    try:
        response = ctx.http.request(method, f"{base_url()}{path}", json=body, headers=headers)
    except httpx.TimeoutException:
        raise ChatError("Lead Intel did not answer in time", code="unavailable", retryable=True) from None
    except httpx.HTTPError:
        raise ChatError("Lead Intel could not be reached", code="unavailable", retryable=True) from None
    if response.status_code >= 400:
        raise plain_error(response, key=key)
    if not response.content:
        return {}
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _refs(ctx: ChatContext) -> tuple[str, str]:
    tenant, connection = ctx.connection.get("tenant_ref", ""), ctx.connection.get("connection_ref", "")
    if not tenant or not connection:
        raise ChatError("No number is connected", code="not_connected")
    return tenant, connection


def _profile_body(profile: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("about", "description"):
        if profile.get(key):
            out[key] = profile[key]
    if profile.get("website"):
        out["websites"] = [profile["website"]]
    return out


class LeadIntelPlatformChat(PlatformChatProvider):
    name = "leadsintel"
    title = "WhatsApp through Lead Intel"
    description = (
        "Connect one WhatsApp number through your Lead Intel account. People who write to it get the same "
        "checked answers as the website assistant."
    )
    config_fields = (
        SettingField(
            "api_key",
            "Lead Intel platform key",
            secret=True,
            help="Paste the platform key from your Lead Intel account. It is stored encrypted and never shown again.",
        ),
    )

    # ---- the key
    def test_key(self, ctx: ChatContext) -> ConnectionTest:
        """A read that changes nothing: ask for a request that cannot exist. 401/403 = key refused; 404 or 400 = the
        key was
        accepted and there is simply nothing by that id. UNVERIFIED that Lead Intel answers an unknown id with 404 (any
        answer but 401/403/429/5xx is taken as 'the key works')."""
        try:
            request(ctx, "GET", f"{WA}/assisted-requests/ziira-key-check")
        except ChatError as error:
            if error.code in ("not_found", "refused"):
                return ConnectionTest(True, "Lead Intel accepted the key.")
            if error.code == "key_rejected":
                return ConnectionTest(False, error.message)
            raise
        return ConnectionTest(True, "Lead Intel accepted the key.")

    # ---- connecting
    def start_connect(self, ctx: ChatContext, request_: ChatConnectRequest) -> ChatConnectState:
        if request_.mode == "existing":
            reply = request(
                ctx,
                "POST",
                f"{WA}/existing-numbers/claims",
                {
                    "phoneNumber": f"+{request_.country_code}{request_.phone_number}",
                    "externalPlatformTenantId": request_.tenant_ref,
                    "externalConnectionId": request_.connection_ref,
                    "inboundWebhookUrl": request_.webhook_url,
                    "inboundWebhookSecret": request_.webhook_secret,
                    "inboundWebhookTimeoutMs": INBOUND_TIMEOUT_MS,
                },
            )
            claim = str(reply.get("claimId") or "")
            if not claim:
                raise ChatError("Lead Intel did not start the claim. Try again.", code="refused")
            return ChatConnectState(
                "awaiting_code", CLAIM_PREFIX + claim, "Lead Intel sent a code to the number. Type it below."
            )
        body: dict[str, Any] = {
            "externalPlatformTenantId": request_.tenant_ref,
            "externalConnectionId": request_.connection_ref,
            "countryCode": request_.country_code,
            "phoneNumber": request_.phone_number,  # UNVERIFIED: digits, no "+"
            "businessName": request_.business_name,
            "displayName": request_.display_name,
            "inboundWebhookUrl": request_.webhook_url,
            "inboundWebhookSecret": request_.webhook_secret,
            "inboundWebhookTimeoutMs": INBOUND_TIMEOUT_MS,
        }
        profile = _profile_body(request_.profile)
        if profile:
            body["businessProfile"] = profile
        reply = request(ctx, "POST", f"{WA}/assisted-requests", body)
        ref = str(reply.get("requestId") or "")
        if not ref:
            raise ChatError("Lead Intel did not accept the request. Try again.", code="refused")
        return ChatConnectState(_status(reply.get("status")), ref, "Lead Intel is setting the number up.")

    def poll_connect(self, ctx: ChatContext, request_ref: str) -> ChatConnectState:
        if request_ref.startswith(CLAIM_PREFIX):
            # UNVERIFIED: no documented status call for a claim, so the connection itself tells.
            info = self.connection_info(ctx)
            if info.active:
                return ChatConnectState(
                    "connected", request_ref, "", phone_number_id=info.phone_number_id, display_phone=info.display_phone
                )
            return ChatConnectState("awaiting_code", request_ref, "Waiting for the code you received on the number.")
        reply = request(ctx, "GET", f"{WA}/assisted-requests/{request_ref}")
        status = _status(reply.get("status"))
        if status == "failed":
            return ChatConnectState("failed", request_ref, _failure(reply), code=str(reply.get("errorCode") or "")[:60])
        message = {
            "pending": "Lead Intel is setting the number up.",
            "awaiting_code": "Lead Intel is waiting for a verification code for this number.",
        }.get(status, "")
        return ChatConnectState(
            status, request_ref, message, phone_number_id=str(reply.get("phoneNumberId") or "") or None
        )

    def cancel_connect(self, ctx: ChatContext, request_ref: str) -> None:
        if request_ref.startswith(CLAIM_PREFIX):
            return  # UNVERIFIED: no documented way to cancel a claim; it lapses there
        try:
            request(ctx, "DELETE", f"{WA}/assisted-requests/{request_ref}")
        except ChatError as error:
            if error.code != "not_found":
                raise

    def verify_code(self, ctx: ChatContext, request_ref: str, code: str) -> ChatConnectState:
        if not request_ref.startswith(CLAIM_PREFIX):
            raise ChatError(
                "This request is not waiting for a code you can type here. Lead Intel handles it.", code="refused"
            )
        request(ctx, "POST", f"{WA}/existing-numbers/claims/{request_ref[len(CLAIM_PREFIX) :]}/verify", {"code": code})
        return ChatConnectState("connected", request_ref, "")

    def find_connection(self, ctx: ChatContext, country_code: str, phone_number: str) -> ChatConnectionInfo | None:
        try:
            # UNVERIFIED reply shape: {externalPlatformTenantId, externalConnectionId, status, phoneNumberId}
            reply = request(ctx, "POST", f"{WA}/connections/lookup", {"phoneNumber": f"+{country_code}{phone_number}"})
        except ChatError as error:
            if error.code == "not_found":
                return None
            raise
        tenant = str(reply.get("externalPlatformTenantId") or reply.get("tenantId") or "")
        connection = str(reply.get("externalConnectionId") or reply.get("connectionId") or "")
        if not tenant or not connection:
            return None
        status = str(reply.get("status") or "")
        return ChatConnectionInfo(
            status == "active",
            status,
            str(reply.get("phoneNumberId") or "") or None,
            str(reply.get("displayPhoneNumber") or "") or None,
            tenant,
            connection,
        )

    def connection_info(self, ctx: ChatContext) -> ChatConnectionInfo:
        tenant, connection = _refs(ctx)
        reply = request(ctx, "GET", f"{WA}/connections/{tenant}/{connection}")
        status = str(reply.get("status") or "")
        return ChatConnectionInfo(
            status == "active",
            status,
            str(reply.get("phoneNumberId") or "") or None,
            str(reply.get("displayPhoneNumber") or reply.get("phoneNumber") or "") or None,
            tenant,
            connection,
        )

    def disconnect(self, ctx: ChatContext) -> None:
        tenant, connection = _refs(ctx)
        try:
            request(ctx, "DELETE", f"{WA}/connections/{tenant}/{connection}")
        except ChatError as error:
            if error.code != "not_found":
                raise

    def update_webhook(self, ctx: ChatContext, url: str, secret: str) -> None:
        tenant, connection = _refs(ctx)
        request(
            ctx,
            "PATCH",
            f"{WA}/connections/{tenant}/{connection}",
            {"inboundWebhookUrl": url, "inboundWebhookSecret": secret, "inboundWebhookTimeoutMs": INBOUND_TIMEOUT_MS},
        )

    def update_profile(self, ctx: ChatContext, profile: dict[str, str]) -> None:
        tenant, connection = _refs(ctx)
        body = _profile_body(profile)
        if body:
            request(ctx, "PATCH", f"{WA}/connections/{tenant}/{connection}", {"businessProfile": body})

    # ---- talking
    def read_delivery(self, ctx: ChatContext, headers: dict[str, str], body: bytes, secret: str) -> ChatDelivery:
        delivery = common.read_delivery(headers, body, secret, ctx.connection.get("phone_number_id") or None)
        return ChatDelivery(delivery.event_id, delivery.receiver_id, delivery.messages, INBOUND_TIMEOUT_MS)

    def reply_body(self, reply: ChatReply) -> dict[str, object]:
        if reply.buttons:
            return {
                "type": "buttons",
                "body": reply.text[:1024],
                "buttons": [{"id": b.id[:256], "title": b.title[:BUTTON_TITLE_MAX]} for b in reply.buttons[:3]],
            }
        return {"type": "text", "text": reply.text[:TEXT_MAX]}

    def send(self, ctx: ChatContext, to: str, reply: ChatReply, idempotency_key: str) -> None:
        tenant, connection = _refs(ctx)
        body: dict[str, object] = {"to": to, **self.reply_body(reply)}
        request(ctx, "POST", f"{WA}/connections/{tenant}/{connection}/send", body, idempotency_key=idempotency_key)


def _status(value: Any) -> str:
    text = str(value or "pending")
    return text if text in ("pending", "awaiting_code", "connected", "failed", "cancelled") else "pending"


def _failure(reply: dict[str, Any]) -> str:
    code, message = str(reply.get("errorCode") or ""), str(reply.get("errorMessage") or "")[:200]
    return (
        "Lead Intel could not connect the number"
        + (f": {message}" if message else ".")
        + (f" ({code})" if code else "")
    )

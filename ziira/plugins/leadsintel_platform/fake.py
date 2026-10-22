"""The development provider (`ZIIRA_CHAT_FAKE=1`, never in production): a stand-in for Lead Intel that needs no key.

It plays the whole connecting story (pending, waiting for a code, connected, or failed), signs deliveries exactly as
Lead
Intel does (so the real signature check runs), and records every message it is asked to send. State and captured
messages
live in a small JSON file so the API and the worker, which are separate processes, see the same thing.

Magic numbers: a number ending 0000 fails to connect ("already connected elsewhere"); one ending 7777 is "already
connected" and can be found and taken over; the code 000000 is wrong, any other 6 digits is right; a key starting with
`bad` is refused.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

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

STATE_DIR = Path(os.environ.get("ZIIRA_CHAT_FAKE_DIR") or Path(tempfile.gettempdir()) / "ziira-chat-fake")
_lock = threading.Lock()


def _file() -> Path:
    return STATE_DIR / "state.json"


def load() -> dict[str, Any]:
    try:
        data = json.loads(_file().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(state))


def reset() -> None:
    with _lock:
        save({})


def _update(change: Any) -> dict[str, Any]:
    with _lock:
        state = load()
        change(state)
        save(state)
        return state


class FakeChatProvider(PlatformChatProvider):
    name = "fake"
    title = "Practice provider (development)"
    description = "A stand-in that plays the connecting story and records messages. Nothing is sent anywhere."
    development_only = True
    config_fields = (SettingField("api_key", "Practice key", secret=True, help="Any text of 8 or more characters"),)

    def test_key(self, ctx: ChatContext) -> ConnectionTest:
        key = ctx.secrets.get("api_key", "")
        return ConnectionTest(
            not key.startswith("bad"),
            "The practice provider accepted the key."
            if not key.startswith("bad")
            else "The practice provider refused the key.",
        )

    def start_connect(self, ctx: ChatContext, request: ChatConnectRequest) -> ChatConnectState:
        ref = f"fake-{int(time.time() * 1000)}"
        number = request.phone_number

        def change(state: dict[str, Any]) -> None:
            state["request"] = {
                "ref": ref,
                "mode": request.mode,
                "number": number,
                "polls": 0,
                "verified": False,
                "tenant": request.tenant_ref,
                "connection": request.connection_ref,
            }
            state["webhook_url"], state["webhook_secret"] = request.webhook_url, request.webhook_secret
            state["profile"] = request.profile
            state["sent"] = state.get("sent", [])

        _update(change)
        if request.mode == "existing":
            return ChatConnectState("awaiting_code", ref, "A code was sent to the number. Type it below.")
        return ChatConnectState("pending", ref, "The practice provider is setting the number up.")

    def poll_connect(self, ctx: ChatContext, request_ref: str) -> ChatConnectState:
        state = load()
        req = state.get("request") or {}
        if req.get("ref") != request_ref:
            raise ChatError("That request is not known", code="not_found")
        if req["number"].endswith("0000"):
            return ChatConnectState(
                "failed",
                request_ref,
                "The practice provider could not connect the number: it is already connected elsewhere.",
                code="phone_number_already_connected",
            )
        if req["mode"] == "existing":
            if req["verified"]:
                return ChatConnectState("connected", request_ref)
            return ChatConnectState("awaiting_code", request_ref, "Waiting for the code you received on the number.")
        polls = req["polls"] + 1
        _update(lambda s: s["request"].update(polls=polls))
        if polls >= 3:
            return ChatConnectState("connected", request_ref)
        if polls == 2:
            return ChatConnectState(
                "awaiting_code", request_ref, "The practice provider is waiting for a verification code."
            )
        return ChatConnectState("pending", request_ref, "The practice provider is setting the number up.")

    def cancel_connect(self, ctx: ChatContext, request_ref: str) -> None:
        _update(lambda s: s.pop("request", None))

    def verify_code(self, ctx: ChatContext, request_ref: str, code: str) -> ChatConnectState:
        if code == "000000":
            raise ChatError("That code is not right. 2 tries left.", code="bad_code")
        _update(lambda s: s["request"].update(verified=True))
        return ChatConnectState("connected", request_ref)

    def find_connection(self, ctx: ChatContext, country_code: str, phone_number: str) -> ChatConnectionInfo | None:
        if not phone_number.endswith("7777"):
            return None
        return ChatConnectionInfo(
            True, "active", "fake-phone-1", f"+{country_code}{phone_number}", "ziira-platform", "bot-recovered"
        )

    def connection_info(self, ctx: ChatContext) -> ChatConnectionInfo:
        req = load().get("request") or {}
        done = (
            req.get("verified")
            or req.get("polls", 0) >= 3
            or ctx.connection.get("mode") == "existing"
            or bool(ctx.connection.get("phone_number_id"))
        )
        number = ctx.connection.get("number") or "+" + str(req.get("number", ""))
        return ChatConnectionInfo(
            bool(done),
            "active" if done else "pending",
            "fake-phone-1",
            number,
            ctx.connection.get("tenant_ref", ""),
            ctx.connection.get("connection_ref", ""),
        )

    def disconnect(self, ctx: ChatContext) -> None:
        _update(lambda s: s.pop("request", None))

    def update_webhook(self, ctx: ChatContext, url: str, secret: str) -> None:
        _update(lambda s: s.update(webhook_url=url, webhook_secret=secret))

    def update_profile(self, ctx: ChatContext, profile: dict[str, str]) -> None:
        _update(lambda s: s.update(profile=profile))

    def read_delivery(self, ctx: ChatContext, headers: dict[str, str], body: bytes, secret: str) -> ChatDelivery:
        delivery = common.read_delivery(headers, body, secret, ctx.connection.get("phone_number_id") or None)
        return ChatDelivery(delivery.event_id, delivery.receiver_id, delivery.messages, 10000)

    def reply_body(self, reply: ChatReply) -> dict[str, object]:
        if reply.buttons:
            return {
                "type": "buttons",
                "body": reply.text[:1024],
                "buttons": [{"id": b.id, "title": b.title[:20]} for b in reply.buttons[:3]],
            }
        return {"type": "text", "text": reply.text[:4000]}

    def send(self, ctx: ChatContext, to: str, reply: ChatReply, idempotency_key: str) -> None:
        def change(state: dict[str, Any]) -> None:
            sent = state.setdefault("sent", [])
            if not any(m["key"] == idempotency_key for m in sent):
                sent.append({"to": to, "key": idempotency_key, **self.reply_body(reply)})

        _update(change)

    def simulate_delivery(
        self, secret: str, sender: str, message: str, button_id: str | None, receiver_id: str | None
    ) -> tuple[dict[str, str], bytes]:
        stamp = str(int(time.time() * 1000))
        item: dict[str, Any] = {"id": f"wamid.fake{stamp}", "from": sender, "timestamp": stamp[:10]}
        if button_id:
            item.update(type="interactive", interactive={"button_reply": {"id": button_id, "title": message}})
        else:
            item.update(type="text", text={"body": message})
        body = json.dumps(
            {
                "messaging_product": "whatsapp",
                "metadata": {"phone_number_id": receiver_id or "fake-phone-1", "display_phone_number": "0"},
                "messages": [item],
            }
        ).encode()
        headers = {
            "x-leadintel-event-id": f"evt-fake-{stamp}",
            "x-leadintel-timestamp": stamp,
            "x-leadintel-signature": common.signature_of(secret, stamp, body),
        }
        return headers, body

    def captured_sends(self) -> list[dict[str, str]]:
        return [{k: str(v) for k, v in m.items()} for m in load().get("sent", [])][-30:]

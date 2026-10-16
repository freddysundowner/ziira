"""Messages that arrive from people over a channel (a reply in a chat service), and what the platform does with them.

A channel plugin that receives a message (after verifying that it is genuine) hands it to `route`. The rules, in order:

1. The sender's conversation window opens, so free-form replies to them are allowed.
2. A STOP word adds the sender to the do-not-contact list, whoever they are.
3. A sender who is not exactly one active user's *verified* number gets nothing back: no answer, no hint that the
   number is known or unknown. The channel plugin keeps the message (a customer's reply to a reminder).
4. A verified user's command is run **as that user**, with their permissions and the channel `chat` in the audit
   log,
   by the first `kernel.inbound_command` handler that understands it (Intelligence reads Approve / Reject / Why
   buttons).
   Commands are rate limited per person, and each is audited.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, messaging, notifications
from ziira.kernel.auth import load_assignments
from ziira.kernel.context import RequestContext, get_context, set_context
from ziira.kernel.errors import ZiiraError
from ziira.kernel.extensions import define_extension_point, implementations

log = logging.getLogger("ziira.inbound")
INBOUND_COMMAND = "kernel.inbound_command"
STOP_WORDS = frozenset({"stop", "unsubscribe", "acha"})        # "acha" is Swahili for stop
COMMANDS_PER_WINDOW = 30
WINDOW_MINUTES = 10
HELP = {
    "en": "I did not understand that. Use the buttons on a suggestion to approve or reject it, or ask me a question "
          "about your business.",
    "sw": "Sijaelewa hilo. Tumia vitufe kwenye pendekezo kuidhinisha au kukataa, au niulize swali kuhusu biashara "
          "yako.",
}


@dataclass(frozen=True)
class InboundMessage:
    """One message from a person: who (international digits), what they wrote or tapped, and its provider id."""

    company_id: UUID
    channel: str
    sender: str
    kind: str                      # text | button | other
    text: str
    button_id: str | None
    received_at: datetime | None
    message_id: str


@dataclass(frozen=True)
class InboundReply:
    """What to say back to the person: text and optional reply buttons (id, title)."""

    text: str
    buttons: tuple[tuple[str, str], ...] = ()


class InboundCommand(ABC):
    """Contract of "kernel.inbound_command": understand a verified user's message and act for them."""

    name: str = "command"

    @abstractmethod
    def handle(self, session: Session, message: InboundMessage, user_id: UUID) -> InboundReply | None:
        """Return a reply if this handler understood the message (the current context is that user's, channel
        'chat'); None to let the next handler try. Raise a ZiiraError to refuse: its message is sent back."""


define_extension_point(INBOUND_COMMAND, InboundCommand,
                       "Understands a signed-in person's reply in a chat channel and acts for them")


def _user_context(session: Session, base: RequestContext, user_id: UUID) -> RequestContext:
    return replace(base, user_id=user_id, channel="chat", all_permissions=False,
                   assignments=load_assignments(session, user_id))


def _recent_commands(session: Session, user_id: UUID) -> int:
    return int(session.execute(text(
        "select count(*) from kernel.audit_log where user_id = :u and action = 'channel.command' "
        "and occurred_at > now() - make_interval(mins => :m)"), {"u": str(user_id), "m": WINDOW_MINUTES}).scalar_one())


def route(session: Session, message: InboundMessage) -> str:
    """Do what the rules above say. Returns the outcome (for the channel plugin's record): `stopped`, `unknown`,
    `limited`, `handled`, `help` or `error`."""
    messaging.record_inbound_contact(session, message.company_id, message.channel, message.sender,
                                     message.received_at)
    if message.kind == "text" and message.text.strip().lower().strip(".!") in STOP_WORDS:
        notifications.opt_out(session, company_id=message.company_id, recipient=f"+{message.sender}", channel=None,
                              reason=f"Replied {message.text.strip()[:20]} on {message.channel}")
        return "stopped"
    user_id = messaging.user_for_phone(session, message.sender)
    if user_id is None:
        return "unknown"
    base = get_context()
    if _recent_commands(session, user_id) >= COMMANDS_PER_WINDOW:
        return "limited"
    set_context(_user_context(session, base, user_id))
    outcome, reply = "help", None
    try:
        for handler in implementations(session, INBOUND_COMMAND):
            try:
                with session.begin_nested():
                    reply = handler.handle(session, message, user_id)
            except ZiiraError as error:
                reply, outcome = InboundReply(error.message), "refused"
                break
            except Exception:  # noqa: BLE001 - a broken handler must not lose the person's message or the others
                log.exception("Inbound command handler %s failed", handler.name)
                reply, outcome = InboundReply("Something went wrong. Please try again in the app."), "error"
                break
            if reply is not None:
                outcome = "handled"
                break
        if reply is None:
            language = messaging.get_prefs(session, user_id).language
            reply = InboundReply(HELP.get(language, HELP["en"]))
        audit.record(session, "channel.command", "kernel.user_phone", user_id, {
            "channel": message.channel, "kind": message.kind, "button": (message.button_id or "")[:80] or None,
            "outcome": outcome})
        _answer(session, message, user_id, reply)
    finally:
        set_context(base)
    return outcome


def _answer(session: Session, message: InboundMessage, user_id: UUID, reply: InboundReply) -> None:
    notifications.queue(session, company_id=message.company_id, channel=message.channel, recipient=f"+{message.sender}",
                        body=reply.text[:3900], buttons=reply.buttons, user_id=user_id, kind="reply",
                        dedupe_key=f"reply:{message.message_id}")

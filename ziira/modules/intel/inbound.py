"""Replying to Intelligence from a chat: the Approve / Reject / Why? buttons on a suggestion, and questions typed to
Ziira. It works on any channel whose provider receives replies (`supports_inbound`) and offers buttons
(`supports_buttons`); Intelligence knows no channel by name.

The platform's channel router (`kernel/inbound.py`) has already checked that the message is genuine, deduplicated it,
and matched the sender's *verified* number to exactly one active user; it runs this handler as that user, with their
permissions and the channel `chat`. So an approval here is the same service call as in the app
(`services/actions.approve`): the owning unit's permissions and approval rules apply to the person, a suggestion that
is no longer open is refused, and the action log, the finding's history and the audit log all say the decision came
by chat.

Buttons carry `approve:<id>`, `reject:<id>` or `why:<id>`. Any other text is a question for Ask Ziira, answered in the
background (`jobs.answer_channel_questions`) and sent back on the same channel.
"""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.permissions import AI_ASK
from ziira.modules.intel.services import actions
from ziira.sdk import (
    InboundCommand,
    InboundMessage,
    InboundReply,
    NotFound,
    Session,
    current_context,
    notification_language,
)

VERBS = ("approve", "reject", "why")
MAX_QUESTION = 500
TEXT = {
    "en": {
        "done": "Done: {message}", "failed": "That did not go through: {message}",
        "rejected": "Okay, I turned that down.", "why": "{description}\nWhy: {summary}{facts}",
        "waiting": "Let me check. I will reply in a moment.", "no_ask": "Ask Ziira is not available to you.",
        "gone": "I cannot find that suggestion.",
    },
    "sw": {
        "done": "Imekamilika: {message}", "failed": "Haikufanikiwa: {message}",
        "rejected": "Sawa, nimekataa pendekezo hilo.", "why": "{description}\nKwa nini: {summary}{facts}",
        "waiting": "Ngoja nikague. Nitakujibu baada ya muda mfupi.", "no_ask": "Ask Ziira haipatikani kwako.",
        "gone": "Sijapata pendekezo hilo.",
    },
}


def parse_button(button_id: str | None) -> tuple[str, UUID] | None:
    """('approve', proposal id) from a button id, or None if it is not one of ours."""
    verb, _, rest = (button_id or "").partition(":")
    if verb not in VERBS:
        return None
    try:
        return verb, UUID(rest)
    except ValueError:
        return None


class ProposalReplies(InboundCommand):
    """Approve, reject or ask why about a suggestion, or ask Ziira a question, from a chat."""

    name = "intel.proposal_replies"

    def handle(self, session: Session, message: InboundMessage, user_id: UUID) -> InboundReply | None:
        words = TEXT.get(notification_language(session, user_id), TEXT["en"])
        if message.kind == "button":
            parsed = parse_button(message.button_id)
            if parsed is None:
                return None                                  # a button of some other feature
            verb, proposal_id = parsed
            return self._decide(session, words, verb, proposal_id)
        if message.kind == "text" and message.text.strip():
            return self._ask(session, words, message, user_id)
        return None

    def _decide(self, session: Session, words: dict[str, str], verb: str, proposal_id: UUID) -> InboundReply:
        try:
            row = actions.get(session, proposal_id)
        except NotFound:
            return InboundReply(words["gone"])
        if verb == "why":
            facts = "".join(f"\n- {k}: {v}" for k, v in dict(row.facts or {}).items())
            return InboundReply(words["why"].format(description=row.description, summary=row.finding_summary or "",
                                                    facts=facts)[:3500])
        if verb == "reject":
            actions.reject(session, proposal_id, "Declined by reply in chat")
            return InboundReply(words["rejected"])
        done = actions.approve(session, proposal_id)
        message = str((done.result or {}).get("message") or "")
        if done.status == "executed":
            return InboundReply(words["done"].format(message=message))
        return InboundReply(words["failed"].format(message=message or done.status))

    def _ask(self, session: Session, words: dict[str, str], message: InboundMessage, user_id: UUID) -> InboundReply:
        ctx = current_context()
        if not ctx.has_anywhere(AI_ASK):
            return InboundReply(words["no_ask"])
        session.execute(text(
            "insert into intel.channel_question (tenant_id, company_id, user_id, channel, sender, message_id, "
            "question) values (kernel.current_tenant(), :c, :u, :ch, :s, :m, :q) on conflict do nothing"),
            {"c": str(message.company_id), "u": str(user_id), "ch": message.channel, "s": message.sender,
             "m": message.message_id, "q": message.text.strip()[:MAX_QUESTION]})
        return InboundReply(words["waiting"])

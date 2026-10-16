"""Answering a question typed to Ziira in a chat: the person is a verified user, the answer is Ask Ziira's
own
(their permissions, their branches, figures checked against tool results), and it goes back on the channel they used.

Called by the background worker with no database transaction open: the claim and the reply are short transactions of
their
own and the AI provider is called in between (`ai.py` insists on that).
"""

import logging
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.services import ask
from ziira.sdk import (
    ZiiraError,
    notification_language,
    recipients_with_permission,
    send_notification,
    tenant_transaction,
)

log = logging.getLogger("ziira.intel")
BATCH = 5
SORRY = {"en": "I could not answer that just now. Please try the Ask Ziira page in the app.",
         "sw": "Sijaweza kujibu hilo kwa sasa. Tafadhali jaribu ukurasa wa Ask Ziira kwenye programu."}


def answer_pending(tenant_id: UUID) -> int:
    """Answer up to a few waiting questions. Returns how many were answered."""
    with tenant_transaction(tenant_id) as session:
        rows = session.execute(text(
            "update intel.channel_question set status = 'answering' where id in (select id from "
            "intel.channel_question where status = 'pending' order by created_at limit :n for update skip locked) "
            "returning id, company_id, user_id, channel, sender, message_id, question"), {"n": BATCH}).all()
        people = {p.user_id: p for p in recipients_with_permission(session, "ai.ask")}
        languages = {r.user_id: notification_language(session, r.user_id) for r in rows}
    answered = 0
    for q in rows:
        person = people.get(q.user_id)
        language = languages[q.user_id]
        reply, ok = SORRY.get(language, SORRY["en"]), False
        if person is not None:
            try:
                reply = ask.ask(replace(person.context, channel="chat"), q.question,
                                company_id=q.company_id, language=language).answer
                ok = True
            except ZiiraError as error:
                reply = error.message
            except Exception:
                log.exception("Ask Ziira could not answer a chat question")
        _send(tenant_id, q, reply[:3900], ok)
        answered += 1 if ok else 0
    return answered


def _send(tenant_id: UUID, q: Any, reply: str, ok: bool) -> None:
    with tenant_transaction(tenant_id) as session:
        send_notification(session, company_id=q.company_id, channel=q.channel, recipient=f"+{q.sender}", body=reply,
                          ref_type="intel.channel_question", ref_id=q.id, dedupe_key=f"reply:{q.message_id}:answer")
        session.execute(text("update intel.channel_question set status = :s, answered_at = now() where id = :i"),
                        {"s": "answered" if ok else "failed", "i": str(q.id)})

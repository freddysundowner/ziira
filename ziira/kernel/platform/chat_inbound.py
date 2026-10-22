"""Deliveries to the chat bot's public address, and the replies that go out later.

`handle` is everything behind `POST /api/v1/public/chat/inbound/{token}` (no sign-in; the signature is the credential):

1. The token is looked up by its hash. An unknown token, a bad or stale signature, a body that is too large and a
   delivery for a bot that is not set up all get the same answer (`REJECTED`), so nothing can be learned by probing.
   Only failures are counted against the caller's address (never a good delivery), so the provider is never locked out.
2. The provider checks the signature on the raw bytes and reads the delivery; its event id is recorded once, and a
repeat
   is acknowledged and ignored (`DUPLICATE`).
3. For each message: `prepare` (who it is, their limits and history), `compose` (the brain, which may be slow) and
`commit`
   (history, hand-off, opt-out, outcome). Only `compose` runs under a deadline. If it does not finish in time the
   delivery
   is answered `202` and the work is queued in `master.chat_outbox`; the worker (`run_pending`) does it afterwards
   with the
   idempotency key `reply-<event id>`, so a retry can never send twice. Otherwise the reply is in the `200` answer.
4. Nothing here raises for a bad message. A failure of our own database is the only thing that gives the provider a 5xx
   (it then delivers again; the event id is forgotten so the second try is not taken for a repeat).

No message text is logged; the logs hold the outcome, a short hash and times.
"""

import hashlib
import hmac
import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from ziira.kernel import site_assistant, throttle
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.platform import behaviour, chat_bot, chat_brain, chat_channel
from ziira.kernel.platform import site_assistant as limits
from ziira.kernel.platform.chat_channel import ChatButton, ChatMessageIn, ChatReply
from ziira.kernel.security import decrypt, encrypt, hash_secret

log = logging.getLogger("ziira.chat")
HISTORY_TURNS = 6
TEXT_KEPT_DAYS = 7
EVENT_KEPT_DAYS = 30
SENDER_KEPT_DAYS = 90
WELCOME_AFTER = timedelta(hours=24)
BACKOFF_SECONDS = (30, 120, 480, 1800, 7200)
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1
CLAIM_SECONDS = 300
MAX_MESSAGES = 5
MAX_TOKEN = 200
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="chat-brain")


@dataclass(frozen=True)
class Result:
    """What the public route answers: a status and, for 200, the reply in the provider's own shape."""

    status: int
    body: dict[str, Any] | None = None


REJECTED = Result(401)
DUPLICATE = Result(204)
IGNORED = Result(204)
LATER = Result(202)


class Deferred(Exception):  # noqa: N818 - not an error: "the brain took too long, the worker will finish"
    pass


# --------------------------------------------------------------------------- people
def sender_hash(digits: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"chat-sender:{digits}".encode(), hashlib.sha256).hexdigest()


def is_opted_out(digits: str) -> bool:
    with master_session() as m:
        return (
            m.execute(
                text("select 1 from master.chat_sender where sender_hash = :h and opted_out_at is not null"),
                {"h": sender_hash(digits)},
            ).first()
            is not None
        )


@dataclass
class Prepared:
    digits: str
    hash: str
    masked: str
    lang: str | None
    first_contact: bool
    opted_out: bool
    history: list[tuple[str, str]]
    over_limit: int  # 0 = fine, 1 = this message is the first over the limit (answer once), 2 = stay quiet


def prepare(message: ChatMessageIn, *, count: bool) -> Prepared:
    """Record that this person wrote, count it against their hourly limit and gather what the brain needs."""
    h, masked = sender_hash(message.sender), chat_brain.mask_number(message.sender)
    with master_session() as m:
        row = m.execute(
            text(
                "insert into master.chat_sender (sender_hash, masked) values (:h, :m) "
                "on conflict (sender_hash) do update set last_seen_at = now() "
                "returning lang, welcomed_at, opted_out_at"
            ),
            {"h": h, "m": masked},
        ).one()
        turns = m.execute(
            text("select role, body from master.chat_turn where sender_hash = :h order by id desc limit :n"),
            {"h": h, "n": HISTORY_TURNS},
        ).all()
    over = 0
    if count:
        used, _ = limits.count_use("chat-sender", h, 3600)
        cap = max(1, get_settings().chat_per_sender_per_hour)
        over = 0 if used <= cap else 1 if used == cap + 1 else 2
    history = [(t.role, t.body) for t in reversed(turns)]
    first = row.welcomed_at is None or datetime.now(UTC) - row.welcomed_at > WELCOME_AFTER
    return Prepared(message.sender, h, masked, row.lang, first, row.opted_out_at is not None, history, over)


def _compose(message: ChatMessageIn, p: Prepared, texts: chat_brain.BotTexts) -> chat_brain.BotReply:
    if p.over_limit == 2:
        return chat_brain.BotReply("", outcome="limited", silent=True, lang=p.lang or "en")
    if p.over_limit == 1:
        lang = p.lang or "en"
        return chat_brain.BotReply(chat_brain.say("slow", lang), outcome="limited", lang=lang)
    return chat_brain.compose(
        message.kind,
        message.text,
        message.button_id,
        texts=texts,
        history=p.history,
        last_lang=p.lang,
        first_contact=p.first_contact,
    )


def _run_with_deadline(work: Any, deadline: float | None) -> chat_brain.BotReply:
    if deadline is None:
        return work()  # type: ignore[no-any-return]
    future: Future[chat_brain.BotReply] = _pool.submit(work)
    try:
        return future.result(timeout=max(deadline, 0.05))
    except FutureTimeout:
        raise Deferred() from None


def commit(message: ChatMessageIn, p: Prepared, reply: chat_brain.BotReply, event_id: str) -> None:
    """Store what happened: the turns (scrubbed, so context can follow), the hand-off, the opt-out or return, the
    language,
    the welcome, and the event's outcome."""
    asked = site_assistant.scrub(site_assistant.clean_input(message.text))[:800]
    with master_session() as m:
        if reply.action == "opt_out":
            m.execute(
                text("update master.chat_sender set opted_out_at = now(), lang = :l where sender_hash = :h"),
                {"h": p.hash, "l": reply.lang},
            )
            m.execute(text("delete from master.chat_turn where sender_hash = :h"), {"h": p.hash})
        else:
            if reply.action == "opt_in":
                m.execute(
                    text("update master.chat_sender set opted_out_at = null where sender_hash = :h"), {"h": p.hash}
                )
            m.execute(
                text(
                    "update master.chat_sender set lang = :l, welcomed_at = case when :w then now() "
                    "else welcomed_at end where sender_hash = :h"
                ),
                {"h": p.hash, "l": reply.lang, "w": bool(reply.text) and not reply.silent},
            )
            if not p.opted_out and asked and reply.action is None and not reply.silent and reply.outcome != "limited":
                m.execute(
                    text("insert into master.chat_turn (sender_hash, role, body) values (:h, 'user', :b)"),
                    {"h": p.hash, "b": asked},
                )
                m.execute(
                    text("insert into master.chat_turn (sender_hash, role, body) values (:h, 'assistant', :b)"),
                    {"h": p.hash, "b": site_assistant.scrub(reply.text)[:800]},
                )
                m.execute(
                    text(
                        "delete from master.chat_turn where sender_hash = :h and id not in "
                        "(select id from master.chat_turn where sender_hash = :h order by id desc limit :n)"
                    ),
                    {"h": p.hash, "n": HISTORY_TURNS},
                )
        m.execute(
            text("update master.chat_event set outcome = :o, sender_hash = :h where event_id = :e"),
            {"o": reply.outcome[:40], "h": p.hash, "e": event_id},
        )
    if reply.action == "handoff":
        _record_handoff(p, asked)


def _record_handoff(p: Prepared, snippet: str) -> None:
    with master_session() as m:
        open_already = m.execute(
            text("select 1 from master.chat_handoff where sender_hash = :h and status = 'open'"), {"h": p.hash}
        ).first()
        if open_already:
            return
        row = m.execute(
            text(
                "insert into master.chat_handoff (sender_hash, sender_masked, snippet) values (:h, :m, :s) returning id"
            ),
            {"h": p.hash, "m": p.masked, "s": snippet[:120] or None},
        ).one()
        m.execute(
            text(
                "insert into master.chat_outbox (event_id, kind, payload_encrypted) values (:e, 'notify_support', :p) "
                "on conflict do nothing"
            ),
            {"e": f"handoff-{row.id}", "p": encrypt(json.dumps({"masked": p.masked}))},
        )


# --------------------------------------------------------------------------- the public entry
def _event_new(event_id: str) -> bool:
    with master_session() as m:
        return (
            m.execute(
                text("insert into master.chat_event (event_id) values (:e) on conflict do nothing returning event_id"),
                {"e": event_id[:200]},
            ).first()
            is not None
        )


def _forget_event(event_id: str) -> None:
    with master_session() as m:
        m.execute(text("delete from master.chat_event where event_id = :e"), {"e": event_id[:200]})


def _mark(event_id: str, outcome: str) -> None:
    with master_session() as m:
        m.execute(
            text("update master.chat_event set outcome = :o where event_id = :e"), {"o": outcome, "e": event_id[:200]}
        )


def handle(token: str, headers: dict[str, str], body: bytes, ip_address: str | None) -> Result:
    """One delivery. See the module note. Raises only for our own failures (the route then answers 5xx)."""
    cfg = get_settings()
    digest = hash_secret(token[:MAX_TOKEN])
    # Only the caller's address is counted: a stranger who learned the address must not lock the provider out.
    counters = throttle.action_counters("chat-in", "-", ip_address, per_subject=10**9, per_ip=60)
    throttle.guard(counters)  # 429 only after many bad deliveries
    if len(token) > MAX_TOKEN or len(body) > cfg.chat_inbound_max_bytes:
        throttle.failed(counters)
        return REJECTED
    row = chat_bot._row()
    provider = chat_channel.get_provider(row["provider"]) if row else None
    if row is None or provider is None or not row["token_hash"] or not hmac.compare_digest(row["token_hash"], digest):
        throttle.failed(counters)
        return REJECTED
    return process(row, provider, headers, body, counters)


def process(
    row: dict[str, Any],
    provider: chat_channel.PlatformChatProvider,
    headers: dict[str, str],
    body: bytes,
    counters: list[throttle.Counter] | None,
) -> Result:
    """A delivery for the bot in `row`, after the address token has been matched (the development screen calls this
    directly with a delivery it signed itself)."""
    secret = chat_bot._secrets(row).get("webhook_secret", "")
    if not secret:
        _failed(counters)
        return REJECTED
    ctx = chat_bot._ctx(row, provider)
    try:
        delivery = provider.read_delivery(ctx, {k.lower(): v for k, v in headers.items()}, body, secret)
    except ValidationFailed:
        _failed(counters)
        return REJECTED
    except Exception:  # noqa: BLE001 - a delivery we cannot read is never a 500
        log.warning("A chat delivery could not be read")
        return IGNORED
    if not _event_new(delivery.event_id):
        return DUPLICATE
    try:
        return _answer(row, provider, ctx, delivery)
    except Exception:
        _forget_event(delivery.event_id)  # let the provider deliver it again
        log.exception("Chat delivery failed")
        raise


def _failed(counters: list[throttle.Counter] | None) -> None:
    if counters:
        throttle.failed(counters)


def _deadline(delivery: chat_channel.ChatDelivery) -> float:
    wanted = float(get_settings().chat_reply_deadline_seconds)
    if delivery.reply_timeout_ms:
        wanted = min(wanted, delivery.reply_timeout_ms / 1000 * 0.6)
    return wanted


def _answer(
    row: dict[str, Any],
    provider: chat_channel.PlatformChatProvider,
    ctx: chat_channel.ChatContext,
    delivery: chat_channel.ChatDelivery,
) -> Result:
    messages = list(delivery.messages)[:MAX_MESSAGES]
    if not messages:
        _mark(delivery.event_id, "ignored")
        return IGNORED
    if not row["enabled"]:
        _mark(delivery.event_id, "off")
        return IGNORED
    texts = chat_bot.bot_texts(row)
    start = time.monotonic()
    inline: ChatReply | None = None
    deferred = False
    for index, message in enumerate(messages):
        event_id = delivery.event_id if index == 0 else f"{delivery.event_id}:{index}"
        remaining = _deadline(delivery) - (time.monotonic() - start)
        if deferred or remaining <= 0:
            _queue(event_id, message, "compute")
            deferred = True
            continue
        prepared = prepare(message, count=True)
        try:
            reply = _run_with_deadline(lambda m=message, p=prepared: _compose(m, p, texts), remaining)
        except Deferred:
            _queue(event_id, message, "compute")
            deferred = True
            continue
        if index:
            with master_session() as m:
                m.execute(
                    text("insert into master.chat_event (event_id) values (:e) on conflict do nothing"),
                    {"e": event_id[:200]},
                )
        commit(message, prepared, reply, event_id)
        if reply.silent or not reply.text:
            continue
        out = ChatReply(reply.text, reply.buttons)
        if inline is None and index == 0:
            inline = out
        else:
            _queue(event_id, message, "send", ready=out)
    if inline is not None and not deferred:
        return Result(200, provider.reply_body(inline))
    if inline is not None:  # a first reply is ready but a later message was deferred
        _queue(delivery.event_id, messages[0], "send", ready=inline)
        return LATER
    return LATER if deferred else IGNORED


# --------------------------------------------------------------------------- the queue
def _queue(event_id: str, message: ChatMessageIn, kind: str, ready: ChatReply | None = None) -> None:
    """Queue work for the worker. `compute`: the message, to be answered later. `send`: a reply already made."""
    payload = (
        {"reply": {"text": ready.text, "buttons": [[b.id, b.title] for b in ready.buttons]}}
        if ready
        else {"message": {"id": message.id, "kind": message.kind, "text": message.text, "button_id": message.button_id}}
    )
    with master_session() as m:
        m.execute(
            text(
                "insert into master.chat_outbox (event_id, kind, sender_hash, to_encrypted, payload_encrypted) "
                "values (:e, :k, :h, :t, :p) on conflict (event_id, kind) do nothing"
            ),
            {
                "e": event_id[:200],
                "k": kind,
                "h": sender_hash(message.sender),
                "t": encrypt(message.sender),
                "p": encrypt(json.dumps(payload)),
            },
        )


def _key(event_id: str) -> str:
    key = f"reply-{event_id}"
    return key if len(key) <= 190 else "reply-" + hashlib.sha256(event_id.encode()).hexdigest()


def _claim(job_id: int) -> Any:
    with master_session() as m:
        return m.execute(
            text(
                "update master.chat_outbox set next_at = now() + make_interval(secs => :c) where id = :i and "
                "status = 'pending' and next_at <= now() returning id, event_id, kind, to_encrypted, "
                "payload_encrypted, attempts"
            ),
            {"c": CLAIM_SECONDS, "i": job_id},
        ).first()


def _finish(job_id: int, status: str, attempts: int, result: str, wait: int | None = None) -> None:
    with master_session() as m:
        if status == "pending":
            m.execute(
                text(
                    "update master.chat_outbox set attempts = :a, result = :r, "
                    "next_at = now() + make_interval(secs => :w) where id = :i"
                ),
                {"a": attempts, "r": result[:300], "w": wait or 60, "i": job_id},
            )
        else:  # the recipient and the words are not kept once the job is over
            m.execute(
                text(
                    "update master.chat_outbox set status = :s, attempts = :a, result = :r, to_encrypted = null, "
                    "payload_encrypted = null, done_at = now() where id = :i"
                ),
                {"s": status, "a": attempts, "r": result[:300], "i": job_id},
            )


def _send_job(job: Any, reply: ChatReply, digits: str) -> tuple[str, str, int | None]:
    """(sent | pending | failed, reason, wait). Sends through the provider; a retryable failure waits and tries
    again."""
    row = chat_bot._row()
    provider = chat_channel.get_provider(row["provider"]) if row else None
    if row is None or provider is None or chat_bot._conn(row).get("status") != "connected":
        return "failed", "The bot is not connected", None
    try:
        chat_channel.call(lambda: provider.send(chat_bot._ctx(row, provider), digits, reply, _key(job.event_id)))
        return "sent", "sent", None
    except chat_channel.ChatError as error:
        reason = chat_bot.scrub(error.message, list(chat_bot._secrets(row).values()))
        if error.retryable and job.attempts + 1 < MAX_ATTEMPTS:
            return "pending", reason, error.retry_after or BACKOFF_SECONDS[job.attempts]
        return "failed", reason, None


def run_job(job_id: int) -> str:
    """Do one queued job (claimed first, so two workers never do the same one). Returns the job's new status."""
    job = _claim(job_id)
    if job is None:
        return "skipped"
    attempts = job.attempts + 1
    try:
        if job.kind == "notify_support":
            status, reason, wait = _notify_support(job)
        else:
            digits = decrypt(job.to_encrypted)
            payload = json.loads(decrypt(job.payload_encrypted))
            if job.kind == "send":
                data = payload["reply"]
                reply = ChatReply(data["text"], tuple(ChatButton(i, t) for i, t in data["buttons"]))
                status, reason, wait = _send_job(job, reply, digits)
            else:
                status, reason, wait = _compute_and_send(job, digits, payload["message"])
    except Exception:  # noqa: BLE001 - the queue never dies; the next try or the failed mark tells the story
        log.exception("Chat job %s failed", job_id)
        status, reason, wait = (
            ("pending", "Unexpected error", BACKOFF_SECONDS[min(job.attempts, 4)])
            if attempts < MAX_ATTEMPTS
            else ("failed", "Unexpected error", None)
        )
    _finish(job_id, status, attempts, reason, wait)
    if status == "failed" and job.kind != "notify_support":
        _mark(job.event_id, "failed")
    return status


def _compute_and_send(job: Any, digits: str, data: dict[str, Any]) -> tuple[str, str, int | None]:
    message = ChatMessageIn(str(data["id"]), digits, str(data["kind"]), str(data["text"]), data.get("button_id"))
    row = chat_bot._row()
    texts = chat_bot.bot_texts(row)
    prepared = prepare(message, count=False)
    reply = _compose(message, prepared, texts)
    commit(message, prepared, reply, job.event_id)
    if reply.silent or not reply.text:
        return "sent", "nothing to send", None
    return _send_job(job, ChatReply(reply.text, reply.buttons), digits)


def _notify_support(job: Any) -> tuple[str, str, int | None]:
    to = str(behaviour.get("public.support_email") or "").strip()
    if not to:
        return "sent", "no support address is set", None
    from ziira.kernel.errors import Unavailable
    from ziira.kernel.platform import mail

    masked = json.loads(decrypt(job.payload_encrypted)).get("masked", "someone")
    try:
        mail.send(
            to,
            "Someone asked to talk to a person on the chat bot",
            f"{masked} asked to talk to a person on the Ziira chat bot.\n\n"
            "Open the Super Admin, the chat bot page, and the list of people waiting. The conversation itself is "
            "in the chat provider's inbox.",
            "other",
        )
    except Unavailable:
        return "pending", "email is not working", 600
    return "sent", "sent", None


def run_pending() -> int:
    """Do every queued job that is due (the worker calls this). Returns how many were tried."""
    with master_session() as m:
        due = [
            r.id
            for r in m.execute(
                text(
                    "select id from master.chat_outbox where status = 'pending' and next_at <= now() "
                    "order by id limit 50"
                )
            )
        ]
    for job_id in due:
        run_job(job_id)
    return len(due)


def purge() -> None:
    """Forget words and old rows: turns and hand-off snippets after seven days, event ids after thirty, senders who have
    not written for ninety days (unless they opted out: that is kept, as a hash only), finished queue rows after
    seven."""
    with master_session() as m:
        m.execute(
            text("delete from master.chat_turn where created_at < now() - make_interval(days => :d)"),
            {"d": TEXT_KEPT_DAYS},
        )
        m.execute(
            text(
                "update master.chat_handoff set snippet = null where snippet is not null and "
                "created_at < now() - make_interval(days => :d)"
            ),
            {"d": TEXT_KEPT_DAYS},
        )
        m.execute(
            text("delete from master.chat_event where received_at < now() - make_interval(days => :d)"),
            {"d": EVENT_KEPT_DAYS},
        )
        m.execute(
            text(
                "delete from master.chat_sender where opted_out_at is null and "
                "last_seen_at < now() - make_interval(days => :d)"
            ),
            {"d": SENDER_KEPT_DAYS},
        )
        m.execute(
            text(
                "delete from master.chat_outbox where status <> 'pending' and "
                "created_at < now() - make_interval(days => :d)"
            ),
            {"d": TEXT_KEPT_DAYS},
        )

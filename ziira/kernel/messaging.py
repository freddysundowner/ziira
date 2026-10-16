"""Reaching people on the channel they prefer: per-person channel choices and quiet hours, the conversation window of
chat channels, verified numbers, and messages built from templates.

The layers, from the bottom: `notifications.queue` records one message for one channel and sends it in the background;
`templates` holds the wording; `channels` says which channels the business has (those of its enabled providers); this
module decides *which* channel for *whom* and *when*:

* **Kinds**: a staff member chooses a channel for each kind of message - `alerts` (urgent findings and nudges), `brief`
  (the daily/weekly brief) and `approvals` (a suggestion waiting for their decision) - or "app" for none. With no
  choice the business's own setting for that kind applies, so nothing changes until someone chooses.
* **Only channels the business has.** A choice or a setting naming a channel whose plugin is off is kept but not used:
  the message goes by the next channel. Switch the plugin on again and it works again.
* **Fallback**: the chosen channel comes first; if it cannot be used (window closed and the template not yet approved,
  no channel set up, the provider refuses) the message goes by the next channel the person has a contact for.
* **Quiet hours**: between the person's quiet start and end, in the *company's* time zone, a message is deferred to
  the end of the quiet period - never dropped. A critical alert may pass if the person allowed it.
* **Verified numbers**: a reply on a channel that receives replies acts as that person, so the number must be proved to
  be theirs: a code is sent and typed back. Only a verified number is ever messaged on such a channel or matched to
  a user.
"""

import json
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, notifications, templates
from ziira.kernel import channels as registry
from ziira.kernel.clock import company_zone
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.security import sign_value, verify_value

KINDS = ("alerts", "brief", "approvals")
APP_ONLY = "app"                          # a person's choice to be told in the app only
CODE_MINUTES = 15
CODE_TRIES = 5


# --------------------------------------------------------------------------- preferences
@dataclass(frozen=True)
class Prefs:
    """What a person chose. `channels` holds only the kinds they chose for."""

    channels: dict[str, str] = field(default_factory=dict)
    quiet_enabled: bool = False
    quiet_start: time = time(21, 0)
    quiet_end: time = time(7, 0)
    quiet_critical_ok: bool = False
    language: str = "en"


def get_prefs(session: Session, user_id: UUID) -> Prefs:
    row = session.execute(text(
        "select channels, quiet_enabled, quiet_start, quiet_end, quiet_critical_ok, language "
        "from kernel.user_notification_pref where user_id = :u"), {"u": str(user_id)}).first()
    if row is None:
        return Prefs()
    return Prefs(dict(row.channels or {}), row.quiet_enabled, row.quiet_start, row.quiet_end, row.quiet_critical_ok,
                 row.language)


def set_prefs(session: Session, user_id: UUID, *, channels: dict[str, str] | None = None,
              quiet_enabled: bool | None = None, quiet_start: time | None = None, quiet_end: time | None = None,
              quiet_critical_ok: bool | None = None, language: str | None = None) -> Prefs:
    """Change a person's preferences (only what is given). Audited."""
    current = get_prefs(session, user_id)
    chosen = dict(current.channels)
    for kind, choice in (channels or {}).items():
        if kind not in KINDS:
            raise ValidationFailed(f"Unknown kind of message '{kind}'")
        if choice in ("", "default", None):
            chosen.pop(kind, None)
        else:
            if choice != APP_ONLY:
                registry.check(session, choice)
            chosen[kind] = choice
    if language is not None and language not in templates.LANGUAGES:
        raise ValidationFailed(f"Language must be one of: {', '.join(templates.LANGUAGES)}")
    new = Prefs(chosen, current.quiet_enabled if quiet_enabled is None else quiet_enabled,
                quiet_start or current.quiet_start, quiet_end or current.quiet_end,
                current.quiet_critical_ok if quiet_critical_ok is None else quiet_critical_ok,
                language or current.language)
    if new.quiet_enabled and new.quiet_start == new.quiet_end:
        raise ValidationFailed("Quiet hours need a start and an end that differ")
    session.execute(text(
        "insert into kernel.user_notification_pref (tenant_id, user_id, channels, quiet_enabled, quiet_start, "
        "quiet_end, quiet_critical_ok, language) values (kernel.current_tenant(), :u, cast(:c as jsonb), :qe, :qs, "
        ":qn, :qc, :l) on conflict (tenant_id, user_id) do update set channels = excluded.channels, "
        "quiet_enabled = excluded.quiet_enabled, quiet_start = excluded.quiet_start, quiet_end = excluded.quiet_end, "
        "quiet_critical_ok = excluded.quiet_critical_ok, language = excluded.language, updated_at = now()"),
        {"u": str(user_id), "c": json.dumps(new.channels), "qe": new.quiet_enabled, "qs": new.quiet_start,
         "qn": new.quiet_end, "qc": new.quiet_critical_ok, "l": new.language})
    audit.record(session, "update", "kernel.user_notification_pref", user_id, {
        "channels": new.channels, "quiet_enabled": new.quiet_enabled, "quiet_start": new.quiet_start.isoformat(),
        "quiet_end": new.quiet_end.isoformat()})
    return new


def quiet_until(now_local: datetime, start: time, end: time) -> datetime | None:
    """When the quiet period that `now_local` is inside ends, or None if it is not quiet now. The period runs from
    `start` to `end` and may cross midnight (21:00 to 07:00). Equal times mean no quiet period."""
    if start == end:
        return None
    t = now_local.time()
    if start < end:
        if not start <= t < end:
            return None
        day = now_local.date()
    else:
        if not (t >= start or t < end):
            return None
        day = now_local.date() if t < end else now_local.date() + timedelta(days=1)
    return datetime.combine(day, end, tzinfo=now_local.tzinfo)


def deliver_at(session: Session, company_id: UUID, user_id: UUID, *, critical: bool = False,
               now: datetime | None = None) -> datetime | None:
    """When a message to this person may go out: None for now, or the end of their quiet hours."""
    prefs = get_prefs(session, user_id)
    if not prefs.quiet_enabled or (critical and prefs.quiet_critical_ok):
        return None
    local = (now or datetime.now(UTC)).astimezone(company_zone(session, company_id))
    return quiet_until(local, prefs.quiet_start, prefs.quiet_end)


# --------------------------------------------------------------------------- contacts and the plan
def configured_channels(session: Session, company_id: UUID) -> set[str]:
    return set(session.execute(text(
        "select distinct provider from kernel.integration_credential where company_id = :c and status = 'active' "
        "and coalesce(config->>'ready', 'true') <> 'false'"), {"c": str(company_id)}).scalars())


def verified_phone(session: Session, user_id: UUID) -> str | None:
    return session.execute(text(
        "select phone from kernel.user_phone where user_id = :u and verified_at is not null"),
        {"u": str(user_id)}).scalar_one_or_none()


def contact_for(session: Session, user_id: UUID, channel: str) -> str | None:
    """How to reach a person on a channel. On a channel that receives replies only their *verified* number counts; on
    others their phone (or their email for email)."""
    found = registry.info(session, channel)
    if found is not None and found.supports_inbound:
        number = verified_phone(session, user_id)
        return f"+{number}" if number else None         # already international: the "+" keeps it so
    column = "email" if channel == "email" else "phone"
    return session.execute(text(f"select {column} from kernel.app_user where id = :u and status = 'active'"),
                           {"u": str(user_id)}).scalar_one_or_none() or None


def plan_for_user(session: Session, company_id: UUID, user_id: UUID, kind: str, default_channels: Sequence[str],
                  require_configured: bool = False, capability: str | None = None) -> list[tuple[str, str]]:
    """The ways to reach a person about `kind`, best first, as (channel, address), using only channels the business has.

    Their own choice comes first, then the business's default for that kind, then (when they made a choice, or a default
    is not available, or a default is a conversational channel that can fail on a closed window) the other channels the
    business has set up. A name that is not available (its plugin is off) is skipped, never an error.
    `capability` ('buttons', 'inbound', 'templates') replaces the defaults with the channels that can do it, and with
    `require_configured` a channel the business has not set up is never in the plan (used for kinds that have no
    legacy behaviour to keep, such as approvals: no such channel means no message, not a failed one)."""
    chosen = get_prefs(session, user_id).channels.get(kind)
    if chosen == APP_ONLY:
        return []
    have = {i.channel: i for i in registry.available(session)}
    defaults = list(default_channels)
    if capability is not None:
        defaults = [c for c, i in have.items() if getattr(i, f"supports_{capability}")]
        require_configured = True
    dropped = chosen is not None and chosen not in have
    if dropped:
        chosen = None
    keep = [c for c in defaults if c in have or c in registry.BASIC]
    dropped = dropped or len(keep) < len(defaults)
    require_configured = require_configured or dropped      # what was asked for is gone: only what works
    conversational = any(c in have and have[c].conversational for c in keep)
    order = ([chosen] if chosen else []) + [c for c in keep if c != chosen]
    if chosen or (capability is None and (dropped or conversational)):
        order += [c for c in have if c not in order]
    configured = configured_channels(session, company_id)
    plan: list[tuple[str, str]] = []
    for channel in order:
        address = contact_for(session, user_id, channel)
        if not address or ((plan or require_configured) and channel not in configured):
            continue
        plan.append((channel, address))
    return plan


def notify_user(session: Session, *, company_id: UUID, user_id: UUID, kind: str, body: str,
                subject: str | None = None, default_channels: Sequence[str] = (), template: str | None = None,
                variables: dict[str, str] | None = None, buttons: Sequence[tuple[str, str]] = (),
                ref_type: str | None = None, ref_id: UUID | None = None, dedupe_key: str | None = None,
                critical: bool = False, require_configured: bool = False,
                capability: str | None = None) -> UUID | None:
    """Message a staff member about `kind` by their preferred channel, falling back to the next, and deferring to the
    end of their quiet hours. Returns the first message's id (None: nothing to send to, or the same `dedupe_key` was
    already used)."""
    plan = plan_for_user(session, company_id, user_id, kind, default_channels, require_configured, capability)
    if not plan:
        return None
    prefs = get_prefs(session, user_id)
    later = deliver_at(session, company_id, user_id, critical=critical)
    for index, (channel, address) in enumerate(plan):
        try:
            with session.begin_nested():
                return notifications.queue(
                    session, company_id=company_id, channel=channel, recipient=address, body=body,
                    subject=subject if subject is not None else (
                        "A message from Ziira" if channel == "email" else None),
                    ref_type=ref_type, ref_id=ref_id, dedupe_key=dedupe_key, template=template, variables=variables,
                    language=prefs.language, buttons=buttons,
                    fallbacks=[{"channel": c, "recipient": a} for c, a in plan[index + 1:]], user_id=user_id,
                    kind=kind, deliver_at=later)
        except ValidationFailed:
            continue                               # an address that is not usable (a mistyped number): try the next
    return None


def notify_user_templated(session: Session, *, company_id: UUID, user_id: UUID, kind: str, template: str,
                          variables: dict[str, str], default_channels: Sequence[str] = (),
                          button_suffix: str | None = None, ref_type: str | None = None, ref_id: UUID | None = None,
                          dedupe_key: str | None = None, critical: bool = False,
                          require_configured: bool = False, capability: str | None = None) -> UUID | None:
    """Like `notify_user`, with the wording of a shipped template in the person's language. `button_suffix` is added to
    the template's button ids (for example the id of the thing to approve): a reply then carries it back."""
    language = get_prefs(session, user_id).language
    subject, body = templates.render(template, language, variables)
    lang, _ = templates.wording(template, language)
    shipped = templates.catalogue()[template]
    buttons = [(f"{bid}:{button_suffix}" if button_suffix else bid, title[:20])
               for bid, title in shipped.buttons.get(lang, [])]
    return notify_user(session, company_id=company_id, user_id=user_id, kind=kind, body=body, subject=subject,
                       default_channels=default_channels, template=template, variables=variables, buttons=buttons,
                       ref_type=ref_type, ref_id=ref_id, dedupe_key=dedupe_key, critical=critical,
                       require_configured=require_configured, capability=capability)


def send_templated(session: Session, *, company_id: UUID, channel: str, recipient: str, template: str,
                   variables: dict[str, str], language: str | None = None,
                   fallbacks: Sequence[dict[str, str]] = (), ref_type: str | None = None, ref_id: UUID | None = None,
                   dedupe_key: str | None = None, kind: str | None = None) -> UUID | None:
    """Send a shipped template to someone outside the business (a customer). A conversational channel uses the
    approved template when its window is closed; SMS and email use the same wording. `fallbacks` are tried in order if
    this channel cannot be used (or is not available at all: its plugin is off)."""
    subject, body = templates.render(template, language, variables)
    return notifications.queue(
        session, company_id=company_id, channel=channel, recipient=recipient, body=body, subject=subject,
        ref_type=ref_type, ref_id=ref_id, dedupe_key=dedupe_key, template=template,
        variables={k: templates.clean_value(str(v)) for k, v in variables.items()},
        language=templates.wording(template, language)[0], fallbacks=fallbacks, kind=kind)


# --------------------------------------------------------------------------- the conversation window
def record_inbound_contact(session: Session, company_id: UUID, channel: str, contact: str,
                           when: datetime | None = None) -> None:
    """Note that a contact wrote to the business: free-form messages to them are allowed for the channel's window."""
    session.execute(text(
        "insert into kernel.contact_window (tenant_id, company_id, channel, contact, last_inbound_at) "
        "values (kernel.current_tenant(), :c, :ch, :p, coalesce(:w, now())) on conflict "
        "(tenant_id, company_id, channel, contact) do update set last_inbound_at = greatest("
        "kernel.contact_window.last_inbound_at, excluded.last_inbound_at)"),
        {"c": str(company_id), "ch": channel, "p": contact, "w": when})


def window_open(session: Session, company_id: UUID, channel: str, contact: str) -> bool:
    found = registry.info(session, channel)
    if found is None or found.window_hours is None:
        return False
    return session.execute(text(
        "select 1 from kernel.contact_window where company_id = :c and channel = :ch and contact = :p "
        "and last_inbound_at > now() - make_interval(hours => :h)"),
        {"c": str(company_id), "ch": channel, "p": contact, "h": found.window_hours}).first() is not None


# --------------------------------------------------------------------------- verified numbers
def code_route(session: Session, company_id: UUID, user_id: UUID, number: str) -> list[tuple[str, str]]:
    """Where the code can be sent: every channel the business has set up, those that reach the number first (the channel
    that will receive replies, then SMS), a person's email last. Raises if nothing is set up."""
    configured = configured_channels(session, company_id)
    route: list[tuple[str, str]] = []
    email = session.execute(text("select email from kernel.app_user where id = :u"), {"u": str(user_id)}).scalar_one()
    for found in registry.available(session):
        if found.channel not in configured:
            continue
        if found.channel == "email":
            if email:
                route.append(("email", email))
        else:
            route.append((found.channel, f"+{number}"))
    route.sort(key=lambda r: r[0] == "email")
    if not route:
        raise ValidationFailed("No channel is set up to send the code. Set up SMS, email or a chat channel first")
    return route


def start_phone_verification(session: Session, user_id: UUID, company_id: UUID, phone: str) -> str:
    """Send a code to prove a number is the person's. Returns the number in international digits. The code goes by the
    first channel the business has set up that reaches the number, then the next, and by email last (an email proves
    only that the person controls their account, not the number)."""
    if not any(i.supports_inbound for i in registry.available(session)):
        raise ValidationFailed("No channel that receives replies is available for this business")
    number = notifications.check_recipient("sms", phone, notifications.calling_code(session, company_id))
    taken = session.execute(text(
        "select 1 from kernel.user_phone where phone = :p and verified_at is not null and user_id <> :u"),
        {"p": number, "u": str(user_id)}).first()
    if taken is not None:
        raise ValidationFailed("That number is already registered to someone else in this business")
    recent = session.execute(text(
        "select 1 from kernel.user_phone where user_id = :u and verified_at is null "
        "and created_at > now() - interval '60 seconds'"), {"u": str(user_id)}).first()
    if recent is not None:
        raise ValidationFailed("A code was just sent. Wait a minute before asking for another")
    route = code_route(session, company_id, user_id, number)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    session.execute(text("delete from kernel.user_phone where user_id = :u and verified_at is null"),
                    {"u": str(user_id)})
    session.execute(text(
        "insert into kernel.user_phone (tenant_id, user_id, phone, code_hash, code_expires_at) values "
        "(kernel.current_tenant(), :u, :p, :h, now() + make_interval(mins => :m))"),
        {"u": str(user_id), "p": number, "h": sign_value(f"phone-code:{user_id}:{number}:{code}"), "m": CODE_MINUTES})
    prefs = get_prefs(session, user_id)
    send_templated(session, company_id=company_id, channel=route[0][0], recipient=route[0][1],
                   template="verification_code", variables={"code": code}, language=prefs.language,
                   fallbacks=[{"channel": c, "recipient": a} for c, a in route[1:]],
                   ref_type="phone_verification", ref_id=user_id, kind="security")
    audit.record(session, "phone_verification_started", "kernel.user_phone", user_id, None)
    return number


def confirm_phone(session: Session, user_id: UUID, code: str) -> str:
    """The person typed back the code: the number becomes theirs. Returns it."""
    row = session.execute(text(
        "select id, phone, code_hash, code_expires_at, attempts from kernel.user_phone "
        "where user_id = :u and verified_at is null for update"), {"u": str(user_id)}).first()
    if row is None or row.code_expires_at is None or row.code_expires_at < datetime.now(UTC):
        raise ValidationFailed("That code has expired. Ask for a new one")
    if row.attempts >= CODE_TRIES:
        raise ValidationFailed("Too many wrong codes. Ask for a new one")
    if not verify_value(f"phone-code:{user_id}:{row.phone}:{code.strip()}", row.code_hash or ""):
        session.execute(text("update kernel.user_phone set attempts = attempts + 1 where id = :i"),
                        {"i": str(row.id)})
        session.commit()                                    # the wrong guess must be counted even though we refuse
        raise ValidationFailed("That code is not right")
    taken = session.execute(text(
        "select 1 from kernel.user_phone where phone = :p and verified_at is not null"), {"p": row.phone}).first()
    if taken is not None:
        raise ValidationFailed("That number is already registered to someone else in this business")
    session.execute(text("delete from kernel.user_phone where user_id = :u and verified_at is not null"),
                    {"u": str(user_id)})
    session.execute(text("update kernel.user_phone set verified_at = now(), code_hash = null, code_expires_at = null "
                         "where id = :i"), {"i": str(row.id)})
    audit.record(session, "phone_verified", "kernel.user_phone", user_id, None)
    return str(row.phone)


def remove_phone(session: Session, user_id: UUID) -> None:
    session.execute(text("delete from kernel.user_phone where user_id = :u"), {"u": str(user_id)})
    audit.record(session, "phone_removed", "kernel.user_phone", user_id, None)


def phone_state(session: Session, user_id: UUID) -> dict[str, Any]:
    """For the settings screen: the number, whether verified, and whether a code is waiting."""
    row = session.execute(text(
        "select phone, verified_at, code_expires_at from kernel.user_phone where user_id = :u "
        "order by verified_at nulls last limit 1"), {"u": str(user_id)}).first()
    if row is None:
        return {"phone": None, "verified": False, "pending": False}
    return {"phone": row.phone, "verified": row.verified_at is not None,
            "pending": row.verified_at is None and row.code_expires_at is not None
            and row.code_expires_at > datetime.now(UTC)}


def user_for_phone(session: Session, phone: str) -> UUID | None:
    """The one active user whose verified number this is, or None (unknown, or not exactly one)."""
    rows = session.execute(text(
        "select p.user_id from kernel.user_phone p join kernel.app_user u on u.id = p.user_id "
        "where p.phone = :p and p.verified_at is not null and u.status = 'active'"), {"p": phone}).scalars().all()
    return rows[0] if len(rows) == 1 else None

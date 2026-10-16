"""Message templates: named messages with variables, per channel and language, and where they stand with the provider.

Ziira's own templates (daily brief, urgent alert, overdue reminder, payment due, action proposal, verification code) are
shipped as data in `message_templates.json`, with their wording in each supported language. A conversational channel
may start a conversation (or write after its window closes) only with a template the provider has approved, so each
business keeps a row per template, language and such channel with its status:

    draft ──submit──▶ submitted ──provider decides──▶ approved | rejected ──(fix and submit again)──▶ submitted

Sending a message that needs a template refuses until it is approved; the message then falls back to the next way of
reaching the person (`kernel/notifications.py`). SMS and email need no approval: they use the same wording directly.
Nothing here names a country: the wording is data, the language a setting of the person or the business.
"""

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import channels as registry
from ziira.kernel import credentials
from ziira.kernel.channels import NOTIFICATION_CHANNEL
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.extensions import implementations
from ziira.kernel.jobs import periodic
from ziira.kernel.notifications import NotificationChannel, TemplateSpec

log = logging.getLogger("ziira.templates")
DATA = Path(__file__).with_name("message_templates.json")
LANGUAGES = ("en", "sw")
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
MAX_VALUE = 400                 # a variable longer than this is cut (providers refuse very long parameters)


@dataclass(frozen=True)
class Shipped:
    """One template as shipped, with its wording per language."""

    code: str
    category: str
    variables: tuple[str, ...]
    examples: tuple[str, ...]
    buttons: dict[str, list[tuple[str, str]]]          # language -> [(id, title)]
    text: dict[str, dict[str, str]]                     # language -> {subject, body}


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Shipped]:
    """The templates Ziira ships, by code."""
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    found: dict[str, Shipped] = {}
    for item in raw["templates"]:
        shipped = Shipped(
            code=item["code"], category=item["category"], variables=tuple(item["variables"]),
            examples=tuple(item["examples"]),
            buttons={lang: [(b[0], b[1]) for b in rows] for lang, rows in item.get("buttons", {}).items()},
            text=item["text"])
        for lang, words in shipped.text.items():
            unknown = set(PLACEHOLDER.findall(words["body"])) - set(shipped.variables)
            if unknown:
                raise ValueError(f"Template {shipped.code}/{lang} uses undeclared variables {sorted(unknown)}")
        found[shipped.code] = shipped
    return found


def clean_value(value: str) -> str:
    """A variable as providers accept it: one line, single spaces, not too long."""
    return re.sub(r"\s+", " ", value).strip()[:MAX_VALUE]


def wording(code: str, language: str | None) -> tuple[str, dict[str, str]]:
    """The language used and the subject/body of a shipped template (English when the language is not shipped)."""
    shipped = catalogue().get(code)
    if shipped is None:
        raise ValidationFailed(f"Unknown message template '{code}'")
    lang = language if language in shipped.text else "en"
    return lang, shipped.text[lang]


def render(code: str, language: str | None, values: dict[str, str]) -> tuple[str, str]:
    """(subject, body) of a shipped template with its variables filled in. Every variable must be given."""
    shipped = catalogue().get(code)
    if shipped is None:
        raise ValidationFailed(f"Unknown message template '{code}'")
    _, words = wording(code, language)
    missing = [v for v in shipped.variables if v not in values]
    if missing:
        raise ValidationFailed(f"Template '{code}' needs: {', '.join(missing)}")
    fill = {v: clean_value(str(values[v])) for v in shipped.variables}
    return (PLACEHOLDER.sub(lambda m: fill[m.group(1)], words["subject"]),
            PLACEHOLDER.sub(lambda m: fill[m.group(1)], words["body"]))


def positional(body: str, variables: tuple[str, ...]) -> str:
    """The body with `{name}` replaced by the {{1}}, {{2}} placeholders providers use, in the order of `variables`."""
    index = {name: n for n, name in enumerate(variables, start=1)}
    return PLACEHOLDER.sub(lambda m: "{{" + str(index[m.group(1)]) + "}}", body)


def provider_name(code: str) -> str:
    return f"ziira_{code}"


# --------------------------------------------------------------------------- a business's templates
@dataclass(frozen=True)
class Approved:
    """An approved template, ready to send."""

    variables: tuple[str, ...]
    provider_name: str
    language: str


def template_channels(session: Session) -> list[str]:
    """The channels of this business whose provider approves templates (none if their plugin is off)."""
    return [i.channel for i in registry.available(session) if i.supports_templates]


def ensure(session: Session, company_id: UUID) -> None:
    """Make sure the business has a draft row for every shipped template and language on each channel that needs
    them."""
    for channel in template_channels(session):
        for shipped in catalogue().values():
            for lang, words in shipped.text.items():
                session.execute(text(
                    "insert into kernel.message_template (tenant_id, company_id, code, channel, language, category, "
                    "body, variables, buttons) values (kernel.current_tenant(), :c, :code, :ch, :l, :cat, :b, "
                    "cast(:v as jsonb), cast(:btn as jsonb)) on conflict do nothing"),
                    {"c": str(company_id), "code": shipped.code, "ch": channel, "l": lang, "cat": shipped.category,
                     "b": words["body"], "v": json.dumps(list(shipped.variables)),
                     "btn": json.dumps([list(b) for b in shipped.buttons.get(lang, [])])})


def list_templates(session: Session, company_id: UUID) -> list[Any]:
    """The business's templates on the channels it has now (rows of a channel whose plugin is off are kept, not
    shown)."""
    ensure(session, company_id)
    return list(session.execute(text(
        "select id, channel, code, language, category, body, variables, buttons, status, provider_template_id, "
        "rejection_reason, submitted_at, decided_at from kernel.message_template "
        "where company_id = :c and channel = any(:ch) order by channel, code, language"),
        {"c": str(company_id), "ch": template_channels(session)}))


def approved(session: Session, company_id: UUID, channel: str, code: str, language: str) -> Approved | None:
    """The approved template for this channel, code and language (English if only that is approved)."""
    for lang in dict.fromkeys((language, "en")):
        row = session.execute(text(
            "select variables, language from kernel.message_template where company_id = :c and code = :code "
            "and channel = :ch and language = :l and status = 'approved'"),
            {"c": str(company_id), "code": code, "ch": channel, "l": lang}).first()
        if row is not None:
            return Approved(tuple(row.variables), provider_name(code), row.language)
    return None


def _provider(session: Session, company_id: UUID, channel: str) -> tuple[NotificationChannel, UUID, dict[str, Any]]:
    found = session.execute(text(
        "select id, config from kernel.integration_credential where company_id = :c and provider = :ch "
        "and status = 'active' order by created_at desc limit 1"), {"c": str(company_id), "ch": channel}).first()
    if found is None:
        raise ValidationFailed(f"Set up the {channel} channel first")
    wanted = str((found.config or {}).get("provider") or "")
    chosen = next((c for c in implementations(session, NOTIFICATION_CHANNEL)
                   if c.channel == channel and c.name == wanted and c.supports_templates), None)
    if chosen is None:
        raise ValidationFailed(f"The {channel} provider cannot manage templates")
    return chosen, found.id, dict(found.config or {})


def _spec(row: Any) -> TemplateSpec:
    shipped = catalogue()[row.code]
    variables = tuple(row.variables)
    examples = tuple(shipped.examples[shipped.variables.index(v)] for v in variables)
    return TemplateSpec(name=provider_name(row.code), language=row.language, category=row.category,
                        body=positional(row.body, variables), variables=variables, examples=examples,
                        buttons=tuple(title for _, title in (row.buttons or [])))


def submit_all(session: Session, company_id: UUID) -> dict[str, int]:
    """Send every template that is a draft or was rejected to its provider for approval, on every channel that needs
    them and is set up. A failure on one is noted on it and does not stop the rest."""
    ensure(session, company_id)
    done = {"submitted": 0, "approved": 0, "failed": 0}
    ready = 0
    for channel in template_channels(session):
        try:
            provider, credential_id, config = _provider(session, company_id, channel)
        except ValidationFailed:
            continue
        ready += 1
        secret = credentials.read_secret(session, credential_id)
        rows = session.execute(text(
            "select id, code, language, category, body, variables, buttons from kernel.message_template "
            "where company_id = :c and channel = :ch and status in ('draft', 'rejected') order by code, language "
            "for update"), {"c": str(company_id), "ch": channel}).all()
        for row in rows:
            try:
                state = provider.submit_template(_spec(row), secret, config)
            except Exception as exc:  # noqa: BLE001 - one template failing must not stop the others
                log.warning("Template %s/%s could not be submitted: %s", row.code, row.language, exc)
                session.execute(text("update kernel.message_template set rejection_reason = :r, updated_at = now() "
                                     "where id = :i"), {"r": f"Could not submit: {exc}"[:300], "i": str(row.id)})
                done["failed"] += 1
                continue
            _store_state(session, row.id, state, provider.name, submitted=True)
            done["approved" if state.status == "approved" else "submitted"] += 1
    if not ready:
        raise ValidationFailed("No channel that needs templates is set up")
    return done


def sync_all(session: Session, company_id: UUID) -> dict[str, int]:
    """Ask each provider where its submitted templates stand and record it."""
    done = {"approved": 0, "rejected": 0, "waiting": 0, "failed": 0}
    ready = 0
    for channel in template_channels(session):
        try:
            provider, credential_id, config = _provider(session, company_id, channel)
        except ValidationFailed:
            continue
        ready += 1
        secret = credentials.read_secret(session, credential_id)
        rows = session.execute(text(
            "select id, code, language, category, body, variables, buttons, provider_template_id from "
            "kernel.message_template where company_id = :c and channel = :ch and status = 'submitted' "
            "order by code, language for update"), {"c": str(company_id), "ch": channel}).all()
        for row in rows:
            try:
                state = provider.template_state(_spec(row), row.provider_template_id, secret, config)
            except Exception as exc:  # noqa: BLE001
                log.warning("Template %s/%s status could not be read: %s", row.code, row.language, exc)
                done["failed"] += 1
                continue
            _store_state(session, row.id, state, provider.name, submitted=False)
            done["waiting" if state.status == "submitted" else state.status] += 1
    if not ready:
        raise ValidationFailed("No channel that needs templates is set up")
    return done


def _store_state(session: Session, template_id: Any, state: Any, provider: str, *, submitted: bool) -> None:
    if state.status not in ("submitted", "approved", "rejected"):
        raise ValidationFailed(f"The provider reported an unknown template status '{state.status}'")
    session.execute(text(
        "update kernel.message_template set status = :s, provider = :p, "
        "provider_template_id = coalesce(:pid, provider_template_id), rejection_reason = :r, updated_at = now(), "
        "submitted_at = case when :sub then now() else submitted_at end, "
        "decided_at = case when :s in ('approved', 'rejected') then now() else decided_at end where id = :i"),
        {"s": state.status, "p": provider, "pid": state.provider_template_id,
         "r": (state.reason or "")[:300] or None, "sub": submitted, "i": str(template_id)})


def get_template(session: Session, template_id: UUID) -> Any:
    row = session.execute(text("select id, company_id, code, language, status from kernel.message_template "
                               "where id = :i"), {"i": str(template_id)}).first()
    if row is None:
        raise NotFound("Template not found")
    return row


@periodic("kernel.sync_templates", every_seconds=1800)
def sync_templates(session: Session) -> None:
    """Pick up the provider's decisions on templates that were submitted."""
    companies = session.execute(text(
        "select distinct company_id from kernel.message_template where status = 'submitted'")).scalars().all()
    for company_id in companies:
        try:
            with session.begin_nested():
                sync_all(session, company_id)
        except ValidationFailed:
            continue                                 # the channel was switched off meanwhile

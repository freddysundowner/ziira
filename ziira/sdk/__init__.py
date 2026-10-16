"""The Ziira SDK: the only kernel interface modules and plugins may import.

Modules and plugins must import from `ziira.sdk`, never from `ziira.kernel`
(enforced by import-linter). This keeps units independent of kernel internals.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import (
    api_keys,
    approvals,
    audit,
    channels,
    company_settings,
    credentials,
    exceptions_inbox,
    idempotency,
    inbound,
    messaging,
    notifications,
    numbering,
    reasons,
    support,
)
from ziira.kernel import templates as _message_templates  # noqa: F401 - registers the recurring template sync
from ziira.kernel.auth import client_ip, context_from_access_token
from ziira.kernel.checks import IntegrityCheck
from ziira.kernel.clock import company_date_of, company_today, format_day, humanise_dates
from ziira.kernel.config import Settings, get_settings
from ziira.kernel.context import Assignment, RequestContext, get_context, set_context, system_context
from ziira.kernel.csvutil import safe, to_csv
from ziira.kernel.db import tenant_session
from ziira.kernel.errors import (
    Conflict,
    Forbidden,
    MfaSetupRequired,
    NotFound,
    Unauthorized,
    ValidationFailed,
    ZiiraError,
)
from ziira.kernel.events import Event, publish, publish_many, subscribe, subscribe_after
from ziira.kernel.extensions import (
    define_extension_point,
    define_validation_hook,
    implementations,
    provider_named,
    provides,
    run_validators,
    validate,
)
from ziira.kernel.inbound import INBOUND_COMMAND, InboundCommand, InboundMessage, InboundReply
from ziira.kernel.jobs import enqueue, job, periodic, unbound_periodic
from ziira.kernel.manifest import SDK_VERSION
from ziira.kernel.notifications import (
    NotificationChannel,
    Outgoing,
    SendResult,
    TemplateSpec,
    TemplateState,
)
from ziira.kernel.numbers import Amount, Quantity, Rate, UnitCost, page_limit, page_offset
from ziira.kernel.organisation import BranchUsageProvider
from ziira.kernel.packs import COUNTRY_SEEDER, CountrySeeder, pack_providers, read_pack_data
from ziira.kernel.personal_data import (
    PLACEHOLDER,
    Kept,
    Outcome,
    PersonalDataProvider,
    PersonalRecord,
    RetentionRule,
    Subject,
    json_one,
    json_rows,
    like_pattern,
    mask_text,
    sql_digits,
    sql_identifier,
    sql_phone_matches,
)
from ziira.kernel.phone import check_calling_code, normalise_phone
from ziira.kernel.platform import ai as platform_ai
from ziira.kernel.platform import entitlements
from ziira.kernel.platform.ai import AI_PLATFORM, AiPlatformHooks
from ziira.kernel.platform.gateways import (
    PAYMENT_GATEWAY,
    AttemptInfo,
    ConnectionTest,
    GatewayContext,
    GatewayError,
    PayerField,
    PaymentGateway,
    PaymentState,
    SettingField,
    StartResult,
    WebhookEvent,
    classify_response,
)
from ziira.kernel.recipients import Recipient, recipients_with_permission
from ziira.kernel.security import decrypt, encrypt, hash_secret, new_secret, sign_value, verify_value

__all__ = [
    "PAYMENT_GATEWAY", "AttemptInfo", "ConnectionTest", "GatewayContext", "GatewayError", "PayerField",
    "PaymentGateway", "PaymentState", "SettingField", "StartResult", "WebhookEvent", "classify_response",
    "safe", "to_csv",
    "COUNTRY_SEEDER", "CountrySeeder", "pack_providers", "read_pack_data",
    "BranchUsageProvider", "PLACEHOLDER", "Kept", "Outcome", "PersonalDataProvider", "PersonalRecord", "RetentionRule",
    "Subject",
    "json_one", "json_rows", "like_pattern", "mask_text", "sql_digits", "sql_identifier", "sql_phone_matches",
    "check_calling_code", "normalise_phone",
    "INBOUND_COMMAND", "InboundCommand", "InboundMessage", "InboundReply", "TemplateSpec", "TemplateState",
    "can_reach", "channel_can", "channel_names", "check_channel", "configured_channels", "mask_contact",
    "notification_language", "notify_user", "notify_user_templated",
    "send_templated", "route_inbound", "record_delivery",
    "Amount", "Assignment", "Conflict", "Event", "Forbidden", "IntegrityCheck", "NotFound", "NotificationChannel",
    "Outgoing",
    "Quantity", "Rate", "Recipient", "RequestContext", "SDK_VERSION", "SendResult", "Session", "Unauthorized",
    "UnitCost",
    "ValidationFailed", "ZiiraError", "audit_record", "check_branch_open", "check_company", "check_reason",
    "company_date_of", "company_setting", "company_today", "format_day", "humanise_dates",
    "current_context", "DB_SESSION", "db_session", "decrypt_text", "define_extension_point", "define_validation_hook",
    "encrypt_text", "enqueue", "flag_for_review", "hash_secret", "idempotency_key_header", "idempotent",
    "implementations", "is_production", "job", "money", "new_secret", "next_document_number", "opt_out_contact",
    "page_limit", "page_offset", "periodic", "provides", "publish", "publish_many", "read_credential",
    "recipients_with_permission", "request_context", "require_permission", "run_validators", "send_notification",
    "platform_settings", "provider_named", "settings_public_base_url", "sign_value", "tenant_transaction",
    "unbound_periodic", "update_company_settings",
    "set_context", "store_credential", "submit_for_approval", "subscribe", "subscribe_after", "system_session",
    "validate",
    "verify_value",
    "AI_PLATFORM", "AiPlatformHooks", "ai_active_secrets", "ai_cap_reached", "ai_record_usage", "ai_runtime",
]


def money(value: Decimal | int | str) -> Decimal:
    """Round a money amount to 2 decimal places, half up. Never use float for money."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def current_context() -> RequestContext:
    """Tenant, user, channel and permissions of the current request.

    Check scope inside services with `current_context().require("stock.adjust", company_id=..., branch_id=...)`.
    """
    return get_context()


def audit_record(session: Session, action: str, entity_type: str, entity_id: UUID | None,
                 changes: dict[str, object] | None = None) -> None:
    """Add an entry to the audit log in the current transaction."""
    audit.record(session, action, entity_type, entity_id, changes)


# --------------------------------------------------------------------------- kernel services
def flag_for_review(session: Session, *, unit: str, kind: str, message: str, severity: str = "medium",
                    company_id: UUID | None = None, branch_id: UUID | None = None, ref_type: str | None = None,
                    ref_id: UUID | None = None, amount: Decimal | None = None,
                    dedupe_key: str | None = None) -> UUID | None:
    """Put something in the exceptions inbox for a person to review (negative stock, a till shortage, an unmatched
    payment). With a `dedupe_key` the same problem raised twice is one item. See kernel/exceptions_inbox.py."""
    return exceptions_inbox.flag(session, unit=unit, kind=kind, message=message, severity=severity,
                                 company_id=company_id, branch_id=branch_id, ref_type=ref_type, ref_id=ref_id,
                                 amount=amount, dedupe_key=dedupe_key)


def store_credential(session: Session, *, company_id: UUID, provider: str, label: str, secret: dict[str, Any],
                     config: dict[str, Any] | None = None, branch_id: UUID | None = None,
                     replace: UUID | None = None) -> UUID:
    """Save an integration secret (Daraja keys, bank keys) encrypted; returns the credential's id. See
    kernel/credentials.py."""
    return credentials.store_secret(session, company_id=company_id, provider=provider, label=label, secret=secret,
                                    config=config, branch_id=branch_id, replace=replace)


def read_credential(session: Session, credential_id: UUID) -> dict[str, Any]:
    """The decrypted secret of a credential. Call it only where the secret is about to be used."""
    return credentials.read_secret(session, credential_id)


def encrypt_text(plain: str) -> str:
    """Encrypt a small secret (a phone number waiting in a job) with the platform's credentials key."""
    return encrypt(plain)


def decrypt_text(token: str) -> str:
    """Decrypt something made by `encrypt_text`."""
    return decrypt(token)


def ai_runtime(feature: str = "ask", tenant_id: UUID | None = None) -> platform_ai.Runtime | None:
    """Which AI provider, key and model the platform has set up for a feature (and for this business), or None."""
    return platform_ai.runtime(feature, tenant_id)


def ai_record_usage(tenant_id: UUID, provider: str, model: str, tokens_in: int, tokens_out: int) -> None:
    """Add a call's tokens to the platform's estimate of AI spend (counts and money only)."""
    platform_ai.record_usage(tenant_id, provider, model, tokens_in, tokens_out)


def ai_active_secrets() -> list[str]:
    """Every AI key the platform holds, to remove from any text before it is stored."""
    return platform_ai.active_secrets()


def ai_cap_reached() -> bool:
    """True when the platform's monthly AI spend cap has been reached."""
    snap = platform_ai.snapshot()
    return snap.cap_usd is not None and snap.spend_usd >= snap.cap_usd


def platform_settings() -> Settings:
    """The platform's own configuration (environment variables): for secrets and options that belong to the operator,
    such as the AI provider's key. Never put a value from here in a reply or a log."""
    return get_settings()


def update_company_settings(session: Session, company_id: UUID, changes: dict[str, Any]) -> dict[str, Any]:
    """Change company settings, audited (the same rules as the settings endpoint). The caller checks permission."""
    return company_settings.update_settings(session, company_id, changes)


@contextmanager
def tenant_transaction(tenant_id: UUID) -> Iterator[Session]:
    """A short transaction in a tenant's database that keeps the current request context (unlike `system_session`).
    For work that must not hold a transaction while it waits on an outside service: read, close, call, then write in
    another one. Commits on success."""
    with tenant_session(tenant_id) as session:
        yield session


def is_production() -> bool:
    """True when running in production (development shortcuts such as the fake payment provider are refused)."""
    return get_settings().env == "production"


def settings_public_base_url() -> str:
    """The address other systems use to reach this API (for callback URLs)."""
    return get_settings().public_base_url


@contextmanager
def system_session(tenant_id: UUID) -> Iterator[Session]:
    """A transaction in a tenant's database acting as the system: for work nobody signed in for (a payment
    callback from Safaricom, a worker job). The caller must have authenticated the request some other way."""
    system_context(tenant_id)
    with tenant_session(tenant_id) as session:
        yield session


def idempotent(session: Session, key: str | None, request: Any, operation: Callable[[], Any]) -> tuple[Any, bool]:
    """Run `operation` once per Idempotency-Key; a retry gets the stored response. Returns (response, replayed).
    `operation` must return something JSON-able. See kernel/idempotency.py."""
    return idempotency.run_once(session, key, request, operation)


async def idempotency_key_header(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key",
                                         description="Makes a retry safe: the same key does the work once"),
) -> str | None:
    """FastAPI dependency: the Idempotency-Key header, if the client sent one."""
    return idempotency.check_key(idempotency_key) if idempotency_key is not None else None


def send_notification(session: Session, *, company_id: UUID, channel: str, recipient: str, body: str,
                      subject: str | None = None, ref_type: str | None = None, ref_id: UUID | None = None,
                      dedupe_key: str | None = None) -> UUID | None:
    """Queue a message on one channel to someone outside the system; it is sent in the background through the
    business's provider for that channel. Returns its id (None if `dedupe_key` was already used). For a customer on a
    chat channel, or a staff member with channel preferences, use `send_templated` / `notify_user`. See
    kernel/notifications.py."""
    return notifications.queue(session, company_id=company_id, channel=channel, recipient=recipient, body=body,
                               subject=subject, ref_type=ref_type, ref_id=ref_id, dedupe_key=dedupe_key)


def send_templated(session: Session, *, company_id: UUID, channel: str, recipient: str, template: str,
                   variables: dict[str, str], language: str | None = None,
                   fallbacks: list[dict[str, str]] | None = None, ref_type: str | None = None,
                   ref_id: UUID | None = None, dedupe_key: str | None = None) -> UUID | None:
    """Send a shipped message template (kernel/message_templates.json) to a customer or supplier. On a
    conversational channel the
    approved template is used when the 24-hour window is closed; `fallbacks` ({"channel", "recipient"}) are tried in
    order when the channel cannot be used. See kernel/messaging.py."""
    return messaging.send_templated(session, company_id=company_id, channel=channel, recipient=recipient,
                                    template=template, variables=variables, language=language,
                                    fallbacks=fallbacks or (), ref_type=ref_type, ref_id=ref_id,
                                    dedupe_key=dedupe_key)


def notify_user(session: Session, *, company_id: UUID, user_id: UUID, kind: str, body: str, subject: str | None = None,
                default_channels: list[str] | None = None, template: str | None = None,
                variables: dict[str, str] | None = None, ref_type: str | None = None, ref_id: UUID | None = None,
                dedupe_key: str | None = None, critical: bool = False,
                require_configured: bool = False, capability: str | None = None) -> UUID | None:
    """Message a staff member about `kind` ("alerts", "brief", "approvals") by the channel they chose, falling back to
    the next, deferred to the end of their quiet hours. `default_channels` apply when they chose nothing; with
    `require_configured` channels the business has not set up are left out; `capability` ('buttons', 'inbound',
    'templates')
    picks the channels that can do it. Channels the business does not have are skipped, never an error. See
    kernel/messaging.py."""
    return messaging.notify_user(session, company_id=company_id, user_id=user_id, kind=kind, body=body,
                                 subject=subject, default_channels=default_channels or (), template=template,
                                 variables=variables, ref_type=ref_type, ref_id=ref_id, dedupe_key=dedupe_key,
                                 critical=critical, require_configured=require_configured,
                                 capability=capability)


def notify_user_templated(session: Session, *, company_id: UUID, user_id: UUID, kind: str, template: str,
                          variables: dict[str, str], default_channels: list[str] | None = None,
                          button_suffix: str | None = None, ref_type: str | None = None, ref_id: UUID | None = None,
                          dedupe_key: str | None = None, critical: bool = False,
                          require_configured: bool = False, capability: str | None = None) -> UUID | None:
    """`notify_user` with a shipped template's wording in the person's language (and its reply buttons, whose ids carry
    `button_suffix` back in the reply)."""
    return messaging.notify_user_templated(
        session, company_id=company_id, user_id=user_id, kind=kind, template=template, variables=variables,
        default_channels=default_channels or (), button_suffix=button_suffix, ref_type=ref_type, ref_id=ref_id,
        dedupe_key=dedupe_key, critical=critical, require_configured=require_configured, capability=capability)


def channel_names(session: Session) -> list[str]:
    """The channels this business has: those whose provider (plugin) is enabled for it. Never a fixed list."""
    return channels.names(session)


def check_channel(session: Session, channel: str) -> str:
    """The channel if the business has it, else a ValidationFailed that says so and lists the ones it has."""
    return channels.check(session, channel)


def channel_can(session: Session, channel: str, capability: str) -> bool:
    """True if the business has the channel and its provider declares the capability: 'buttons', 'inbound' or
    'templates'."""
    found = channels.info(session, channel)
    return found is not None and bool(getattr(found, f"supports_{capability}", False))


def configured_channels(session: Session, company_id: UUID) -> set[str]:
    """The channels the business has set up and that are ready to send."""
    return messaging.configured_channels(session, company_id)


def can_reach(session: Session, company_id: UUID, user_id: UUID, kind: str, default_channels: list[str]) -> bool:
    """True if `notify_user` would have somewhere to send to for this person and kind."""
    return bool(messaging.plan_for_user(session, company_id, user_id, kind, default_channels))


def notification_language(session: Session, user_id: UUID) -> str:
    """The language a person chose for messages ('en', 'sw')."""
    return messaging.get_prefs(session, user_id).language


def mask_contact(recipient: str) -> str:
    """A phone number or email for screens and logs, most of it hidden."""
    return notifications.mask(recipient)


def route_inbound(session: Session, message: InboundMessage) -> str:
    """A channel plugin hands a verified incoming message to the platform (STOP, replies from staff). See
    kernel/inbound.py."""
    return inbound.route(session, message)


def record_delivery(session: Session, *, provider: str, provider_ref: str, status: str,
                    error: str | None = None) -> bool:
    """A channel provider reports what became of a message (delivered, read, failed)."""
    return notifications.record_delivery(session, provider=provider, provider_ref=provider_ref, status=status,
                                         error=error)


def opt_out_contact(session: Session, *, company_id: UUID, recipient: str, channel: str | None = None,
                    reason: str | None = None) -> UUID:
    """Record that a person asked not to be messaged (on one channel, or on all). See kernel/notifications.py."""
    return notifications.opt_out(session, company_id=company_id, recipient=recipient, channel=channel, reason=reason)


def company_setting(session: Session, company_id: UUID, key: str) -> Any:
    """A company policy such as 'negative_stock_allowed' (default if never changed). See kernel/company_settings.py."""
    return company_settings.get_setting(session, company_id, key)


def check_company(session: Session, company_id: UUID, branch_id: UUID | None = None) -> None:
    """Raise ValidationFailed unless the company (and branch, if given) belong to the current tenant.

    Call it before saving any record that names a company or branch: foreign keys are checked
    by PostgreSQL without row-level security, so they would accept another tenant's id.
    """
    checked: set[tuple[UUID, UUID | None]] = session.info.setdefault("checked_companies", set())
    if (company_id, branch_id) in checked:             # a posting asks again for every line and entry it makes
        return
    if session.execute(text("select 1 from kernel.company where id = :c"), {"c": str(company_id)}).first() is None:
        raise ValidationFailed("Company not found")
    if branch_id is not None and session.execute(
            text("select 1 from kernel.branch where id = :b and company_id = :c"),
            {"b": str(branch_id), "c": str(company_id)}).first() is None:
        raise ValidationFailed("Branch not found in that company")
    checked.add((company_id, branch_id))


def check_branch_open(session: Session, branch_id: UUID) -> None:
    """Raise ValidationFailed if the branch has been closed (Settings > Organisation): a closed branch keeps its history
    but takes no new tills, devices or locations."""
    closed = session.execute(text("select 1 from kernel.branch where id = :b and not is_active"),
                             {"b": str(branch_id)}).first()
    if closed is not None:
        raise ValidationFailed("This branch is closed. Reopen it in Settings > Organisation first")


def next_document_number(session: Session, *, company_id: UUID, branch_id: UUID | None, doc_type: str,
                         prefix: str) -> str:
    """Take the next human document number, e.g. ADJ-THK-000001. See kernel/numbering.py."""
    return numbering.next_document_number(session, company_id=company_id, branch_id=branch_id,
                                          doc_type=doc_type, prefix=prefix)


def check_reason(session: Session, category: str, reason_code_id: UUID | None, note: str | None = None) -> None:
    """Raise ValidationFailed unless a valid, active reason of `category` was given (with a note if needed)."""
    reasons.check_reason(session, category, reason_code_id, note)


def submit_for_approval(session: Session, *, company_id: UUID, doc_type: str, doc_id: UUID,
                        amount: Decimal = Decimal("0")) -> str:
    """Start approval of a document. Returns 'approved' (no approval needed) or 'pending'.

    When pending, subscribe to 'approval.decided' (aggregate_type == doc_type) to post or reject
    the document; event.payload["status"] is 'approved' or 'rejected'.
    """
    return approvals.submit_for_approval(session, company_id=company_id, doc_type=doc_type, doc_id=doc_id,
                                         amount=amount).status


# --------------------------------------------------------------------------- FastAPI dependencies
async def request_context(
    request: Request,
    authorization: str | None = Header(default=None, description="Bearer <access token>"),
    x_api_key: str | None = Header(default=None, description="API key for server-to-server integrations"),
    x_tenant_id: UUID | None = Header(default=None, description="Development only: act as this tenant"),
) -> RequestContext:
    """FastAPI dependency: authenticate the request and set who is acting.

    Order: bearer token, then API key, then (development only) the X-Tenant-ID header,
    which acts with every permission. Async on purpose: it runs in the request's own task,
    so the context it sets is copied into the threads that run sync dependencies and endpoints.
    """
    settings = get_settings()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthorized("Use 'Authorization: Bearer <token>'")
        ctx = await run_in_threadpool(context_from_access_token, token.strip())
    elif x_api_key:
        ctx = await run_in_threadpool(api_keys.authenticate, x_api_key.strip(), client_ip(request))
    elif settings.dev_tenant_header and (x_tenant_id or settings.dev_default_tenant):
        tenant_id = x_tenant_id or settings.dev_default_tenant
        assert tenant_id is not None
        ctx = RequestContext(tenant_id=tenant_id, channel="api", all_permissions=True)
    else:
        raise Unauthorized("Sign in first")
    ctx = replace(ctx, ip_address=client_ip(request))
    request.state.ziira_ctx = ctx              # for the export audit (kernel/export_audit.py), which runs outside
    api_keys.enforce(ctx, request)             # an API key: read-only keys, and the public API only
    support.enforce(ctx, request.method, request.url.path)     # platform staff under a support grant: its limits
    await run_in_threadpool(entitlements.enforce_access, ctx, request)    # suspended, cancelled or unlicensed: 402
    if ctx.mfa_setup_required and not request.url.path.startswith("/api/v1/auth/"):
        # The business requires a second factor of this person and it is not set up: nothing else works until it is.
        raise MfaSetupRequired("Set up two-step verification to continue")
    set_context(ctx)
    return ctx


def db_session(ctx: RequestContext = Depends(request_context)) -> Iterator[Session]:
    """The transaction scoped to the request's tenant. Use `DB_SESSION` in routes, not `Depends(db_session)`."""
    with tenant_session(ctx.tenant_id) as session:
        yield session


# The scope matters. FastAPI (since 0.118) ends a `yield` dependency AFTER the response has gone to the client unless
# told otherwise: the transaction would commit after "201 Created" was sent (the next request may not see the record,
# and a failed commit could never become an error reply). `scope="function"` ends it right after the endpoint, before
# the reply.
DB_SESSION = Depends(db_session, scope="function")


def require_permission(permission: str) -> Callable[[RequestContext], RequestContext]:
    """FastAPI dependency: reject the request unless the actor holds `permission` somewhere.

    Endpoints that act on a company or branch must also check the scope in the service:
    `current_context().require(permission, company_id=..., branch_id=...)`.
    """

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not ctx.has_anywhere(permission):
            raise Forbidden(f"You do not have permission '{permission}'")
        return ctx

    return check

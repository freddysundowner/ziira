"""Self-service subscription payments (docs/subscription-payments.md).

A business pays one of its issued invoices through a payment gateway plugin. This service owns everything that is the
same for every gateway:

- which gateways are offered for an invoice (enabled by the platform owner, configured, serving the invoice's currency
  and the business's country; none: the manual payment instructions);
- the platform owner's gateway settings, with secrets stored encrypted and never returned;
- the attempt record (`master.payment_attempt`) and its timeline, one open attempt per invoice, a rate limit;
- **confirm before credit**: an invoice is credited only after the gateway's own `check` says completed *and* the
  amount, currency and invoice reference match; a notification or a browser return only makes us ask. A mismatch is
  flagged to the billing operators and never credited;
- recovery: a recurring pass asks the gateway about open attempts, so a lost notification still ends in a credit, and
  attempts older than a day expire.

Crediting uses the existing `billing.record_payment`, so the subscription moves on exactly as for a manual payment.
"""

import hashlib
import hmac
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import Conflict, NotFound, TooManyRequests, Unavailable, ValidationFailed
from ziira.kernel.platform import billing, gateways, settings
from ziira.kernel.platform.gateways import (
    AttemptInfo,
    GatewayContext,
    GatewayError,
    PaymentGateway,
    PaymentState,
)
from ziira.kernel.security import decrypt, encrypt

log = logging.getLogger("ziira.payments")
OPEN = ("initiated", "pending")
RATE_LIMIT_PER_HOUR = 5
EXPIRE_AFTER = timedelta(hours=24)
YOUNG = timedelta(minutes=15)
OLD_RECHECK = timedelta(hours=1)
NEVER_REACHED_AFTER = timedelta(minutes=5)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def _now() -> datetime:
    return datetime.now(UTC)


def _installed(name: str) -> PaymentGateway:
    found = gateways.get_gateway(name)
    if found is None:
        raise NotFound("No such payment method")
    return found


# --------------------------------------------------------------------------- settings and secrets
def _row(name: str) -> dict[str, Any] | None:
    with master_session() as m:
        row = m.execute(text("select * from master.payment_gateway where name = :n"), {"n": name}).first()
    return dict(row._mapping) if row else None


def _secrets_of(row: dict[str, Any] | None) -> dict[str, str]:
    if not row or not row["secrets_encrypted"]:
        return {}
    data = json.loads(decrypt(row["secrets_encrypted"]))
    return {str(k): str(v) for k, v in data.items()}


def _config_of(gateway: PaymentGateway, row: dict[str, Any] | None) -> dict[str, str]:
    stored = (row or {}).get("config") or {}
    return {f.name: str(stored.get(f.name, f.default)) for f in gateway.config_fields if not f.secret}


def _configured(gateway: PaymentGateway, row: dict[str, Any] | None) -> bool:
    config, secrets = _config_of(gateway, row), _secrets_of(row)
    for f in gateway.config_fields:
        if f.required and not (secrets.get(f.name) if f.secret else config.get(f.name, "").strip()):
            return False
    return True


def webhook_url(name: str) -> tuple[str | None, str | None]:
    """The address to register with the provider, and a plain problem when the public address cannot receive it."""
    base = get_settings().public_base_url.rstrip("/")
    host = base.split("://", 1)[-1].split("/", 1)[0].split(":")[0] if "://" in base else base
    local = host in LOCAL_HOSTS or host.endswith((".localhost", ".test")) or host == "[::1]"
    if base.startswith("http://") and not local:
        return None, "The platform's public address is not https: set ZIIRA_PUBLIC_BASE_URL to the https address first"
    return f"{base}/api/v1/billing/webhooks/{name}", None


def overview() -> list[dict[str, Any]]:
    """Every installed gateway with its saved settings. Secrets are reported only as set / not set."""
    out = []
    for cls in gateways.installed():
        gateway = cls()
        row = _row(gateway.name)
        secrets, config = _secrets_of(row), _config_of(gateway, row)
        url, problem = webhook_url(gateway.name)
        out.append(
            {
                "name": gateway.name,
                "title": gateway.title,
                "pay_label": gateway.pay_label,
                "description": gateway.description,
                "flow": gateway.flow,
                "methods": list(gateway.methods),
                "currencies": list(gateway.currencies),
                "countries": list(gateway.countries),
                "development_only": gateway.development_only,
                "fields": [
                    {
                        "name": f.name,
                        "label": f.label,
                        "secret": f.secret,
                        "required": f.required,
                        "help": f.help,
                        "value": None if f.secret else config.get(f.name, ""),
                        "is_set": bool(secrets.get(f.name)) if f.secret else bool(config.get(f.name, "").strip()),
                    }
                    for f in gateway.config_fields
                ],
                "enabled": bool(row and row["enabled"]),
                "configured": _configured(gateway, row),
                "default_for": list((row or {}).get("default_for") or []),
                "webhook_url": url,
                "webhook_problem": problem,
                "updated_at": (row or {}).get("updated_at"),
                "updated_by": (row or {}).get("updated_by"),
            }
        )
    return out


def _code_list(values: list[str]) -> list[str]:
    out = sorted({str(v).strip().upper() for v in values if str(v).strip()})
    if any(len(c) not in (2, 3) or not c.isalpha() for c in out):
        raise ValidationFailed("Default-for entries are currency or country codes such as USD or GB")
    return out


def save_gateway(
    name: str,
    *,
    enabled: bool | None,
    config: dict[str, str] | None,
    secrets: dict[str, str] | None,
    clear_secrets: list[str] | None,
    default_for: list[str] | None,
    by: str,
) -> dict[str, Any]:
    """Change a gateway's settings. A secret left empty is kept; naming it in `clear_secrets` removes it."""
    gateway = _installed(name)
    by_name = {f.name: f for f in gateway.config_fields}
    for key, value in (config or {}).items():
        if key not in by_name or by_name[key].secret:
            raise ValidationFailed(f"'{key}' is not a setting of {gateway.title}")
        if len(str(value)) > 500:
            raise ValidationFailed(f"'{key}' is too long")
    for key in {*(secrets or {}), *(clear_secrets or [])}:
        if key not in by_name or not by_name[key].secret:
            raise ValidationFailed(f"'{key}' is not a secret of {gateway.title}")
    row = _row(name)
    new_config = {**_config_of(gateway, row), **{k: str(v).strip() for k, v in (config or {}).items()}}
    new_config = gateway.validate_config(new_config)
    new_secrets = _secrets_of(row)
    for key in clear_secrets or []:
        new_secrets.pop(key, None)
    for key, value in (secrets or {}).items():
        if str(value).strip():
            if len(str(value)) > 2000:
                raise ValidationFailed(f"'{key}' is too long")
            new_secrets[key] = str(value).strip()
    now_enabled = bool(row and row["enabled"]) if enabled is None else enabled
    probe = {"config": new_config, "secrets_encrypted": json.dumps(new_secrets) if new_secrets else None}
    if now_enabled and not _configured(gateway, {**probe, "secrets_encrypted": encrypt(json.dumps(new_secrets))}):
        raise ValidationFailed("Enter every required setting and secret before switching this payment method on")
    codes = _code_list(default_for) if default_for is not None else list((row or {}).get("default_for") or [])
    with master_session() as m:
        m.execute(
            text(
                "insert into master.payment_gateway (name, enabled, config, secrets_encrypted, default_for, "
                "updated_by) "
                "values (:n, :e, cast(:c as jsonb), :s, :d, :b) on conflict (name) do update set enabled = "
                "excluded.enabled, config = excluded.config, secrets_encrypted = excluded.secrets_encrypted, "
                "default_for = excluded.default_for, updated_at = now(), updated_by = excluded.updated_by"
            ),
            {
                "n": name,
                "e": now_enabled,
                "c": json.dumps(new_config),
                "s": encrypt(json.dumps(new_secrets)) if new_secrets else None,
                "d": codes,
                "b": by,
            },
        )
    return next(g for g in overview() if g["name"] == name)


@contextmanager
def gateway_context(name: str) -> Iterator[GatewayContext]:
    """The settings, secrets and an HTTP client for one call."""
    gateway = _installed(name)
    row = _row(name)
    client = gateways.new_http_client()
    try:
        yield GatewayContext(_config_of(gateway, row), _secrets_of(row), client, webhook_url(name)[0])
    finally:
        client.close()


def test_gateway(name: str) -> dict[str, Any]:
    """The gateway's lightest safe call. Moves no money."""
    gateway = _installed(name)
    if not _configured(gateway, _row(name)):
        raise ValidationFailed("Enter every required setting and secret first")
    try:
        with gateway_context(name) as ctx:
            result = gateways.call(name, lambda: gateway.test_connection(ctx))
    except GatewayError as error:
        return {"ok": False, "message": error.message}
    return {"ok": result.ok, "message": result.message}


# --------------------------------------------------------------------------- what to offer
def tenant_country(tenant_id: UUID) -> str | None:
    """The business's country (its first company's), or None when none was entered."""
    try:
        with tenant_session(tenant_id, admin=True) as s:
            value = s.execute(text("select country from kernel.company order by created_at limit 1")).scalar()
    except Exception:  # noqa: BLE001 - an unreadable business database must not block paying
        return None
    return str(value).upper() if value else None


def options_for(tenant_id: UUID, invoice: dict[str, Any]) -> dict[str, Any]:
    """The ways this invoice can be paid now: the enabled, configured gateways serving its currency and country, the
    preferred ones first. With none, `options` is empty and the manual instructions apply."""
    currency = str(invoice["currency"]).strip().upper()
    country = tenant_country(tenant_id)
    options: list[dict[str, Any]] = []
    hints: list[str] = []
    for cls in gateways.installed():
        gateway = cls()
        row = _row(gateway.name)
        if not (row and row["enabled"] and _configured(gateway, row)):
            continue
        if gateway.countries and country and country not in gateway.countries:
            continue
        if gateway.currencies and currency not in gateway.currencies:
            if gateway.currency_hint:
                hints.append(gateway.currency_hint)
            continue
        defaults = set(row["default_for"] or [])
        options.append(
            {
                "provider": gateway.name,
                "label": gateway.pay_label,
                "flow": gateway.flow,
                "methods": list(gateway.methods),
                "payer_fields": [vars(f) for f in gateway.payer_fields],
                "preferred": bool(defaults & {currency, country or "-"}),
            }
        )
    options.sort(key=lambda o: (not o["preferred"], o["label"]))
    return {
        "invoice_id": invoice["id"],
        "currency": currency,
        "options": options,
        "hints": [] if options else sorted(set(hints)),
        "payment_instructions": settings.get("billing.payment_instructions"),
    }


# --------------------------------------------------------------------------- attempts
def phone_hash(phone: str) -> str:
    """The keyed hash a phone number is matched by (data requests); the number itself is never stored."""
    digits = "".join(c for c in phone if c.isdigit())
    key = get_settings().secret_key.encode()
    return hmac.new(key, b"payer-phone:" + digits.encode(), hashlib.sha256).hexdigest()


def _public(row: Any) -> dict[str, Any]:
    d = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    gateway = gateways.get_gateway(d["provider"])
    d["flow"] = gateway.flow if gateway else "redirect"
    d["provider_label"] = gateway.title if gateway else d["provider"]
    d["open"] = d["status"] in OPEN
    d["currency"] = str(d["currency"]).strip()
    created = d["created_at"]
    d["seconds_open"] = max(0, int((_now() - created).total_seconds())) if d["open"] else 0
    return d


def _event(m: Any, attempt_id: UUID, kind: str, detail: dict[str, Any] | None = None, key: str | None = None) -> None:
    m.execute(
        text(
            "insert into master.payment_attempt_event (attempt_id, kind, event_key, detail) values "
            "(:a, :k, :e, cast(:d as jsonb)) on conflict do nothing"
        ),
        {"a": str(attempt_id), "k": kind, "e": key, "d": json.dumps(detail, default=str) if detail else None},
    )


def get_attempt(attempt_id: UUID, *, tenant_id: UUID | None = None) -> dict[str, Any]:
    """One attempt; with `tenant_id` only if it is that business's."""
    with master_session() as m:
        row = m.execute(
            text(
                "select a.*, i.number as invoice_number, t.code as tenant_code, t.name as tenant_name from "
                "master.payment_attempt a join master.billing_invoice i on i.id = a.invoice_id join master.tenant t "
                "on t.id = a.tenant_id where a.id = :i"
            ),
            {"i": str(attempt_id)},
        ).first()
    if row is None or (tenant_id is not None and row.tenant_id != tenant_id):
        raise NotFound("No such payment")
    return _public(row)


def list_attempts(
    *,
    tenant_id: UUID | None = None,
    invoice_id: UUID | None = None,
    status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    with master_session() as m:
        rows = m.execute(
            text(
                "select a.*, i.number as invoice_number, t.code as tenant_code, t.name as tenant_name from "
                "master.payment_attempt a join master.billing_invoice i on i.id = a.invoice_id join master.tenant t "
                "on t.id = a.tenant_id where (cast(:t as uuid) is null or a.tenant_id = :t) and (cast(:i as uuid) "
                "is null or a.invoice_id = :i) and (cast(:s as text) is null or a.status = :s) and "
                "(cast(:f as timestamptz) is null or a.created_at >= :f) and (cast(:u as timestamptz) is null or "
                "a.created_at < :u) order by a.created_at desc limit :l offset :o"
            ),
            {
                "t": str(tenant_id) if tenant_id else None,
                "i": str(invoice_id) if invoice_id else None,
                "s": status,
                "f": since,
                "u": until,
                "l": limit,
                "o": offset,
            },
        )
        return [_public(r) for r in rows]


def timeline(attempt_id: UUID) -> list[dict[str, Any]]:
    with master_session() as m:
        return [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select occurred_at, kind, detail from master.payment_attempt_event where attempt_id = :a "
                    "order by id"
                ),
                {"a": str(attempt_id)},
            )
        ]


def _open_attempt(m: Any, invoice_id: UUID) -> Any:
    return m.execute(
        text("select * from master.payment_attempt where invoice_id = :i and status in ('initiated', 'pending')"),
        {"i": str(invoice_id)},
    ).first()


def _info(row: Any, invoice_number: str, payer: dict[str, str] | None = None) -> AttemptInfo:
    web = get_settings().public_web_url.rstrip("/")
    back = f"{web}/billing?attempt={row.id}"
    return AttemptInfo(
        reference=row.reference,
        invoice_number=invoice_number,
        amount=row.amount,
        currency=str(row.currency).strip(),
        description=f"Invoice {invoice_number}",
        payer=payer or {},
        provider_transaction_id=row.provider_transaction_id,
        checkout_request_id=row.checkout_request_id,
        return_url=f"{back}&payment=success",
        cancel_url=f"{back}&payment=cancelled",
    )


def start_payment(
    tenant_id: UUID,
    invoice_id: UUID,
    provider: str,
    payer: dict[str, str],
    *,
    by: str,
    contact_email: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Begin paying an invoice. A second call while an attempt is open returns that attempt (no second charge)."""
    moment = now or _now()
    invoice = billing.get_invoice(invoice_id, tenant_id=tenant_id)
    if invoice["status"] != "issued" or invoice["balance"] <= 0:
        raise Conflict("This invoice is not waiting for payment")
    offered = {o["provider"] for o in options_for(tenant_id, invoice)["options"]}
    if provider not in offered:
        hints = options_for(tenant_id, invoice)["hints"]
        raise ValidationFailed(hints[0] if hints else "This payment method is not available for this invoice")
    gateway = _installed(provider)
    clean = gateway.normalise_payer({k: str(v) for k, v in payer.items()})
    if "email" in {f.name for f in gateway.payer_fields} and not clean.get("email") and contact_email:
        clean["email"] = contact_email
    with master_session() as m:
        existing = _open_attempt(m, invoice_id)
    if existing is not None:
        if (moment - existing.created_at).total_seconds() < gateway.retry_after_seconds:
            return _public(get_attempt(existing.id))
        settle(existing.id, source="replaced")                     # it may have been paid after all
        with master_session() as m:
            still = _open_attempt(m, invoice_id)
            if still is not None:
                m.execute(
                    text("update master.payment_attempt set status = 'expired', updated_at = now(), result_desc = "
                         "'Replaced by a new attempt' where id = :i"),
                    {"i": str(still.id)},
                )
                _event(m, still.id, "replaced")
        if billing.get_invoice(invoice_id)["status"] != "issued":
            raise Conflict("This invoice has just been paid")
    with master_session() as m:
        recent = m.execute(
            text("select count(*) from master.payment_attempt where tenant_id = :t and created_at > :s"),
            {"t": str(tenant_id), "s": moment - timedelta(hours=1)},
        ).scalar_one()
    if recent >= RATE_LIMIT_PER_HOUR:
        raise TooManyRequests("Too many payment attempts this hour: wait a little, then try again")
    phone = clean.get("phone", "")
    try:
        with master_session() as m:
            row = m.execute(
                text(
                    "insert into master.payment_attempt (reference, invoice_id, tenant_id, provider, amount, currency, "
                    "payer_phone_last4, payer_phone_hash, payer_email, created_by) values (:r, :i, :t, :p, :a, :c, "
                    ":l4, :h, :e, :by) returning *"
                ),
                {
                    "r": f"zp-{uuid4().hex[:20]}",
                    "i": str(invoice_id),
                    "t": str(tenant_id),
                    "p": provider,
                    "a": invoice["balance"],
                    "c": invoice["currency"],
                    "l4": phone[-4:] if phone else None,
                    "h": phone_hash(phone) if phone else None,
                    "e": clean.get("email"),
                    "by": by,
                },
            ).one()
            _event(m, row.id, "created", {"provider": provider})
    except IntegrityError:                                          # a parallel click won the single open slot
        with master_session() as m:
            existing = _open_attempt(m, invoice_id)
        if existing is None:
            raise
        return _public(get_attempt(existing.id))
    try:
        with gateway_context(provider) as ctx:
            result = gateways.call(provider, lambda: gateway.start(ctx, _info(row, invoice["number"], clean)))
    except GatewayError as error:
        _fail(row.id, error.message, "start_failed")
        if error.retryable:
            raise Unavailable(f"{error.message}. Nothing has been confirmed: try again in a few minutes") from None
        raise ValidationFailed(error.message) from None
    with master_session() as m:
        m.execute(
            text(
                "update master.payment_attempt set status = 'pending', provider_transaction_id = :p, "
                "checkout_request_id = :c, redirect_url = :u, updated_at = now() where id = :i"
            ),
            {
                "p": result.provider_transaction_id,
                "c": result.checkout_request_id,
                "u": result.redirect_url,
                "i": str(row.id),
            },
        )
        _event(m, row.id, "started", {"message": result.message} if result.message else None)
    return get_attempt(row.id)


def _fail(attempt_id: UUID, reason: str, kind: str, status: str = "failed", code: str | None = None) -> None:
    with master_session() as m:
        m.execute(
            text(
                "update master.payment_attempt set status = :s, result_desc = :r, result_code = coalesce(:c, "
                "result_code), updated_at = now() where id = :i and status in ('initiated', 'pending')"
            ),
            {"s": status, "r": reason[:500], "c": code, "i": str(attempt_id)},
        )
        _event(m, attempt_id, kind, {"reason": reason[:300]})


# --------------------------------------------------------------------------- confirm, then credit
def settle(attempt_id: UUID, *, source: str, by: str | None = None) -> dict[str, Any]:
    """Ask the gateway what became of an open attempt, and act on its answer: credit a confirmed payment, record a
    failure, or leave a pending one. Safe to call from a webhook, the poller and a person at once."""
    attempt = get_attempt(attempt_id)
    if not attempt["open"]:
        return attempt
    gateway = gateways.get_gateway(attempt["provider"])
    if gateway is None:
        _touch(attempt_id)
        return get_attempt(attempt_id)
    info = _info(_Row(attempt), attempt["invoice_number"])
    try:
        with gateway_context(attempt["provider"]) as ctx:
            state = gateways.call(attempt["provider"], lambda: gateway.check(ctx, info))
    except GatewayError as error:
        with master_session() as m:
            m.execute(
                text("update master.payment_attempt set last_checked_at = now() where id = :i"),
                {"i": str(attempt_id)},
            )
            _event(m, attempt_id, "check_failed", {"reason": error.message, "retryable": error.retryable,
                                                   "source": source})
        return get_attempt(attempt_id)
    _apply(attempt_id, state, source, by)
    return get_attempt(attempt_id)


class _Row:
    """An attempt dict with attribute access (what `_info` reads)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.__dict__.update(data)


def _touch(attempt_id: UUID) -> None:
    with master_session() as m:
        m.execute(text("update master.payment_attempt set last_checked_at = now() where id = :i"),
                  {"i": str(attempt_id)})


def _apply(attempt_id: UUID, state: PaymentState, source: str, by: str | None) -> None:
    flagged: tuple[dict[str, Any], list[str]] | None = None
    credited: dict[str, Any] | None = None
    with master_session() as m:
        row = m.execute(
            text("select * from master.payment_attempt where id = :i for update"), {"i": str(attempt_id)}
        ).one()
        if row.status not in OPEN:
            return                                                  # someone else settled it while we asked
        invoice = billing.get_invoice(row.invoice_id)
        if state.status == "pending":
            m.execute(text("update master.payment_attempt set last_checked_at = now() where id = :i"),
                      {"i": str(attempt_id)})
            _event(m, attempt_id, "checked", {"status": "pending", "source": source})
            return
        if state.status == "failed":
            m.execute(
                text(
                    "update master.payment_attempt set status = 'failed', result_desc = :r, result_code = :c, "
                    "last_checked_at = now(), updated_at = now() where id = :i"
                ),
                {"r": (state.reason or "The payment was not completed")[:500], "c": state.code, "i": str(attempt_id)},
            )
            _event(m, attempt_id, "failed", {"reason": state.reason[:300], "source": source})
            return
        problems = _problems(row, invoice, state)
        if problems:
            m.execute(
                text(
                    "update master.payment_attempt set status = 'mismatch', result_desc = :r, last_checked_at = now(), "
                    "updated_at = now() where id = :i"
                ),
                {"r": "; ".join(problems)[:500], "i": str(attempt_id)},
            )
            _event(m, attempt_id, "mismatch", {"problems": problems, "source": source})
            flagged = (invoice, problems)
        else:
            reference = state.reference or row.reference
            already = m.execute(
                text(
                    "select 1 from master.billing_payment where invoice_id = :i and provider = :p and reference = :r "
                    "and reversed_at is null"
                ),
                {"i": str(row.invoice_id), "p": row.provider, "r": reference},
            ).first()
            gateway = gateways.get_gateway(row.provider)
            if already is None:
                billing.record_payment(
                    row.invoice_id,
                    method=gateway.payment_method if gateway else "online",
                    amount=row.amount,
                    reference=reference,
                    provider=row.provider,
                    by=by or f"provider:{row.provider}",
                )
            m.execute(
                text(
                    "update master.payment_attempt set status = 'completed', payment_reference = :r, completed_at = "
                    "now(), completed_by = :b, result_code = :c, result_desc = null, last_checked_at = now(), "
                    "updated_at = now() where id = :i"
                ),
                {"r": reference, "b": by or f"provider:{row.provider}", "c": state.code, "i": str(attempt_id)},
            )
            _event(m, attempt_id, "credited", {"reference": reference, "source": source})
            credited = billing.get_invoice(row.invoice_id)
    if flagged is not None:
        _tell_operators_of_mismatch(attempt_id, *flagged)
    if credited is not None:
        _send_receipt(credited, state.reference)


def _problems(row: Any, invoice: dict[str, Any], state: PaymentState) -> list[str]:
    found = []
    if state.amount is None or state.amount != row.amount:
        found.append(f"amount reported {state.amount} but {row.amount} was expected")
    if state.currency and state.currency.strip().upper() != str(row.currency).strip().upper():
        found.append(f"currency reported {state.currency} but {str(row.currency).strip()} was expected")
    if state.invoice_number and invoice["number"] and state.invoice_number != invoice["number"]:
        found.append(f"invoice reference reported {state.invoice_number} but {invoice['number']} was expected")
    if invoice["status"] != "issued" or invoice["balance"] < row.amount:
        found.append(f"the invoice is no longer open (status {invoice['status']}): money may need to be returned")
    return found


def _send_receipt(invoice: dict[str, Any], reference: str | None) -> None:
    web = get_settings().public_web_url.rstrip("/")
    try:
        billing._email_owners(
            invoice["tenant_id"],
            f"Receipt for invoice {invoice['number']}",
            f"Thank you. We received your payment for invoice {invoice['number']}: {invoice['total']} "
            f"{str(invoice['currency']).strip()}"
            + (f" (reference {reference})" if reference else "")
            + f".\nYour subscription is up to date. You can print the receipt from {web}/billing\n",
        )
    except Exception:  # noqa: BLE001 - the payment is recorded; a mail failure must not undo it
        log.warning("Could not send the receipt for %s", invoice["number"], exc_info=True)


def _tell_operators_of_mismatch(attempt_id: UUID, invoice: dict[str, Any], problems: list[str]) -> None:
    log.error("Payment attempt %s for invoice %s did not match: %s", attempt_id, invoice["number"], problems)
    with master_session() as m:
        emails = list(
            m.execute(
                text(
                    "select email from master.operator where status = 'active' and role in ('superadmin', 'billing') "
                    "order by email"
                )
            ).scalars()
        )
    extra = [x.strip() for x in str(settings.get("billing.notify_emails")).split(",") if x.strip()]
    from ziira.kernel import platform_mail

    for address in sorted({*emails, *extra}):
        try:
            platform_mail.send(
                address,
                f"Payment needs a look: invoice {invoice['number']}",
                f"A payment reported by the payment provider did not match invoice {invoice['number']} and was NOT "
                f"credited. {'; '.join(problems)}.\n\nOpen the Super Admin > Billing > Payment attempts "
                f"(attempt {attempt_id}) to review it.",
                "billing",
            )
        except Exception:  # noqa: BLE001
            log.warning("Could not tell %s about a payment mismatch", address, exc_info=True)


# --------------------------------------------------------------------------- notifications and recovery
def handle_webhook(provider: str, headers: dict[str, str], body: bytes) -> dict[str, int]:
    """A provider's notification. The signature is checked on the raw body before anything is read; a notification only
    makes us ask the provider about an attempt (`settle`). Unknown transactions and repeats are accepted and ignored. An
    internal failure raises, so the provider sends the notification again."""
    gateway = gateways.get_gateway(provider)
    row = _row(provider)
    if gateway is None or not row or not _secrets_of(row):
        raise NotFound("No such payment method")
    lowered = {k.lower(): v for k, v in headers.items()}
    with gateway_context(provider) as ctx:
        events = gateway.verify_webhook(ctx, lowered, body)         # ValidationFailed: not genuine
    handled = 0
    for event in events:
        if event.kind == "ignored":
            continue
        with master_session() as m:
            attempt = m.execute(
                text(
                    "select id from master.payment_attempt where provider = :p and ((cast(:t as text) is not null and "
                    "provider_transaction_id = :t) or (cast(:r as text) is not null and reference = :r)) "
                    "order by created_at desc limit 1"
                ),
                {"p": provider, "t": event.provider_transaction_id, "r": event.attempt_reference},
            ).first()
            if attempt is None:
                log.info("Notification from %s for an unknown transaction (%s)", provider, event.event_key[:40])
                continue
            seen = m.execute(
                text("select 1 from master.payment_attempt_event where attempt_id = :a and event_key = :k"),
                {"a": str(attempt.id), "k": event.event_key},
            ).first()
        if seen is not None:
            continue
        settle(attempt.id, source="webhook")
        with master_session() as m:
            _event(m, attempt.id, "notified", {"kind": event.kind}, key=event.event_key)
        handled += 1
    return {"handled": handled}


def recover_pending(*, now: datetime | None = None) -> dict[str, int]:
    """Ask about open attempts (every pass for young ones, hourly for older), fail the ones that never reached the
    provider, and expire those a day old. Repeating it changes nothing that is already settled."""
    moment = now or _now()
    counts = {"checked": 0, "expired": 0, "credited": 0, "failed": 0}
    with master_session() as m:
        open_rows = [dict(r._mapping) for r in m.execute(
            text("select id, created_at, last_checked_at, provider_transaction_id, checkout_request_id, status "
                 "from master.payment_attempt where status in ('initiated', 'pending') order by created_at"))]
    for row in open_rows:
        age = moment - row["created_at"]
        try:
            if row["status"] == "initiated" and age > NEVER_REACHED_AFTER:
                _fail(row["id"], "The request never reached the payment service", "never_reached")
                counts["failed"] += 1
                continue
            due = age < YOUNG or row["last_checked_at"] is None or moment - row["last_checked_at"] > OLD_RECHECK
            if due:
                result = settle(row["id"], source="recovery")
                counts["checked"] += 1
                if result["status"] == "completed":
                    counts["credited"] += 1
                if not result["open"]:
                    continue
            if age > EXPIRE_AFTER:
                _fail(row["id"], "No answer from the payment service within a day", "expired", status="expired")
                counts["expired"] += 1
        except Exception:  # noqa: BLE001 - one attempt must not stop the others
            log.exception("Recovery failed for attempt %s", row["id"])
    return counts


def recheck(attempt_id: UUID, *, tenant_id: UUID | None = None, by: str | None = None) -> dict[str, Any]:
    """Ask the provider now (the owner's "Check again", or an operator's "Re-check")."""
    get_attempt(attempt_id, tenant_id=tenant_id)
    return settle(attempt_id, source="manual_check", by=by)


def mark_paid_manually(attempt_id: UUID, reason: str, *, by: str) -> dict[str, Any]:
    """An operator confirms, outside the system, that an attempt was paid (for a stuck case). Credits through the same
    payment service as a manual payment, and says so in the timeline."""
    if len(reason.strip()) < 3:
        raise ValidationFailed("Say why")
    with master_session() as m:
        row = m.execute(
            text("select * from master.payment_attempt where id = :i for update"), {"i": str(attempt_id)}
        ).first()
        if row is None:
            raise NotFound("No such payment")
        if row.status == "completed":
            raise Conflict("This payment was already credited")
        invoice = billing.get_invoice(row.invoice_id)
        if invoice["status"] != "issued":
            raise Conflict("The invoice is not waiting for payment any more")
        billing.record_payment(
            row.invoice_id,
            method="manual",
            amount=min(row.amount, invoice["balance"]),
            reference=f"attempt {row.reference}",
            provider=row.provider,
            by=by,
        )
        m.execute(
            text(
                "update master.payment_attempt set status = 'completed', completed_at = now(), completed_by = :b, "
                "payment_reference = :r, result_desc = :d, updated_at = now() where id = :i"
            ),
            {"b": by, "r": f"attempt {row.reference}", "d": f"Marked paid by hand: {reason.strip()[:300]}",
             "i": str(attempt_id)},
        )
        _event(m, attempt_id, "marked_paid", {"by": by, "reason": reason.strip()[:300]})
    return get_attempt(attempt_id)


# --------------------------------------------------------------------------- choosing a plan by oneself
def subscribe(
    tenant_id: UUID,
    plan_code: str,
    *,
    interval: str | None,
    currency: str | None,
    coupon_code: str | None,
    by_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The owner picks a plan and interval: the usual plan request is made (so proration, coupons and entitlements stay
    in one place) and, where money is due now, approved at once so the invoice is ready to pay. Where nothing is due now
    (a change at the end of the period) it stays a request for the vendor, as before."""
    moment = now or _now()
    for old in billing.list_requests(tenant_id=tenant_id, status="pending"):
        billing.cancel_request(tenant_id, old["id"])
    with master_session() as m:
        stale = [
            r.id
            for r in m.execute(
                text(
                    "select i.id from master.billing_invoice i where i.tenant_id = :t and i.status = 'issued' and "
                    "i.plan_change is not null and i.amount_paid = 0 and not exists (select 1 from "
                    "master.payment_attempt a where a.invoice_id = i.id and a.status in ('initiated', 'pending'))"
                ),
                {"t": str(tenant_id)},
            )
        ]
    for invoice_id in stale:
        billing.void_invoice(invoice_id, "replaced by a new plan choice", by=by_name, now=moment)
    request = billing.request_plan_change(
        tenant_id, plan_code, interval=interval, currency=currency, coupon_code=coupon_code, note="",
        by_name=by_name, now=moment,
    )
    if request["invoice"] is None:
        return {"request": request, "invoice": None, "waiting_for_vendor": True}
    decided = billing.decide_request(request["id"], True, by="self-service", now=moment)
    return {"request": request, "invoice": decided["invoice"], "waiting_for_vendor": False}

"""Self-service registration: a person creates a business of their own.

    register  -> a request is saved (nothing is provisioned) and a verification link is emailed
    verify    -> the link proves the email; the business, its own database and its owner are created, the default units
                 are switched on, and the owner is signed in

The registration holds the owner's password already hashed, and the emailed token only as a hash. Abuse is limited by
rate (per email and per address), by mode (open, invitation code, or closed), and by the email step itself: a database
is created only after the link is used. Registering an email that already owns businesses is allowed (the login
directory lets one person work for several); the answer to `register` is the same whatever the address, so it
reveals nothing.
"""

import json
import logging
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import auth, company_settings, editions, industry, operators, packs, passwords, platform_mail
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import (
    Conflict,
    Forbidden,
    RegistrationFailed,
    TooManyRequests,
    Unauthorized,
    ValidationFailed,
)
from ziira.kernel.phone import check_calling_code, normalise_phone
from ziira.kernel.platform import behaviour, mail, plans, subscriptions
from ziira.kernel.registry import Registry
from ziira.kernel.security import hash_password, hash_secret, new_secret
from ziira.kernel.tenants import CODE_PATTERN, create_tenant, drop_tenant

log = logging.getLogger("ziira.registration")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TAX_ID = re.compile(r"^[A-Z0-9][A-Z0-9/\-. ]{2,29}$")
TOKEN_PREFIX = "zg_"
# Onboarding answers (hints only, never rules): the allowed values; anything else is refused.
ROLES = ("owner", "manager", "accountant", "other")
BUSINESS_SIZES = ("1", "2-5", "6-20", "more")           # branches
STAFF_SIZES = ("1-5", "6-20", "21-50", "more")
BUSINESS_TYPES = ("retail", "wholesale", "services", "other")
MODES = ("core", "standalone")      # older callers: 'core' is the full edition, 'standalone' the intelligence edition


def units_for_mode(mode: str) -> list[str]:
    """The units switched on for an older-style `mode` ('core' = full edition, 'standalone' = intelligence edition)."""
    return list(editions.get(editions.resolve(mode=mode)).units)


@dataclass(frozen=True)
class Started:
    """What `register` hands back. `dev_token` is only given outside production (tests and local development), where
    no real mailbox is read. `instant_token` is given when the platform has no working email: nothing could be sent,
    so the person goes straight on (the client uses it at once) instead of waiting for a link that cannot arrive."""

    dev_token: str | None
    instant_token: str | None = None


@dataclass(frozen=True)
class Completed:
    tokens: auth.Tokens
    workspace: str
    business_name: str


def _clean(value: str, what: str, low: int, high: int) -> str:
    text_ = " ".join(value.split())
    if not low <= len(text_) <= high:
        raise ValidationFailed(f"{what} must be {low} to {high} characters")
    return text_


@contextmanager
def _field(name: str) -> Iterator[None]:
    """A validation failure inside names the field of the request it belongs to, so a form can show it there."""
    try:
        yield
    except ValidationFailed as problem:
        raise ValidationFailed(problem.message, {**(problem.details or {}), "field": name}) from None


def _industry_pack_names() -> tuple[str, ...]:
    """The installed industry packs a business can name as its kind of business (the Services edition asks)."""
    try:
        reg = Registry()
        installed = reg.installed()
        return tuple(m.name for m in industry.installed_packs(reg.units) if m.name in installed)
    except Exception:  # noqa: BLE001 - never stop a registration for a pack lookup
        return ()


def _choice(value: str | None, allowed: tuple[str, ...], what: str) -> str | None:
    """An optional answer that must be one of the offered values."""
    if value is None or not value.strip():
        return None
    if value not in allowed:
        raise ValidationFailed(f"{what} must be one of: {', '.join(allowed)}")
    return value


def invite_hash(code: str) -> str:
    return hash_secret("invite:" + code.strip().upper())


def create_invite(*, uses: int = 1, days: int | None = 30, note: str | None = None) -> str:
    """Make an invitation code (shown once). Operators hand it to the people they want to register."""
    if uses < 1 or uses > 10000:
        raise ValidationFailed("Uses is from 1 to 10000")
    code = "INV-" + secrets.token_hex(5).upper()
    expires = datetime.now(UTC) + timedelta(days=days) if days else None
    with master_session() as s:
        s.execute(text("insert into master.invite_code (code_hash, uses_left, expires_at, note) "
                       "values (:h, :u, :e, :n)"), {"h": invite_hash(code), "u": uses, "e": expires, "n": note})
    return code


def _check_invite(code: str | None) -> str:
    if not code or not code.strip():
        raise Forbidden("Registration needs an invitation code", {"field": "invite_code"})
    with master_session() as s:
        row = s.execute(text(
            "select 1 from master.invite_code where code_hash = :h and uses_left > 0 "
            "and (expires_at is null or expires_at > now())"), {"h": invite_hash(code)}).first()
    if row is None:
        raise Forbidden("That invitation code is not valid")
    return invite_hash(code)


def register(*, business_name: str, owner_name: str, email: str, password: str, currency: str,
             phone_country_code: str = "", country: str | None = None, tax_id: str | None = None,
             timezone: str | None = None, invite_code: str | None = None, ip_address: str | None = None,
             mode: str | None = None, edition: str | None = None, phone: str | None = None,
             owner_role: str | None = None, business_size: str | None = None, staff_size: str | None = None,
             business_type: str | None = None, plan: str | None = None) -> Started:
    """Ask for a business. Saves the request and emails a verification link (or, when the platform has no working
    email, hands back a token to use at once); creates nothing else."""
    settings = get_settings()
    mode_now = behaviour.registration_mode()
    if mode_now == "closed":
        raise Forbidden("Registration is closed: ask the operator to create your business")
    with _field("business_name"):
        business = _clean(business_name, "The business name", 2, 120)
    with _field("owner_name"):
        owner = _clean(owner_name, "Your name", 2, 120)
    address = email.strip().lower()
    with _field("email"):
        if len(address) > 200 or not EMAIL.match(address):
            raise ValidationFailed("That email address does not look right")
    currency = currency.strip().upper()
    with _field("currency"):
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValidationFailed("Currency is a three-letter code such as USD")
    with _field("phone_country_code"):
        code = check_calling_code(phone_country_code)
    with _field("timezone"):
        zone = str(company_settings.SETTINGS["timezone"].parse(timezone)) if timezone and timezone.strip() else None
    nation = country.strip().upper() if country and country.strip() else None
    with _field("country"):
        if nation is not None and not re.fullmatch(r"[A-Z]{2}", nation):
            raise ValidationFailed("Country is a two-letter code such as GB")
    tax = " ".join(tax_id.upper().split()) if tax_id and tax_id.strip() else None
    with _field("tax_id"):
        if tax is not None and not TAX_ID.match(tax):
            raise ValidationFailed("A tax number is 3 to 30 letters, digits, '-', '/' or '.'")
    if mode is not None and mode not in MODES:
        raise ValidationFailed("Mode is 'core' (run the business on Ziira) or 'standalone' (watch the system you have)")
    chosen = editions.resolve(edition, mode)
    with _field("phone"):
        contact = normalise_phone(phone, code) if phone and phone.strip() else None
    hints: dict[str, str | None] = {}
    for name, value, allowed, label in (
            ("owner_role", owner_role, ROLES, "Role"), ("business_size", business_size, BUSINESS_SIZES, "Branches"),
            ("staff_size", staff_size, STAFF_SIZES, "Staff"),
            ("business_type", business_type, (*BUSINESS_TYPES, *_industry_pack_names()), "Kind of business")):
        with _field(name):
            hints[name] = _choice(value, allowed, label)
    legacy_mode = "standalone" if chosen == "intelligence" else "core"
    plan_code = plan.strip() if plan and plan.strip() in _public_plan_codes() else None     # unknown plans are ignored
    with _field("password"):
        passwords.check(password, login=address)                              # length, common passwords, not the email
        password_hash = hash_password(password)
    invite = _check_invite(invite_code) if mode_now == "invite" else None

    since = datetime.now(UTC) - timedelta(hours=1)
    with master_session() as s:
        by_email = s.execute(text("select count(*) from master.registration where email = :e and created_at > :t"),
                             {"e": address, "t": since}).scalar_one()
        by_ip = (s.execute(text("select count(*) from master.registration where ip_address = :i and created_at > :t"),
                           {"i": ip_address, "t": since}).scalar_one() if ip_address else 0)
        if by_email >= settings.registration_per_email_per_hour or by_ip >= settings.registration_per_ip_per_hour:
            raise TooManyRequests("Too many registration attempts: please try again in an hour", {"retry_after": 3600})
        token = TOKEN_PREFIX + new_secret()
        # an earlier unverified request for this email stops working (its row stays: it counts towards the rate limit)
        s.execute(text("update master.registration set expires_at = now() where email = :e and verified_at is null "
                       "and expires_at > now()"), {"e": address})
        s.execute(text(
            "insert into master.registration (email, business_name, owner_name, password_hash, currency, "
            "phone_country_code, country, timezone, tax_id, invite_code_hash, token_hash, ip_address, expires_at, "
            "mode, edition, phone, owner_role, business_size, staff_size, business_type, plan_code) "
            "values "
            "(:e, :b, :o, :p, :c, :pc, :n, :z, :t, :i, :h, :ip, :x, :m, :ed, :ph, :ro, :bs, :ss, :bt, :pl)"),
            {"e": address, "b": business, "o": owner, "p": password_hash, "c": currency, "pc": code, "n": nation,
             "z": zone, "t": tax, "i": invite, "h": hash_secret(token), "ip": ip_address, "m": legacy_mode,
             "ed": chosen, "ph": contact, "ro": hints["owner_role"], "bs": hints["business_size"],
             "ss": hints["staff_size"], "bt": hints["business_type"], "pl": plan_code,
             "x": datetime.now(UTC) + timedelta(hours=settings.registration_token_hours)})
    if not mail.status()["working"] and settings.env == "production":
        return Started(dev_token=None, instant_token=token)      # no email to send: the owner set the password just now
    link = f"{behaviour.public_web_url()}/register/verify?token={token}"
    platform_mail.send(address, "Confirm your email to create your business",
                       f"Hello {owner},\n\nTo finish creating {business}, confirm your email address:\n\n{link}\n\n"
                       f"The link works for {settings.registration_token_hours} hours and only once. If you did not "
                       "ask for this, ignore this message: nothing will be created.\n", "registration")
    return Started(dev_token=token if settings.env != "production" else None)


def _workspace_code(name: str) -> str:
    """A free workspace code from a business name: letters and digits, with '-', made unique with a number."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:34].strip("-")
    if len(base) < 2:
        base = "business"
    with master_session() as s:
        taken = {r[0] for r in s.execute(text("select code from master.tenant where code like :p"), {"p": base + "%"})}
    for n in range(1, 200):
        candidate = base if n == 1 else f"{base}-{n}"
        if candidate not in taken and CODE_PATTERN.match(candidate):
            return candidate
    return f"{base[:30]}-{secrets.token_hex(3)}"


def complete(token: str, *, device_id: str, device_name: str | None = None,
             ip_address: str | None = None) -> Completed:
    """Use the emailed link: create the business and sign its owner in. The link works once."""
    if not token.startswith(TOKEN_PREFIX) or not device_id.strip():
        raise Unauthorized("This link is not valid")
    with master_session() as s:
        row = s.execute(text("select * from master.registration where token_hash = :h for update"),
                        {"h": hash_secret(token)}).first()
        if row is None or row.expires_at < datetime.now(UTC):
            raise Unauthorized("This link is not valid or has expired: register again")
        if row.verified_at is not None:
            raise Conflict("This link has already been used: sign in with your email and password")
        if row.invite_code_hash:
            used = s.execute(text("update master.invite_code set uses_left = uses_left - 1 where code_hash = :h "
                                  "and uses_left > 0 and (expires_at is null or expires_at > now()) returning id"),
                             {"h": row.invite_code_hash}).first()
            if used is None:
                raise Forbidden("The invitation code has been used up")
        s.execute(text("update master.registration set verified_at = now() where id = :i"), {"i": str(row.id)})
    code = _workspace_code(row.business_name)
    created: Any = None
    try:
        registry = Registry()
        created = create_tenant(
            name=row.business_name, code=code, company=row.business_name, branch_code="HQ", branch_name="Head office",
            owner_name=row.owner_name, owner_email=row.email, owner_password_hash=row.password_hash,
            currency=row.currency, phone_country_code=row.phone_country_code, country=row.country,
            timezone=row.timezone, tax_id=row.tax_id, edition=row.edition, registry=registry)
        editions.enable_edition(registry, created.tenant_id, row.edition)
    except Exception:
        log.exception("Could not create the business for registration %s", row.id)
        _undo(row.id, created)
        raise RegistrationFailed(
            "Your business could not be created right now. Nothing was kept: please try the link again in a minute.",
            {"registration": str(row.id)}) from None
    with master_session() as s:
        s.execute(text("update master.registration set tenant_id = :t where id = :i"),
                  {"t": str(created.tenant_id), "i": str(row.id)})
    # The business exists. Everything below is optional: a failure is logged, flagged to the operators and retried
    # later by the worker (`repair_pending`); it never loses the business or stops the owner signing in.
    detail = {"country": row.country, "edition": row.edition, "currency": row.currency, "plan": row.plan_code,
              "business_type": row.business_type}
    _optional_step(row.id, created.tenant_id, code, "pack", detail)
    _optional_step(row.id, created.tenant_id, code, "plan", detail)
    _optional_step(row.id, created.tenant_id, code, "hints", {"role": row.owner_role, "phone": row.phone,
                                                              "business_size": row.business_size,
                                                              "staff_size": row.staff_size,
                                                              "business_type": row.business_type})
    tokens = auth.open_session_for(created.tenant_id, created.owner_id, device_id=device_id, device_name=device_name,
                                   ip_address=ip_address)
    return Completed(tokens, code, row.business_name)


# --------------------------------------------------------------------------- optional steps and their repair
def _do_step(step: str, tenant_id: UUID, detail: dict[str, Any]) -> None:
    """One optional step of setting a business up. Each is safe to run again."""
    if step == "pack":
        registry = Registry()
        packs.enable_country_pack(registry, tenant_id, detail.get("country"))
        packs.apply_to_tenant(tenant_id)
        kind = str(detail.get("business_type") or "")
        if kind in _industry_pack_names():            # the Services edition asks what kind of service business
            registry.enable(tenant_id, kind)           # switching it on seeds it (safe to repeat)
    elif step == "plan":
        if subscriptions.get(tenant_id) is None:                                        # already started: nothing to do
            _start_trial(tenant_id, detail)
    elif step == "hints":
        with master_session() as s:
            s.execute(text("update master.tenant set onboarding = cast(:o as jsonb) where id = :t"),
                      {"o": json.dumps({k: v for k, v in detail.items() if v}), "t": str(tenant_id)})
    else:
        raise ValueError(f"unknown setup step {step}")


def _public_plan_codes() -> set[str]:
    try:
        return {str(p["code"]) for p in plans.public_plans()["plans"]}
    except Exception:  # noqa: BLE001 - a plan lookup problem must not stop a registration being asked for
        return set()


def trial_offer(edition: str | None, plan: str | None = None) -> dict[str, Any] | None:
    """The trial a new business would start on: the public plan the person arrived from, else the platform's default
    plan. None when there is none (an unmanaged business) or when this installation does not bill. Nothing is invented:
    only the plan's name and its trial length."""
    if get_settings().deployment_mode == "selfhosted":
        return None
    try:
        chosen = editions.resolve(edition, None) if edition else None
    except ValidationFailed:
        chosen = None                                                  # an unknown edition is ignored here
    code = plan.strip() if plan and plan.strip() in _public_plan_codes() else subscriptions.default_plan_code(chosen)
    if not code:
        return None
    try:
        found = plans.get_plan(code)
    except Exception:  # noqa: BLE001
        return None
    if found["status"] != "active" or not found["trial_days"]:
        return None
    return {"plan_code": str(found["code"]), "plan_name": str(found["name"]),
            "trial_days": behaviour.trial_days(int(found["trial_days"]))}


def _start_trial(tenant_id: UUID, detail: dict[str, Any]) -> None:
    """Start the trial: on the plan the person arrived from when it is still public, else the default plan."""
    chosen = detail.get("plan")
    if chosen and chosen in _public_plan_codes() and get_settings().deployment_mode != "selfhosted":
        subscriptions.start(tenant_id, chosen, currency=str(detail.get("currency") or ""), mode="trial")
        subscriptions.enforce_units(tenant_id)
        return
    subscriptions.start_for_registration(tenant_id, detail.get("edition"), str(detail.get("currency") or ""))


def _optional_step(registration_id: UUID | None, tenant_id: UUID, workspace: str, step: str,
                   detail: dict[str, Any]) -> bool:
    """Run an optional step; on failure keep the business, log it with the registration id, flag it to the operators
    and queue the step for repair. Returns whether it worked."""
    try:
        _do_step(step, tenant_id, detail)
        return True
    except Exception as exc:  # noqa: BLE001 - an optional step must never lose a business that was just made
        log.exception("Registration %s: setup step '%s' failed for business %s; it will be retried",
                      registration_id, step, workspace)
        _flag_failed_step(registration_id, tenant_id, workspace, step, detail, exc)
        return False


def _flag_failed_step(registration_id: UUID | None, tenant_id: UUID, workspace: str, step: str,
                      detail: dict[str, Any], exc: Exception) -> None:
    """Queue the step for repair and write it to the operators' trail. Must not raise."""
    message = f"{type(exc).__name__}: {exc}"[:500]
    try:
        if step != "hints":
            with master_session() as s:
                s.execute(text(
                    "insert into master.registration_repair (tenant_id, registration_id, step, detail, error) "
                    "values (:t, :r, :s, cast(:d as jsonb), :e) "
                    "on conflict (tenant_id, step) where resolved_at is null "
                    "do update set error = :e, last_attempt_at = now()"),
                    {"t": str(tenant_id), "r": str(registration_id) if registration_id else None, "s": step,
                     "d": json.dumps(detail), "e": message})
        operators.audit_sign_in("registration.setup_step_failed", None, "system", outcome="failed", target=workspace,
                                detail={"step": step, "registration": str(registration_id), "error": message},
                                ip_address=None)
    except Exception:  # noqa: BLE001
        log.exception("Could not record the failed setup step '%s' for %s", step, workspace)


def repair_pending(*, limit: int = 20, max_attempts: int = 12) -> int:
    """Retry the optional setup steps that failed at registration (the worker calls this every minute). Returns how many
    were repaired. A step that keeps failing is left (after `max_attempts`) for an operator, who sees it in the log."""
    with master_session() as s:
        rows = s.execute(text(
            "select r.id, r.tenant_id, r.step, r.detail, r.attempts from master.registration_repair r "
            "join master.tenant t on t.id = r.tenant_id "
            "where r.resolved_at is null and r.attempts < :m and r.last_attempt_at < now() - interval '30 seconds' "
            "order by r.created_at limit :n"), {"m": max_attempts, "n": limit}).all()
    fixed = 0
    for row in rows:
        try:
            _do_step(row.step, row.tenant_id, dict(row.detail or {}))
        except Exception as exc:  # noqa: BLE001
            log.warning("Setup step '%s' for %s failed again: %s", row.step, row.tenant_id, exc)
            with master_session() as s:
                s.execute(text("update master.registration_repair set attempts = attempts + 1, error = :e, "
                               "last_attempt_at = now() where id = :i"), {"e": str(exc)[:500], "i": str(row.id)})
            continue
        with master_session() as s:
            s.execute(text("update master.registration_repair set resolved_at = now(), last_attempt_at = now() "
                           "where id = :i"), {"i": str(row.id)})
        fixed += 1
    return fixed


def _undo(registration_id: UUID, created: object | None) -> None:
    """Make the link usable again after a failed provisioning, and remove what was half made."""
    tenant_id = getattr(created, "tenant_id", None)
    if tenant_id is not None:
        try:
            drop_tenant(tenant_id)
        except Exception:
            log.exception("Could not remove the half-made business %s", tenant_id)
    with master_session() as s:
        s.execute(text("update master.registration set verified_at = null where id = :i and tenant_id is null"),
                  {"i": str(registration_id)})


def purge(days: int = 7) -> int:
    """Delete registrations that expired more than `days` days ago, or that were verified long ago (the business has
    them in its own records). Returns how many."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with master_session() as s:
        gone = s.execute(text("delete from master.registration where (expires_at < :c and verified_at is null) "
                              "or (verified_at is not null and verified_at < :c) returning id"), {"c": cutoff}).all()
    return len(gone)

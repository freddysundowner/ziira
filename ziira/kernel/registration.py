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

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import auth, company_settings, platform_mail
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, Forbidden, TooManyRequests, Unauthorized, Unavailable, ValidationFailed
from ziira.kernel.phone import check_calling_code
from ziira.kernel.registry import Registry
from ziira.kernel.security import hash_password, hash_secret, new_secret
from ziira.kernel.tenants import CODE_PATTERN, create_tenant, drop_tenant

log = logging.getLogger("ziira.registration")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TAX_ID = re.compile(r"^[A-Z0-9][A-Z0-9/\-. ]{2,29}$")
TOKEN_PREFIX = "zg_"
MODES = ("core", "standalone")


def units_for_mode(mode: str) -> list[str]:
    """The units switched on for a new business: the business modules ('core') or just what Ziira needs to watch the
    system the business already has ('standalone'). Both lists are settings (`ZIIRA_REGISTRATION_UNITS`,
    `ZIIRA_STANDALONE_UNITS`)."""
    settings = get_settings()
    raw = settings.standalone_units if mode == "standalone" else settings.registration_units
    return [u.strip() for u in raw.split(",") if u.strip()]


@dataclass(frozen=True)
class Started:
    """What `register` hands back. The token is only given outside production (tests and local development), where
    no real mailbox is read."""

    dev_token: str | None


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
        raise Forbidden("Registration needs an invitation code")
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
             mode: str = "core") -> Started:
    """Ask for a business. Saves the request and emails a verification link; creates nothing else."""
    settings = get_settings()
    if settings.registration_mode == "closed":
        raise Forbidden("Registration is closed: ask the operator to create your business")
    business = _clean(business_name, "The business name", 2, 120)
    owner = _clean(owner_name, "Your name", 2, 120)
    address = email.strip().lower()
    if len(address) > 200 or not EMAIL.match(address):
        raise ValidationFailed("That email address does not look right")
    currency = currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValidationFailed("Currency is a three-letter code such as USD")
    code = check_calling_code(phone_country_code)
    zone = str(company_settings.SETTINGS["timezone"].parse(timezone)) if timezone and timezone.strip() else None
    nation = country.strip().upper() if country and country.strip() else None
    if nation is not None and not re.fullmatch(r"[A-Z]{2}", nation):
        raise ValidationFailed("Country is a two-letter code such as GB")
    tax = " ".join(tax_id.upper().split()) if tax_id and tax_id.strip() else None
    if tax is not None and not TAX_ID.match(tax):
        raise ValidationFailed("A tax number is 3 to 30 letters, digits, '-', '/' or '.'")
    if mode not in MODES:
        raise ValidationFailed("Mode is 'core' (run the business on Ziira) or 'standalone' (watch the system you have)")
    password_hash = hash_password(password)                                   # checks the password's length
    invite = _check_invite(invite_code) if settings.registration_mode == "invite" else None

    since = datetime.now(UTC) - timedelta(hours=1)
    with master_session() as s:
        by_email = s.execute(text("select count(*) from master.registration where email = :e and created_at > :t"),
                             {"e": address, "t": since}).scalar_one()
        by_ip = (s.execute(text("select count(*) from master.registration where ip_address = :i and created_at > :t"),
                           {"i": ip_address, "t": since}).scalar_one() if ip_address else 0)
        if by_email >= settings.registration_per_email_per_hour or by_ip >= settings.registration_per_ip_per_hour:
            raise TooManyRequests("Too many registration attempts: please try again in an hour")
        token = TOKEN_PREFIX + new_secret()
        # an earlier unverified request for this email stops working (its row stays: it counts towards the rate limit)
        s.execute(text("update master.registration set expires_at = now() where email = :e and verified_at is null "
                       "and expires_at > now()"), {"e": address})
        s.execute(text(
            "insert into master.registration (email, business_name, owner_name, password_hash, currency, "
            "phone_country_code, country, timezone, tax_id, invite_code_hash, token_hash, ip_address, expires_at, "
            "mode) "
            "values "
            "(:e, :b, :o, :p, :c, :pc, :n, :z, :t, :i, :h, :ip, :x, :m)"),
            {"e": address, "b": business, "o": owner, "p": password_hash, "c": currency, "pc": code, "n": nation,
             "z": zone, "t": tax, "i": invite, "h": hash_secret(token), "ip": ip_address, "m": mode,
             "x": datetime.now(UTC) + timedelta(hours=settings.registration_token_hours)})
    link = f"{settings.public_web_url.rstrip('/')}/register/verify?token={token}"
    platform_mail.send(address, "Confirm your email to create your business",
                       f"Hello {owner},\n\nTo finish creating {business}, confirm your email address:\n\n{link}\n\n"
                       f"The link works for {settings.registration_token_hours} hours and only once. If you did not "
                       "ask for this, ignore this message: nothing will be created.\n")
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
    try:
        registry = Registry()
        created = create_tenant(
            name=row.business_name, code=code, company=row.business_name, branch_code="HQ", branch_name="Head office",
            owner_name=row.owner_name, owner_email=row.email, owner_password_hash=row.password_hash,
            currency=row.currency, phone_country_code=row.phone_country_code, country=row.country,
            timezone=row.timezone, tax_id=row.tax_id, registry=registry)
        for unit in units_for_mode(row.mode):
            registry.enable(created.tenant_id, unit)
    except Exception:
        log.exception("Could not create the business for registration %s", row.id)
        _undo(row.id, locals().get("created"))
        raise Unavailable("Your business could not be created right now. Please try the link in a minute.") from None
    with master_session() as s:
        s.execute(text("update master.registration set tenant_id = :t where id = :i"),
                  {"t": str(created.tenant_id), "i": str(row.id)})
    tokens = auth.open_session_for(created.tenant_id, created.owner_id, device_id=device_id, device_name=device_name,
                                   ip_address=ip_address)
    return Completed(tokens, code, row.business_name)


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

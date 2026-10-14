"""Second factor: time-based one-time codes (RFC 6238, what authenticator apps make) and backup codes.

- A person sets it up (`setup` gives a secret and an `otpauth://` address for the app's QR code), proves the app
  works by typing a code (`enable`, which also gives ten single-use backup codes, shown once), and from then on
  every sign-in asks for a code after the password. Disabling needs the password and a code; an administrator can
  reset it for someone who lost their phone (that signs them out everywhere).
- A code works once (the counter it was made for is remembered), a code from the previous or next 30 seconds is
  accepted for clock drift, and wrong codes count against the same throttle as passwords.
- The business chooses who must use it (`kernel.tenant.mfa_policy`): nobody, people with powerful roles, or everyone.
  Someone who must but has not set it up gets a session that can only do the setup.
- The secret is stored encrypted; backup codes only as hashes.
"""

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.config import get_settings
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.security import decrypt, encrypt

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
BACKUP_CODE_COUNT = 10
POLICIES = ("off", "privileged", "everyone")

# Permissions that make a role powerful enough to need a second factor under the "privileged" policy.
PRIVILEGED_PERMISSIONS = frozenset({
    "users.manage", "roles.manage", "settings.manage", "api_keys.manage", "approvals.manage", "accounts.manage",
    "journal.approve", "period.close", "expenses.approve", "payroll.approve", "payroll.pay", "payroll.rates",
    "employee.pay_edit", "privacy.manage", "imports.manage",
})


def _now() -> float:
    """The clock the codes are checked against (a seam, so tests can move time)."""
    return time.time()


# --------------------------------------------------------------------------- the algorithm
def hotp(secret: bytes, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226: the code for a counter."""
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(number).zfill(digits)


def counter_at(moment: float) -> int:
    return int(moment // STEP_SECONDS)


def totp(secret: bytes, moment: float, digits: int = DIGITS) -> str:
    """RFC 6238: the code at a moment."""
    return hotp(secret, counter_at(moment), digits)


def match(secret: bytes, code: str, moment: float, after_counter: int = 0) -> int | None:
    """The counter the code was made for if valid now (within the drift) and newer than `after_counter`, else None."""
    clean = code.strip().replace(" ", "")
    if not (clean.isdigit() and len(clean) == DIGITS):
        return None
    now = counter_at(moment)
    for counter in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        if counter > after_counter and hmac.compare_digest(hotp(secret, counter), clean):
            return counter
    return None


def new_secret() -> str:
    """A new shared secret, as base32 text (what authenticator apps take)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _secret_bytes(b32: str) -> bytes:
    return base64.b32decode(b32 + "=" * (-len(b32) % 8))


def otpauth_uri(secret_b32: str, account: str) -> str:
    issuer = get_settings().mfa_issuer
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


_BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"          # no look-alike characters


def new_backup_codes(count: int = BACKUP_CODE_COUNT) -> list[str]:
    def one() -> str:
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"

    return [one() for _ in range(count)]


def _backup_hash(code: str) -> str:
    return hashlib.sha256(code.strip().lower().replace("-", "").encode()).hexdigest()


# --------------------------------------------------------------------------- state
def status(s: Session, user_id: UUID) -> dict[str, object]:
    row = s.execute(text("select confirmed_at, backup_hashes from kernel.user_mfa where user_id = :u"),
                    {"u": str(user_id)}).first()
    enabled = bool(row and row.confirmed_at)
    return {"enabled": enabled, "backup_codes_left": len(row.backup_hashes) if enabled and row else 0,
            "policy": policy(s), "required": required_for(s, user_id)}


def is_enabled(s: Session, user_id: UUID) -> bool:
    return s.execute(text("select 1 from kernel.user_mfa where user_id = :u and confirmed_at is not null"),
                     {"u": str(user_id)}).first() is not None


def policy(s: Session) -> str:
    value = s.execute(text("select mfa_policy from kernel.tenant where id = kernel.current_tenant()")).scalar()
    return str(value or "off")


def set_policy(s: Session, value: str) -> str:
    if value not in POLICIES:
        raise ValidationFailed(f"Policy must be one of: {', '.join(POLICIES)}")
    before = policy(s)
    s.execute(text("update kernel.tenant set mfa_policy = :p where id = kernel.current_tenant()"), {"p": value})
    audit.record(s, "mfa_policy", "kernel.tenant", None, {"from": before, "to": value})
    return value


def required_for(s: Session, user_id: UUID) -> bool:
    """True if the business's policy makes a second factor compulsory for this person."""
    chosen = policy(s)
    if chosen == "everyone":
        return True
    if chosen != "privileged":
        return False
    return s.execute(text(
        "select 1 from kernel.user_role ur join kernel.role_permission rp on rp.role_id = ur.role_id "
        "where ur.user_id = :u and rp.permission_code = any(:p) limit 1"),
        {"u": str(user_id), "p": sorted(PRIVILEGED_PERMISSIONS)}).first() is not None


def must_set_up(s: Session, user_id: UUID) -> bool:
    """Compulsory but not yet set up: the session may only do the setup."""
    return required_for(s, user_id) and not is_enabled(s, user_id)


# --------------------------------------------------------------------------- set up, use, switch off
def setup(s: Session, user_id: UUID, account: str) -> tuple[str, str]:
    """Start setting up: returns the secret and the address for the QR code. Nothing is switched on until a code from
    the app is confirmed (`enable`); starting again replaces an unconfirmed secret."""
    if is_enabled(s, user_id):
        raise ValidationFailed("Two-step verification is already on; switch it off first to set it up again")
    secret = new_secret()
    s.execute(text(
        "insert into kernel.user_mfa (user_id, tenant_id, secret_enc) values (:u, kernel.current_tenant(), :e) "
        "on conflict (user_id) do update set secret_enc = :e, confirmed_at = null, last_counter = 0, "
        "backup_hashes = '[]'::jsonb"), {"u": str(user_id), "e": encrypt(secret)})
    return secret, otpauth_uri(secret, account)


def enable(s: Session, user_id: UUID, code: str) -> list[str]:
    """Confirm the app works (a current code) and switch it on. Returns the backup codes: shown once."""
    row = s.execute(text("select secret_enc, confirmed_at from kernel.user_mfa where user_id = :u for update"),
                    {"u": str(user_id)}).first()
    if row is None or row.confirmed_at is not None:
        raise ValidationFailed("Start the setup first")
    counter = match(_secret_bytes(decrypt(row.secret_enc)), code, _now())
    if counter is None:
        raise ValidationFailed("That code is not right: check the app and try the next one")
    codes = new_backup_codes()
    s.execute(text("update kernel.user_mfa set confirmed_at = now(), last_counter = :c, "
                   "backup_hashes = cast(:h as jsonb) where user_id = :u"),
              {"c": counter, "h": json.dumps([_backup_hash(c) for c in codes]), "u": str(user_id)})
    s.execute(text("update kernel.app_user set mfa_enabled = true where id = :u"), {"u": str(user_id)})
    audit.record(s, "mfa_enabled", "kernel.app_user", user_id)
    return codes


def verify(s: Session, user_id: UUID, code: str) -> bool:
    """Check a code at sign-in: an authenticator code (once) or a backup code (once). Locks the row so two attempts at
    the same moment cannot both use one code."""
    row = s.execute(text("select secret_enc, last_counter, backup_hashes from kernel.user_mfa "
                         "where user_id = :u and confirmed_at is not null for update"), {"u": str(user_id)}).first()
    if row is None:
        return False
    counter = match(_secret_bytes(decrypt(row.secret_enc)), code, _now(), after_counter=row.last_counter)
    if counter is not None:
        s.execute(text("update kernel.user_mfa set last_counter = :c where user_id = :u"),
                  {"c": counter, "u": str(user_id)})
        return True
    digest = _backup_hash(code)
    remaining: list[str] = list(row.backup_hashes)
    if digest in remaining:
        remaining.remove(digest)
        s.execute(text("update kernel.user_mfa set backup_hashes = cast(:h as jsonb) where user_id = :u"),
                  {"h": json.dumps(remaining), "u": str(user_id)})
        audit.record(s, "mfa_backup_code_used", "kernel.app_user", user_id, {"left": len(remaining)})
        return True
    return False


def regenerate_backup_codes(s: Session, user_id: UUID) -> list[str]:
    if not is_enabled(s, user_id):
        raise ValidationFailed("Two-step verification is not on")
    codes = new_backup_codes()
    s.execute(text("update kernel.user_mfa set backup_hashes = cast(:h as jsonb) where user_id = :u"),
              {"h": json.dumps([_backup_hash(c) for c in codes]), "u": str(user_id)})
    audit.record(s, "mfa_backup_codes_renewed", "kernel.app_user", user_id)
    return codes


def disable(s: Session, user_id: UUID, *, by_admin: bool = False) -> None:
    """Switch it off (the caller has checked the password and a code, or the administrator's permission)."""
    s.execute(text("delete from kernel.user_mfa where user_id = :u"), {"u": str(user_id)})
    s.execute(text("update kernel.app_user set mfa_enabled = false where id = :u"), {"u": str(user_id)})
    audit.record(s, "mfa_reset_by_admin" if by_admin else "mfa_disabled", "kernel.app_user", user_id)

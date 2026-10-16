"""Licences for businesses that buy Ziira outright or run their own copy (docs/licensing.md).

A licence is a JSON document whose body (`payload`) is signed with the vendor's Ed25519 private key over its canonical
form. A self-hosted instance holds only the PUBLIC key (`ZIIRA_LICENCE_PUBLIC_KEY`), so it can check a licence but never
make one. The private key lives on the vendor's side (a file named by `ZIIRA_LICENCE_SIGNING_KEY_FILE`, or given to the
command line).

Threat model, honestly: this stops casual sharing and edits of the file. A determined administrator of a self-hosted
machine can patch the code, swap the public key or move the clock; no check in software prevents that. The contract and
the vendor's support and update terms are the real control. What the checks do guarantee: a licence cannot be forged
without the private key, an edited licence is refused, an instance-bound licence works on one instance, a clock moved
back is noticed, and an expired or revoked licence never deletes data: the instance becomes read-only.
"""

import base64
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import text

from ziira.kernel import editions
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.registry import discover

log = logging.getLogger("ziira.licences")

FORMAT = "ziira-licence/1"
RENEWAL_WARNING_DAYS = 30
DEFAULT_GRACE_DAYS = 30


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- keys and signatures
def canonical(payload: dict[str, Any]) -> bytes:
    """The bytes that are signed: sorted keys, no spaces, ASCII only."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def generate_keypair() -> tuple[str, str]:
    """A new signing key pair as base64 of the raw 32 bytes: (private, public). The private key is for the vendor
    only."""
    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    raw_public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw_private).decode(), base64.b64encode(raw_public).decode()


def _private_key(value: str) -> Ed25519PrivateKey:
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(value.strip(), validate=True))
    except ValueError:
        raise ValidationFailed("That is not a licence signing key (base64 of 32 bytes)") from None


def signing_key() -> str:
    """The vendor's private key from the configured file. Raises ValidationFailed when this deployment has none (a
    self-hosted copy never does)."""
    path = get_settings().licence_signing_key_file
    if not path:
        raise ValidationFailed(
            "This deployment has no licence signing key (ZIIRA_LICENCE_SIGNING_KEY_FILE): "
            "licences are issued on the vendor's side"
        )
    try:
        return Path(path).read_text().strip()
    except OSError:
        raise ValidationFailed("The licence signing key file cannot be read") from None


def sign(payload: dict[str, Any], private_key: str) -> str:
    """The licence file text for a payload."""
    signature = _private_key(private_key).sign(canonical(payload))
    return json.dumps(
        {"format": FORMAT, "payload": payload, "signature": base64.b64encode(signature).decode()},
        indent=2,
        sort_keys=True,
    )


def verify(file_text: str, public_key: str) -> dict[str, Any]:
    """Check a licence or revocation file against the vendor's public key and return its payload. Raises
    ValidationFailed
    for anything that is not exactly what the vendor signed."""
    try:
        document = json.loads(file_text)
        payload = document["payload"]
        signature = base64.b64decode(document["signature"], validate=True)
        if document.get("format") != FORMAT or not isinstance(payload, dict):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValidationFailed("This is not a Ziira licence file") from None
    if not public_key.strip():
        raise ValidationFailed(
            "This instance has no vendor public key (ZIIRA_LICENCE_PUBLIC_KEY): licences cannot be checked"
        )
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key.strip(), validate=True)).verify(
            signature, canonical(payload)
        )
    except (InvalidSignature, ValueError):
        raise ValidationFailed(
            "The licence signature is not valid: the file was changed or is not from the vendor"
        ) from None
    return payload


# --------------------------------------------------------------------------- issuing (vendor)
def _next_number() -> str:
    with master_session() as m:
        m.execute(
            text(
                "insert into master.billing_counter (name, last_value) values ('licence', 0) "
                "on conflict (name) do nothing"
            )
        )
        n = m.execute(
            text(
                "update master.billing_counter set last_value = last_value + 1 where name = 'licence' "
                "returning last_value"
            )
        ).scalar_one()
    return f"LIC-{n:06d}"


def _entitlements(
    plan_code: str | None, units: list[str] | None, edition: str | None, limits: dict[str, int | None]
) -> dict[str, Any]:
    names = set(units or [])
    known = discover()
    if names - set(known):
        raise ValidationFailed("Unknown unit(s): " + ", ".join(sorted(names - set(known))))
    if edition:
        names |= set(editions.get(edition).units)
    if not names:
        raise ValidationFailed("A licence must include an edition or some units")
    return {
        "edition": edition,
        "units": sorted(names),
        "plan_code": plan_code,
        "max_users": limits.get("max_users"),
        "max_branches": limits.get("max_branches"),
        "max_companies": limits.get("max_companies"),
    }


def issue(
    *,
    customer: str,
    contact_email: str | None = None,
    plan_code: str | None = None,
    units: list[str] | None = None,
    edition: str | None = None,
    max_users: int | None = None,
    max_branches: int | None = None,
    max_companies: int | None = None,
    valid_until: datetime | None = None,
    update_until: datetime | None = None,
    grace_days: int = DEFAULT_GRACE_DAYS,
    instance_id: str | None = None,
    notes: str = "",
    issued_by: str | None = None,
    private_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Make and record a licence (vendor side). With `plan_code` the plan's units and limits are the starting point and
    any value given here overrides it. Returns the record, including the file text in `token`."""
    from ziira.kernel.platform import plans

    name = " ".join(customer.split())
    if not 2 <= len(name) <= 160:
        raise ValidationFailed("The customer's name is 2 to 160 characters")
    if not 0 <= grace_days <= 365:
        raise ValidationFailed("Grace days are from 0 to 365")
    moment = now or _now()
    if valid_until is not None and valid_until <= moment:
        raise ValidationFailed("A licence must be valid until a future date (or perpetual)")
    plan_id = None
    if plan_code:
        plan = plans.get_plan(plan_code)
        plan_id = plan["id"]
        base = plans.plan_limits(plan)
        units = sorted(set(units or []) | set(plans.plan_units(plan)))
        edition = edition or plan["edition"]
        max_users = max_users if max_users is not None else base["max_users"]
        max_branches = max_branches if max_branches is not None else base["max_branches"]
        max_companies = max_companies if max_companies is not None else base["max_companies"]
    entitlement = _entitlements(
        plan_code,
        units,
        edition,
        {"max_users": max_users, "max_branches": max_branches, "max_companies": max_companies},
    )
    number = _next_number()
    payload = {
        "kind": "licence",
        "licence_no": number,
        "customer": name,
        "contact_email": contact_email,
        "issued_at": moment.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until else None,
        "update_until": update_until.isoformat() if update_until else None,
        "grace_days": grace_days,
        "instance_id": instance_id or None,
        "entitlements": entitlement,
    }
    token = sign(payload, private_key or signing_key())
    with master_session() as m:
        row = m.execute(
            text(
                "insert into master.licence (licence_no, customer, contact_email, plan_id, plan_code, entitlements, "
                "issued_at, valid_until, update_until, grace_days, instance_id, token, notes, issued_by) "
                "values (:n, :c, :e, :p, :pc, cast(:en as jsonb), :i, :v, :u, :g, :inst, :t, :no, :by) returning *"
            ),
            {
                "n": number,
                "c": name,
                "e": contact_email,
                "p": str(plan_id) if plan_id else None,
                "pc": plan_code,
                "en": json.dumps(entitlement),
                "i": moment,
                "v": valid_until,
                "u": update_until,
                "g": grace_days,
                "inst": instance_id or None,
                "t": token,
                "no": notes,
                "by": issued_by,
            },
        ).one()
    return dict(row._mapping)


def list_licences() -> list[dict[str, Any]]:
    with master_session() as m:
        return [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select id, licence_no, customer, contact_email, plan_code, entitlements, issued_at, valid_until, "
                    "update_until, grace_days, instance_id, status, revoked_at, revoked_reason, notes, issued_by "
                    "from master.licence order by issued_at desc"
                )
            )
        ]


def get_licence(licence_id: uuid.UUID) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(text("select * from master.licence where id = :i"), {"i": str(licence_id)}).first()
    if row is None:
        raise NotFound("No such licence")
    return dict(row._mapping)


def revoke(licence_id: uuid.UUID, reason: str) -> dict[str, Any]:
    """Mark a licence revoked in the vendor's records. A self-hosted copy learns of it only when it installs a signed
    revocation list (`revocation_list`) or when the licence runs out: say so to the customer."""
    if len(reason.strip()) < 5:
        raise ValidationFailed("Say why (at least a few words)")
    with master_session() as m:
        row = m.execute(
            text(
                "update master.licence set status = 'revoked', revoked_at = now(), revoked_reason = :r "
                "where id = :i and status = 'active' returning licence_no"
            ),
            {"r": reason.strip(), "i": str(licence_id)},
        ).first()
        if row is None:
            raise ValidationFailed("No such active licence")
    return get_licence(licence_id)


def revocation_list(*, private_key: str | None = None, now: datetime | None = None) -> str:
    """A signed file listing every revoked licence number, to install on self-hosted copies."""
    with master_session() as m:
        numbers = list(
            m.execute(
                text("select licence_no from master.licence where status = 'revoked' order by licence_no")
            ).scalars()
        )
    payload = {"kind": "revocation", "issued_at": (now or _now()).isoformat(), "licence_nos": numbers}
    return sign(payload, private_key or signing_key())


# --------------------------------------------------------------------------- state of a licence
@dataclass(frozen=True)
class LicenceState:
    """Where a licence stands at a moment. `access` follows the same words as subscriptions: full / warning /
    read_only."""

    status: str  # valid | grace | expired | revoked | wrong_instance | clock_rollback
    access: str
    message: str
    days_left: int | None  # until valid_until (negative once past); None = perpetual
    grace_ends: datetime | None
    renewal_due: bool
    updates_ended: bool


def _when(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def evaluate(
    payload: dict[str, Any], *, now: datetime, revoked: set[str], this_instance: str, clock_rolled_back: bool = False
) -> LicenceState:
    """Pure: the state of a verified licence payload at `now`."""
    until = _when(payload.get("valid_until"))
    update_until = _when(payload.get("update_until"))
    updates_ended = update_until is not None and now > update_until
    days_left = None if until is None else (until - now).days if until >= now else -((now - until).days + 1)
    bound = payload.get("instance_id")
    if payload.get("licence_no") in revoked:
        return LicenceState(
            "revoked",
            "read_only",
            "This licence was revoked. The system is read-only: contact the vendor.",
            days_left,
            None,
            False,
            updates_ended,
        )
    if bound and bound != this_instance:
        return LicenceState(
            "wrong_instance",
            "read_only",
            f"This licence belongs to another installation ({bound}). This installation is {this_instance}.",
            days_left,
            None,
            False,
            updates_ended,
        )
    if clock_rolled_back:
        return LicenceState(
            "clock_rollback",
            "read_only",
            "The system clock is earlier than it has been. Correct the date and time of this server.",
            days_left,
            None,
            False,
            updates_ended,
        )
    if until is None or now <= until:
        due = until is not None and (until - now) <= timedelta(days=RENEWAL_WARNING_DAYS)
        message = "" if not due else f"The licence ends in {days_left} day(s): renew it to avoid interruption."
        return LicenceState("valid", "warning" if due else "full", message, days_left, None, due, updates_ended)
    grace_ends = until + timedelta(days=int(payload.get("grace_days", DEFAULT_GRACE_DAYS)))
    if now <= grace_ends:
        return LicenceState(
            "grace",
            "warning",
            f"The licence ended on {until:%Y-%m-%d}. Everything still works until {grace_ends:%Y-%m-%d}: renew it.",
            days_left,
            grace_ends,
            True,
            updates_ended,
        )
    return LicenceState(
        "expired",
        "read_only",
        f"The licence ended on {until:%Y-%m-%d}. The system is read-only: your "
        "data is safe. Install a renewed licence to continue.",
        days_left,
        grace_ends,
        True,
        updates_ended,
    )


# --------------------------------------------------------------------------- the clock guard
CLOCK_KEY = "clock.last_seen"


def clock_rolled_back(now: datetime, *, tolerance_hours: int | None = None, record: bool = True) -> bool:
    """True when `now` is earlier than the latest time this instance has seen by more than the tolerance. Otherwise the
    latest time seen moves forward (at most once a minute). The stored value is itself only a deterrent: see the
    threat model above."""
    tolerance = timedelta(
        hours=get_settings().licence_clock_tolerance_hours if tolerance_hours is None else tolerance_hours
    )
    with master_session() as m:
        row = m.execute(text("select value from master.platform_setting where key = :k"), {"k": CLOCK_KEY}).first()
        last = _when(row.value) if row is not None else None
        if last is not None and now < last - tolerance:
            return True
        if record and (last is None or now > last + timedelta(minutes=1)):
            m.execute(
                text(
                    "insert into master.platform_setting (key, value) values (:k, cast(:v as jsonb)) "
                    "on conflict (key) do update set value = excluded.value, updated_at = now()"
                ),
                {"k": CLOCK_KEY, "v": json.dumps(now.isoformat())},
            )
    return False


# --------------------------------------------------------------------------- the installed licence (self-hosted)
def instance_id() -> str:
    """This installation's id (ZIIRA_INSTANCE_ID, else one made on first use and kept). A vendor can bind a licence to
    it."""
    configured = get_settings().instance_id.strip()
    if configured:
        return configured
    with master_session() as m:
        row = m.execute(text("select value from master.platform_setting where key = 'instance.id'")).first()
        if row is not None:
            return str(row.value)
        fresh = uuid.uuid4().hex[:16]
        m.execute(
            text(
                "insert into master.platform_setting (key, value) values ('instance.id', cast(:v as jsonb)) "
                "on conflict (key) do nothing"
            ),
            {"v": json.dumps(fresh)},
        )
        row = m.execute(text("select value from master.platform_setting where key = 'instance.id'")).one()
    return str(row.value)


def install(file_text: str, *, by: str | None = None) -> dict[str, Any]:
    """Check a licence file with the vendor's public key and keep it. Returns what it allows."""
    payload = verify(file_text, get_settings().licence_public_key)
    if payload.get("kind") != "licence":
        raise ValidationFailed("This file is not a licence")
    bound = payload.get("instance_id")
    if bound and bound != instance_id():
        raise ValidationFailed(f"This licence is for installation {bound}; this one is {instance_id()}")
    with master_session() as m:
        m.execute(
            text(
                "insert into master.installed_licence (singleton, token, payload, installed_by) "
                "values (true, :t, cast(:p as jsonb), :b) on conflict (singleton) do update set token = "
                "excluded.token, "
                "payload = excluded.payload, installed_at = now(), installed_by = excluded.installed_by"
            ),
            {"t": file_text, "p": json.dumps(payload), "b": by},
        )
    from ziira.kernel.platform import entitlements

    entitlements.invalidate()
    return describe(now=_now())


def install_revocations(file_text: str) -> int:
    """Install a signed revocation list; returns how many licences it names."""
    payload = verify(file_text, get_settings().licence_public_key)
    if payload.get("kind") != "revocation":
        raise ValidationFailed("This file is not a revocation list")
    numbers = [str(n) for n in payload.get("licence_nos", [])]
    with master_session() as m:
        for number in numbers:
            m.execute(
                text("insert into master.licence_revocation (licence_no) values (:n) on conflict do nothing"),
                {"n": number},
            )
    from ziira.kernel.platform import entitlements

    entitlements.invalidate()
    return len(numbers)


def installed_payload() -> dict[str, Any] | None:
    """The installed licence's payload, re-checked against the public key now (so a changed row or key is noticed)."""
    with master_session() as m:
        row = m.execute(text("select token from master.installed_licence where singleton")).first()
    if row is None:
        return None
    try:
        return verify(row.token, get_settings().licence_public_key)
    except ValidationFailed:
        log.warning("The installed licence no longer verifies")
        return None


def describe(*, now: datetime | None = None) -> dict[str, Any]:
    """What this instance holds, for the Licence screen and `ziira licence status`."""
    moment = now or _now()
    with master_session() as m:
        row = m.execute(text("select installed_at, installed_by from master.installed_licence where singleton")).first()
        revoked = set(m.execute(text("select licence_no from master.licence_revocation")).scalars())
    payload = installed_payload() if row is not None else None
    base: dict[str, Any] = {
        "instance_id": instance_id(),
        "installed": row is not None,
        "required": get_settings().licence_required,
    }
    if row is None:
        return {
            **base,
            "valid_signature": False,
            "status": "none",
            "message": "No licence is installed.",
            "access": "read_only" if base["required"] else "full",
        }
    if payload is None:
        return {
            **base,
            "valid_signature": False,
            "status": "invalid",
            "access": "read_only",
            "message": "The installed licence does not verify. Install the licence file again.",
            "installed_at": row.installed_at,
        }
    state = evaluate(
        payload,
        now=moment,
        revoked=revoked,
        this_instance=instance_id(),
        clock_rolled_back=clock_rolled_back(moment, record=False),
    )
    return {
        **base,
        "valid_signature": True,
        "status": state.status,
        "access": state.access,
        "message": state.message,
        "licence_no": payload["licence_no"],
        "customer": payload["customer"],
        "issued_at": payload["issued_at"],
        "valid_until": payload["valid_until"],
        "update_until": payload["update_until"],
        "days_left": state.days_left,
        "grace_ends": state.grace_ends,
        "renewal_due": state.renewal_due,
        "updates_ended": state.updates_ended,
        "entitlements": payload["entitlements"],
        "installed_at": row.installed_at,
    }

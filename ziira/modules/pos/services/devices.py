"""Use cases: register the tills, tablets and phones that sell, and block lost ones.

A device holds a secret key (shown once, stored only as a hash). The key is how a device proves itself when it syncs
offline sales; the cashier still signs in as themselves, so every sale has a person and a device.
"""

import re
from datetime import UTC, datetime
from uuid import UUID

from ziira.modules.pos.permissions import DEVICES_MANAGE, SALES_SELL
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import Device
from ziira.sdk import (
    Conflict,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    hash_secret,
    new_secret,
)

CODE_PATTERN = re.compile(r"^[A-Z0-9]{1,8}$")
KEY_PREFIX = "zdk_"


def _check_location(session: Session, location_id: UUID | None, company_id: UUID, branch_id: UUID) -> None:
    if location_id is None:
        return
    found = pos_repo.location_branch(session, location_id)
    if found is None or found != (company_id, branch_id):
        raise ValidationFailed("The stock location must belong to the device's branch")


def register_device(session: Session, *, branch_id: UUID, code: str, name: str,
                    location_id: UUID | None = None) -> tuple[Device, str]:
    """Register a device at a branch and give it a key. `location_id` is the store its sales take stock from. Returns
    the device and its key, which is not shown again. Needs 'devices.manage' for the branch."""
    company_id = pos_repo.branch_company(session, branch_id)
    if company_id is None:
        raise ValidationFailed("Branch not found")
    ctx = current_context()
    ctx.require(DEVICES_MANAGE, company_id=company_id, branch_id=branch_id)
    code = code.strip().upper()
    if not CODE_PATTERN.match(code):
        raise ValidationFailed("A device code is 1-8 letters or digits, for example D1")
    if not name.strip():
        raise ValidationFailed("A device needs a name")
    _check_location(session, location_id, company_id, branch_id)
    if pos_repo.device_code_exists(session, branch_id, code):
        raise Conflict(f"This branch already has a device with code {code}")
    key = KEY_PREFIX + new_secret()
    device = Device(tenant_id=ctx.tenant_id, created_by=ctx.user_id, branch_id=branch_id, code=code,
                    name=name.strip(), location_id=location_id, device_key_hash=hash_secret(key))
    pos_repo.add(session, device)
    audit_record(session, "register", "pos.device", device.id, {"code": code, "branch_id": branch_id})
    return device, key


def get_device(session: Session, device_id: UUID, *, for_selling: bool = False) -> Device:
    """A device the user may see (or, for selling, may sell on). Others read as not found."""
    device = pos_repo.get_device(session, device_id)
    company_id = pos_repo.branch_company(session, device.branch_id) if device else None
    if device is None or company_id is None:
        raise NotFound("Device not found")
    ctx = current_context()
    permission = SALES_SELL if for_selling else DEVICES_MANAGE
    if not (ctx.can(permission, company_id=company_id, branch_id=device.branch_id)
            or ctx.can(SALES_SELL, company_id=company_id, branch_id=device.branch_id)):
        raise NotFound("Device not found")
    return device


def list_devices(session: Session, branch_id: UUID | None = None) -> list[Device]:
    ctx = current_context()
    scopes = ctx.scopes_with(DEVICES_MANAGE)
    sellers = ctx.scopes_with(SALES_SELL)
    combined = None if scopes is None or sellers is None else sorted({*scopes, *sellers}, key=str)
    return pos_repo.list_devices(session, combined, branch_id)


def set_status(session: Session, device_id: UUID, status: str) -> Device:
    """Block a lost or stolen device (it can no longer sell or sync) or let it work again. Needs 'devices.manage'."""
    if status not in ("active", "blocked"):
        raise ValidationFailed("Status must be 'active' or 'blocked'")
    device = pos_repo.get_device(session, device_id, lock=True)
    company_id = pos_repo.branch_company(session, device.branch_id) if device else None
    if device is None or company_id is None:
        raise NotFound("Device not found")
    current_context().require(DEVICES_MANAGE, company_id=company_id, branch_id=device.branch_id)
    device.status = status
    session.flush()
    audit_record(session, "set_status", "pos.device", device.id, {"status": status})
    return device


def rotate_key(session: Session, device_id: UUID) -> tuple[Device, str]:
    """Give a device a new key (the old one stops working). Needs 'devices.manage'."""
    device = pos_repo.get_device(session, device_id, lock=True)
    company_id = pos_repo.branch_company(session, device.branch_id) if device else None
    if device is None or company_id is None:
        raise NotFound("Device not found")
    current_context().require(DEVICES_MANAGE, company_id=company_id, branch_id=device.branch_id)
    key = KEY_PREFIX + new_secret()
    device.device_key_hash = hash_secret(key)
    session.flush()
    audit_record(session, "rotate_key", "pos.device", device.id, None)
    return device, key


def authenticate(session: Session, key: str | None) -> Device:
    """The active device holding this key, for the offline sync endpoints. The signed-in cashier must also be allowed to
    sell at the device's branch."""
    if not key or not key.startswith(KEY_PREFIX):
        raise Forbidden("A device key is required")
    device = pos_repo.device_by_hash(session, hash_secret(key))
    if device is None or device.status != "active":
        raise Forbidden("This device key is not valid")
    company_id = pos_repo.branch_company(session, device.branch_id)
    if company_id is None:
        raise Forbidden("This device key is not valid")
    current_context().require(SALES_SELL, company_id=company_id, branch_id=device.branch_id)
    device.last_sync_at = datetime.now(UTC)
    session.flush()
    return device

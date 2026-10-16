"""The operator console's endpoints (docs/security.md, "Operator console"): platform units, businesses, platform health
and the operators themselves. Only platform staff with an operator token reach them (a business user's token is a
different kind and is refused); every change needs a confirmation no older than
`ZIIRA_OPERATOR_MFA_MAX_AGE_MINUTES` (403 `mfa_step_up_required`: send the operator's password, or with
`ZIIRA_OPERATOR_MFA=totp` a fresh code, to `POST /operator/confirm`, then retry)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import operator_console as console
from ziira.kernel import operators
from ziira.kernel.api.operator_routes import current_operator, require
from ziira.kernel.auth import client_ip
from ziira.kernel.config import get_settings

router = APIRouter(prefix="/api/v1/operator", tags=["Operator console"])


# --------------------------------------------------------------------------- session and second factor
class OperatorMe(BaseModel):
    name: str
    email: str
    mfa_verified_at: datetime = Field(description="When the operator last confirmed their identity (signing in counts)")
    step_up_needed: bool = Field(description="True when a change would ask to confirm again now")
    mfa_max_age_minutes: int
    mfa_mode: str = Field(description="off: password only (a change asks for the password again); totp: a code")
    mfa_off_in_production: bool = Field(description="True in production with no second factor: show a warning")
    must_change_password: bool
    role: str
    permissions: list[str]


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str | None = Field(default=None, max_length=1024, description="The password (mfa_mode off)")
    code: str | None = Field(default=None, max_length=64, description="An authenticator code (mfa_mode totp)")


class ConfirmOut(BaseModel):
    mfa_verified_at: datetime
    valid_minutes: int


@router.get("/me", response_model=OperatorMe)
def me(operator: operators.Operator = Depends(current_operator)) -> object:
    """Who is signed in and whether a change would ask to confirm again."""
    settings = get_settings()
    return {"name": operator.name, "email": operator.email, "mfa_verified_at": operator.mfa_verified_at,
            "step_up_needed": console.step_up_needed(operator),
            "mfa_max_age_minutes": settings.operator_mfa_max_age_minutes,
            "mfa_mode": settings.operator_mfa,
            "mfa_off_in_production": settings.env == "production" and settings.operator_password_only(),
            "must_change_password": operator.must_change_password,
            "role": operator.role, "permissions": sorted(operator.permissions)}


@router.post("/confirm", response_model=ConfirmOut)
@router.post("/mfa/confirm", response_model=ConfirmOut, include_in_schema=False)
def confirm(body: ConfirmIn, request: Request, operator: operators.Operator = Depends(current_operator)) -> object:
    """Confirm your password again (or, with a second factor, a fresh code) so changes are allowed for a while."""
    verified = console.confirm_identity(operator, code=body.code, password=body.password,
                                        ip_address=client_ip(request))
    return {"mfa_verified_at": verified, "valid_minutes": get_settings().operator_mfa_max_age_minutes}


# --------------------------------------------------------------------------- platform units
class PlatformUnit(BaseModel):
    name: str
    title: str
    kind: str = Field(description="kernel, module or plugin")
    category: str
    source: str = Field(description="built in, or extra folder (a plugin loaded from ZIIRA_EXTRA_UNIT_PATHS)")
    description: str
    version_on_disk: str
    version_installed: str | None
    installed_at: datetime | None
    status: str = Field(description="available | installed | needs_upgrade")
    requires: list[str]
    required_by: list[str] = Field(description="Installed units that need this one")
    businesses_enabled: int
    businesses_holding: int = Field(description="Businesses whose database has the unit's tables (enabled or not)")
    businesses_behind: int = Field(description="Businesses missing some of the unit's migrations")


class UnitMigrations(BaseModel):
    code: str
    migrations: list[str]


class UnitUpgrade(BaseModel):
    name: str
    title: str
    from_version: str
    to_version: str
    businesses: list[UnitMigrations]


class UnitInstallItem(BaseModel):
    name: str
    title: str
    kind: str
    version: str


class UnitHolder(BaseModel):
    code: str
    name: str
    enabled: bool


class UnitPlan(BaseModel):
    action: str
    unit: str
    title: str
    will_install: list[UnitInstallItem]
    upgrades: list[UnitUpgrade]
    holders: list[UnitHolder]
    dependants: list[str]
    blocked: list[str] = Field(description="Why it cannot be done now; empty when it can")


class UnitResult(BaseModel):
    installed: list[str] = []
    upgraded: list[dict[str, Any]] = []
    uninstalled: str | None = None


class UninstallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str = Field(max_length=100, description="The unit's name, typed to confirm")


@router.get("/units", response_model=list[PlatformUnit])
def units(_: operators.Operator = Depends(require("platform.view"))) -> object:
    """Every unit found on disk, with its state on the platform and how many businesses have it."""
    return console.list_units()


@router.get("/units/{name}/plan", response_model=UnitPlan)
def unit_plan(name: str, action: str = Query(pattern="^(install|upgrade|uninstall)$"),
              _: operators.Operator = Depends(require("platform.view"))) -> object:
    """What an install, upgrade or uninstall would do, and what stands in its way. Changes nothing."""
    return console.plan_unit(name, action)


@router.post("/units/{name}/install", response_model=UnitResult)
def install(name: str, request: Request, operator: operators.Operator = Depends(require("platform.units"))) -> object:
    """Install a unit and the units it requires (the command line's `ziira install`)."""
    return console.install_unit(operator, name, ip_address=client_ip(request))


@router.post("/units/{name}/upgrade", response_model=UnitResult)
def upgrade(name: str, request: Request, operator: operators.Operator = Depends(require("platform.units"))) -> object:
    """Apply a unit's new version in every business database that has it."""
    return console.upgrade_unit(operator, name, ip_address=client_ip(request))


@router.post("/units/{name}/uninstall", response_model=UnitResult)
def uninstall(name: str, body: UninstallIn, request: Request,
              operator: operators.Operator = Depends(require("platform.units"))) -> object:
    """Stop offering a unit. Refused for the kernel, units others need, and while any business database has it."""
    return console.uninstall_unit(operator, name, body.confirm, ip_address=client_ip(request))


# --------------------------------------------------------------------------- businesses
class BusinessRow(BaseModel):
    id: UUID
    code: str
    name: str
    status: str
    edition: str | None
    country: str | None
    created_at: datetime
    last_activity: datetime | None
    users: int
    enabled_units: list[str]
    behind: bool = Field(description="Its database lacks some migrations of the code on disk")
    error: str | None = Field(description="Set when the business's database could not be read")


class BusinessUnit(BaseModel):
    name: str
    title: str
    kind: str
    category: str
    installed: bool
    enabled: bool
    has_data: bool
    can_enable: bool
    can_disable: bool
    why_not_disable: str | None
    requires: list[str]
    will_also_enable: list[str]


class BusinessGrant(BaseModel):
    id: UUID
    level: str
    reason: str
    expires_at: datetime
    created_at: datetime


class BusinessSession(BaseModel):
    id: UUID
    operator_name: str
    level: str
    started_at: datetime
    expires_at: datetime
    mine: bool


class BusinessDetail(BusinessRow):
    units: list[BusinessUnit]
    grants: list[BusinessGrant] = Field(description="Support access the business has given and not withdrawn")
    sessions: list[BusinessSession] = Field(description="Staff sessions open in it now")
    behind_units: dict[str, list[str]]


class UnitSwitchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(max_length=500, description="Why; written to the business's own audit log")


class UnitSwitchOut(BaseModel):
    business: str
    unit: str
    enabled: bool
    also_enabled: list[str]


class UpgradeBusinessesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codes: list[str] | None = Field(default=None, max_length=500,
                                    description="Businesses to upgrade; empty: every one that is behind")


class UpgradeResult(BaseModel):
    code: str
    name: str
    ok: bool
    applied: dict[str, list[str]] = Field(description="Migration files applied, by unit")
    error: str | None


@router.get("/businesses/overview", response_model=list[BusinessRow])
def businesses_overview(search: str | None = Query(default=None, max_length=100),
                        _: operators.Operator = Depends(require("platform.view"))) -> object:
    """Every business with its figures. Never any of their records."""
    return console.list_businesses(search)


@router.get("/businesses/{code}", response_model=BusinessDetail)
def business(code: str, operator: operators.Operator = Depends(require("platform.view"))) -> object:
    """One business: its units, the support access it has given and the staff sessions open in it."""
    return console.business_detail(operator, code)


@router.post("/businesses/{code}/units/{unit}/enable", response_model=UnitSwitchOut)
def enable_unit(code: str, unit: str, body: UnitSwitchIn, request: Request,
                operator: operators.Operator = Depends(require("platform.units"))) -> object:
    """Switch a unit on for a business (with a reason; the business's audit log shows who and why)."""
    return console.set_business_unit(operator, code, unit, enable=True, reason=body.reason,
                                     ip_address=client_ip(request))


@router.post("/businesses/{code}/units/{unit}/disable", response_model=UnitSwitchOut)
def disable_unit(code: str, unit: str, body: UnitSwitchIn, request: Request,
                 operator: operators.Operator = Depends(require("platform.units"))) -> object:
    """Switch a unit off for a business (its data is kept)."""
    return console.set_business_unit(operator, code, unit, enable=False, reason=body.reason,
                                     ip_address=client_ip(request))


@router.post("/businesses/upgrade", response_model=list[UpgradeResult])
def upgrade_businesses(body: UpgradeBusinessesIn, request: Request,
                       operator: operators.Operator = Depends(require("platform.units"))) -> object:
    """Bring business databases up to date: those named, or all that are behind. Each business is done on its own."""
    return console.upgrade_businesses(operator, body.codes, ip_address=client_ip(request))


# --------------------------------------------------------------------------- health, operators, trail
class BehindBusiness(BaseModel):
    code: str
    name: str
    behind: dict[str, list[str]] = Field(description="Migration files not yet applied, by unit")


class UnreadableBusiness(BaseModel):
    code: str
    name: str
    error: str | None


class BackupStatus(BaseModel):
    reported: bool = Field(description="False when ZIIRA_BACKUP_DIR is not set or not a folder")
    master_taken_at: datetime | None
    master_age_hours: float | None
    tenants_without_backup: list[str]


class RecurringTask(BaseModel):
    name: str
    oldest_run_age_seconds: int
    failing_businesses: int


class QueueStatus(BaseModel):
    jobs_queued: int
    jobs_due: int
    jobs_failed: int
    outbox_pending: int
    outbox_stuck: int
    notifications_queued: int
    notifications_failed: int
    intel_check_failures: int
    jobs_oldest_due_seconds: int
    outbox_lag_seconds: int
    tenant_errors: int
    collected_at: datetime
    recurring: list[RecurringTask]


class RegistrationStatus(BaseModel):
    pending: int
    expired: int


class ExtraPlugin(BaseModel):
    name: str
    title: str
    version: str
    checksum: str
    manifest_checksum_ok: bool
    on_allow_list: bool
    pinned: bool


class RefusedPlugin(BaseModel):
    name: str
    reason: str


class PluginStatus(BaseModel):
    folders: list[str]
    production_allow_list: bool
    loaded: list[ExtraPlugin]
    refused: list[RefusedPlugin]


class PlatformHealth(BaseModel):
    ready: bool
    problems: list[str]
    master_migrations_pending: list[str]
    businesses_total: int
    businesses_behind: list[BehindBusiness]
    businesses_unreadable: list[UnreadableBusiness]
    backups: BackupStatus
    queues: QueueStatus | None = Field(description="Null when the platform figures could not be collected")
    registrations: RegistrationStatus
    plugins: PluginStatus


class OperatorRow(BaseModel):
    id: UUID
    name: str
    email: str
    status: str
    role: str
    created_at: datetime
    last_sign_in_at: datetime | None
    mfa_enrolled: bool
    must_change_password: bool
    open_sessions: int


class ActionLine(BaseModel):
    id: int
    occurred_at: datetime
    operator_name: str
    action: str
    target: str | None
    outcome: str
    reason: str | None
    detail: dict[str, Any] | None


@router.get("/health", response_model=PlatformHealth)
def health(_: operators.Operator = Depends(require("platform.view"))) -> object:
    """Readiness, migrations, backups, queues, registrations and extra plugins."""
    return console.platform_health()


@router.get("/operators", response_model=list[OperatorRow])
def operator_list(_: operators.Operator = Depends(require("platform.operators"))) -> object:
    """The platform staff, their second-factor state and whether they must change their password."""
    return console.operators_overview()


@router.get("/actions", response_model=list[ActionLine])
def actions(limit: int = Query(default=100, ge=1, le=500),
            _: operators.Operator = Depends(require("platform.operators"))) -> object:
    """The newest lines of the operator action trail."""
    return console.action_log(limit=limit)

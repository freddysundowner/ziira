"""The operator console's services: what platform staff can see and change from the web (docs/security.md, "Operator
console").

Everything here is a thin layer over the same functions the command line uses (`Registry.install`, `uninstall`,
`unit_admin.enable_unit`, ...), plus three things the command line does not need:

- **A recent confirmation for every change.** A change needs the operator's identity confirmed within
  `ZIIRA_OPERATOR_MFA_MAX_AGE_MINUTES` (`confirm_identity`): a fresh authenticator code with `ZIIRA_OPERATOR_MFA=totp`,
  the operator's password again with `off`; otherwise `StepUpRequired` (403, `mfa_step_up_required`, a code kept for
  compatibility) and the screen asks and retries. Signing in counts as a confirmation.
- **An audit trail.** Each change (and each refused change) is a line in `master.operator_action_log`, which the
  database never lets anyone edit. A change inside a business is also written to that business's own audit log
  (channel `support`, with the operator named), so the business sees it too: "logged twice".
- **Overviews.** One pass over every business's database (`scan_businesses`) gives the numbers the screens show.

Nothing here returns a connection string, key or token, and nothing reads a business's records.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import audit, backup, mfa, operators, platform_metrics, plugin_trust, throttle, unit_admin
from ziira.kernel.config import get_settings
from ziira.kernel.context import RequestContext, set_context
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import DependencyError, Forbidden, NotFound, Unauthorized, ValidationFailed, ZiiraError
from ziira.kernel.manifest import Manifest, sdk_compatible
from ziira.kernel.operators import Operator
from ziira.kernel.registry import Registry, discover, install_order, migration_files
from ziira.kernel.security import decrypt, verify_password

log = logging.getLogger("ziira.operator_console")

MIN_REASON_LENGTH = 5


class StepUpRequired(Forbidden):
    """The operator's last confirmation is too old: send a fresh one to /operator/confirm, then retry."""

    code = "mfa_step_up_required"


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- recent confirmation and audit trail
def step_up_message() -> str:
    """What to tell an operator whose confirmation is too old."""
    if get_settings().operator_password_only():
        return "Confirm your password to make this change"
    return "Confirm with a fresh code from your authenticator app to make this change"


def step_up_why() -> str:
    """The reason written to the trail for a change refused because the confirmation was too old."""
    password_only = get_settings().operator_password_only()
    return f"{'password' if password_only else 'second factor'} not confirmed recently"


def step_up_needed(operator: Operator) -> bool:
    """True when the operator must confirm again (a password or a code, by setting) before changing anything."""
    limit = timedelta(minutes=get_settings().operator_mfa_max_age_minutes)
    return _now() - operator.mfa_verified_at > limit


def confirm_identity(operator: Operator, *, code: str | None = None, password: str | None = None,
                     ip_address: str | None) -> datetime:
    """Confirm the operator again, so changes are allowed for a while: their password (ZIIRA_OPERATOR_MFA=off) or a
    fresh code from their authenticator app (totp). Wrong tries are counted and locked out like sign-in's, and every
    try is a line in the trail. A code works once, so the one used to sign in cannot be used again."""
    password_only = get_settings().operator_password_only()
    given = password if password_only else code
    if not given:
        raise ValidationFailed("Enter your password" if password_only else "Enter the code from your authenticator app")
    kind = "operator-confirm" if password_only else "operator-mfa"
    counters = throttle.action_counters(kind, str(operator.id), ip_address, per_subject=5, per_ip=30)
    throttle.guard(counters)
    verified: datetime | None = None
    with master_session() as m:
        row = m.execute(text("select password_hash, mfa_secret_enc, mfa_last_counter, status from master.operator "
                             "where id = :i for update"), {"i": str(operator.id)}).first()
        good = row is not None and row.status == "active"
        if password_only:
            passed = verify_password(given, row.password_hash if row is not None else None) and good
        else:
            counter = mfa.check_code(decrypt(row.mfa_secret_enc), given, row.mfa_last_counter) \
                if row is not None and good and row.mfa_secret_enc else None
            passed = counter is not None
            if passed:
                m.execute(text("update master.operator set mfa_last_counter = :c where id = :i"),
                          {"c": counter, "i": str(operator.id)})
        if passed:
            verified = m.execute(text("update master.operator_session set mfa_verified_at = now() where id = :s "
                                      "returning mfa_verified_at"), {"s": str(operator.session_id)}).scalar_one()
    if verified is None:
        throttle.failed(counters)
        operators.audit_sign_in("auth.confirm", operator.id, operator.name, outcome="refused", ip_address=ip_address)
        raise Unauthorized("That password is not right" if password_only else "That code is not right")
    throttle.succeeded(counters[:1])
    operators.audit_sign_in("auth.confirm", operator.id, operator.name, ip_address=ip_address)
    return verified


def log_action(operator: Operator, action: str, *, target: str | None = None, outcome: str = "ok",
               reason: str | None = None, detail: dict[str, Any] | None = None, ip_address: str | None = None) -> None:
    """One line in the platform's operator trail (append-only in the database)."""
    with master_session() as m:
        m.execute(text(
            "insert into master.operator_action_log (operator_id, operator_name, action, target, outcome, reason, "
            "detail, ip_address) values (:o, :n, :a, :t, :out, :r, cast(:d as jsonb), :ip)"),
            {"o": str(operator.id), "n": operator.name, "a": action, "t": target, "out": outcome, "r": reason,
             "d": json.dumps(detail, default=str) if detail else None, "ip": ip_address})


def _change(operator: Operator, action: str, target: str, ip_address: str | None, work: Any, *,
            reason: str | None = None) -> Any:
    """Run one change: needs a recent confirmation, and leaves a line in the trail whether it worked or was refused."""
    if step_up_needed(operator):
        log_action(operator, action, target=target, outcome="refused", reason=reason,
                   detail={"why": step_up_why()}, ip_address=ip_address)
        raise StepUpRequired(step_up_message())
    try:
        result = work()
    except ZiiraError as error:
        log_action(operator, action, target=target, outcome="refused", reason=reason,
                   detail={"why": error.message}, ip_address=ip_address)
        raise
    except Exception as error:
        log_action(operator, action, target=target, outcome="failed", reason=reason,
                   detail={"error": type(error).__name__}, ip_address=ip_address)
        raise
    log_action(operator, action, target=target, reason=reason,
               detail=result if isinstance(result, dict) else None, ip_address=ip_address)
    return result


def action_log(*, limit: int = 100) -> list[dict[str, Any]]:
    """The newest lines of the operator trail."""
    with master_session() as m:
        return [dict(r._mapping) for r in m.execute(text(
            "select id, occurred_at, operator_name, action, target, outcome, reason, detail from "
            "master.operator_action_log order by id desc limit :n"), {"n": limit})]


# --------------------------------------------------------------------------- one pass over the businesses
@dataclass
class BusinessScan:
    """What one business's database says about itself (never any of its records)."""

    id: UUID
    code: str
    name: str
    status: str
    created_at: datetime
    scanned: bool = False
    error: str | None = None
    edition: str | None = None
    country: str | None = None
    users: int = 0
    branches: int = 0
    companies: int = 0
    failed_jobs: int = 0
    storage_bytes: int = 0
    last_activity: datetime | None = None
    present: set[str] = field(default_factory=set)
    enabled: set[str] = field(default_factory=set)
    behind: dict[str, list[str]] = field(default_factory=dict)          # unit -> migration files not yet applied


def _scan_one(units: dict[str, Manifest], row: Any) -> BusinessScan:
    scan = BusinessScan(id=row.id, code=row.code, name=row.name, status=row.status, created_at=row.created_at)
    if row.status not in ("active", "provisioning"):
        return scan
    try:
        with tenant_session(row.id, admin=True) as s:
            info = s.execute(text(
                "select (select edition from kernel.tenant limit 1) as edition, "
                "(select country from kernel.company order by created_at limit 1) as country, "
                "(select count(*) from kernel.app_user where status in ('active', 'invited')) as users, "
                "(select count(*) from kernel.branch where is_active) as branches, "
                "(select count(*) from kernel.company) as companies, "
                "(select count(*) from kernel.job where status = 'failed') as failed_jobs, "
                "pg_database_size(current_database()) as storage_bytes, "
                "(select max(occurred_at) from kernel.audit_log where channel <> 'support') as last_activity")).one()
            scan.edition, scan.country, scan.users, scan.last_activity = \
                info.edition, info.country, int(info.users), info.last_activity
            scan.branches, scan.companies, scan.failed_jobs, scan.storage_bytes = \
                int(info.branches), int(info.companies), int(info.failed_jobs), int(info.storage_bytes)
            scan.present = set(s.execute(text("select name from kernel.unit")).scalars())
            scan.enabled = set(s.execute(text(
                "select unit_name from kernel.tenant_unit where status = 'enabled'")).scalars())
            applied: dict[str, set[str]] = {}
            for r in s.execute(text("select unit_name, migration from kernel.schema_migration")):
                applied.setdefault(r.unit_name, set()).add(r.migration)
        for name in scan.present:
            if name in units:
                pending = [f.name for f in migration_files(units[name], "up") if f.name not in applied.get(name, set())]
                if pending:
                    scan.behind[name] = pending
        scan.scanned = True
    except Exception as error:  # noqa: BLE001 - one unreachable business must not hide the others
        log.warning("Operator console: could not read business %s", row.code, exc_info=True)
        scan.error = f"could not be read ({type(error).__name__})"
    return scan


def scan_businesses(units: dict[str, Manifest] | None = None) -> list[BusinessScan]:
    """Every business, with what its own database says about units, users and migrations."""
    found = units if units is not None else discover()
    with master_session() as m:
        rows = list(m.execute(text("select id, code, name, status, created_at from master.tenant order by name")))
    return [_scan_one(found, r) for r in rows]


# --------------------------------------------------------------------------- platform units
def _source(m: Manifest) -> str:
    return "extra folder" if m.package.startswith(plugin_trust.EXTRA_PACKAGE + ".") else "built in"


def _kind(m: Manifest) -> str:
    return "kernel" if m.core else m.kind


def _installed_rows() -> dict[str, Any]:
    with master_session() as m:
        if m.execute(text("select to_regclass('master.unit')")).scalar() is None:
            return {}
        return {r.name: r for r in m.execute(text("select name, version, installed_at from master.unit"))}


def _status(m: Manifest, installed: Any, behind: int) -> str:
    if installed is None:
        return "available"
    return "needs_upgrade" if installed.version != m.version or behind else "installed"


def list_units(units: dict[str, Manifest] | None = None,
               scans: list[BusinessScan] | None = None) -> list[dict[str, Any]]:
    """Every unit found on disk with its platform state and how many businesses have it."""
    found = units if units is not None else discover()
    scanned = scans if scans is not None else scan_businesses(found)
    installed = _installed_rows()
    out = []
    for m in sorted(found.values(), key=lambda u: (not u.core, u.kind != "module", u.title.lower())):
        row = installed.get(m.name)
        behind = sum(1 for b in scanned if m.name in b.behind)
        out.append({
            "name": m.name, "title": m.title, "kind": _kind(m), "category": m.category, "source": _source(m),
            "description": m.description, "version_on_disk": m.version,
            "version_installed": row.version if row else None, "installed_at": row.installed_at if row else None,
            "status": _status(m, row, behind), "requires": list(m.requires),
            "required_by": sorted(u.name for u in found.values() if m.name in u.requires and u.name in installed),
            "businesses_enabled": sum(1 for b in scanned if m.name in b.enabled),
            "businesses_holding": sum(1 for b in scanned if m.name in b.present),
            "businesses_behind": behind})
    return out


def _unit(units: dict[str, Manifest], name: str) -> Manifest:
    m = units.get(name)
    if m is None:
        raise NotFound(f"No unit named '{name}' was found on this server")
    return m


def plan_unit(name: str, action: str) -> dict[str, Any]:
    """What an install, upgrade or uninstall would do, and why it cannot be done now (`blocked`). Changes nothing."""
    units = discover()
    m = _unit(units, name)
    installed = _installed_rows()
    scans = scan_businesses(units)
    blocked: list[str] = []
    out: dict[str, Any] = {"action": action, "unit": name, "title": m.title, "will_install": [], "upgrades": [],
                           "holders": [], "dependants": []}
    if action == "install":
        if name in installed:
            blocked.append("It is installed already: use Upgrade to apply new versions.")
        for n in install_order(units, [name]):
            u = units[n]
            if n not in installed:
                out["will_install"].append({"name": n, "title": u.title, "kind": _kind(u), "version": u.version})
                if not sdk_compatible(u.sdk):
                    blocked.append(f"{u.title} needs a different SDK version than this server provides.")
    elif action == "upgrade":
        if name not in installed:
            blocked.append("It is not installed: use Install.")
        for n in install_order(units, [name]):
            u = units[n]
            if n not in installed:
                continue
            behind = {b.code: b.behind[n] for b in scans if n in b.behind}
            if installed[n].version != u.version or behind:
                out["upgrades"].append({"name": n, "title": u.title, "from_version": installed[n].version,
                                        "to_version": u.version, "businesses": [
                                            {"code": c, "migrations": files} for c, files in sorted(behind.items())]})
        if name in installed and not out["upgrades"]:
            blocked.append("Nothing to upgrade: the installed version is the one on disk and every business is "
                           "current.")
    elif action == "uninstall":
        if m.core:
            blocked.append("The kernel cannot be uninstalled.")
        elif name not in installed:
            blocked.append("It is not installed.")
        out["dependants"] = sorted(u.name for u in units.values() if name in u.requires and u.name in installed)
        if out["dependants"]:
            blocked.append("Installed units need it: " + ", ".join(out["dependants"]) + ".")
        out["holders"] = [{"code": b.code, "name": b.name, "enabled": name in b.enabled}
                          for b in scans if name in b.present]
        if out["holders"]:
            blocked.append("These businesses still have it, so it cannot go: "
                           + ", ".join(h["name"] for h in out["holders"]) + ".")
    else:
        raise ValidationFailed("Action must be install, upgrade or uninstall")
    out["blocked"] = blocked
    return out


def install_unit(operator: Operator, name: str, *, ip_address: str | None) -> dict[str, Any]:
    """Install a unit (and what it requires) on the platform: the command line's `ziira install <unit>`."""
    def work() -> dict[str, Any]:
        if name in _installed_rows():
            raise DependencyError(f"'{name}' is installed already: use Upgrade")
        _unit(discover(), name)
        return {"installed": Registry(discover()).install(name)}
    result: dict[str, Any] = _change(operator, "unit.install", name, ip_address, work)
    return result


def upgrade_unit(operator: Operator, name: str, *, ip_address: str | None) -> dict[str, Any]:
    """Apply a unit's new version: new migrations in every business database that has it."""
    def work() -> dict[str, Any]:
        plan = plan_unit(name, "upgrade")
        if plan["blocked"]:
            raise DependencyError(" ".join(plan["blocked"]))
        Registry(discover()).install(name)
        return {"upgraded": [{"name": u["name"], "from": u["from_version"], "to": u["to_version"],
                              "businesses": len(u["businesses"])} for u in plan["upgrades"]]}
    result: dict[str, Any] = _change(operator, "unit.upgrade", name, ip_address, work)
    return result


def uninstall_unit(operator: Operator, name: str, confirm: str, *, ip_address: str | None) -> dict[str, Any]:
    """Stop offering a unit. Refused for the kernel, for units others need and while any business database has it."""
    def work() -> dict[str, Any]:
        if confirm != name:
            raise ValidationFailed(f"Type the unit's name, '{name}', to confirm")
        plan = plan_unit(name, "uninstall")
        if plan["blocked"]:
            raise DependencyError(" ".join(plan["blocked"]),
                                  {"holders": plan["holders"], "dependants": plan["dependants"]})
        Registry(discover()).uninstall(name)
        return {"uninstalled": name}
    result: dict[str, Any] = _change(operator, "unit.uninstall", name, ip_address, work)
    return result


# --------------------------------------------------------------------------- businesses
def _business_row(scan: BusinessScan) -> dict[str, Any]:
    return {"id": scan.id, "code": scan.code, "name": scan.name, "status": scan.status, "edition": scan.edition,
            "country": scan.country, "created_at": scan.created_at, "last_activity": scan.last_activity,
            "users": scan.users, "enabled_units": sorted(scan.enabled), "behind": bool(scan.behind),
            "error": scan.error}


def list_businesses(search: str | None = None, scans: list[BusinessScan] | None = None) -> list[dict[str, Any]]:
    """Every business with its figures; `search` matches name or code."""
    found = scans if scans is not None else scan_businesses()
    needle = (search or "").strip().lower()
    return [_business_row(b) for b in found if not needle or needle in b.name.lower() or needle in b.code.lower()]


def scan_business(code: str, units: dict[str, Manifest] | None = None) -> BusinessScan | None:
    """One business's scan (the others are not touched), or None when there is no such business."""
    with master_session() as m:
        row = m.execute(text("select id, code, name, status, created_at from master.tenant where code = :c"),
                        {"c": code.strip().lower()}).first()
    return _scan_one(units if units is not None else discover(), row) if row is not None else None


def _scan_for(code: str) -> BusinessScan:
    scan = scan_business(code)
    if scan is None:
        raise NotFound("No such business")
    return scan


def business_detail(operator: Operator, code: str) -> dict[str, Any]:
    """One business: its units, its support-access state and the staff sessions open in it."""
    units = discover()
    scan = scan_business(code, units)
    if scan is None:
        raise NotFound("No such business")
    out = _business_row(scan)
    out.update({"units": [], "grants": [], "sessions": [], "behind_units": scan.behind})
    if scan.status != "active":
        return out
    set_context(RequestContext(tenant_id=scan.id, channel="support", support_operator_id=operator.id,
                               support_operator_name=operator.name))
    with tenant_session(scan.id) as s:
        keep = ("name", "title", "kind", "category", "installed", "enabled", "has_data", "can_enable", "can_disable",
                "why_not_disable", "requires", "will_also_enable")
        out["units"] = [{k: c[k] for k in keep} for c in unit_admin.catalog(s, Registry(units))]
        out["grants"] = [dict(r._mapping) for r in s.execute(text(
            "select id, level, reason, expires_at, created_at from kernel.support_grant "
            "where revoked_at is null and expires_at > now() order by expires_at desc"))]
        out["sessions"] = [{**dict(r._mapping), "mine": r.operator_id == operator.id} for r in s.execute(text(
            "select ss.id, ss.operator_id, ss.operator_name, ss.level, ss.started_at, "
            "least(ss.expires_at, g.expires_at) as expires_at from kernel.support_session ss "
            "join kernel.support_grant g on g.id = ss.grant_id where ss.ended_at is null and g.revoked_at is null "
            "and ss.expires_at > now() and g.expires_at > now() order by ss.started_at desc"))]
    for session in out["sessions"]:
        session.pop("operator_id")
    return out


def set_business_unit(operator: Operator, code: str, unit: str, *, enable: bool, reason: str,
                      ip_address: str | None) -> dict[str, Any]:
    """Switch a unit on or off for one business, as platform staff: the business's own Apps page logic, a mandatory
    reason, a line in the operator trail and one in the business's audit log naming the operator."""
    why = reason.strip()
    action = "business.unit_enable" if enable else "business.unit_disable"

    def work() -> dict[str, Any]:
        if len(why) < MIN_REASON_LENGTH:
            raise ValidationFailed("Say why (at least a few words): the business can see this")
        scan = _scan_for(code)
        if scan.status != "active":
            raise DependencyError("This business is not active")
        units = discover()
        reg = Registry(units)
        set_context(RequestContext(tenant_id=scan.id, channel="support", ip_address=ip_address,
                                   support_operator_id=operator.id, support_operator_name=operator.name))
        with tenant_session(scan.id) as s:
            changed: list[str] = []
            if enable:
                changed = unit_admin.enable_unit(s, reg, scan.id, unit)
            else:
                unit_admin.disable_unit(s, reg, scan.id, unit)
            audit.record(s, "operator_unit_change", "kernel.unit", None,
                         {"unit": unit, "enabled": enable, "reason": why})
        return {"business": scan.code, "unit": unit, "enabled": enable, "also_enabled": changed}
    result: dict[str, Any] = _change(operator, action, f"{code}:{unit}", ip_address, work, reason=why)
    return result


def upgrade_businesses(operator: Operator, codes: list[str] | None, *, ip_address: str | None) -> list[dict[str, Any]]:
    """Bring business databases up to the code on disk: those named, or every one that is behind. Each business is
    done on its own, so one failing does not stop the others; the answer lists what happened to each."""
    def work() -> list[dict[str, Any]]:
        units = discover()
        reg = Registry(units)
        wanted = {c.strip().lower() for c in codes} if codes else None
        results: list[dict[str, Any]] = []
        for scan in scan_businesses(units):
            if wanted is not None and scan.code not in wanted:
                continue
            if wanted is None and not scan.behind:
                continue
            if scan.status not in ("active", "provisioning"):
                results.append({"code": scan.code, "name": scan.name, "ok": False, "applied": {},
                                "error": "this business is not active"})
                continue
            try:
                applied = reg.upgrade_tenant(scan.id)
                results.append({"code": scan.code, "name": scan.name, "ok": True, "applied": applied, "error": None})
            except Exception as error:  # noqa: BLE001 - report it for this business and carry on with the rest
                log.warning("Upgrading business %s failed", scan.code, exc_info=True)
                results.append({"code": scan.code, "name": scan.name, "ok": False, "applied": {},
                                "error": f"{type(error).__name__}: {str(error)[:200]}"})
        if wanted is not None:
            missing = wanted - {r["code"] for r in results}
            if missing:
                raise NotFound("No such business: " + ", ".join(sorted(missing)))
        return results
    target = ",".join(sorted(codes)) if codes else "all businesses behind"
    result: list[dict[str, Any]] = _change(operator, "business.upgrade", target, ip_address, work)
    # The per-business results go to the trail too (a list is not a dict, so _change did not store them).
    log_action(operator, "business.upgrade.results", target=target, ip_address=ip_address,
               detail={"results": [{"code": r["code"], "ok": r["ok"], "units": sorted(r["applied"])} for r in result]})
    return result


# --------------------------------------------------------------------------- platform health
def _backup_status() -> dict[str, Any]:
    folder = get_settings().backup_dir.strip()
    if not folder or not Path(folder).is_dir():
        return {"reported": False, "master_taken_at": None, "master_age_hours": None, "tenants_without_backup": []}
    root = Path(folder)
    master = backup.list_backups(root, "master")
    taken = master[-1].taken_at if master else None
    with master_session() as m:
        codes = list(m.execute(text("select code from master.tenant where status = 'active' order by code")).scalars())
    missing = [c for c in codes if not backup.list_backups(root, c)]
    return {"reported": True, "master_taken_at": taken,
            "master_age_hours": round((_now() - taken).total_seconds() / 3600, 1) if taken else None,
            "tenants_without_backup": missing}


def _plugin_status(units: dict[str, Manifest]) -> dict[str, Any]:
    settings = get_settings()
    allowed = settings.allowed_plugin_map()
    loaded = []
    for m in sorted(units.values(), key=lambda u: u.name):
        if _source(m) != "extra folder":
            continue
        actual = plugin_trust.tree_digest(m.path)
        loaded.append({"name": m.name, "title": m.title, "version": m.version, "checksum": actual,
                       "manifest_checksum_ok": (not m.checksum) or m.checksum == actual,
                       "on_allow_list": m.name in allowed,
                       "pinned": bool(allowed.get(m.name) or m.checksum)})
    return {"folders": settings.extra_unit_path_list(), "production_allow_list": settings.env == "production",
            "loaded": loaded, "refused": [{"name": n, "reason": r} for n, r in sorted(plugin_trust.refused.items())]}


def platform_health() -> dict[str, Any]:
    """Readiness, migrations, backups, queues, registrations and extra plugins in one reading."""
    from ziira.kernel.api.ops_routes import MASTER_MIGRATIONS, readiness_problems

    units = discover()
    scans = scan_businesses(units)
    with master_session() as m:
        applied = set(m.execute(text("select migration from master.schema_migration")).scalars()) \
            if m.execute(text("select to_regclass('master.schema_migration')")).scalar() else set()
        registrations = m.execute(text(
            "select count(*) filter (where expires_at > now()) as pending, "
            "count(*) filter (where expires_at <= now()) as expired from master.registration "
            "where verified_at is null")).one()
    problems = readiness_problems()
    try:
        snap = platform_metrics.collect()
        queues: dict[str, Any] | None = {
            **{k: int(v) for k, v in snap.sums.items()},
            "jobs_oldest_due_seconds": int(snap.maxes["jobs_oldest_due_seconds"]),
            "outbox_lag_seconds": int(snap.maxes["outbox_lag_seconds"]),
            "tenant_errors": snap.tenant_errors, "collected_at": datetime.fromtimestamp(snap.collected_at, UTC),
            "recurring": [{"name": n, "oldest_run_age_seconds": int(a),
                           "failing_businesses": snap.periodic_failures.get(n, 0)}
                          for n, a in sorted(snap.periodic_age.items())]}
    except Exception:  # noqa: BLE001 - the rest of the page is still worth showing
        log.warning("Operator console: platform metrics unavailable", exc_info=True)
        queues = None
    return {
        "ready": not problems, "problems": problems,
        "master_migrations_pending": sorted(
            f.name for f in MASTER_MIGRATIONS.glob("*.up.sql") if f.name not in applied),
        "businesses_total": len(scans),
        "businesses_behind": [{"code": b.code, "name": b.name, "behind": b.behind} for b in scans if b.behind],
        "businesses_unreadable": [{"code": b.code, "name": b.name, "error": b.error} for b in scans if b.error],
        "backups": _backup_status(), "queues": queues,
        "registrations": {"pending": int(registrations.pending), "expired": int(registrations.expired)},
        "plugins": _plugin_status(units)}


# --------------------------------------------------------------------------- operators
def operators_overview() -> list[dict[str, Any]]:
    """The platform staff: read only (they are created, disabled and reset from the command line)."""
    with master_session() as m:
        return [dict(r._mapping) for r in m.execute(text(
            "select o.id, o.name, o.email, o.status, o.role, o.created_at, o.last_sign_in_at, "
            "(o.mfa_secret_enc <> '') as mfa_enrolled, o.must_change_password, "
            "(select count(*) from master.operator_session s where s.operator_id = o.id and s.revoked_at is null "
            "  and s.expires_at > now()) as open_sessions from master.operator o order by o.name"))]

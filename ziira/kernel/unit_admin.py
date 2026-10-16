"""Apps & plugins: what a business can switch on or off, and doing it (the same Registry the CLI uses).

Enabling a unit also enables the units it requires; disabling keeps the data; removing deletes the unit's data for
this business only. The platform's own installing and uninstalling stay operator jobs (the CLI).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.errors import DependencyError, NotFound
from ziira.kernel.manifest import Manifest
from ziira.kernel.platform import entitlements
from ziira.kernel.registry import Registry

PERMISSION = "units.manage"


def _requirers(units: dict[str, Manifest], name: str, among: set[str]) -> list[str]:
    return sorted(u for u in among if u in units and name in units[u].requires)


def _enabled(session: Session) -> set[str]:
    return set(session.execute(text(
        "select unit_name from kernel.tenant_unit where status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).scalars())


def _present(session: Session) -> set[str]:
    """Units whose tables exist in this business's database (enabled now, or enabled once and later switched off)."""
    return set(session.execute(text("select name from kernel.unit")).scalars())


def _titles(units: dict[str, Manifest], names: list[str]) -> str:
    return ", ".join(units[n].title for n in names)


def catalog(session: Session, reg: Registry) -> list[dict[str, Any]]:
    """Every module and plugin (the kernel excluded) with its state for this business and what can be done now."""
    installed = reg.installed()
    enabled = _enabled(session)
    present = _present(session)
    plan = entitlements.for_tenant(session.execute(text("select kernel.current_tenant()")).scalar_one())
    out: list[dict[str, Any]] = []
    for m in sorted(reg.units.values(), key=lambda u: (u.kind != "module", u.title)):
        if m.core or m.platform_scope:
            continue
        is_installed = m.name in installed
        is_enabled = m.name in enabled
        dependants = _requirers(reg.units, m.name, enabled)
        present_dependants = _requirers(reg.units, m.name, present)
        needs = [n for n in m.requires if n in reg.units and n not in enabled]
        also = [n for n in needs]
        for n in needs:
            also += [r for r in reg.units[n].requires if r not in enabled and r not in also]
        can_disable, why_not_disable = True, None
        if not is_enabled:
            can_disable, why_not_disable = False, "It is not switched on."
        elif dependants:
            can_disable, why_not_disable = False, f"Needed by {_titles(reg.units, dependants)}: switch those off first."
        can_remove, why_not_remove = True, None
        if m.name not in present:
            can_remove, why_not_remove = False, "There is no data to remove."
        elif is_enabled:
            can_remove, why_not_remove = False, "Switch it off first."
        elif present_dependants:
            can_remove, why_not_remove = False, f"{_titles(reg.units, present_dependants)} still holds data " \
                                               "that needs it: remove that first."
        in_plan = plan.units is None or m.name in plan.units
        out.append({
            "name": m.name, "title": m.title, "description": m.description, "category": m.category,
            "countries": list(m.countries), "kind": m.kind, "version": m.version,
            "requires": list(m.requires), "optional": list(m.optional), "dependants": dependants,
            "installed": is_installed, "enabled": is_enabled, "has_data": m.name in present,
            "will_also_enable": [] if is_enabled else [n for n in reg.units if n in also],
            "can_enable": is_installed and not is_enabled and in_plan and all(n in installed for n in also),
            "in_plan": in_plan,
            "why_not_enable": None if in_plan else
            f"Not in your plan{f' ({plan.plan_name})' if plan.plan_name else ''}: upgrade to switch it on.",
            "can_disable": can_disable, "why_not_disable": why_not_disable,
            "can_remove": can_remove, "why_not_remove": why_not_remove})
    return out


def _unit(reg: Registry, name: str) -> Manifest:
    m = reg.units.get(name)
    if m is None:
        raise NotFound(f"'{name}' was not found")
    if m.core:
        raise DependencyError("The kernel is always on and cannot be changed")
    return m


def enable_unit(session: Session, reg: Registry, tenant_id: UUID, name: str) -> list[str]:
    """Switch a unit on, with the units it requires. Returns every unit newly switched on."""
    m = _unit(reg, name)
    installed = reg.installed()
    missing = [n for n in [m.name, *m.requires] if n in reg.units and n not in installed]
    if missing:
        raise DependencyError(f"{_titles(reg.units, missing)} is not available yet: ask your Ziira operator")
    newly = reg.enable(tenant_id, name)
    audit.record(session, "enable", "kernel.unit", None, {"unit": name, "enabled": newly})
    return newly


def disable_unit(session: Session, reg: Registry, tenant_id: UUID, name: str) -> None:
    """Switch a unit off; its data is kept."""
    _unit(reg, name)
    reg.disable(tenant_id, name)
    audit.record(session, "disable", "kernel.unit", None, {"unit": name})


def remove_unit(session: Session, reg: Registry, tenant_id: UUID, name: str, confirm: str) -> None:
    """Delete a switched-off unit's data for this business. `confirm` must be the unit's name."""
    _unit(reg, name)
    if confirm != name:
        raise DependencyError(f"Type the name '{name}' to confirm that its data will be deleted")
    reg.remove_from_tenant(tenant_id, name)
    audit.record(session, "remove", "kernel.unit", None, {"unit": name, "data_deleted": True})

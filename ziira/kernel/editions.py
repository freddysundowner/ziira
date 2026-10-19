"""Editions: named bundles of units, menu order and first steps (`editions.toml`, which is data, never per country).

A business picks an edition when it registers and may switch later. Switching only ever switches units ON; taking a
unit away stays an explicit act on the Apps & plugins screen. `mode` ('core' / 'standalone') of older callers maps to
the `full` / `intelligence` editions.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.config import get_settings
from ziira.kernel.errors import DependencyError, NotFound, ValidationFailed
from ziira.kernel.manifest import CATEGORIES
from ziira.kernel.registry import Registry

DEFAULT = "full"
MODE_ALIASES = {"core": "full", "standalone": "intelligence"}
BUILT_IN = Path(__file__).with_name("editions.toml")
GROUPS = ("sell", "services", "stock", "buy", "money", "people", "admin")


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    hint: str
    to: str
    unit: str          # the step is shown only while this unit is on ("" = always)


@dataclass(frozen=True)
class Edition:
    id: str
    title: str
    pitch: str
    units: tuple[str, ...]
    plugin_categories: tuple[str, ...]
    menu_groups: tuple[str, ...]
    landing: str
    checklist: tuple[Step, ...]
    sample_data: tuple[str, ...]
    default_plan: str = ""          # plan code a business of this edition starts a trial on (empty: none)


def _units(data: dict[str, object], edition: str) -> tuple[str, ...]:
    if "units_setting" in data:
        raw = str(getattr(get_settings(), str(data["units_setting"])))
        return tuple(u.strip() for u in raw.split(",") if u.strip())
    units = data.get("units", [])
    if not isinstance(units, list) or not units:
        raise ValueError(f"edition '{edition}' lists no units")
    return tuple(str(u) for u in units)


def load_editions(path: Path | None = None) -> dict[str, Edition]:
    """Read the editions file (the built-in one, or `ZIIRA_EDITIONS_FILE`). Raises ValueError if it is inconsistent."""
    file = path or (Path(get_settings().editions_file) if get_settings().editions_file else BUILT_IN)
    raw = tomllib.loads(file.read_text())
    out: dict[str, Edition] = {}
    for key, d in raw.items():
        steps = tuple(Step(id=s["id"], title=s["title"], hint=s.get("hint", ""), to=s["to"], unit=s.get("unit", ""))
                      for s in d.get("checklist", []))
        ids = [s.id for s in steps]
        if len(set(ids)) != len(ids):
            raise ValueError(f"edition '{key}': checklist step ids repeat")
        if any(not s.to.startswith("/") for s in steps) or (d.get("landing") and not str(d["landing"]).startswith("/")):
            raise ValueError(f"edition '{key}': pages are paths starting with '/'")
        groups = tuple(d.get("menu_groups", []))
        if any(g not in GROUPS for g in groups):
            raise ValueError(f"edition '{key}': menu_groups are from {', '.join(GROUPS)}")
        cats = tuple(d.get("plugin_categories", []))
        if any(c not in CATEGORIES for c in cats):
            raise ValueError(f"edition '{key}': unknown plugin category in {cats}")
        out[key] = Edition(id=key, title=d["title"], pitch=d["pitch"], units=_units(d, key), plugin_categories=cats,
                           menu_groups=groups, landing=d.get("landing", ""), checklist=steps,
                           sample_data=tuple(d.get("sample_data", [])), default_plan=str(d.get("default_plan", "")))
    if DEFAULT not in out:
        raise ValueError(f"the editions file must define '{DEFAULT}'")
    return out


def _default() -> str:
    """The edition used when none is asked for: the owner's choice in the Super Admin, else the built-in default."""
    from ziira.kernel.platform import behaviour

    try:
        chosen = behaviour.default_edition()
    except Exception:  # noqa: BLE001 - no master database (a tool run without one) means the built-in default
        chosen = ""
    return chosen if chosen in load_editions() else DEFAULT


def resolve(name: str | None = None, mode: str | None = None) -> str:
    """The edition a request means: `edition` if given, else the older `mode` mapped, else the default."""
    chosen = (name or "").strip().lower() or MODE_ALIASES.get((mode or "").strip().lower(), "") or _default()
    if chosen not in load_editions():
        raise ValidationFailed(f"Edition is one of: {', '.join(load_editions())}")
    return chosen


def get(name: str) -> Edition:
    editions = load_editions()
    if name not in editions:
        raise NotFound(f"Edition '{name}' was not found")
    return editions[name]


def enable_edition(registry: Registry, tenant_id: UUID, name: str) -> list[str]:
    """Switch on every unit of an edition (with what they require; units this platform does not ship are skipped).
    Returns the units newly switched on."""
    newly: list[str] = []
    for unit in get(name).units:
        if unit not in registry.units:        # a unit not built or not shipped here (yet) is skipped, not an error
            continue
        newly += registry.enable(tenant_id, unit)
    return newly


# ---- the business's own edition and first steps (kernel.tenant)

def current(session: Session) -> str:
    value = session.execute(text("select edition from kernel.tenant where id = kernel.current_tenant()")).scalar()
    return str(value) if value in load_editions() else DEFAULT


def switch(session: Session, registry: Registry, tenant_id: UUID, name: str) -> list[str]:
    """Move to another edition: switches its units on and keeps everything already on and every record."""
    edition = get(name)
    missing = [u for u in edition.units if u in registry.units and u not in registry.installed()]
    if missing:
        raise DependencyError(f"{', '.join(missing)} is not available yet: ask your Ziira operator")
    from ziira.kernel.platform import entitlements

    for unit in edition.units:                # a plan that lacks one of them refuses the switch (402 not_in_plan)
        if unit in registry.units:
            entitlements.check_unit(tenant_id, unit, registry.units[unit].title)
    before = current(session)
    newly = enable_edition(registry, tenant_id, name)
    session.execute(text("update kernel.tenant set edition = :e where id = kernel.current_tenant()"), {"e": name})
    audit.record(session, "switch_edition", "kernel.tenant", None, {"from": before, "to": name, "enabled": newly})
    return newly


def onboarding(session: Session) -> tuple[list[str], bool]:
    row = session.execute(text("select onboarding_done, onboarding_dismissed from kernel.tenant "
                               "where id = kernel.current_tenant()")).one()
    return list(row.onboarding_done), bool(row.onboarding_dismissed)


def mark_step(session: Session, step: str, done: bool) -> None:
    name = current(session)
    if step not in {s.id for s in get(name).checklist}:
        raise NotFound(f"There is no step '{step}' in this edition")
    session.execute(text(
        "update kernel.tenant set onboarding_done = case when cast(:d as boolean) then "
        "(select array_agg(distinct x) from unnest(onboarding_done || cast(:s as text)) x) "
        "else array_remove(onboarding_done, :s) end where id = kernel.current_tenant()"), {"s": step, "d": done})


def dismiss(session: Session, dismissed: bool) -> None:
    session.execute(text("update kernel.tenant set onboarding_dismissed = cast(:d as boolean) "
                               "where id = kernel.current_tenant()"), {"d": dismissed})

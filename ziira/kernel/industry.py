"""Industry packs: plugins (category "industry") that bring the DATA a kind of business starts with: its services, job
statuses, checklists, message templates, custom fields, check settings.

    a pack --is switched on for a business--> every unit that implements `kernel.industry_seeder`
    copies what the pack supplies for that unit into its own tables, once, for each company

A pack is a folder with `manifest.toml` (category = "industry"), `data/pack.toml` and one data file per unit it feeds
(`data/products.toml`, `data/jobs.toml` ...; the file name is the unit's name). The kernel's own seeder reads
`data/custom_fields.toml`. See docs/industry-packs.md.

Seeding is the same promise the country packs make: it only adds what is missing, never overwrites or removes what the
business changed, never touches a posted record, and running it again changes nothing. Every item it adds is written to
`kernel.pack_seed_log`, so switching a pack off can offer to remove what was never touched.
"""

import logging
import tomllib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import context, custom_fields
from ziira.kernel.db import tenant_session
from ziira.kernel.errors import NotFound
from ziira.kernel.extensions import define_extension_point, implementations, provides
from ziira.kernel.manifest import Manifest

if TYPE_CHECKING:
    from ziira.kernel.registry import Registry

log = logging.getLogger("ziira.industry")
INDUSTRY_SEEDER = "kernel.industry_seeder"
CATEGORY = "industry"
PACK_FILE = "pack.toml"
# data files the kernel itself reads (the others are named after units)
KERNEL_DATA_FILES = ("custom_fields", "checklist")


def is_industry(m: Manifest) -> bool:
    return m.kind == "plugin" and m.category == CATEGORY


@dataclass(frozen=True)
class PackData:
    """What a pack supplies. `meta` is `data/pack.toml`; `unit_data(unit)` is the pack's file for that unit."""

    name: str                       # the plugin's name, e.g. "pack_salon"
    title: str
    summary: str
    meta: dict[str, Any]
    directory: Path

    @property
    def units(self) -> tuple[str, ...]:
        return tuple(self.meta.get("units", ()))

    @property
    def editions(self) -> tuple[str, ...]:
        return tuple(self.meta.get("editions", ()))

    def unit_data(self, unit: str) -> dict[str, Any]:
        """The pack's data for one unit (its `data/<unit>.toml` as a dict; empty when the pack has none)."""
        path = self.directory / "data" / f"{unit}.toml"
        return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@dataclass(frozen=True)
class SeededItem:
    item_type: str                  # what kind of row ("product", "custom_field_def" ...)
    item_id: UUID
    label: str = ""


@dataclass
class SeedReport:
    """What one seeder did for one pack and company."""

    added: list[SeededItem] = field(default_factory=list)
    skipped: int = 0                # already there (or its record type is not available): left as it is
    notes: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.added)


class IndustrySeeder(ABC):
    """Contract of the "kernel.industry_seeder" extension point: a unit copies the data an industry pack supplies for it
    into its own tables. `unit` names the data file (`data/<unit>.toml`). Must be idempotent and only add what is
    missing; report every row added so the pack can be switched off later."""

    name: str = "seeder"
    unit: str = ""

    @abstractmethod
    def seed(self, session: Session, pack: PackData, company_id: UUID) -> SeedReport:
        """Add what is missing for the company from `pack.unit_data(self.unit)`."""

    def untouched(self, session: Session, item_type: str, item_id: UUID) -> bool:
        """True when a row this seeder added is still exactly as the pack made it and nothing refers to it: removing it
        loses nothing. The default says no (nothing is offered for removal unless a unit opts in)."""
        return False

    def remove(self, session: Session, item_type: str, item_id: UUID) -> None:
        """Remove a row `untouched` approved. Only called after `untouched` returned True."""
        raise NotImplementedError(f"{self.name} approved removing a row but cannot remove it")


define_extension_point(INDUSTRY_SEEDER, IndustrySeeder,
                       "A unit that copies the data of an industry pack (services, statuses, templates, fields) "
                       "into its own tables")


# --------------------------------------------------------------------------- reading and checking a pack
def load_pack(m: Manifest) -> PackData:
    path = m.path / "data" / PACK_FILE
    meta: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8")).get("pack", {}) if path.exists() else {}
    return PackData(name=m.name, title=m.title, summary=m.description, meta=meta, directory=m.path)


def validate_pack(m: Manifest, known_units: set[str], known_editions: set[str]) -> list[str]:
    """Problems with a pack's files, in plain words (empty: fine). Used by the tests and the pack kit."""
    problems: list[str] = []
    if not is_industry(m):
        return [f"{m.name}: an industry pack is a plugin with category = \"{CATEGORY}\""]
    data = m.path / "data"
    if not (data / PACK_FILE).exists():
        return [f"{m.name}: data/{PACK_FILE} is missing"]
    try:
        meta = tomllib.loads((data / PACK_FILE).read_text(encoding="utf-8")).get("pack")
    except tomllib.TOMLDecodeError as exc:
        return [f"{m.name}: data/{PACK_FILE} is not valid TOML ({exc})"]
    if not isinstance(meta, dict):
        return [f"{m.name}: data/{PACK_FILE} needs a [pack] table"]
    if not m.description:
        problems.append(f"{m.name}: the manifest needs a one-sentence description (it is the pack's summary)")
    units = meta.get("units", [])
    if not isinstance(units, list) or any(not isinstance(u, str) for u in units):
        problems.append(f"{m.name}: [pack] units is a list of unit names")
        units = []
    for unit in units:
        if unit not in known_units:
            problems.append(f"{m.name}: [pack] units names '{unit}', which is not a unit")
        elif unit not in m.requires and unit not in m.optional:
            problems.append(f"{m.name}: '{unit}' is in [pack] units but not in the manifest's requires or optional")
    editions = meta.get("editions", [])
    if not isinstance(editions, list):
        problems.append(f"{m.name}: [pack] editions is a list of edition names")
        editions = []
    problems += [f"{m.name}: [pack] editions names '{e}', which is not an edition" for e in editions
                 if e not in known_editions]
    for file in sorted(data.glob("*.toml")):
        if file.name == PACK_FILE:
            continue
        try:
            tomllib.loads(file.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{m.name}: data/{file.name} is not valid TOML ({exc})")
        if file.stem not in units and file.stem not in KERNEL_DATA_FILES:
            problems.append(f"{m.name}: data/{file.name} feeds '{file.stem}', which is not in [pack] units")
    problems += _checklist_problems(m, data / "checklist.toml")
    return problems


def _checklist_problems(m: Manifest, path: Path) -> list[str]:
    """`data/checklist.toml`: `[[step]]` tables with id, title and `to` (the page that does the step)."""
    if not path.exists():
        return []
    try:
        steps = tomllib.loads(path.read_text(encoding="utf-8")).get("step", [])
    except tomllib.TOMLDecodeError:
        return []                                              # reported above as invalid TOML
    problems = [f"{m.name}: a checklist step needs an id, a title and a page (to)" for s in steps
                if not all(isinstance(s.get(k), str) and s.get(k) for k in ("id", "title", "to"))]
    ids = [s.get("id") for s in steps]
    if len(set(ids)) != len(ids):
        problems.append(f"{m.name}: checklist step ids repeat")
    return problems


def check_pack(name: str) -> list[str]:
    """Problems with the pack called `name` among the units this platform finds (a pack's own test calls this)."""
    from ziira.kernel import editions
    from ziira.kernel.registry import discover

    units = discover()
    if name not in units:
        return [f"{name}: the platform does not find this pack (is its folder on ZIIRA_EXTRA_UNIT_PATHS?)"]
    return validate_pack(units[name], set(units), set(editions.load_editions()))


def installed_packs(units: dict[str, Manifest]) -> list[Manifest]:
    return sorted((m for m in units.values() if is_industry(m)), key=lambda m: m.title)


# --------------------------------------------------------------------------- seeding
def _log(session: Session, pack: str, company_id: UUID, seeder: str, item: SeededItem) -> None:
    session.execute(text(
        "insert into kernel.pack_seed_log (tenant_id, pack, company_id, seeder, item_type, item_id, item_label) "
        "values (kernel.current_tenant(), :p, :c, :s, :t, :i, :l) "
        "on conflict (tenant_id, pack, seeder, item_type, item_id) do nothing"),
        {"p": pack, "c": str(company_id), "s": seeder, "t": item.item_type, "i": str(item.item_id), "l": item.label})


def seed_company(session: Session, packs: list[PackData], company_id: UUID) -> dict[str, int]:
    """Run every seeder of every enabled unit for each pack that is on. Returns rows added per `pack/seeder`."""
    added: dict[str, int] = {}
    for pack in packs:
        for seeder in implementations(session, INDUSTRY_SEEDER):
            report = seeder.seed(session, pack, company_id)
            for item in report.added:
                _log(session, pack.name, company_id, seeder.name, item)
            if report.count:
                added[f"{pack.name}/{seeder.name}"] = report.count
    return added


def enabled_packs(session: Session, registry: "Registry") -> list[PackData]:
    on = registry.enabled_for(session)
    return [load_pack(m) for m in installed_packs(registry.units) if m.name in on]


def apply_to_tenant(registry: "Registry", tenant_id: UUID) -> dict[str, dict[str, int]]:
    """Seed every company of a business from the industry packs switched on for it. Returns rows added per company."""
    previous = context._current.get()
    context.system_context(tenant_id)
    try:
        with tenant_session(tenant_id) as session:
            packs = enabled_packs(session, registry)
            if not packs:
                return {}
            ids = [UUID(str(i)) for i in session.execute(text("select id from kernel.company order by name")).scalars()]
            return {str(c): seeded for c in ids if (seeded := seed_company(session, packs, c))}
    finally:
        context._current.set(previous)


def after_enable(registry: "Registry", tenant_id: UUID, newly: list[str]) -> None:
    """Called when units were switched on for a business: seed when an industry pack came on, or when a seeding unit
    came on while a pack is already on. A failure is logged, not raised (`ziira apply-packs` runs it again)."""
    seeding = {m.name for m in registry.units.values() if INDUSTRY_SEEDER in m.implements}
    packs = {m.name for m in installed_packs(registry.units)}
    if not any(n in packs or n in seeding for n in newly):
        return
    with tenant_session(tenant_id, admin=True) as s:
        enabled = registry.enabled_for(s)
    if not enabled & packs:
        return
    from ziira.kernel.registry import load_event_handlers

    load_event_handlers(registry.units)
    try:
        apply_to_tenant(registry, tenant_id)
    except Exception:
        log.exception("Could not seed the industry pack data for %s", tenant_id)


# --------------------------------------------------------------------------- switching a pack off
@dataclass(frozen=True)
class SeededRow:
    seeder: str
    item_type: str
    item_id: UUID
    label: str
    untouched: bool


def seeded_rows(session: Session, pack: str) -> list[SeededRow]:
    """Everything a pack added, and whether each row is still as the pack made it (safe to remove)."""
    seeders = {s.name: s for s in implementations(session, INDUSTRY_SEEDER)}
    rows = session.execute(text(
        "select seeder, item_type, item_id, item_label from kernel.pack_seed_log where pack = :p "
        "order by seeder, item_label"), {"p": pack})
    out: list[SeededRow] = []
    for r in rows:
        seeder = seeders.get(r.seeder)
        out.append(SeededRow(r.seeder, r.item_type, r.item_id, r.item_label,
                             bool(seeder and seeder.untouched(session, r.item_type, r.item_id))))
    return out


def remove_untouched(session: Session, pack: str) -> int:
    """Remove what the pack added and nobody has used or changed. Returns how many rows went."""
    seeders = {s.name: s for s in implementations(session, INDUSTRY_SEEDER)}
    removed = 0
    for row in seeded_rows(session, pack):
        seeder = seeders.get(row.seeder)
        if seeder is None or not row.untouched:
            continue
        seeder.remove(session, row.item_type, row.item_id)
        session.execute(text("delete from kernel.pack_seed_log where pack = :p and seeder = :s and item_type = :t "
                             "and item_id = :i"),
                        {"p": pack, "s": row.seeder, "t": row.item_type, "i": str(row.item_id)})
        removed += 1
    return removed


def require_pack(units: dict[str, Manifest], name: str) -> Manifest:
    m = units.get(name)
    if m is None or not is_industry(m):
        raise NotFound(f"'{name}' is not an industry pack")
    return m


# --------------------------------------------------------------------------- the kernel's own seeder: custom fields
@provides(INDUSTRY_SEEDER)
class CustomFieldSeeder(IndustrySeeder):
    """Adds the custom fields a pack ships (`data/custom_fields.toml`, a list of `[[field]]` tables with entity_type,
    key, label, kind, and optionally choices, required, searchable). A field for a kind of record whose unit is off is
    skipped (and added by `ziira apply-packs` once the unit is on)."""

    name = "kernel.custom_fields"
    unit = "custom_fields"

    def seed(self, session: Session, pack: PackData, company_id: UUID) -> SeedReport:
        report = SeedReport()
        known = custom_fields.entities(session)
        for spec in pack.unit_data(self.unit).get("field", []):
            if spec["entity_type"] not in known:
                report.skipped += 1
                report.notes.append(f"{spec['key']}: {spec['entity_type']} is not available in this business")
                continue
            made, added = custom_fields.seed_definition(
                session, pack=pack.name, entity_type=spec["entity_type"], key=spec["key"], label=spec["label"],
                kind=spec["kind"], choices=list(spec.get("choices", [])), required=bool(spec.get("required", False)),
                searchable=bool(spec.get("searchable", False)))
            if added:
                report.added.append(SeededItem("custom_field_def", made.id, f"{spec['entity_type']}: {made.label}"))
            else:
                report.skipped += 1
        return report

    def untouched(self, session: Session, item_type: str, item_id: UUID) -> bool:
        row = session.execute(text("select entity_type, key from kernel.custom_field_def where id = :i"),
                              {"i": str(item_id)}).first()
        if row is None:
            return False
        used = session.execute(text(
            "select 1 from kernel.custom_field_value where entity_type = :t and data ? cast(:k as text) limit 1"),
            {"t": row.entity_type, "k": row.key}).first()
        return used is None

    def remove(self, session: Session, item_type: str, item_id: UUID) -> None:
        session.execute(text("delete from kernel.custom_field_def where id = :i"), {"i": str(item_id)})


# --------------------------------------------------------------------------- the first steps a pack adds to Home
def pack_steps(session: Session, registry: "Registry") -> list[tuple[str, str, str, str, str]]:
    """The first steps of the industry packs switched on for the business (`data/checklist.toml`, `[[step]]` tables
    with id, title, hint, to and optionally unit), as (id, title, hint, to, unit). Step ids start with the pack's
    name so they cannot clash with the edition's own."""
    steps: list[tuple[str, str, str, str, str]] = []
    for pack in enabled_packs(session, registry):
        for s in pack.unit_data("checklist").get("step", []):
            steps.append((f"{pack.name}_{s['id']}", str(s["title"]), str(s.get("hint", "")), str(s["to"]),
                          str(s.get("unit", ""))))
    return steps

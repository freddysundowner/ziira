"""Country packs: plugins that bring a country's DATA (tax codes, chart of accounts, payroll tables) to a business.

    a pack (category "country") --is switched on for a business--> every unit that has a `kernel.country_seeder`
    copies the pack's data into the business's own tables, once, for each company of that country

* A unit that has country-shaped data offers an extension point of its own (`products.tax_code_seed`,
  `finance.chart_template`, `people.statutory_table_seed`) with a generic fallback of its own, and implements
  `kernel.country_seeder` to copy what the packs supply. It reads the packs through `pack_providers`, which picks the
  providers that name the company's country, or else the worldwide ones (the international pack).
* Seeding is **data the business can edit**: it only adds what is missing (a row the business already has, changed or
  removed on purpose, is never overwritten) and never touches a posted record. Running it again changes nothing.
* It runs when a pack is switched on, when a unit that seeds is switched on later, at registration (the pack of the
  chosen country, else the international one) and on `ziira apply-packs`.
"""

import logging
import tomllib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import context
from ziira.kernel.countries import is_pack, pack_for
from ziira.kernel.db import tenant_session
from ziira.kernel.extensions import define_extension_point, implementations

if TYPE_CHECKING:
    from ziira.kernel.registry import Registry

log = logging.getLogger("ziira.packs")
COUNTRY_SEEDER = "kernel.country_seeder"


class CountrySeeder(ABC):
    """Contract of the "kernel.country_seeder" extension point: a unit copies the data country packs supply into its own
    tables for one company. Must be idempotent and only add what is missing."""

    name: str = "seeder"

    @abstractmethod
    def seed(self, session: Session, company_id: UUID, country: str | None) -> int:
        """Add what is missing for the company (its ISO country, or None). Returns how many rows were added."""


define_extension_point(COUNTRY_SEEDER, CountrySeeder,
                       "A unit that copies the data of the business's country pack into its own tables")


def read_pack_data(module_file: str, name: str) -> dict[str, Any]:
    """A pack's data file (TOML) from the `data/` folder beside the Python file `module_file` (pass `__file__`). Figures
    and names live in these files, never in code."""
    return tomllib.loads((Path(module_file).parent / "data" / name).read_text(encoding="utf-8"))


def company_country(session: Session, company_id: UUID) -> str | None:
    value = session.execute(text("select country from kernel.company where id = :c"), {"c": str(company_id)}).scalar()
    return str(value).upper() if value else None


def pack_providers(session: Session, point: str, company_id: UUID) -> list[Any]:
    """The implementations of a unit's seed socket that apply to the company: those of packs naming its country; when
    there are none, the worldwide ones (a pack with no `countries`). A company with no country recorded takes every
    pack that is on (someone switched the pack on for it on purpose). Only packs switched on for the business count."""
    country = company_country(session, company_id)
    found = implementations(session, point)
    if country is None:
        return list(found)
    specific = [i for i in found if country and country in getattr(i, "countries", ())]
    return specific or [i for i in found if not getattr(i, "countries", ())]


def seed_company(session: Session, company_id: UUID) -> dict[str, int]:
    """Run every seeder for one company. Returns rows added per seeder (only those that added something)."""
    country = company_country(session, company_id)
    added: dict[str, int] = {}
    for seeder in implementations(session, COUNTRY_SEEDER):
        count = seeder.seed(session, company_id, country)
        if count:
            added[seeder.name] = count
    return added


def apply_to_tenant(tenant_id: UUID) -> dict[str, dict[str, int]]:
    """Seed every company of a business from the packs switched on for it. Returns rows added per company."""
    previous = context._current.get()
    context.system_context(tenant_id)
    try:
        with tenant_session(tenant_id) as session:
            ids = [UUID(str(i)) for i in session.execute(text("select id from kernel.company order by name")).scalars()]
            return {str(c): seeded for c in ids if (seeded := seed_company(session, c))}
    finally:
        context._current.set(previous)


def enable_country_pack(registry: "Registry", tenant_id: UUID, country: str | None) -> str | None:
    """Switch on the pack for a business's country: the pack that names it, else the international pack. Nothing happens
    when no such pack is installed (the business works with the units' own fallbacks). Returns the pack's name."""
    pack = pack_for(country, registry.units, registry.installed())
    if pack is None:
        return None
    registry.enable(tenant_id, pack.name)
    return pack.name


def after_enable(registry: "Registry", tenant_id: UUID, newly: list[str]) -> None:
    """Called when units were switched on for a business: seed when a pack came on, or when a seeding unit came on
    while a pack is already on. A failure is logged, not raised (the unit is on; `ziira apply-packs` runs it again)."""
    from ziira.kernel.registry import load_event_handlers

    seeding = {m.name for m in registry.units.values() if COUNTRY_SEEDER in m.implements}
    if not any(is_pack(registry.units[n]) or n in seeding for n in newly if n in registry.units):
        return
    with tenant_session(tenant_id, admin=True) as s:
        enabled = registry.enabled_for(s)
    if not any(is_pack(registry.units[n]) for n in enabled if n in registry.units) or not enabled & seeding:
        return
    load_event_handlers(registry.units)
    try:
        apply_to_tenant(tenant_id)
    except Exception:
        log.exception("Could not seed the country pack data for %s", tenant_id)

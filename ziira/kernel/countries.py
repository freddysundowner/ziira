"""Countries: the list the sign-up form offers, and what a country pack adds to an entry.

The built-in list (`data/countries.json`) is plain reference data: name, calling code, usual currency and main time
zone for each country, so ANY country can register. A *country pack* is a plugin with `category = "country"` and
`countries = [...]`; its `data/country.toml` refines the entries of its countries (a different currency or zone, the
label and pattern of its tax number, date and number formats) and the pack's other data files (tax codes, chart of
accounts, payroll tables) are seeded into a business that switches the pack on (`packs.py`). Nothing here is
behaviour: no unit treats any country specially.
"""

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ziira.kernel.manifest import Manifest

BUILT_IN = Path(__file__).parent / "data" / "countries.json"
COUNTRY_FILE = "country.toml"
INTERNATIONAL_PACK = "pack_international"       # the pack used when no pack names the business's country


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    calling: str
    currency: str
    zone: str
    pack: str | None = None                 # the country pack that names this country (installed or not)
    pack_available: bool = False            # ... and it is installed on this platform
    tax_id_label: str = ""
    tax_id_pattern: str = ""                # a hint for the sign-up form, not a rule the server enforces
    date_format: str = ""
    number_format: str = ""


def built_in() -> dict[str, Country]:
    """The built-in list, by ISO code."""
    data = json.loads(BUILT_IN.read_text(encoding="utf-8"))
    return {c["code"]: Country(c["code"], c["name"], c["calling"], c["currency"], c["zone"]) for c in data["countries"]}


def is_pack(m: Manifest) -> bool:
    return m.kind == "plugin" and m.category == "country"


def pack_file(m: Manifest) -> dict[str, Any]:
    """A pack's `data/country.toml` as a dict (empty when it has none)."""
    path = m.path / "data" / COUNTRY_FILE
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def check_pack_file(m: Manifest) -> list[str]:
    """Problems with a pack's country file (empty when it is fine): used at install and by the tests."""
    problems: list[str] = []
    entries = pack_file(m).get("country", [])
    codes = [str(e.get("code", "")) for e in entries]
    if m.countries and sorted(codes) != sorted(m.countries):
        problems.append(f"{m.name}: country.toml names {codes}, the manifest says {list(m.countries)}")
    for e in entries:
        for key in ("code", "name", "currency", "phone_calling_code", "timezone"):
            if not str(e.get(key, "")).strip():
                problems.append(f"{m.name}: {e.get('code', '?')} has no {key}")
        if e.get("tax_id_pattern"):
            try:
                re.compile(str(e["tax_id_pattern"]))
            except re.error:
                problems.append(f"{m.name}: {e.get('code')}: tax_id_pattern is not a regular expression")
    return problems


def packs_by_country(units: dict[str, Manifest]) -> dict[str, list[Manifest]]:
    """Country packs by the ISO codes they name (worldwide packs are under the empty string)."""
    found: dict[str, list[Manifest]] = {}
    for m in sorted(units.values(), key=lambda u: u.name):
        if is_pack(m):
            for code in m.countries or ("",):
                found.setdefault(code, []).append(m)
    return found


def pack_for(country: str | None, units: dict[str, Manifest], installed: set[str] | None = None) -> Manifest | None:
    """The pack a business in `country` should have: the pack that names the country, else the international pack,
    else None. With `installed`, only packs installed on the platform count."""
    def usable(m: Manifest) -> bool:
        return installed is None or m.name in installed

    by_country = packs_by_country(units)
    for m in by_country.get((country or "").upper(), []):
        if usable(m):
            return m
    international = units.get(INTERNATIONAL_PACK)
    return international if international is not None and usable(international) else None


def catalogue(units: dict[str, Manifest], installed: set[str] | None = None) -> list[Country]:
    """The countries a new business can choose: the built-in list with each pack's refinements, sorted by name."""
    out = built_in()
    for code, packs in packs_by_country(units).items():
        if not code:
            continue
        for m in packs:
            for entry in pack_file(m).get("country", []):
                if entry.get("code") != code:
                    continue
                base = out.get(code)
                out[code] = Country(
                    code=code, name=str(entry.get("name") or (base.name if base else code)),
                    calling=str(entry.get("phone_calling_code") or (base.calling if base else "")),
                    currency=str(entry.get("currency") or (base.currency if base else "")),
                    zone=str(entry.get("timezone") or (base.zone if base else "UTC")),
                    pack=m.name, pack_available=installed is None or m.name in installed,
                    tax_id_label=str(entry.get("tax_id_label", "")),
                    tax_id_pattern=str(entry.get("tax_id_pattern", "")),
                    date_format=str(entry.get("date_format", "")), number_format=str(entry.get("number_format", "")))
    return sorted(out.values(), key=lambda c: c.name)

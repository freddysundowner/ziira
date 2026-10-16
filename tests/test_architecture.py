"""Module boundary rules, checked on every test run.

1. Modules and plugins never import ziira.kernel (they use ziira.sdk).
2. A unit may import another unit only through its public.py.
3. No module or kernel code names a country, a currency, a tax authority or a vendor (rule 15): those are data a business
   enters, or belong to a plugin (a country pack, a provider plugin).
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "ziira"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _unit_files() -> list[tuple[str, str, Path]]:
    files = []
    for kind in ("modules", "plugins"):
        for unit_dir in (ROOT / kind).iterdir():
            if unit_dir.is_dir() and (unit_dir / "manifest.toml").exists():
                files += [(kind, unit_dir.name, f) for f in unit_dir.rglob("*.py")]
    return files


def test_units_do_not_import_kernel() -> None:
    bad = [f"{f}: {m}" for _, _, f in _unit_files() for m in _imports(f) if m.startswith("ziira.kernel")]
    assert not bad, "Use ziira.sdk instead of ziira.kernel:\n" + "\n".join(bad)


def test_units_only_use_other_units_public_interface() -> None:
    bad = []
    for _, unit, f in _unit_files():
        for m in _imports(f):
            parts = m.split(".")
            other_unit = len(parts) >= 3 and parts[:2] in (["ziira", "modules"], ["ziira", "plugins"])
            if other_unit and parts[2] != unit and (len(parts) < 4 or parts[3] != "public"):
                bad.append(f"{f}: {m}")
    assert not bad, "Import other units only through their public.py:\n" + "\n".join(bad)


def test_hooks_in_code_match_the_manifests() -> None:
    """Every socket a unit defines or plugs into in code is declared in its manifest, and back."""
    from ziira.kernel import extensions
    from ziira.kernel.registry import discover, load_event_handlers

    units = discover()
    load_event_handlers(units)
    assert not extensions.undefined_registrations()
    points, hooks = extensions.extension_points(), extensions.validation_hooks()
    in_code: dict[str, dict[str, set[str]]] = {name: {"extension_points": set(), "validation_hooks": set(),
                                                      "implements": set(), "validates": set()} for name in units}
    for p in points.values():
        if p.owner in in_code:
            in_code[p.owner]["extension_points"].add(p.name)
        for unit, _ in p.implementations:
            if unit in in_code:
                in_code[unit]["implements"].add(p.name)
    for h in hooks.values():
        if h.owner in in_code:
            in_code[h.owner]["validation_hooks"].add(h.name)
        for unit, _ in h.validators:
            if unit in in_code:
                in_code[unit]["validates"].add(h.name)
    for name, m in units.items():
        declared = {"extension_points": set(m.extension_points), "validation_hooks": set(m.validation_hooks),
                    "implements": set(m.implements), "validates": set(m.validates)}
        assert in_code[name] == declared, f"{name}: manifest says {declared}, code does {in_code[name]}"


# ---------------------------------------------------------------------------------------------- no country in code
COUNTRY_WORDS = re.compile(
    r"\b(?:KES|Ksh|KRA|PAYE|NHIF|NSSF|SHIF)\b|(?i:\b(?:Daraja|Safaricom|M-Pesa|mpesa|eTIMS|Kenya\w*|Nairobi|Mombasa|Airtel)\b)"
    r"|Africa/|(?<!=)\b254\b(?!\))|\b254\d{2,}")

# file relative to ziira/ -> (words allowed there, why it could not move). Aim: empty. Each entry is a known leftover.
ALLOWED: dict[str, tuple[tuple[str, ...], str]] = {
    "modules/connect/connectors/_http.py": (
        ("mpesa", "m-pesa", "airtel"),
        "words that tell a mobile-money payment method from a bank one in a customer's ERP export (source aliases)"),
    "modules/connect/connectors/files.py": (
        ("mpesa", "m-pesa", "airtel"),
        "words that tell a mobile-money column or sheet from a bank one in an uploaded export (source aliases)"),
    "modules/connect/connectors/csv_exports.py": (
        ("mpesa",), "a column-heading alias ('mpesa code') in a customer's CSV export (source alias)"),
}


def _scanned_files() -> list[Path]:
    files = []
    for area in ("modules", "kernel"):
        for f in (ROOT / area).rglob("*"):
            parts = f.relative_to(ROOT).parts
            if (f.is_file() and f.suffix in (".py", ".toml") and "__pycache__" not in parts
                    and not {"tests", "data", "migrations", "master_migrations"} & set(parts)):
                files.append(f)
    return files


def test_modules_and_kernel_name_no_country_currency_or_vendor() -> None:
    """Rule 15, enforced: scans modules and kernel (not tests, `data/` reference files or SQL history). A known leftover
    must be in ALLOWED with its reason."""
    found: dict[tuple[str, str], list[int]] = {}
    for f in _scanned_files():
        rel = str(f.relative_to(ROOT))
        for number, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for match in COUNTRY_WORDS.finditer(line):
                found.setdefault((rel, match.group(0).lower()), []).append(number)
    bad = {k: v for k, v in found.items() if k[1] not in ALLOWED.get(k[0], ((), ""))[0]}
    assert not bad, "Country- or vendor-specific words in code (move them to a pack or a provider plugin, or make them " \
        "data):\n" + "\n".join(f"{path}: {word!r} at lines {lines}" for (path, word), lines in sorted(bad.items()))
    stale = [(path, word) for path, (words, _) in ALLOWED.items() for word in words if (path, word) not in found]
    assert not stale, f"ALLOWED lists leftovers that no longer exist (remove them): {stale}"

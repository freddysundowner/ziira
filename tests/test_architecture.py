"""Module boundary rules, checked on every test run.

1. Modules and plugins never import ziira.kernel (they use ziira.sdk).
2. A unit may import another unit only through its public.py.
"""

import ast
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

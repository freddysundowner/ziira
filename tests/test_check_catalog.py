"""The marketing site's catalogue of checks and actions is generated from the real registry (scripts/export_check_catalog.py).

These tests run the script against every unit's registrations. They need no database. They fail when a check, an action or an
Ask Ziira tool is added without its plain-language text in site/src/content/*.plain.json, or when that text outlives its check,
or when the committed site/src/content/checks.catalog.json is stale (run `make site-catalog`).
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "site" / "src" / "content"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_check_catalog", ROOT / "scripts" / "export_check_catalog.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _impls(point: str) -> list[Any]:
    from ziira.kernel.extensions import implementations_of

    return list(implementations_of(point))


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load_script()


@pytest.fixture(scope="module")
def catalog(script: ModuleType) -> dict[str, Any]:
    built: dict[str, Any] = script.build_catalog()
    return built


def test_the_catalogue_lists_real_checks_in_known_areas(catalog: dict[str, Any]) -> None:
    from ziira.modules.intel.public import AREAS

    assert catalog["totals"]["checks"] > 0
    assert catalog["totals"]["checks"] == len(catalog["checks"])
    assert catalog["totals"]["ziira"] + catalog["totals"]["connected"] == catalog["totals"]["checks"]
    assert catalog["totals"]["connected"] > 0
    assert len({c["code"] for c in catalog["checks"]}) == len(catalog["checks"]), "a check code appears twice"
    assert set(catalog["totals"]["by_area"]) <= set(AREAS)
    assert sum(catalog["totals"]["by_area"].values()) == catalog["totals"]["checks"]
    # a connected check is exactly one whose code starts with standalone.
    for c in catalog["checks"]:
        assert (c["source"] == "connected") == c["code"].startswith("standalone."), c["code"]


def test_every_check_has_plain_text_a_group_an_example_and_labelled_limits(catalog: dict[str, Any]) -> None:
    groups = {g["key"] for g in catalog["groups"]}
    for c in catalog["checks"]:
        assert c["title"] and c["description"], c["code"]
        assert c["plain"] and len(c["plain"]) >= 30, f"{c['code']} has no plain description"
        assert c["example"], f"{c['code']} has no example"
        assert c["group"] in groups, f"{c['code']} has an unknown group {c['group']}"
        for limit in c["limits"]:
            assert limit["label"], f"{c['code']} limit '{limit['name']}' has no plain label"
        if c["source"] == "connected":
            assert c["needs"], f"{c['code']} does not say which data it needs"


def test_group_counts_add_up(catalog: dict[str, Any]) -> None:
    assert sum(g["count"] for g in catalog["groups"]) == catalog["totals"]["checks"]
    for g in catalog["groups"]:
        assert g["ziira"] + g["connected"] == g["count"]
        assert g["count"] == sum(1 for c in catalog["checks"] if c["group"] == g["key"])


def test_plain_text_has_no_entry_for_a_check_that_does_not_exist(catalog: dict[str, Any]) -> None:
    plain = json.loads((CONTENT / "checks.plain.json").read_text())
    known = {c["code"] for c in catalog["checks"]}
    stale = {k for k in plain if not k.startswith("_")} - known
    assert not stale, f"checks.plain.json describes checks that do not exist: {sorted(stale)}"


def test_every_registered_action_is_listed_with_plain_text(catalog: dict[str, Any]) -> None:
    registered = {str(a.type) for a in _impls("intel.action")}
    listed = {a["type"] for a in catalog["actions"]}
    assert registered and listed == registered
    assert catalog["totals"]["actions"] == len(registered)
    codes = {c["code"] for c in catalog["checks"]}
    for a in catalog["actions"]:
        assert a["plain"] and a["example"] and a["level"] in (3, 4), a["type"]
        assert a["who_approves"], f"{a['type']}: permission {a['permission']} has no plain description"
        assert a["for_checks"], a["type"]
        for f in a["for_checks"]:
            assert f["code"] in codes, f"{a['type']} acts on {f['code']}, which is not a registered check"
        # only routine actions may run by themselves, and never one that touches money, prices or credit
        if a["automatic"]:
            assert a["level"] == 4, a["type"]
        else:
            assert a["level"] == 3, a["type"]
    plain = json.loads((CONTENT / "actions.plain.json").read_text())
    assert {k for k in plain if not k.startswith("_")} == registered


def test_every_ask_tool_has_a_plain_description(catalog: dict[str, Any]) -> None:
    registered = {str(t.name) for t in _impls("intel.ask_tool")}
    assert registered and {t["name"] for t in catalog["ask_tools"]} == registered
    for t in catalog["ask_tools"]:
        assert t["plain"], f"ask tool {t['name']} has no plain description in actions.plain.json (_ask_tools)"
    plain = json.loads((CONTENT / "actions.plain.json").read_text())
    assert set(plain["_ask_tools"]) == registered


def test_the_committed_catalogue_is_current(script: ModuleType, catalog: dict[str, Any]) -> None:
    committed = (CONTENT / "checks.catalog.json").read_text()
    assert committed == script.render(catalog), "site/src/content/checks.catalog.json is stale: run `make site-catalog`"

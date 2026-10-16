"""Write the catalogue of Intelligence checks, actions and Ask Ziira tools for the marketing site.

    .venv/bin/python scripts/export_check_catalog.py            # writes site/src/content/checks.catalog.json
    .venv/bin/python scripts/export_check_catalog.py --check    # exits 1 if the committed file is out of date

The facts come from the real registry: every `intel.check`, `intel.action` and `intel.ask_tool` implementation that any
unit (and the Connectors unit's standalone checks) registers. The plain-language text (what a check means, a made-up
example, its limits in plain words) lives in `site/src/content/checks.plain.json` and `actions.plain.json`, because
the site is written for business owners and the checks' own descriptions are written for the people who tune them.
`tests/test_check_catalog.py` fails when a check or action has no plain text. No database is needed.
`make site-catalog` runs this.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "site" / "src" / "content"
OUT = CONTENT / "checks.catalog.json"
PLAIN = CONTENT / "checks.plain.json"
ACTIONS_PLAIN = CONTENT / "actions.plain.json"

SEVERITY_LABEL = {"info": "Information", "low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}


def _registry() -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    from ziira.kernel.extensions import implementations_of
    from ziira.kernel.registry import load_event_handlers

    load_event_handlers()
    return (implementations_of("intel.check"), implementations_of("intel.action"), implementations_of("intel.ask_tool"),
            implementations_of("intel.baseline_metric"))


def _value(v: Any) -> Any:
    """A default as JSON: numbers stay numbers, everything else is text."""
    return v if isinstance(v, bool | int | float) else str(v)


def build_catalog() -> dict[str, Any]:
    """The whole catalogue as a JSON-ready dict (deterministic: no dates, sorted)."""
    plain = json.loads(PLAIN.read_text())
    plain_actions = json.loads(ACTIONS_PLAIN.read_text())
    checks, actions, tools, metrics = _registry()
    param_labels: dict[str, str] = plain["_params"]
    units: dict[str, str] = plain["_units"]
    groups: dict[str, dict[str, str]] = plain["_groups"]

    out_checks: list[dict[str, Any]] = []
    for c in sorted(checks, key=lambda c: c.code):
        p = plain.get(c.code, {})
        unit = c.code.split(".")[0]
        source = "connected" if unit == "standalone" else "ziira"
        limits = []
        for name, default in c.params.items():
            label = p.get("limits", {}).get(name) or param_labels.get(name)
            limits.append({"name": name, "label": label, "default": _value(default)})
        out_checks.append({
            "code": c.code, "area": c.area, "group": p.get("group"), "title": c.title, "description": c.description,
            "plain": p.get("plain"), "example": p.get("example"), "source": source,
            "unit": units.get(unit, unit), "needs": p.get("needs"),
            "severity": c.default_severity,
            "severity_label": SEVERITY_LABEL.get(c.default_severity, c.default_severity),
            "closes_itself": bool(c.auto_resolves), "limits": limits,
        })
    by_code = {c["code"]: c for c in out_checks}

    out_actions: list[dict[str, Any]] = []
    for a in sorted(actions, key=lambda a: a.type):
        p = plain_actions.get(a.type, {})
        out_actions.append({
            "type": a.type, "title": a.title, "description": a.description,
            "plain": p.get("plain"), "example": p.get("example"),
            "kind": p.get("kind"), "level": p.get("level"),
            "for_checks": [{"code": code, "title": by_code[code]["title"] if code in by_code else code}
                           for code in a.check_codes],
            "permission": a.needs_permission, "who_approves": plain_actions["_permissions"].get(a.needs_permission),
            "automatic": bool(a.auto_allowed),
            "rule_conditions": sorted((getattr(a, "rule_schema", None) or {}).get("properties", {})),
        })

    ask_plain = plain_actions.get("_ask_tools", {})
    out_tools = [{"name": t.name, "description": t.description, "plain": ask_plain.get(t.name)}
                 for t in sorted(tools, key=lambda t: t.name)]

    area_counts = Counter(c["area"] for c in out_checks)
    group_counts = {g: sum(1 for c in out_checks if c["group"] == g) for g in groups}
    group_counts_by_source = {s: {g: sum(1 for c in out_checks if c["group"] == g and c["source"] == s) for g in groups}
                              for s in ("ziira", "connected")}
    return {
        "groups": [{"key": k, "title": v["title"], "lead": v["lead"], "count": group_counts[k],
                    "ziira": group_counts_by_source["ziira"][k], "connected": group_counts_by_source["connected"][k]}
                   for k, v in groups.items()],
        "totals": {
            "checks": len(out_checks),
            "ziira": sum(1 for c in out_checks if c["source"] == "ziira"),
            "connected": sum(1 for c in out_checks if c["source"] == "connected"),
            "actions": len(out_actions),
            "automatic_actions": sum(1 for a in out_actions if a["automatic"]),
            "ask_tools": len(out_tools),
            "baselines": len(metrics),
            "by_area": dict(sorted(area_counts.items())),
        },
        "checks": out_checks,
        "actions": out_actions,
        "ask_tools": out_tools,
    }


def render(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--check", action="store_true", help="fail if the committed catalogue is out of date")
    args = parser.parse_args()
    text = render(build_catalog())
    if args.check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT} is out of date: run `make site-catalog`", file=sys.stderr)
            return 1
        print("catalogue is up to date")
        return 0
    OUT.write_text(text)
    data = json.loads(text)["totals"]
    print(f"Wrote {OUT} ({data['checks']} checks: {data['ziira']} in Ziira, {data['connected']} on connected systems; "
          f"{data['actions']} actions; {data['ask_tools']} ask tools)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

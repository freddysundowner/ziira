"""Reading unit manifests (manifest.toml in every module and plugin)."""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SDK_VERSION = "1.0"
CATEGORIES = ("sales", "stock", "purchasing", "accounting", "people", "customers", "payments", "tax", "messaging",
              "connector", "country", "intelligence", "data", "ai", "example")


@dataclass(frozen=True)
class PublicEvent:
    """An event a business may subscribe to with an outgoing webhook (docs/webhooks.md)."""

    description: str
    fields: tuple[str, ...]        # the payload keys sent; nothing else leaves the system


@dataclass(frozen=True)
class Manifest:
    """What a module or plugin declares about itself."""

    name: str
    kind: str                      # "module" or "plugin"
    version: str
    title: str
    package: str                   # Python package, e.g. "ziira.modules.products"
    path: Path                     # folder containing manifest.toml
    sdk: str = ">=1.0,<2.0"
    description: str = ""        # one plain sentence for the Apps & plugins screen
    category: str = ""           # how the Apps & plugins screen groups it (CATEGORIES); "" = by kind
    countries: tuple[str, ...] = ()   # plugins: ISO country codes it is meant for; empty = worldwide
    core: bool = False             # kernel only: always installed and enabled
    platform_scope: bool = False   # serves the platform itself (payment gateways): no business switches it on
    # [upgrade] enable_if_sql: read-only SQL run in each tenant database that has the units this one requires; when it
    # returns a row the unit is switched on there (an upgrade step: a plugin that took over from code that used to be
    # built in is switched on for the businesses that were using it).
    upgrade_enable_sql: str = ""
    publisher: str = ""            # who made it (shown to reviewers and on the Apps & plugins screen)
    homepage: str = ""
    checksum: str = ""             # sha256 of the unit's files, set by `ziira plugin pack` (docs/plugin-review.md)
    requires: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    permissions: dict[str, str] = field(default_factory=dict)
    publishes: tuple[str, ...] = ()
    subscribes: tuple[str, ...] = ()
    api_prefix: str | None = None
    settings: tuple[str, ...] = ()
    # Default role name -> permissions of this unit it receives when the unit is enabled.
    # The Owner role always receives every permission, so it is not listed.
    roles: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Reason code category -> {code: label}, seeded for a tenant when the unit is enabled.
    reason_codes: dict[str, dict[str, str]] = field(default_factory=dict)
    # Sockets this unit offers ([provides]) and sockets of other units it plugs into ([extends]).
    extension_points: tuple[str, ...] = ()
    validation_hooks: tuple[str, ...] = ()
    implements: tuple[str, ...] = ()
    validates: tuple[str, ...] = ()
    # Events (a subset of `publishes`) that outgoing webhooks may carry, with the payload fields they expose.
    public_events: dict[str, PublicEvent] = field(default_factory=dict)

    @property
    def migrations_dir(self) -> Path:
        return self.path / "migrations"


def sdk_compatible(spec: str, version: str = SDK_VERSION) -> bool:
    """True if `version` satisfies a spec such as ">=1.0,<2.0"."""
    def parse(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    checks = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
              "<": lambda a, b: a < b, "==": lambda a, b: a == b}
    for clause in filter(None, (c.strip() for c in spec.split(","))):
        m = re.fullmatch(r"(>=|<=|==|>|<)\s*([0-9.]+)", clause)
        if m is None:
            raise ValueError(f"Cannot read SDK requirement '{clause}'")
        a, b = parse(version), parse(m.group(2))
        width = max(len(a), len(b))
        a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
        if not checks[m.group(1)](a, b):
            return False
    return True


def load_manifest(manifest_file: Path, package: str) -> Manifest:
    """Parse one manifest.toml file. Raises ValueError if it is inconsistent."""
    data = tomllib.loads(manifest_file.read_text())
    unit = data["unit"]
    provides = data.get("provides", {})
    permissions = dict(data.get("permissions", {}))
    roles = {name: tuple(perms) for name, perms in data.get("roles", {}).items()}
    for role, perms in roles.items():
        unknown = set(perms) - set(permissions)
        if unknown:
            raise ValueError(f"{manifest_file}: role '{role}' lists undeclared permissions {sorted(unknown)}")
    category = str(unit.get("category", ""))
    if category and category not in CATEGORIES:
        raise ValueError(f"{manifest_file}: category '{category}' is not one of {', '.join(CATEGORIES)}")
    countries = tuple(str(c) for c in unit.get("countries", []))
    if any(not re.fullmatch(r"[A-Z]{2}", c) for c in countries):
        raise ValueError(f"{manifest_file}: countries are two-letter codes such as KE")
    if countries and unit.get("kind", "module") != "plugin":
        raise ValueError(f"{manifest_file}: only plugins declare countries")
    publishes = tuple(provides.get("publishes", []))
    public_events: dict[str, PublicEvent] = {}
    for event_type, spec in provides.get("public_events", {}).items():
        if event_type not in publishes:
            raise ValueError(f"{manifest_file}: public event '{event_type}' is not listed under publishes")
        if not spec.get("description") or not isinstance(spec.get("fields"), list):
            raise ValueError(f"{manifest_file}: public event '{event_type}' needs a description and a list of fields")
        public_events[event_type] = PublicEvent(str(spec["description"]), tuple(str(f) for f in spec["fields"]))
    return Manifest(
        name=unit["name"],
        kind=unit.get("kind", "module"),
        version=unit["version"],
        title=unit.get("title", unit["name"]),
        package=package,
        path=manifest_file.parent,
        sdk=unit.get("sdk", ">=1.0,<2.0"),
        description=unit.get("description", ""),
        category=category,
        countries=countries,
        core=bool(unit.get("core", False)),
        platform_scope=bool(unit.get("platform_scope", False)),
        upgrade_enable_sql=str(data.get("upgrade", {}).get("enable_if_sql", "")).strip(),
        publisher=str(unit.get("publisher", "")),
        homepage=str(unit.get("homepage", "")),
        checksum=str(unit.get("checksum", "")),
        requires=tuple(unit.get("requires", [])),
        optional=tuple(unit.get("optional", [])),
        permissions=permissions,
        publishes=publishes,
        subscribes=tuple(provides.get("subscribes", [])),
        api_prefix=provides.get("api_prefix"),
        settings=tuple(provides.get("settings", [])),
        roles=roles,
        reason_codes={c: dict(codes) for c, codes in data.get("reason_codes", {}).items()},
        extension_points=tuple(provides.get("extension_points", [])),
        validation_hooks=tuple(provides.get("validation_hooks", [])),
        implements=tuple(data.get("extends", {}).get("implements", [])),
        validates=tuple(data.get("extends", {}).get("validates", [])),
        public_events=public_events,
    )

"""Reading unit manifests (manifest.toml in every module and plugin)."""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SDK_VERSION = "1.0"


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
    core: bool = False             # kernel only: always installed and enabled
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
    return Manifest(
        name=unit["name"],
        kind=unit.get("kind", "module"),
        version=unit["version"],
        title=unit.get("title", unit["name"]),
        package=package,
        path=manifest_file.parent,
        sdk=unit.get("sdk", ">=1.0,<2.0"),
        core=bool(unit.get("core", False)),
        requires=tuple(unit.get("requires", [])),
        optional=tuple(unit.get("optional", [])),
        permissions=permissions,
        publishes=tuple(provides.get("publishes", [])),
        subscribes=tuple(provides.get("subscribes", [])),
        api_prefix=provides.get("api_prefix"),
        settings=tuple(provides.get("settings", [])),
        roles=roles,
        reason_codes={c: dict(codes) for c, codes in data.get("reason_codes", {}).items()},
        extension_points=tuple(provides.get("extension_points", [])),
        validation_hooks=tuple(provides.get("validation_hooks", [])),
        implements=tuple(data.get("extends", {}).get("implements", [])),
        validates=tuple(data.get("extends", {}).get("validates", [])),
    )

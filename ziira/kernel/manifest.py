"""Reading unit manifests (manifest.toml in every module and plugin)."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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

    @property
    def migrations_dir(self) -> Path:
        return self.path / "migrations"


def load_manifest(manifest_file: Path, package: str) -> Manifest:
    """Parse one manifest.toml file."""
    data = tomllib.loads(manifest_file.read_text())
    unit = data["unit"]
    provides = data.get("provides", {})
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
        permissions=dict(data.get("permissions", {})),
        publishes=tuple(provides.get("publishes", [])),
        subscribes=tuple(provides.get("subscribes", [])),
        api_prefix=provides.get("api_prefix"),
        settings=tuple(provides.get("settings", [])),
    )

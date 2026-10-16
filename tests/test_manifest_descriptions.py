"""Every unit says in one plain sentence what it is: the Add-ons screen shows it on the card."""

import tomllib
from pathlib import Path

import ziira

MANIFESTS = sorted(Path(ziira.__file__).parent.rglob("manifest.toml"))


def test_every_unit_manifest_has_a_description() -> None:
    assert len(MANIFESTS) > 15
    missing = [str(m.relative_to(Path(ziira.__file__).parent)) for m in MANIFESTS
               if not str(tomllib.loads(m.read_text())["unit"].get("description", "")).strip()]
    assert missing == []

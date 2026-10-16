"""Which third-party plugins may load, and proof that their files are the ones that were reviewed.

Built-in modules and plugins ship with the platform. A plugin from an *extra folder* (`ZIIRA_EXTRA_UNIT_PATHS`) is code
somebody else wrote: it runs inside the platform and sees tenants' data, so in production it loads only when the
operator has allow-listed it (`ZIIRA_ALLOWED_PLUGINS`) and its files still match the checksum that was reviewed.
`docs/plugin-review.md` is the reviewer's checklist.

The checksum (`tree_digest`) is a sha256 over every file of the plugin folder: file names and contents, in sorted
order, skipping caches and the pack file, with the manifest's own `checksum` line left out (so the manifest can carry
the checksum it is part of).
"""

import hashlib
import logging
import re
import sys
import types
from pathlib import Path

from ziira.kernel.config import get_settings
from ziira.kernel.manifest import Manifest

log = logging.getLogger("ziira.plugins")
EXTRA_PACKAGE = "ziira_ext"
PACK_FILE = "ziira-pack.json"
_SKIPPED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}
_CHECKSUM_LINE = re.compile(r"^\s*checksum\s*=.*$\n?", re.MULTILINE)
refused: dict[str, str] = {}  # plugin name -> why it was not loaded (for `ziira plugin list`)


def plugin_files(root: Path) -> list[Path]:
    """The files that make up a plugin, sorted by relative path."""
    found = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and not (set(p.relative_to(root).parts) & _SKIPPED_DIRS)
        and p.suffix != ".pyc"
        and p.name != PACK_FILE
        and p.name != ".DS_Store"
    ]
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def _content(path: Path, root: Path) -> bytes:
    data = path.read_bytes()
    if path.relative_to(root).as_posix() == "manifest.toml":
        data = _CHECKSUM_LINE.sub("", data.decode()).encode()
    return data


def file_digests(root: Path) -> dict[str, str]:
    """sha256 of each file, by relative path (the manifest without its checksum line)."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(_content(p, root)).hexdigest() for p in plugin_files(root)}


def tree_digest(root: Path) -> str:
    """One sha256 over all the plugin's files (names and contents)."""
    h = hashlib.sha256()
    for name, digest in file_digests(root).items():
        h.update(f"{name}\0{digest}\n".encode())
    return h.hexdigest()


def extra_package(roots: list[str]) -> None:
    """Make `ziira_ext.<folder>` importable for the plugins in the extra folders."""
    module = sys.modules.get(EXTRA_PACKAGE)
    if module is None:
        module = types.ModuleType(EXTRA_PACKAGE)
        module.__package__ = EXTRA_PACKAGE
        sys.modules[EXTRA_PACKAGE] = module
    module.__path__ = [str(Path(r).resolve()) for r in roots]


def vet(m: Manifest) -> str | None:
    """None if this plugin from an extra folder may load; otherwise the reason it may not."""
    settings = get_settings()
    actual = tree_digest(m.path)
    if m.checksum and m.checksum != actual:
        return f"its files do not match the checksum in its manifest ({actual[:12]}... found); changed after packing?"
    if settings.env != "production":
        return None
    allowed = settings.allowed_plugin_map()
    if m.name not in allowed:
        return "it is not on ZIIRA_ALLOWED_PLUGINS (production loads only reviewed plugins)"
    pinned = allowed[m.name] or m.checksum
    if not pinned:
        return "production needs a checksum: list it as name=SHA256 in ZIIRA_ALLOWED_PLUGINS or pack it with a checksum"
    if pinned != actual:
        return f"its files do not match the reviewed checksum (actual {actual})"
    return None

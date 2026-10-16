"""The install manifest: every system file the installer created, modified or removed, so uninstall can undo exactly that."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

MANIFEST_PATH = "/var/lib/ziira/install-manifest.json"
BACKUP_ROOT = "/var/lib/ziira/backups"


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class Manifest:
    entries: list[dict[str, str]] = field(default_factory=list)       # path, kind (file|dir|link), action, backup, checksum
    extra: dict[str, list[str]] = field(default_factory=dict)         # lineages, units, packages installed ...

    def known(self, path: str) -> dict[str, str] | None:
        for e in self.entries:
            if e["path"] == path:
                return e
        return None

    def add(self, path: str, kind: str, action: str, backup: str = "", digest: str = "") -> None:
        if self.known(path) is None:
            self.entries.append({"path": path, "kind": kind, "action": action, "backup": backup, "checksum": digest})

    def note(self, key: str, value: str) -> None:
        bucket = self.extra.setdefault(key, [])
        if value not in bucket:
            bucket.append(value)

    def dumps(self) -> str:
        return json.dumps({"version": 1, "entries": self.entries, "extra": self.extra}, indent=1) + "\n"

    @classmethod
    def loads(cls, text: str | None) -> Manifest:
        if not text:
            return cls()
        data = json.loads(text)
        return cls(entries=list(data.get("entries", [])), extra={k: list(v) for k, v in data.get("extra", {}).items()})

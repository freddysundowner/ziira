"""Files in a backup: a tar of the stored bytes a database dump refers to, and a way to read it back.

`ziira backup` writes `<target>-<time>.files.tar` beside the database dump. It holds exactly the files the dump's rows
name (read in the same database snapshot), under their store keys. `ArchiveStore` reads such a tar as a read-only store,
so the restore test can check the restored rows against it; `extract` unpacks it into a new folder for a real restore.
"""

import hashlib
import io
import tarfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from ziira.kernel.files.store import KEY, FileStore


class ArchiveStore(FileStore):
    """A tar of files as a read-only store."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._members: dict[str, tarfile.TarInfo] = {}
        if path is not None and path.exists():
            with tarfile.open(path) as tar:
                self._members = {m.name: m for m in tar.getmembers() if m.isfile()}

    def put(self, key: str, data: bytes) -> None:
        raise PermissionError("a backup archive is read only")

    def get(self, key: str) -> bytes:
        member = self._members.get(key)
        if member is None or self.path is None:
            raise FileNotFoundError(key)
        with tarfile.open(self.path) as tar:
            handle = tar.extractfile(member)
            if handle is None:
                raise FileNotFoundError(key)
            return handle.read()

    def delete(self, key: str) -> bool:
        raise PermissionError("a backup archive is read only")

    def size(self, key: str) -> int | None:
        member = self._members.get(key)
        return member.size if member else None

    def modified(self, key: str) -> float | None:
        member = self._members.get(key)
        return float(member.mtime) if member else None

    def keys(self, prefix: str) -> Iterator[str]:
        yield from sorted(k for k in self._members if k.startswith(prefix))


def write_archive(store: FileStore, keys: Iterable[str], path: Path) -> dict[str, Any]:
    """Write the named files from the store into a tar. Keys the store no longer has (a file removed while the backup
    ran) are left out and listed. Returns what a manifest records: file count, bytes, checksum, missing keys."""
    missing: list[str] = []
    count = total = 0
    partial = path.with_suffix(path.suffix + ".partial")
    try:
        with tarfile.open(partial, "w") as tar:
            for key in sorted(set(keys)):
                try:
                    data = store.get(key)
                except FileNotFoundError:
                    missing.append(key)
                    continue
                info = tarfile.TarInfo(key)
                info.size, info.mode = len(data), 0o600
                tar.addfile(info, io.BytesIO(data))
                count += 1
                total += len(data)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {"archive": path.name, "count": count, "bytes": total, "sha256": digest.hexdigest(), "missing": missing}


def extract(path: Path, into: Path) -> int:
    """Unpack an archive into a folder that does not exist yet, refusing any name that is not a store key. Returns the
    number of files."""
    if into.exists() and any(into.iterdir()):
        raise FileExistsError(f"{into} is not empty; a restore never writes over existing files")
    done = 0
    with tarfile.open(path) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not KEY.match(member.name):
                raise ValueError(f"'{member.name}' is not a stored file name; the archive is not trusted")
            target = into / member.name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            handle = tar.extractfile(member)
            assert handle is not None
            target.write_bytes(handle.read())
            target.chmod(0o600)
            done += 1
    return done

"""Where the bytes of files live: a small interface, and a directory on the server as the default.

Rows in `kernel.attachment` say what a file is and who may see it; the store only keeps bytes under opaque keys the
service builds from ids (`<tenant id>/<first two characters of the file id>/<file id>.<variant>`). Nothing here is
ever served from a public path: every download goes through the service (docs/files.md). Object storage can replace
the directory by implementing `FileStore` and returning it from `get_store`.
"""

import os
import re
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from ziira.kernel.config import get_settings
from ziira.kernel.errors import Unavailable

KEY = re.compile(r"^[0-9a-f-]{36}/[0-9a-f]{2}/[0-9a-f-]{36}\.[a-z]{3,8}$")


class FileStore(ABC):
    """Contract of the byte storage."""

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        """Store the bytes under the key (atomically: a reader never sees half a file)."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """The bytes, or FileNotFoundError."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove the bytes; True if there were any."""

    @abstractmethod
    def size(self, key: str) -> int | None:
        """The size in bytes, or None when the key does not exist."""

    @abstractmethod
    def modified(self, key: str) -> float | None:
        """When the bytes were last written (seconds since 1970), or None when the key does not exist."""

    @abstractmethod
    def keys(self, prefix: str) -> Iterator[str]:
        """Every key under a prefix (a tenant's folder)."""

    def problems(self) -> list[str]:
        """Why this store cannot be used right now (empty when it can). Used by readiness checks."""
        return []


class LocalFileStore(FileStore):
    """Files in a directory: private (owner only), written atomically, keys cannot leave the directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def _path(self, key: str) -> Path:
        if not KEY.match(key):
            raise ValueError("not a file key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("not a file key")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> bool:
        try:
            self._path(key).unlink()
            return True
        except FileNotFoundError:
            return False

    def size(self, key: str) -> int | None:
        try:
            return self._path(key).stat().st_size
        except FileNotFoundError:
            return None

    def modified(self, key: str) -> float | None:
        try:
            return self._path(key).stat().st_mtime
        except FileNotFoundError:
            return None

    def keys(self, prefix: str) -> Iterator[str]:
        base = (self.root / prefix).resolve()
        if base != self.root and self.root not in base.parents:
            return
        for found in sorted(base.rglob("*")):
            if found.is_file() and not found.name.startswith(".part-"):
                yield found.relative_to(self.root).as_posix()

    def problems(self) -> list[str]:
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            probe = self.root / ".write-test"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as error:
            return [f"The files folder {self.root} cannot be written: {error.strerror or error}"]
        return []


def configured_directory() -> Path:
    """The folder files are kept in: ZIIRA_FILES_DIR, or `var/files` next to where the server runs in development."""
    settings = get_settings()
    if settings.files_dir.strip():
        return Path(settings.files_dir.strip()).expanduser()
    if settings.env == "production":
        raise Unavailable("File storage is not set up on this server: set ZIIRA_FILES_DIR (docs/files.md)")
    return Path("var/files")


@lru_cache
def _local(directory: str) -> LocalFileStore:
    return LocalFileStore(directory)


def get_store() -> FileStore:
    """The store in use. One place to change when object storage replaces the directory."""
    return _local(str(configured_directory().resolve()))


def forget_store() -> None:
    """For tests: drop the cached store so a changed ZIIRA_FILES_DIR is read again."""
    _local.cache_clear()

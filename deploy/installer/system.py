"""Everything the installer does to the machine goes through a `System`: commands, files, DNS.

`System` really does it. With `dry_run=True` read-only probes still run (so the plan reflects the machine) but
anything that would change something is printed instead. Tests use `FakeSystem` (tests/fakes.py): an in-memory
file system and scripted command answers, so every step can be tested without a server.
"""
from __future__ import annotations

import os
import pwd
import shutil
import socket
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Result:
    code: int = 0
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


class CommandFailed(Exception):
    def __init__(self, argv: Sequence[str], result: Result, secret: bool = False) -> None:
        shown = "[hidden command]" if secret else " ".join(argv)
        tail = "" if secret else (result.err.strip() or result.out.strip())[-600:]
        super().__init__(f"command failed ({result.code}): {shown}\n{tail}".rstrip())
        self.result = result


class System:
    def __init__(self, *, dry_run: bool = False, say: Callable[[str], None] | None = None) -> None:
        self.dry_run = dry_run
        self.say = say or (lambda s: None)          # prints "would ..." lines in dry-run mode
        self.fake = False

    # ---------------------------------------------------------------- commands
    def run(self, argv: Sequence[str], *, probe: bool = False, check: bool = True, input: str | None = None,
            user: str | None = None, env: Mapping[str, str] | None = None, secret: bool = False,
            cwd: str | None = None, timeout: int | None = 900, desc: str = "") -> Result:
        """Run a command. `probe=True`: changes nothing, so it runs even in dry-run mode.
        `user`: run as that user (runuser). `secret`: do not echo the command or its output (it holds a secret)."""
        full = ["runuser", "-u", user, "--", *argv] if user else list(argv)
        if self.dry_run and not probe:
            self.say(desc or ("run: " + ("[hidden command]" if secret else " ".join(argv))) + (f"  (as {user})" if user else ""))
            return Result()
        result = self._exec(full, input, env, cwd, timeout)
        if check and not result.ok:
            raise CommandFailed(argv, result, secret)
        return result

    def _exec(self, argv: list[str], input: str | None, env: Mapping[str, str] | None, cwd: str | None,
              timeout: int | None) -> Result:
        full_env = {**os.environ, **env} if env else None
        try:
            p = subprocess.run(argv, input=input, capture_output=True, text=True, env=full_env, cwd=cwd,
                               timeout=timeout, check=False)
        except FileNotFoundError:
            return Result(127, "", f"{argv[0]}: command not found")
        except subprocess.TimeoutExpired:
            return Result(124, "", f"timed out after {timeout}s")
        return Result(p.returncode, p.stdout, p.stderr)

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    # ---------------------------------------------------------------- facts about the machine
    def is_root(self) -> bool:
        return os.geteuid() == 0

    def cpu_count(self) -> int:
        return os.cpu_count() or 1

    def ram_mb(self) -> int:
        for line in (self.read_text("/proc/meminfo") or "").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
        return 0

    def disk_free_mb(self, path: str) -> int:
        probe = path
        while not os.path.exists(probe) and probe != "/":
            probe = os.path.dirname(probe)
        return shutil.disk_usage(probe).free // (1024 * 1024)

    def resolve(self, host: str) -> tuple[list[str], list[str]]:
        """(IPv4 addresses, IPv6 addresses) of a name; empty lists when it does not resolve."""
        v4: list[str] = []
        v6: list[str] = []
        for family, bucket in ((socket.AF_INET, v4), (socket.AF_INET6, v6)):
            try:
                for info in socket.getaddrinfo(host, None, family, socket.SOCK_STREAM):
                    address = str(info[4][0])
                    if address not in bucket:
                        bucket.append(address)
            except (socket.gaierror, OSError):
                pass
        return v4, v6

    def user_exists(self, name: str) -> bool:
        try:
            pwd.getpwnam(name)
            return True
        except KeyError:
            return False

    # ---------------------------------------------------------------- files
    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(path)

    def read_text(self, path: str) -> str | None:
        try:
            return Path(path).read_text()
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return None

    def listdir(self, path: str) -> list[str]:
        try:
            return sorted(os.listdir(path))
        except (FileNotFoundError, NotADirectoryError):
            return []

    def readlink(self, path: str) -> str | None:
        try:
            return os.readlink(path)
        except OSError:
            return None

    def mtime(self, path: str) -> float | None:
        try:
            return os.stat(path).st_mtime
        except OSError:
            return None

    def makedirs(self, path: str, *, mode: int = 0o755, owner: str | None = None, group: str | None = None) -> bool:
        """Create a directory (and set owner/mode). Returns True if anything changed."""
        changed = not os.path.isdir(path)
        if self.dry_run:
            if changed:
                self.say(f"create directory {path}")
            return changed
        os.makedirs(path, exist_ok=True)
        if self._chmod_chown(path, mode, owner, group):
            changed = True
        return changed

    def write_text(self, path: str, content: str, *, mode: int = 0o644, owner: str | None = None,
                   group: str | None = None, secret: bool = False) -> bool:
        """Write a file atomically if its content (or mode/owner) differs. Returns True if it changed."""
        current = self.read_text(path)
        same = current == content
        if self.dry_run:
            if not same:
                self.say(f"write {path} ({len(content)} bytes{', secret' if secret else ''})")
            return not same
        changed = not same
        if not same:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = f"{path}.ziira-new"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.replace(tmp, path)
        if self._chmod_chown(path, mode, owner, group):
            changed = True
        return changed

    def _chmod_chown(self, path: str, mode: int, owner: str | None, group: str | None) -> bool:
        changed = False
        st = os.stat(path)
        if (st.st_mode & 0o7777) != mode:
            os.chmod(path, mode)
            changed = True
        if (owner or group) and self.is_root():
            import grp
            uid = pwd.getpwnam(owner).pw_uid if owner else -1
            gid = grp.getgrnam(group).gr_gid if group else -1
            if (uid != -1 and st.st_uid != uid) or (gid != -1 and st.st_gid != gid):
                os.chown(path, uid, gid)
                changed = True
        return changed

    def symlink(self, link: str, target: str) -> bool:
        """Point `link` at `target` atomically. Returns True if it changed."""
        if self.readlink(link) == target:
            return False
        if self.dry_run:
            self.say(f"point {link} -> {target}")
            return True
        tmp = f"{link}.ziira-new"
        if os.path.lexists(tmp):
            os.remove(tmp)
        os.symlink(target, tmp)
        os.replace(tmp, link)
        return True

    def remove(self, path: str) -> None:
        if self.dry_run:
            self.say(f"remove {path}")
        elif os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)

    def copy_tree(self, src: str, dst: str, *, exclude: Sequence[str] = ()) -> None:
        """Copy a directory tree (symlinks kept), skipping names in `exclude` at any depth."""
        if self.dry_run:
            self.say(f"copy {src} -> {dst}")
            return
        shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns(*exclude), dirs_exist_ok=False)

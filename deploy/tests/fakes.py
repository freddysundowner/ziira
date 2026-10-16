"""A fake machine for the installer tests: in-memory files, scripted command answers, a record of everything done."""
from __future__ import annotations

import posixpath
from collections.abc import Callable, Mapping, Sequence

from installer.system import Result, System

Matcher = str | Callable[[list[str], str | None], bool]


class FakeSystem(System):
    def __init__(self, *, dry_run: bool = False) -> None:
        super().__init__(dry_run=dry_run)
        self.fake = True
        self.files: dict[str, str] = {}
        self.links: dict[str, str] = {}
        self.dirs: set[str] = {"/", "/etc", "/var", "/opt", "/usr", "/tmp"}
        self.modes: dict[str, int] = {}
        self.owners: dict[str, tuple[str | None, str | None]] = {}
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []
        self.rules: list[tuple[Matcher, Result]] = []
        self.root = True
        self.cpus = 4
        self.ram = 8192
        self.disk_mb = 50_000
        self.dns: dict[str, tuple[list[str], list[str]]] = {}
        self.users: set[str] = set()
        self.programs: set[str] = {"python3", "curl", "git", "ss", "dpkg-query", "apt-get", "systemctl", "openssl"}
        self.said: list[str] = []
        self.say = self.said.append
        self.mutations: list[str] = []

    def _store_backup(self, path: str, backup: str) -> None:
        self.files[backup] = self.files.get(path, "")

    def _raw_write(self, path: str, content: str) -> None:
        self._note_dirs(posixpath.dirname(path))
        self.files[path] = content
        self.dirs.add(posixpath.dirname(path))

    def save_manifest(self) -> None:
        if not self.dry_run and (self.manifest.entries or self.manifest.extra):
            self._raw_write("/var/lib/ziira/install-manifest.json", self.manifest.dumps())

    def raw_remove(self, path: str) -> None:
        if not self.dry_run:
            self.files.pop(path, None)

    # ---------------------------------------------------------------- scripting
    def on(self, match: Matcher, out: str = "", code: int = 0, err: str = "") -> FakeSystem:
        """The newest rule whose text occurs in the joined command (or whose function says yes) answers."""
        self.rules.insert(0, (match, Result(code, out, err)))
        return self

    def ran(self, text: str) -> bool:
        return any(text in " ".join(c) for c in self.calls)

    def count(self, text: str) -> int:
        return sum(text in " ".join(c) for c in self.calls)

    def _exec(self, argv: list[str], input: str | None, env: Mapping[str, str] | None, cwd: str | None,
              timeout: int | None) -> Result:
        self.calls.append(list(argv))
        self.inputs.append(input)
        joined = " ".join(argv)
        self._builtin(argv)
        for match, result in self.rules:
            if callable(match):
                if match(argv, input):
                    return result
            elif match in joined or (input and match in input):
                return result
        return Result(0, "", "")

    def _builtin(self, argv: list[str]) -> None:
        """The few file commands the installer uses, applied to the in-memory files."""
        if argv[0] == "mv" and len(argv) == 3:
            src, dst = argv[1], argv[2]
            for p in [p for p in list(self.files) if p == src or p.startswith(src + "/")]:
                self.files[dst + p[len(src):]] = self.files.pop(p)
            self.dirs.discard(src)
            self.dirs.add(dst)
        elif argv[0] == "rm":
            for target in [a for a in argv[1:] if not a.startswith("-")]:
                for p in [p for p in list(self.files) if p == target or p.startswith(target + "/")]:
                    self.files.pop(p, None)
                self.dirs.discard(target)
        elif argv[0] == "rsync" and argv[-2].endswith("/") and argv[-1].endswith("/"):
            src, dst = argv[-2], argv[-1]
            for p in [p for p in list(self.files) if p.startswith(src)]:
                self.files[dst + p[len(src):]] = self.files[p]
            self.dirs.add(dst.rstrip("/"))

    def run(self, argv: Sequence[str], *, probe: bool = False, check: bool = True, input: str | None = None,
            user: str | None = None, env: Mapping[str, str] | None = None, secret: bool = False,
            cwd: str | None = None, timeout: int | None = 900, desc: str = "") -> Result:
        if not probe and not self.dry_run:
            self.mutations.append(" ".join(argv))
        return super().run(argv, probe=probe, check=check, input=input, user=user, env=env, secret=secret, cwd=cwd,
                           timeout=timeout, desc=desc)

    # ---------------------------------------------------------------- machine facts
    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.programs else None

    def is_root(self) -> bool:
        return self.root

    def cpu_count(self) -> int:
        return self.cpus

    def ram_mb(self) -> int:
        return self.ram

    def disk_free_mb(self, path: str) -> int:
        return self.disk_mb

    def resolve(self, host: str) -> tuple[list[str], list[str]]:
        return self.dns.get(host, ([], []))

    def user_exists(self, name: str) -> bool:
        return name in self.users

    # ---------------------------------------------------------------- files
    def exists(self, path: str) -> bool:
        return path in self.files or path in self.links or path in self.dirs

    def is_dir(self, path: str) -> bool:
        return path in self.dirs

    def read_text(self, path: str) -> str | None:
        if path in self.links:
            return self.files.get(self.links[path])
        return self.files.get(path)

    def listdir(self, path: str) -> list[str]:
        path = path.rstrip("/")
        names = set()
        for p in list(self.files) + list(self.links) + list(self.dirs):
            if p.startswith(path + "/"):
                names.add(p[len(path) + 1:].split("/")[0])
        return sorted(names)

    def readlink(self, path: str) -> str | None:
        return self.links.get(path)

    def mtime(self, path: str) -> float | None:
        return 0.0 if path in self.files else None

    def makedirs(self, path: str, *, mode: int = 0o755, owner: str | None = None, group: str | None = None) -> bool:
        changed = path not in self.dirs
        if self.dry_run:
            if changed:
                self.say(f"create directory {path}")
            return changed
        self._note_dirs(path)
        parts = path.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            self.dirs.add("/" + "/".join(parts[:i]))
        self.modes[path] = mode
        self.owners[path] = (owner, group)
        return changed

    def write_text(self, path: str, content: str, *, mode: int = 0o644, owner: str | None = None,
                   group: str | None = None, secret: bool = False) -> bool:
        changed = self.read_text(path) != content or self.modes.get(path, mode) != mode
        if self.dry_run:
            if changed:
                self.say(f"write {path}")
            return changed
        if changed:
            self.mutations.append(f"write {path}")
            self._before_change(path)
        self.files[path] = content
        self.modes[path] = mode
        self.owners[path] = (owner, group)
        self.dirs.add(posixpath.dirname(path))
        return changed

    def symlink(self, link: str, target: str) -> bool:
        if self.links.get(link) == target:
            return False
        if self.dry_run:
            self.say(f"point {link} -> {target}")
            return True
        self.mutations.append(f"link {link}")
        self._before_change(link, "link")
        self.links[link] = target
        return True

    def remove(self, path: str) -> None:
        if self.dry_run:
            self.say(f"remove {path}")
            return
        self.mutations.append(f"remove {path}")
        if self.exists(path) and not self.manifest.known(path) and path not in self.dirs:
            self._before_change(path)
            self.manifest.entries[-1]["action"] = "removed"
        self.files.pop(path, None)
        self.links.pop(path, None)
        for p in [p for p in list(self.files) + list(self.links) if p.startswith(path.rstrip("/") + "/")]:
            self.files.pop(p, None)
            self.links.pop(p, None)
        for d in [d for d in self.dirs if d == path or d.startswith(path.rstrip("/") + "/")]:
            self.dirs.discard(d)

    def copy_tree(self, src: str, dst: str, *, exclude: Sequence[str] = ()) -> None:
        if self.dry_run:
            self.say(f"copy {src} -> {dst}")
            return
        self.mutations.append(f"copy {src} {dst}")
        self._note_dirs(dst)
        for p in [p for p in list(self.files) if p.startswith(src.rstrip("/") + "/")]:
            self.files[dst + p[len(src):]] = self.files[p]
        self.dirs.add(dst)

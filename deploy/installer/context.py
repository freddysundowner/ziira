"""Shared state of one installer run, and helpers every step uses."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from installer import envfile, util
from installer.config import Config
from installer.system import System
from installer.ui import UI, StepFailed

SUPPORTED_OS = {("ubuntu", "20.04"), ("ubuntu", "22.04"), ("ubuntu", "24.04"), ("debian", "12")}
END_OF_LIFE = {("ubuntu", "20.04")}
VOLATILE = {"pg_action", "disk_free_mb", "ram_available_mb", "pgdg_done"}          # volatile facts: not saved
PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass
class Secrets:
    secret_key: str
    credentials_key: str
    metrics_token: str
    db_password: str
    hook_secret: str
    hook_token: str
    fresh_credentials_key: bool = False       # generated in this run: the summary must say "back it up"


@dataclass
class Ctx:
    cfg: Config
    sys: System
    ui: UI
    facts: dict[str, Any] = field(default_factory=dict)
    _secrets: Secrets | None = None
    started: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"))

    # ---------------------------------------------------------------- paths
    @property
    def env_path(self) -> str:
        return f"{self.cfg.env_dir}/ziira.env"

    @property
    def rebuild_env_path(self) -> str:
        return f"{self.cfg.env_dir}/site-rebuild.env"

    @property
    def summary_path(self) -> str:
        return f"{self.cfg.env_dir}/install-summary.txt"

    @property
    def state_path(self) -> str:
        return f"{self.cfg.env_dir}/install.json"

    def venv_bin(self, name: str) -> str:
        return f"{self.cfg.current}/venv/bin/{name}"

    @property
    def rebuild_enabled(self) -> bool:
        return not self.cfg.prebuilt

    @property
    def real_services(self) -> bool:
        return not self.cfg.no_services

    # ---------------------------------------------------------------- environment file
    def existing_state(self) -> dict[str, object]:
        """The saved install state (install.json) of an earlier run, or {}."""
        import json
        try:
            return dict(json.loads(self.sys.read_text(self.state_path) or "{}"))
        except ValueError:
            return {}

    def existing_env(self) -> dict[str, str]:
        return envfile.parse(self.sys.read_text(self.env_path) or "")

    def app_env(self) -> dict[str, str]:
        """The environment for running the `ziira` command as the service user."""
        env = {**self.existing_env(), "PATH": PATH, "HOME": self.cfg.state_dir, "LANG": "C.UTF-8"}
        return env

    # ---------------------------------------------------------------- secrets
    def secrets(self) -> Secrets:
        """Secrets of this installation: read from the env file when it exists, otherwise generated (once per run)."""
        if self._secrets is not None:
            return self._secrets
        env = self.existing_env()
        from urllib.parse import unquote, urlparse
        db_password = ""
        if env.get("ZIIRA_MASTER_DATABASE_URL"):
            db_password = unquote(urlparse(env["ZIIRA_MASTER_DATABASE_URL"]).password or "")
        hook_url = env.get("ZIIRA_SITE_BUILD_HOOK_URL", "")
        rebuild = envfile.parse(self.sys.read_text(self.rebuild_env_path) or "")
        s = Secrets(
            secret_key=env.get("ZIIRA_SECRET_KEY") or util.new_secret(),
            credentials_key=env.get("ZIIRA_CREDENTIALS_KEY") or util.new_secret(),
            metrics_token=env.get("ZIIRA_METRICS_TOKEN") or util.new_secret(24),
            db_password=db_password or util.new_password(),
            hook_secret=env.get("ZIIRA_SITE_BUILD_HOOK_SECRET") or rebuild.get("ZIIRA_REBUILD_SECRET") or util.new_secret(),
            hook_token=(hook_url.rstrip("/").rsplit("/", 1)[-1] if "/_hooks/site-rebuild/" in hook_url else "")
            or rebuild.get("ZIIRA_REBUILD_TOKEN") or util.new_secret(18),
            fresh_credentials_key=not env.get("ZIIRA_CREDENTIALS_KEY"))
        self._secrets = s
        return s

    def db_urls(self) -> tuple[str, str]:
        port = int(self.facts.get("pg_port", 5432))
        s = self.secrets()
        return (util.database_url(self.cfg.db_role, s.db_password, "127.0.0.1", port, self.cfg.master_db),
                util.database_url(self.cfg.db_role, s.db_password, "127.0.0.1", port, "postgres"))

    # ---------------------------------------------------------------- helpers
    def need_root(self) -> None:
        if not self.sys.is_root() and not self.cfg.dry_run:
            raise StepFailed("this installer must run as root", hint="Run it with:  sudo bash deploy/install.sh")

    def apt_missing(self, packages: list[str]) -> list[str]:
        """The packages from the list that are not installed."""
        missing: list[str] = []
        for pkg in packages:
            r = self.sys.run(["dpkg-query", "-W", "-f=${Status}", pkg], probe=True, check=False)
            if not (r.ok and "install ok installed" in r.out):
                missing.append(pkg)
        return missing

    def apt_install(self, packages: list[str]) -> None:
        self.sys.run(["apt-get", "install", "-y", "--no-install-recommends", *packages],
                     env={"DEBIAN_FRONTEND": "noninteractive", "NEEDRESTART_MODE": "a"}, timeout=1800)

    def units_to_enable(self, units: list[str]) -> list[str]:
        """The units that are not both enabled and active yet (so a re-run does not touch what already works)."""
        todo = []
        for unit in units:
            enabled = self.sys.run(["systemctl", "is-enabled", unit], probe=True, check=False).out.strip() == "enabled"
            active = self.sys.run(["systemctl", "is-active", unit], probe=True, check=False).out.strip() == "active"
            if not (enabled and active):
                todo.append(unit)
        return todo

    def write_state(self) -> None:
        data = {"installer_version": "1.0.0", "config": self.cfg.public_dict(),
                "facts": {k: v for k, v in self.facts.items()
                                                                if isinstance(v, (str, int, float, bool)) and k not in VOLATILE}}
        self.sys.write_text(self.state_path, json.dumps(data, indent=2, sort_keys=True) + "\n", mode=0o640,
                            owner="root", group=self.cfg.service_user)

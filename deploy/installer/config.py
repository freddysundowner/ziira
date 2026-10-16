"""The installer's inputs: one dataclass, filled from flags, an answers file, environment variables and prompts."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field, fields

from installer import util


@dataclass
class Config:
    # --- names
    root_domain: str = ""
    app_host: str = ""                  # default app.<root>
    admin_host: str = ""                # default admin.<root>
    www: bool = True                    # also serve www.<root> as a redirect to <root>
    email: str = ""                     # Let's Encrypt contact
    # --- where things live
    install_dir: str = "/opt/ziira"
    service_user: str = "ziira"
    web_root: str = "/var/www/ziira"
    backup_dir: str = "/var/backups/ziira"
    env_dir: str = "/etc/ziira"
    # --- PostgreSQL
    postgres_new_cluster: bool = False  # allow a second PostgreSQL 16 cluster when only an older one exists
    db_prefix: str = "ziira_"           # every database and role we create starts with this
    pg_port: int = 0                    # which PostgreSQL when several run (0 = the only one, or ask)
    # --- first super admin (the password comes from ZIIRA_OPERATOR_PASSWORD or a prompt, never a flag)
    admin_name: str = "Platform admin"
    admin_email: str = ""
    # --- platform mailer (all optional; the password comes from ZIIRA_INSTALL_SMTP_PASSWORD or a prompt)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "Ziira"
    # --- application defaults
    default_plan: str = ""
    registration_mode: str = ""         # advanced; "" = closed (the Super Admin opens it after Email is configured)
    operator_mfa: str = "off"           # off | totp
    operator_networks: str = ""         # comma separated CIDRs ("" = no limit)
    # --- where the code comes from
    repo: str = ""
    branch: str = "main"
    from_dir: str = ""
    tarball: str = ""
    prebuilt: bool = False
    site_strict: bool = False
    # --- TLS
    cert_mode: str = "per-host"         # per-host | single
    staging: bool = False
    self_signed: bool = False
    agree_tos: bool = False
    hsts: str = "on"                    # off | on | include-subdomains
    csp: str = "report-only"            # report-only | enforce | off
    # --- machine
    skip_dns_check: bool = False
    public_ip: str = ""
    no_services: bool = False           # config-only: write and validate files, touch no service
    manage_firewall: bool = False       # allowed to ENABLE ufw (never done by default)
    fail2ban: bool = False              # install/enable fail2ban with a ziira-only jail (never done by default)
    inspect: bool = False               # only print the inventory and the plan
    proxy_mode: str = ""                # "snippet": another proxy owns 80/443: run behind it and write config for it
    ports: int = 0                      # run our own nginx on 127.0.0.1:<port> (plain HTTP) behind another proxy
    snippet_dir: str = ""               # where proxy snippets go (default <install_dir>/proxy-snippets)
    allow_unsupported_os: bool = False
    api_port: int = 8000
    rebuild_port: int = 9001
    workers: int = 0                    # 0 = from CPU count and RAM
    # --- behaviour
    dry_run: bool = False
    yes: bool = False
    only: list[str] = field(default_factory=list)
    skip: list[str] = field(default_factory=list)
    # --- secrets (from the environment or prompts; never written to the answers file or the install state)
    admin_password: str = field(default="", repr=False)
    smtp_password: str = field(default="", repr=False)

    # ---------------------------------------------------------------- derived
    @property
    def db_role(self) -> str:
        return self.db_prefix.rstrip("_") or "ziira"

    @property
    def master_db(self) -> str:
        return f"{self.db_prefix}master"

    @property
    def template_db(self) -> str:
        return f"{self.db_prefix}template"

    @property
    def tenant_db_prefix(self) -> str:
        return f"{self.db_prefix}t_"

    @property
    def tenant_role_prefix(self) -> str:
        return "zt_" if self.db_prefix == "ziira_" else f"{self.db_prefix}r_"

    @property
    def behind(self) -> bool:
        """Run our own nginx on a local port behind another proxy instead of joining/owning ports 80/443."""
        return self.ports > 0 or self.proxy_mode == "snippet"

    def resolve_defaults(self) -> None:
        self.root_domain = self.root_domain.strip().lower().rstrip(".")
        if self.root_domain:
            self.app_host = (self.app_host or f"app.{self.root_domain}").strip().lower()
            self.admin_host = (self.admin_host or f"admin.{self.root_domain}").strip().lower()
        if not self.registration_mode:
            self.registration_mode = "closed"        # the Super Admin opens registration once its email is set up
        if self.db_prefix and not self.db_prefix.endswith("_"):
            self.db_prefix += "_"
        if self.proxy_mode == "snippet" and not self.ports:
            self.ports = 8081
        if self.behind:
            self.hsts = "off"
        if self.staging or self.self_signed:
            self.hsts = "off"               # a browser must never pin a certificate nobody trusts

    @property
    def www_host(self) -> str:
        return f"www.{self.root_domain}"

    def hosts(self) -> list[str]:
        """Every name that needs a certificate and DNS."""
        names = [self.root_domain]
        if self.www:
            names.append(self.www_host)
        return [*names, self.app_host, self.admin_host]

    def lineages(self) -> dict[str, list[str]]:
        """Certificate name -> host names on it. per-host: the site (with www), app and admin each get their own."""
        if self.cert_mode == "single":
            return {f"ziira-{self.root_domain}": self.hosts()}
        site = [self.root_domain] + ([self.www_host] if self.www else [])
        return {f"ziira-{self.root_domain}": site, f"ziira-{self.app_host}": [self.app_host],
                f"ziira-{self.admin_host}": [self.admin_host]}

    def lineage_of(self, host: str) -> str:
        for name, hosts in self.lineages().items():
            if host in hosts:
                return name
        raise KeyError(host)

    @property
    def release_dir(self) -> str:
        return f"{self.install_dir}/releases"

    @property
    def current(self) -> str:
        return f"{self.install_dir}/current"

    @property
    def state_dir(self) -> str:
        return "/var/lib/ziira"

    def public_dict(self) -> dict[str, object]:
        """Everything that is not secret (written to /etc/ziira/install.json for update.sh and the doctor)."""
        skip = {"admin_password", "smtp_password", "dry_run", "yes", "only", "skip"}
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in skip}

    # ---------------------------------------------------------------- validation
    def validate(self) -> list[str]:
        problems: list[str] = []
        if not util.valid_hostname(self.root_domain):
            problems.append(f"root domain '{self.root_domain}' is not a valid domain name (example: ziira.io)")
        for label, host in (("app host", self.app_host), ("admin host", self.admin_host)):
            if not util.valid_hostname(host):
                problems.append(f"{label} '{host}' is not a valid domain name")
        if len({self.root_domain, self.app_host, self.admin_host}) < 3:
            problems.append("the root domain, app host and admin host must be three different names")
        if self.www and self.www_host in (self.app_host, self.admin_host):
            problems.append("www would collide with the app or admin host; use --no-www")
        if not self.self_signed and not util.valid_email(self.email):
            problems.append("a contact email for Let's Encrypt is required (--email)")
        if not util.valid_email(self.admin_email):
            problems.append("the first super admin needs an email (--admin-email)")
        if not self.admin_name.strip() or "'" in self.admin_name:
            problems.append("the first super admin needs a name (no quotes)")
        for label, value in (("install directory", self.install_dir), ("web root", self.web_root),
                             ("backup directory", self.backup_dir), ("env directory", self.env_dir)):
            if not value.startswith("/") or value.rstrip("/") == "" or ".." in value.split("/"):
                problems.append(f"{label} must be an absolute path without '..'")
        if not util.valid_ident(self.service_user.replace("-", "_")):
            problems.append("service user must be a simple lower-case name")
        if not util.valid_ident(self.db_prefix.rstrip("_") or "x") or len(self.db_prefix) > 20:
            problems.append("--db-prefix must be lower-case letters, digits and underscores (at most 20), e.g. ziira_")
        if self.proxy_mode not in ("", "snippet"):
            problems.append("--proxy-mode must be snippet")
        if self.ports and not 1024 <= self.ports <= 65000:
            problems.append("--ports must be a local port between 1024 and 65000")
        if self.cert_mode not in ("per-host", "single"):
            problems.append("--cert-mode must be per-host or single")
        if self.hsts not in ("off", "on", "include-subdomains"):
            problems.append("--hsts must be off, on or include-subdomains")
        if self.csp not in ("report-only", "enforce", "off"):
            problems.append("--csp must be report-only, enforce or off")
        if self.operator_mfa not in ("off", "totp"):
            problems.append("--operator-mfa must be off or totp")
        if self.registration_mode not in ("open", "invite", "closed"):
            problems.append("--registration-mode must be open, invite or closed")
        elif self.registration_mode != "closed" and not self.smtp_host:
            problems.append("registration needs a way to send the verification email: give --smtp-host (and the "
                            "other SMTP details) or use --registration-mode closed")
        try:
            util.parse_cidrs(self.operator_networks)
        except ValueError as error:
            problems.append(f"--operator-networks: {error}")
        if self.smtp_host:
            if not util.valid_email(self.smtp_from):
                problems.append("--smtp-from must be the sender address (an email)")
            if not 1 <= self.smtp_port <= 65535:
                problems.append("--smtp-port must be 1-65535")
            for label, value in (("SMTP user", self.smtp_user), ("SMTP password", self.smtp_password),
                                 ("sender name", self.smtp_from_name)):
                if "'" in value or "\n" in value or "\\" in value:
                    problems.append(f"{label} must not contain quotes, backslashes or line breaks (they cannot be "
                                    "stored safely in the environment file)")
        if self.default_plan and not self.default_plan.replace("-", "").replace("_", "").isalnum():
            problems.append("--default-plan must be a plan code (letters, digits, - and _)")
        sources = [bool(self.repo), bool(self.from_dir), bool(self.tarball)]
        if sum(sources) > 1:
            problems.append("give only one of --repo, --from-dir and --tarball")
        if self.prebuilt and self.repo:
            problems.append("--prebuilt needs built folders in --from-dir or --tarball, not --repo")
        if self.public_ip:
            try:
                import ipaddress
                ipaddress.ip_address(self.public_ip)
            except ValueError:
                problems.append("--public-ip is not an IP address")
        return problems


# --------------------------------------------------------------------------- command line
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="install.sh", description="Install Ziira (business app, website and Super Admin) on this server.",
        epilog="Every option can also be a line `name=value` in an --config answers file. Passwords are never flags: "
               "ZIIRA_OPERATOR_PASSWORD (super admin) and ZIIRA_INSTALL_SMTP_PASSWORD, or you are asked.")
    a = p.add_argument
    a("--root-domain", help="the landing page's domain, e.g. ziira.io")
    a("--app-host", help="host of the business web app (default app.<root>)")
    a("--admin-host", help="host of the Super Admin (default admin.<root>)")
    a("--www", dest="www", action="store_true", default=None, help="also serve www.<root> as a redirect (default)")
    a("--no-www", dest="www", action="store_false", default=None)
    a("--email", help="contact email for Let's Encrypt")
    a("--install-dir"), a("--web-root"), a("--backup-dir")
    a("--postgres-new-cluster", action="store_true", default=None,
      help="if only a PostgreSQL older than 16 exists, create a second 16 cluster on another port (needs your consent)")
    a("--db-prefix", help="prefix of every database and role we create (default ziira_: role ziira, ziira_master, ziira_t_<code>)")
    a("--pg-port", type=int, help="which PostgreSQL to use when several run")
    a("--admin-name"), a("--admin-email")
    a("--smtp-host", help=argparse.SUPPRESS), a("--smtp-port", type=int, help=argparse.SUPPRESS)       # advanced: set Email in the
    a("--smtp-user", help=argparse.SUPPRESS), a("--smtp-from", help=argparse.SUPPRESS)                  # Super Admin instead
    a("--smtp-from-name", help=argparse.SUPPRESS)
    a("--default-plan", help="plan code given to new registrations (optional; can be set in the Super Admin)")
    a("--registration-mode", choices=["open", "invite", "closed"], help=argparse.SUPPRESS)
    a("--operator-mfa", choices=["off", "totp"], help="Super Admin sign-in: off = email and password only")
    a("--operator-networks", help="comma separated CIDRs allowed to reach the Super Admin (empty = anyone)")
    a("--repo", help="git repository to install from"), a("--branch")
    a("--from-dir", help="install from this checkout (default: the checkout this script is in)")
    a("--tarball", help="install from a release tarball")
    a("--prebuilt", action="store_true", default=None, help="use already built frontend/dist and site/dist")
    a("--site-strict", action="store_true", default=None, help="fail the website build when it is not on published content")
    a("--cert-mode", choices=["per-host", "single"])
    a("--staging", action="store_true", default=None, help="Let's Encrypt staging (untrusted test certificates)")
    a("--self-signed", action="store_true", default=None, help="throwaway self-signed certificates instead of Let's Encrypt")
    a("--agree-tos", action="store_true", default=None, help="accept the Let's Encrypt subscriber agreement")
    a("--hsts", choices=["off", "on", "include-subdomains"])
    a("--csp", choices=["report-only", "enforce", "off"], help="Content-Security-Policy of the web app")
    a("--skip-dns-check", action="store_true", default=None)
    a("--public-ip", help="this server's public IP (default: looked up)")
    a("--no-services", action="store_true", default=None,
      help="config-only: write and validate files; install no database, start no service (for tests and staging images)")
    a("--manage-firewall", action="store_true", default=None, help="allow the installer to ENABLE ufw (asks to confirm)")
    a("--fail2ban", action="store_true", default=None, help="install/enable fail2ban with a ziira-only jail")
    a("--inspect", action="store_true", default=None, help="print what is on this server and what would change; change nothing")
    a("--proxy-mode", choices=["snippet"], help="another proxy owns 80/443: run behind it and write config snippets for it")
    a("--ports", type=int, help="run our own nginx on 127.0.0.1:PORT (plain HTTP) to be fronted by another proxy")
    a("--snippet-dir", help="folder for the proxy snippets")
    a("--user", dest="service_user", help="system user to run Ziira as (default ziira)")
    a("--allow-unsupported-os", action="store_true", default=None)
    a("--api-port", type=int), a("--rebuild-port", type=int), a("--workers", type=int)
    a("--dry-run", action="store_true", help="print the plan, change nothing")
    a("--yes", "-y", action="store_true", help="non-interactive: use flags, the answers file and defaults")
    a("--config", help="answers file (lines name=value, or JSON)")
    a("--only", help="run only these steps (comma separated; see --list-steps)")
    a("--skip", help="skip these steps (comma separated)")
    a("--list-steps", action="store_true")
    a("--version", action="store_true")
    return p


def read_answers(text: str) -> dict[str, str]:
    """An answers file: JSON object, or `name=value` lines (# comments)."""
    text = text.strip()
    if text.startswith("{"):
        return {str(k).replace("-", "_"): str(v) if not isinstance(v, bool) else str(v).lower()
                for k, v in json.loads(text).items()}
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip().lstrip("-").replace("-", "_")] = value
    return out


def _coerce(name: str, raw: str, current: object) -> object:
    if isinstance(current, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return raw


def load(argv: list[str], environ: dict[str, str] | None = None, config_text: str | None = None) -> tuple[Config, argparse.Namespace]:
    """Build a Config: answers file first, then flags on top. Secrets only from the environment."""
    env = os.environ if environ is None else environ
    ns = build_parser().parse_args(argv)
    cfg = Config()
    names = {f.name for f in fields(Config)}
    if ns.config or config_text is not None:
        text = config_text if config_text is not None else open(ns.config).read()
        for key, raw in read_answers(text).items():
            if key in names and key not in ("admin_password", "smtp_password"):
                setattr(cfg, key, _coerce(key, raw, getattr(cfg, key)))
            elif key not in names:
                raise SystemExit(f"Unknown setting '{key}' in the answers file")
    for key, value in vars(ns).items():
        if key in names and value is not None and value != "":
            setattr(cfg, key, _coerce(key, value, getattr(cfg, key)) if isinstance(value, str) else value)
    if ns.only:
        cfg.only = [x.strip() for x in ns.only.split(",") if x.strip()]
    if ns.skip:
        cfg.skip = [x.strip() for x in ns.skip.split(",") if x.strip()]
    cfg.dry_run = bool(ns.dry_run)
    cfg.yes = bool(ns.yes)
    cfg.admin_password = env.get("ZIIRA_OPERATOR_PASSWORD", "")
    cfg.smtp_password = env.get("ZIIRA_INSTALL_SMTP_PASSWORD", "")
    return cfg, ns

"""The ordered list of steps, and the final summary."""
from __future__ import annotations

from typing import Callable, Tuple

from installer.context import Ctx
from installer.steps_app import step_env, step_migrate, step_release, step_services, step_user, step_webapp
from installer.steps_base import step_node, step_packages, step_preflight, step_python
from installer.steps_inspect import step_inspect
from installer.steps_pg import step_postgres
from installer.steps_web import step_nginx, step_nginx_tls, step_site, step_ssl, step_system

Step = Tuple[str, str, Callable[[Ctx], None]]       # typing generics: this runs at import time on Python 3.8

STEPS: list[Step] = [
    ("inspect", "Inspecting this server (read-only) and planning", step_inspect),
    ("preflight", "Checking the server (system, resources, ports, DNS)", step_preflight),
    ("packages", "System packages (only the missing ones)", step_packages),
    ("python", "Python 3.12 or newer for the application", step_python),
    ("node", "Node.js (to build the web app and website)", step_node),
    ("user", "Service user and folders", step_user),
    ("postgres", "PostgreSQL (detect, then create only the Ziira role and databases)", step_postgres),
    ("release", "Application release (code and virtual environment)", step_release),
    ("env", "Configuration file /etc/ziira/ziira.env", step_env),
    ("migrate", "Platform install, master database and first super admin", step_migrate),
    ("webapp", "Business web app (also served on the admin host)", step_webapp),
    ("services", "Services (API, worker, website rebuild receiver, timers)", step_services),
    ("nginx", "nginx on port 80 (certificate challenge)", step_nginx),
    ("ssl", "SSL certificates and automatic renewal", step_ssl),
    ("nginx-tls", "nginx over HTTPS for the three hosts", step_nginx_tls),
    ("site", "Website (landing page)", step_site),
    ("system", "Firewall, fail2ban, log rotation", step_system),
    ("summary", "Summary", lambda ctx: step_summary(ctx)),
]
NAMES = [s[0] for s in STEPS]


def summary_text(ctx: Ctx) -> str:
    cfg = ctx.cfg
    s = ctx.secrets()
    lines = [
        "Ziira installation summary", f"Written {ctx.started} (root-only file; contains secrets)", "",
        "Addresses",
        f"  Landing page      https://{cfg.root_domain}" + (f"   (www.{cfg.root_domain} redirects here)" if cfg.www else ""),
        f"  Business app      https://{cfg.app_host}      (sign in; /register to create a business)",
        f"  Super Admin       https://{cfg.admin_host}    (sign in as {cfg.admin_email})", "",
        "Where things are",
        f"  Application       {cfg.current} -> {cfg.release_dir}/<release>   (virtualenv inside each release)",
        f"  Configuration     {ctx.env_path}   (mode 0640 root:{cfg.service_user})",
        f"  Web roots         {cfg.web_root}/app/current   {cfg.web_root}/site/current",
        f"  Backups           {cfg.backup_dir}   (nightly 02:17, restore test Sundays)",
        "  nginx             /etc/nginx/sites-available/ziira-*.conf, logs /var/log/nginx/ziira/",
        "  Services          ziira-api  ziira-worker  ziira-site-rebuild  (journalctl -u ziira-api)",
        "  Helper commands   ziira-doctor   ziira-update   ziira-backup-now   ziira-cli <ziira command>", "",
        "KEEP THESE SAFE (copy them OFFLINE now; this file is the only plain copy outside the env file)",
    ]
    if s.fresh_credentials_key:
        lines += [f"  ZIIRA_CREDENTIALS_KEY = {s.credentials_key}",
                  "    Losing this key locks out EVERY business: their database logins are encrypted with it.",
                  "    It must not be stored with the backups. Also keep the whole " + ctx.env_path + "."]
    else:
        lines += [f"  ZIIRA_CREDENTIALS_KEY: unchanged from an earlier install; it is in {ctx.env_path}"]
    lines += ["", "Warnings"] + [f"  - {w}" for w in ctx.ui.report.warnings] if ctx.ui.report.warnings else []
    return "\n".join(lines) + "\n"


def step_summary(ctx: Ctx) -> None:
    ui = ctx.ui
    text = summary_text(ctx)
    existing = ctx.sys.read_text(ctx.summary_path)
    if existing is None or (ctx.secrets().fresh_credentials_key and "ZIIRA_CREDENTIALS_KEY =" not in existing):
        ctx.sys.write_text(ctx.summary_path, text, mode=0o600, owner="root", group="root", secret=True)
        ui.ok(f"summary written to {ctx.summary_path} (mode 0600)")
    else:
        ui.already(f"summary {ctx.summary_path} (kept; it holds the key shown at the first install)")
    ctx.write_state()

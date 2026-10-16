"""uninstall.sh: remove what the installer set up. Data stays unless you ask twice.

    sudo bash deploy/uninstall.sh                 # removes services, timers, nginx sites, helper commands (typed confirmation)
    sudo bash deploy/uninstall.sh --purge-data    # ALSO drops the Ziira databases and roles, deletes the files (asks twice)

Never touched, even with --purge-data: PostgreSQL itself and any database or role that is not Ziira's, nginx, certbot and the
certificates, the firewall rules, other sites, the backup folder (copy or delete it yourself).
"""
from __future__ import annotations

import argparse
import sys

from installer import util
from installer.context import Ctx
from installer.steps_pg import psql_admin
from installer.system import System
from installer.ui import UI, StepFailed
from installer.update import load_config

UNITS_GLOB = ("ziira-api.service", "ziira-worker.service", "ziira-site-rebuild.service", "ziira-nginx-reload.path",
              "ziira-nginx-reload.service", "ziira-certbot-renew.service", "ziira-certbot-renew.timer")


def typed(ui: UI, expected: str, prompt: str) -> bool:
    if not ui.interactive:
        return False
    return ui._reader(f"  {prompt}\n  Type '{expected}' to continue: ").strip() == expected


def remove_services(ctx: Ctx) -> None:
    sysm, ui = ctx.sys, ctx.ui
    from installer import units
    names = list(UNITS_GLOB) + [f"ziira-{j.name}.{kind}" for j in units.JOBS for kind in ("service", "timer")]
    active = [n for n in names if n.endswith((".service", ".timer", ".path")) and sysm.exists(f"/etc/systemd/system/{n}")]
    if active:
        sysm.run(["systemctl", "disable", "--now", *active], check=False, desc="stop and disable the Ziira units")
    for n in active:
        sysm.remove(f"/etc/systemd/system/{n}")
    sysm.run(["systemctl", "daemon-reload"], check=False)
    ui.ok(f"removed {len(active)} systemd unit(s)")
    for name in ("ziira-site.conf", "ziira-app.conf", "ziira-admin.conf", "ziira-default.conf"):
        sysm.remove(f"/etc/nginx/sites-enabled/{name}")
        sysm.remove(f"/etc/nginx/sites-available/{name}")
    for path in ["/etc/nginx/conf.d/ziira-common.conf"] + [f"/etc/nginx/snippets/{f}" for f in sysm.listdir("/etc/nginx/snippets")
                                                         if f.startswith("ziira-")]:
        sysm.remove(path)
    if sysm.run(["nginx", "-t"], probe=True, check=False).ok:
        sysm.run(["systemctl", "reload", "nginx"], check=False)
        ui.ok("removed the Ziira nginx configuration and reloaded nginx")
    else:
        ui.warn("nginx -t fails after removing the Ziira files: fix nginx by hand before reloading")
    for path in ("/etc/logrotate.d/ziira-nginx", "/etc/fail2ban/jail.d/ziira.local",
                 "/etc/letsencrypt/renewal-hooks/deploy/ziira-reload-nginx.sh",
                 "/usr/local/bin/ziira-cli", "/usr/local/bin/ziira-doctor", "/usr/local/bin/ziira-update",
                 "/usr/local/bin/ziira-backup-now"):
        sysm.remove(path)
    ui.ok("removed helper commands, log rotation and the fail2ban jail")


def purge_data(ctx: Ctx) -> None:
    """Drop the Ziira databases and roles, delete the files. Only objects that belong to Ziira are named."""
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    port = int(ctx.facts.get("pg_port", 5432) or 5432)
    prefix_db, prefix_role = "ziira_t_", "zt_"
    names = psql_admin(ctx, port, "select datname from pg_database where datname like 'ziira\\_t\\_%' "
                                  f"or datname in ({util.sql_literal(cfg.master_db)}, 'ziira_template') order by 1;",
                       probe=True, check=False).out.split()
    roles = psql_admin(ctx, port, "select rolname from pg_roles where rolname like 'zt\\_%' order by 1;", probe=True,
                       check=False).out.split()
    for db in names:
        if db == cfg.master_db or db == "ziira_template" or db.startswith(prefix_db):
            psql_admin(ctx, port, f"drop database {util.sql_ident(db)} with (force);", check=False)
    for role in roles:
        if role.startswith(prefix_role):
            psql_admin(ctx, port, f"drop role {util.sql_ident(role)};", check=False)
    psql_admin(ctx, port, f"drop role if exists {util.sql_ident(cfg.db_role)};", check=False)
    ui.ok(f"dropped {len(names)} database(s) and {len(roles)} tenant role(s), and the role '{cfg.db_role}'")
    for path in (cfg.install_dir, cfg.web_root, cfg.state_dir, cfg.env_dir):
        sysm.remove(path)
    ui.ok("deleted the application, web roots, state and /etc/ziira (the backup folder was kept)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="uninstall.sh", description=__doc__.split("\n\n")[0])
    p.add_argument("--purge-data", action="store_true", help="also drop the Ziira databases and delete the files")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true", help="skip the first confirmation (never the --purge-data one)")
    ns = p.parse_args(argv)
    ui = UI(interactive=sys.stdin.isatty())
    sysm = System(dry_run=ns.dry_run, say=ui.plan)
    try:
        cfg, facts = load_config(sysm)
        ctx = Ctx(cfg=cfg, sys=sysm, ui=ui, facts=dict(facts))
        ctx.need_root()
        if not ns.dry_run:
            if not (ns.yes or typed(ui, "uninstall", f"This stops Ziira on {cfg.root_domain} and removes its services and nginx sites.")):
                ui.fail("not confirmed; nothing was changed")
                return 1
            if ns.purge_data and not typed(ui, f"delete all data of {cfg.root_domain}",
                                           "PURGE: every business database, login and file of this installation will be "
                                           "destroyed and CANNOT be recovered (except from backups you copied elsewhere)."):
                ui.fail("purge not confirmed; nothing was changed")
                return 1
        remove_services(ctx)
        if ns.purge_data:
            purge_data(ctx)
        else:
            ui.info(f"Kept: the databases, {cfg.env_dir}, {cfg.install_dir}, {cfg.web_root}, {cfg.backup_dir}, certificates.")
        return 0
    except StepFailed as error:
        ui.fail(error.message, error.hint)
        return 1


if __name__ == "__main__":
    sys.exit(main())

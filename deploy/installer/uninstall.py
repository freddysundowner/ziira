"""uninstall.sh: undo exactly what the installer recorded in its manifest, and nothing else.

    sudo bash deploy/uninstall.sh                 # removes what we ADDED to the system (units, nginx files, helpers, our certificates
                                                  # are kept), restores files we modified; keeps the data
    sudo bash deploy/uninstall.sh --purge-data    # ALSO drops the Ziira databases and roles and deletes /etc/ziira, /var/lib/ziira,
                                                  # the backups folder and the application (asks twice)
    sudo bash deploy/uninstall.sh --dry-run       # lists every file and command, changes nothing

Never touched: PostgreSQL itself and any database or role that is not Ziira's, nginx and its other sites, other certificates,
firewall rules, packages (they stay installed), the system user (use --remove-user), other users' crontabs and files.
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


def data_roots(ctx: Ctx) -> list[str]:
    cfg = ctx.cfg
    return [cfg.env_dir, cfg.state_dir, cfg.backup_dir]


def is_data(ctx: Ctx, path: str) -> bool:
    return any(path == r or path.startswith(r + "/") for r in data_roots(ctx))


def ours(ctx: Ctx, path: str) -> bool:
    """Directories inside our own namespaces may be removed with their content; others only when empty."""
    cfg = ctx.cfg
    roots = [cfg.install_dir, cfg.env_dir, cfg.state_dir, cfg.web_root, cfg.backup_dir, "/var/log/ziira"]
    return any(path == r or path.startswith(r + "/") for r in roots)


def restore(ctx: Ctx, entry: dict[str, str]) -> None:
    sysm = ctx.sys
    path, backup = entry["path"], entry["backup"]
    if backup.startswith("link:"):
        sysm.remove(path)
        sysm.symlink(path, backup[5:])
        return
    text = sysm.read_text(backup)
    if text is not None:
        sysm.write_text(path, text)


def undo_manifest(ctx: Ctx, *, purge: bool) -> int:
    """Walk the manifest backwards. Returns how many entries were handled."""
    sysm, ui = ctx.sys, ctx.ui
    handled = 0
    for entry in reversed(list(sysm.manifest.entries)):
        path, action, kind = entry["path"], entry["action"], entry["kind"]
        if is_data(ctx, path) and not purge:
            continue
        if action == "created":
            if kind == "dir":
                if sysm.exists(path) and (ours(ctx, path) or not sysm.listdir(path)):
                    sysm.remove(path)
            elif sysm.exists(path):
                sysm.remove(path)
        elif action in ("modified", "removed"):
            restore(ctx, entry)
        handled += 1
    ui.ok(f"undid {handled} recorded change(s)" + ("" if purge else " (data folders kept)"))
    return handled


def remove_services(ctx: Ctx, *, purge: bool) -> None:
    sysm, ui = ctx.sys, ctx.ui
    units = [e["path"].rsplit("/", 1)[-1] for e in sysm.manifest.entries
             if e["path"].startswith("/etc/systemd/system/ziira-") and e["action"] == "created"]
    live = [u for u in units if sysm.exists(f"/etc/systemd/system/{u}")]
    if live:
        sysm.run(["systemctl", "disable", "--now", *live], check=False, desc="stop and disable the Ziira units: " + " ".join(live))
    undo_manifest(ctx, purge=purge)
    sysm.run(["systemctl", "daemon-reload"], check=False)
    if sysm.which("nginx"):
        if sysm.run(["nginx", "-t"], probe=True, check=False).ok:
            if sysm.run(["systemctl", "is-active", "--quiet", "nginx"], probe=True, check=False).ok:
                sysm.run(["systemctl", "reload", "nginx"], check=False, desc="systemctl reload nginx")
            ui.ok("nginx still passes nginx -t without our files")
        else:
            ui.warn("nginx -t fails after removing our files: check /etc/nginx by hand before reloading")
    for lineage in sysm.manifest.extra.get("lineages", []):
        if purge:
            sysm.run(["certbot", "delete", "--non-interactive", "--cert-name", lineage], check=False,
                     desc=f"certbot delete --cert-name {lineage} (our certificate only)")
    if not purge and cfg_clusters(ctx):
        ui.info("Kept the PostgreSQL cluster(s) the installer created (" + ", ".join(cfg_clusters(ctx)) + ") with all data and running; "
                "--purge-data drops them. The postgresql-16 package stays installed.")
    if not purge and sysm.manifest.extra.get("lineages"):
        ui.info("Kept our certificates (lineages " + ", ".join(sysm.manifest.extra["lineages"]) + "); --purge-data removes them.")


def cfg_clusters(ctx: Ctx) -> list[str]:
    """PostgreSQL clusters the installer itself created (only ever a separate '16/ziira', or a 16/main it installed)."""
    return [c for c in ctx.sys.manifest.extra.get("clusters", []) if c.startswith("16/")]


def purge_data(ctx: Ctx) -> None:
    """Drop the Ziira databases and roles (by the configured prefix only)."""
    cfg, ui = ctx.cfg, ctx.ui
    port = int(ctx.facts.get("pg_port", 5432) or 5432)
    like = lambda prefix: prefix.replace("_", "\\_") + "%"          # noqa: E731
    names = psql_admin(ctx, port, "select datname from pg_database where datname like "
                       f"{util.sql_literal(like(cfg.tenant_db_prefix))} or datname in ({util.sql_literal(cfg.master_db)}, "
                       f"{util.sql_literal(cfg.template_db)}) order by 1;", probe=True, check=False).out.split()
    roles = psql_admin(ctx, port, f"select rolname from pg_roles where rolname like {util.sql_literal(like(cfg.tenant_role_prefix))} "
                       "order by 1;", probe=True, check=False).out.split()
    for db in names:
        if db in (cfg.master_db, cfg.template_db) or db.startswith(cfg.tenant_db_prefix):
            psql_admin(ctx, port, f"drop database {util.sql_ident(db)} with (force);", check=False)
    for role in roles:
        if role.startswith(cfg.tenant_role_prefix):
            psql_admin(ctx, port, f"drop role {util.sql_ident(role)};", check=False)
    psql_admin(ctx, port, f"drop role if exists {util.sql_ident(cfg.db_role)};", check=False)
    for cluster in cfg_clusters(ctx):
        version, name = cluster.split("/")
        ctx.sys.run(["pg_dropcluster", version, name, "--stop"], check=False,
                    desc=f"pg_dropcluster {version} {name} (created by this installer)")
    ui.ok(f"dropped {len(names)} database(s) and {len(roles)} tenant role(s), and the role '{cfg.db_role}'")


def run_uninstall(ctx: Ctx, *, purge: bool, remove_user: bool = False) -> None:
    sysm, ui, cfg = ctx.sys, ctx.ui, ctx.cfg
    if purge:
        purge_data(ctx)
    remove_services(ctx, purge=purge)
    if remove_user and cfg.service_user in sysm.manifest.extra.get("users", []):
        sysm.run(["userdel", cfg.service_user], check=False, desc=f"userdel {cfg.service_user}")
    elif remove_user:
        ui.info("the system user was not created by this installer: left alone")
    if purge:
        sysm.raw_remove("/var/lib/ziira/install-manifest.json")
    else:
        sysm.save_manifest()


def typed(ui: UI, expected: str, prompt: str) -> bool:
    if not ui.interactive:
        return False
    return ui._reader(f"  {prompt}\n  Type '{expected}' to continue: ").strip() == expected


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="uninstall.sh", description=__doc__.split("\n\n")[0])
    p.add_argument("--purge-data", action="store_true", help="also drop the Ziira databases and delete the data folders")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true", help="skip the first confirmation (never the --purge-data one)")
    p.add_argument("--confirm-purge", help="the exact phrase 'delete all data of <root domain>' (for unattended use; never implied)")
    p.add_argument("--remove-user", action="store_true", help="also delete the system user (only if the installer created it)")
    ns = p.parse_args(argv)
    ui = UI(interactive=sys.stdin.isatty())
    sysm = System(dry_run=ns.dry_run, say=ui.plan)
    try:
        cfg, facts = load_config(sysm)
        sysm.load_manifest()
        ctx = Ctx(cfg=cfg, sys=sysm, ui=ui, facts=dict(facts))
        ctx.need_root()
        if not sysm.manifest.entries:
            raise StepFailed("there is no install manifest (/var/lib/ziira/install-manifest.json): refusing to guess what to remove")
        if not ns.dry_run:
            if not (ns.yes or typed(ui, "uninstall", f"This stops Ziira ({cfg.root_domain}) and removes what the installer added.")):
                ui.fail("not confirmed; nothing was changed")
                return 1
            phrase = f"delete all data of {cfg.root_domain}"
            if ns.purge_data and ns.confirm_purge != phrase and not typed(
                    ui, phrase, "PURGE: every business database, login and file of this installation will be destroyed "
                                "and CANNOT be recovered (except from backups you copied elsewhere)."):
                ui.fail("purge not confirmed; nothing was changed")
                return 1
        run_uninstall(ctx, purge=ns.purge_data, remove_user=ns.remove_user)
        return 0
    except StepFailed as error:
        ui.fail(error.message, error.hint)
        return 1


if __name__ == "__main__":
    sys.exit(main())

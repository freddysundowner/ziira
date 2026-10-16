"""ziira-update: deploy a newer version, with a database backup first and automatic rollback of the code.

    sudo ziira-update --from-dir /path/to/checkout       # or --repo URL --branch main, or --tarball FILE
    sudo ziira-update --rollback                         # go back to the previous release

Order (docs/operations.md, "Deploying"): build the new release next to the live one, check the configuration, back up the
master database, run the migrations with the NEW code while the OLD code keeps serving (migrations are backward
compatible for one release), switch the `current` symlink, restart, wait for /readyz, then publish the web app and
rebuild the website. If the new release does not become ready, `current` and the services go back to the old release.
Migrations are never reversed automatically: an applied migration stays (a mistake is fixed by a new forward migration).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import fields
from urllib.parse import unquote, urlparse

from installer import release, webbuild
from installer.config import Config
from installer.context import Ctx
from installer.steps_app import step_services, wait_http
from installer.steps_base import step_node, step_python
from installer.steps_web import step_nginx_tls
from installer.system import CommandFailed, System
from installer.ui import UI, StepFailed

STATE_PATH = "/etc/ziira/install.json"


def load_config(sysm: System) -> tuple[Config, dict[str, object]]:
    text = sysm.read_text(STATE_PATH)
    if not text:
        raise StepFailed(f"{STATE_PATH} not found: this server was not installed with deploy/install.sh")
    data = json.loads(text)
    known = {f.name for f in fields(Config)}
    cfg = Config(**{k: v for k, v in data["config"].items() if k in known})
    cfg.resolve_defaults()
    return cfg, data.get("facts", {})


def backup_master(ctx: Ctx) -> str:
    """pg_dump of the master database before migrations. Returns the file written."""
    cfg, sysm = ctx.cfg, ctx.sys
    env = ctx.existing_env()
    url = urlparse(env["ZIIRA_MASTER_DATABASE_URL"].replace("postgresql+psycopg", "postgresql"))
    dump_tool = env.get("ZIIRA_PG_DUMP_COMMAND", "pg_dump")
    target_dir = f"{cfg.backup_dir}/pre-update"
    sysm.makedirs(target_dir, mode=0o750, owner=cfg.service_user, group=cfg.service_user)
    out = f"{target_dir}/master-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.dump"
    sysm.run([dump_tool, "--format=custom", "--compress=6", "-h", url.hostname or "127.0.0.1", "-p", str(url.port or 5432),
              "-U", unquote(url.username or ""), "-d", (url.path or "/").lstrip("/"), "-f", out], user=cfg.service_user,
             env={"PGPASSWORD": unquote(url.password or "")}, secret=True, cwd=cfg.state_dir, timeout=1800,
             desc=f"pg_dump of the master database to {out}")
    return out


def restart_and_wait(ctx: Ctx, seconds: int = 90) -> bool:
    ctx.sys.run(["systemctl", "restart", "ziira-api.service", "ziira-worker.service"], desc="restart the API and worker")
    return wait_http(ctx, f"http://127.0.0.1:{ctx.cfg.api_port}/readyz", seconds)


def rollback(ctx: Ctx, to: str | None = None) -> bool:
    """Put `current` back on the previous release (or `to`). True when the old release answers /readyz again."""
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    live = sysm.readlink(cfg.current) or ""
    if to is None:
        older = [r for r in sorted(release.list_releases(ctx, cfg.release_dir)) if f"{cfg.release_dir}/{r}" != live
                 and sysm.exists(f"{cfg.release_dir}/{r}/.complete")]
        older = [r for r in older if r < live.rsplit("/", 1)[-1]]
        if not older:
            raise StepFailed("there is no older release to go back to")
        to = f"{cfg.release_dir}/{older[-1]}"
    release.activate(ctx, to)
    ok = restart_and_wait(ctx)
    name = to.rsplit("/", 1)[-1]
    if ok:
        ui.ok(f"{cfg.current} points at {name} again")
    else:
        ui.warn(f"went back to {name} but /readyz does not answer: run ziira-doctor and check journalctl -u ziira-api")
    return ok


def run_update(ctx: Ctx, *, skip_backup: bool = False, keep: int = release.KEEP_RELEASES) -> int:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    ctx.need_root()
    old = sysm.readlink(cfg.current)
    if not old:
        raise StepFailed("nothing is installed yet (no current release)", hint="Run deploy/install.sh first.")
    ui.step(1, 6, "Preparing the new release")
    step_python(ctx)
    step_node(ctx)
    ctx.facts.setdefault("cpus", sysm.cpu_count())
    ctx.facts.setdefault("ram_mb", sysm.ram_mb())
    workdir = f"{cfg.state_dir}/fetch"
    if cfg.repo or cfg.tarball:
        sysm.makedirs(workdir)
        sysm.run(["rm", "-rf", f"{workdir}/src"], check=False)
    src, label = release.fetch_source(ctx, workdir)
    rel_id = release.new_release_id(label)
    path = release.build_release(ctx, src, rel_id)
    ctx.facts.update(release=path, release_id=rel_id)
    ui.ok(f"built release {rel_id}")

    ui.step(2, 6, "Checking the configuration with the new code")
    r = sysm.run(["python3", f"{path}/scripts/check_env.py", ctx.env_path], probe=True, check=False)
    if r.code != 0 and not cfg.dry_run:
        sysm.run(["rm", "-rf", path], check=False)
        raise StepFailed("the new version rejects the current configuration; nothing was changed",
                         hint=r.out[-1200:] + f"\nFix {ctx.env_path} (see the release notes) and run the update again.")
    ui.ok("scripts/check_env.py accepts the configuration")

    ui.step(3, 6, "Backing up the master database")
    if skip_backup:
        ui.warn("backup skipped (--skip-backup)")
    else:
        ui.ok(f"backup written: {backup_master(ctx)}")

    ui.step(4, 6, "Running migrations with the new code (the old code keeps serving)")
    env = ctx.app_env()
    sysm.run([f"{path}/venv/bin/ziira", "install", "--all"], user=cfg.service_user, env=env, cwd=cfg.state_dir, timeout=3600,
             desc="ziira install --all (new release)")
    ui.ok("migrations applied")

    ui.step(5, 6, "Switching to the new release")
    release.activate(ctx, path)
    if not restart_and_wait(ctx):
        log = sysm.run(["journalctl", "-u", "ziira-api", "-n", "30", "--no-pager"], probe=True, check=False).out
        ui.warn("the new release did not become ready; going back to the previous one. Last log lines:\n" + log[-1200:])
        rollback(ctx, old)
        ui.warn("Migrations that were applied stay applied (the old release is expected to work with them; docs/operations.md).")
        raise StepFailed("the update failed and was rolled back", hint=f"The failed release is kept at {path} for inspection.")
    ui.ok("the new release answers /readyz")

    ui.step(6, 6, "Web app, website, services and nginx")
    webbuild.build_frontend(ctx, path, rel_id)          # built and published only now that the API is healthy
    step_services(ctx)
    step_nginx_tls(ctx)
    if ctx.rebuild_enabled and not cfg.no_services:
        sysm.run(["/usr/bin/python3", "-m", "installer.sitebuild", "build"], user=cfg.service_user,
                 env={"PYTHONPATH": f"{path}/deploy", "ZIIRA_REBUILD_ENV": ctx.rebuild_env_path}, cwd=cfg.state_dir,
                 check=False, timeout=3600, desc="rebuild the website")
    removed = release.prune(ctx, cfg.release_dir, keep)
    if removed:
        ui.info("removed old releases: " + ", ".join(removed))
    ctx.write_state()
    ui.info(f"\nUpdated to release {rel_id}. Previous release kept for rollback:  sudo ziira-update --rollback")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ziira-update", description=__doc__.split("\n\n")[0])
    p.add_argument("--from-dir"), p.add_argument("--repo"), p.add_argument("--branch", default=None), p.add_argument("--tarball")
    p.add_argument("--prebuilt", action="store_true")
    p.add_argument("--skip-backup", action="store_true")
    p.add_argument("--rollback", action="store_true", help="go back to the previous release")
    p.add_argument("--keep", type=int, default=release.KEEP_RELEASES)
    p.add_argument("--dry-run", action="store_true")
    ns = p.parse_args(argv)
    ui = UI(interactive=False)
    sysm = System(dry_run=ns.dry_run, say=ui.plan)
    try:
        cfg, facts = load_config(sysm)
        cfg.dry_run = ns.dry_run
        if ns.from_dir or ns.repo or ns.tarball:        # an explicit source replaces the one remembered from the install
            cfg.from_dir, cfg.repo, cfg.tarball = ns.from_dir or "", ns.repo or "", ns.tarball or ""
        if ns.branch:
            cfg.branch = ns.branch
        if ns.prebuilt:
            cfg.prebuilt = True
        if not ns.rollback and not (cfg.from_dir or cfg.repo or cfg.tarball):
            raise StepFailed("no source for the new version",
                             hint="Give --from-dir DIR (a new checkout), --repo URL [--branch B], or --tarball FILE.")
        ctx = Ctx(cfg=cfg, sys=sysm, ui=ui, facts={k: v for k, v in facts.items()})
        if ns.rollback:
            return 0 if rollback(ctx) else 1
        return run_update(ctx, skip_backup=ns.skip_backup, keep=ns.keep)
    except StepFailed as error:
        ui.fail(error.message, error.hint)
        return 1
    except CommandFailed as error:
        ui.fail(str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())

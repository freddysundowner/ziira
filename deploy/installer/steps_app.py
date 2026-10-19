"""Steps 6-11: service user and folders, the application release, its environment file, migrations, operator, web app, services."""
from __future__ import annotations

import time

from installer import appenv, envfile, release, units, webbuild
from installer.context import Ctx
from installer.ui import StepFailed

WRAPPERS = {
    "ziira-cli": """#!/bin/sh
# Run the `ziira` administration command as the service user with the production environment.
#   sudo ziira-cli tenants        sudo ziira-cli backup --dir {backup_dir}
exec runuser -u {user} -- sh -c 'set -a; . {env}; set +a; cd {state}; exec {install}/current/venv/bin/ziira "$@"' ziira "$@"
""",
    "ziira-doctor": """#!/bin/sh
exec env PYTHONPATH={install}/current/deploy /usr/bin/python3 -m installer.doctor "$@"
""",
    "ziira-update": """#!/bin/sh
exec env PYTHONPATH={install}/current/deploy /usr/bin/python3 -m installer.update "$@"
""",
    "ziira-backup-now": """#!/bin/sh
exec runuser -u {user} -- sh -c 'set -a; . {env}; set +a; cd {state}; \\
  exec {install}/current/venv/bin/ziira backup --dir {backup_dir} "$@"' ziira "$@"
""",
}


def step_user(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    if sysm.user_exists(cfg.service_user):
        ui.already(f"system user '{cfg.service_user}'")
    else:
        sysm.run(["useradd", "--system", "--user-group", "--home-dir", cfg.state_dir, "--no-create-home", "--shell",
                  "/usr/sbin/nologin", cfg.service_user], desc=f"create system user {cfg.service_user} (no login)")
        sysm.manifest.note("users", cfg.service_user)
        ui.ok(f"created system user '{cfg.service_user}' (no login shell)")
    u = cfg.service_user
    changed = False
    for path, mode, owner, group in (
            (cfg.install_dir, 0o755, "root", "root"), (cfg.release_dir, 0o755, "root", "root"),
            (cfg.env_dir, 0o750, "root", u), (cfg.state_dir, 0o750, u, u), (f"{cfg.state_dir}/nginx", 0o755, u, u),
            (f"{cfg.state_dir}/site-build", 0o750, u, u), (f"{cfg.state_dir}/files", 0o700, u, u),
            (cfg.backup_dir, 0o750, u, u),
            (cfg.web_root, 0o755, "root", "root"), (f"{cfg.web_root}/app", 0o755, "root", "root"),
            (f"{cfg.web_root}/site", 0o755, u, u), ("/var/www/letsencrypt", 0o755, "root", "root"),
            ("/var/log/ziira", 0o750, "root", "adm"), ("/var/log/ziira/nginx", 0o750, "root", "adm")):
        if sysm.makedirs(path, mode=mode, owner=owner, group=group):
            changed = True
    if changed:
        ui.ok("created the folders (install, releases, /etc/ziira, state, backups, web roots, logs)")
    else:
        ui.already("folders")
    if webbuild.ensure_placeholders(ctx):
        # site/ is written by the service user (the rebuild receiver switches `current` inside it)
        sysm.run(["chown", "-R", f"{u}:{u}", f"{cfg.web_root}/site"], check=False, desc="give the service user the site web root")
    if not sysm.exists(f"{cfg.state_dir}/nginx/site-redirects.conf"):
        sysm.write_text(f"{cfg.state_dir}/nginx/site-redirects.conf", "# no redirects yet\n", mode=0o644, owner=u, group=u)


def install_helpers(ctx: Ctx) -> None:
    """Helper commands in /usr/local/bin and the safe nginx reload script (written every run; cheap and idempotent)."""
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    changed = False
    for name, body in WRAPPERS.items():
        text = body.format(user=cfg.service_user, env=ctx.env_path, state=cfg.state_dir, install=cfg.install_dir,
                           backup_dir=cfg.backup_dir)
        changed |= sysm.write_text(f"/usr/local/bin/{name}", text, mode=0o755)
    sysm.makedirs(f"{cfg.install_dir}/bin")
    changed |= sysm.write_text(f"{cfg.install_dir}/bin/nginx-safe-reload.sh",
                               units.nginx_safe_reload_script(cfg, ctx.facts.get("mode") == "behind"), mode=0o755,
                               owner="root", group="root")
    if changed:
        ui.ok("installed the helper commands: ziira-cli, ziira-doctor, ziira-update, ziira-backup-now")


def step_release(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    current = sysm.readlink(cfg.current)
    if current and sysm.exists(f"{current}/.complete"):
        name = current.rsplit("/", 1)[-1]
        # An install that stopped part-way (the services are not written yet) and is re-run from a NEWER checkout must use the
        # new code: otherwise a fix pulled from the repository is ignored and the same failure repeats. A finished install is
        # only ever changed by ziira-update (with a database backup and a rollback).
        unfinished = not sysm.exists("/etc/systemd/system/ziira-api.service")
        newer = False
        if unfinished and not cfg.repo and not cfg.tarball:
            sha = sysm.run(["git", "-C", cfg.from_dir or release.repo_root_of_installer(), "rev-parse", "--short", "HEAD"],
                           probe=True, check=False).out.strip()
            newer = bool(sha) and not name.endswith("-" + sha)
        if not newer:
            ctx.facts["release"] = current
            ctx.facts["release_id"] = name
            ui.already(f"release {name} is installed and active (use ziira-update to deploy a newer version)")
            return
        ui.note(f"release {name} was made by an earlier, unfinished run from older code: building a new release from this checkout")
    workdir = f"{cfg.state_dir}/fetch"
    if cfg.repo or cfg.tarball:
        sysm.makedirs(workdir)
        sysm.run(["rm", "-rf", f"{workdir}/src"], check=False)
    src, label = release.fetch_source(ctx, workdir)
    rel_id = release.new_release_id(label)
    path = release.build_release(ctx, src, rel_id, venv=ctx.real_services)
    release.activate(ctx, path)
    ctx.facts["release"] = path
    ctx.facts["release_id"] = rel_id
    ui.ok(f"installed release {rel_id}; {cfg.current} now points at it")


def step_env(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    s = ctx.secrets()
    master, server = ctx.db_urls()
    wanted = appenv.build(cfg, secret_key=s.secret_key, credentials_key=s.credentials_key, metrics_token=s.metrics_token,
                          master_url=master, server_url=server, hook_secret=s.hook_secret, hook_token=s.hook_token,
                          pg_major=int(ctx.facts.get("pg_major", 16)), rebuild=ctx.rebuild_enabled)
    existing = ctx.existing_env()
    merged, added, differing = envfile.merge(existing, wanted)
    text = envfile.render(merged, cfg.service_user)
    if sysm.write_text(ctx.env_path, text, mode=0o640, owner="root", group=cfg.service_user, secret=True):
        ui.ok(f"{ctx.env_path}: " + (f"added {len(added)} setting(s)" if existing else f"created with {len(merged)} settings")
              + " (mode 0640, root:" + cfg.service_user + ")")
    else:
        ui.already(f"{ctx.env_path} has every setting")
    for line in envfile.diff_lines(existing, wanted, differing):
        ui.warn(line)
    if cfg.operator_mfa == "off":
        ui.warn("Super Admin sign-in is EMAIL + PASSWORD ONLY (your choice). One stolen or guessed password gives control "
                "of every business. The installer set ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED=true. Strongly consider "
                "--operator-networks (limit by address) or --operator-mfa totp (docs/security.md).")
    # the website rebuild receiver's own, smaller environment (no database access)
    if ctx.rebuild_enabled:
        rb = appenv.rebuild_env(cfg, hook_secret=s.hook_secret, hook_token=s.hook_token)
        rb["ZIIRA_NODE_BIN"] = str(ctx.facts.get("node_bin", ""))
        sysm.write_text(ctx.rebuild_env_path, envfile.render(rb, cfg.service_user), mode=0o640, owner="root",
                        group=cfg.service_user, secret=True)
    # validate with the project's own checker
    checker = f"{ctx.facts.get('release', cfg.current)}/scripts/check_env.py"
    if sysm.exists(checker) or cfg.dry_run:
        r = sysm.run(["python3", checker, ctx.env_path], probe=True, check=False)
        for line in r.out.splitlines():
            if line.startswith("ERROR"):
                ui.warn("check_env: " + line)
            elif line.startswith("WARN"):
                ui.info("check_env: " + line)
        if r.code != 0 and not cfg.dry_run:
            raise StepFailed("scripts/check_env.py found errors in the generated configuration (listed above)",
                             hint=f"Fix them in {ctx.env_path} and run the installer again.\n{r.out[-800:]}")
        if r.code == 0:
            ui.ok("scripts/check_env.py accepts the configuration")
    if not sysm.exists(ctx.state_path):
        ctx.write_state()


def step_migrate(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    if cfg.no_services:
        ui.already("migrations skipped (--no-services)")
        return
    env = ctx.app_env()
    zi = ctx.venv_bin("ziira")
    sysm.run([zi, "install", "--all"], user=cfg.service_user, env=env, cwd=cfg.state_dir, timeout=1800,
             desc="ziira install --all (master database, tenant template, every module)")
    ui.ok("master database and tenant template are up to date (ziira install --all)")
    # first super admin
    listing = sysm.run([zi, "operator", "list"], user=cfg.service_user, env=env, cwd=cfg.state_dir, probe=True, check=False)
    if cfg.admin_email.lower() in listing.out.lower():
        ui.already(f"super admin {cfg.admin_email}")
    else:
        if not cfg.admin_password and not cfg.dry_run:
            raise StepFailed("no password for the first super admin",
                             hint="Set ZIIRA_OPERATOR_PASSWORD in the environment, or run interactively.")
        sysm.run([zi, "operator", "create", cfg.admin_name, cfg.admin_email, "--role", "superadmin"],
                 user=cfg.service_user, env={**env, "ZIIRA_OPERATOR_PASSWORD": cfg.admin_password}, cwd=cfg.state_dir,
                 secret=True, desc=f"ziira operator create '{cfg.admin_name}' {cfg.admin_email} (password hidden)")
        ui.ok(f"created the first super admin {cfg.admin_email}")
        if cfg.operator_mfa == "totp":
            ui.warn("two-step sign-in is on: set it up at first sign-in, or run  ziira-cli operator reset-mfa "
                    f"{cfg.admin_email}  to get a new secret (the creation output was not stored)")


def step_webapp(ctx: Ctx) -> None:
    cfg, ui = ctx.cfg, ctx.ui
    if cfg.no_services and not cfg.prebuilt:
        ui.already("web app build skipped (--no-services without --prebuilt)")
        return
    current = ctx.sys.readlink(f"{cfg.web_root}/app/current") or ""
    if "initial" not in current and current:
        ui.already(f"web app {current.rsplit('/', 1)[-1]} is published")
        return
    path = ctx.facts.get("release", cfg.current)
    webbuild.build_frontend(ctx, path, str(ctx.facts.get("release_id", time.strftime("%Y%m%d%H%M%S"))))


def wait_http(ctx: Ctx, url: str, seconds: int = 60) -> bool:
    if ctx.cfg.dry_run:
        return True
    for _ in range(seconds):
        if ctx.sys.run(["curl", "-fsS", "--max-time", "3", "-o", "/dev/null", url], probe=True, check=False).ok:
            return True
        time.sleep(1)
    return False


def step_services(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    install_helpers(ctx)
    workers = cfg.workers or units.worker_count(int(ctx.facts.get("cpus", 2)), int(ctx.facts.get("ram_mb", 2048)))
    files = {
        "/etc/systemd/system/ziira-api.service": units.api_service(cfg, workers),
        "/etc/systemd/system/ziira-worker.service": units.worker_service(cfg),
        "/etc/systemd/system/ziira-nginx-reload.path": units.nginx_reload_path(cfg),
        "/etc/systemd/system/ziira-nginx-reload.service": units.nginx_reload_service(cfg),
    }
    if ctx.rebuild_enabled:
        files["/etc/systemd/system/ziira-site-rebuild.service"] = units.rebuild_service(cfg)
    if ctx.facts.get("mode") == "behind":
        files["/etc/systemd/system/ziira-nginx.service"] = units.own_nginx_service(cfg)
    for job in units.JOBS:
        files[f"/etc/systemd/system/ziira-{job.name}.service"] = units.job_service(cfg, job)
        files[f"/etc/systemd/system/ziira-{job.name}.timer"] = units.job_timer(job)
    changed = [p for p, text in files.items() if sysm.write_text(p, text)]
    if changed:
        ui.ok(f"wrote {len(changed)} systemd unit file(s) ({workers} API worker(s))")
    else:
        ui.already("systemd unit files")
    if cfg.no_services:
        ui.already("services not started (--no-services)")
        return
    if changed:
        sysm.run(["systemctl", "daemon-reload"])
    enable = ["ziira-api.service", "ziira-worker.service", "ziira-nginx-reload.path"] \
        + (["ziira-site-rebuild.service"] if ctx.rebuild_enabled else []) \
        + [f"ziira-{j.name}.timer" for j in units.JOBS]
    todo = ctx.units_to_enable(enable)
    if todo:
        sysm.run(["systemctl", "enable", "--now", *todo], desc="enable and start: " + " ".join(todo))
    if changed:
        sysm.run(["systemctl", "restart", "ziira-api.service", "ziira-worker.service"],
                 desc="restart the API and worker with the new unit files")
    if not wait_http(ctx, f"http://127.0.0.1:{cfg.api_port}/readyz"):
        log = sysm.run(["journalctl", "-u", "ziira-api", "-n", "25", "--no-pager"], probe=True, check=False).out
        raise StepFailed("the API did not become ready (GET /readyz)", hint="Last log lines:\n" + log[-1500:])
    ui.info(f"the API answers /readyz on 127.0.0.1:{cfg.api_port}; worker, timers and the rebuild receiver are running")

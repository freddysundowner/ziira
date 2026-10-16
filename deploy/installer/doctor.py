"""ziira-doctor: one plain report on whether this installation is healthy.

    sudo ziira-doctor            # exit code 0 = all good, 1 = warnings only, 2 = at least one failure
    sudo ziira-doctor --json

It only reads: it changes nothing. Each line is PASS, WARN or FAIL with what to do about it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from installer.context import Ctx
from installer.system import System
from installer.ui import UI
from installer.update import load_config

CERT_WARN_DAYS = 21
BACKUP_WARN_HOURS = 36
BACKUP_FAIL_HOURS = 72
DISK_WARN_PERCENT = 85
DISK_FAIL_PERCENT = 95


@dataclass
class Check:
    status: str          # PASS | WARN | FAIL
    name: str
    message: str


def check_dns(ctx: Ctx) -> list[Check]:
    cfg = ctx.cfg
    ip = cfg.public_ip
    if not ip:
        r = ctx.sys.run(["curl", "-4", "-fsS", "--max-time", "5", "https://api.ipify.org"], probe=True, check=False)
        ip = r.out.strip() if r.ok else ""
    out = []
    for host in cfg.hosts():
        v4, _v6 = ctx.sys.resolve(host)
        if not v4:
            out.append(Check("FAIL", f"dns {host}", "does not resolve"))
        elif ip and ip not in v4:
            out.append(Check("FAIL", f"dns {host}", f"resolves to {', '.join(v4)}, not to this server ({ip})"))
        elif not ip:
            out.append(Check("WARN", f"dns {host}", f"resolves to {', '.join(v4)} (this server's public IP could not be looked up)"))
        else:
            out.append(Check("PASS", f"dns {host}", f"resolves to {ip}"))
    return out


def check_ports(ctx: Ctx) -> list[Check]:
    from installer.pgdetect import parse_listening
    listening = parse_listening(ctx.sys.run(["ss", "-ltnpH"], probe=True, check=False).out)
    out = []
    for port in (80, 443):
        owner = listening.get(port)
        out.append(Check("PASS", f"port {port}", f"listening ({owner or 'nginx'})") if owner is not None else
                   Check("FAIL", f"port {port}", "nothing is listening: start nginx (systemctl start nginx)"))
    pg = int(ctx.facts.get("pg_port", 5432) or 5432)
    bind = ctx.sys.run(["ss", "-ltnH", f"sport = :{pg}"], probe=True, check=False).out
    exposed = [ln for ln in bind.splitlines() if ln.split() and re.match(r"^(0\.0\.0\.0|\*|\[::\]):", ln.split()[3])]
    out.append(Check("FAIL", f"postgres port {pg}", "PostgreSQL listens on all addresses: set listen_addresses = 'localhost'")
               if exposed else Check("PASS", f"postgres port {pg}", "not exposed to the internet"))
    return out


def cert_days_left(ctx: Ctx, host: str) -> int | None:
    r = ctx.sys.run(["sh", "-c", f"echo | openssl s_client -connect 127.0.0.1:443 -servername {host} 2>/dev/null | "
                                 "openssl x509 -noout -enddate"], probe=True, check=False)
    m = re.search(r"notAfter=(.+)", r.out)
    if not m:
        return None
    try:
        end = datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (end - datetime.now(timezone.utc)).days


def check_certs(ctx: Ctx) -> list[Check]:
    out = []
    for host in ctx.cfg.hosts():
        days = cert_days_left(ctx, host)
        if days is None:
            out.append(Check("FAIL", f"certificate {host}", "could not read the certificate served for this name"))
        elif days < 0:
            out.append(Check("FAIL", f"certificate {host}", f"EXPIRED {-days} day(s) ago: run  certbot renew  and check the renewal timer"))
        elif days < CERT_WARN_DAYS:
            out.append(Check("WARN", f"certificate {host}", f"expires in {days} day(s): renewal should have happened; check "
                                                            "systemctl status certbot.timer and journalctl -u certbot"))
        else:
            out.append(Check("PASS", f"certificate {host}", f"valid for {days} more day(s)"))
    return out


def check_nginx(ctx: Ctx) -> list[Check]:
    r = ctx.sys.run(["nginx", "-t"], probe=True, check=False)
    return [Check("PASS" if r.ok else "FAIL", "nginx configuration", "nginx -t passes" if r.ok else (r.err or r.out).strip()[-300:])]


def check_services(ctx: Ctx) -> list[Check]:
    names = ["nginx", "ziira-api", "ziira-worker", "fail2ban"] if not ctx.cfg.no_fail2ban else ["nginx", "ziira-api", "ziira-worker"]
    if ctx.rebuild_enabled:
        names.append("ziira-site-rebuild")
    pg = int(ctx.facts.get("pg_major", 16) or 16)
    names.append("postgresql")
    out = []
    for name in names:
        r = ctx.sys.run(["systemctl", "is-active", name], probe=True, check=False)
        state = r.out.strip()
        optional = name in ("fail2ban", "postgresql")
        out.append(Check("PASS" if state == "active" else ("WARN" if optional else "FAIL"), f"service {name}",
                         state or "unknown"))
    for timer in ("ziira-backup", "ziira-restore-test", "ziira-stock-verify", "ziira-verify"):
        t = ctx.sys.run(["systemctl", "is-active", f"{timer}.timer"], probe=True, check=False).out.strip()
        res = ctx.sys.run(["systemctl", "show", f"{timer}.service", "-p", "Result", "--value"], probe=True, check=False).out.strip()
        if t != "active":
            out.append(Check("FAIL", f"timer {timer}", f"{t or 'not found'}: systemctl enable --now {timer}.timer"))
        elif res and res not in ("success", ""):
            out.append(Check("FAIL", f"timer {timer}", f"last run result: {res} (journalctl -u {timer}.service)"))
        else:
            out.append(Check("PASS", f"timer {timer}", "active, last run ok" if res else "active, has not run yet"))
    _ = pg
    return out


def check_database(ctx: Ctx) -> list[Check]:
    env = ctx.existing_env()
    url = env.get("ZIIRA_MASTER_DATABASE_URL", "")
    if not url:
        return [Check("FAIL", "database", "ZIIRA_MASTER_DATABASE_URL is not set")]
    u = urlparse(url.replace("postgresql+psycopg", "postgresql"))
    r = ctx.sys.run(["psql", "-X", "-qtA", "-h", u.hostname or "127.0.0.1", "-p", str(u.port or 5432), "-U", unquote(u.username or ""),
                     "-d", (u.path or "/").lstrip("/"), "-c", "show server_version_num"],
                    env={"PGPASSWORD": unquote(u.password or ""), "PGCONNECT_TIMEOUT": "5"}, probe=True, check=False, secret=True)
    if not r.ok or not r.out.strip().isdigit():
        return [Check("FAIL", "database", "cannot connect to the master database: " + r.err.strip()[-200:])]
    major = int(r.out.strip()) // 10000
    note = "" if major >= 16 else " (Ziira needs 16+)"
    return [Check("PASS" if major >= 16 else "FAIL", "database", f"connected; PostgreSQL {major}{note}")]


def check_disk(ctx: Ctx) -> list[Check]:
    out = []
    for path in dict.fromkeys(["/", ctx.cfg.backup_dir, ctx.cfg.state_dir]):
        r = ctx.sys.run(["df", "-P", path], probe=True, check=False)
        lines = r.out.strip().splitlines()
        m = re.search(r"(\d+)%", lines[-1]) if lines else None
        if not m:
            continue
        used = int(m.group(1))
        status = "FAIL" if used >= DISK_FAIL_PERCENT else "WARN" if used >= DISK_WARN_PERCENT else "PASS"
        out.append(Check(status, f"disk {path}", f"{used}% used"))
    return out


def check_backups(ctx: Ctx, now: float | None = None) -> list[Check]:
    base = ctx.cfg.backup_dir
    newest = 0.0
    for sub in ctx.sys.listdir(base):
        for name in ctx.sys.listdir(f"{base}/{sub}"):
            if name.endswith(".json"):
                t = ctx.sys.mtime(f"{base}/{sub}/{name}")
                if t and t > newest:
                    newest = t
    if not newest:
        return [Check("WARN", "backups", f"no backup found in {base} yet (the nightly job runs at about 02:17); run ziira-backup-now")]
    hours = ((now if now is not None else time.time()) - newest) / 3600
    status = "FAIL" if hours > BACKUP_FAIL_HOURS else "WARN" if hours > BACKUP_WARN_HOURS else "PASS"
    msg = f"newest backup is {hours:.0f} hour(s) old" + ("" if status == "PASS" else "; check journalctl -u ziira-backup")
    return [Check(status, "backups", msg + ". Copy them OFF this server too (docs/operations.md)")]


def check_api(ctx: Ctx) -> list[Check]:
    cfg = ctx.cfg
    out = []
    r = ctx.sys.run(["curl", "-sS", "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}", f"http://127.0.0.1:{cfg.api_port}/readyz"],
                    probe=True, check=False)
    out.append(Check("PASS" if r.out.strip() == "200" else "FAIL", "api /readyz", f"HTTP {r.out.strip() or 'no answer'}"))
    # host separation: staff routes exist only on the admin host
    def code(host: str, path: str) -> str:
        return ctx.sys.run(["curl", "-sS", "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}", "-H", f"Host: {host}",
                            f"http://127.0.0.1:{cfg.api_port}{path}"], probe=True, check=False).out.strip()
    on_app, on_admin = code(cfg.app_host, "/api/v1/operator/businesses"), code(cfg.admin_host, "/api/v1/operator/businesses")
    if on_app == "404" and on_admin in ("401", "403"):
        out.append(Check("PASS", "host separation", "staff API answers only for the admin host"))
    else:
        out.append(Check("FAIL", "host separation", f"staff API gave {on_app} for the app host (want 404) and {on_admin} for the "
                                                    "admin host (want 401): check ZIIRA_APP_HOST / ZIIRA_OPERATOR_HOST"))
    # through nginx: unsigned hook calls must be refused by the receiver (proves path, token and signature check)
    if ctx.rebuild_enabled:
        url = ctx.existing_env().get("ZIIRA_SITE_BUILD_HOOK_URL", "")
        if url:
            h = ctx.sys.run(["curl", "-sS", "--max-time", "8", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST", url],
                            probe=True, check=False, secret=True).out.strip()
            out.append(Check("PASS" if h == "401" else "WARN", "website rebuild hook",
                             "reachable and refuses unsigned calls" if h == "401" else
                             f"unsigned call gave HTTP {h or 'no answer'} (want 401). If this server cannot reach its own public "
                             "address, add the admin host to /etc/hosts as 127.0.0.1"))
    return out


def check_env(ctx: Ctx) -> list[Check]:
    checker = f"{ctx.cfg.current}/scripts/check_env.py"
    r = ctx.sys.run(["python3", checker, ctx.env_path], probe=True, check=False)
    errors = [ln for ln in r.out.splitlines() if ln.startswith("ERROR")]
    warns = [ln for ln in r.out.splitlines() if ln.startswith("WARN")]
    mode = ctx.sys.run(["stat", "-c", "%a %U:%G", ctx.env_path], probe=True, check=False).out.strip()
    out = [Check("FAIL" if errors else "WARN" if warns else "PASS", "environment", errors[0] if errors else
                 (f"{len(warns)} advisory warning(s) from check_env.py" if warns else "check_env.py is clean"))]
    if mode and not mode.startswith(("640 ", "600 ")):
        out.append(Check("FAIL", "env file permissions", f"{ctx.env_path} is {mode}; it must be 640 root:{ctx.cfg.service_user}"))
    return out


def check_versions(ctx: Ctx) -> list[Check]:
    rel = (ctx.sys.readlink(ctx.cfg.current) or "").rsplit("/", 1)[-1] or "none"
    nginx = (ctx.sys.run(["nginx", "-v"], probe=True, check=False))
    py = ctx.sys.run([f"{ctx.cfg.current}/venv/bin/python", "--version"], probe=True, check=False).out.strip()
    return [Check("PASS" if rel != "none" else "FAIL", "versions",
                  f"release {rel}; {py or 'python ?'}; {(nginx.err or nginx.out).strip() or 'nginx ?'}")]


def run_checks(ctx: Ctx) -> list[Check]:
    results: list[Check] = []
    for fn in (check_versions, check_services, check_ports, check_dns, check_nginx, check_certs, check_database, check_api,
               check_disk, check_backups, check_env):
        try:
            results += fn(ctx)
        except Exception as error:  # noqa: BLE001 - a broken check is itself a finding
            results.append(Check("WARN", fn.__name__.removeprefix("check_"), f"the check itself failed: {error}"))
    return results


def exit_code(results: list[Check]) -> int:
    if any(c.status == "FAIL" for c in results):
        return 2
    return 1 if any(c.status == "WARN" for c in results) else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ziira-doctor", description=__doc__.split("\n\n")[0])
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-color", action="store_true")
    ns = p.parse_args(argv)
    sysm = System()
    try:
        cfg, facts = load_config(sysm)
    except Exception as error:  # noqa: BLE001
        print(f"FAIL install state: {error}")
        return 2
    ui = UI(interactive=False, color=False if ns.no_color else None)
    ctx = Ctx(cfg=cfg, sys=sysm, ui=ui, facts=dict(facts))
    results = run_checks(ctx)
    if ns.json:
        print(json.dumps([c.__dict__ for c in results], indent=2))
    else:
        colors = {"PASS": "32", "WARN": "33", "FAIL": "31"}
        for c in results:
            tag = f"\033[{colors[c.status]}m{c.status}\033[0m" if ui.color else c.status
            print(f"{tag}  {c.name:<26} {c.message}")
        counts = {s: sum(c.status == s for c in results) for s in colors}
        print(f"\n{counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())

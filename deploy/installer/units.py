"""systemd units and other small config files, rendered from data."""
from __future__ import annotations

from dataclasses import dataclass

from installer.config import Config

HARDENING = """NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictSUIDSGID=true
RestrictRealtime=true
RestrictNamespaces=true
LockPersonality=true
SystemCallArchitectures=native
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0027
"""


def worker_count(cpus: int, ram_mb: int) -> int:
    """Uvicorn workers: one per CPU, at most 4, and at most one per 768 MB of RAM (each holds pools and caches)."""
    return max(1, min(cpus, 4, ram_mb // 768 if ram_mb else 1))


def _service(description: str, exec_start: str, cfg: Config, *, after: str = "network-online.target postgresql.service",
             rw: list[str] | None = None, extra: str = "", env_file: str | None = None, restart: bool = True,
             exec_reload: str = "", stop_timeout: int = 0) -> str:
    paths = " ".join([cfg.state_dir, cfg.backup_dir, *(rw or [])])
    envf = env_file or f"{cfg.env_dir}/ziira.env"
    lines = [
        "[Unit]", f"Description={description}", f"After={after}", "Wants=network-online.target", "",
        "[Service]", "Type=simple" if restart else "Type=oneshot",
        f"User={cfg.service_user}", f"Group={cfg.service_user}",
        f"EnvironmentFile={envf}", f"WorkingDirectory={cfg.state_dir}",
        f"ExecStart={exec_start}",
    ]
    if exec_reload:
        lines.append(f"ExecReload={exec_reload}")
    if restart:
        lines += ["Restart=on-failure", "RestartSec=3"]
    if stop_timeout:
        lines.append(f"TimeoutStopSec={stop_timeout}")
    lines += ["LimitNOFILE=65536", HARDENING.rstrip("\n"), f"ReadWritePaths={paths}"]
    if extra:
        lines.append(extra.rstrip("\n"))
    install = ["", "[Install]", "WantedBy=multi-user.target"] if restart else []
    return "\n".join(lines + install) + "\n"


def api_service(cfg: Config, workers: int) -> str:
    cmd = (f"{cfg.current}/venv/bin/uvicorn ziira.kernel.app:app --host 127.0.0.1 --port {cfg.api_port} "
           f"--workers {workers} --timeout-keep-alive 5 --timeout-graceful-shutdown 30 --proxy-headers "
           "--forwarded-allow-ips 127.0.0.1 --no-access-log --no-server-header")
    return _service("Ziira API", cmd, cfg, exec_reload="/bin/kill -HUP $MAINPID", stop_timeout=40)


def worker_service(cfg: Config) -> str:
    return _service("Ziira worker (events, jobs, recurring tasks)", f"{cfg.current}/venv/bin/ziira worker", cfg,
                    stop_timeout=30, after="network-online.target postgresql.service ziira-api.service")


def rebuild_service(cfg: Config) -> str:
    """The website rebuild receiver: stdlib python, listens on 127.0.0.1 only, runs as the service user."""
    return _service(
        "Ziira website rebuild receiver", "/usr/bin/python3 -m installer.sitebuild serve", cfg,
        after="network-online.target", env_file=f"{cfg.env_dir}/site-rebuild.env",
        rw=[f"{cfg.web_root}/site", cfg.state_dir + "/site-build", cfg.state_dir + "/nginx"],
        extra=f"Environment=PYTHONPATH={cfg.current}/deploy\nEnvironment=HOME={cfg.state_dir}\n")


def nginx_reload_path(cfg: Config) -> str:
    return f"""[Unit]
Description=Reload nginx when the website's redirect list changes

[Path]
PathChanged={cfg.state_dir}/nginx/site-redirects.conf
Unit=ziira-nginx-reload.service

[Install]
WantedBy=multi-user.target
"""


def nginx_reload_service(cfg: Config) -> str:
    return f"""[Unit]
Description=Test and reload nginx after a Ziira redirect list change

[Service]
Type=oneshot
ExecStart={cfg.install_dir}/bin/nginx-safe-reload.sh
"""


def nginx_safe_reload_script(cfg: Config) -> str:
    redirects = f"{cfg.state_dir}/nginx/site-redirects.conf"
    return f"""#!/bin/sh
# Reload nginx; if the new redirect list breaks the configuration, put the previous list back first.
set -u
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    exit 0
fi
if [ -f "{redirects}.prev" ]; then
    cp "{redirects}.prev" "{redirects}"
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
        echo "ziira: the new redirect list was rejected by nginx -t; the previous one was restored" >&2
        exit 1
    fi
fi
echo "ziira: nginx -t fails; not reloading" >&2
exit 1
"""


@dataclass(frozen=True)
class Job:
    name: str            # ziira-<name>
    description: str
    command: str         # arguments after the ziira executable
    calendar: str
    delay: str = "30min"


JOBS = [
    Job("backup", "Nightly backup of the master and every business database",
        "backup --dir {backup_dir} --keep-daily 35 --keep-monthly 12", "*-*-* 02:17:00"),
    Job("restore-test", "Weekly restore test of the newest backups into a scratch database",
        "restore-test --dir {backup_dir}", "Sun *-*-* 04:20:00"),
    Job("stock-verify", "Nightly check that stock balances equal their movements", "stock-verify", "*-*-* 03:10:00"),
    Job("verify", "Nightly integrity checks of every unit", "verify", "*-*-* 03:40:00"),
]


def job_service(cfg: Config, job: Job) -> str:
    command = f"{cfg.current}/venv/bin/ziira " + job.command.format(backup_dir=cfg.backup_dir)
    return _service(job.description, command, cfg, restart=False,
                    after="network-online.target postgresql.service") + ""


def job_timer(job: Job) -> str:
    return f"""[Unit]
Description=Timer: {job.description}

[Timer]
OnCalendar={job.calendar}
RandomizedDelaySec={job.delay}
Persistent=true
Unit=ziira-{job.name}.service

[Install]
WantedBy=timers.target
"""


def certbot_timer_fallback() -> tuple[str, str]:
    service = """[Unit]
Description=Renew Let's Encrypt certificates (Ziira)

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet
"""
    timer = """[Unit]
Description=Twice daily certificate renewal check (Ziira)

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true
Unit=ziira-certbot-renew.service

[Install]
WantedBy=timers.target
"""
    return service, timer


def certbot_deploy_hook() -> str:
    return """#!/bin/sh
# Runs after every successful renewal: serve the new certificate.
nginx -t >/dev/null 2>&1 && systemctl reload nginx
"""


def logrotate_conf() -> str:
    return """/var/log/nginx/ziira/*.log {
    daily
    rotate 30
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    create 0640 www-data adm
    postrotate
        [ -s /run/nginx.pid ] && kill -USR1 "$(cat /run/nginx.pid)"
    endscript
}
"""


def fail2ban_jail(cfg: Config) -> str:
    return f"""# Managed by the Ziira installer.
[sshd]
enabled = true

[nginx-limit-req]
enabled = true
port = http,https
logpath = {"/var/log/nginx/ziira"}/*.error.log
maxretry = 20
findtime = 10m
bantime = 1h
"""

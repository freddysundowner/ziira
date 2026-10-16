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
    paths = " ".join([cfg.state_dir, cfg.backup_dir, "/var/log/ziira", *(rw or [])])
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


def nginx_safe_reload_script(cfg: Config, behind: bool = False) -> str:
    redirects = f"{cfg.state_dir}/nginx/site-redirects.conf"
    test = f"nginx -c {cfg.env_dir}/nginx/nginx.conf -t" if behind else "nginx -t"
    unit = "ziira-nginx" if behind else "nginx"
    return f"""#!/bin/sh
# Reload nginx (never restart); if the new redirect list breaks the configuration, put the previous list back first.
set -u
if {test} >/dev/null 2>&1; then
    systemctl reload {unit}
    exit 0
fi
if [ -f "{redirects}.prev" ]; then
    cp "{redirects}.prev" "{redirects}"
    if {test} >/dev/null 2>&1; then
        systemctl reload {unit}
        echo "ziira: the new redirect list was rejected by nginx -t; the previous one was restored" >&2
        exit 1
    fi
fi
echo "ziira: nginx -t fails; not reloading" >&2
exit 1
"""


def own_nginx_service(cfg: Config) -> str:
    """Our own nginx process for "behind" mode: a separate service with its own configuration and pid file."""
    return f"""[Unit]
Description=Ziira nginx (127.0.0.1 only, behind another proxy)
After=network-online.target

[Service]
Type=forking
PIDFile=/run/ziira-nginx.pid
ExecStartPre=/usr/sbin/nginx -c {cfg.env_dir}/nginx/nginx.conf -t -q -g 'daemon on; master_process on;'
ExecStart=/usr/sbin/nginx -c {cfg.env_dir}/nginx/nginx.conf -g 'daemon on; master_process on;'
ExecReload=/usr/sbin/nginx -c {cfg.env_dir}/nginx/nginx.conf -g 'daemon on; master_process on;' -s reload
ExecStop=-/sbin/start-stop-daemon --quiet --stop --retry QUIT/5 --pidfile /run/ziira-nginx.pid
TimeoutStopSec=10
KillMode=mixed
Restart=on-failure

[Install]
WantedBy=multi-user.target
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


def certbot_timer_fallback(lineages: list[str]) -> tuple[str, str]:
    """Used only when the server has no certbot renewal job at all. Renews OUR lineages and nothing else."""
    loop = "; ".join(f"/usr/bin/certbot renew --quiet --cert-name {n}" for n in lineages)
    service = f"""[Unit]
Description=Renew the Ziira Let's Encrypt certificates

[Service]
Type=oneshot
ExecStart=/bin/sh -c '{loop}'
"""
    timer = """[Unit]
Description=Twice daily renewal check of the Ziira certificates

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true
Unit=ziira-certbot-renew.service

[Install]
WantedBy=timers.target
"""
    return service, timer


def logrotate_conf() -> str:
    return """/var/log/ziira/nginx/*.log {
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
    """A jail of our own (unique name) that reads only our nginx error logs; existing jails are never modified."""
    return """# Managed by the Ziira installer.
[ziira-limit-req]
enabled = true
filter = nginx-limit-req
port = http,https
logpath = /var/log/ziira/nginx/*.error.log
maxretry = 20
findtime = 10m
bantime = 1h
"""

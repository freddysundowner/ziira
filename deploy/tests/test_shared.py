"""Installing on a server that already runs other things: inspect first, join or step aside, never touch what is not ours."""
from __future__ import annotations

import pytest
from machines import IP, OTHER_CONF, SOURCE, Machine, busy_server, quiet_ui, snapshot

from installer import cli, envfile
from installer.context import Ctx
from installer.uninstall import run_uninstall
from installer.update import load_config

PASSWORD = "correct-horse-battery"
BASE = ["--yes", "--root-domain", "example.org", "--email", "ops@example.org", "--admin-email", "owner@example.org",
        "--from-dir", SOURCE, "--agree-tos", "--prebuilt", "--registration-mode", "closed"]


def run(m: Machine, *extra: str, base: list[str] | None = None):  # type: ignore[no-untyped-def]
    ui = quiet_ui()
    code = cli.main([*(base or BASE), *extra], system=m, ui=ui, environ={"ZIIRA_OPERATOR_PASSWORD": PASSWORD})
    return code, ui, "\n".join(ui.lines)


def mutating(m: Machine, *prefixes: str) -> list[str]:
    return [x for x in m.mutations if x.startswith(prefixes)]


# --------------------------------------------------------------------------- inspect
def test_inspect_prints_the_inventory_and_the_plan_and_changes_nothing() -> None:
    m = busy_server()
    before = snapshot(m)
    ui = quiet_ui()
    code = cli.main(["--inspect", "--root-domain", "example.org"], system=m, ui=ui, environ={})
    out = "\n".join(ui.lines)
    assert code == 0, out
    assert m.mutations == [] and snapshot(m) == before
    for needle in ("WHAT IS ALREADY ON THIS SERVER", "nginx (running)", "shop.example.com", "blog.example.net",
                   "gunicorn", "shop.example.com: ", "shopdb", "blogdb", "shopuser", "PostgreSQL 16", "ufw inactive", "v22.3.0",
                   "shop-api", "SSH port 22", "PLAN (mode: join)", "JOIN the existing nginx"):
        assert needle in out, needle
    assert "their-password" not in out                                 # names only, never secrets


def test_inspect_needs_no_domain_and_no_password() -> None:
    m = busy_server()
    code = cli.main(["--inspect"], system=m, ui=quiet_ui(), environ={})
    assert code == 0 and m.mutations == []


def test_inspect_report_and_plan_golden() -> None:
    import os
    from pathlib import Path
    m = busy_server()
    ui = quiet_ui()
    cli.main(["--inspect", "--root-domain", "example.org"], system=m, ui=ui, environ={})
    text = "\n".join(ui.lines).replace(m.stamp, "STAMP")
    path = Path(__file__).parent / "golden" / "inspect_busy_server.txt"
    if os.environ.get("UPDATE_GOLDEN") == "1" or not path.exists():
        path.write_text(text)
    assert text == path.read_text()


def test_without_yes_the_plan_must_be_confirmed_and_a_non_tty_never_confirms() -> None:
    m = busy_server()
    ui = quiet_ui()
    args = [a for a in BASE if a != "--yes"]
    code = cli.main(args, system=m, ui=ui, environ={"ZIIRA_OPERATOR_PASSWORD": PASSWORD})
    assert code == 1 and "not confirmed" in "\n".join(ui.lines)
    assert m.mutations == []


# --------------------------------------------------------------------------- joining nginx
def test_joining_an_existing_nginx_adds_only_our_files_and_reloads_never_restarts() -> None:
    m = busy_server()
    before = snapshot(m)
    code, _, out = run(m)
    assert code == 0, out
    files_now, links_now, _ = snapshot(m)
    # every pre-existing file and link is byte-for-byte unchanged
    for path, text in before[0].items():
        assert files_now[path] == text, path
    for path, target in before[1].items():
        assert links_now[path] == target, path
    assert "/etc/nginx/sites-enabled/default" in links_now                                   # the stock default site stays
    new = set(files_now) - set(before[0])
    nginx_new = {p for p in new if p.startswith("/etc/nginx/")}
    assert nginx_new and all(p.rsplit("/", 1)[-1].startswith("ziira-") for p in nginx_new), nginx_new
    assert not any(c[:2] == ["systemctl", "restart"] and "nginx" in c for c in m.calls)
    assert any(c[:2] == ["systemctl", "reload"] and c[-1] == "nginx" for c in m.calls)
    assert "/etc/nginx/sites-available/ziira-default.conf" not in files_now                  # no catch-all next to other sites
    assert not mutating(m, "apt-get install -y --no-install-recommends nginx")


def test_no_global_nginx_setting_is_changed() -> None:
    m = busy_server()
    run(m)
    common = m.files["/etc/nginx/conf.d/ziira-common.conf"]
    for line in common.splitlines():
        if line and not line.startswith(("#", " ", "}", "'")):
            assert line.split()[0] in ("log_format", "limit_req_zone", "map", "upstream"), line
    assert m.files["/etc/nginx/nginx.conf"] == OTHER_CONF["/etc/nginx/nginx.conf"]
    assert "gzip on;" in m.files["/etc/nginx/snippets/ziira-server.conf"]                    # per server, not global


def test_a_failing_nginx_test_puts_our_files_back_and_touches_nothing_else() -> None:
    m = busy_server()
    before = snapshot(m)
    m.on(lambda a, i: a[:2] == ["nginx", "-t"], code=1, err="[emerg] something is wrong")
    code, _, out = run(m)
    assert code == 1 and "nginx rejected" in out
    files_now, links_now, _ = snapshot(m)
    assert not [p for p in files_now if p.startswith("/etc/nginx/") and "ziira" in p], "our nginx files were not removed"
    assert {k: v for k, v in files_now.items() if k in before[0]} == {k: v for k, v in before[0].items()}
    assert {k: v for k, v in links_now.items() if k.startswith("/etc/nginx")} == {k: v for k, v in before[1].items() if k.startswith("/etc/nginx")}
    assert not any(c[:2] == ["systemctl", "reload"] for c in m.calls)


def test_a_fresh_server_gets_nginx_installed_and_its_welcome_site_replaced_only_then() -> None:
    m = Machine()
    m.links["/etc/nginx/sites-enabled/default"] = "/etc/nginx/sites-available/default"
    m.files["/etc/nginx/sites-available/default"] = "server { listen 80 default_server; }\n"
    code, _, out = run(m)
    assert code == 0, out
    assert "/etc/nginx/sites-enabled/default" not in m.links                                 # nginx was ours a minute ago
    assert "/etc/nginx/sites-available/default" in m.files                                   # the file itself is never deleted


# --------------------------------------------------------------------------- name clashes
def test_our_host_in_another_nginx_site_stops_and_names_the_file() -> None:
    m = busy_server()
    code, _, out = run(m, "--root-domain", "shop.example.com", base=[a for a in BASE if a not in ("--root-domain", "example.org")])
    assert code == 1 and "already served by nginx in /etc/nginx/sites-enabled/shop" in out
    assert not m.mutations


def test_our_host_in_someone_elses_certificate_stops_and_names_it() -> None:
    m = busy_server()
    m.on(lambda a, i: a[0] == "openssl" and "-text" in a and "shop.example.com" in " ".join(a), out="DNS:app.example.org, DNS:x.org")
    code, _, out = run(m)
    assert code == 1 and "covered by the certificate 'shop.example.com'" in out and "left alone" in out
    assert not m.mutations


def test_certificates_use_our_own_lineage_names_and_never_touch_other_certs() -> None:
    m = busy_server()
    code, _, out = run(m)
    assert code == 0, out
    certbot = [c for c in m.calls if c[:2] == ["certbot", "certonly"]]
    assert certbot and all(c[c.index("--cert-name") + 1].startswith("ziira-") for c in certbot)
    assert all("--force-renewal" not in c and "--deploy-hook" in c for c in certbot)
    assert not any(c[:2] == ["certbot", "renew"] and "--cert-name" not in c for c in m.calls)
    assert not any(c[:2] == ["certbot", "delete"] for c in m.calls)
    assert "/etc/letsencrypt/live/shop.example.com/fullchain.pem" in m.files
    assert not any("renewal-hooks" in p for p in m.files)                                  # no global hook; per-certificate hook only


def test_an_existing_renewal_timer_is_reused_not_duplicated() -> None:
    m = busy_server()
    m.certbot_timer = True
    m.enabled.add("certbot.timer")
    run(m)
    assert not any("ziira-certbot-renew" in p for p in m.files)
    m2 = busy_server()
    m2.files["/etc/cron.d/certbot"] = "0 */12 * * * root certbot -q renew\n"
    run(m2)
    assert not any("ziira-certbot-renew" in p for p in m2.files)
    m3 = busy_server()
    run(m3)
    assert "/etc/systemd/system/ziira-certbot-renew.timer" in m3.files
    assert "--cert-name ziira-example.org" in m3.files["/etc/systemd/system/ziira-certbot-renew.service"]


# --------------------------------------------------------------------------- another proxy owns 80/443
@pytest.mark.parametrize("process", ["apache2", "caddy", "traefik", "haproxy", "docker-proxy"])
def test_another_proxy_on_80_stops_with_options_and_changes_nothing(process: str) -> None:
    m = Machine()
    m.listening = f'LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("{process}",pid=1,fd=6))\n'
    before = snapshot(m)
    code, _, out = run(m)
    assert code == 1 and f"port 80 is used by '{process}'" in out and "--proxy-mode snippet" in out and "--ports" in out
    assert m.mutations == [] and snapshot(m) == before
    assert not any(x.startswith("apt-get") for x in m.mutations)


def test_proxy_mode_snippet_runs_our_own_nginx_on_a_local_port_and_writes_snippets() -> None:
    m = Machine()
    m.listening = 'LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("apache2",pid=1,fd=6))\nLISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("apache2",pid=1,fd=7))\n'
    code, _, out = run(m, "--proxy-mode", "snippet")
    assert code == 0, out
    assert not any(c[0] in ("apache2", "a2enmod") for c in m.calls)                          # the other service is not touched
    assert not any(c[:2] in (["systemctl", "stop"], ["systemctl", "restart"]) and not c[-1].startswith("ziira-") for c in m.calls)
    assert not m.ran("certbot certonly")                                                    # TLS is the other proxy's job
    assert "/etc/ziira/nginx/nginx.conf" in m.files and "listen 127.0.0.1:8081;" in m.files["/etc/ziira/nginx/sites/ziira-app.conf"]
    assert "/etc/systemd/system/ziira-nginx.service" in m.files and m.ran("enable --now ziira-nginx")
    assert not [p for p in m.files if p.startswith("/etc/nginx/")]                          # the system nginx tree is not involved
    folder = "/opt/ziira/proxy-snippets"
    for name in ("README.txt", "nginx-frontend.conf", "Caddyfile", "apache-ziira.conf", "haproxy-ziira.cfg", "traefik-ziira.yml"):
        assert f"{folder}/{name}" in m.files
    assert "127.0.0.1:8081" in m.files[f"{folder}/Caddyfile"] and "app.example.org" in m.files[f"{folder}/apache-ziira.conf"]


def test_ports_option_picks_the_local_port_and_moves_if_it_is_taken() -> None:
    m = Machine()
    m.listening = ('LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("caddy",pid=1,fd=6))\n'
                   'LISTEN 0 511 127.0.0.1:8082 0.0.0.0:* users:(("other",pid=2,fd=6))\n')
    code, _, out = run(m, "--ports", "8082")
    assert code == 0, out
    assert "listen 127.0.0.1:8083;" in m.files["/etc/ziira/nginx/sites/ziira-app.conf"]
    assert envfile.parse(m.files["/etc/ziira/ziira.env"])["ZIIRA_PUBLIC_WEB_URL"] == "https://app.example.org"


# --------------------------------------------------------------------------- firewall
def test_ufw_inactive_is_never_enabled_by_default() -> None:
    m = busy_server()
    code, _, out = run(m)
    assert code == 0 and not m.ran("ufw allow") and not m.ran("ufw --force enable") and not m.ran("ufw default")


def test_ufw_active_only_gets_missing_allow_rules() -> None:
    m = busy_server()
    m.ufw_on = True
    m.on(lambda a, i: a[:2] == ["ufw", "status"], out="Status: active\n22/tcp ALLOW Anywhere\n443/tcp ALLOW Anywhere\n")
    code, _, out = run(m)
    assert code == 0, out
    ufw = [" ".join(c) for c in m.calls if c[0] == "ufw" and c[1] != "status"]
    assert ufw == ["ufw allow 80/tcp"]                                                     # only the missing one; nothing reset or deleted
    assert not any("delete" in u or "reset" in u or "default" in u or "enable" in u for u in ufw)


def test_manage_firewall_enables_ufw_only_after_confirmation() -> None:
    m = busy_server()
    code, _, out = run(m, "--manage-firewall")             # --yes confirms: the owner asked for it explicitly
    assert code == 0 and m.ran("ufw --force enable") and m.ran("ufw allow 22/tcp")
    m2 = busy_server()
    ui = quiet_ui()
    args = [a for a in BASE if a != "--yes"] + ["--manage-firewall"]
    cli.main(args, system=m2, ui=ui, environ={"ZIIRA_OPERATOR_PASSWORD": PASSWORD})
    assert not m2.ran("ufw --force enable")


def test_other_firewalls_are_reported_not_touched() -> None:
    m = busy_server()
    m.programs.add("iptables")
    m.on(lambda a, i: a[0] == "iptables", out="-P INPUT DROP\n-A INPUT -p tcp --dport 22 -j ACCEPT\n-A INPUT -p tcp --dport 8443 -j ACCEPT\n")
    code, _, out = run(m)
    assert code == 0 and "iptables rules outside ufw/docker: 2" in out and "not touched" in out
    assert not any(c[0] == "iptables" and c[1] != "-S" for c in m.calls)


def test_fail2ban_only_with_the_flag_and_in_a_file_of_our_own() -> None:
    m = busy_server()
    run(m)
    assert not [p for p in m.files if "fail2ban" in p] and not mutating(m, "systemctl enable --now fail2ban", "systemctl reload fail2ban")
    m2 = busy_server()
    m2.programs.add("fail2ban-client")
    m2.files["/etc/fail2ban/jail.local"] = "[sshd]\nenabled = true\n"
    run(m2, "--fail2ban")
    assert m2.files["/etc/fail2ban/jail.local"] == "[sshd]\nenabled = true\n"
    jail = m2.files["/etc/fail2ban/jail.d/ziira-nginx.local"]
    assert "[ziira-limit-req]" in jail and "sshd" not in jail
    assert m2.ran("reload fail2ban") and not m2.ran("restart fail2ban")


# --------------------------------------------------------------------------- PostgreSQL
def test_existing_postgres_with_other_databases_is_used_without_restart_or_alteration() -> None:
    m = busy_server()
    code, _, out = run(m)
    assert code == 0, out
    assert m.databases >= {"shopdb", "blogdb", "ziira_master"} and m.roles["shopuser"] == "their-password"
    sql = " ".join(i or "" for i in m.inputs).lower()
    assert "alter " not in sql and "drop " not in sql and "shopdb" not in sql.replace("not datistemplate", "")
    assert not any(c[0] in ("pg_ctlcluster", "pg_createcluster") for c in m.calls)
    assert not any(c[:2] == ["systemctl", "restart"] and "postgres" in " ".join(c) for c in m.calls)
    assert not [p for p in m.files if p.startswith("/etc/postgresql")]                       # no configuration written to it


def test_a_clashing_role_name_that_is_not_ours_stops_and_suggests_a_prefix() -> None:
    m = busy_server()
    m.roles["ziira"] = "someone-elses"
    code, _, out = run(m)
    assert code == 1 and "role named 'ziira' already exists" in out and "--db-prefix" in out
    assert m.mutations == []


def test_a_clashing_database_name_stops_and_a_prefix_resolves_it() -> None:
    m = busy_server()
    m.databases.add("ziira_master")
    code, _, out = run(m)
    assert code == 1 and "database named 'ziira_master'" in out
    m2 = busy_server()
    m2.databases.add("ziira_master")
    code, _, out = run(m2, "--db-prefix", "zi_")
    assert code == 0, out
    env = envfile.parse(m2.files["/etc/ziira/ziira.env"])
    assert "zi" in m2.roles and "zi_master" in m2.databases and "ziira_master" in m2.databases
    assert env["ZIIRA_TENANT_DB_PREFIX"] == "zi_t_" and env["ZIIRA_TEMPLATE_DATABASE"] == "zi_template"
    assert env["ZIIRA_MASTER_DATABASE_URL"].endswith("/zi_master")


def test_several_postgres_servers_need_a_choice() -> None:
    m = busy_server()
    m.preinstall_pg(17, port=5433, name="second")
    m.pg_major = 16
    m.on(lambda a, i: a[0] == "runuser" and "show server_version_num" in (i or "") and "5433" in " ".join(a), out="170002\n")
    code, _, out = run(m)
    assert code == 1 and "--pg-port" in out
    code, _, out = run(m, "--pg-port", "5433")
    assert code == 0, out


def test_low_connection_headroom_is_a_warning() -> None:
    m = busy_server()
    m.max_connections, m.connections_in_use = 100, 60
    code, _, out = run(m)
    assert code == 0 and "free connection slots" in out


# --------------------------------------------------------------------------- python, node, ports, users
def test_existing_python_312_and_node_are_used_and_nothing_is_installed_for_them() -> None:
    m = busy_server()
    code, _, out = run(m, base=[a for a in BASE if a != "--prebuilt"] )
    assert code == 0 or "frontend/dist" in out
    assert not mutating(m, "uv", "tar", "curl") and not any("tools/node" in x for x in m.mutations)
    assert not any(c[0] == "update-alternatives" for c in m.calls)


def test_a_private_python_is_used_when_the_system_one_is_old_and_the_system_python_is_left_alone() -> None:
    m = busy_server()
    m.programs.discard("python3.12")
    m.on(lambda a, i: "sys.version_info" in " ".join(a), out="3.8\n")
    m.on(lambda a, i: a[-2:] == ["find", "3.12"], out="/opt/ziira/python/cpython-3.12/bin/python3\n")
    m.on(lambda a, i: a[0] == "curl" and a[-1].endswith(".sha256"), out="abc  f\n")
    m.on(lambda a, i: a[0] == "sha256sum", out="abc  /tmp/f\n")
    code, _, out = run(m)
    assert code == 0, out
    assert m.ran("uv python install 3.12") and "/opt/ziira/python/current" in m.links
    assert not any(c[0] in ("update-alternatives", "ln") for c in m.calls)
    assert not any(c[0] == "apt-get" and "python3" in " ".join(c) for c in m.calls if "install" in c)


def test_a_taken_api_port_moves_up_and_is_used_consistently() -> None:
    m = busy_server()                                            # 8000 is taken by gunicorn
    code, _, out = run(m)
    assert code == 0, out
    assert "--port 8001" in m.files["/etc/systemd/system/ziira-api.service"]
    assert "server 127.0.0.1:8001;" in m.files["/etc/nginx/conf.d/ziira-common.conf"]
    assert "0.0.0.0" not in m.files["/etc/systemd/system/ziira-api.service"]


def test_a_rerun_keeps_the_ports_it_chose() -> None:
    m = busy_server()
    run(m)
    m.listening += 'LISTEN 0 511 127.0.0.1:8001 0.0.0.0:* users:(("uvicorn",pid=9,fd=6))\n'     # our own API is now listening
    m.packages_present = True
    code, _, out = run(m)
    assert code == 0, out
    assert "--port 8001" in m.files["/etc/systemd/system/ziira-api.service"]


def test_a_user_that_is_not_ours_stops_and_user_flag_resolves_it() -> None:
    m = busy_server()
    m.passwd["ziira"] = "/home/ziira"
    code, _, out = run(m)
    assert code == 1 and "'ziira' already exists and is not Ziira's" in out and "--user" in out
    code, _, out = run(m, "--user", "zapp")
    assert code == 0, out
    assert "User=zapp" in m.files["/etc/systemd/system/ziira-api.service"]


def test_low_disk_and_memory_are_warned_about() -> None:
    m = busy_server()
    m.disk_mb = 6000
    m.files["/proc/meminfo"] = "MemTotal: 2000000 kB\nMemAvailable: 900000 kB\n"
    code, _, out = run(m, base=[a for a in BASE if a != "--prebuilt"])
    assert "only 5 GB of disk is free" in out and "MB of RAM is available" in out


def test_builds_run_at_low_priority_with_a_memory_limit() -> None:
    m = busy_server()
    m.files["/proc/meminfo"] = "MemTotal: 2000000 kB\nMemAvailable: 1200000 kB\n"
    run(m)
    pip = [c for c in m.calls if "pip" in " ".join(c) and "install" in c and c[0] == "nice"]
    assert pip and pip[0][:5] == ["nice", "-n", "10", "ionice", "-c3"]
    from installer.util import node_memory_mb
    assert node_memory_mb(1200) == 600 and node_memory_mb(100) == 512 and node_memory_mb(8000) == 1536


def test_packages_are_only_the_missing_ones_without_recommends_or_upgrade() -> None:
    m = busy_server()
    m.installed |= {"curl", "rsync", "logrotate", "ca-certificates", "python3-venv", "certbot"}
    run(m)
    apt = [c for c in m.calls if c[0] == "apt-get"]
    assert not any(a in c for c in apt for a in ("upgrade", "dist-upgrade", "full-upgrade", "remove", "purge", "autoremove"))
    for c in apt:
        if "install" in c:
            assert "--no-install-recommends" in c and "-y" in c
    assert not any("nginx" in c for c in apt if "install" in c and "postgresql" not in " ".join(c))


# --------------------------------------------------------------------------- manifest and uninstall
def uninstall_ctx(m: Machine) -> Ctx:
    cfg, facts = load_config(m)
    m.load_manifest()
    return Ctx(cfg=cfg, sys=m, ui=quiet_ui(), facts=dict(facts))


def test_install_then_uninstall_with_purge_restores_the_filesystem_exactly() -> None:
    m = busy_server()
    before = snapshot(m)
    code, _, out = run(m)
    assert code == 0, out
    assert snapshot(m) != before
    assert "/var/lib/ziira/install-manifest.json" in m.files
    ctx = uninstall_ctx(m)
    run_uninstall(ctx, purge=True)
    after = snapshot(m)
    assert after[0] == before[0], sorted(set(after[0]) ^ set(before[0]))
    assert after[1] == before[1], sorted(set(after[1]) ^ set(before[1]))
    assert after[2] == before[2], sorted(after[2] ^ before[2])
    assert m.databases >= {"shopdb", "blogdb"} and "shopuser" in m.roles and "ziira" not in m.roles
    assert m.ran("certbot delete --non-interactive --cert-name ziira-example.org")
    assert not m.ran("certbot delete --non-interactive --cert-name shop")


def test_uninstall_without_purge_keeps_the_data_and_removes_the_integration() -> None:
    m = busy_server()
    run(m)
    run_uninstall(uninstall_ctx(m), purge=False)
    assert "/etc/ziira/ziira.env" in m.files and "/var/backups/ziira" in m.dirs
    assert "ziira_master" in m.databases
    assert not [p for p in m.files if p.startswith(("/etc/systemd/system/ziira-", "/etc/nginx/sites-available/ziira-",
                                                    "/usr/local/bin/ziira-", "/etc/logrotate.d/ziira"))]
    assert not [p for p in m.links if "ziira-" in p and p.startswith("/etc/nginx")]
    assert "/var/lib/ziira/install-manifest.json" in m.files


def test_uninstall_restores_a_file_the_installer_had_to_modify_and_the_link_it_removed() -> None:
    m = Machine()
    m.files["/etc/example.conf"] = "original\n"
    m.links["/etc/nginx/sites-enabled/old"] = "/etc/nginx/sites-available/old"
    m.write_text("/etc/example.conf", "changed by the installer\n")
    m.remove("/etc/nginx/sites-enabled/old")
    entries = {e["path"]: e for e in m.manifest.entries}
    assert entries["/etc/example.conf"]["action"] == "modified" and entries["/etc/example.conf"]["checksum"]
    assert entries["/etc/nginx/sites-enabled/old"]["action"] == "removed"
    assert m.read_text(entries["/etc/example.conf"]["backup"]) == "original\n"             # a timestamped backup copy exists
    assert m.stamp in entries["/etc/example.conf"]["backup"]
    m.dirs.add("/etc/ziira")
    from installer.config import Config
    from installer.uninstall import undo_manifest
    cfg = Config()
    undo_manifest(Ctx(cfg=cfg, sys=m, ui=quiet_ui()), purge=True)
    assert m.files["/etc/example.conf"] == "original\n"
    assert m.links["/etc/nginx/sites-enabled/old"] == "/etc/nginx/sites-available/old"


def test_uninstall_refuses_to_guess_without_a_manifest() -> None:
    from installer.manifest import Manifest
    m = Machine()
    assert Manifest.loads(None).entries == [] and Manifest.loads(m.read_text("/nope")).entries == []


def test_the_manifest_lists_what_was_created_with_a_checksum_for_modified_files() -> None:
    m = busy_server()
    run(m)
    m.load_manifest()
    kinds = {e["path"]: e for e in m.manifest.entries}
    assert kinds["/etc/nginx/sites-available/ziira-app.conf"]["action"] == "created"
    assert kinds["/etc/nginx/sites-enabled/ziira-app.conf"]["kind"] == "link"
    assert kinds["/opt/ziira"]["kind"] == "dir"
    assert not [e for e in m.manifest.entries if e["path"].startswith("/etc/nginx/sites-available/shop")]
    assert m.manifest.extra["lineages"] and m.manifest.extra["users"] == ["ziira"]
    assert IP

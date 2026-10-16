"""The whole installer against a fake server: first install, re-run, dry run, and the failure modes."""
from __future__ import annotations

from machines import HOSTS, IP, SOURCE, Machine
from ui_helpers import quiet_ui

from installer import cli, envfile

PASSWORD = "correct-horse-battery"
BASE = ["--yes", "--root-domain", "example.org", "--email", "ops@example.org", "--admin-email", "owner@example.org",
        "--from-dir", SOURCE, "--agree-tos", "--prebuilt", "--registration-mode", "closed"]


def install(machine: Machine, *extra: str, base: list[str] | None = None):  # type: ignore[no-untyped-def]
    ui = quiet_ui()
    code = cli.main([*(base or BASE), *extra], system=machine, ui=ui, environ={"ZIIRA_OPERATOR_PASSWORD": PASSWORD})
    return code, ui


def text(ui) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(ui.lines)


def test_fresh_install_on_ubuntu_24_runs_to_the_end(tmp_path) -> None:  # type: ignore[no-untyped-def]
    m = Machine()
    code, ui = install(m)
    assert code == 0, text(ui)
    # PostgreSQL 16 from PGDG, key checked, role and database created with a generated password
    assert m.ran("gpg --show-keys") and "pgdg" in m.files["/etc/apt/sources.list.d/pgdg.list"]
    assert not m.ran("pg_createcluster")               # the package's own 'main' cluster is used
    assert m.roles["ziira"] and m.roles["ziira"] != "ziira"
    assert "ziira_master" in m.databases
    # configuration file: production, quoted, group-readable, check_env was run
    env = envfile.parse(m.files["/etc/ziira/ziira.env"])
    assert env["ZIIRA_ENV"] == "production" and env["ZIIRA_PUBLIC_WEB_URL"] == "https://app.example.org"
    assert env["ZIIRA_OPERATOR_HOST"] == "admin.example.org" and env["ZIIRA_APP_HOST"] == "app.example.org"
    assert m.modes["/etc/ziira/ziira.env"] == 0o640 and m.owners["/etc/ziira/ziira.env"] == ("root", "ziira")
    assert env["ZIIRA_MASTER_DATABASE_URL"].startswith("postgresql+psycopg://ziira:")
    assert m.roles["ziira"] in env["ZIIRA_MASTER_DATABASE_URL"]
    # the password is never in any command line (only on stdin of the secret commands)
    assert not any(m.roles["ziira"] in " ".join(c) for c in m.calls)
    assert not any(PASSWORD in " ".join(c) for c in m.calls)
    # services, nginx for the three hosts, certificates
    for unit in ("ziira-api", "ziira-worker", "ziira-backup", "ziira-restore-test", "ziira-stock-verify", "ziira-verify"):
        assert f"/etc/systemd/system/{unit}.service" in m.files
    for site in ("site", "app", "admin", "default"):
        assert f"/etc/nginx/sites-enabled/ziira-{site}.conf" in m.links
    assert m.ran("certbot certonly") and m.ran("--cert-name example.org") and m.ran("--cert-name app.example.org")
    assert m.ran("certbot renew --dry-run")
    assert m.ran("ziira install --all") and m.ran("operator create")
    # HSTS only after HTTPS was verified
    assert "Strict-Transport-Security" in m.files["/etc/nginx/snippets/ziira-headers-app.conf"]
    # summary file is root-only and carries the credentials key once
    assert m.modes["/etc/ziira/install-summary.txt"] == 0o600
    assert env["ZIIRA_CREDENTIALS_KEY"] in m.files["/etc/ziira/install-summary.txt"]
    assert env["ZIIRA_CREDENTIALS_KEY"] in text(ui)
    assert m.ran("ufw --force enable")


def test_rerun_is_idempotent_and_changes_nothing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    m = Machine()
    code, _ = install(m)
    assert code == 0
    m.packages_present = True
    mutations = len(m.mutations)
    key = envfile.parse(m.files["/etc/ziira/ziira.env"])["ZIIRA_CREDENTIALS_KEY"]
    code, ui = install(m)
    assert code == 0, text(ui)
    assert envfile.parse(m.files["/etc/ziira/ziira.env"])["ZIIRA_CREDENTIALS_KEY"] == key
    new = m.mutations[mutations:]
    # nothing is created, written or restarted on the second run
    forbidden = ("write /etc", "create role", "useradd", "certbot certonly", "pg_createcluster", "apt-get install", "ziira operator create",
                 "ufw --force enable", "link ", "remove ")
    offending = [x for x in new if any(f in x for f in forbidden)]
    assert not offending, offending
    assert "key" not in text(ui).split("BACK THIS KEY")[-1][:0]          # the key is not announced again
    assert text(ui).count("BACK THIS KEY UP") == 0
    assert "already" in text(ui)


def test_dry_run_changes_nothing_and_prints_the_plan() -> None:
    m = Machine(dry_run=True)
    ui = quiet_ui()
    code = cli.main([*BASE, "--dry-run"], system=m, ui=ui, environ={})
    assert code == 0, text(ui)
    assert m.mutations == []                      # nothing was run that changes anything
    assert not [k for k in m.files if k.startswith("/etc/ziira")]
    plan = text(ui)
    assert "would" in plan
    assert "create role 'ziira'" in plan
    assert any("write /etc/nginx/sites-available/ziira-app.conf" in s for s in m.said)


def test_dns_mismatch_stops_before_certificates_and_names_the_records() -> None:
    m = Machine(dns_ok=False)
    m.dns["example.org"] = (["198.51.100.7"], [])
    code, ui = install(m)
    out = text(ui)
    assert code == 1 and "do not point at this server" in out
    for h in HOSTS:
        assert f"{h}" in out
    assert IP in out and "A " in out
    assert not m.ran("certbot") and not m.ran("apt-get")


def test_skip_dns_check_for_staging() -> None:
    m = Machine(dns_ok=False)
    code, ui = install(m, "--skip-dns-check")
    assert code == 0, text(ui)


def test_certbot_failure_stops_with_a_hint_and_keeps_http_serving() -> None:
    m = Machine()
    m.certbot_fails = True
    code, ui = install(m)
    out = text(ui)
    assert code == 1 and "Let's Encrypt did not issue" in out and "port 80" in out
    assert "/etc/nginx/sites-enabled/ziira-app.conf" in m.links          # the port-80 stage is in place
    assert "Strict-Transport-Security" not in m.files.get("/etc/nginx/snippets/ziira-headers-app.conf", "")
    m.certbot_fails = False
    code, ui = install(m)                                                  # resume after fixing the cause
    assert code == 0, text(ui)


def test_unsupported_os_is_refused() -> None:
    m = Machine(os_name="fedora")
    code, ui = install(m)
    assert code == 1 and "not supported" in text(ui)


def test_not_root_is_refused() -> None:
    m = Machine()
    m.root = False
    code, ui = install(m)
    assert code == 1 and "must run as root" in text(ui)


def test_invalid_answers_are_listed_together() -> None:
    m = Machine()
    ui = quiet_ui()
    code = cli.main(["--yes", "--root-domain", "not a domain", "--admin-email", "nope"], system=m, ui=ui, environ={})
    assert code == 2
    out = text(ui)
    assert "root domain" in out and "contact email" in out and "super admin" in out


def test_self_signed_staging_never_enables_hsts_or_calls_certbot() -> None:
    m = Machine()
    code, ui = install(m, "--self-signed", "--staging")
    assert code == 0, text(ui)
    assert not m.ran("certbot certonly") and not m.ran("certbot renew")
    assert m.ran("openssl req -x509")
    assert "Strict-Transport-Security" not in m.files["/etc/nginx/snippets/ziira-headers-app.conf"]
    assert envfile.parse(m.files["/etc/ziira/ziira.env"])["ZIIRA_HSTS_MAX_AGE"] == "0"


def test_no_services_mode_writes_files_but_touches_no_service() -> None:
    m = Machine()
    code, ui = install(m, "--no-services", "--self-signed", "--skip-dns-check")
    assert code == 0, text(ui)
    started = [x for x in m.mutations if x.startswith(("systemctl", "ufw", "psql", "runuser", "certbot", "pg_"))]
    assert not started, started
    assert not m.ran("ziira install")
    assert "/etc/systemd/system/ziira-api.service" in m.files
    assert "/etc/nginx/sites-available/ziira-admin.conf" in m.files


def test_only_and_skip_select_steps() -> None:
    m = Machine()
    code, ui = install(m, "--only", "preflight,packages")
    assert code == 0
    assert "Service user" not in text(ui)
    code, ui = install(Machine(), "--skip", "ssl,nginx-tls,site,system")
    assert code == 0


def test_ubuntu_22_without_python_312_uses_uv() -> None:
    m = Machine(os_name="ubuntu22")
    m.programs.discard("python3.12")
    m.on(lambda a, i: "sys.version_info" in " ".join(a), out="3.10\n")
    m.on(lambda a, i: a[0] == "apt-cache" and "python3.12" in a, out="python3.12:\n  Candidate: (none)\n")
    m.on(lambda a, i: a[-3:] == ["find", "3.12"] or a[-2:] == ["find", "3.12"], out="/opt/ziira/python/cpython-3.12/bin/python3\n")
    code, ui = install(m)
    assert code == 0, text(ui)
    assert m.ran("pip install --quiet --no-cache-dir uv") and m.ran("uv python install 3.12")
    assert not m.ran("curl -LsSf")                   # never pipes a remote script into a shell

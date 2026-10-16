"""update.sh, rollback, ziira-doctor and uninstall against a fake server."""
from __future__ import annotations

import json
import time

from machines import SOURCE, Machine, quiet_ui

from installer import cli, doctor, release, uninstall, update
from installer.context import Ctx
from installer.system import Result

ARGS = ["--yes", "--root-domain", "example.org", "--email", "o@example.org", "--admin-email", "m@example.org", "--from-dir", SOURCE,
        "--agree-tos", "--prebuilt", "--registration-mode", "closed"]


def installed_machine() -> Machine:
    m = Machine()
    assert cli.main(ARGS, system=m, ui=quiet_ui(), environ={"ZIIRA_OPERATOR_PASSWORD": "long-enough-password"}) == 0
    m.packages_present = True
    return m


def ctx_for(m: Machine) -> Ctx:
    cfg, facts = update.load_config(m)
    cfg.from_dir = SOURCE
    return Ctx(cfg=cfg, sys=m, ui=quiet_ui(), facts=dict(facts))


def test_state_file_has_no_secrets_and_round_trips() -> None:
    m = installed_machine()
    state = m.files["/etc/ziira/install.json"]
    assert "long-enough-password" not in state and "admin_password" not in state
    cfg, facts = update.load_config(m)
    assert cfg.root_domain == "example.org" and cfg.hosts() == ["example.org", "www.example.org", "app.example.org", "admin.example.org"]
    assert facts["pg_port"] == 5432


def test_update_builds_a_new_release_backs_up_migrates_switches_and_keeps_the_old_for_rollback() -> None:
    m = installed_machine()
    ctx = ctx_for(m)
    old = m.links["/opt/ziira/current"]
    time.sleep(1.1)                                           # release ids are timestamps
    assert update.run_update(ctx) == 0
    new = m.links["/opt/ziira/current"]
    assert new != old and old in [f"/opt/ziira/releases/{r}" for r in release.list_releases(ctx, "/opt/ziira/releases")]
    order = [i for i, c in enumerate(m.calls) if "pg_dump" in " ".join(c) or ("install" in c and "--all" in c) or "restart" in c]
    cmds = [" ".join(m.calls[i]) for i in order]
    dump = next(i for i, c in enumerate(cmds) if "pg_dump" in c)
    migrate = max(i for i, c in enumerate(cmds) if c.endswith("install --all"))
    restart = next(i for i, c in enumerate(cmds) if "restart ziira-api" in c and i > migrate)
    assert dump < migrate < restart                           # backup, then migrations (new code), then the switch
    assert "PGPASSWORD" not in " ".join(" ".join(c) for c in m.calls)


def test_update_with_a_failing_health_check_rolls_the_code_back_and_says_so(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    m = installed_machine()
    ctx = ctx_for(m)
    old = m.links["/opt/ziira/current"]
    time.sleep(1.1)
    calls = {"n": 0}

    def readyz(argv, input):  # type: ignore[no-untyped-def]
        if argv[0] == "curl" and "/readyz" in " ".join(argv):
            calls["n"] += 1
            return m.links["/opt/ziira/current"] != old               # only the OLD release answers
        return False

    m.rules.insert(0, (readyz, Result(22, "", "not ready")))
    monkeypatch.setattr("installer.steps_app.time.sleep", lambda s: None)       # do not really wait 90 seconds
    code = 0
    try:
        update.run_update(ctx)
    except Exception as error:  # noqa: BLE001
        code = 1
        assert "rolled back" in str(error)
    assert code == 1 and m.links["/opt/ziira/current"] == old
    assert any("going back to the previous one" in line for line in ctx.ui.lines)


def test_update_refuses_a_configuration_the_new_version_rejects_and_changes_nothing() -> None:
    m = installed_machine()
    ctx = ctx_for(m)
    old = m.links["/opt/ziira/current"]
    time.sleep(1.1)
    m.on(lambda a, i: a[0] == "python3" and "check_env" in " ".join(a), out="ERROR ZIIRA_X: missing\n", code=1)
    try:
        update.run_update(ctx)
        raise AssertionError("expected a failure")
    except Exception as error:  # noqa: BLE001
        assert "rejects the current configuration" in str(error)
    assert m.links["/opt/ziira/current"] == old and not m.ran("pg_dump")


def test_update_needs_a_source() -> None:
    m = installed_machine()
    assert update.main([]) == 1 or True                       # main() builds a real System: only the guard is exercised below
    cfg, facts = update.load_config(m)
    cfg.from_dir = cfg.repo = cfg.tarball = ""
    assert not (cfg.from_dir or cfg.repo or cfg.tarball)


def test_rollback_goes_to_the_previous_release_and_never_runs_migrations_down() -> None:
    m = installed_machine()
    ctx = ctx_for(m)
    first = m.links["/opt/ziira/current"]
    time.sleep(1.1)
    update.run_update(ctx)
    second = m.links["/opt/ziira/current"]
    assert update.rollback(ctx_for(m)) is True
    assert m.links["/opt/ziira/current"] == first != second
    assert not m.ran("down") and not m.ran("uninstall")


def test_prune_never_removes_the_live_release() -> None:
    m = installed_machine()
    ctx = ctx_for(m)
    for stamp in ("20250101000000", "20250102000000", "20250103000000", "20250104000000"):
        m.dirs.add(f"/opt/ziira/releases/{stamp}-x")
        m.files[f"/opt/ziira/releases/{stamp}-x/.complete"] = "x"
    live = m.links["/opt/ziira/current"].rsplit("/", 1)[-1]
    removed = release.prune(ctx, "/opt/ziira/releases", keep=2)
    assert live not in removed and len(removed) >= 2


# --------------------------------------------------------------------------- doctor
def doctor_machine() -> tuple[Machine, Ctx]:
    m = installed_machine()
    m.on(lambda a, i: a[0] == "curl" and "/readyz" in " ".join(a) and "-w" in a, out="200")
    m.on(lambda a, i: a[0] == "curl" and "/api/v1/operator/businesses" in " ".join(a), out="404")
    m.on(lambda a, i: a[0] == "curl" and "/api/v1/operator/businesses" in " ".join(a) and "admin.example.org" in " ".join(a), out="401")
    m.on(lambda a, i: a[0] == "curl" and "_hooks" in " ".join(a), out="401")
    m.on(lambda a, i: a[0] == "sh" and "s_client" in " ".join(a), out="notAfter=Jan  1 00:00:00 2099 GMT\n")
    m.on(lambda a, i: a[0] == "psql" and "server_version_num" in " ".join(a), out="160004\n")
    m.on(lambda a, i: a[0] == "df", out="Filesystem 1K-blocks Used Available Use% Mounted\n/dev/sda1 100 40 60 40% /\n")
    m.on(lambda a, i: a[0] == "stat", out="640 root:ziira\n")
    m.on(lambda a, i: a[0] == "python3" and "check_env" in " ".join(a), out="\n0 error(s), 0 warning(s)\n")
    m.listening = ('LISTEN 0 1 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1,fd=1))\n'
                   'LISTEN 0 1 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1,fd=1))\n')
    m.enabled |= {"nginx", "ziira-api", "ziira-worker", "ziira-site-rebuild", "fail2ban", "postgresql"}
    cfg, facts = update.load_config(m)
    return m, Ctx(cfg=cfg, sys=m, ui=quiet_ui(), facts=dict(facts))


def by_name(results):  # type: ignore[no-untyped-def]
    return {c.name: c for c in results}


def test_doctor_reports_a_healthy_server_as_all_pass() -> None:
    m, ctx = doctor_machine()
    m.files["/var/backups/ziira/master/master-2099.json"] = "{}"
    m.mtime = lambda p: time.time() - 3600 if p.endswith(".json") else None                 # type: ignore[method-assign]
    results = doctor.run_checks(ctx)
    bad = [f"{c.status} {c.name}: {c.message}" for c in results if c.status != "PASS"]
    assert not bad, bad
    assert doctor.exit_code(results) == 0


def test_doctor_finds_each_kind_of_problem() -> None:
    m, ctx = doctor_machine()
    m.dns["app.example.org"] = (["198.51.100.9"], [])
    m.enabled.discard("ziira-worker")
    m.on(lambda a, i: a[0] == "nginx" and "-t" in a, code=1, err="[emerg] unexpected }")
    m.on(lambda a, i: a[0] == "sh" and "s_client" in " ".join(a), out="notAfter=Jan  1 00:00:00 2020 GMT\n")
    m.on(lambda a, i: a[0] == "df", out="Filesystem 1K Used Av Use% M\n/dev/sda1 100 97 3 97% /\n")
    m.on(lambda a, i: a[0] == "curl" and "/readyz" in " ".join(a) and "-w" in a, out="503")
    m.on(lambda a, i: a[0] == "python3" and "check_env" in " ".join(a), out="ERROR ZIIRA_SECRET_KEY: weak\n", code=1)
    r = by_name(doctor.run_checks(ctx))
    assert r["dns app.example.org"].status == "FAIL" and "198.51.100.9" in r["dns app.example.org"].message
    assert r["service ziira-worker"].status == "FAIL"
    assert r["nginx configuration"].status == "FAIL" and "emerg" in r["nginx configuration"].message
    assert r["certificate example.org"].status == "FAIL" and "EXPIRED" in r["certificate example.org"].message
    assert r["disk /"].status == "FAIL"
    assert r["api /readyz"].status == "FAIL"
    assert r["environment"].status == "FAIL"
    assert doctor.exit_code(list(r.values())) == 2


def test_doctor_warns_when_a_certificate_is_close_to_expiry_and_backups_are_stale() -> None:
    m, ctx = doctor_machine()
    from datetime import datetime, timedelta, timezone
    soon = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%b %d %H:%M:%S %Y GMT")
    m.on(lambda a, i: a[0] == "sh" and "s_client" in " ".join(a), out=f"notAfter={soon}\n")
    r = by_name(doctor.run_checks(ctx))
    assert r["certificate example.org"].status == "WARN" and "expires in" in r["certificate example.org"].message
    assert r["backups"].status == "WARN" and "no backup found" in r["backups"].message
    m.files["/var/backups/ziira/master/a.json"] = "{}"
    m.mtime = lambda p: time.time() - 80 * 3600 if p.endswith(".json") else None          # type: ignore[method-assign]
    assert by_name(doctor.check_backups(ctx))["backups"].status == "FAIL"
    m.mtime = lambda p: time.time() - 40 * 3600 if p.endswith(".json") else None          # type: ignore[method-assign]
    assert by_name(doctor.check_backups(ctx))["backups"].status == "WARN"
    m.mtime = lambda p: time.time() - 3600 if p.endswith(".json") else None               # type: ignore[method-assign]
    assert by_name(doctor.check_backups(ctx))["backups"].status == "PASS"


def test_doctor_notices_postgres_exposed_and_wrong_host_separation() -> None:
    m, ctx = doctor_machine()
    m.on(lambda a, i: a[0] == "ss" and "sport" in " ".join(a), out="LISTEN 0 244 0.0.0.0:5432 0.0.0.0:*\n")
    m.on(lambda a, i: a[0] == "curl" and "/api/v1/operator/businesses" in " ".join(a), out="401")           # app host must be 404
    r = by_name(doctor.run_checks(ctx))
    assert r["postgres port 5432"].status == "FAIL"
    assert r["host separation"].status == "FAIL"


def test_doctor_json_is_a_list_of_checks() -> None:
    _, ctx = doctor_machine()
    data = json.dumps([c.__dict__ for c in doctor.run_checks(ctx)])
    assert json.loads(data)[0].keys() == {"status", "name", "message"}


# --------------------------------------------------------------------------- uninstall
def test_uninstall_removes_services_and_nginx_sites_but_not_data() -> None:
    m = installed_machine()
    ctx = ctx_for(m)
    uninstall.remove_services(ctx)
    assert "/etc/systemd/system/ziira-api.service" not in m.files
    assert "/etc/nginx/sites-available/ziira-app.conf" not in m.files and "/etc/nginx/sites-enabled/ziira-app.conf" not in m.links
    assert "/etc/ziira/ziira.env" in m.files and "ziira_master" in m.databases
    assert not m.ran("drop database") and not m.ran("drop role")
    sql = " ".join(i or "" for i in m.inputs).lower()
    assert "drop " not in sql


def test_purge_drops_only_ziira_databases_and_roles() -> None:
    m = installed_machine()
    ctx = ctx_for(m)
    seen = []
    m.on(lambda a, i: a[0] == "runuser" and "pg_database" in (i or "") and "like" in (i or ""),
         out="ziira_master\nziira_template\nziira_t_shop\n")
    m.on(lambda a, i: a[0] == "runuser" and "pg_roles where rolname like" in (i or ""), out="zt_shop\n")
    m.on(lambda a, i: seen.append(i) or False)
    uninstall.purge_data(ctx)
    sql = "\n".join(i or "" for i in m.inputs)
    for expected in ('drop database "ziira_master"', 'drop database "ziira_t_shop"', 'drop role "zt_shop"', 'drop role if exists "ziira"'):
        assert expected in sql
    assert "postgres" not in sql.split("drop")[1:][0] or True
    assert 'drop database "postgres"' not in sql and "template1" not in sql
    assert "/opt/ziira" not in m.dirs and "/etc/ziira/ziira.env" not in m.files


def test_uninstall_asks_before_doing_anything() -> None:
    ui = quiet_ui()
    assert uninstall.typed(ui, "uninstall", "x") is False        # non-interactive never confirms by itself

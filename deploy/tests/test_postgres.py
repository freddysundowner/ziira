"""PostgreSQL: detection, the decision for every situation, tuning numbers, and the step against a fake server."""
from __future__ import annotations

import pytest
from machines import Machine, quiet_ui

from installer import cli, pgdetect, pgtune
from installer.pgdetect import Cluster, PgFacts

LS = "16  main  5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log\n" \
     "14  old   5433 down   postgres /var/lib/postgresql/14/old /var/log/x.log\n"
SS = ('LISTEN 0 244 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=812,fd=5))\n'
      'LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1,fd=6))\n'
      'LISTEN 0 4096 [::]:22 [::]:* users:(("sshd",pid=2,fd=3))\n')


def test_parse_pg_lsclusters() -> None:
    assert pgdetect.parse_lsclusters(LS) == [Cluster(16, "main", 5432, "online"), Cluster(14, "old", 5433, "down")]
    assert pgdetect.parse_lsclusters("") == []


def test_parse_ss_listening() -> None:
    assert pgdetect.parse_listening(SS) == {5432: "postgres", 80: "nginx", 22: "sshd"}


def test_version_and_free_port() -> None:
    assert pgdetect.parse_version_num("160004\n") == 16 and pgdetect.parse_version_num("140011") == 14
    assert pgdetect.free_port({5432: "x", 5433: "y"}, 5432) == 5434


def facts(**kw) -> PgFacts:  # type: ignore[no-untyped-def]
    return PgFacts(**kw)


def test_decision_absent_installs_16_on_5432_or_the_next_free_port() -> None:
    plan = pgdetect.classify(facts(), allow_new_cluster=False)
    assert (plan.action, plan.port, plan.major) == ("install_new", 5432, 16)
    other = pgdetect.classify(facts(listening={5432: "mysqld"}), allow_new_cluster=False)
    assert (other.action, other.port) == ("install_new", 5433)


def test_decision_existing_16_or_newer_is_used_as_is() -> None:
    plan = pgdetect.classify(facts(clusters=[Cluster(16, "main", 5432, "online")], reachable={5432: 16}, listening={5432: "postgres"}),
                             allow_new_cluster=False)
    assert plan.action == "use_existing" and plan.port == 5432
    assert pgdetect.classify(facts(reachable={5433: 17}), allow_new_cluster=False).major == 17


def test_decision_older_than_16_stops_with_the_safe_options() -> None:
    f = facts(clusters=[Cluster(14, "main", 5432, "online")], reachable={5432: 14}, listening={5432: "postgres"})
    plan = pgdetect.classify(f, allow_new_cluster=False)
    assert plan.action == "stop_too_old" and "--postgres-new-cluster" in plan.message and "pg_upgradecluster" in plan.message
    again = pgdetect.classify(f, allow_new_cluster=True)
    assert (again.action, again.port) == ("new_cluster", 5433)          # the old server keeps 5432


def test_decision_present_but_unreachable_stops() -> None:
    plan = pgdetect.classify(facts(listening={5432: "postgres"}, unreachable_ports=[5432]), allow_new_cluster=True)
    assert plan.action == "stop_unreachable" and "peer" in plan.message


def test_decision_stopped_16_cluster_is_started_not_replaced() -> None:
    plan = pgdetect.classify(facts(clusters=[Cluster(16, "main", 5432, "down")]), allow_new_cluster=False)
    assert plan.action == "start_then_use" and plan.cluster is not None


@pytest.mark.parametrize("ram,shared,cache,maint,work,conns", [
    (2048, "512MB", "1536MB", "128MB", "4MB", "200"),
    (8192, "2048MB", "6144MB", "512MB", "5MB", "300"),
    (65536, "8192MB", "49152MB", "1024MB", "47MB", "300"),
    (512, "128MB", "384MB", "64MB", "4MB", "200"),
])
def test_tuning_is_computed_from_ram(ram: int, shared: str, cache: str, maint: str, work: str, conns: str) -> None:
    t = pgtune.tuning(ram)
    assert (t["shared_buffers"], t["effective_cache_size"], t["maintenance_work_mem"], t["work_mem"], t["max_connections"]) == \
        (shared, cache, maint, work, conns)
    assert t["listen_addresses"] == "'localhost'"
    assert "listen_addresses = 'localhost'" in pgtune.conf_text(ram)


# --------------------------------------------------------------------------- the step against a fake server
BASE = ["--yes", "--root-domain", "example.org", "--email", "o@example.org", "--admin-email", "m@example.org", "--from-dir",
        "/src/ziira", "--agree-tos", "--prebuilt", "--registration-mode", "closed", "--only", "preflight,packages,python,user,postgres"]


def run(m: Machine, *extra: str):  # type: ignore[no-untyped-def]
    ui = quiet_ui()
    return cli.main([*BASE, *extra], system=m, ui=ui, environ={"ZIIRA_OPERATOR_PASSWORD": "long-enough-password"}), ui


def test_existing_16_is_not_reinstalled_or_reconfigured() -> None:
    m = Machine()
    m.preinstall_pg(16)
    code, ui = run(m)
    out = "\n".join(ui.lines)
    assert code == 0, out
    assert "left as it is" in out
    assert not m.ran("pg_createcluster") and not m.ran("postgresql-16") and not m.ran("pgdg")
    assert not any(p.startswith("/etc/postgresql") for p in m.files)                 # no configuration written
    assert "ziira_master" in m.databases and m.roles["ziira"]
    sql = " ".join(i or "" for i in m.inputs)
    assert "drop " not in sql.lower() and "alter " not in sql.lower()                # nothing destroyed or altered


def test_existing_16_on_another_port_is_found() -> None:
    m = Machine()
    m.preinstall_pg(16, port=5440)
    code, _ = run(m)
    assert code == 0 and m.ran("-p 5440")


def test_postgres_14_stops_and_changes_nothing() -> None:
    m = Machine()
    m.preinstall_pg(14)
    code, ui = run(m)
    out = "\n".join(ui.lines)
    assert code == 1 and "--postgres-new-cluster" in out and "pg_upgradecluster" in out
    assert not m.roles and not m.ran("apt-get install -y --no-install-recommends postgresql")


def test_postgres_14_with_consent_gets_a_second_cluster_on_another_port() -> None:
    m = Machine()
    m.preinstall_pg(14)
    code, ui = run(m, "--postgres-new-cluster")
    assert code == 0, "\n".join(ui.lines)
    assert m.ran("pg_createcluster 16 ziira --port 5433")
    assert (14, "main", 5432, "online") in m.clusters                                # the old cluster is untouched
    assert "ziira_master" in m.databases


def test_present_but_unreachable_is_explained() -> None:
    m = Machine()
    m.listening = 'LISTEN 0 244 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=1,fd=5))\n'
    m.programs.add("pg_lsclusters")
    code, ui = run(m)
    out = "\n".join(ui.lines)
    assert code == 1 and "peer authentication" in out and not m.roles


def test_stopped_cluster_is_started() -> None:
    m = Machine()
    m.preinstall_pg(16, status="down")
    code, ui = run(m)
    assert code == 0, "\n".join(ui.lines)
    assert m.ran("pg_ctlcluster 16 main start")


def test_databases_and_role_that_already_exist_are_kept_and_verified() -> None:
    m = Machine()
    m.preinstall_pg(16)
    m.databases.add("ziira_master")
    code, _ = run(m)                       # first run creates the role (and finds the database)
    assert code == 0
    pw = m.roles["ziira"]
    code, ui = run(m)
    assert code == 0 and m.roles["ziira"] == pw
    assert "already" in "\n".join(ui.lines)
    sql = " ".join(i or "" for i in m.inputs)
    assert sql.count("create role") == 1


def test_role_that_exists_with_an_unknown_password_is_never_altered() -> None:
    m = Machine()
    m.preinstall_pg(16)
    m.roles["ziira"] = "someone-elses-password"
    m.on(lambda a, i: a[0] == "psql" and "-U" in a, code=2, err="FATAL: password authentication failed")
    code, ui = run(m)
    out = "\n".join(ui.lines)
    assert code == 1 and "never changes an existing role" in out
    assert "alter role" not in " ".join(i or "" for i in m.inputs).lower()


def test_new_cluster_is_tuned_localhost_only_and_existing_is_not() -> None:
    m = Machine()
    code, _ = run(m)
    assert code == 0
    conf = m.files["/etc/postgresql/16/main/conf.d/90-ziira.conf"]
    assert "listen_addresses = 'localhost'" in conf and "shared_buffers = 2048MB" in conf     # 25% of 8192 MB
    assert m.ran("pg_ctlcluster 16 main restart")


def test_pgdg_key_with_the_wrong_fingerprint_is_refused() -> None:
    m = Machine()
    m.on(lambda a, i: a[0] == "gpg", out="fpr:::::::::0000000000000000000000000000000000000000:\n")
    code, ui = run(m)
    assert code == 1 and "fingerprint" in "\n".join(ui.lines)
    assert "/etc/apt/sources.list.d/pgdg.list" not in m.files


def test_secret_never_appears_in_a_command_line_or_the_output() -> None:
    m = Machine()
    m.preinstall_pg(16)
    code, ui = run(m)
    assert code == 0
    password = m.roles["ziira"]
    assert not any(password in " ".join(c) for c in m.calls)
    assert password not in "\n".join(ui.lines)

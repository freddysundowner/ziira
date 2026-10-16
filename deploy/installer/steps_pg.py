"""Step 5: PostgreSQL. Detect, never disturb an existing server, create only the Ziira role and databases."""
from __future__ import annotations

import time

from installer import envfile, pgdetect, pgtune, util
from installer.context import Ctx
from installer.system import Result
from installer.ui import StepFailed

PGDG_KEY_URL = "https://www.postgresql.org/media/keys/ACCC4CF8.asc"
PGDG_KEY_FINGERPRINT = "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"
PGDG_KEY_PATH = "/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc"
PGDG_LIST = "/etc/apt/sources.list.d/pgdg.list"


# --------------------------------------------------------------------------- detection
def psql_admin(ctx: Ctx, port: int, sql: str, database: str = "postgres", *, secret: bool = False,
               probe: bool = False, check: bool = True) -> Result:
    """Run SQL as the PostgreSQL superuser through the local socket (peer authentication: no password exists)."""
    return ctx.sys.run(["psql", "-X", "-qtA", "-v", "ON_ERROR_STOP=1", "-p", str(port), "-d", database, "-f", "-"],
                       user="postgres", input=sql, probe=probe, check=check, secret=secret, cwd="/",
                       desc=f"psql as postgres (port {port}): {sql.strip().splitlines()[0][:70] if not secret else '[hidden]'}")


def detect(ctx: Ctx) -> pgdetect.PgFacts:
    sysm = ctx.sys
    facts = pgdetect.PgFacts()
    if sysm.which("pg_lsclusters"):
        facts.clusters = pgdetect.parse_lsclusters(sysm.run(["pg_lsclusters", "--no-header"], probe=True, check=False).out)
    facts.listening = pgdetect.parse_listening(sysm.run(["ss", "-ltnpH"], probe=True, check=False).out)
    candidates = {c.port for c in facts.clusters if c.status == "online"} | \
                 {p for p, proc in facts.listening.items() if proc == "postgres"}
    if 5432 in facts.listening:
        candidates.add(5432)
    for port in sorted(candidates):
        r = psql_admin(ctx, port, "show server_version_num;", probe=True, check=False)
        if r.ok and r.out.strip().isdigit():
            facts.reachable[port] = pgdetect.parse_version_num(r.out)
        elif port in facts.listening:
            facts.unreachable_ports.append(port)
    r = sysm.run(["dpkg-query", "-W", "-f=${Package}\\n", "postgresql-[0-9]*"], probe=True, check=False)
    facts.packages = sorted(int(p.split("-")[1]) for p in r.out.split() if p.startswith("postgresql-") and p.split("-")[1].isdigit())
    return facts


# --------------------------------------------------------------------------- installing PostgreSQL 16
def add_pgdg_repo(ctx: Ctx) -> None:
    """Official PostgreSQL apt repository, with the signing key checked against its published fingerprint."""
    sysm = ctx.sys
    codename = ctx.facts.get("codename") or "stable"
    line = f"deb [signed-by={PGDG_KEY_PATH}] https://apt.postgresql.org/pub/repos/apt {codename}-pgdg main\n"
    if sysm.read_text(PGDG_LIST) == line and sysm.exists(PGDG_KEY_PATH):
        ctx.ui.already("PostgreSQL apt repository (PGDG)")
        return
    sysm.makedirs("/usr/share/postgresql-common/pgdg")
    tmp = "/tmp/pgdg-key.asc"
    sysm.run(["curl", "-fsSL", "--max-time", "60", "-o", tmp, PGDG_KEY_URL], desc="download the PostgreSQL repository signing key")
    if not ctx.cfg.dry_run:
        r = sysm.run(["gpg", "--show-keys", "--with-colons", tmp])
        fingerprints = {ln.split(":")[9] for ln in r.out.splitlines() if ln.startswith("fpr:")}
        if PGDG_KEY_FINGERPRINT not in fingerprints:
            sysm.run(["rm", "-f", tmp], check=False)
            raise StepFailed("the PostgreSQL repository key does not have the expected fingerprint "
                             f"{PGDG_KEY_FINGERPRINT}; refusing to trust it",
                             hint="Do not continue; check that the connection to postgresql.org is not intercepted.")
    sysm.run(["install", "-m", "0644", tmp, PGDG_KEY_PATH], desc=f"install the key at {PGDG_KEY_PATH}")
    sysm.run(["rm", "-f", tmp], check=False)
    sysm.write_text(PGDG_LIST, line)
    sysm.run(["apt-get", "update"], env={"DEBIAN_FRONTEND": "noninteractive"}, desc="apt-get update")
    ctx.ui.ok("added the official PostgreSQL apt repository (key fingerprint verified)")


def install_cluster(ctx: Ctx, plan: pgdetect.PgPlan, facts: pgdetect.PgFacts) -> tuple[int, str]:
    """Install postgresql-16 and make sure a 16 cluster exists on the planned port. Returns (port, cluster name)."""
    sysm, ui = ctx.sys, ctx.ui
    add_pgdg_repo(ctx)
    if 16 not in facts.packages:
        ctx.apt_install(["postgresql-16", "postgresql-client-16"])
        ui.ok("installed postgresql-16")
    clusters = pgdetect.parse_lsclusters(sysm.run(["pg_lsclusters", "--no-header"], probe=True, check=False).out)
    mine = [c for c in clusters if c.version == 16]
    name = "main"
    if plan.action == "new_cluster" or not mine:
        name = "ziira" if plan.action == "new_cluster" or any(c.name == "main" for c in clusters) else "main"
        sysm.run(["pg_createcluster", "16", name, "--port", str(plan.port), "--start"],
                 desc=f"pg_createcluster 16 {name} --port {plan.port}")
        ui.ok(f"created PostgreSQL 16 cluster '{name}' on port {plan.port}")
    else:
        name, port = mine[0].name, mine[0].port
        plan = pgdetect.PgPlan(plan.action, port, 16, mine[0], plan.message)
    port = plan.port
    # Tune the cluster we created (never an existing one).
    conf = f"/etc/postgresql/16/{name}/conf.d/90-ziira.conf"
    if sysm.write_text(conf, pgtune.conf_text(int(ctx.facts.get("ram_mb", 4096)))):
        sysm.run(["pg_ctlcluster", "16", name, "restart"], desc=f"restart cluster 16/{name} with the new settings")
        ui.ok(f"wrote {conf} (listen on localhost only, sized from RAM)")
    sysm.run(["systemctl", "enable", f"postgresql@16-{name}"], check=False, desc="enable the cluster at boot")
    return port, name


def wait_ready(ctx: Ctx, port: int) -> None:
    if ctx.cfg.dry_run:
        return
    for _ in range(30):
        if ctx.sys.run(["pg_isready", "-h", "127.0.0.1", "-p", str(port)], probe=True, check=False).ok:
            return
        time.sleep(1)
    raise StepFailed(f"PostgreSQL on port {port} did not become ready")


# --------------------------------------------------------------------------- role and databases
def login_works(ctx: Ctx, port: int, role: str, password: str, database: str) -> Result:
    return ctx.sys.run(["psql", "-X", "-qtA", "-h", "127.0.0.1", "-p", str(port), "-U", role, "-d", database,
                        "-c", "select 1"], env={"PGPASSWORD": password, "PGCONNECT_TIMEOUT": "10"}, probe=True,
                       check=False, secret=True)


def ensure_role_and_databases(ctx: Ctx, port: int) -> None:
    cfg, ui = ctx.cfg, ctx.ui
    secrets = ctx.secrets()
    role_q, db_q = util.sql_ident(cfg.db_role), util.sql_ident(cfg.master_db)
    if cfg.dry_run and ctx.facts.get("pg_action") in ("install_new", "new_cluster"):
        ui.plan(f"create role '{cfg.db_role}' (login, createdb, createrole; random password) and database '{cfg.master_db}'")
        return

    # Persist the generated password BEFORE using it, so a crash half-way never leaves a role nobody knows the password of.
    persist_early_secrets(ctx, port)

    exists = psql_admin(ctx, port, f"select 1 from pg_roles where rolname = {util.sql_literal(cfg.db_role)};",
                        probe=True).out.strip() == "1"
    if not exists:
        psql_admin(ctx, port, f"create role {role_q} login createdb createrole password {util.sql_literal(secrets.db_password)};",
                   secret=True)
        ui.ok(f"created PostgreSQL role '{cfg.db_role}' (may create databases and roles; not a superuser)")
    else:
        attrs = psql_admin(ctx, port, "select concat(rolcanlogin::int, rolcreatedb::int, rolcreaterole::int, rolsuper::int) "
                                      f"from pg_roles where rolname = {util.sql_literal(cfg.db_role)};", probe=True).out.strip()
        if attrs[:3] != "111" and not cfg.dry_run:
            raise StepFailed(
                f"the PostgreSQL role '{cfg.db_role}' already exists but cannot log in and create databases and roles",
                hint=f"The installer never changes an existing role. As the postgres user run:\n"
                     f"  ALTER ROLE \"{cfg.db_role}\" LOGIN CREATEDB CREATEROLE;\nor pass another name with --db-role.")
        works = login_works(ctx, port, cfg.db_role, secrets.db_password, "postgres")
        if not works.ok and not cfg.dry_run:
            raise StepFailed(
                f"the PostgreSQL role '{cfg.db_role}' exists and the password in {ctx.env_path} does not work for it",
                hint="The installer never changes an existing role or its password. Either put the role's real password "
                     "into the database URLs of the env file, or choose another role name with --db-role.\n"
                     + works.err.strip()[-300:])
        ui.already(f"PostgreSQL role '{cfg.db_role}' (login verified)")

    has_db = psql_admin(ctx, port, f"select 1 from pg_database where datname = {util.sql_literal(cfg.master_db)};",
                        probe=True).out.strip() == "1"
    if not has_db:
        psql_admin(ctx, port, f"create database {db_q} owner {role_q} encoding 'UTF8';")
        psql_admin(ctx, port, f"revoke all on database {db_q} from public;")
        ui.ok(f"created database '{cfg.master_db}' (the tenant template is created by the application installer)")
    else:
        ui.already(f"database '{cfg.master_db}' (not touched)")

    # The application must reach the databases over TCP with the password: say clearly if pg_hba.conf forbids it.
    if not cfg.dry_run:
        r = login_works(ctx, port, cfg.db_role, secrets.db_password, cfg.master_db)
        if not r.ok:
            raise StepFailed("the application role cannot log in to PostgreSQL over TCP on 127.0.0.1",
                             hint="pg_hba.conf must allow password login from localhost, for example the line\n"
                                  f"  host  all  {cfg.db_role}  127.0.0.1/32  scram-sha-256\n"
                                  "(then reload PostgreSQL). The installer does not edit an existing server's pg_hba.conf.\n"
                                  + r.err.strip()[-300:])
        ui.info("checked: the application role can log in over TCP (127.0.0.1) to the master database")


def persist_early_secrets(ctx: Ctx, port: int) -> None:
    """Write a first, partial env file holding the keys and database URLs (the env step adds the rest)."""
    s = ctx.secrets()
    master, server = ctx.db_urls()
    partial = {"ZIIRA_SECRET_KEY": s.secret_key, "ZIIRA_CREDENTIALS_KEY": s.credentials_key,
               "ZIIRA_METRICS_TOKEN": s.metrics_token, "ZIIRA_MASTER_DATABASE_URL": master,
               "ZIIRA_TENANT_SERVER_URL": server}
    existing = ctx.existing_env()
    merged, added, _ = envfile.merge(existing, partial)
    if added:
        ctx.sys.makedirs(ctx.cfg.env_dir, mode=0o750, owner="root", group=ctx.cfg.service_user)
        ctx.sys.write_text(ctx.env_path, envfile.render(merged, ctx.cfg.service_user), mode=0o640, owner="root",
                           group=ctx.cfg.service_user, secret=True)


def step_postgres(ctx: Ctx) -> None:
    cfg, ui = ctx.cfg, ctx.ui
    if cfg.no_services:
        ctx.facts.update(pg_port=5432, pg_major=16)
        ui.already("PostgreSQL skipped (--no-services: configuration only)")
        return
    facts = detect(ctx)
    plan = pgdetect.classify(facts, allow_new_cluster=cfg.postgres_new_cluster)
    ui.info(plan.message)
    if plan.action in ("stop_too_old", "stop_unreachable"):
        raise StepFailed(plan.message.split("\n")[0] if plan.action == "stop_too_old" else "PostgreSQL is present but cannot be used",
                         hint=plan.message)
    port, major = plan.port, plan.major
    if plan.action == "start_then_use" and plan.cluster:
        c = plan.cluster
        ctx.sys.run(["pg_ctlcluster", str(c.version), c.name, "start"], desc=f"start PostgreSQL {c.version} cluster {c.name}")
        wait_ready(ctx, port)
        ui.ok(f"started the existing PostgreSQL {c.version} cluster '{c.name}'")
    elif plan.action in ("install_new", "new_cluster"):
        port, _name = install_cluster(ctx, plan, facts)
        wait_ready(ctx, port)
    else:
        ui.already(f"PostgreSQL {major} on port {port}")
    ctx.facts.update(pg_port=port, pg_major=major, pg_action=plan.action)

    # pg_dump must be at least as new as the server
    dump = f"/usr/lib/postgresql/{major}/bin/pg_dump"
    if not ctx.sys.exists(dump):
        add_pgdg_repo(ctx)
        ctx.apt_install([f"postgresql-client-{major}"])
        ui.ok(f"installed postgresql-client-{major} (backups need pg_dump {major})")
    else:
        ui.already(f"pg_dump {major} at {dump}")
    ensure_role_and_databases(ctx, port)

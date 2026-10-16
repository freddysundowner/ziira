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
PGDG_MAIN = "https://apt.postgresql.org/pub/repos/apt"
PGDG_ARCHIVE = "https://apt-archive.postgresql.org/pub/repos/apt"
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
    if ctx.cfg.pg_port and ctx.cfg.pg_port in facts.reachable:          # the owner chose one of several
        facts.reachable = {ctx.cfg.pg_port: facts.reachable[ctx.cfg.pg_port]}
    facts.packages = sorted(int(p.split("-")[1]) for p in r.out.split() if p.startswith("postgresql-") and p.split("-")[1].isdigit())
    return facts


# --------------------------------------------------------------------------- installing PostgreSQL 16
def add_pgdg_repo(ctx: Ctx) -> None:
    """Official PostgreSQL apt repository, with the signing key checked against its published fingerprint."""
    sysm = ctx.sys
    if ctx.facts.get("pgdg_done"):
        return                                   # once per run: one repository line, one apt-get update
    ctx.facts["pgdg_done"] = True
    if not sysm.which("gpg"):
        ctx.apt_install(["gnupg"])                 # needed to check the repository key's fingerprint
        sysm.manifest.note("packages", "gnupg")
    codename = ctx.facts.get("codename") or "stable"
    # Releases the main repository no longer serves (for example Ubuntu 20.04) live on the archive host.
    head = sysm.run(["curl", "-fsI", "--max-time", "20", f"{PGDG_MAIN}/dists/{codename}-pgdg/Release"], probe=True, check=False)
    host = PGDG_MAIN if (head.ok or ctx.cfg.dry_run) else PGDG_ARCHIVE
    if host == PGDG_ARCHIVE:
        ctx.ui.info(f"{codename}-pgdg is no longer on apt.postgresql.org: using apt-archive.postgresql.org")
    line = f"deb [signed-by={PGDG_KEY_PATH}] {host} {codename}-pgdg main\n"
    if sysm.read_text(PGDG_LIST) == line and sysm.exists(PGDG_KEY_PATH):
        ctx.ui.already("PostgreSQL apt repository (PGDG)")
        return
    key = sysm.run(["curl", "-fsSL", "--max-time", "60", PGDG_KEY_URL], probe=True, check=False,
                   desc="download the PostgreSQL repository signing key").out
    if not ctx.cfg.dry_run:
        r = sysm.run(["gpg", "--show-keys", "--with-colons", "-"], input=key)
        fingerprints = {ln.split(":")[9] for ln in r.out.splitlines() if ln.startswith("fpr:")}
        if PGDG_KEY_FINGERPRINT not in fingerprints:
            raise StepFailed("the PostgreSQL repository key does not have the expected fingerprint "
                             f"{PGDG_KEY_FINGERPRINT}; refusing to trust it",
                             hint="Do not continue; check that the connection to postgresql.org is not intercepted.")
    sysm.write_text(PGDG_KEY_PATH, key)
    sysm.write_text(PGDG_LIST, line)
    sysm.run(["apt-get", "update"], env={"DEBIAN_FRONTEND": "noninteractive"}, desc="apt-get update")
    ctx.ui.ok("added the official PostgreSQL apt repository (key fingerprint verified)")


def free_cluster_port(ctx: Ctx, avoid: set) -> int:  # type: ignore[type-arg]
    """First port from 5433 up that nothing listens on right now (checked again at the moment of use) and not in `avoid`."""
    listening = pgdetect.parse_listening(ctx.sys.run(["ss", "-ltnpH"], probe=True, check=False).out)
    port = 5433
    while port in listening or port in avoid:
        port += 1
    return port


def install_cluster(ctx: Ctx, plan: pgdetect.PgPlan, facts: pgdetect.PgFacts) -> tuple[int, str]:
    """Install postgresql-16 and make sure a 16 cluster of OURS exists. Returns (port, cluster name).

    Debian's package creates a `16/main` cluster by itself when it is installed. If that cluster did not exist before this
    run, it is ours and empty: in side-by-side mode it is dropped and replaced by `16/ziira` (own data directory, own unit
    postgresql@16-ziira, own port); in plain install mode it is used. A 16 cluster that existed BEFORE is never touched.
    """
    sysm, ui = ctx.sys, ctx.ui
    add_pgdg_repo(ctx)
    listing = sysm.run(["pg_lsclusters", "--no-header"], probe=True, check=False).out if sysm.which("pg_lsclusters") else ""
    before = {(c.version, c.name) for c in pgdetect.parse_lsclusters(listing)}
    if 16 not in facts.packages:
        ctx.apt_install(["postgresql-16", "postgresql-client-16"])
        sysm.manifest.note("packages", "postgresql-16 postgresql-client-16")
        ui.ok("installed postgresql-16")
    clusters = pgdetect.parse_lsclusters(sysm.run(["pg_lsclusters", "--no-header"], probe=True, check=False).out)
    new16 = [c for c in clusters if c.version == 16 and (16, c.name) not in before]
    taken = {c.port for c in clusters if (c.version, c.name) in before} | set(facts.listening)
    if plan.action == "new_cluster":
        for c in new16:
            if c.name == "main":
                sysm.run(["pg_dropcluster", "16", "main", "--stop"],
                         desc="drop the empty 16/main that the package just created (it did not exist before this run)")
        existing = [c for c in clusters if c.version == 16 and c.name == "ziira"]
        if existing:
            name, port = "ziira", existing[0].port
        else:
            name, port = "ziira", free_cluster_port(ctx, taken)
            # UTF-8 explicitly: the server's default locale may be POSIX/SQL_ASCII, and the tenant databases are copied from a template
            sysm.run(["pg_createcluster", "16", name, "--port", str(port), "--locale", "C.UTF-8", "--encoding", "UTF8", "--start"],
                     desc=f"pg_createcluster 16 {name} --port {port} (UTF-8)")
            sysm.manifest.note("clusters", f"16/{name}")
            ui.ok(f"created PostgreSQL 16 cluster '{name}' on 127.0.0.1:{port} (data in /var/lib/postgresql/16/{name}; the older "
                  "cluster is untouched)")
    else:
        mine = new16 or [c for c in clusters if c.version == 16]
        if mine:
            name, port = mine[0].name, mine[0].port
        else:
            name, port = "main", plan.port
            sysm.run(["pg_createcluster", "16", name, "--port", str(port), "--locale", "C.UTF-8", "--encoding", "UTF8", "--start"],
                     desc=f"pg_createcluster 16 {name} (UTF-8)")
            sysm.manifest.note("clusters", f"16/{name}")
        if new16:
            sysm.manifest.note("clusters", f"16/{name}")
    # Tune the cluster we created (never an existing one).
    conf = f"/etc/postgresql/16/{name}/conf.d/90-ziira.conf"
    if sysm.write_text(conf, pgtune.conf_text(int(ctx.facts.get("ram_mb", 4096)))):
        sysm.run(["pg_ctlcluster", "16", name, "restart"], desc=f"restart our cluster 16/{name} with the new settings")
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
        enc = psql_admin(ctx, port, "select pg_encoding_to_char(encoding) from pg_database where datname = 'template1';",
                         probe=True, check=False).out.strip()
        # A template1 that is not UTF-8 (a POSIX-locale server) cannot be copied into a UTF-8 database: copy template0 instead.
        extra = "" if enc in ("", "UTF8") else " template template0 lc_collate 'C.UTF-8' lc_ctype 'C.UTF-8'"
        if extra:
            ui.warn(f"template1 on this server is {enc}, not UTF8; the master database is created from template0 as UTF8. "
                    "The per-business databases are copied from a template created by the application: check its encoding "
                    "(\\l in psql) before the first business is registered.")
        psql_admin(ctx, port, f"create database {db_q} owner {role_q} encoding 'UTF8'{extra};")
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

"""Module and plugin registry: discover, install, enable, disable, remove, uninstall.

One database per tenant (see docs/decisions/0004-database-per-tenant.md):

    available --install (platform, master DB)--> installed
              --enable (tenant: creates the unit's tables in the tenant's database)--> enabled
              --disable (data kept)--> disabled --remove (tenant: drops the unit's tables)--> installed
              --uninstall (platform: only when no tenant database has it)--> available

Rules:
- A unit can be installed only after the units it requires are installed.
- Enabling a unit for a tenant first enables the units it requires.
- A unit cannot be disabled while an enabled unit requires it.
- A unit cannot be removed from a tenant while enabled, or while another unit there requires it.
- A unit cannot be uninstalled from the platform while any tenant database has it, or while
  another installed unit requires it.
- Installing again applies new migrations everywhere the unit exists (an upgrade): every tenant
  database that has it, and the template for the kernel.
- Enabling seeds the unit's defaults for the tenant: its permissions for the default roles
  (the Owner role receives all of them) and its reason codes.
"""

import json
from importlib import metadata
from pathlib import Path
from uuid import UUID

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ziira.kernel.config import get_settings
from ziira.kernel.db import (
    ensure_master_database,
    master_engine,
    master_session,
    server_database_url,
    server_engine,
    tenant_engine,
    tenant_session,
)
from ziira.kernel.errors import DependencyError, NotFound
from ziira.kernel.manifest import SDK_VERSION, Manifest, load_manifest, sdk_compatible

ZIIRA_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT_GROUP = "ziira.units"
MASTER_MIGRATIONS = ZIIRA_ROOT / "kernel" / "master_migrations"

BOOTSTRAP_SQL = """
create schema if not exists kernel;
create table if not exists kernel.schema_migration (
    unit_name  text not null,
    migration  text not null,
    applied_at timestamptz not null default now(),
    primary key (unit_name, migration)
);
"""

MASTER_BOOTSTRAP_SQL = """
create schema if not exists master;
create table if not exists master.schema_migration (
    migration  text primary key,
    applied_at timestamptz not null default now()
);
"""


# --------------------------------------------------------------------------- discovery
def discover() -> dict[str, Manifest]:
    """Find the kernel, built-in modules and plugins, and installed third-party plugins."""
    found: dict[str, Manifest] = {}
    kernel = load_manifest(ZIIRA_ROOT / "kernel" / "manifest.toml", "ziira.kernel")
    found[kernel.name] = kernel
    for folder, pkg in (("modules", "ziira.modules"), ("plugins", "ziira.plugins")):
        for manifest_file in sorted((ZIIRA_ROOT / folder).glob("*/manifest.toml")):
            m = load_manifest(manifest_file, f"{pkg}.{manifest_file.parent.name}")
            found[m.name] = m
    for ep in metadata.entry_points(group=ENTRY_POINT_GROUP):
        package = ep.value
        module = __import__(package, fromlist=["__file__"])
        manifest_file = Path(module.__file__).parent / "manifest.toml"  # type: ignore[arg-type]
        m = load_manifest(manifest_file, package)
        found[m.name] = m
    return found



def load_event_handlers(units: dict[str, Manifest] | None = None) -> None:
    """Import every unit's events.py so its @subscribe handlers are registered.

    Must run in any process that publishes events: the API, the CLI and scripts.
    """
    import contextlib
    import importlib

    from ziira.kernel.events import register_unit_package

    for m in (units or discover()).values():
        if m.core:
            continue
        register_unit_package(m.package, m.name)
        with contextlib.suppress(ModuleNotFoundError):
            importlib.import_module(f"{m.package}.events")


def install_order(units: dict[str, Manifest], names: list[str] | None = None) -> list[str]:
    """Return unit names so that every unit comes after the units it requires."""
    wanted = names if names is not None else list(units)
    ordered: list[str] = []
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in ordered:
            return
        if name not in units:
            raise DependencyError(f"Unknown unit '{name}'")
        if name in visiting:
            raise DependencyError(f"Circular dependency involving '{name}'")
        visiting.add(name)
        implicit = () if units[name].core else ("kernel",)   # every unit needs the kernel
        for dep in (*implicit, *units[name].requires):
            visit(dep)
        visiting.discard(name)
        ordered.append(name)

    for n in wanted:
        visit(n)
    return ordered


def migration_files(m: Manifest, direction: str) -> list[Path]:
    """Migration files for a unit, e.g. 0001_init.up.sql, sorted."""
    files = sorted(m.migrations_dir.glob(f"*.{direction}.sql"))
    return list(reversed(files)) if direction == "down" else files


def _run_script(conn: "Connection", sql: str) -> None:
    """Run a whole SQL file on the connection's current transaction.

    Uses the driver cursor directly so '%' in SQL (e.g. in PL/pgSQL messages)
    is not treated as a parameter placeholder.
    """
    with conn.connection.dbapi_connection.cursor() as cur:  # type: ignore[union-attr]
        cur.execute(sql)


def seed_unit_defaults(s: Session, m: Manifest) -> None:
    """Give the tenant's default roles this unit's permissions and add its reason codes.

    Safe to run again (re-enabling keeps what the tenant changed and adds what is missing).
    The session must be scoped to the tenant.
    """
    s.execute(text(
        "insert into kernel.role_permission (tenant_id, role_id, permission_code) "
        "select r.tenant_id, r.id, p.code from kernel.role r cross join kernel.permission p "
        "where r.tenant_id = kernel.current_tenant() and r.is_system and r.name = 'Owner' "
        "and p.unit_name = :n on conflict (role_id, permission_code) do nothing"), {"n": m.name})
    for role_name, permission_codes in m.roles.items():
        for code in permission_codes:
            s.execute(text(
                "insert into kernel.role_permission (tenant_id, role_id, permission_code) "
                "select r.tenant_id, r.id, :c from kernel.role r "
                "where r.tenant_id = kernel.current_tenant() and r.is_system and r.name = :r "
                "on conflict (role_id, permission_code) do nothing"), {"c": code, "r": role_name})
    for category, codes in m.reason_codes.items():
        for code, label in codes.items():
            s.execute(text(
                "insert into kernel.reason_code (tenant_id, category, code, label) "
                "values (kernel.current_tenant(), :cat, :code, :label) "
                "on conflict (tenant_id, category, code) do nothing"),
                {"cat": category, "code": code, "label": label})


# --------------------------------------------------------------------------- applying units to a database
def unit_schema(m: Manifest) -> str:
    """PostgreSQL schema of a unit: kernel, <module>, or plg_<plugin>."""
    return "kernel" if m.core else (f"plg_{m.name}" if m.kind == "plugin" else m.name)


def apply_migrations(conn: Connection, m: Manifest) -> list[str]:
    """Apply a unit's pending migrations in this database. Returns the files applied."""
    _run_script(conn, BOOTSTRAP_SQL)
    applied = set(conn.execute(
        text("select migration from kernel.schema_migration where unit_name = :n"), {"n": m.name}).scalars())
    done = []
    for f in migration_files(m, "up"):
        if f.name in applied:
            continue
        _run_script(conn, f.read_text())
        conn.execute(text("insert into kernel.schema_migration (unit_name, migration) values (:n, :f)"),
                     {"n": m.name, "f": f.name})
        done.append(f.name)
    return done


def register_unit(conn: Connection, m: Manifest) -> None:
    """Record the unit and its permissions in this database's kernel tables."""
    manifest_json = json.dumps({
        "title": m.title, "requires": list(m.requires), "optional": list(m.optional),
        "publishes": list(m.publishes), "subscribes": list(m.subscribes),
    })
    conn.execute(text(
        "insert into kernel.unit (name, kind, version, manifest) values (:n, :k, :v, cast(:m as jsonb)) "
        "on conflict (name) do update set version = excluded.version, manifest = excluded.manifest"),
        {"n": m.name, "k": m.kind, "v": m.version, "m": manifest_json})
    for code, description in m.permissions.items():
        conn.execute(text(
            "insert into kernel.permission (code, unit_name, description) values (:c, :n, :d) "
            "on conflict (code) do update set description = excluded.description"),
            {"c": code, "n": m.name, "d": description})


def grant_unit(conn: Connection, m: Manifest, role: str) -> None:
    """Let the tenant's own login use the unit's tables (row-level security still applies)."""
    schema = unit_schema(m)
    conn.exec_driver_sql(f'grant usage on schema {schema} to "{role}"')
    conn.exec_driver_sql(f'grant select, insert, update, delete on all tables in schema {schema} to "{role}"')
    conn.exec_driver_sql(f'grant usage, select on all sequences in schema {schema} to "{role}"')


def ensure_master() -> None:
    """Create the master database if needed, and create or upgrade its schema."""
    ensure_master_database()
    with master_engine().begin() as conn:
        _run_script(conn, MASTER_BOOTSTRAP_SQL)
        applied = set(conn.execute(text("select migration from master.schema_migration")).scalars())
        for f in sorted(MASTER_MIGRATIONS.glob("*.up.sql")):
            if f.name not in applied:
                _run_script(conn, f.read_text())
                conn.execute(text("insert into master.schema_migration (migration) values (:f)"), {"f": f.name})


# --------------------------------------------------------------------------- platform level
class Registry:
    """Installs units on the platform and enables, disables or removes them per tenant database."""

    def __init__(self, units: dict[str, Manifest] | None = None) -> None:
        self.units = units if units is not None else discover()

    # ---- queries
    def installed(self) -> set[str]:
        """Units the platform offers (master database)."""
        with master_session() as s:
            if s.execute(text("select to_regclass('master.unit')")).scalar() is None:
                return set()
            return set(s.execute(text("select name from master.unit")).scalars())

    def tenant_ids(self) -> list[UUID]:
        """Tenants whose databases exist (active or being set up)."""
        with master_session() as s:
            if s.execute(text("select to_regclass('master.tenant')")).scalar() is None:
                return []
            return list(s.execute(text(
                "select id from master.tenant where status in ('provisioning', 'active') order by created_at"))
                .scalars())

    def installed_in(self, tenant_id: UUID) -> set[str]:
        """Units whose tables exist in the tenant's database."""
        with tenant_engine(tenant_id, admin=True).connect() as conn:
            return set(conn.execute(text("select name from kernel.unit")).scalars())

    def enabled_for(self, session: Session) -> set[str]:
        """Units enabled for the tenant of this session (kernel always included)."""
        rows = session.execute(
            text("select unit_name from kernel.tenant_unit "
                 "where status = 'enabled' and tenant_id = kernel.current_tenant()")
        ).scalars()
        return {"kernel", *rows}

    def get(self, name: str) -> Manifest:
        if name not in self.units:
            raise NotFound(f"Unit '{name}' was not found")
        return self.units[name]

    @staticmethod
    def app_role(tenant_id: UUID) -> str:
        """The tenant's own database login."""
        with master_session() as s:
            role = s.execute(text("select app_role from master.tenant where id = :t"), {"t": str(tenant_id)}).scalar()
        if role is None:
            raise NotFound("Tenant not found")
        return str(role)

    # ---- install / uninstall (platform)
    def install(self, name: str) -> list[str]:
        """Offer a unit (and the units it requires) on the platform. Returns the units newly installed.

        Units already installed are upgraded: new migrations run in every tenant database that has
        the unit (and in the template, for the kernel).
        """
        ensure_master()
        done: list[str] = []
        installed = self.installed()
        for unit_name in install_order(self.units, [name]):
            m = self.units[unit_name]
            if not sdk_compatible(m.sdk):
                raise DependencyError(f"'{unit_name}' needs SDK {m.sdk}; this kernel provides {SDK_VERSION}")
            self._register_platform(m)
            if m.core:
                self.ensure_template()
            if unit_name in installed:
                for tenant_id in self.tenant_ids():
                    if unit_name in self.installed_in(tenant_id):
                        self._install_in_tenant(tenant_id, m)
                continue
            installed.add(unit_name)
            done.append(unit_name)
        return done

    def install_all(self) -> list[str]:
        done: list[str] = []
        for unit_name in install_order(self.units):
            done += self.install(unit_name)
        return done

    def uninstall(self, name: str) -> None:
        """Stop offering a unit. Refused while any tenant database has it, or a unit requires it."""
        m = self.get(name)
        if m.core:
            raise DependencyError("The kernel cannot be uninstalled")
        installed = self.installed()
        if name not in installed:
            raise DependencyError(f"'{name}' is not installed")
        dependants = [u for u in installed if u in self.units and name in self.units[u].requires]
        if dependants:
            raise DependencyError(f"'{name}' is required by installed units: {', '.join(sorted(dependants))}")
        holders = [t for t in self.tenant_ids() if name in self.installed_in(t)]
        if holders:
            raise DependencyError(f"'{name}' is still in {len(holders)} tenant database(s); remove it there first")
        with master_session() as s:
            s.execute(text("delete from master.unit where name = :n"), {"n": name})

    def _register_platform(self, m: Manifest) -> None:
        manifest_json = json.dumps({"title": m.title, "requires": list(m.requires), "optional": list(m.optional),
                                    "permissions": m.permissions})
        with master_session() as s:
            s.execute(text(
                "insert into master.unit (name, kind, version, manifest) values (:n, :k, :v, cast(:m as jsonb)) "
                "on conflict (name) do update set version = excluded.version, manifest = excluded.manifest"),
                {"n": m.name, "k": m.kind, "v": m.version, "m": manifest_json})

    def ensure_template(self) -> None:
        """Create or upgrade the template database (kernel only) new tenant databases are copied from."""
        name = get_settings().template_database
        with server_engine().connect() as conn:
            if conn.execute(text("select 1 from pg_database where datname = :n"), {"n": name}).first() is None:
                conn.exec_driver_sql(f'create database "{name}"')
                conn.exec_driver_sql(f'revoke all on database "{name}" from public')
        # NullPool: no connection may stay open, or the template cannot be copied.
        engine = create_engine(server_database_url(name), poolclass=NullPool)
        try:
            with engine.begin() as conn:
                apply_migrations(conn, self.units["kernel"])
                register_unit(conn, self.units["kernel"])
        finally:
            engine.dispose()

    # ---- per tenant database
    def _install_in_tenant(self, tenant_id: UUID, m: Manifest) -> None:
        """Create or upgrade the unit's tables in the tenant's database."""
        role = self.app_role(tenant_id)
        with tenant_engine(tenant_id, admin=True).begin() as conn:
            apply_migrations(conn, m)
            register_unit(conn, m)
            grant_unit(conn, m, role)

    def remove_from_tenant(self, tenant_id: UUID, name: str) -> None:
        """Drop a unit's tables from one tenant's database (its data is deleted).

        Refused while the unit is enabled there, or another unit there requires it.
        """
        m = self.get(name)
        if m.core:
            raise DependencyError("The kernel cannot be removed")
        present = self.installed_in(tenant_id)
        if name not in present:
            raise DependencyError(f"'{name}' is not in this tenant's database")
        dependants = [u for u in present if u in self.units and name in self.units[u].requires]
        if dependants:
            raise DependencyError(f"'{name}' is required by: {', '.join(sorted(dependants))}")
        with tenant_session(tenant_id, admin=True) as s:
            if name in self.enabled_for(s):
                raise DependencyError(f"'{name}' is enabled for this tenant; disable it first")
        with tenant_engine(tenant_id, admin=True).begin() as conn:
            for f in migration_files(m, "down"):
                _run_script(conn, f.read_text())
            conn.execute(text("delete from kernel.schema_migration where unit_name = :n"), {"n": name})
            conn.execute(text("delete from kernel.tenant_unit where unit_name = :n"), {"n": name})
            conn.execute(text("delete from kernel.role_permission where permission_code in "
                              "(select code from kernel.permission where unit_name = :n)"), {"n": name})
            conn.execute(text("delete from kernel.permission where unit_name = :n"), {"n": name})
            conn.execute(text("delete from kernel.unit where name = :n"), {"n": name})

    # ---- enable / disable (per tenant)
    def enable(self, tenant_id: UUID, name: str) -> list[str]:
        """Enable a unit for a tenant, enabling required units first. Returns units newly enabled.

        Creates the unit's tables in the tenant's database the first time.
        """
        installed = self.installed()
        present = self.installed_in(tenant_id)
        newly: list[str] = []
        for unit_name in install_order(self.units, [name]):
            m = self.units[unit_name]
            if m.core:
                continue
            if unit_name not in installed:
                raise DependencyError(f"'{unit_name}' is not installed on this platform")
            if unit_name not in present:
                self._install_in_tenant(tenant_id, m)
                present.add(unit_name)
            with tenant_session(tenant_id, admin=True) as s:
                if unit_name in self.enabled_for(s):
                    continue
                s.execute(text(
                    "insert into kernel.tenant_unit (tenant_id, unit_name, status, enabled_at) "
                    "values (:t, :n, 'enabled', now()) on conflict (tenant_id, unit_name) "
                    "do update set status = 'enabled', enabled_at = now(), disabled_at = null"),
                    {"t": str(tenant_id), "n": unit_name})
                seed_unit_defaults(s, m)
            newly.append(unit_name)
        return newly

    def disable(self, tenant_id: UUID, name: str) -> None:
        """Disable a unit for a tenant. Data is kept. Refused if an enabled unit requires it."""
        m = self.get(name)
        if m.core:
            raise DependencyError("The kernel cannot be disabled")
        with tenant_session(tenant_id, admin=True) as s:
            enabled = self.enabled_for(s)
            if name not in enabled:
                return
            dependants = [u for u in enabled if u in self.units and name in self.units[u].requires]
            if dependants:
                raise DependencyError(
                    f"'{name}' is required by enabled units: {', '.join(sorted(dependants))}")
            s.execute(text(
                "update kernel.tenant_unit set status = 'disabled', disabled_at = now() "
                "where unit_name = :n and tenant_id = kernel.current_tenant()"), {"n": name})

"""Module and plugin registry: discover, install, enable, disable, uninstall.

Lifecycle:
    available -> install (platform) -> enable (per tenant) -> disable -> uninstall (platform)

Rules:
- A unit can be installed only after the units it requires are installed.
- A unit can be enabled for a tenant only if the units it requires are enabled.
- A unit cannot be disabled while an enabled unit requires it.
- A unit cannot be uninstalled while any tenant has it enabled, or another installed unit requires it.
- Disabling keeps all data. Uninstalling runs the unit's down migrations.
"""

import json
from importlib import metadata
from pathlib import Path
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from ziira.kernel.config import get_settings
from ziira.kernel.db import admin_engine, admin_session, tenant_session
from ziira.kernel.errors import DependencyError, NotFound
from ziira.kernel.manifest import Manifest, load_manifest

ZIIRA_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT_GROUP = "ziira.units"

BOOTSTRAP_SQL = """
create schema if not exists kernel;
create table if not exists kernel.schema_migration (
    unit_name  text not null,
    migration  text not null,
    applied_at timestamptz not null default now(),
    primary key (unit_name, migration)
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

    for m in (units or discover()).values():
        if m.core:
            continue
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


# --------------------------------------------------------------------------- platform level
class Registry:
    """Installs and removes units, and enables or disables them per tenant."""

    def __init__(self, units: dict[str, Manifest] | None = None) -> None:
        self.units = units if units is not None else discover()

    # ---- queries
    def installed(self) -> set[str]:
        with admin_session() as s:
            exists = s.execute(text("select to_regclass('kernel.unit')")).scalar()
            if exists is None:
                return set()
            return set(s.execute(text("select name from kernel.unit")).scalars())

    def enabled_for(self, session: Session) -> set[str]:
        """Units enabled for the tenant of this session (kernel always included).

        The tenant filter is explicit as well as enforced by row-level security,
        so admin sessions (which may bypass row-level security) stay correct.
        """
        rows = session.execute(
            text("select unit_name from kernel.tenant_unit "
                 "where status = 'enabled' and tenant_id = kernel.current_tenant()")
        ).scalars()
        return {"kernel", *rows}

    def get(self, name: str) -> Manifest:
        if name not in self.units:
            raise NotFound(f"Unit '{name}' was not found")
        return self.units[name]

    # ---- install / uninstall (platform)
    def install(self, name: str) -> list[str]:
        """Install a unit and any units it requires. Returns the units newly installed."""
        done: list[str] = []
        installed = self.installed()
        for unit_name in install_order(self.units, [name]):
            if unit_name in installed:
                continue
            self._apply_migrations(self.units[unit_name])
            self._register(self.units[unit_name])
            installed.add(unit_name)
            done.append(unit_name)
        return done

    def install_all(self) -> list[str]:
        done: list[str] = []
        for unit_name in install_order(self.units):
            done += self.install(unit_name)
        return done

    def uninstall(self, name: str) -> None:
        """Remove a unit's tables. Refused if anything still depends on it."""
        m = self.get(name)
        if m.core:
            raise DependencyError("The kernel cannot be uninstalled")
        installed = self.installed()
        if name not in installed:
            raise DependencyError(f"'{name}' is not installed")
        dependants = [u for u in installed if u in self.units and name in self.units[u].requires]
        if dependants:
            raise DependencyError(f"'{name}' is required by installed units: {', '.join(sorted(dependants))}")
        with admin_session() as s:
            tenants = s.execute(
                text("select count(*) from kernel.tenant_unit where unit_name = :n and status = 'enabled'"),
                {"n": name},
            ).scalar_one()
        if tenants:
            raise DependencyError(f"'{name}' is enabled for {tenants} tenant(s); disable it first")
        with admin_engine().begin() as conn:
            for f in migration_files(m, "down"):
                _run_script(conn, f.read_text())
            conn.execute(text("delete from kernel.schema_migration where unit_name = :n"), {"n": name})
            conn.execute(text("delete from kernel.tenant_unit where unit_name = :n"), {"n": name})
            conn.execute(text("delete from kernel.role_permission where permission_code in "
                              "(select code from kernel.permission where unit_name = :n)"), {"n": name})
            conn.execute(text("delete from kernel.permission where unit_name = :n"), {"n": name})
            conn.execute(text("delete from kernel.unit where name = :n"), {"n": name})

    def _apply_migrations(self, m: Manifest) -> None:
        role = get_settings().app_db_role
        with admin_engine().begin() as conn:
            _run_script(conn, BOOTSTRAP_SQL)
            applied = set(conn.execute(
                text("select migration from kernel.schema_migration where unit_name = :n"),
                {"n": m.name},
            ).scalars())
            for f in migration_files(m, "up"):
                if f.name in applied:
                    continue
                _run_script(conn, f.read_text())
                conn.execute(text("insert into kernel.schema_migration (unit_name, migration) "
                                  "values (:n, :f)"), {"n": m.name, "f": f.name})
            schema = "kernel" if m.core else (f"plg_{m.name}" if m.kind == "plugin" else m.name)
            conn.exec_driver_sql(f"grant usage on schema {schema} to {role}")
            conn.exec_driver_sql(f"grant select, insert, update, delete on all tables in schema {schema} to {role}")
            conn.exec_driver_sql(f"grant usage, select on all sequences in schema {schema} to {role}")

    def _register(self, m: Manifest) -> None:
        manifest_json = json.dumps({
            "title": m.title, "requires": list(m.requires), "optional": list(m.optional),
            "publishes": list(m.publishes), "subscribes": list(m.subscribes),
        })
        with admin_session() as s:
            s.execute(text(
                "insert into kernel.unit (name, kind, version, manifest) values (:n, :k, :v, cast(:m as jsonb)) "
                "on conflict (name) do update set version = excluded.version, manifest = excluded.manifest"),
                {"n": m.name, "k": m.kind, "v": m.version, "m": manifest_json})
            for code, description in m.permissions.items():
                s.execute(text(
                    "insert into kernel.permission (code, unit_name, description) values (:c, :n, :d) "
                    "on conflict (code) do update set description = excluded.description"),
                    {"c": code, "n": m.name, "d": description})

    # ---- enable / disable (per tenant)
    def enable(self, tenant_id: UUID, name: str) -> list[str]:
        """Enable a unit for a tenant, enabling required units first. Returns units newly enabled."""
        installed = self.installed()
        newly: list[str] = []
        with tenant_session(tenant_id, admin=True) as s:
            enabled = self.enabled_for(s)
            for unit_name in install_order(self.units, [name]):
                if self.units[unit_name].core or unit_name in enabled:
                    continue
                if unit_name not in installed:
                    raise DependencyError(f"'{unit_name}' is not installed on this platform")
                s.execute(text(
                    "insert into kernel.tenant_unit (tenant_id, unit_name, status, enabled_at) "
                    "values (:t, :n, 'enabled', now()) on conflict (tenant_id, unit_name) "
                    "do update set status = 'enabled', enabled_at = now(), disabled_at = null"),
                    {"t": str(tenant_id), "n": unit_name})
                enabled.add(unit_name)
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

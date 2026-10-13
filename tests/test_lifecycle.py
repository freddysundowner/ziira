"""Install, enable, disable, remove and uninstall rules, with one database per tenant."""

import pytest
from sqlalchemy import text

from ziira.kernel.errors import DependencyError


def schemas(tenant_id) -> set[str]:  # type: ignore[no-untyped-def]
    """Schemas that exist in the tenant's own database."""
    from ziira.kernel.db import tenant_engine

    with tenant_engine(tenant_id, admin=True).connect() as conn:
        return set(conn.execute(text("select nspname from pg_namespace")).scalars())


def test_everything_installed_on_the_platform(registry) -> None:  # type: ignore[no-untyped-def]
    assert {"kernel", "products", "pos", "finance", "people", "catalog_stats"} <= registry.installed()


def test_tenant_database_holds_only_enabled_units(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    a = tenants["A"]["tenant_id"]
    assert {"kernel", "products", "plg_catalog_stats"} <= schemas(a)
    assert "finance" not in schemas(a) and "pos" not in schemas(a)
    assert registry.installed_in(a) == {"kernel", "products", "catalog_stats"}


def test_enabling_pos_enables_what_it_requires(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    b = tenants["B"]["tenant_id"]
    newly = registry.enable(b, "pos")
    assert set(newly) == {"inventory", "payments", "pos"}      # products was already enabled
    with tenant_session(b) as s:
        assert {"products", "inventory", "payments", "pos"} <= registry.enabled_for(s)
    assert {"inventory", "payments", "pos"} <= schemas(b)     # tables created in B's database only
    assert "pos" not in schemas(tenants["A"]["tenant_id"])


def test_cannot_disable_a_required_module(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    b = tenants["B"]["tenant_id"]
    registry.enable(b, "inventory")
    with pytest.raises(DependencyError, match="required by enabled units"):
        registry.disable(b, "products")


def test_cannot_uninstall_a_required_module(registry) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(DependencyError, match="required by installed units"):
        registry.uninstall("products")


def test_plugin_remove_and_uninstall(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import master_session

    a = tenants["A"]["tenant_id"]
    registry.enable(a, "catalog_stats")
    with pytest.raises(DependencyError, match="disable it first"):
        registry.remove_from_tenant(a, "catalog_stats")
    with pytest.raises(DependencyError, match="tenant database"):
        registry.uninstall("catalog_stats")

    registry.disable(a, "catalog_stats")
    registry.remove_from_tenant(a, "catalog_stats")
    assert "plg_catalog_stats" not in schemas(a)
    assert "catalog_stats" not in registry.installed_in(a)
    others = [t for t in registry.tenant_ids() if "catalog_stats" in registry.installed_in(t)]
    for t in others:                                           # other tests' tenants may have it too
        registry.disable(t, "catalog_stats")
        registry.remove_from_tenant(t, "catalog_stats")
    registry.uninstall("catalog_stats")
    with master_session() as s:
        assert s.execute(text("select count(*) from master.unit where name = 'catalog_stats'")).scalar() == 0

    assert registry.install("catalog_stats") == ["catalog_stats"]
    registry.enable(a, "catalog_stats")
    assert "plg_catalog_stats" in schemas(a)


def test_unused_module_uninstall(registry) -> None:  # type: ignore[no-untyped-def]
    registry.uninstall("command")                              # no tenant database has it
    assert "command" not in registry.installed()
    registry.install("command")


def _scratch_plugin(folder, sdk: str = ">=1.0,<2.0"):  # type: ignore[no-untyped-def]
    """A throwaway plugin in a temporary folder."""
    from ziira.kernel.manifest import load_manifest

    (folder / "migrations").mkdir(exist_ok=True)
    (folder / "manifest.toml").write_text(
        f'[unit]\nname = "scratch"\nkind = "plugin"\nversion = "1.0.0"\nsdk = "{sdk}"\n')
    (folder / "migrations" / "0001_init.up.sql").write_text(
        "create schema plg_scratch; create table plg_scratch.note (id int primary key);")
    (folder / "migrations" / "0001_init.down.sql").write_text("drop schema plg_scratch cascade;")
    return load_manifest(folder / "manifest.toml", "scratch")


def test_installing_again_upgrades_every_tenant_database(registry, tenants, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_engine
    from ziira.kernel.registry import Registry

    a = tenants["A"]["tenant_id"]
    reg = Registry({**registry.units, "scratch": _scratch_plugin(tmp_path)})
    assert reg.install("scratch") == ["scratch"]
    reg.enable(a, "scratch")
    (tmp_path / "migrations" / "0002_add_text.up.sql").write_text("alter table plg_scratch.note add column body text;")
    assert reg.install("scratch") == []                        # nothing new installed ...
    with tenant_engine(a, admin=True).connect() as conn:       # ... but A's database was upgraded
        assert conn.execute(text("select count(*) from information_schema.columns "
                                 "where table_schema = 'plg_scratch' and column_name = 'body'")).scalar() == 1
    reg.disable(a, "scratch")
    reg.remove_from_tenant(a, "scratch")
    reg.uninstall("scratch")


def test_incompatible_sdk_is_refused(registry, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.registry import Registry

    reg = Registry({**registry.units, "scratch": _scratch_plugin(tmp_path, sdk=">=2.0")})
    with pytest.raises(DependencyError, match="needs SDK"):
        reg.install("scratch")
    assert "scratch" not in reg.installed()

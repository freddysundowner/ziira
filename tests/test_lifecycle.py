"""Enable, disable, install and uninstall rules against a real database."""

import pytest
from sqlalchemy import text

from ziira.kernel.errors import DependencyError


def test_everything_installed(registry) -> None:  # type: ignore[no-untyped-def]
    assert {"kernel", "products", "pos", "finance", "people", "catalog_stats"} <= registry.installed()


def test_enabling_pos_enables_what_it_requires(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    b = tenants["B"]["tenant_id"]
    newly = registry.enable(b, "pos")
    assert set(newly) == {"inventory", "payments", "pos"}      # products was already enabled
    with tenant_session(b) as s:
        assert {"products", "inventory", "payments", "pos"} <= registry.enabled_for(s)


def test_cannot_disable_a_required_module(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    b = tenants["B"]["tenant_id"]
    registry.enable(b, "inventory")
    with pytest.raises(DependencyError, match="required by enabled units"):
        registry.disable(b, "products")


def test_cannot_uninstall_a_required_module(registry) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(DependencyError, match="required by installed units"):
        registry.uninstall("products")


def test_plugin_uninstall_and_reinstall(registry, tenants) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import admin_session

    a = tenants["A"]["tenant_id"]
    registry.enable(a, "catalog_stats")
    with pytest.raises(DependencyError, match="enabled for"):
        registry.uninstall("catalog_stats")

    registry.disable(a, "catalog_stats")
    registry.uninstall("catalog_stats")
    with admin_session() as s:
        assert s.execute(text("select to_regnamespace('plg_catalog_stats')")).scalar() is None
        assert s.execute(text("select count(*) from kernel.unit where name = 'catalog_stats'")).scalar() == 0

    assert registry.install("catalog_stats") == ["catalog_stats"]
    registry.enable(a, "catalog_stats")


def test_optional_module_uninstall_leaves_others(registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import admin_session

    registry.uninstall("command")
    with admin_session() as s:
        assert s.execute(text("select to_regnamespace('command')")).scalar() is None
        assert s.execute(text("select to_regclass('pos.sale')")).scalar() is not None
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


def test_installing_again_applies_new_migrations(registry, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import admin_session
    from ziira.kernel.registry import Registry

    reg = Registry({**registry.units, "scratch": _scratch_plugin(tmp_path)})
    assert reg.install("scratch") == ["scratch"]
    (tmp_path / "migrations" / "0002_add_text.up.sql").write_text("alter table plg_scratch.note add column body text;")
    assert reg.install("scratch") == []                        # nothing new installed ...
    with admin_session() as s:                                 # ... but the new migration ran
        assert s.execute(text("select count(*) from information_schema.columns where table_schema = 'plg_scratch' "
                              "and column_name = 'body'")).scalar() == 1
        assert s.execute(text("select count(*) from kernel.schema_migration where unit_name = 'scratch'")).scalar() == 2
    reg.uninstall("scratch")


def test_incompatible_sdk_is_refused(registry, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.registry import Registry

    reg = Registry({**registry.units, "scratch": _scratch_plugin(tmp_path, sdk=">=2.0")})
    with pytest.raises(DependencyError, match="needs SDK"):
        reg.install("scratch")
    assert "scratch" not in reg.installed()

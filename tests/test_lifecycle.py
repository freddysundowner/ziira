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

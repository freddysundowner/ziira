"""Every unit on its own: enabled alone (with only what it requires), its tables and permissions appear, it can be
disabled and enabled again with its data kept, and removed cleanly (the uninstall scripts really remove it)."""

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant
from ziira.kernel.db import tenant_session
from ziira.kernel.registry import discover, install_order

# Reference data shared by every business, kept by the platform (specification Appendix A): no tenant_id.
PLATFORM_TABLES = {"people.statutory_rate_table", "intel.check_definition"}

UNITS = sorted(name for name, m in discover().items()
               if not m.core and not m.platform_scope)      # platform-scope plugins are never switched on by a business


def schemas(tenant_id) -> set[str]:  # type: ignore[no-untyped-def]
    with tenant_session(tenant_id, admin=True) as s:
        return set(s.execute(text(
            "select schema_name from information_schema.schemata where schema_name not like 'pg_%' "
            "and schema_name not in ('information_schema', 'public')")).scalars())


def schema_of(m) -> str:  # type: ignore[no-untyped-def]
    return f"plg_{m.name}" if m.kind == "plugin" else m.name


@pytest.mark.parametrize("unit", UNITS)
def test_a_unit_enabled_alone(registry, unit: str) -> None:  # type: ignore[no-untyped-def]
    units = discover()
    m = units[unit]
    tenant = make_tenant(f"Alone {unit.replace('_', ' ')}")
    t = tenant["tenant_id"]
    needed = [u for u in install_order(units, [unit]) if not units[u].core]
    assert unit in needed

    # --- enabling brings exactly what it requires, and nothing else
    newly = registry.enable(t, unit)
    assert set(newly) == set(needed)
    assert schemas(t) == {"kernel"} | {schema_of(units[u]) for u in needed}
    assert registry.installed_in(t) >= set(needed)

    with tenant_session(t, admin=True) as s:
        # its permissions are registered, and the Owner holds them all
        codes = {c for c, in s.execute(text("select code from kernel.permission where unit_name = :n"), {"n": unit})}
        assert codes == set(m.permissions)
        owner_codes = {c for c, in s.execute(text(
            "select rp.permission_code from kernel.role_permission rp join kernel.role r on r.id = rp.role_id "
            "where r.name = 'Owner'"))}
        assert codes <= owner_codes
        # default roles received the grants the manifest names (and only valid ones)
        for role, permissions in m.roles.items():
            granted = {c for c, in s.execute(text(
                "select rp.permission_code from kernel.role_permission rp join kernel.role r on r.id = rp.role_id "
                "where r.name = :r"), {"r": role})}
            assert set(permissions) <= granted, (unit, role)
        # reason codes it seeds exist
        for category, reason_codes in m.reason_codes.items():
            seeded = {c for c, in s.execute(text("select code from kernel.reason_code where category = :c"),
                                            {"c": category})}
            assert set(reason_codes) <= seeded
        # every tenant table it created has row-level security forced (a second layer behind the tenant's own
        # database); the only tables without a tenant_id are the platform-level reference tables listed above
        unprotected = s.execute(text(
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = :s and c.relkind = 'r' and not (c.relrowsecurity and c.relforcerowsecurity)"),
            {"s": schema_of(m)}).scalars().all()
        assert {f"{schema_of(m)}.{t}" for t in unprotected} <= PLATFORM_TABLES, \
            f"{unit}: tables without forced row-level security: {unprotected}"
        for table in unprotected:                           # ...and those really have no tenant data in them
            columns = set(s.execute(text(
                "select column_name from information_schema.columns where table_schema = :s and table_name = :t"),
                {"s": schema_of(m), "t": table}).scalars())
            assert "tenant_id" not in columns, f"{schema_of(m)}.{table} has tenant data but no row-level security"

    # --- disabling keeps everything; enabling again changes nothing
    registry.disable(t, unit)
    assert schemas(t) == {"kernel"} | {schema_of(units[u]) for u in needed}
    assert registry.enable(t, unit) == [unit]
    registry.disable(t, unit)

    # --- removing deletes it (dependants first), and what it required stays until removed
    registry.remove_from_tenant(t, unit)
    assert schema_of(m) not in schemas(t)
    for other in reversed(needed):
        if other == unit:
            continue
        registry.disable(t, other)
        registry.remove_from_tenant(t, other)
    assert schemas(t) == {"kernel"}
    with tenant_session(t, admin=True) as s:
        assert s.execute(text("select count(*) from kernel.permission where unit_name = :n"), {"n": unit}
                         ).scalar_one() == 0
        assert s.execute(text("select count(*) from kernel.unit where name = :n"), {"n": unit}).scalar_one() == 0


def test_the_kernel_alone_works(registry, client) -> None:  # type: ignore[no-untyped-def]
    """A business with no unit enabled can still sign in, manage users and read its units."""
    from tests.conftest import sign_in

    make_tenant("Kernel Only")
    owner = sign_in(client, "kernel-only", "owner@kernel-only.test").headers
    assert client.get("/api/v1/auth/me", headers=owner).status_code == 200
    assert client.get("/api/v1/users", headers=owner).status_code == 200
    assert {u["name"] for u in client.get("/api/v1/units", headers=owner).json() if u["enabled"]} == {"kernel"}
    for prefix in ("products", "inventory", "plugins/catalog-stats"):
        assert client.get(f"/api/v1/{prefix}/x", headers=owner).status_code in (404, 405)


def test_optional_units_are_really_optional(client, registry) -> None:  # type: ignore[no-untyped-def]
    """Products works without Inventory, and Inventory without POS and Purchasing."""
    from tests.conftest import sign_in

    t = make_tenant("Optional Co")
    registry.enable(t["tenant_id"], "products")
    owner = sign_in(client, "optional-co", "owner@optional-co.test").headers
    uom = client.post("/api/v1/products/uoms", headers=owner, json={"code": "PCS", "name": "Pieces"}).json()["id"]
    tax = client.post("/api/v1/products/tax-codes", headers=owner, json={
        "code": "V", "name": "VAT", "vat_rate": "16", "authority_code": "B"}).json()["id"]
    r = client.post("/api/v1/products/products", headers=owner, json={
        "company_id": str(t["company_id"]), "sku": "ALONE", "name": "Alone", "base_uom_id": uom, "tax_code_id": tax})
    assert r.status_code == 201
    assert client.get("/api/v1/inventory/balances", headers=owner).status_code == 404         # not enabled: no stock
    registry.enable(t["tenant_id"], "inventory")                                              # no POS, no Purchasing
    assert client.get("/api/v1/inventory/balances", headers=owner).status_code == 200

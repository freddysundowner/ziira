"""Apps & plugins: the catalog, switching units on and off, removing their data, who may, and that it is audited."""

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from tests.stock_helpers import system

U = "/api/v1/units"


@pytest.fixture(scope="module")
def biz(client, registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Apps Co")
    owner = sign_in(client, "apps-co", "owner@apps-co.test").headers
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner).json()}
    u = client.post("/api/v1/users", headers=owner, json={"full_name": "Manager", "email": "mgr@apps-co.test",
                                                         "password": "manager-pass-1"}).json()
    r = client.post(f"/api/v1/users/{u['id']}/roles", headers=owner, json={
        "role_id": roles["Branch Manager"], "scope": "company", "company_id": str(t["company_id"]), "branch_id": None})
    assert r.status_code == 201, r.text
    return {**t, "owner": owner, "manager": sign_in(client, "apps-co", "mgr@apps-co.test", "manager-pass-1").headers}


@pytest.fixture(scope="module")
def other(client, registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Apps Other")
    return {**t, "owner": sign_in(client, "apps-other", "owner@apps-other.test").headers}


def card(client, headers, name: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return next(c for c in client.get(f"{U}/catalog", headers=headers).json() if c["name"] == name)


def audit_actions(biz, action: str) -> list[dict]:  # type: ignore[no-untyped-def,type-arg]
    with system(biz) as s:
        rows = s.execute(text("select changes from kernel.audit_log where entity_type = 'kernel.unit' "
                              "and action = :a order by id"), {"a": action}).scalars().all()
    return list(rows)


def test_catalog_lists_modules_and_plugins_but_never_the_kernel(client, biz) -> None:  # type: ignore[no-untyped-def]
    cards = client.get(f"{U}/catalog", headers=biz["owner"]).json()
    names = {c["name"] for c in cards}
    assert "kernel" not in names and {"products", "inventory", "catalog_stats"} <= names
    inv = next(c for c in cards if c["name"] == "inventory")
    assert inv["kind"] == "module" and inv["requires"] == ["products"] and inv["description"]
    assert inv["installed"] and not inv["enabled"] and inv["will_also_enable"] == ["products"]
    assert inv["can_enable"] and not inv["can_disable"] and not inv["can_remove"]
    assert next(c for c in cards if c["name"] == "catalog_stats")["kind"] == "plugin"


def test_only_the_owner_may(client, biz) -> None:  # type: ignore[no-untyped-def]
    assert client.get(f"{U}/catalog", headers=biz["manager"]).status_code == 403
    assert client.post(f"{U}/inventory/enable", headers=biz["manager"]).status_code == 403
    assert client.post(f"{U}/inventory/disable", headers=biz["manager"]).status_code == 403
    assert client.post(f"{U}/inventory/remove", headers=biz["manager"], json={"confirm": "inventory"}
                       ).status_code == 403
    assert client.get(f"{U}/catalog").status_code in (401, 403)
    assert not card(client, biz["owner"], "inventory")["enabled"]


def test_enable_switches_on_what_is_required_and_says_so(client, biz) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{U}/inventory/enable", headers=biz["owner"])
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] == ["products", "inventory"]
    assert r.json()["unit"]["enabled"] is True
    assert card(client, biz["owner"], "products")["dependants"] == ["inventory"]
    assert {u["name"] for u in client.get(U, headers=biz["owner"]).json() if u["enabled"]} >= {"products", "inventory"}
    # the module's own endpoints answer now
    assert client.get("/api/v1/products/products", headers=biz["owner"]).status_code == 200
    made = client.post("/api/v1/inventory/locations", headers=biz["owner"], json={
        "company_id": str(biz["company_id"]), "branch_id": str(biz["branch_id"]), "code": "MAIN", "name": "Main"})
    assert made.status_code == 201, made.text
    # again: nothing new
    assert client.post(f"{U}/inventory/enable", headers=biz["owner"]).json()["enabled"] == []
    assert audit_actions(biz, "enable")[0] == {"unit": "inventory", "enabled": ["products", "inventory"]}


def test_disable_is_refused_while_something_needs_it_and_keeps_data(client, biz) -> None:  # type: ignore[no-untyped-def]
    products = card(client, biz["owner"], "products")
    assert not products["can_disable"] and "Inventory" in products["why_not_disable"]
    r = client.post(f"{U}/products/disable", headers=biz["owner"])
    assert r.status_code == 409 and "inventory" in r.json()["message"]
    assert client.post(f"{U}/inventory/disable", headers=biz["owner"]).status_code == 200
    assert client.get("/api/v1/inventory/locations", headers=biz["owner"]).status_code == 404   # switched off
    after = card(client, biz["owner"], "inventory")
    assert not after["enabled"] and after["has_data"] and not after["can_disable"]
    assert audit_actions(biz, "disable") == [{"unit": "inventory"}]


def test_remove_needs_the_name_a_switched_off_unit_and_no_dependants(client, biz) -> None:  # type: ignore[no-untyped-def]
    # products is switched on and inventory (which needs it) still holds data
    assert client.post(f"{U}/products/remove", headers=biz["owner"], json={"confirm": "products"}).status_code == 409
    # the switched-off unit may be removed; one that is on may not
    assert card(client, biz["owner"], "inventory")["can_remove"] is True
    assert card(client, biz["owner"], "products")["can_remove"] is False
    wrong = client.post(f"{U}/inventory/remove", headers=biz["owner"], json={"confirm": "Inventory"})
    assert wrong.status_code == 409 and "inventory" in wrong.json()["message"]
    assert client.post(f"{U}/inventory/remove", headers=biz["owner"], json={}).status_code == 422
    assert card(client, biz["owner"], "inventory")["has_data"]


def test_remove_deletes_the_data_and_a_later_enable_starts_clean(client, biz) -> None:  # type: ignore[no-untyped-def]
    with system(biz) as s:
        assert s.execute(text("select count(*) from inventory.location")).scalar() == 1
    r = client.post(f"{U}/inventory/remove", headers=biz["owner"], json={"confirm": "inventory"})
    assert r.status_code == 200, r.text
    assert r.json()["unit"]["has_data"] is False
    with system(biz) as s:
        assert s.execute(text("select 1 from information_schema.schemata where schema_name = 'inventory'")).first() is None
        assert s.execute(text("select 1 from kernel.unit where name = 'inventory'")).first() is None
    assert audit_actions(biz, "remove") == [{"unit": "inventory", "data_deleted": True}]
    again = client.post(f"{U}/inventory/enable", headers=biz["owner"])
    assert again.status_code == 200 and again.json()["enabled"] == ["inventory"]
    with system(biz) as s:
        assert s.execute(text("select count(*) from inventory.location")).scalar() == 0
    assert client.get("/api/v1/inventory/locations", headers=biz["owner"]).json() == []


def test_removing_a_unit_that_was_never_switched_on_is_refused(client, biz) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{U}/catalog_stats/remove", headers=biz["owner"], json={"confirm": "catalog_stats"})
    assert r.status_code == 409


def test_the_kernel_and_unknown_units_cannot_be_touched(client, biz) -> None:  # type: ignore[no-untyped-def]
    for action in ("enable", "disable"):
        assert client.post(f"{U}/kernel/{action}", headers=biz["owner"]).status_code == 409
    assert client.post(f"{U}/kernel/remove", headers=biz["owner"], json={"confirm": "kernel"}).status_code == 409
    assert client.post(f"{U}/nonsense/enable", headers=biz["owner"]).status_code == 404


def test_a_unit_the_platform_has_not_installed_cannot_be_enabled(client, biz, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.registry import Registry

    real = Registry.installed
    monkeypatch.setattr(Registry, "installed", lambda self: real(self) - {"catalog_stats"})
    c = card(client, biz["owner"], "catalog_stats")
    assert not c["installed"] and not c["can_enable"]
    r = client.post(f"{U}/catalog_stats/enable", headers=biz["owner"])
    assert r.status_code == 409 and "not available yet" in r.json()["message"]
    assert not card(client, biz["owner"], "catalog_stats")["enabled"]


def test_one_business_cannot_change_or_see_another(client, biz, other) -> None:  # type: ignore[no-untyped-def]
    client.post(f"{U}/catalog_stats/enable", headers=biz["owner"])
    assert card(client, biz["owner"], "catalog_stats")["enabled"]
    assert not card(client, other["owner"], "catalog_stats")["enabled"]
    assert client.post(f"{U}/catalog_stats/disable", headers=other["owner"]).status_code == 200   # nothing to do
    assert card(client, biz["owner"], "catalog_stats")["enabled"]
    assert audit_actions(other, "enable") == [] and audit_actions(other, "disable") == [{"unit": "catalog_stats"}]

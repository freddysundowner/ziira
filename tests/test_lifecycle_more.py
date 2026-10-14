"""Units coming and going: errors in the registry, data kept when disabled, events ignored for disabled units,
the public endpoints, and uniqueness under simultaneous requests."""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from tests.stock_helpers import INV, make_stock_shop, system
from ziira.kernel.errors import DependencyError, NotFound, ZiiraError


# --------------------------------------------------------------------------- registry errors
def test_registry_refusals(registry) -> None:  # type: ignore[no-untyped-def]
    tenant = make_tenant("Registry Co")
    t = tenant["tenant_id"]
    registry.enable(t, "inventory")
    with pytest.raises(NotFound):
        registry.get("no_such_unit")
    with pytest.raises(NotFound, match="Tenant not found"):
        registry.app_role(uuid4())
    for call in (lambda: registry.uninstall("kernel"), lambda: registry.remove_from_tenant(t, "kernel"),
                 lambda: registry.disable(t, "kernel")):
        with pytest.raises(DependencyError, match="kernel"):
            call()
    with pytest.raises(DependencyError, match="not in this tenant"):
        registry.remove_from_tenant(t, "pos")                                # never enabled here
    with pytest.raises(DependencyError, match="required by"):
        registry.remove_from_tenant(t, "products")                           # inventory needs it
    with pytest.raises(DependencyError, match="disable it first"):
        registry.remove_from_tenant(t, "inventory")
    with pytest.raises(DependencyError, match="required by"):
        registry.disable(t, "products")                                      # an enabled unit requires it
    registry.disable(t, "pos")                                               # not enabled: nothing happens
    assert "inventory" in registry.installed_in(t) and "pos" not in registry.installed_in(t)
    with pytest.raises(ZiiraError):
        registry.enable(t, "no_such_unit")


def test_disabling_keeps_data_and_enabling_again_seeds_nothing_twice(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_stock_shop(client, registry, "Cycle Co")
    owner, co = shop["owner"], str(shop["company_id"])
    client.post(f"{INV}/opening-stock", headers=owner, json={
        "company_id": co, "location_id": shop["main"],
        "lines": [{"product_id": shop["cement"], "quantity": "10", "unit_cost": "5"}]})

    def counts() -> tuple[int, int, int]:
        with system(shop) as s:
            return tuple(s.execute(text(q)).scalar_one() for q in (   # type: ignore[return-value]
                "select count(*) from kernel.reason_code", "select count(*) from kernel.role",
                "select count(*) from kernel.role_permission"))

    before = counts()
    registry.disable(shop["tenant_id"], "inventory")
    r = client.get(f"{INV}/balances", headers=owner)
    assert r.status_code == 404 and r.json()["error"] == "unit_not_enabled"             # off, even for the owner
    # events for a disabled unit are ignored: a sale does not touch the stock
    from ziira.sdk import Event, publish

    with system(shop) as s:
        publish(s, Event("sale.posted", "pos.sale", uuid4(), {
            "company_id": shop["company_id"], "location_id": shop["main"],
            "lines": [{"line_id": uuid4(), "product_id": shop["cement"], "quantity": "3"}]}))
    registry.enable(shop["tenant_id"], "inventory")
    registry.enable(shop["tenant_id"], "inventory")                                      # twice is harmless
    assert counts() == before                                                            # nothing seeded twice
    balances = client.get(f"{INV}/balances", headers=owner).json()
    assert [b["quantity"] for b in balances] == ["10.0000"]                              # data kept, sale ignored
    assert client.get(f"{INV}/locations", headers=shop["cashier"]).status_code == 200    # roles survived too


def test_removing_a_unit_deletes_its_data_and_enabling_starts_fresh(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_stock_shop(client, registry, "Wipe Co")
    registry.disable(shop["tenant_id"], "inventory")
    registry.remove_from_tenant(shop["tenant_id"], "inventory")
    assert "inventory" not in registry.installed_in(shop["tenant_id"])
    registry.enable(shop["tenant_id"], "inventory")
    assert client.get(f"{INV}/locations", headers=shop["owner"]).json() == []           # empty again
    assert client.get(f"{INV}/balances", headers=shop["owner"]).json() == []


# --------------------------------------------------------------------------- public endpoints
def test_public_endpoints(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/docs"
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/no/such/path").status_code == 404
    assert client.get("/api/v1/inventory/balances", headers={"X-Tenant-ID": str(uuid4())}).status_code in (401, 404)


def test_the_units_list_reflects_the_tenant(client, registry) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Units Co")
    owner = sign_in(client, "units-co", "owner@units-co.test").headers
    names = {u["name"]: u["enabled"] for u in client.get("/api/v1/units", headers=owner).json()}
    assert names["kernel"] is True and names["inventory"] is False
    registry.enable(t["tenant_id"], "inventory")
    names = {u["name"]: u["enabled"] for u in client.get("/api/v1/units", headers=owner).json()}
    assert names["inventory"] is True and names["products"] is True                      # what it requires comes along


# --------------------------------------------------------------------------- uniqueness under load
def together(calls):  # type: ignore[no-untyped-def]
    barrier = threading.Barrier(len(calls))

    def run(call):  # type: ignore[no-untyped-def]
        barrier.wait()
        return call()

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(run, calls))


def test_simultaneous_duplicates_leave_one_and_leak_nothing(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_stock_shop(client, registry, "Dup Co")
    owner, co = shop["owner"], str(shop["company_id"])
    product = {"company_id": co, "sku": "RACE-1", "name": "Race", "base_uom_id": shop["uom"],
               "tax_code_id": shop["tax"]}
    location = {"company_id": co, "branch_id": str(shop["branch_id"]), "code": "RACE", "name": "Race"}
    user = {"full_name": "Racer", "email": "racer@dup-co.test", "password": "racer-pass-123"}
    for path, body in (("/api/v1/products/products", product), (f"{INV}/locations", location),
                       ("/api/v1/users", user)):
        results = together([lambda path=path, body=body: client.post(path, headers=owner, json=body)
                            for _ in range(6)])
        assert Counter(r.status_code for r in results) == {201: 1, 409: 5}, path
        for r in results:
            if r.status_code == 409:
                text_ = r.text.lower()
                assert "constraint" not in text_ and "violates" not in text_ and "inventory." not in text_, r.text


def test_the_database_itself_refuses_a_second_open_count(client, registry) -> None:  # type: ignore[no-untyped-def]
    """The rule does not depend on the service: even a direct insert cannot create a second open count."""
    from sqlalchemy.exc import IntegrityError

    from ziira.kernel.db import tenant_session

    shop = make_stock_shop(client, registry, "Index Co")
    loc, tenant = UUID(shop["main"]), shop["tenant_id"]
    insert = ("insert into inventory.stock_count (tenant_id, company_id, number, location_id, status, snapshot_at) "
              "values (:t, :c, :n, :l, :s, now())")
    params = {"t": str(tenant), "c": str(shop["company_id"]), "l": str(loc)}
    with tenant_session(tenant, admin=True) as s:
        s.execute(text(insert), {**params, "n": "X1", "s": "counting"})
        s.execute(text(insert), {**params, "n": "X2", "s": "posted"})            # finished counts do not count
        s.execute(text(insert), {**params, "n": "X3", "s": "cancelled"})
    with pytest.raises(IntegrityError), tenant_session(tenant, admin=True) as s:
        s.execute(text(insert), {**params, "n": "X4", "s": "review"})


def test_upgrading_a_unit_gives_the_owner_its_new_permissions(registry) -> None:  # type: ignore[no-untyped-def]
    """A permission added by a newer version of a unit must reach the Owner of businesses that already use it."""
    from ziira.kernel.db import tenant_session

    t = make_tenant("Upgrade Co")["tenant_id"]
    registry.enable(t, "pos")
    with tenant_session(t, admin=True) as s:
        s.execute(text("delete from kernel.role_permission where permission_code in ('till.review', 'devices.manage') "
                       "and role_id = (select id from kernel.role where name = 'Owner')"))
    registry.install("pos")                                                  # an upgrade run
    with tenant_session(t, admin=True) as s:
        owner_has = set(s.execute(text(
            "select permission_code from kernel.role_permission rp join kernel.role r on r.id = rp.role_id "
            "where r.name = 'Owner' and rp.permission_code in ('till.review', 'devices.manage')")).scalars())
    assert owner_has == {"till.review", "devices.manage"}

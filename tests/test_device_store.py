"""A till's Store: defaulted at registration, required when the branch has several, editable while no till is open,
a plain message at the till when missing; and the defaults a new business starts with (one store per branch, units)."""

from sqlalchemy import text

from tests.conftest import make_tenant
from tests.pos_helpers import INV, POS, make_pos_shop, open_till, sell
from tests.stock_helpers import system


def add_store(client, shop, code: str) -> str:  # type: ignore[no-untyped-def]
    r = client.post(f"{INV}/locations", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "code": code, "name": code})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def register(client, shop, code: str, **extra):  # type: ignore[no-untyped-def]
    return client.post(f"{POS}/devices", headers=shop["owner"], json={
        "branch_id": str(shop["branch_id"]), "code": code, "name": code, **extra})


def test_store_defaults_is_required_and_can_be_changed(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_pos_shop(client, registry, "Pos Dev Store Co")
    owner = shop["owner"]
    only = register(client, shop, "ONE")                       # one store at the branch: it is the default
    assert only.status_code == 201 and only.json()["location_id"] == shop["main"]

    second = add_store(client, shop, "BACK")
    missing = register(client, shop, "TWO")                    # two stores: the person must choose
    assert missing.status_code == 422 and "choose the store" in missing.text
    chosen = register(client, shop, "THREE", location_id=second)
    assert chosen.status_code == 201 and chosen.json()["location_id"] == second

    device = chosen.json()["id"]
    changed = client.patch(f"{POS}/devices/{device}", headers=owner, json={"location_id": shop["main"]})
    assert changed.status_code == 200 and changed.json()["location_id"] == shop["main"]
    with system(shop) as s:
        row = s.execute(text("select count(*) from kernel.audit_log where action = 'set_location' and "
                             "entity_id = :d"), {"d": device}).scalar_one()
    assert row == 1
    assert client.patch(f"{POS}/devices/{device}", headers=owner, json={"location_id": shop["juja_store"]}
                        ).status_code == 422               # another branch's store
    assert client.patch(f"{POS}/devices/{device}", headers=shop["cashier"], json={"location_id": second}
                        ).status_code == 403

    opened = open_till(client, shop, "cashier", device=device)
    assert opened.status_code == 201, opened.text
    refused = client.patch(f"{POS}/devices/{device}", headers=owner, json={"location_id": second})
    assert refused.status_code == 409 and "close it" in refused.text


def test_a_sale_on_a_till_without_a_store_says_what_to_do(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_pos_shop(client, registry, "Pos No Store Co")
    add_store(client, shop, "BACK2")
    device = shop["devices"]["cashier"]
    with system(shop) as s:                                    # a device from before the Store was required
        s.execute(text("update pos.pos_device set location_id = null where id = :d"), {"d": device})
    sale = sell(client, shop)
    assert sale.status_code == 422
    assert "This till has no store set. Ask a manager to set one under Sell > Tills and devices" in sale.text
    fixed = client.patch(f"{POS}/devices/{device}", headers=shop["owner"], json={"location_id": shop["main"]})
    assert fixed.status_code in (200, 409)                     # 409 if the cashier's till is still open
    if fixed.status_code == 409:
        closed = client.post(f"{POS}/tills/{shop['tills']['cashier']}/close", headers=shop["cashier"],
                             json={"counted_cash": "1000.00"})
        assert closed.status_code == 200, closed.text
        fixed = client.patch(f"{POS}/devices/{device}", headers=shop["owner"], json={"location_id": shop["main"]})
    assert fixed.status_code == 200
    assert sell(client, shop).status_code == 201


def test_a_new_business_starts_with_a_store_per_branch_and_some_units(client, registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.seed_store import seed_default_stores
    from ziira.modules.products.services.seed_uoms import seed_default_uoms

    t = make_tenant("Seed Defaults Co")
    registry.enable(t["tenant_id"], "inventory")
    with system(t) as s:
        assert seed_default_stores(s, t["company_id"]) == 1
        assert seed_default_stores(s, t["company_id"]) == 0    # again: nothing changes
        rows = s.execute(text("select code, name, kind from inventory.location")).all()
        assert [(r.code, r.name, r.kind) for r in rows] == [("HQ-MAIN", "Main store", "store")]
        assert seed_default_uoms(s) == 4
        assert seed_default_uoms(s) == 0
        codes = set(s.execute(text("select code from products.uom")).scalars())
        assert codes == {"EACH", "KG", "LITRE", "BOX"}

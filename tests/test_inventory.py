"""Inventory: locations, opening stock, the stock ledger, costing, batches, policies and visibility."""

from decimal import Decimal as Dec
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_stock_shop(client, registry, "Stock Co")


def opening(client, shop, headers=None, **body):  # type: ignore[no-untyped-def]
    return client.post(f"{INV}/opening-stock", headers=headers or shop["owner"],
                       json={"company_id": str(shop["company_id"]), "location_id": shop["main"], **body})


# --------------------------------------------------------------------------- locations
def test_location_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])

    def create(headers, **body):  # type: ignore[no-untyped-def]
        return client.post(f"{INV}/locations", headers=headers, json={"company_id": co, **body})

    assert create(shop["owner"], code="main", name="Dup", kind="store",
                  branch_id=str(shop["branch_id"])).status_code == 409                    # codes are unique
    assert create(shop["owner"], code="NOBRANCH", name="x", kind="store").status_code == 422
    assert create(shop["owner"], code="TR", name="x", kind="transit",
                  branch_id=str(shop["branch_id"])).status_code == 422
    assert create(shop["owner"], code="bad code!", name="x", kind="virtual").status_code == 422
    assert create(shop["owner"], code="TRANSIT", name="In transit", kind="transit").status_code == 201
    # Only people with locations.manage, and only for their branch
    assert create(shop["storekeeper"], code="X1", name="x", branch_id=str(shop["branch_id"])).status_code == 403
    assert create(shop["cashier"], code="X2", name="x", branch_id=str(shop["branch_id"])).status_code == 403
    hq = str(shop["branch_id"])
    assert create(shop["manager"], code="HQ-2", name="Second HQ shelf", branch_id=hq).status_code == 201
    assert create(shop["manager"], code="J-2", name="x", branch_id=str(shop["juja"])).status_code == 403


def test_locations_are_listed_by_scope(client, shop) -> None:  # type: ignore[no-untyped-def]
    def codes(headers):  # type: ignore[no-untyped-def]
        return {loc["code"] for loc in client.get(f"{INV}/locations", headers=headers).json()}

    assert {"MAIN", "JUJA-STORE", "TRANSIT"} <= codes(shop["owner"])
    assert codes(shop["storekeeper"]) == {"MAIN", "HQ-2", "TRANSIT"}        # own branch + company-level only
    assert codes(shop["juja_keeper"]) == {"JUJA-STORE", "TRANSIT"}


# --------------------------------------------------------------------------- opening stock
def test_opening_stock_posts_movements_balances_and_cost(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = opening(client, shop, lines=[{"product_id": shop["cement"], "quantity": "100", "unit_cost": "650"}])
    assert r.status_code == 201, r.text
    m = r.json()[0]
    assert (m["movement_type"], Dec(m["quantity"]), Dec(m["unit_cost"]), Dec(m["value"])) == (
        "opening", 100, 650, 65000)
    stock = client.get(f"{INV}/products/{shop['cement']}/stock", headers=shop["owner"]).json()
    assert (Dec(stock["quantity"]), Dec(stock["average_cost"]), Dec(stock["value"])) == (100, 650, 65000)
    bal = client.get(f"{INV}/balances", headers=shop["owner"], params={"product_id": shop["cement"]}).json()
    assert [(b["location_code"], Dec(b["quantity"]), b["sku"]) for b in bal] == [("MAIN", 100, "CEM")]


def test_opening_stock_is_only_for_a_product_without_history(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = opening(client, shop, lines=[{"product_id": shop["cement"], "quantity": "5", "unit_cost": "700"}])
    assert r.status_code == 409 and "adjustment" in r.json()["message"]


def test_opening_stock_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    line = {"quantity": "1", "unit_cost": "1"}
    assert opening(client, shop, lines=[{"product_id": shop["delivery"], **line}]).status_code == 422   # a service
    assert opening(client, shop, lines=[{"product_id": shop["paint"], **line}]).status_code == 422      # needs a batch
    assert opening(client, shop, lines=[{"product_id": str(uuid4()), **line}]).status_code == 422
    assert opening(client, shop, lines=[{"product_id": shop["cement"], "quantity": "0", "unit_cost": "1"}]
                   ).status_code == 422
    assert opening(client, shop, lines=[{"product_id": shop["cement"], "quantity": "1.00001", "unit_cost": "1"}]
                   ).status_code == 422
    r = client.post(f"{INV}/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": str(uuid4()),
        "lines": [{"product_id": shop["cement"], **line}]})
    assert r.status_code == 422


def test_opening_stock_needs_permission_for_the_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    line = [{"product_id": shop["cement"], "quantity": "1", "unit_cost": "1"}]
    assert opening(client, shop, shop["cashier"], lines=line).status_code == 403
    assert opening(client, shop, shop["juja_keeper"], lines=line).status_code == 403     # wrong branch


def test_batch_tracked_opening_stock_and_first_expiry_first_out(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = opening(client, shop, lines=[
        {"product_id": shop["paint"], "quantity": "5", "unit_cost": "400", "batch_no": "B-LATE",
         "expiry_date": "2027-06-01"},
        {"product_id": shop["paint"], "quantity": "5", "unit_cost": "400", "batch_no": "B-EARLY",
         "expiry_date": "2027-01-01"}])
    assert r.status_code == 201, r.text
    from ziira.modules.inventory.services.ledger import MovementRequest, post_stock_out

    with system(shop) as s:
        posted = post_stock_out(s, MovementRequest(
            company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(shop["paint"]),
            quantity=Dec("-7"), movement_type="sale", source_type="test_sale", source_id=uuid4()))
        picks = [(m.quantity, m.batch_id) for m in posted]
    bal = {b["batch_id"]: Dec(b["quantity"]) for b in client.get(
        f"{INV}/balances", headers=shop["owner"], params={"product_id": shop["paint"]}).json()}
    assert [q for q, _ in picks] == [Dec("-5"), Dec("-2")]               # B-EARLY first, then B-LATE
    assert sorted(bal.values()) == [3]                                   # B-EARLY is gone (zero rows hidden)


# --------------------------------------------------------------------------- the ledger
def sell(shop, quantity: str, **kw):  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    with system(shop) as s:
        return post_movement(s, MovementRequest(
            company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(shop["cement"]),
            quantity=-Dec(quantity), movement_type=kw.pop("movement_type", "sale"), source_type="test_sale",
            source_id=uuid4(), **kw))


def events(shop, event_type: str) -> int:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select count(*) from kernel.event_outbox where event_type = :e"),
                         {"e": event_type}).scalar_one()


def test_a_sale_takes_the_average_cost_and_publishes_events(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = events(shop, "stock.moved")
    m = sell(shop, "20")
    assert (m.quantity, m.unit_cost, m.value) == (Dec("-20"), Dec("650"), Dec("-13000"))
    stock = client.get(f"{INV}/products/{shop['cement']}/stock", headers=shop["owner"]).json()
    assert (Dec(stock["quantity"]), Dec(stock["value"])) == (80, 52000)
    assert events(shop, "stock.moved") == before + 1


def test_below_reorder_is_published_once_when_the_level_is_crossed(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = events(shop, "stock.below_reorder")
    sell(shop, "60")                                    # 80 -> 20: still above the level of 10
    assert events(shop, "stock.below_reorder") == before
    sell(shop, "11")                                    # 20 -> 9: crosses
    assert events(shop, "stock.below_reorder") == before + 1
    sell(shop, "1")                                     # 9 -> 8: already below, no repeat
    assert events(shop, "stock.below_reorder") == before + 1


def test_selling_more_than_there_is_is_blocked_by_default(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import ValidationFailed

    with pytest.raises(ValidationFailed, match="Not enough stock: 8 on hand, 9 needed"):
        sell(shop, "9")
    assert Dec(client.get(f"{INV}/products/{shop['cement']}/stock", headers=shop["owner"]).json()["quantity"]) == 8


def test_negative_stock_policy_lets_a_sale_through_and_raises_an_exception(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                     json={"negative_stock_allowed": True})
    assert r.status_code == 200
    before = events(shop, "stock.negative")
    m = sell(shop, "10")                                # 8 -> -2, at the last average
    assert m.unit_cost == Dec("650")
    assert events(shop, "stock.negative") == before + 1
    # The policy covers sales only: other outgoing movements never go below zero
    from ziira.sdk import ValidationFailed

    with pytest.raises(ValidationFailed, match="Not enough stock"):
        sell(shop, "1", movement_type="write_off", reason_code_id=_reason(shop, "write_off"))
    # A receipt then fixes the quantity; the cost is the weighted average of the net quantities
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    with system(shop) as s:
        post_movement(s, MovementRequest(
            company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(shop["cement"]),
            quantity=Dec("12"), movement_type="receipt", source_type="test_receipt", source_id=uuid4(),
            unit_cost=Dec("700")))
    stock = client.get(f"{INV}/products/{shop['cement']}/stock", headers=shop["owner"]).json()
    # value -1300 + 12 x 700 = 7100 over 10 units: the shortage is costed into the new average
    assert (Dec(stock["quantity"]), Dec(stock["value"]), Dec(stock["average_cost"])) == (10, 7100, 710)
    client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                 json={"negative_stock_allowed": False})


def _reason(shop, category: str) -> UUID:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select id from kernel.reason_code where category = :c order by code limit 1"),
                         {"c": category}).scalar_one()


def test_reasons_are_required_where_the_rules_say(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import ValidationFailed

    with pytest.raises(ValidationFailed, match="reason is required"):
        sell(shop, "1", movement_type="write_off")
    assert sell(shop, "1", movement_type="write_off", reason_code_id=_reason(shop, "write_off")).value < 0


def test_the_ledger_cannot_be_changed(shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError, match="immutable"), system(shop) as s:
        s.execute(text("update inventory.stock_movement set quantity = 1"))


def test_balances_equal_the_sum_of_movements(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        rows = s.execute(text(
            "select b.quantity as bal, coalesce((select sum(m.quantity) from inventory.stock_movement m "
            "where m.location_id = b.location_id and m.product_id = b.product_id "
            "and m.batch_id is not distinct from b.batch_id), 0) as moved from inventory.stock_balance b")).all()
        cost = s.execute(text(
            "select c.quantity, c.value, (select sum(m.quantity) from inventory.stock_movement m "
            "where m.product_id = c.product_id and m.company_id = c.company_id) as moved_q, "
            "(select sum(m.value) from inventory.stock_movement m where m.product_id = c.product_id "
            "and m.company_id = c.company_id) as moved_v from inventory.product_cost c")).all()
    assert rows and all(r.bal == r.moved for r in rows)
    assert cost and all(c.quantity == c.moved_q and c.value == c.moved_v for c in cost)


# --------------------------------------------------------------------------- who sees what
def test_costs_are_hidden_without_the_cost_permission(client, shop) -> None:  # type: ignore[no-untyped-def]
    mv = client.get(f"{INV}/movements", headers=shop["cashier"], params={"product_id": shop["cement"]}).json()
    assert mv and all(m["unit_cost"] is None and m["value"] is None for m in mv)
    mv = client.get(f"{INV}/movements", headers=shop["manager"], params={"product_id": shop["cement"]}).json()
    assert all(m["unit_cost"] is not None for m in mv)
    own = client.get(f"{INV}/products/{shop['cement']}/stock", headers=shop["cashier"]).json()
    assert own["average_cost"] is None and own["value"] is None and Dec(own["quantity"]) == 9


def test_stock_is_visible_only_for_branches_the_user_may_see(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.get(f"{INV}/balances", headers=shop["juja_keeper"]).json() == []
    assert client.get(f"{INV}/movements", headers=shop["juja_keeper"]).json() == []
    assert client.get(f"{INV}/balances", headers=shop["storekeeper"]).json() != []
    other_branch = {"branch_id": str(shop["juja"])}
    assert client.get(f"{INV}/balances", headers=shop["storekeeper"], params=other_branch).json() == []


def test_the_module_requires_its_permission(client, shop, tenants) -> None:  # type: ignore[no-untyped-def]
    assert client.get(f"{INV}/balances").status_code in (401, 403)

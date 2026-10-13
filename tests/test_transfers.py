"""Transfers: dispatch to in-transit, receipt at the destination, differences, approval, scope, costing."""

from decimal import Decimal as Dec
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Transfer Co")
    co = str(s["company_id"])
    r = client.post(f"{INV}/opening-stock", headers=s["owner"], json={
        "company_id": co, "location_id": s["main"],
        "lines": [{"product_id": s["cement"], "quantity": "100", "unit_cost": "100"},
                  {"product_id": s["paint"], "quantity": "10", "unit_cost": "50", "batch_no": "B1",
                   "expiry_date": "2027-03-01"}]})
    assert r.status_code == 201, r.text
    reasons = client.get("/api/v1/settings/reason-codes", headers=s["owner"]).json()
    s["short"] = next(x["id"] for x in reasons if x["category"] == "transfer_variance" and x["code"] == "SHORT_SHIPPED")
    s["juja_manager"] = s["user"]("jujamanager", "Branch Manager", s["juja"])
    with system(s) as db:
        s["batch"] = str(db.execute(text("select id from inventory.batch where batch_no = 'B1'")).scalar_one())
    return s


def qty(shop, location: str, product: str = "cement") -> Dec:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text(
            "select coalesce(sum(b.quantity), 0) from inventory.stock_balance b "
            "join inventory.location l on l.id = b.location_id where b.product_id = :p and l.code = :c"),
            {"p": shop[product], "c": location}).scalar_one()


def pool(shop, product: str = "cement"):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        row = s.execute(text("select quantity, value, average_cost from inventory.product_cost where product_id = :p"),
                        {"p": shop[product]}).one()
    return row.quantity, row.value, row.average_cost


def new_transfer(client, shop, lines, headers=None, source="main", target="juja_store"):  # type: ignore[no-untyped-def]
    return client.post(f"{INV}/transfers", headers=headers or shop["storekeeper"], json={
        "company_id": str(shop["company_id"]), "from_location_id": shop[source], "to_location_id": shop[target],
        "lines": lines})


def cement_line(shop, quantity: str):  # type: ignore[no-untyped-def]
    return {"product_id": shop["cement"], "quantity": quantity}


def act(client, shop, transfer_id, action, headers=None, **body):  # type: ignore[no-untyped-def]
    return client.post(f"{INV}/transfers/{transfer_id}/{action}", headers=headers or shop["storekeeper"],
                       json=body or None)


# --------------------------------------------------------------------------- drafts
def test_a_draft_moves_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = new_transfer(client, shop, [cement_line(shop, "10")])
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "draft" and t["number"] == "TRF-HQ-000001" and t["lines"][0]["qty_sent"] == "10.0000"
    assert qty(shop, "MAIN") == 100


def test_draft_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert new_transfer(client, shop, [cement_line(shop, "10")], target="main").status_code == 422     # same place
    assert new_transfer(client, shop, [cement_line(shop, "0")]).status_code == 422
    assert new_transfer(client, shop, [cement_line(shop, "1"), cement_line(shop, "2")]).status_code == 422
    assert new_transfer(client, shop, [{"product_id": shop["paint"], "quantity": "1"}]).status_code == 422   # batch
    assert new_transfer(client, shop, [{"product_id": shop["delivery"], "quantity": "1"}]).status_code == 422
    assert new_transfer(client, shop, []).status_code == 422


def test_creating_needs_transfer_permission_at_the_source(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert new_transfer(client, shop, [cement_line(shop, "1")], headers=shop["cashier"]).status_code == 403
    assert new_transfer(client, shop, [cement_line(shop, "1")], headers=shop["juja_keeper"]).status_code == 403


# --------------------------------------------------------------------------- the normal journey
def test_dispatch_then_receive_everything(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = new_transfer(client, shop, [cement_line(shop, "30")]).json()
    r = act(client, shop, t["id"], "dispatch")
    assert r.status_code == 200 and r.json()["status"] == "dispatched" and r.json()["dispatched_by"]
    assert (qty(shop, "MAIN"), qty(shop, "TRANSIT"), qty(shop, "JUJA-STORE")) == (70, 30, 0)
    assert pool(shop)[0] == 100                                  # the company still has all of it
    assert act(client, shop, t["id"], "dispatch").status_code == 409                       # only once

    # Only people at the destination can receive it
    assert act(client, shop, t["id"], "receive", headers=shop["storekeeper"]).status_code == 403
    r = act(client, shop, t["id"], "receive", headers=shop["juja_keeper"])
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "received" and [x["qty_received"] for x in done["lines"]] == ["30.0000"]
    assert (qty(shop, "MAIN"), qty(shop, "TRANSIT"), qty(shop, "JUJA-STORE")) == (70, 0, 30)
    assert pool(shop) == (100, Dec("10000"), Dec("100"))         # value and cost untouched
    assert act(client, shop, t["id"], "receive", headers=shop["juja_keeper"]).status_code == 409


def test_the_destination_stock_keeps_the_cost_it_left_with(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    t = new_transfer(client, shop, [cement_line(shop, "10")]).json()
    act(client, shop, t["id"], "dispatch")
    with system(shop) as s:                    # the company's average cost changes while the stock is on the road
        post_movement(s, MovementRequest(
            company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(shop["cement"]),
            quantity=Dec("10"), movement_type="receipt",
            source_type="test_receipt", source_id=uuid4(), unit_cost=Dec("200")))
    assert pool(shop)[2] != 100
    act(client, shop, t["id"], "receive", headers=shop["juja_keeper"])
    with system(shop) as s:
        costs = s.execute(text(
            "select m.movement_type, l.code, m.unit_cost, m.value from inventory.stock_movement m "
            "join inventory.location l on l.id = m.location_id where m.source_id = :t"), {"t": t["id"]}).all()
    assert sorted((c.movement_type, c.code, c.unit_cost) for c in costs) == sorted([
        ("transfer_out", "MAIN", 100), ("transfer_in", "TRANSIT", 100),
        ("transfer_out", "TRANSIT", 100), ("transfer_in", "JUJA-STORE", 100)])    # all at the dispatch cost
    assert sum(c.value for c in costs) == 0


def test_not_enough_stock_blocks_the_dispatch(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = new_transfer(client, shop, [cement_line(shop, "9999")]).json()
    r = act(client, shop, t["id"], "dispatch")
    assert r.status_code == 422 and "Not enough stock" in r.json()["message"]
    assert client.get(f"{INV}/transfers/{t['id']}", headers=shop["storekeeper"]).json()["status"] == "draft"


def test_drafts_can_be_cancelled_but_dispatched_transfers_cannot(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = new_transfer(client, shop, [cement_line(shop, "1")]).json()
    assert act(client, shop, t["id"], "cancel").json()["status"] == "cancelled"
    assert act(client, shop, t["id"], "dispatch").status_code == 409
    t = new_transfer(client, shop, [cement_line(shop, "1")]).json()
    act(client, shop, t["id"], "dispatch")
    assert act(client, shop, t["id"], "cancel").status_code == 409
    act(client, shop, t["id"], "receive", headers=shop["juja_keeper"])


def test_batch_tracked_transfers_name_their_batch(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = new_transfer(client, shop, [{"product_id": shop["paint"], "quantity": "4", "batch_id": shop["batch"]}]).json()
    act(client, shop, t["id"], "dispatch")
    act(client, shop, t["id"], "receive", headers=shop["juja_keeper"])
    assert (qty(shop, "MAIN", "paint"), qty(shop, "JUJA-STORE", "paint")) == (6, 4)


# --------------------------------------------------------------------------- differences
def dispatched(client, shop, quantity: str):  # type: ignore[no-untyped-def]
    t = new_transfer(client, shop, [cement_line(shop, quantity)]).json()
    assert act(client, shop, t["id"], "dispatch").status_code == 200
    return t


def arrived(t, quantity: str, reason=None):  # type: ignore[no-untyped-def]
    return {"lines": [{"line_id": t["lines"][0]["id"], "qty_received": quantity, "reason_code_id": reason}]}


def test_a_difference_needs_a_reason(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = dispatched(client, shop, "10")
    r = act(client, shop, t["id"], "receive", headers=shop["juja_keeper"], **arrived(t, "8"))
    assert r.status_code == 422
    r = act(client, shop, t["id"], "receive", headers=shop["juja_keeper"], **arrived(t, "8", str(uuid4())))
    assert r.status_code == 422                                                       # not a real reason
    assert act(client, shop, t["id"], "receive", headers=shop["juja_keeper"],
               **{"lines": [{"line_id": str(uuid4()), "qty_received": "10"}]}).status_code == 422
    assert client.get(f"{INV}/transfers/{t['id']}", headers=shop["owner"]).json()["status"] == "dispatched"
    act(client, shop, t["id"], "receive", headers=shop["juja_keeper"])               # finish it: all 10 arrived


def test_short_delivery_without_an_approval_rule_writes_off_the_missing_stock(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = pool(shop)
    juja_before = qty(shop, "JUJA-STORE")
    t = dispatched(client, shop, "10")
    r = act(client, shop, t["id"], "receive", headers=shop["juja_keeper"], **arrived(t, "7", shop["short"]))
    assert r.status_code == 200 and r.json()["status"] == "received"
    assert qty(shop, "JUJA-STORE") == juja_before + 7 and qty(shop, "TRANSIT") == 0
    after = pool(shop)
    assert after[0] == before[0] - 3 and after[1] == before[1] - round(3 * before[2], 2)   # lost at the average cost
    with system(shop) as s:
        loss = s.execute(text("select quantity, reason_code_id from inventory.stock_movement "
                              "where source_id = :t and movement_type = 'write_off'"), {"t": t["id"]}).one()
    assert (loss.quantity, str(loss.reason_code_id)) == (-3, shop["short"])


def test_more_than_was_sent_arrives_as_an_adjustment(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = pool(shop)
    t = dispatched(client, shop, "10")
    r = act(client, shop, t["id"], "receive", headers=shop["juja_keeper"], **arrived(t, "12", shop["short"]))
    assert r.status_code == 200 and r.json()["status"] == "received"
    assert pool(shop)[0] == before[0] + 2 and qty(shop, "TRANSIT") == 0


def test_nothing_arrived(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = pool(shop)
    t = dispatched(client, shop, "5")
    r = act(client, shop, t["id"], "receive", headers=shop["juja_keeper"], **arrived(t, "0", shop["short"]))
    assert r.status_code == 200, r.text
    assert pool(shop)[0] == before[0] - 5 and qty(shop, "TRANSIT") == 0


# --------------------------------------------------------------------------- approval of differences
@pytest.fixture(scope="module")
def rule(client, shop):  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "transfer",
        "approver_role_id": shop["roles"]["Branch Manager"], "min_amount": "100"})
    assert r.status_code == 201, r.text


def pending(client, shop, doc_id):  # type: ignore[no-untyped-def]
    return next(r for r in client.get("/api/v1/approvals/pending", headers=shop["boss"]).json()
                if r["doc_id"] == doc_id)


def test_a_difference_waits_for_approval_then_posts(client, shop, rule) -> None:  # type: ignore[no-untyped-def]
    before = pool(shop)
    t = dispatched(client, shop, "10")
    r = act(client, shop, t["id"], "receive", headers=shop["juja_keeper"], **arrived(t, "6", shop["short"]))
    assert r.json()["status"] == "pending_approval"
    assert qty(shop, "TRANSIT") == 10 and pool(shop) == (before[0], before[1], before[2])   # nothing posted yet
    request = pending(client, shop, t["id"])
    assert Dec(request["amount"]) == round(4 * before[2], 2)                                 # 4 units at the cost
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["juja_manager"],
                       json={"approve": True}).status_code == 403                            # branch-level: not enough
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["boss"], json={"approve": True})
    assert r.status_code == 200, r.text
    done = client.get(f"{INV}/transfers/{t['id']}", headers=shop["owner"]).json()
    assert done["status"] == "received" and done["received_by"] is not None
    assert qty(shop, "TRANSIT") == 0 and pool(shop)[0] == before[0] - 4


def test_a_rejected_receipt_goes_back_to_be_counted_again(client, shop, rule) -> None:  # type: ignore[no-untyped-def]
    t = dispatched(client, shop, "10")
    act(client, shop, t["id"], "receive", headers=shop["juja_keeper"], **arrived(t, "2", shop["short"]))
    request = pending(client, shop, t["id"])
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["boss"],
                    json={"approve": False, "note": "Count again"})
    assert r.status_code == 200
    back = client.get(f"{INV}/transfers/{t['id']}", headers=shop["owner"]).json()
    assert back["status"] == "dispatched" and back["lines"][0]["qty_received"] is None
    assert qty(shop, "TRANSIT") == 10
    done = act(client, shop, t["id"], "receive", headers=shop["juja_keeper"])               # it all arrived
    assert done.json()["status"] == "received"


def test_receiving_exactly_what_was_sent_never_needs_approval(client, shop, rule) -> None:  # type: ignore[no-untyped-def]
    t = dispatched(client, shop, "10")
    assert act(client, shop, t["id"], "receive", headers=shop["juja_keeper"]).json()["status"] == "received"


# --------------------------------------------------------------------------- who sees what
def test_transfers_are_visible_to_both_ends_only(client, shop) -> None:  # type: ignore[no-untyped-def]
    t = new_transfer(client, shop, [cement_line(shop, "1")]).json()
    assert client.get(f"{INV}/transfers/{t['id']}", headers=shop["juja_keeper"]).status_code == 200   # destination
    assert client.get(f"{INV}/transfers/{t['id']}", headers=shop["storekeeper"]).status_code == 200   # source
    third = shop["user"]("thirdparty", "Storekeeper", None)                                          # company-wide
    assert client.get(f"{INV}/transfers/{t['id']}", headers=third).status_code == 200
    assert client.get(f"{INV}/transfers/{uuid4()}", headers=shop["owner"]).status_code == 404


def test_the_ledger_still_balances(shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        bad = s.execute(text(
            "select count(*) from inventory.stock_balance b where b.quantity <> coalesce((select sum(m.quantity) "
            "from inventory.stock_movement m where m.location_id = b.location_id and m.product_id = b.product_id "
            "and m.batch_id is not distinct from b.batch_id), 0)")).scalar_one()
        pool_bad = s.execute(text(
            "select count(*) from inventory.product_cost c where c.value <> (select sum(m.value) from "
            "inventory.stock_movement m where m.product_id = c.product_id and m.company_id = c.company_id)"
        )).scalar_one()
    assert bad == 0 and pool_bad == 0

"""Stock counts: snapshot, counting while sales continue, reasons, threshold and approval, posting."""

from decimal import Decimal as Dec
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import INV, make_stock_shop, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Count Co")
    co = str(s["company_id"])
    r = client.post(f"{INV}/opening-stock", headers=s["owner"], json={
        "company_id": co, "location_id": s["main"],
        "lines": [{"product_id": s["cement"], "quantity": "100", "unit_cost": "100"},
                  {"product_id": s["paint"], "quantity": "10", "unit_cost": "50", "batch_no": "B1",
                   "expiry_date": "2027-03-01"}]})
    assert r.status_code == 201, r.text
    reasons = client.get("/api/v1/settings/reason-codes", headers=s["owner"]).json()
    s["reason"] = next(x["id"] for x in reasons if x["category"] == "count_variance" and x["code"] == "COUNT_ERROR")
    s["nails"] = client.post("/api/v1/products/products", headers=s["owner"], json={
        "company_id": co, "sku": "NAILS", "name": "Nails", "base_uom_id": s["uom"], "tax_code_id": s["tax"]}
    ).json()["id"]
    with system(s) as db:
        s["batch"] = str(db.execute(text("select id from inventory.batch where batch_no = 'B1'")).scalar_one())
    return s


def start(client, shop, headers=None, **body):  # type: ignore[no-untyped-def]
    return client.post(f"{INV}/counts", headers=headers or shop["storekeeper"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"], **body})


def do(client, shop, count_id, action, headers=None, **body):  # type: ignore[no-untyped-def]
    return client.post(f"{INV}/counts/{count_id}/{action}", headers=headers or shop["storekeeper"], json=body or None)


def entry(shop, product: str, counted: str, **extra):  # type: ignore[no-untyped-def]
    return {"product_id": shop[product], "counted_qty": counted, **extra}


def sell(shop, quantity: str, product: str = "cement") -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    with system(shop) as s:
        post_movement(s, MovementRequest(
            company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(shop[product]),
            quantity=-Dec(quantity), movement_type="sale", source_type="test_sale", source_id=uuid4()))


def stock(shop, product: str = "cement") -> Dec:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text("select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = :p"),
                         {"p": shop[product]}).scalar_one()


def lines_by_product(shop, count) -> dict[str, dict]:  # type: ignore[no-untyped-def]
    names = {shop["cement"]: "cement", shop["paint"]: "paint", shop["nails"]: "nails"}
    return {names[x["product_id"]]: x for x in count["lines"]}


# --------------------------------------------------------------------------- starting
def test_starting_a_count_takes_a_snapshot(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = start(client, shop)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "counting" and c["number"] == "CNT-HQ-000001"
    lines = lines_by_product(shop, c)
    assert Dec(lines["cement"]["expected_qty"]) == 100 and Dec(lines["paint"]["expected_qty"]) == 10
    assert lines["cement"]["counted_qty"] is None
    assert start(client, shop).status_code == 409                          # one count at a time per location
    do(client, shop, c["id"], "cancel")


def test_who_may_start_a_count(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert start(client, shop, headers=shop["cashier"]).status_code == 403
    assert start(client, shop, headers=shop["juja_keeper"]).status_code == 403             # other branch
    assert start(client, shop, location_id=str(uuid4())).status_code == 422


def test_a_count_can_cover_only_some_products(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = start(client, shop, product_ids=[shop["cement"]]).json()
    assert list(lines_by_product(shop, c)) == ["cement"]
    do(client, shop, c["id"], "cancel")


# --------------------------------------------------------------------------- counting while the shop trades
def test_variance_is_against_what_the_system_held_at_counting(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = start(client, shop).json()
    sell(shop, "5")                                       # a sale before the shelf is counted: 100 -> 95
    r = do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", "93")])
    assert r.status_code == 200, r.text
    cement = lines_by_product(shop, r.json())["cement"]
    assert Dec(cement["expected_qty"]) == 100 and Dec(cement["variance_qty"]) == -2       # 93 against 95, not 100
    sell(shop, "4")                                       # a sale after counting: the variance does not change
    again = client.get(f"{INV}/counts/{c['id']}", headers=shop["manager"]).json()
    assert Dec(lines_by_product(shop, again)["cement"]["variance_qty"]) == -2
    do(client, shop, c["id"], "cancel")


def test_recounting_replaces_the_earlier_figure(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = start(client, shop, product_ids=[shop["cement"]]).json()
    do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", "50")])
    r = do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", stock(shop).to_eng_string())])
    assert Dec(lines_by_product(shop, r.json())["cement"]["variance_qty"]) == 0
    do(client, shop, c["id"], "cancel")


def test_entry_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = start(client, shop).json()
    assert do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", "-1")]).status_code == 422
    assert do(client, shop, c["id"], "entries", entries=[entry(shop, "paint", "3")]).status_code == 422   # which batch?
    assert do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", "1"), entry(shop, "cement", "2")]
              ).status_code == 422
    assert do(client, shop, c["id"], "entries", entries=[entry(shop, "delivery", "1")]).status_code == 422   # a service
    assert do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", "1", reason_code_id=str(uuid4()))]
              ).status_code == 422
    assert do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", "1")], headers=shop["cashier"]
              ).status_code == 403
    do(client, shop, c["id"], "cancel")


# --------------------------------------------------------------------------- finishing and submitting
def test_a_count_with_differences_needs_reasons_then_posts(client, shop) -> None:  # type: ignore[no-untyped-def]
    now = stock(shop)
    c = start(client, shop).json()
    do(client, shop, c["id"], "entries", entries=[
        entry(shop, "cement", (now - 3).to_eng_string()),                      # 3 short
        entry(shop, "paint", "10", batch_id=shop["batch"]),                    # correct
        entry(shop, "nails", "7")])                                            # found: not in the snapshot
    assert do(client, shop, c["id"], "submit").status_code == 409              # still counting: finish it first
    done = do(client, shop, c["id"], "finish").json()
    assert done["status"] == "review"
    assert do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", "1")]).status_code == 409   # closed
    lines = lines_by_product(shop, done)
    assert Dec(lines["nails"]["expected_qty"]) == 0 and Dec(lines["nails"]["variance_qty"]) == 7

    r = do(client, shop, c["id"], "submit")
    assert r.status_code == 422 and "need a reason" in r.json()["message"]
    reasons = [{"line_id": lines["cement"]["id"], "reason_code_id": shop["reason"]},
               {"line_id": lines["nails"]["id"], "reason_code_id": shop["reason"]}]
    r = do(client, shop, c["id"], "submit", reasons=reasons)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "posted"                                      # no approval rule applies
    assert stock(shop) == now - 3 and stock(shop, "nails") == 7 and stock(shop, "paint") == 10
    with system(shop) as s:
        moves = s.execute(text("select movement_type, quantity, reason_code_id, value from inventory.stock_movement "
                               "where source_id = :c order by quantity"), {"c": c["id"]}).all()
    assert [(m.movement_type, m.quantity) for m in moves] == [("count_variance", -3), ("count_variance", 7)]
    assert all(str(m.reason_code_id) == shop["reason"] for m in moves)
    assert moves[0].value == -300 and moves[1].value == 0                      # found nails have no cost yet


def test_lines_nobody_counted_are_left_alone_or_counted_as_zero(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = start(client, shop, product_ids=[shop["cement"], shop["paint"]]).json()
    done = do(client, shop, c["id"], "finish").json()                          # nothing counted
    assert all(x["variance_qty"] is None for x in done["lines"])
    assert do(client, shop, c["id"], "submit").json()["status"] == "posted"    # no differences: nothing to post
    c = start(client, shop, product_ids=[shop["paint"]]).json()
    done = do(client, shop, c["id"], "finish", uncounted_as_zero=True).json()
    assert Dec(done["lines"][0]["counted_qty"]) == 0 and Dec(done["lines"][0]["variance_qty"]) == -10
    do(client, shop, c["id"], "cancel")


def test_cancelling_changes_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = stock(shop)
    c = start(client, shop).json()
    do(client, shop, c["id"], "entries", entries=[entry(shop, "cement", "1")])
    assert do(client, shop, c["id"], "cancel").json()["status"] == "cancelled"
    assert stock(shop) == before and do(client, shop, c["id"], "submit").status_code == 409


# --------------------------------------------------------------------------- threshold and approval
def settings(client, shop, **body):  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"], json=body)
    assert r.status_code == 200, r.text


def counted_short(client, shop, units: int):  # type: ignore[no-untyped-def]
    c = start(client, shop, product_ids=[shop["cement"]]).json()
    do(client, shop, c["id"], "entries", entries=[
        entry(shop, "cement", (stock(shop) - units).to_eng_string(), reason_code_id=shop["reason"])])
    do(client, shop, c["id"], "finish")
    return c


def test_only_differences_above_the_threshold_wait_for_approval(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "stock_count",
        "approver_role_id": shop["roles"]["Branch Manager"]})
    settings(client, shop, count_variance_threshold="1000")
    before = stock(shop)

    small = counted_short(client, shop, 5)                                     # 500: within the threshold
    assert do(client, shop, small["id"], "submit").json()["status"] == "posted"
    assert stock(shop) == before - 5

    big = counted_short(client, shop, 20)                                      # 2,000: above it
    r = do(client, shop, big["id"], "submit")
    assert r.json()["status"] == "pending_approval" and stock(shop) == before - 5
    request = next(x for x in client.get("/api/v1/approvals/pending", headers=shop["boss"]).json()
                   if x["doc_id"] == big["id"])
    assert Dec(request["amount"]) == 2000
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["storekeeper"],
                       json={"approve": True}).status_code == 403
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["boss"], json={"approve": True})
    assert r.status_code == 200, r.text
    done = client.get(f"{INV}/counts/{big['id']}", headers=shop["manager"]).json()
    assert done["status"] == "posted" and done["approved_by"] is not None
    assert stock(shop) == before - 25


def test_a_rejected_count_goes_back_to_review(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = stock(shop)
    c = counted_short(client, shop, 30)
    do(client, shop, c["id"], "submit")
    request = next(x for x in client.get("/api/v1/approvals/pending", headers=shop["boss"]).json()
                   if x["doc_id"] == c["id"])
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["boss"],
                    json={"approve": False, "note": "Recount the back shelf"})
    assert r.status_code == 200
    assert client.get(f"{INV}/counts/{c['id']}", headers=shop["manager"]).json()["status"] == "review"
    assert stock(shop) == before
    assert do(client, shop, c["id"], "cancel").json()["status"] == "cancelled"


def test_counts_are_visible_only_to_their_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    c = start(client, shop).json()
    assert client.get(f"{INV}/counts/{c['id']}", headers=shop["juja_keeper"]).status_code == 404
    assert client.get(f"{INV}/counts", headers=shop["juja_keeper"]).json() == []
    assert any(x["id"] == c["id"] for x in client.get(f"{INV}/counts", headers=shop["storekeeper"]).json())
    do(client, shop, c["id"], "cancel")

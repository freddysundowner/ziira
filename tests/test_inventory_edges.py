"""Inventory edge cases: another company in the same business, inactive things, wrong references, boundaries."""

from decimal import Decimal as Dec
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.conftest import sign_in
from tests.stock_helpers import INV, P, make_stock_shop, system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Edge Co")
    co = str(s["company_id"])
    # A second company of the same business, with its own branch, location, product and manager
    co2, br2 = uuid4(), uuid4()
    with system(s) as db:
        db.execute(text("insert into kernel.company (id, tenant_id, name) values (:i, :t, 'Second Ltd')"),
                   {"i": str(co2), "t": str(s["tenant_id"])})
        db.execute(text("insert into kernel.branch (id, tenant_id, company_id, code, name) "
                        "values (:i, :t, :c, 'S1', 'Second shop')"), {"i": str(br2), "t": str(s["tenant_id"]),
                                                                       "c": str(co2)})
    s["co2"], s["br2"] = str(co2), str(br2)
    owner = s["owner"]
    s["loc2"] = client.post(f"{INV}/locations", headers=owner, json={
        "company_id": s["co2"], "branch_id": s["br2"], "code": "SHOP2", "name": "Second shop"}).json()["id"]
    s["prod2"] = client.post(f"{P}/products", headers=owner, json={
        "company_id": s["co2"], "sku": "P2", "name": "Other company product", "base_uom_id": s["uom"],
        "tax_code_id": s["tax"]}).json()["id"]
    s["manager2"] = s["user"]("manager2", "Branch Manager", None)
    # re-scope: manager2 is company-wide for company 1 by default; give them company 2 only
    users = client.get("/api/v1/users", headers=owner).json()
    uid = next(u["id"] for u in users if u["email"] == f"manager2@{s['code']}.test")
    for g in client.get(f"/api/v1/users/{uid}/roles", headers=owner).json():
        client.delete(f"/api/v1/users/{uid}/roles/{g['id']}", headers=owner)
    client.post(f"/api/v1/users/{uid}/roles", headers=owner, json={
        "role_id": s["roles"]["Branch Manager"], "scope": "company", "company_id": s["co2"]})
    s["manager2"] = sign_in(client, s["code"], f"manager2@{s['code']}.test", "manager2-pass-1").headers
    for loc, prod, company in ((s["main"], s["cement"], co), (s["loc2"], s["prod2"], s["co2"])):
        r = client.post(f"{INV}/opening-stock", headers=owner, json={
            "company_id": company, "location_id": loc, "lines": [{"product_id": prod, "quantity": "50",
                                                                 "unit_cost": "10"}]})
        assert r.status_code == 201, r.text
    reasons = client.get("/api/v1/settings/reason-codes", headers=owner).json()
    s["reason"] = next(x["id"] for x in reasons if x["category"] == "stock_adjustment" and x["code"] == "FOUND")
    s["count_reason"] = next(x["id"] for x in reasons if x["category"] == "count_variance")
    s["variance_reason"] = next(x["id"] for x in reasons if x["category"] == "transfer_variance")
    return s


# --------------------------------------------------------------------------- one business, two companies
def test_documents_cannot_mix_two_companies(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co, co2 = shop["owner"], str(shop["company_id"]), shop["co2"]
    adjust = f"{INV}/adjustments"
    base = {"reason_code_id": shop["reason"]}
    assert client.post(adjust, headers=owner, json={**base, "company_id": co, "location_id": shop["loc2"],
                       "lines": [{"product_id": shop["cement"], "qty_change": "1"}]}).status_code == 422
    assert client.post(adjust, headers=owner, json={**base, "company_id": co, "location_id": shop["main"],
                       "lines": [{"product_id": shop["prod2"], "qty_change": "1"}]}).status_code == 422
    assert client.post(f"{INV}/transfers", headers=owner, json={
        "company_id": co, "from_location_id": shop["main"], "to_location_id": shop["loc2"],
        "lines": [{"product_id": shop["cement"], "quantity": "1"}]}).status_code == 422
    assert client.post(f"{INV}/counts", headers=owner, json={"company_id": co, "location_id": shop["loc2"]}
                       ).status_code == 422
    assert client.post(f"{INV}/counts", headers=owner, json={
        "company_id": co2, "location_id": shop["loc2"], "product_ids": [shop["cement"]]}).status_code == 422
    assert client.post(f"{INV}/opening-stock", headers=owner, json={
        "company_id": co, "location_id": shop["main"], "lines": [{"product_id": shop["prod2"], "quantity": "1",
                                                                  "unit_cost": "1"}]}).status_code == 422


def test_each_company_keeps_its_own_cost_and_numbers(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = client.post(f"{INV}/adjustments", headers=shop["owner"], json={
        "company_id": shop["co2"], "location_id": shop["loc2"], "reason_code_id": shop["reason"],
        "lines": [{"product_id": shop["prod2"], "qty_change": "1"}]}).json()
    assert a["number"] == "ADJ-S1-000001"                                    # its own series, not Edge Co's
    stock = client.get(f"{INV}/products/{shop['prod2']}/stock", headers=shop["owner"]).json()
    assert Dec(stock["average_cost"]) == 10 and stock["company_id"] == shop["co2"]


def test_a_manager_of_one_company_sees_and_does_nothing_in_the_other(client, shop) -> None:  # type: ignore[no-untyped-def]
    m2 = shop["manager2"]
    assert {x["code"] for x in client.get(f"{INV}/locations", headers=m2).json()} == {"SHOP2"}
    assert [x["location_code"] for x in client.get(f"{INV}/balances", headers=m2).json()] == ["SHOP2"]
    assert client.get(f"{INV}/products/{shop['cement']}/stock", headers=m2).status_code == 404
    assert client.get(f"{INV}/movements", headers=m2, params={"product_id": shop["cement"]}).json() == []
    attempt = {"company_id": str(shop["company_id"]), "location_id": shop["main"],
               "reason_code_id": shop["reason"], "lines": [{"product_id": shop["cement"], "qty_change": "1"}]}
    assert client.post(f"{INV}/adjustments", headers=m2, json=attempt).status_code == 403
    assert client.post(f"{INV}/counts", headers=m2, json={"company_id": str(shop["company_id"]),
                                                          "location_id": shop["main"]}).status_code == 403
    assert client.post(f"{INV}/opening-stock", headers=m2, json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"],
        "lines": [{"product_id": shop["cement"], "quantity": "1", "unit_cost": "1"}]}).status_code == 403


# --------------------------------------------------------------------------- inactive and wrong things
def set_active(shop, table: str, ident: str, active: bool) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text(f"update {table} set is_active = :a where id = :i"), {"a": active, "i": ident})


def test_an_inactive_location_takes_no_stock(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner = shop["owner"]
    loc = client.post(f"{INV}/locations", headers=owner, json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "code": "OLD", "name": "Old"}
    ).json()["id"]
    set_active(shop, "inventory.location", loc, False)
    body = {"company_id": str(shop["company_id"]), "location_id": loc,
            "lines": [{"product_id": shop["cement"], "quantity": "1", "unit_cost": "1"}]}
    assert client.post(f"{INV}/opening-stock", headers=owner, json=body).status_code == 422
    assert client.post(f"{INV}/adjustments", headers=owner, json={
        **{k: v for k, v in body.items() if k != "lines"}, "reason_code_id": shop["reason"],
        "lines": [{"product_id": shop["cement"], "qty_change": "1"}]}).status_code == 422
    assert client.post(f"{INV}/transfers", headers=owner, json={
        "company_id": str(shop["company_id"]), "from_location_id": shop["main"], "to_location_id": loc,
        "lines": [{"product_id": shop["cement"], "quantity": "1"}]}).status_code == 422
    assert client.post(f"{INV}/counts", headers=owner, json={
        "company_id": str(shop["company_id"]), "location_id": loc}).status_code == 422


def test_an_inactive_product_cannot_be_moved(client, shop) -> None:  # type: ignore[no-untyped-def]
    product = client.post(f"{P}/products", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "sku": "DEAD", "name": "Dead", "base_uom_id": shop["uom"],
        "tax_code_id": shop["tax"]}).json()["id"]
    set_active(shop, "products.product", product, False)
    r = client.post(f"{INV}/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"],
        "lines": [{"product_id": product, "quantity": "1", "unit_cost": "1"}]})
    assert r.status_code == 422 and "inactive" in r.json()["message"]


def test_batches_belong_to_one_product(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co = shop["owner"], str(shop["company_id"])
    other_paint = client.post(f"{P}/products", headers=owner, json={
        "company_id": co, "sku": "PAINT2", "name": "Paint 2", "base_uom_id": shop["uom"], "tax_code_id": shop["tax"],
        "is_batch_tracked": True}).json()["id"]
    for product in (shop["paint"], other_paint):
        r = client.post(f"{INV}/opening-stock", headers=owner, json={
            "company_id": co, "location_id": shop["main"], "lines": [
                {"product_id": product, "quantity": "5", "unit_cost": "2", "batch_no": "B1",
                 "expiry_date": "2027-01-01"}]})
        assert r.status_code == 201, r.text
    with system(shop) as s:
        batch = s.execute(text("select id from inventory.batch where product_id = :p"), {"p": shop["paint"]}
                          ).scalar_one()
    wrong = client.post(f"{INV}/adjustments", headers=owner, json={
        "company_id": co, "location_id": shop["main"], "reason_code_id": shop["reason"],
        "lines": [{"product_id": other_paint, "qty_change": "1", "batch_id": str(batch)}]})
    assert wrong.status_code == 422 and "Batch not found" in wrong.json()["message"]
    assert client.post(f"{INV}/transfers", headers=owner, json={
        "company_id": co, "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
        "lines": [{"product_id": other_paint, "quantity": "1", "batch_id": str(batch)}]}).status_code == 422
    assert client.post(f"{INV}/adjustments", headers=owner, json={
        "company_id": co, "location_id": shop["main"], "reason_code_id": shop["reason"],
        "lines": [{"product_id": shop["cement"], "qty_change": "1", "batch_id": str(batch)}]}).status_code == 422


def test_opening_stock_batch_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co = shop["owner"], str(shop["company_id"])
    product = client.post(f"{P}/products", headers=owner, json={
        "company_id": co, "sku": "PAINT3", "name": "Paint 3", "base_uom_id": shop["uom"], "tax_code_id": shop["tax"],
        "is_batch_tracked": True}).json()["id"]

    def opening(lines):  # type: ignore[no-untyped-def]
        return client.post(f"{INV}/opening-stock", headers=owner, json={
            "company_id": co, "location_id": shop["main"], "lines": lines})

    line = {"product_id": product, "quantity": "1", "unit_cost": "1"}
    assert opening([{**line, "batch_no": "A"}, {**line, "batch_no": "A"}]).status_code == 422   # same batch twice
    assert opening([{**line, "batch_no": "  "}]).status_code == 422   # blank batch number
    assert opening([{**line, "batch_no": "A", "expiry_date": "2027-01-01"},
                    {**line, "batch_no": "B", "expiry_date": "2027-02-01"}]).status_code == 201     # two batches
    assert opening([{**line, "batch_no": "C"}]).status_code == 409                                    # has history now


def test_reason_codes_must_come_from_the_right_list(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co = shop["owner"], str(shop["company_id"])
    assert client.post(f"{INV}/adjustments", headers=owner, json={
        "company_id": co, "location_id": shop["main"], "reason_code_id": shop["count_reason"],
        "lines": [{"product_id": shop["cement"], "qty_change": "1"}]}).status_code == 422
    c = client.post(f"{INV}/counts", headers=owner, json={"company_id": co, "location_id": shop["juja_store"]}).json()
    bad = client.post(f"{INV}/counts/{c['id']}/entries", headers=owner, json={"entries": [
        {"product_id": shop["cement"], "counted_qty": "3", "reason_code_id": shop["reason"]}]})
    assert bad.status_code == 422                                              # an adjustment reason on a count
    client.post(f"{INV}/counts/{c['id']}/cancel", headers=owner)


# --------------------------------------------------------------------------- transfers and counts: wrong references
def test_a_receipt_names_only_lines_of_its_own_transfer(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co = shop["owner"], str(shop["company_id"])

    def transfer():  # type: ignore[no-untyped-def]
        t = client.post(f"{INV}/transfers", headers=owner, json={
            "company_id": co, "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
            "lines": [{"product_id": shop["cement"], "quantity": "2"}]}).json()
        client.post(f"{INV}/transfers/{t['id']}/dispatch", headers=owner)
        return t

    t1, t2 = transfer(), transfer()
    line1, line2 = t1["lines"][0]["id"], t2["lines"][0]["id"]
    r = client.post(f"{INV}/transfers/{t1['id']}/receive", headers=owner, json={"lines": [
        {"line_id": line2, "qty_received": "2"}]})
    assert r.status_code == 422                                                # a line of another transfer
    r = client.post(f"{INV}/transfers/{t1['id']}/receive", headers=owner, json={"lines": [
        {"line_id": line1, "qty_received": "1"}, {"line_id": line1, "qty_received": "1"}]})
    assert r.status_code == 422                                                # the same line twice
    r = client.post(f"{INV}/transfers/{t1['id']}/receive", headers=owner, json={"lines": [
        {"line_id": line1, "qty_received": "1.00001", "reason_code_id": shop["variance_reason"]}]})
    assert r.status_code == 422                                                # too precise
    r = client.post(f"{INV}/transfers/{t1['id']}/receive", headers=owner, json={"lines": [
        {"line_id": line1, "qty_received": "1", "reason_code_id": shop["reason"]}]})
    assert r.status_code == 422                                                # the wrong list of reasons
    for t in (t1, t2):
        assert client.post(f"{INV}/transfers/{t['id']}/receive", headers=owner).status_code == 200


def test_count_rules_around_the_edges(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co = shop["owner"], str(shop["company_id"])
    transit = client.post(f"{INV}/locations", headers=owner, json={"company_id": co, "code": "TRANSIT", "name": "T",
                                                                    "kind": "transit"})
    transit_id = transit.json()["id"] if transit.status_code == 201 else next(
        x["id"] for x in client.get(f"{INV}/locations", headers=owner).json() if x["kind"] == "transit")
    assert client.post(f"{INV}/counts", headers=owner, json={"company_id": co, "location_id": transit_id}
                       ).status_code == 422                                        # in transit cannot be counted
    service_only = {"company_id": co, "location_id": shop["juja_store"], "product_ids": [shop["delivery"]]}
    assert client.post(f"{INV}/counts", headers=owner, json=service_only).status_code == 422
    c = client.post(f"{INV}/counts", headers=owner, json={"company_id": co, "location_id": shop["juja_store"]}).json()
    held = next(x["expected_qty"] for x in c["lines"] if x["product_id"] == shop["cement"])
    entry = {"product_id": shop["cement"], "counted_qty": held}               # exactly what the system holds
    assert client.post(f"{INV}/counts/{c['id']}/entries", headers=owner, json={"entries": [entry]}).status_code == 200
    assert client.post(f"{INV}/counts/{c['id']}/finish", headers=owner).status_code == 200
    assert client.post(f"{INV}/counts/{c['id']}/finish", headers=owner).status_code == 409
    bogus = client.post(f"{INV}/counts/{c['id']}/submit", headers=owner, json={"reasons": [
        {"line_id": str(uuid4()), "reason_code_id": shop["count_reason"]}]})
    assert bogus.status_code == 422                                                # a line that is not on this count
    assert client.post(f"{INV}/counts/{c['id']}/submit", headers=owner).status_code == 200      # nothing differs
    assert client.post(f"{INV}/counts/{c['id']}/submit", headers=owner).status_code == 409
    assert client.post(f"{INV}/counts/{c['id']}/cancel", headers=owner).status_code == 409       # posted is final


# --------------------------------------------------------------------------- boundaries of the rules
def test_below_reorder_fires_only_when_the_level_is_crossed(shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    def events() -> int:
        with system(shop) as s:
            return s.execute(text("select count(*) from kernel.event_outbox where event_type = 'stock.below_reorder'")
                             ).scalar_one()

    product = UUID(shop["cement"])                    # reorder level 10; the company holds 50 + 50 - ... see below
    with system(shop) as s:
        held = s.execute(text("select quantity from inventory.product_cost where product_id = :p"),
                         {"p": str(product)}).scalar_one()

    def sell(quantity: Dec) -> None:
        with system(shop) as s:
            post_movement(s, MovementRequest(
                company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=product,
                quantity=-quantity, movement_type="sale", source_type="edge", source_id=uuid4()))

    before = events()
    sell(held - 10)                                    # down to exactly the level: not below it
    assert events() == before
    sell(Dec("1"))                                     # one under: crossed
    assert events() == before + 1
    sell(Dec("1"))                                     # already under: no repeat
    assert events() == before + 1


def test_a_corrupt_company_setting_does_not_stop_sales(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session
    from ziira.modules.inventory.services.ledger import MovementRequest, post_movement

    def settings(value: str) -> None:
        with tenant_session(shop["tenant_id"], admin=True) as s:
            s.execute(text("update kernel.company set settings = cast(:v as jsonb) where id = :c"),
                      {"v": value, "c": str(shop["company_id"])})

    settings('{"negative_stock_allowed": "maybe", "count_variance_threshold": "lots"}')
    try:
        r = client.get(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"])
        assert r.status_code == 200 and r.json() == {"negative_stock_allowed": False, "count_variance_threshold": "0",
                                                     "late_posting": "redirect"}
        with system(shop) as s:                          # a sale still posts: bad values fall back to the defaults
            sale = post_movement(s, MovementRequest(
                company_id=shop["company_id"], location_id=UUID(shop["main"]), product_id=UUID(shop["cement"]),
                quantity=Dec("-1"), movement_type="sale", source_type="edge", source_id=uuid4()))
        assert sale.quantity == -1
    finally:
        settings("{}")

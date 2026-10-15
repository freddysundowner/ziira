"""What a till needs beyond selling: barcodes on products, sales held on the server, and a browser terminal sending the
sales it made offline (it has no device key, so it may send sales for its own till only)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.pos_helpers import POS, ensure_till, line, make_pos_shop, open_till, stock
from tests.test_imports import check, commit, upload

PRODUCTS = "/api/v1/products"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_pos_shop(client, registry, "Till Gaps Co", stock="100")
    registry.enable(s["tenant_id"], "imports")
    return s


def set_codes(client, shop, product: str, codes: list[str], who: str = "owner"):  # type: ignore[no-untyped-def]
    return client.put(f"{PRODUCTS}/products/{shop[product]}/barcodes", headers=shop[who], json={"barcodes": codes})


# --------------------------------------------------------------------------- barcodes
def test_a_product_has_several_barcodes_and_a_code_has_one_product(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = set_codes(client, shop, "cement", ["  6001234567890 ", "CEM-SCAN-2", "6001234567890"])
    assert r.status_code == 200, r.text
    assert r.json()["barcodes"] == ["6001234567890", "CEM-SCAN-2"]                 # trimmed, repeats dropped
    assert client.get(f"{PRODUCTS}/products/{shop['cement']}/barcodes", headers=shop["owner"]).json() == [
        "6001234567890", "CEM-SCAN-2"]
    assert client.get(f"{PRODUCTS}/products/{shop['cement']}", headers=shop["owner"]).json()["barcodes"] == [
        "6001234567890", "CEM-SCAN-2"]

    taken = set_codes(client, shop, "paint", ["CEM-SCAN-2"])
    assert taken.status_code == 409 and "CEM" in taken.json()["message"]
    assert client.get(f"{PRODUCTS}/products/{shop['paint']}", headers=shop["owner"]).json()["barcodes"] == []
    # the same code on the same product again, and moving one away then onto another, are fine
    assert set_codes(client, shop, "cement", ["6001234567890"]).status_code == 200
    assert set_codes(client, shop, "paint", ["CEM-SCAN-2"]).status_code == 200
    assert set_codes(client, shop, "paint", []).json()["barcodes"] == []
    for bad in (["has space"], ["x" * 65], [""], [f"C{i}" for i in range(21)]):
        assert set_codes(client, shop, "cement", bad).status_code == 422, bad
    assert set_codes(client, shop, "cement", ["6001234567890"], who="cashier").status_code == 403       # view only


def test_products_are_found_by_barcode(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert set_codes(client, shop, "cement", ["6001234567890", "CEM-SCAN-2"]).status_code == 200
    found = client.get(f"{PRODUCTS}/products", headers=shop["cashier"], params={"barcode": "CEM-SCAN-2"}).json()
    assert [p["sku"] for p in found] == ["CEM"] and found[0]["barcodes"] == ["6001234567890", "CEM-SCAN-2"]
    assert client.get(f"{PRODUCTS}/products", headers=shop["cashier"], params={"barcode": "cem-scan-2"}).json() == []
    assert client.get(f"{PRODUCTS}/products", headers=shop["cashier"], params={"barcode": "nope"}).json() == []
    by_search = client.get(f"{PRODUCTS}/products", headers=shop["cashier"], params={"search": "6001234567890"}).json()
    assert [p["sku"] for p in by_search] == ["CEM"]
    # the till's catalog carries the codes (for the copy kept on the device) and filters by them
    base = {"branch_id": str(shop["branch_id"]), "location_id": shop["main"]}
    catalog = client.get(f"{POS}/catalog", headers=shop["cashier"], params=base).json()
    assert {i["sku"]: i["barcodes"] for i in catalog}["CEM"] == ["6001234567890", "CEM-SCAN-2"]
    one = client.get(f"{POS}/catalog", headers=shop["cashier"], params={**base, "barcode": "6001234567890"}).json()
    assert [i["sku"] for i in one] == ["CEM"] and Dec(one[0]["price"]) == 116
    snap = client.get(f"{POS}/sync/snapshot", headers={**shop["cashier"], "X-Device-Key": shop["device_key"]}).json()
    assert {i["sku"]: i["barcodes"] for i in snap["items"]}["CEM"] == ["6001234567890", "CEM-SCAN-2"]


def test_the_lookup_by_barcode_uses_an_index(client, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from tests.stock_helpers import system

    with system(shop) as s:
        names = set(s.execute(text("select indexname from pg_indexes where tablename = 'product_barcode'")).scalars())
    assert {"product_barcode_ix2", "product_barcode_company_id_barcode_key"} <= names


def test_a_file_import_can_carry_barcodes(client, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.test_imports import sql

    content = ("sku,name,unit,tax_code,barcode\n"
               "BAR-1,With codes,PCS,VAT16,5000000000011;5000000000028\n"
               "BAR-2,Without,PCS,VAT16,\n"
               "BAR-3,Code taken,PCS,VAT16,CEM-SCAN-2\n"
               "BAR-4,Bad code,PCS,VAT16,has space\n")
    batch = upload(client, shop, "products", content)
    assert "barcode" in batch["mapping"] and batch["mapping"]["barcode"] == "barcode"
    checked = check(client, shop, batch["id"])
    assert checked["counts"]["valid"] == 2 and checked["counts"]["invalid"] == 2
    commit(client, shop, batch["id"])
    stored = sql(shop, "select p.sku, b.barcode from products.product_barcode b join products.product p "
                       "on p.id = b.product_id where p.sku like 'BAR-%' order by b.barcode")
    assert [(r.sku, r.barcode) for r in stored] == [("BAR-1", "5000000000011"), ("BAR-1", "5000000000028")]
    found = client.get(f"{PRODUCTS}/products", headers=shop["owner"], params={"barcode": "5000000000028"}).json()
    assert [p["sku"] for p in found] == ["BAR-1"]


def test_barcode_rules() -> None:
    from ziira.modules.products.domain import rules
    from ziira.sdk import ValidationFailed

    assert rules.clean_barcodes([" A1 ", "A1", "b2"]) == ["A1", "b2"]
    for bad in ("", "  ", "a b", "é", "x" * 65, "ta\tb"):
        with pytest.raises(ValidationFailed):
            rules.clean_barcodes([bad])


# --------------------------------------------------------------------------- held sales
def held_body(shop, **kw):  # type: ignore[no-untyped-def]
    return {"local_id": str(uuid4()), "label": "Mama · 10:30", "customer_name": "", "customer_phone": "", "lines": [
        {"product_id": shop["cement"], "sku": "CEM", "name": "Product CEM", "quantity": "2", "list_price": "116.00",
         "price": "116.00", "discount": "0"}], **kw}


def books(shop) -> tuple[int, int, Dec]:  # type: ignore[no-untyped-def]
    """Sales, stock movements and journal-free proof that nothing was sold: (sales, movements, stock of cement)."""
    from tests.payments_helpers import one

    return (one(shop, "select count(*) from pos.sale"), one(shop, "select count(*) from inventory.stock_movement"),
            stock(shop))


def test_a_held_sale_is_a_draft_that_can_be_resumed_or_discarded(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = ensure_till(client, shop)
    before = books(shop)
    body = held_body(shop, customer_name="Mama Mboga", note="Back in 5 minutes")
    made = client.post(f"{POS}/tills/{till}/held", headers=shop["cashier"], json=body)
    assert made.status_code == 201, made.text
    held = made.json()
    assert held["status"] == "held" and held["customer_name"] == "Mama Mboga" and held["note"] == "Back in 5 minutes"
    assert held["lines"][0]["sku"] == "CEM" and Dec(held["lines"][0]["quantity"]) == 2
    assert books(shop) == before                                       # a draft: no sale, no stock movement

    again = client.post(f"{POS}/tills/{till}/held", headers=shop["cashier"], json=body)       # same local_id
    assert again.status_code == 200 and again.json()["id"] == held["id"]
    listed = client.get(f"{POS}/tills/{till}/held", headers=shop["cashier"]).json()
    assert [h["id"] for h in listed] == [held["id"]]

    resumed = client.post(f"{POS}/held/{held['id']}/resume", headers=shop["cashier"])
    assert resumed.status_code == 200 and resumed.json()["status"] == "resumed"
    assert client.post(f"{POS}/held/{held['id']}/resume", headers=shop["cashier"]).status_code == 200    # safe to repeat
    assert client.get(f"{POS}/tills/{till}/held", headers=shop["cashier"]).json() == []
    assert client.post(f"{POS}/held/{held['id']}/discard", headers=shop["cashier"]).status_code == 200

    second = client.post(f"{POS}/tills/{till}/held", headers=shop["cashier"], json=held_body(shop)).json()
    gone = client.post(f"{POS}/held/{second['id']}/discard", headers=shop["cashier"])
    assert gone.status_code == 200 and gone.json()["status"] == "discarded"
    assert client.post(f"{POS}/held/{second['id']}/discard", headers=shop["cashier"]).status_code == 200
    assert client.post(f"{POS}/held/{second['id']}/resume", headers=shop["cashier"]).status_code == 409
    assert client.get(f"{POS}/tills/{till}/held", headers=shop["cashier"], params={"status": "all"}).json()
    assert books(shop) == before


def test_a_held_sale_can_be_resumed_or_discarded_by_the_terminals_own_id(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = ensure_till(client, shop)
    body = held_body(shop)
    made = client.post(f"{POS}/tills/{till}/held", headers=shop["cashier"], json=body).json()
    assert client.post(f"{POS}/held/{body['local_id']}/resume", headers=shop["cashier"]).json()["id"] == made["id"]
    other = held_body(shop)
    client.post(f"{POS}/tills/{till}/held", headers=shop["cashier"], json=other)
    assert client.post(f"{POS}/held/{other['local_id']}/discard", headers=shop["cashier"]).json()["status"] == "discarded"
    assert client.post(f"{POS}/held/{uuid4()}/discard", headers=shop["cashier"]).status_code == 404


def test_held_sales_belong_to_their_cashier_and_are_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = ensure_till(client, shop)
    mine = client.post(f"{POS}/tills/{till}/held", headers=shop["cashier"], json=held_body(shop)).json()
    other = shop["manager"]
    assert client.post(f"{POS}/tills/{till}/held", headers=other, json=held_body(shop)).status_code == 403
    assert client.post(f"{POS}/held/{mine['id']}/resume", headers=other).status_code == 404
    assert client.post(f"{POS}/held/{mine['id']}/discard", headers=other).status_code == 404
    assert client.get(f"{POS}/tills/{till}/held", headers=shop["owner"]).status_code == 200          # a reviewer may look
    assert client.post(f"{POS}/tills/{till}/held", headers=shop["cashier"], json=held_body(shop, lines=[])).status_code == 422
    bad = held_body(shop)
    bad["lines"][0]["quantity"] = "0"
    assert client.post(f"{POS}/tills/{till}/held", headers=shop["cashier"], json=bad).status_code == 422
    assert client.post(f"{POS}/tills/{uuid4()}/held", headers=shop["cashier"], json=held_body(shop)).status_code == 404
    client.post(f"{POS}/held/{mine['id']}/discard", headers=shop["cashier"])


def test_closing_the_till_ends_what_is_still_on_hold(client, shop) -> None:  # type: ignore[no-untyped-def]
    opened = open_till(client, shop, "boss")
    assert opened.status_code == 201, opened.text
    till = opened.json()["id"]
    for _ in range(3):
        assert client.post(f"{POS}/tills/{till}/held", headers=shop["boss"], json=held_body(shop)).status_code == 201
    gone = client.post(f"{POS}/tills/{till}/held", headers=shop["boss"], json=held_body(shop)).json()
    client.post(f"{POS}/held/{gone['id']}/discard", headers=shop["boss"])
    closed = client.post(f"{POS}/tills/{till}/close", headers=shop["boss"], json={"counted_cash": "1000.00"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["held_expired"] == 3                               # the discarded one is not counted
    assert client.get(f"{POS}/tills/{till}/report", headers=shop["boss"]).json()["held_expired"] == 3
    assert client.get(f"{POS}/tills/{till}/held", headers=shop["boss"]).json() == []
    states = {h["status"] for h in client.get(f"{POS}/tills/{till}/held", headers=shop["boss"],
                                              params={"status": "all"}).json()}
    assert states == {"expired", "discarded"}
    assert client.post(f"{POS}/tills/{till}/held", headers=shop["boss"], json=held_body(shop)).status_code in (404, 409)


# --------------------------------------------------------------------------- a browser terminal sends its offline sales
def web_sale(shop, till, *, local=None, qty="1", paid="116.00", at=None, **kw):  # type: ignore[no-untyped-def]
    return {"type": "sale", "local_id": local or str(uuid4()), "till_session_id": till,
            "at": at or (datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
            "lines": [line(shop, "cement", qty)], "payments": [{"method": "cash", "amount": paid}], **kw}


def test_a_browser_terminal_uploads_its_offline_sales_without_a_device_key(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = ensure_till(client, shop)
    start = books(shop)
    earlier = (datetime.now(UTC) - timedelta(hours=2)).replace(microsecond=0)
    ops = [web_sale(shop, till, at=earlier.isoformat()), web_sale(shop, till, qty="2", paid="232.00")]
    r = client.post(f"{POS}/sync/upload", headers=shop["cashier"], json={"ops": ops})
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()["results"]] == ["ok", "ok"]
    after = books(shop)
    assert after[0] == start[0] + 2 and after[2] == start[2] - 3
    sales = client.get(f"{POS}/sales", headers=shop["manager"], params={"limit": 5}).json()
    mine = {s["id"]: s for s in sales if s["synced_offline"]}
    first = next(s for s in mine.values() if Dec(s["total"]) == 116 and s["sold_at"].startswith(earlier.isoformat()[:19]))
    assert first["number"].startswith("POS-")

    # a lost reply: the same sales sent again are answered, not sold twice
    again = client.post(f"{POS}/sync/upload", headers=shop["cashier"], json={"ops": ops})
    assert [x["status"] for x in again.json()["results"]] == ["duplicate", "duplicate"]
    assert books(shop) == after


def test_the_same_offline_sale_sent_twice_at_once_is_one_sale(client, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.test_lifecycle_more import together

    till = ensure_till(client, shop)
    before = books(shop)
    op = web_sale(shop, till)
    results = together([lambda: client.post(f"{POS}/sync/upload", headers=shop["cashier"], json={"ops": [op]})] * 3)
    assert all(x.status_code == 200 for x in results)
    assert books(shop)[0] == before[0] + 1


def test_without_a_device_key_only_own_sales_may_be_sent(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = ensure_till(client, shop)
    mgr_till = ensure_till(client, shop, "manager")
    before = books(shop)

    def send(ops, who="cashier"):  # type: ignore[no-untyped-def]
        return client.post(f"{POS}/sync/upload", headers=shop[who], json={"ops": ops})

    assert send([web_sale(shop, mgr_till)]).status_code == 403                            # another cashier's till
    assert send([web_sale(shop, till), web_sale(shop, mgr_till)]).status_code == 403      # two tills in one go
    assert send([]).status_code == 403
    assert send([{"type": "till_open", "local_id": str(uuid4()), "at": datetime.now(UTC).isoformat()}]).status_code == 403
    assert send([{"type": "sale", "local_id": str(uuid4()), "till_local_id": str(uuid4()), "at": datetime.now(UTC).isoformat(),
                  "lines": [line(shop)], "payments": [{"method": "cash", "amount": "116.00"}]}]).status_code == 403
    assert send([web_sale(shop, str(uuid4()))]).status_code == 403
    assert books(shop) == before


def test_an_offline_sale_that_cannot_be_accepted_is_kept_not_lost(client, shop) -> None:  # type: ignore[no-untyped-def]
    till = ensure_till(client, shop)
    bad = web_sale(shop, till)
    bad["lines"] = [{"product_id": str(uuid4()), "quantity": "1"}]
    r = client.post(f"{POS}/sync/upload", headers=shop["cashier"], json={"ops": [bad]})
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "rejected"
    assert r.json()["results"][0]["error"]
    kept = client.get(f"{POS}/sync/rejections", headers=shop["owner"]).json()
    assert any(k["local_id"] == bad["local_id"] for k in kept)
    # sent again after the cause is fixed (a manager fixes it; here the same id with good lines) it is accepted
    fixed = {**bad, "lines": [line(shop)]}
    ok = client.post(f"{POS}/sync/upload", headers=shop["cashier"], json={"ops": [fixed]}).json()
    assert ok["results"][0]["status"] == "ok"


def test_a_terminal_can_fetch_the_lines_of_a_receipt_to_print_offline(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{POS}/receipt-settings", headers=shop["cashier"], params={"branch_id": str(shop["branch_id"])})
    assert r.status_code == 200, r.text
    assert len(r.json()["header"]) >= 2                                              # the company, then the branch
    assert r.json()["footer"] == ["Thank you for shopping with us"]
    assert client.get(f"{POS}/receipt-settings", headers=shop["cashier"], params={"branch_id": str(uuid4())}).status_code == 404

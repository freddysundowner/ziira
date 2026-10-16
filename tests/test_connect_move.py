"""Moving from a connected system into Ziira Core, and not checking the same ground twice.

The other system's records are planted the way a connector stores them; the move proposes Core records from them,
checks them with the owning units' importers, stages one Data Import batch per kind and imports them. Numbers by hand
(go-live 2026-06-30, so the 5 July movement and the 2 July invoice are left out):

Products   BOLT-10 (new, price 8.00)  NUT-8 (new, price 5.00)  CEM (already in Ziira)  one with no code (skipped).
Customers  Alpha Stores -> C-0001, Beta Traders -> C-0002, Delta (a phone nobody can read: brought without it) -> C-0003,
           Gamma Mart (same phone as Gamma Mart Ltd, CUST-G, already in Ziira) -> matched, not created.
Suppliers  First Supplies -> S-0001, Second Supplies -> S-0002.
Stock      BOLT-10 at HQ: +100 at 4.00, +100 at 5.00, -40 sold -> 160 at (100*4 + 100*5)/200 = 4.50 = 720.00.
           NUT-8 at Juja: +60 at 2.00 -> 60 at 2.00 = 120.00. Stock value 840.00.
           Skipped: NUT-8 at a branch nobody mapped; BOLT-10 at Juja where only a sale was seen (-5).
Customers owe  C-0001: INV-1 1,000.00 + INV-2 (2,500.50 less 500.50 paid) 2,000.00 = 3,000.00; C-0002: INV-3 750.00;
           CUST-G (Gamma): 300.00. Total 4,050.00.   Suppliers: S-0001 BD-1 4,000.00; S-0002 X-9 (800.00 less 100.00)
           700.00. Total 4,700.00.
Books      receivables 1100 = 4,050.00 debit, payables 2000 = 4,700.00 credit, inventory 1200 = 840.00 debit, and opening
           balance equity 3100 takes the difference: credit 4,050.00 + 840.00 less debit 4,700.00 = 190.00 credit.
"""

from datetime import date
from decimal import Decimal as D  # noqa: N817
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.connect_helpers import CONNECT, TODAY, Planter, at, new_connection, rows, scalar
from tests.finance_helpers import FIN, balance
from tests.pos_helpers import make_sales_shop
from tests.stock_helpers import system
from ziira.kernel.jobs import run_due
from ziira.modules.connect.public import Invoice, Party, Product, Sale, StockMovement

GO_LIVE = date(2026, 6, 30)


def d(y: int, m: int, day: int) -> date:
    return date(y, m, day)


def plant_everything(p: Planter) -> None:
    """The other system's records, as described at the top of the file."""
    p.put("products", [
        Product("p1", "Bolt 10mm", "bolt-10", "Fixings", D("4.50"), D("8.00")),
        Product("p2", "Nut 8mm", "NUT-8", "Fixings", D("2.00"), D("5.00")),
        Product("p3", "Cement", "CEM", None, D("50"), D("116")),
        Product("p4", "Mystery item", None, None, None, None)])
    p.put("parties", [
        Party("c1", "customer", "Alpha Stores", "0712000111", "alpha@example.com", "TX-ALPHA1", at(d(2025, 1, 1))),
        Party("c2", "customer", "Beta Traders", "0712000222", None, None, at(d(2025, 1, 2))),
        Party("c3", "customer", "Gamma Mart", "0712000333", None, None, at(d(2025, 1, 3))),
        Party("c4", "customer", "Delta Hardware", "abc", None, None, at(d(2025, 1, 4))),
        Party("s1", "supplier", "First Supplies", None, None, "SUP-TAX-1", at(d(2025, 1, 5))),
        Party("s2", "supplier", "Second Supplies", "0722000444", None, None, at(d(2025, 1, 6)))])
    p.put("stock_movements", [
        StockMovement("m1", at(d(2026, 5, 1)), "p1", D(100), "purchase", "HQ", unit_cost=D("4.00")),
        StockMovement("m2", at(d(2026, 6, 1)), "p1", D(100), "purchase", "HQ", unit_cost=D("5.00")),
        StockMovement("m3", at(d(2026, 6, 15)), "p1", D(-40), "sale", "HQ"),
        StockMovement("m4", at(d(2026, 7, 5)), "p1", D(10), "purchase", "HQ", unit_cost=D("9.00")),    # after go-live
        StockMovement("m5", at(d(2026, 6, 1)), "p2", D(60), "purchase", "JUJA", unit_cost=D("2.00")),
        StockMovement("m6", at(d(2026, 6, 2)), "p2", D(25), "purchase", "ZED", unit_cost=D("2.00")),   # unmapped branch
        StockMovement("m7", at(d(2026, 6, 3)), "p1", D(-5), "sale", "JUJA")])                         # only a sale seen
    p.put("invoices", [
        Invoice("i1", "customer", d(2026, 5, 1), D("1000"), due_date=d(2026, 5, 31), number="INV-1", party_ref="c1"),
        Invoice("i2", "customer", d(2026, 6, 10), D("2500.50"), paid=D("500.50"), due_date=d(2026, 7, 10),
                number="INV-2", party_ref="c1"),
        Invoice("i3", "customer", d(2026, 6, 1), D("750"), number="INV-3", party_ref="c2"),
        Invoice("i4", "customer", d(2026, 6, 5), D("400"), paid=D("400"), status="paid", number="INV-4",
                party_ref="c1"),
        Invoice("i5", "customer", d(2026, 7, 2), D("999"), number="INV-5", party_ref="c1"),             # after go-live
        Invoice("i6", "customer", d(2026, 6, 20), D("300"), due_date=d(2026, 7, 20), number="INV-6",
                party_ref="c3"),
        Invoice("b1", "supplier", d(2026, 6, 1), D("4000"), due_date=d(2026, 7, 1), number="BD-1", party_ref="s1"),
        Invoice("b2", "supplier", d(2026, 6, 20), D("800"), paid=D("100"), due_date=d(2026, 7, 4), number="X-9",
                party_ref="s2")])


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.command.hooks  # noqa: F401
    import ziira.modules.intel.hooks  # noqa: F401

    s = make_sales_shop(client, registry, "Move Co", stock="0")
    for unit in ("purchasing", "imports", "connect", "intel", "command"):
        registry.enable(s["tenant_id"], unit)
    co = str(s["company_id"])
    s["co"] = co
    assert client.post(f"{FIN}/companies/{co}/books", headers=s["owner"]).status_code == 200
    r = client.post("/api/v1/crm/customers", headers=s["owner"], json={
        "company_id": co, "code": "CUST-G", "name": "Gamma Mart Ltd", "phone": "0712000333"})
    assert r.status_code == 201, r.text
    s["connection"] = new_connection(client, s, "csv_sales", "Old ERP")["id"]
    plant_everything(Planter(s, UUID(s["connection"])))
    return s


def body(**extra: Any) -> dict[str, Any]:
    return {"kinds": ["products", "customers", "suppliers", "opening_stock", "customer_balances", "supplier_balances"],
            "as_of": GO_LIVE.isoformat(), "unit": "PCS", "tax_code": "VAT16", **extra}


def url(shop: dict[str, Any], tail: str) -> str:
    return f"{CONNECT}/connections/{shop['connection']}{tail}"


def preview(client, shop, **extra: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.post(url(shop, "/move/preview"), headers=shop["owner"], json=body(**extra))
    assert r.status_code == 200, r.text
    return {k["kind"]: k for k in r.json()["kinds"]}


def run_jobs(shop) -> None:  # type: ignore[no-untyped-def]
    while run_due(shop["tenant_id"]) > 0:
        pass


def run_move(client, shop, **extra: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.post(url(shop, "/move"), headers=shop["owner"], json=body(**extra))
    assert r.status_code == 202, r.text
    run_jobs(shop)
    done = client.get(f"{CONNECT}/moves/{r.json()['id']}", headers=shop["owner"]).json()
    assert done["state"] == "done", done
    return {"move": done, **{b["kind"]: b for b in done["batches"]}}


def reasons_of(kind: dict[str, Any]) -> dict[str, int]:
    return {r["reason"]: r["count"] for r in kind["reasons"]}


# --------------------------------------------------------------------------- options and the preview
def test_options_say_what_can_be_brought_and_where_stock_goes(client, shop) -> None:  # type: ignore[no-untyped-def]
    o = client.get(url(shop, "/move/options"), headers=shop["owner"]).json()
    assert all(k["available"] and k["allowed"] and not k["needs"] for k in o["kinds"])
    assert {k["kind"] for k in o["kinds"]} == {"products", "customers", "suppliers", "opening_stock",
                                                "customer_balances", "supplier_balances"}
    assert o["source_counts"] == {"products": 4, "customers": 4, "suppliers": 2, "stock_movements": 7,
                                  "customer_invoices": 5, "supplier_invoices": 2, "users": 0}
    places = {b["branch_name"]: [x["code"] for x in b["locations"]] for b in o["mapped_branches"]}
    assert places == {"Head Office": ["MAIN"], "Juja": ["JUJA-STORE"]} or list(places.values()) == [["MAIN"], ["JUJA-STORE"]]
    assert o["running_move_id"] is None and o["last_move_id"] is None
    s = client.get(f"{CONNECT}/move/suggestion", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert s == {"suggest": True, "connection_id": shop["connection"]}


def test_the_preview_counts_what_would_be_created_and_what_is_left_out_and_why(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = rows(shop, "select (select count(*) from products.product) as p, (select count(*) from crm.customer) as c, "
                        "(select count(*) from imports.batch) as b")[0]
    k = preview(client, shop)
    assert (k["products"]["candidates"], k["products"]["create"], k["products"]["exists"], k["products"]["skipped"]) \
        == (4, 2, 1, 1)
    assert reasons_of(k["products"]) == {"The product has no product code": 1, "Product CEM already exists": 1}
    assert [r["sku"] for r in k["products"]["sample"]] == ["BOLT-10", "NUT-8"]
    assert [r["price"] for r in k["products"]["sample"]] == ["8.00", "5.00"]
    assert (k["customers"]["candidates"], k["customers"]["create"], k["customers"]["exists"]) == (4, 3, 1)
    assert [r["code"] for r in k["customers"]["sample"]] == ["C-0001", "C-0002", "C-0003"]
    assert any("Gamma Mart Ltd (CUST-G) has the same phone number" in r["reason"] for r in k["customers"]["reasons"])
    assert any("could not read" in w for w in k["customers"]["warnings"])               # Delta's phone, dropped
    assert [r["phone"] for r in k["customers"]["sample"]] == ["0712000111", "0712000222", ""]
    assert (k["suppliers"]["create"], k["suppliers"]["exists"], k["suppliers"]["skipped"]) == (2, 0, 0)
    assert [r["code"] for r in k["suppliers"]["sample"]] == ["S-0001", "S-0002"]
    stock = k["opening_stock"]
    assert (stock["create"], stock["skipped"]) == (2, 2)
    assert [(r["sku"], r["location"], r["quantity"], r["unit_cost"], r["as_of"]) for r in stock["sample"]] == [
        ("BOLT-10", "MAIN", "160", "4.5", "2026-06-30"), ("NUT-8", "JUJA-STORE", "60", "2", "2026-06-30")]
    assert any("not mapped" in r["reason"] for r in stock["reasons"]) and any("negative" in r["reason"]
                                                                              for r in stock["reasons"])
    cb = k["customer_balances"]
    assert cb["create"] == 4 and cb["skipped"] == 0
    assert sorted((r["customer_code"], r["reference"], r["amount"]) for r in cb["sample"]) == [
        ("C-0001", "INV-1", "1000.00"), ("C-0001", "INV-2", "2000.00"), ("C-0002", "INV-3", "750.00"),
        ("CUST-G", "INV-6", "300.00")]
    assert [r["due_date"] for r in cb["sample"] if r["reference"] == "INV-3"] == [""]       # the customer's terms apply
    sb = k["supplier_balances"]
    assert sorted((r["supplier_code"], r["reference"], r["amount"]) for r in sb["sample"]) == [
        ("S-0001", "BD-1", "4000.00"), ("S-0002", "X-9", "700.00")]
    after = rows(shop, "select (select count(*) from products.product) as p, (select count(*) from crm.customer) as c, "
                       "(select count(*) from imports.batch) as b")[0]
    assert tuple(after) == tuple(before)                                         # a preview writes and stages nothing


def test_a_kind_whose_unit_is_off_explains_and_cannot_be_started(client, registry) -> None:  # type: ignore[no-untyped-def]
    from tests.connect_helpers import make_connect_shop

    lean = make_connect_shop(client, registry, "Lean Move Co")          # connect, intel, command, imports only
    lean["connection"] = new_connection(client, lean, "csv_sales", "Old ERP")["id"]
    plant_everything(Planter(lean, UUID(lean["connection"])))
    o = client.get(url(lean, "/move/options"), headers=lean["owner"]).json()
    kinds = {k["kind"]: k for k in o["kinds"]}
    assert not any(k["available"] for k in kinds.values())
    assert kinds["customers"]["needs"] == ["crm"] and kinds["customer_balances"]["needs"] == ["pos", "crm", "finance"]
    assert client.get(f"{CONNECT}/move/suggestion", headers=lean["owner"],
                      params={"company_id": lean["co"] if "co" in lean else str(lean["company_id"])}).json()["suggest"] is False
    r = client.post(url(lean, "/move"), headers=lean["owner"], json=body())
    assert r.status_code == 422 and "Add-ons" in r.text
    assert rows(lean, "select count(*) from connect.move")[0][0] == 0


def test_people_without_the_permissions_cannot_preview_or_move(client, shop) -> None:  # type: ignore[no-untyped-def]
    acc = shop["fm"]                                                     # Finance Manager: connect.view only
    assert client.get(url(shop, "/move/options"), headers=acc).status_code == 403
    assert client.post(url(shop, "/move/preview"), headers=acc, json=body()).status_code == 403
    assert client.post(url(shop, "/move"), headers=acc, json=body()).status_code == 403
    assert client.get(f"{CONNECT}/moves/{UUID(int=1)}", headers=acc).status_code in (403, 404)
    role = client.post("/api/v1/roles", headers=shop["owner"], json={
        "name": "Connector only", "permissions": ["connect.view", "connect.manage"]})
    assert role.status_code == 201, role.text
    # a manager of connections who may not import: every kind is listed but none is allowed
    made = client.post("/api/v1/users", headers=shop["owner"], json={
        "full_name": "Connie", "email": "connie@move-co.test", "password": "connie-pass-1"}).json()
    client.post(f"/api/v1/users/{made['id']}/roles", headers=shop["owner"], json={
        "role_id": role.json()["id"], "scope": "company", "company_id": shop["co"], "branch_id": None})
    from tests.conftest import sign_in

    connie = sign_in(client, "move-co", "connie@move-co.test", "connie-pass-1").headers
    o = client.get(url(shop, "/move/options"), headers=connie).json()
    assert not any(k["allowed"] for k in o["kinds"])
    refused = client.post(url(shop, "/move"), headers=connie, json=body())
    assert refused.status_code == 422 and "may not bring over" in refused.text
    assert client.get(f"{CONNECT}/move/suggestion", headers=connie, params={"company_id": shop["co"]}).json() \
        == {"suggest": False, "connection_id": None}


# --------------------------------------------------------------------------- the move, end to end
def test_the_move_creates_exactly_what_the_preview_promised(client, shop) -> None:  # type: ignore[no-untyped-def]
    done = run_move(client, shop)
    assert done["move"]["needs_attention"] is False
    assert {k: (done[k]["status"], done[k]["staged"]) for k in
            ("products", "customers", "suppliers", "opening_stock", "customer_balances", "supplier_balances")} == {
        "products": ("done", 2), "customers": ("done", 3), "suppliers": ("done", 2), "opening_stock": ("done", 2),
        "customer_balances": ("done", 4), "supplier_balances": ("done", 2)}
    # records
    assert [(r.sku, r.name) for r in rows(shop, "select sku, name from products.product where sku in ('BOLT-10', "
                                                "'NUT-8') order by sku")] == [("BOLT-10", "Bolt 10mm"),
                                                                              ("NUT-8", "Nut 8mm")]
    prices = {r.sku: D(r.price) for r in rows(
        shop, "select p.sku, i.price from products.price_list_item i join products.product p on p.id = i.product_id "
              "where i.valid_to is null and p.sku in ('BOLT-10', 'NUT-8')")}
    assert prices == {"BOLT-10": D("8.00"), "NUT-8": D("5.00")}
    customers = {r.code: (r.name, r.phone) for r in rows(shop, "select code, name, phone from crm.customer "
                                                               "order by code")}
    assert customers == {"C-0001": ("Alpha Stores", "254712000111"), "C-0002": ("Beta Traders", "254712000222"),
                         "C-0003": ("Delta Hardware", None), "CUST-G": ("Gamma Mart Ltd", "254712000333")}
    assert {r.code: r.name for r in rows(shop, "select code, name from purchasing.supplier")} == {
        "S-0001": "First Supplies", "S-0002": "Second Supplies"}
    # stock
    stock = {(r.sku, r.code): (D(r.quantity), D(r.unit_cost), D(r.value), r.business_date) for r in rows(
        shop, "select p.sku, l.code, m.quantity, m.unit_cost, m.value, m.business_date from inventory.stock_movement m "
              "join products.product p on p.id = m.product_id join inventory.location l on l.id = m.location_id "
              "where m.movement_type = 'opening'")}
    assert stock == {("BOLT-10", "MAIN"): (D(160), D("4.5"), D("720.00"), GO_LIVE),
                     ("NUT-8", "JUJA-STORE"): (D(60), D("2"), D("120.00"), GO_LIVE)}
    # who owes what: documents, dates and the books agree
    invoices = {r.external_ref: (r.code, D(r.total), r.issue_date, r.due_date) for r in rows(
        shop, "select i.external_ref, c.code, i.total, i.issue_date, i.due_date from pos.sales_invoice i "
              "join crm.customer c on c.id = i.customer_id where i.kind = 'opening_balance'")}
    assert invoices == {"INV-1": ("C-0001", D("1000.00"), d(2026, 5, 1), d(2026, 5, 31)),
                        "INV-2": ("C-0001", D("2000.00"), d(2026, 6, 10), d(2026, 7, 10)),
                        "INV-3": ("C-0002", D("750.00"), d(2026, 6, 1), d(2026, 6, 1)),
                        "INV-6": ("CUST-G", D("300.00"), d(2026, 6, 20), d(2026, 7, 20))}
    bills = {r.supplier_invoice_no: (r.code, D(r.total), r.due_date) for r in rows(
        shop, "select b.supplier_invoice_no, s.code, b.total, b.due_date from purchasing.supplier_bill b "
              "join purchasing.supplier s on s.id = b.supplier_id where b.kind = 'opening_balance'")}
    assert bills == {"BD-1": ("S-0001", D("4000.00"), d(2026, 7, 1)), "X-9": ("S-0002", D("700.00"), d(2026, 7, 4))}
    assert balance(shop, "1100") == D("4050.00") and balance(shop, "2000") == D("-4700.00")
    assert balance(shop, "1200") == D("840.00") and balance(shop, "3100") == D("-190.00")
    sub = {r.code: D(r.net) for r in rows(
        shop, "select c.code, sum(l.debit - l.credit) as net from finance.journal_line l join finance.account a "
              "on a.id = l.account_id join crm.customer c on c.id = l.party_id where a.code = '1100' group by 1")}
    assert sub == {"C-0001": D("3000.00"), "C-0002": D("750.00"), "CUST-G": D("300.00")}
    tb = client.get(f"{FIN}/reports/trial-balance", headers=shop["owner"],
                    params={"company_id": shop["co"], "as_of": "2026-12-31"}).json()
    assert tb["balanced"] and D(tb["total_debit"]) == D(tb["total_credit"])
    from ziira.kernel import cli

    assert cli.main(["verify", shop["code"]]) == 0


def test_every_batch_is_tagged_with_its_connection_and_reconciles(client, shop) -> None:  # type: ignore[no-untyped-def]
    batches = client.get("/api/v1/imports/batches", headers=shop["owner"], params={"limit": 50}).json()
    assert len(batches) == 6
    assert {(b["source_kind"], b["source_id"]) for b in batches} == {("connect.connection", shop["connection"])}
    assert all(b["filename"].startswith("From Old ERP: ") for b in batches)
    for b in batches:
        report = client.get(f"/api/v1/imports/batches/{b['id']}/report", headers=shop["owner"]).json()
        assert report["problems"] == [] and report["reconciled"], (b["kind"], report)
    balances = next(b for b in batches if b["kind"] == "customer_balances")
    assert balances["options"]["as_of"] == "2026-06-30" and balances["reversible"]


def test_the_move_alone_does_not_count_as_running_the_business_on_ziira(client, shop) -> None:  # type: ignore[no-untyped-def]
    o = client.get(f"{CONNECT}/overlap", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert o["overlapping"] is False and o["areas"] == []                # opening stock and balances do not count
    s = client.get(f"{CONNECT}/move/suggestion", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert s["suggest"] is False                                          # already moved


def test_running_the_move_again_creates_nothing_twice(client, shop) -> None:  # type: ignore[no-untyped-def]
    counts = "select (select count(*) from products.product) a, (select count(*) from crm.customer) b, " \
             "(select count(*) from purchasing.supplier) c, (select count(*) from inventory.stock_movement) d, " \
             "(select count(*) from pos.sales_invoice) e, (select count(*) from purchasing.supplier_bill) f, " \
             "(select count(*) from finance.journal_entry) g, (select count(*) from imports.batch) h"
    before = tuple(rows(shop, counts)[0])
    k = preview(client, shop)
    assert {n: x["create"] for n, x in k.items()} == dict.fromkeys(k, 0)
    assert k["customers"]["exists"] == 4 and k["products"]["exists"] == 3          # three + CEM
    again = run_move(client, shop)
    assert all(again[k]["status"] == "nothing_new" for k in
               ("products", "customers", "suppliers", "opening_stock", "customer_balances", "supplier_balances"))
    assert tuple(rows(shop, counts)[0]) == before                        # not even an empty batch is left behind
    codes = {r.source_ref: r.code for r in rows(shop, "select source_ref, code from connect.move_code")}
    assert codes == {"c1": "C-0001", "c2": "C-0002", "c3": "CUST-G", "c4": "C-0003", "s1": "S-0001", "s2": "S-0002"}
    assert scalar(shop, "select count(*) from connect.move") == 2


def test_another_business_cannot_see_the_move(client, shop, registry) -> None:  # type: ignore[no-untyped-def]
    from tests.connect_helpers import make_connect_shop

    other = make_connect_shop(client, registry, "Other Move Co")
    mine = rows(shop, "select id from connect.move limit 1")[0].id
    assert client.get(f"{CONNECT}/moves/{mine}", headers=other["owner"]).status_code == 404
    assert client.post(f"{CONNECT}/moves/{mine}/undo", headers=other["owner"], json={"reason": "x"}).status_code == 404
    assert client.get(url(shop, "/move/options"), headers=other["owner"]).status_code == 404


def test_undo_takes_back_the_balances_and_says_what_it_cannot(client, shop) -> None:  # type: ignore[no-untyped-def]
    move_id = rows(shop, "select id from connect.move order by created_at limit 1")[0].id
    assert client.post(f"{CONNECT}/moves/{move_id}/undo", headers=shop["owner"], json={"reason": " "}).status_code == 422
    r = client.post(f"{CONNECT}/moves/{move_id}/undo", headers=shop["owner"], json={"reason": "Wrong go-live date"})
    assert r.status_code == 200, r.text
    states = {b["kind"]: b["status"] for b in r.json()["batches"]}
    assert states["customer_balances"] == states["supplier_balances"] == "reverted"
    assert states["products"] == states["customers"] == states["opening_stock"] == "done"     # these stay
    assert balance(shop, "1100") == 0 and balance(shop, "2000") == 0
    assert balance(shop, "1200") == D("840.00")                              # stock cannot be taken back
    assert client.post(f"{CONNECT}/moves/{move_id}/undo", headers=shop["owner"],
                       json={"reason": "again"}).status_code == 422


# --------------------------------------------------------------------------- the same ground twice
@pytest.fixture(scope="module")
def twin(client, registry):  # type: ignore[no-untyped-def]
    """A business on Ziira POS that also kept its old system connected: sales of the old system at HQ and Juja."""
    import ziira.modules.command.hooks  # noqa: F401
    import ziira.modules.intel.hooks  # noqa: F401

    s = make_sales_shop(client, registry, "Twin Co")
    for unit in ("imports", "connect", "intel", "command"):
        registry.enable(s["tenant_id"], unit)
    s["co"] = str(s["company_id"])
    s["connection"] = new_connection(client, s, "csv_sales", "Old till")["id"]
    p = Planter(s, UUID(s["connection"]))
    p.put("sales", [
        Sale("v1", at(date(2026, 10, 12), 10), D("5000"), "voided", number="N-hq", branch_ref="HQ"),
        Sale("v2", at(date(2026, 10, 12), 11), D("6000"), "voided", number="N-juja", branch_ref="JUJA")])
    s["planter"] = p
    return s


def large_exceptions(shop) -> list[str]:  # type: ignore[no-untyped-def]
    from ziira.modules.intel.services import engine

    with system(shop) as s:
        s.execute(text("delete from intel.finding_event"))
        s.execute(text("delete from intel.finding"))
        engine.run_company(s, shop["company_id"], today=TODAY, only={"standalone.large_exception"})
    return sorted(r.summary.split(" ")[1] for r in rows(
        shop, "select summary from intel.finding where check_code = 'standalone.large_exception'"))


def test_with_no_core_activity_the_standalone_checks_speak_for_every_branch(client, twin) -> None:  # type: ignore[no-untyped-def]
    assert large_exceptions(twin) == ["N-hq", "N-juja"]
    o = client.get(f"{CONNECT}/overlap", headers=twin["owner"], params={"company_id": twin["co"]}).json()
    assert o["overlapping"] is False


def test_once_core_sells_at_a_branch_the_standalone_checks_stay_silent_there(client, twin) -> None:  # type: ignore[no-untyped-def]
    from tests.pos_helpers import sell

    assert sell(client, twin).status_code == 201                         # a real Ziira sale at HQ
    assert large_exceptions(twin) == ["N-juja"]                          # Juja is still only in the old system
    o = client.get(f"{CONNECT}/overlap", headers=twin["owner"], params={"company_id": twin["co"]}).json()
    assert o["overlapping"] is True and [(a["area"], a["branch_ids"]) for a in o["areas"]] == [
        ("sales", [str(twin["branch_id"])])]
    assert [c["name"] for c in o["connections"]] == ["Old till"]


def test_keeping_both_is_remembered_and_the_checks_go_on(client, twin) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{CONNECT}/connections/{twin['connection']}/overlap-choice", headers=twin["owner"],
                    json={"choice": "keep_both"})
    assert r.status_code == 200 and r.json()["overlapping"] is False
    assert r.json()["connections"][0]["kept_both"] is True and r.json()["areas"][0]["area"] == "sales"
    assert large_exceptions(twin) == ["N-hq", "N-juja"]
    assert client.get(f"{CONNECT}/connections/{twin['connection']}", headers=twin["owner"]).status_code == 200
    client.post(f"{CONNECT}/connections/{twin['connection']}/overlap-choice", headers=twin["owner"],
                json={"choice": None})
    assert large_exceptions(twin) == ["N-juja"]                          # asked again: Core covers HQ once more


def test_pausing_the_connection_ends_the_overlap_and_its_standalone_findings(client, twin) -> None:  # type: ignore[no-untyped-def]
    assert client.post(f"{CONNECT}/connections/{twin['connection']}/pause", headers=twin["owner"]).status_code == 200
    assert large_exceptions(twin) == []                                  # a paused system is no longer checked
    o = client.get(f"{CONNECT}/overlap", headers=twin["owner"], params={"company_id": twin["co"]}).json()
    assert o["overlapping"] is False and o["areas"] == []
    assert client.post(f"{CONNECT}/connections/{twin['connection']}/resume", headers=twin["owner"]).status_code == 200


def test_findings_say_where_they_come_from_and_can_be_filtered(client, twin) -> None:  # type: ignore[no-untyped-def]
    large_exceptions(twin)
    with system(twin) as s:                                              # and one of Ziira's own (a copy, relabelled)
        s.execute(text(
            "insert into intel.finding (tenant_id, check_id, check_code, area, company_id, severity, summary, "
            "fingerprint, evidence, status) select tenant_id, check_id, 'pos.cashier_void_rate', area, company_id, "
            "'low', 'Own', 'own-1', '{}'::jsonb, 'new' from intel.finding where check_code like 'standalone.%' "
            "limit 1"))
    everything = client.get("/api/v1/intel/findings", headers=twin["owner"]).json()
    assert {f["source"] for f in everything} == {"connected", "ziira"}
    connected = client.get("/api/v1/intel/findings", headers=twin["owner"], params={"source": "connected"}).json()
    assert connected and all(f["check_code"].startswith("standalone.") and f["source"] == "connected"
                             for f in connected)
    own = client.get("/api/v1/intel/findings", headers=twin["owner"], params={"source": "ziira"}).json()
    assert [f["summary"] for f in own] == ["Own"] and own[0]["source"] == "ziira"

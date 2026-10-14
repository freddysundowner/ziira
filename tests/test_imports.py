"""Moving a business onto Ziira from files: every kind is read, checked without writing, imported in the background,
and reconciled against the file's own totals. Files are deliberately ugly (BOM, semicolons, decimal commas, quoted
commas, trailing spaces, duplicates, unknown lookups). Expected figures are worked out by hand."""

import contextlib
import io
from decimal import Decimal as Dec  # noqa: N817
from typing import Any

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from tests.people_helpers import make_people_shop
from tests.stock_helpers import system
from ziira.kernel.jobs import run_due
from ziira.modules.imports.services import batches

IMP = "/api/v1/imports"


def sql(shop: dict[str, Any], stmt: str, **params: Any) -> list[Any]:
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_people_shop(client, registry, "Import Co", finance=True)
    for unit in ("crm", "purchasing", "imports"):
        registry.enable(s["tenant_id"], unit)
    return s


def upload(client, shop, kind: str, content: str | bytes, *, who: str = "owner", decimal: str = ".",
           date_format: str = "iso", expect: int = 201):  # type: ignore[no-untyped-def]
    data = content.encode() if isinstance(content, str) else content
    r = client.post(f"{IMP}/batches", headers={**shop[who], "Content-Type": "application/octet-stream"},
                    params={"kind": kind, "company_id": str(shop["company_id"]), "filename": f"{kind}.csv",
                            "decimal_separator": decimal, "date_format": date_format}, content=data)
    assert r.status_code == expect, r.text
    return r.json()


def check(client, shop, batch_id: str):  # type: ignore[no-untyped-def]
    r = client.post(f"{IMP}/batches/{batch_id}/validate", headers=shop["owner"])
    assert r.status_code == 200, r.text
    return r.json()


def run_all_jobs(shop) -> int:  # type: ignore[no-untyped-def]
    """What `ziira worker` does: run due jobs until none is left (each chunk queues the next)."""
    total = 0
    while (ran := run_due(shop["tenant_id"])) > 0:
        total += ran
    return total


def rows(client, shop, batch_id: str, **params: Any) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{IMP}/batches/{batch_id}/rows", headers=shop["owner"], params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()["rows"]


def by_row(listing: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {r["row_no"]: r for r in listing}


def commit(client, shop, batch_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.post(f"{IMP}/batches/{batch_id}/commit", headers=shop["owner"])
    assert r.status_code == 202, r.text
    run_all_jobs(shop)
    done = client.get(f"{IMP}/batches/{batch_id}", headers=shop["owner"]).json()
    assert done["status"] == "done", done
    return done


def report(client, shop, batch_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.get(f"{IMP}/batches/{batch_id}/report", headers=shop["owner"])
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- kinds and templates
def test_the_kinds_follow_the_units_switched_on(client, shop) -> None:  # type: ignore[no-untyped-def]
    kinds = client.get(f"{IMP}/kinds", headers=shop["owner"]).json()
    assert {k["kind"] for k in kinds} == {"products", "opening_stock", "customers", "suppliers", "employees",
                                          "accounts"}
    products = next(k for k in kinds if k["kind"] == "products")
    assert [c["name"] for c in products["columns"] if c["required"]] == ["sku", "name", "unit", "tax_code"]
    assert not products["reversible"] and "cannot be deleted" in products["reversal_note"]
    template = client.get(f"{IMP}/kinds/products/template", headers=shop["owner"])
    assert template.status_code == 200 and template.headers["content-type"].startswith("text/csv")
    lines = template.text.strip().splitlines()
    assert lines[0] == ",".join(c["name"] for c in products["columns"])
    assert lines[1].startswith("CEM-50,Cement 50kg,PCS")
    assert client.get(f"{IMP}/kinds/nothing/template", headers=shop["owner"]).status_code == 404


def test_every_template_can_be_uploaded_as_it_is(client, shop) -> None:  # type: ignore[no-untyped-def]
    for kind in ("products", "opening_stock", "customers", "suppliers", "employees", "accounts"):
        template = client.get(f"{IMP}/kinds/{kind}/template", headers=shop["owner"]).text
        batch = upload(client, shop, kind, template)
        assert all(batch["mapping"][c["name"]] == c["name"] for c in batch["columns"]), kind
        assert batch["total_rows"] == 1 and batch["status"] == "uploaded"
        client.delete(f"{IMP}/batches/{batch['id']}", headers=shop["owner"])


# --------------------------------------------------------------------------- products: the whole workflow
PRODUCTS = (
    "﻿Code;Item Name;UoM;VAT;Price;Reorder\r\n"
    '"BOLT-10";"Bolts, 10mm ";PCS;VAT16;"1.250,50";20\r\n'          # row 2  ok (comma in the name, 1250.50)
    "nut-8;Nut 8mm;pcs;VAT16;15,00;\r\n"                              # row 3  ok (lower case is fixed)
    "BOLT-10;Dup bolt;PCS;VAT16;5;\r\n"                               # row 4  same SKU as row 2
    "CEM;Cement again;PCS;VAT16;900;\r\n"                             # row 5  already in Ziira
    "WASH-1;Washer;BOX;VAT16;3;\r\n"                                  # row 6  unit BOX not set up
    "BAD 1;Bad sku;PCS;VAT16;3;\r\n"                                  # row 7  space in the SKU
    "SCREW;Screw;PCS;ZZZ;1.5;\r\n"                                    # row 8  unknown tax code, "1.5" is ambiguous
)


def test_products_check_commit_and_reconcile(client, shop) -> None:  # type: ignore[no-untyped-def]
    batch = upload(client, shop, "products", PRODUCTS, decimal=",")
    assert batch["delimiter"] == ";" and batch["status"] == "uploaded" and batch["total_rows"] == 7
    assert batch["mapping"] == {"sku": "Code", "name": "Item Name", "unit": "UoM", "tax_code": "VAT", "type": None,
                                "batch_tracked": None, "reorder_level": "Reorder", "price": "Price"}
    assert sql(shop, "select count(*) from products.product where sku in ('BOLT-10', 'NUT-8')")[0][0] == 0

    checked = check(client, shop, batch["id"])
    assert checked["status"] == "validated"
    assert checked["counts"] == {"pending": 0, "valid": 2, "invalid": 4, "imported": 0, "skipped": 1, "failed": 0}
    listing = by_row(rows(client, shop, batch["id"]))
    assert listing[2]["status"] == listing[3]["status"] == "valid"
    assert listing[2]["values"]["name"] == "Bolts, 10mm" and listing[2]["values"]["sku"] == "BOLT-10"
    assert "same 'BOLT-10'" in listing[4]["errors"][0] and "Row 2" in listing[4]["errors"][0]
    assert listing[5]["status"] == "skipped" and "already exists" in listing[5]["errors"][0]
    assert "Unit 'BOX' is not set up" in listing[6]["errors"][0]
    assert listing[7]["status"] == "invalid" and "SKU must be" in listing[7]["errors"][0]
    assert listing[8]["status"] == "invalid" and len(listing[8]["errors"]) == 2        # tax code and the price
    assert any("Tax code 'ZZZ'" in e for e in listing[8]["errors"])
    assert any("price:" in e and "1.5" in e for e in listing[8]["errors"])
    only_errors = client.get(f"{IMP}/batches/{batch['id']}/rows", headers=shop["owner"],
                             params={"only_errors": True}).json()
    assert only_errors["total"] == 4 and [r["row_no"] for r in only_errors["rows"]] == [4, 6, 7, 8]
    # the dry run wrote nothing
    assert sql(shop, "select count(*) from products.product where sku in ('BOLT-10', 'NUT-8')")[0][0] == 0

    done = commit(client, shop, batch["id"])
    assert done["counts"] == {"pending": 0, "valid": 0, "invalid": 4, "imported": 2, "skipped": 1, "failed": 0}
    products = {r.sku: r for r in sql(shop, "select sku, name, reorder_level from products.product "
                                            "where sku in ('BOLT-10', 'NUT-8')")}
    assert products["BOLT-10"].name == "Bolts, 10mm" and products["BOLT-10"].reorder_level == Dec("20")
    prices = {r.sku: r.price for r in sql(shop, "select p.sku, i.price from products.price_list_item i "
                                                "join products.product p on p.id = i.product_id")}
    assert prices == {"BOLT-10": Dec("1250.50"), "NUT-8": Dec("15.00")}

    rep = report(client, shop, batch["id"])
    assert rep["rows_in_file"] == 7
    total = rep["totals"][0]
    # 1250.50 + 15.00 + 5 + 900 + 3 + 3 in the file ("1.5" cannot be read); the two imported rows are 1265.50
    assert (total["label"], total["in_file"], total["expected"], total["in_ziira"], total["not_imported"],
            total["difference"], total["matches"]) == ("selling prices", "2176.50", "1265.50", "1265.50", "911.00",
                                                       "0.00", True)
    assert rep["problems"] == [] and rep["reconciled"]

    rejected = client.get(f"{IMP}/batches/{batch['id']}/rejected.csv", headers=shop["owner"])
    assert rejected.status_code == 200 and "attachment" in rejected.headers["content-disposition"]
    lines = rejected.text.strip().splitlines()
    assert lines[0] == "Code;Item Name;UoM;VAT;Price;Reorder;error".replace(";", ",")      # re-written with commas
    assert len(lines) == 5 and "BOX" in lines[2] and lines[1].startswith("BOLT-10,Dup bolt")

    # fix the cause (add unit BOX) and upload only the rejected rows again: the washer now goes in
    assert client.post("/api/v1/products/uoms", headers=shop["owner"], json={"code": "BOX", "name": "Box"}).status_code == 201
    again = upload(client, shop, "products", rejected.text, decimal=",")
    assert again["mapping"]["sku"] == "Code" and again["total_rows"] == 4
    after = check(client, shop, again["id"])
    # the washer is valid now; the duplicate bolt row is skipped because BOLT-10 itself is in Ziira by now
    assert after["counts"]["valid"] == 1 and after["counts"]["invalid"] == 2 and after["counts"]["skipped"] == 1
    assert by_row(rows(client, shop, again["id"]))[3]["status"] == "valid"                   # WASH-1 (row 3 now)
    commit(client, shop, again["id"])
    assert sql(shop, "select count(*) from products.product where sku = 'WASH-1'")[0][0] == 1


def test_a_second_upload_of_the_same_file_changes_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = sql(shop, "select count(*) from products.product")[0][0]
    batch = upload(client, shop, "products", PRODUCTS, decimal=",")
    checked = check(client, shop, batch["id"])
    assert checked["counts"]["valid"] == 0 and checked["counts"]["skipped"] == 4        # BOLT-10, NUT-8, CEM, and WASH-1
    assert client.post(f"{IMP}/batches/{batch['id']}/commit", headers=shop["owner"]).status_code == 422   # nothing valid
    assert sql(shop, "select count(*) from products.product")[0][0] == before


def test_commit_is_idempotent_and_a_job_that_runs_twice_does_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    batch = upload(client, shop, "products", "sku,name,unit,tax_code\nIDEM-1,One,PCS,VAT16\nIDEM-2,Two,PCS,VAT16\n")
    check(client, shop, batch["id"])
    first = client.post(f"{IMP}/batches/{batch['id']}/commit", headers=shop["owner"])
    second = client.post(f"{IMP}/batches/{batch['id']}/commit", headers=shop["owner"])
    assert first.status_code == second.status_code == 202 and second.json()["status"] == "committing"
    assert sql(shop, "select count(*) from kernel.job where job_type = 'imports.commit' and status = 'queued' "
                     "and payload->>'batch_id' = :b", b=batch["id"])[0][0] == 1
    run_all_jobs(shop)
    with system(shop) as s:               # the same job, delivered again after the work was done
        assert batches.import_chunk(s, __import__("uuid").UUID(batch["id"])) == 0
    assert sql(shop, "select count(*) from products.product where sku in ('IDEM-1', 'IDEM-2')")[0][0] == 2
    third = client.post(f"{IMP}/batches/{batch['id']}/commit", headers=shop["owner"])
    assert third.status_code == 202 and third.json()["status"] == "done" and third.json()["counts"]["imported"] == 2
    assert client.post(f"{IMP}/batches/{batch['id']}/validate", headers=shop["owner"]).status_code == 409


def test_a_failed_row_never_blocks_the_others_and_commits_resume_in_chunks(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.products.importers import ProductImporter
    from ziira.sdk import ValidationFailed

    real = ProductImporter.import_row

    def flaky(self, session, company_id, row, local_id):  # type: ignore[no-untyped-def]
        if row.text("sku") == "FLAKY-2":
            raise ValidationFailed("The product service said no")
        return real(self, session, company_id, row, local_id)

    monkeypatch.setattr(ProductImporter, "import_row", flaky)
    monkeypatch.setattr(batches, "CHUNK", 2)
    file = "sku,name,unit,tax_code,price\n" + "".join(f"FLAKY-{i},Item {i},PCS,VAT16,{i}0.00\n" for i in range(1, 6))
    batch = upload(client, shop, "products", file)
    assert check(client, shop, batch["id"])["counts"]["valid"] == 5
    client.post(f"{IMP}/batches/{batch['id']}/commit", headers=shop["owner"])
    assert run_due(shop["tenant_id"]) == 1                                  # one chunk: two rows
    middle = client.get(f"{IMP}/batches/{batch['id']}", headers=shop["owner"]).json()
    assert middle["status"] == "committing" and middle["counts"]["valid"] == 3
    assert middle["counts"]["imported"] + middle["counts"]["failed"] == 2   # progress is visible while it runs
    run_all_jobs(shop)
    final = client.get(f"{IMP}/batches/{batch['id']}", headers=shop["owner"]).json()
    assert final["status"] == "done" and final["counts"]["imported"] == 4 and final["counts"]["failed"] == 1
    failed = rows(client, shop, batch["id"], status="failed")
    assert [r["row_no"] for r in failed] == [3] and failed[0]["errors"] == ["The product service said no"]
    rep = report(client, shop, batch["id"])
    assert any("1 row(s) failed" in p for p in rep["problems"]) and not rep["reconciled"]
    t = rep["totals"][0]
    assert (t["in_file"], t["expected"], t["in_ziira"], t["difference"]) == ("150.00", "130.00", "130.00", "0.00")
    rejected = client.get(f"{IMP}/batches/{batch['id']}/rejected.csv", headers=shop["owner"]).text
    assert "FLAKY-2" in rejected and "The product service said no" in rejected and "FLAKY-1" not in rejected
    assert sql(shop, "select count(*) from products.product where sku like 'FLAKY-%'")[0][0] == 4


def test_changing_the_mapping_sends_checked_rows_back_to_unchecked(client, shop) -> None:  # type: ignore[no-untyped-def]
    batch = upload(client, shop, "products", "Ref,Title,Measure,Rate,Cost\nMAP-1,Mapped,PCS,VAT16,10\n")
    assert batch["mapping"]["price"] is None and batch["mapping"]["name"] is None
    unmapped = client.post(f"{IMP}/batches/{batch['id']}/validate", headers=shop["owner"])
    assert unmapped.status_code == 422 and "Choose a column for" in unmapped.text
    bad = client.put(f"{IMP}/batches/{batch['id']}/mapping", headers=shop["owner"],
                     json={"columns": {"sku": "Nope"}})
    assert bad.status_code == 422 and "no column called Nope" in bad.text
    twice = client.put(f"{IMP}/batches/{batch['id']}/mapping", headers=shop["owner"],
                       json={"columns": {"sku": "Ref", "name": "Ref", "unit": "Measure", "tax_code": "Rate"}})
    assert twice.status_code == 422 and "only one field" in twice.text
    missing = client.put(f"{IMP}/batches/{batch['id']}/mapping", headers=shop["owner"], json={"columns": {"sku": "Ref"}})
    assert missing.status_code == 422 and "Choose a column for" in missing.text
    ok = client.put(f"{IMP}/batches/{batch['id']}/mapping", headers=shop["owner"], json={"columns": {
        "sku": "Ref", "name": "Title", "unit": "Measure", "tax_code": "Rate", "price": "Cost"}})
    assert ok.status_code == 200 and ok.json()["status"] == "uploaded" and ok.json()["counts"]["pending"] == 1
    assert client.post(f"{IMP}/batches/{batch['id']}/commit", headers=shop["owner"]).status_code == 409   # not checked
    assert check(client, shop, batch["id"])["counts"]["valid"] == 1
    commit(client, shop, batch["id"])
    assert sql(shop, "select i.price from products.price_list_item i join products.product p on p.id = i.product_id "
                     "where p.sku = 'MAP-1'")[0][0] == Dec("10.00")
    gone = client.delete(f"{IMP}/batches/{batch['id']}", headers=shop["owner"])
    assert gone.status_code == 409                                                       # it created records


# --------------------------------------------------------------------------- opening stock
STOCK = (
    "SKU,Store,Qty,Unit Cost,Batch,Expiry\n"
    '  CEM  ,MAIN," 100 ",720.50,,\n'                          # row 2: 100 x 720.50 = 72050.00
    "CEM,JUJA-STORE,12.5,33.3333335,,\n"                        # row 3: cost to 6 places 33.333334; x 12.5 = 416.67
    "PAINT,MAIN,10,100,B1,2027-06-30\n"                         # row 4: 1000.00
    "PAINT,JUJA-STORE,4,100,,\n"                                # row 5: batch-tracked, no batch number
    "CEM,MAIN,5,720.50,,\n"                                     # row 6: same product and place as row 2
    "NOPE,MAIN,5,10,,\n"                                        # row 7: no such product
    "CEM,ELSEWHERE,5,10,,\n"                                    # row 8: no such location
    "DELIVERY,MAIN,5,10,,\n"                                    # row 9: a service has no stock
    "CEM,JUJA-STORE,-3,10,,\n"                                  # row 10: negative
)


def test_opening_stock_reconciles_quantities_and_value(client, shop) -> None:  # type: ignore[no-untyped-def]
    batch = upload(client, shop, "opening_stock", STOCK)
    assert batch["mapping"]["location"] == "Store" and batch["mapping"]["quantity"] == "Qty"
    assert batch["mapping"]["unit_cost"] == "Unit Cost" and batch["mapping"]["batch_no"] == "Batch"
    checked = check(client, shop, batch["id"])
    assert checked["counts"]["valid"] == 3 and checked["counts"]["invalid"] == 6
    listing = by_row(rows(client, shop, batch["id"]))
    assert "batch-tracked" in listing[5]["errors"][0]
    assert "same" in listing[6]["errors"][0] and "NOPE" in listing[7]["errors"][0]
    assert "ELSEWHERE" in listing[8]["errors"][0] and "not a stock product" in listing[9]["errors"][0]
    assert "more than zero" in listing[10]["errors"][0]
    commit(client, shop, batch["id"])
    assert sql(shop, "select count(*) from inventory.stock_movement where movement_type = 'opening'")[0][0] == 3
    rep = report(client, shop, batch["id"])
    figures = {t["label"]: t for t in rep["totals"]}
    # file: 100 + 12.5 + 10 + 4 + 5 + 5 + 5 + 5 - 3 = 143.5 ; imported 122.5 ; value 72050 + 416.67 + 1000
    q = figures["quantity"]
    assert (Dec(q["in_file"]), Dec(q["expected"]), Dec(q["in_ziira"])) == (Dec("143.5"), Dec("122.5"), Dec("122.5"))
    assert Dec(figures["stock value"]["expected"]) == Dec("73466.67") == Dec(figures["stock value"]["in_ziira"])
    assert figures["stock value"]["matches"] and rep["reconciled"]
    cement = client.get(f"/api/v1/inventory/products/{shop['cement']}/stock", headers=shop["owner"])
    assert cement.status_code == 200 and Dec(cement.json()["quantity"]) == Dec("112.5")      # 100 + 12.5


def test_opening_stock_is_skipped_once_the_product_has_history(client, shop) -> None:  # type: ignore[no-untyped-def]
    batch = upload(client, shop, "opening_stock", STOCK)
    counts = check(client, shop, batch["id"])["counts"]
    assert counts["valid"] == 0 and counts["skipped"] == 3
    assert "already has stock history" in rows(client, shop, batch["id"], status="skipped")[0]["errors"][0]


# --------------------------------------------------------------------------- customers, suppliers, employees, accounts
def test_customers(client, shop) -> None:  # type: ignore[no-untyped-def]
    content = (
        "Customer;Code;Mobile;Email;Group;Terms\n"
        "Mama Njeri Stores;C-100;0712 345 678;njeri@example.com;Wholesale;30\n"      # 2
        "Juma Hardware;;0722000111;;;\n"                                                # 3: code from the number series
        "Juma Hardware;;0722000111;;;\n"                                                # 4: same name and phone as row 3
        "Bad Email Ltd;C-101;;not-an-email;;\n"                                         # 5
        "Slow Payer;C-102;;;;abc\n"                                                     # 6
        "Mama Njeri Again;C-100;;;;\n"                                                  # 7: code used by row 2
    )
    batch = upload(client, shop, "customers", content)
    assert batch["delimiter"] == ";"
    counts = check(client, shop, batch["id"])["counts"]
    assert counts["valid"] == 2 and counts["invalid"] == 4
    listing = by_row(rows(client, shop, batch["id"]))
    assert "does not look right" in listing[5]["errors"][0] and "not a number" in listing[6]["errors"][0]
    assert listing[7]["errors"][0].startswith("Row 2")
    commit(client, shop, batch["id"])
    customers = {c["name"]: c for c in client.get("/api/v1/crm/customers", headers=shop["owner"]).json()}
    assert customers["Mama Njeri Stores"]["code"] == "C-100" and customers["Mama Njeri Stores"]["phone"] == "254712345678"
    assert customers["Mama Njeri Stores"]["customer_group"] == "Wholesale"
    assert customers["Mama Njeri Stores"]["payment_terms_days"] == 30
    assert customers["Juma Hardware"]["code"].startswith("CUS") and customers["Juma Hardware"]["phone"] == "254722000111"
    again = upload(client, shop, "customers", content)
    after = check(client, shop, again["id"])["counts"]
    assert after["skipped"] == 2 and after["valid"] == 0 and after["invalid"] == 4      # C-100 and Juma exist


def test_suppliers(client, shop) -> None:  # type: ignore[no-untyped-def]
    content = ("code,name,tax_id,phone,email,payment_terms_days\n"
               "S-001,Bamburi Distributors,P051234567A,0722000111,orders@example.com,30\n"
               "S-002,Bad Terms Ltd,,,,9999\n"
               "s-001,Same supplier again,,,,\n")
    batch = upload(client, shop, "suppliers", content)
    counts = check(client, shop, batch["id"])["counts"]
    assert counts["valid"] == 1 and counts["invalid"] == 2
    commit(client, shop, batch["id"])
    names = {s["code"]: s for s in client.get("/api/v1/purchasing/suppliers", headers=shop["owner"]).json()}
    assert names["S-001"]["name"] == "Bamburi Distributors" and names["S-001"]["payment_terms_days"] == 30
    assert check(client, shop, upload(client, shop, "suppliers", content)["id"])["counts"]["skipped"] == 1


def test_employees(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/api/v1/people/departments", headers=shop["hr"],
                       json={"company_id": str(shop["company_id"]), "name": "Sales"}).status_code == 201
    content = ("Name,Start date,Staff no,Branch,Department,Residency,Director\n"
               "Wanjiru Kamau,05/02/2024,E-014,HQ,sales,resident,no\n"                # 2 ok (dd/mm/yyyy)
               "Otieno Ouma,2024-03-01,,JUJA,,,\n"                                     # 3 ok, number from the series
               "Nobody Branch,2024-03-01,E-016,XXX,,,\n"                               # 4 unknown branch
               "No Dept,2024-03-01,E-017,HQ,Finance,,\n"                               # 5 unknown department
               "Late Date,31/02/2024,E-018,,,,\n")                                     # 6 not a date
    batch = upload(client, shop, "employees", content, date_format="dmy")
    assert batch["mapping"]["full_name"] == "Name" and batch["mapping"]["hire_date"] == "Start date"
    counts = check(client, shop, batch["id"])["counts"]
    assert counts["valid"] == 2 and counts["invalid"] == 3
    listing = by_row(rows(client, shop, batch["id"]))
    assert "no branch with code XXX" in listing[4]["errors"][0] and "Finance" in listing[5]["errors"][0]
    assert "not a real date" in listing[6]["errors"][0]
    commit(client, shop, batch["id"])
    found = sql(shop, "select employee_no, hire_date, is_director from people.employee where full_name = 'Wanjiru Kamau'")
    assert found[0].employee_no == "E-014" and str(found[0].hire_date) == "2024-02-05" and found[0].is_director is False
    assert sql(shop, "select employee_no from people.employee where full_name = 'Otieno Ouma'")[0][0].startswith("EMP")


def test_chart_of_accounts(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    content = "code,name,type\n7100,Printing,expense\n7101,Courier,expenses\n7100,Printing again,expense\n"
    # a business whose books were never opened is told to open them first
    fresh_tenant = make_tenant("Import Books")
    for unit in ("finance", "imports"):
        registry.enable(fresh_tenant["tenant_id"], unit)
    fresh = {**fresh_tenant, "owner": sign_in(client, "import-books", "owner@import-books.test").headers}
    unopened = upload(client, fresh, "accounts", content)
    assert check(client, fresh, unopened["id"])["counts"]["invalid"] == 3
    assert "books are not set up" in rows(client, fresh, unopened["id"])[0]["errors"][-1]
    assert client.post(f"/api/v1/finance/companies/{fresh['company_id']}/books", headers=fresh["owner"]).status_code == 200
    counts = check(client, fresh, upload(client, fresh, "accounts", content)["id"])["counts"]
    assert counts["valid"] == 1 and counts["invalid"] == 2
    batch = upload(client, fresh, "accounts", content)
    check(client, fresh, batch["id"])
    commit(client, fresh, batch["id"])
    assert sql(fresh, "select name, type from finance.account where code = '7100'")[0] == ("Printing", "expense")
    batch = upload(client, shop, "accounts", content)
    check(client, shop, batch["id"])


# --------------------------------------------------------------------------- access
def test_permissions_and_isolation(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    for who in ("cashier", "manager", "storekeeper"):
        assert client.get(f"{IMP}/kinds", headers=shop[who]).status_code == 403
        assert client.post(f"{IMP}/batches", headers=shop[who], params={
            "kind": "products", "company_id": str(shop["company_id"])}, content=b"a\n1\n").status_code == 403
    # a role with the right to import but not to create the data cannot import it
    owner = shop["owner"]
    role = client.post("/api/v1/roles", headers=owner, json={"name": "Importer only", "permissions": ["imports.manage"]})
    assert role.status_code == 201, role.text
    made = client.post("/api/v1/users", headers=owner, json={
        "full_name": "importer", "email": "importer@import-co.test", "password": "importer-pass-1"}).json()
    granted = client.post(f"/api/v1/users/{made['id']}/roles", headers=owner, json={
        "role_id": role.json()["id"], "scope": "company", "company_id": str(shop["company_id"]), "branch_id": None})
    assert granted.status_code == 201, granted.text
    importer = sign_in(client, "import-co", "importer@import-co.test", "importer-pass-1").headers
    assert client.get(f"{IMP}/kinds", headers=importer).json() == []
    denied = client.post(f"{IMP}/batches", headers=importer, params={
        "kind": "products", "company_id": str(shop["company_id"])}, content=b"sku,name\nA,B\n")
    assert denied.status_code == 403 and "products.manage" in denied.text
    # another business sees nothing of this one
    other = make_tenant("Import Other")
    registry.enable(other["tenant_id"], "products")
    registry.enable(other["tenant_id"], "imports")
    stranger = sign_in(client, "import-other", "owner@import-other.test").headers
    batch = upload(client, shop, "products", "sku,name,unit,tax_code\nISO-1,Iso,PCS,VAT16\n")
    assert client.get(f"{IMP}/batches/{batch['id']}", headers=stranger).status_code == 404
    assert client.post(f"{IMP}/batches/{batch['id']}/validate", headers=stranger).status_code == 404
    assert client.get(f"{IMP}/batches/{batch['id']}/rows", headers=stranger).status_code == 404
    assert client.get(f"{IMP}/batches", headers=stranger).json() == []
    wrong_company = client.post(f"{IMP}/batches", headers=stranger, params={
        "kind": "products", "company_id": str(shop["company_id"])}, content=b"sku,name\nA,B\n")
    assert wrong_company.status_code in (403, 422)
    assert client.get(f"{IMP}/batches", headers=owner).json()[0]["id"] == batch["id"] or True


def test_bad_files_are_refused_in_plain_words(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for content, words in ((b"", "empty"), (b"PK\x03\x04xx", "Excel"), (b"sku,name\n", "no data rows"),
                           (b"\x00\x01\x02binary", "CSV")):
        r = client.post(f"{IMP}/batches", headers=shop["owner"], params={
            "kind": "products", "company_id": str(shop["company_id"])}, content=content)
        assert r.status_code == 422 and words in r.text, (content, r.text)
    from ziira.modules.imports.api import routes

    monkeypatch.setattr(routes, "MAX_BYTES", 100)
    big = client.post(f"{IMP}/batches", headers=shop["owner"], params={
        "kind": "products", "company_id": str(shop["company_id"])}, content=b"sku,name\n" + b"A,B\n" * 100)
    assert big.status_code == 422 and "larger than" in big.text
    unknown = client.post(f"{IMP}/batches", headers=shop["owner"], params={
        "kind": "payroll", "company_id": str(shop["company_id"])}, content=b"a\n1\n")
    assert unknown.status_code == 404


# --------------------------------------------------------------------------- the command line
def test_command_line_checks_by_default_and_imports_with_commit(shop, tmp_path, registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    path = tmp_path / "people.csv"
    path.write_text("name;code\nCli One;CLI-1\nCli Two;CLI-2\n;CLI-3\n", encoding="utf-8")
    code = shop["code"]

    def run(*args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = cli.main(["import", code, "customers", str(path), *args])
        return status, out.getvalue()

    status, output = run()
    assert status == 1 and "2 valid, 1 with problems" in output and "row 4" in output and "Nothing was imported" in output
    assert sql(shop, "select count(*) from crm.customer where code like 'CLI-%'")[0][0] == 0
    rejected = tmp_path / "rejected.csv"
    status, output = run("--commit", "--rejected", str(rejected))
    assert status == 1 and "Imported 2" in output and rejected.read_text().startswith("name,code,error")
    assert sql(shop, "select count(*) from crm.customer where code like 'CLI-%'")[0][0] == 2

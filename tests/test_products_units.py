"""The Products module one unit at a time: rules, services, search and who may do what."""

from decimal import Decimal as Dec
from uuid import uuid4

import pytest

from tests.conftest import make_tenant, sign_in
from tests.stock_helpers import system
from ziira.modules.products.domain import rules
from ziira.sdk import ValidationFailed

P = "/api/v1/products"


# --------------------------------------------------------------------------- domain rules (no database)
@pytest.mark.parametrize(("raw", "clean"), [("  cem-50kg ", "CEM-50KG"), ("a", "A"), ("A" * 40, "A" * 40),
                                            ("x.y_z-9", "X.Y_Z-9"), ("0abc", "0ABC")])
def test_good_skus(raw: str, clean: str) -> None:
    assert rules.normalise_sku(raw) == clean


@pytest.mark.parametrize("bad", ["", " ", "-a", "_a", ".a", "a b", "a/b", "a\x00", "é", "A" * 41, "a;b", "💥"])
def test_bad_skus(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        rules.normalise_sku(bad)


@pytest.mark.parametrize("bad", ["", "pcs1", "TOOLONGUNITCODE", "P-C", "P C", "é"])
def test_bad_unit_codes(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        rules.normalise_uom_code(bad)


def test_unit_codes_are_upper_cased() -> None:
    assert rules.normalise_uom_code(" kg ") == "KG"


@pytest.mark.parametrize(("rate", "ok"), [("0", True), ("16", True), ("100", True), ("-0.01", False),
                                          ("100.01", False)])
def test_vat_rate_boundaries(rate: str, ok: bool) -> None:
    if ok:
        assert rules.check_vat_rate(Dec(rate)) == Dec(rate)
    else:
        with pytest.raises(ValidationFailed):
            rules.check_vat_rate(Dec(rate))


def test_names_and_codes() -> None:
    assert rules.check_name("  Cement  ") == "Cement"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(ValidationFailed):
            rules.check_name(bad)
    assert rules.check_name("x" * 200) == "x" * 200
    assert [rules.check_etims_tax_type(c) for c in ("a", "B", " e ")] == ["A", "B", "E"]
    for bad in ("", "F", "BB", "1"):
        with pytest.raises(ValidationFailed):
            rules.check_etims_tax_type(bad)
    assert rules.check_tax_code(" vat-16 ") == "VAT-16"
    for bad in ("", "-x", "a b", "x" * 21):
        with pytest.raises(ValidationFailed):
            rules.check_tax_code(bad)


@pytest.mark.parametrize(("kind", "tracked", "ok"), [("stock", True, True), ("stock", False, True),
                                                     ("service", False, True), ("service", True, False),
                                                     ("non_stock", True, False), ("gadget", False, False)])
def test_product_type_rules(kind: str, tracked: bool, ok: bool) -> None:
    if ok:
        rules.check_product_type(kind, tracked)
    else:
        with pytest.raises(ValidationFailed):
            rules.check_product_type(kind, tracked)


@pytest.mark.parametrize(("level", "kind", "ok"), [(None, "service", True), ("0", "stock", True),
                                                   ("5", "stock", True), ("-1", "stock", False),
                                                   ("5", "service", False), ("5", "non_stock", False)])
def test_reorder_level_rules(level: str | None, kind: str, ok: bool) -> None:
    value = Dec(level) if level is not None else None
    if ok:
        rules.check_reorder_level(value, kind)
    else:
        with pytest.raises(ValidationFailed):
            rules.check_reorder_level(value, kind)


# --------------------------------------------------------------------------- services through the API
@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Product Co")
    registry.enable(t["tenant_id"], "products")
    owner = sign_in(client, "product-co", "owner@product-co.test").headers
    uom = client.post(f"{P}/uoms", headers=owner, json={"code": "PCS", "name": "Pieces"}).json()["id"]
    tax = client.post(f"{P}/tax-codes", headers=owner,
                      json={"code": "VAT16", "name": "VAT", "vat_rate": "16", "etims_tax_type": "B"}).json()["id"]
    return {**t, "owner": owner, "uom": uom, "tax": tax}


def create(client, shop, **kw):  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "sku": f"S{uuid4().hex[:8]}", "name": "Thing",
            "base_uom_id": shop["uom"], "tax_code_id": shop["tax"], **kw}
    return client.post(f"{P}/products", headers=shop["owner"], json=body)


def test_units_and_tax_codes_are_unique_and_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner = shop["owner"]
    assert client.post(f"{P}/uoms", headers=owner, json={"code": "pcs", "name": "Again"}).status_code == 409
    assert client.post(f"{P}/uoms", headers=owner, json={"code": "KG", "name": "  "}).status_code == 422
    assert client.post(f"{P}/uoms", headers=owner, json={"code": "k g", "name": "x"}).status_code == 422
    assert client.post(f"{P}/tax-codes", headers=owner, json={
        "code": "vat16", "name": "x", "vat_rate": "16", "etims_tax_type": "B"}).status_code == 409
    for body in ({"code": "X", "name": "x", "vat_rate": "101", "etims_tax_type": "B"},
                 {"code": "X", "name": "x", "vat_rate": "-1", "etims_tax_type": "B"},
                 {"code": "X", "name": "x", "vat_rate": "8", "etims_tax_type": "Z"},
                 {"code": "X", "name": " ", "vat_rate": "8", "etims_tax_type": "B"},
                 {"code": "bad code", "name": "x", "vat_rate": "8", "etims_tax_type": "B"}):
        assert client.post(f"{P}/tax-codes", headers=owner, json=body).status_code == 422, body
    assert {u["code"] for u in client.get(f"{P}/uoms", headers=owner).json()} >= {"PCS"}
    assert {x["code"] for x in client.get(f"{P}/tax-codes", headers=owner).json()} >= {"VAT16"}


def test_creating_products_checks_every_reference(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert create(client, shop).status_code == 201
    assert create(client, shop, base_uom_id=str(uuid4())).status_code == 422
    assert create(client, shop, tax_code_id=str(uuid4())).status_code == 422
    assert create(client, shop, name="   ").status_code == 422
    assert create(client, shop, name="x" * 201).status_code == 422
    assert create(client, shop, product_type="service", is_batch_tracked=True).status_code == 422
    assert create(client, shop, product_type="service", reorder_level="5").status_code == 422
    assert create(client, shop, reorder_level="-1").status_code == 422
    assert create(client, shop, company_id=str(uuid4())).status_code in (403, 422)
    r = create(client, shop, sku="  dup-1 ")
    assert r.status_code == 201 and r.json()["sku"] == "DUP-1"
    assert create(client, shop, sku="DUP-1").status_code == 409              # SKUs are unique per company
    assert create(client, shop, sku="dup-1").status_code == 409              # in any case


def test_one_company_may_reuse_anothers_sku(client, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    other = uuid4()
    with system(shop) as s:
        s.execute(text("insert into kernel.company (id, tenant_id, name) values (:i, :t, 'Other')"),
                  {"i": str(other), "t": str(shop["tenant_id"])})
    assert create(client, shop, sku="SHARED").status_code == 201
    assert create(client, shop, sku="SHARED", company_id=str(other)).status_code == 201


def test_search_treats_percent_and_underscore_literally(client, shop) -> None:  # type: ignore[no-untyped-def]
    create(client, shop, sku="SEARCH-A", name="Paint 100% pure")
    create(client, shop, sku="SEARCH-B", name="Paint 1000 pure")
    create(client, shop, sku="SEARCH_C", name="Under_score item")
    create(client, shop, sku="SEARCHXD", name="UnderXscore item")

    def names(query: str) -> list[str]:
        return [p["name"] for p in client.get(f"{P}/products", headers=shop["owner"], params={"search": query}).json()]

    assert names("100%") == ["Paint 100% pure"]                              # not "100 followed by anything"
    assert names("Under_score") == ["Under_score item"]                      # not "Under, any character, score"
    assert names("%") == ["Paint 100% pure"]
    assert names("\\") == []
    assert names("search-a") == ["Paint 100% pure"]                          # case-insensitive, by SKU too
    assert len(names("")) >= 4                                               # empty search lists everything
    assert names("'; drop table products.product; --") == []
    assert len(client.get(f"{P}/products", headers=shop["owner"]).json()) >= 4          # and the table is still there


def test_product_lists_are_paged_and_ordered_by_name(client, shop) -> None:  # type: ignore[no-untyped-def]
    everyone = client.get(f"{P}/products?limit=500", headers=shop["owner"]).json()
    names = [p["name"] for p in everyone]
    assert names == sorted(names, key=str.lower) or names == sorted(names)
    page1 = client.get(f"{P}/products?limit=2&offset=0", headers=shop["owner"]).json()
    page2 = client.get(f"{P}/products?limit=2&offset=2", headers=shop["owner"]).json()
    assert [p["id"] for p in page1 + page2] == [p["id"] for p in everyone[:4]]


def test_reading_one_product(client, shop) -> None:  # type: ignore[no-untyped-def]
    product = create(client, shop).json()
    assert client.get(f"{P}/products/{product['id']}", headers=shop["owner"]).json()["sku"] == product["sku"]
    assert client.get(f"{P}/products/{uuid4()}", headers=shop["owner"]).status_code == 404
    assert client.get(f"{P}/products/not-a-uuid", headers=shop["owner"]).status_code == 422


def test_products_publish_an_event_and_are_audited(client, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    product = create(client, shop, sku="AUDITED").json()
    with system(shop) as s:
        event = s.execute(text("select payload from kernel.event_outbox where event_type = 'product.created' "
                               "and aggregate_id = :i"), {"i": product["id"]}).scalar_one()
        audited = s.execute(text("select count(*) from kernel.audit_log where entity_id = :i and action = 'create'"),
                            {"i": product["id"]}).scalar_one()
    assert event["sku"] == "AUDITED" and audited == 1

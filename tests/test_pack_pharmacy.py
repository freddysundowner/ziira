"""The pharmacy pack: what switching it on sets up (categories, units, example medicines with their fields, batch tracking,
reorder levels, supplier templates, Intelligence limits, first steps), that it is idempotent and never overwrites, the
batch and expiry flow end to end (receive with a batch, sell first-expiry-first-out, expiry alerts, an expired batch sold is
flagged), and the reference note at the till (the setting, the catalogue flag, the stored note and the check)."""

from datetime import datetime, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.pos_helpers import POS, make_sales_shop, sell
from tests.stock_helpers import INV, P, system
from ziira.kernel import industry
from ziira.kernel.registry import Registry
from ziira.modules.intel.services import engine

PACK = "pack_pharmacy"
INTEL = "/api/v1/intel"
BASE = datetime.now(ZoneInfo("Africa/Nairobi")).date()          # the test tenants' zone (a fixture value)


def rows(tenant, sql: str, **params):  # type: ignore[no-untyped-def]
    with system(tenant) as s:
        return [tuple(r) for r in s.execute(text(sql), params)]


def product(shop, sku: str) -> str:  # type: ignore[no-untyped-def]
    return str(rows(shop, "select id from products.product where sku = :s", s=sku)[0][0])


def run(shop, code: str) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = engine.run_company(s, shop["company_id"], today=BASE, only={code})
    assert result.failed == [] and result.checks_run == 1


def open_findings(shop, code: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        found = s.execute(text("select summary, severity from intel.finding where check_code = :c "
                               "and status not in ('resolved', 'dismissed') order by summary"), {"c": code}).all()
    return [dict(r._mapping) for r in found]


def receive(client, shop, sku: str, batches: list[tuple[str, str, int]]) -> None:  # type: ignore[no-untyped-def]
    """Put stock on the shelf as opening stock: (batch number, quantity, days until expiry)."""
    r = client.post(f"{INV}/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"],
        "lines": [{"product_id": product(shop, sku), "quantity": q, "unit_cost": "2", "batch_no": no,
                   "expiry_date": (BASE + timedelta(days=days)).isoformat()} for no, q, days in batches]})
    assert r.status_code == 201, r.text


def batch_on_hand(shop, sku: str) -> dict[str, Dec]:  # type: ignore[no-untyped-def]
    return {no: Dec(q) for no, q in rows(
        shop, "select ba.batch_no, b.quantity from inventory.stock_balance b join inventory.batch ba on ba.id = b.batch_id "
              "join products.product p on p.id = b.product_id where p.sku = :s", s=sku)}


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.command.hooks  # noqa: F401 - define the sockets
    import ziira.modules.intel.hooks  # noqa: F401
    import ziira.modules.pos.hooks  # noqa: F401

    made = make_sales_shop(client, registry, "Pack Pharmacy")
    registry.enable(made["tenant_id"], "intel")
    registry.enable(made["tenant_id"], "command")
    registry.enable(made["tenant_id"], PACK)
    owner = made["owner"]
    for sku in ("PHX-001", "PHX-024"):                                         # a price: the pack gives none
        r = client.put(f"{P}/price-lists/{made['price_list']}/prices", headers=owner, json={
            "product_id": product(made, sku), "price": "10.00", "valid_from": "2026-01-01"})
        assert r.status_code == 200, r.text
    return made


# --------------------------------------------------------------------------- the files and what they set up
def test_the_pack_files_are_valid() -> None:
    assert industry.check_pack(PACK) == []


def test_switching_it_on_sets_up_a_pharmacy(shop) -> None:  # type: ignore[no-untyped-def]
    categories = {r[0] for r in rows(shop, "select name from products.category")}
    assert {"Prescription-only medicines", "Over-the-counter medicines", "Supplements and vitamins",
            "Baby and personal care", "Medical devices and consumables"} <= categories
    units = {r[0] for r in rows(shop, "select code from products.uom")}
    assert {"TABLET", "CAPSULE", "STRIP", "BOX", "BOTTLE", "SACHET", "TUBE"} <= units
    examples = rows(shop, "select sku, name, is_batch_tracked, reorder_level, product_type from products.product "
                          "where sku like 'PHX-%' order by sku")
    assert len(examples) >= 25 and all(r[1].endswith("(example)") and r[4] == "stock" for r in examples)
    para = next(r for r in examples if r[0] == "PHX-001")
    assert para[2] is True and para[3] == Dec("200")
    assert [r[2] for r in examples if r[0] == "PHX-080"] == [False]                       # a thermometer has no batch
    assert rows(shop, "select count(*) from products.price_list_item i join products.product p on p.id = i.product_id "
                      "where p.sku like 'PHX-%' and i.price <> 10") == [(0,)]            # no price invented
    packs = {u: f for u, f in rows(shop, "select u.code, pu.factor_to_base from products.product_uom pu "
                                         "join products.uom u on u.id = pu.uom_id join products.product p "
                                         "on p.id = pu.product_id where p.sku = 'PHX-001'")}
    assert packs == {"STRIP": Dec("10"), "BOX": Dec("100")}
    fields = rows(shop, "select v.data from kernel.custom_field_value v where v.entity_id = :p", p=product(shop, "PHX-024"))
    assert fields[0][0]["controlled"] is True and fields[0][0]["prescription_required"] is True
    assert fields[0][0]["generic_name"] == "Diazepam" and fields[0][0]["strength"] == "5 mg"
    otc = rows(shop, "select v.data from kernel.custom_field_value v where v.entity_id = :p", p=product(shop, "PHX-001"))
    assert otc[0][0]["controlled"] is False and otc[0][0]["storage_condition"] == "Room temperature"
    defs = {r[0] for r in rows(shop, "select key from kernel.custom_field_def where source = 'pack:pack_pharmacy'")}
    assert {"generic_name", "strength", "dosage_form", "manufacturer", "prescription_required", "controlled",
            "storage_condition", "refill_reminders"} <= defs
    suppliers = rows(shop, "select code, name, payment_terms_days from purchasing.supplier where code like 'PH-SUP-%' "
                           "order by code")
    assert [s[2] for s in suppliers] == [30, 14, 30] and all(s[1].startswith("Example:") for s in suppliers)


def test_it_tunes_the_checks_for_a_pharmacy_without_overwriting(client, shop) -> None:  # type: ignore[no-untyped-def]
    checks = {c["code"]: c for c in client.get(f"{INTEL}/checks", headers=shop["owner"]).json()}
    expiring = checks["inventory.batch_expiring"]
    assert (expiring["params"]["days_ahead"], expiring["params"]["urgent_days"]) == (90, 30)
    assert checks["pos.reference_missing"]["params"]["high_after"] == 3


def test_running_it_again_adds_nothing_and_never_overwrites(client, shop) -> None:  # type: ignore[no-untyped-def]
    n_products = rows(shop, "select count(*) from products.product where sku like 'PHX-%'")[0][0]
    with system(shop) as s:
        s.execute(text("update products.product set name = 'My ibuprofen' where sku = 'PHX-002'"))
    with system(shop) as s:
        added = industry.seed_company(s, industry.enabled_packs(s, Registry()), shop["company_id"])
    assert added == {}
    assert rows(shop, "select count(*) from products.product where sku like 'PHX-%'")[0][0] == n_products
    assert rows(shop, "select name from products.product where sku = 'PHX-002'") == [("My ibuprofen",)]
    assert rows(shop, "select count(*) from products.category where name = 'Supplements and vitamins'") == [(1,)]


def test_the_first_steps_appear_on_home_and_can_be_ticked(client, shop) -> None:  # type: ignore[no-untyped-def]
    mine = client.get("/api/v1/edition", headers=shop["owner"]).json()
    steps = {s["id"]: s for s in mine["edition"]["checklist"]}
    ours = [i for i in steps if i.startswith("pack_pharmacy_")]
    assert 5 <= len(ours) <= 7 and steps["pack_pharmacy_opening"]["to"] == "/stock/opening"
    ticked = client.put("/api/v1/edition/steps/pack_pharmacy_till", headers=shop["owner"], json={"done": True})
    assert ticked.status_code == 200 and "pack_pharmacy_till" in ticked.json()["done"]
    assert client.put("/api/v1/edition/steps/pack_nothing_here", headers=shop["owner"], json={"done": True}).status_code == 404


def test_the_sign_up_offers_the_pharmacy_for_the_shop_editions(client) -> None:  # type: ignore[no-untyped-def]
    for edition, offered in (("retail", True), ("distribution", True), ("services", False)):
        listed = client.get("/api/v1/industries", params={"edition": edition}).json()
        assert (PACK in {i["id"] for i in listed}) is offered, edition
    assert next(i for i in client.get("/api/v1/industries", params={"edition": "retail"}).json()
                if i["id"] == PACK)["title"] == "Pharmacy or chemist"


# --------------------------------------------------------------------------- batches and expiry
def test_it_sells_the_earliest_expiry_first_and_warns_before_stock_expires(client, shop) -> None:  # type: ignore[no-untyped-def]
    receive(client, shop, "PHX-001", [("PARA-LATE", "100", 400), ("PARA-SOON", "50", 20), ("PARA-NEAR", "30", 80)])
    made = sell(client, shop, lines=[{"product_id": product(shop, "PHX-001"), "quantity": "60"}],
                payments=[{"method": "cash", "amount": "600.00"}])
    assert made.status_code == 201, made.text
    left = batch_on_hand(shop, "PHX-001")
    assert left["PARA-SOON"] == 0 and left["PARA-NEAR"] == 20 and left["PARA-LATE"] == 100      # earliest expiry first
    run(shop, "inventory.batch_expiring")
    warned = open_findings(shop, "inventory.batch_expiring")
    assert len(warned) == 1 and "PARA-NEAR" in warned[0]["summary"] and warned[0]["severity"] == "medium"   # 80 days: inside 90
    assert "PARA-LATE" not in warned[0]["summary"]


def test_the_home_box_lists_what_expires_soon(client, shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text("update inventory.batch set expiry_date = :d where batch_no = 'PARA-NEAR'"),
                  {"d": BASE + timedelta(days=10)})
    listed = client.get("/api/v1/inventory/expiring", params={"days": 90}, headers=shop["owner"]).json()
    near = next(r for r in listed if r["batch_no"] == "PARA-NEAR")
    assert near["days_left"] == 10 and Dec(near["quantity"]) == 20 and near["location_code"] == "MAIN"
    assert [r["batch_no"] for r in listed] == sorted(
        (r["batch_no"] for r in listed), key=lambda b: next(x["expiry_date"] for x in listed if x["batch_no"] == b))
    assert all(r["batch_no"] != "PARA-LATE" for r in listed)                                   # 400 days: outside
    assert client.get("/api/v1/inventory/expiring", headers=shop["cashier"]).status_code == 200  # stock.view
    assert client.get("/api/v1/inventory/expiring").status_code in (401, 403)


def test_expired_stock_still_on_the_shelf_is_reported_and_a_sale_from_it_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text("update inventory.batch set expiry_date = :d where batch_no = 'PARA-NEAR'"),
                  {"d": BASE - timedelta(days=2)})
    run(shop, "inventory.batch_expired")
    gone = open_findings(shop, "inventory.batch_expired")
    assert len(gone) == 1 and "PARA-NEAR" in gone[0]["summary"] and gone[0]["severity"] == "high"
    made = sell(client, shop, lines=[{"product_id": product(shop, "PHX-001"), "quantity": "5"}],
                payments=[{"method": "cash", "amount": "50.00"}])
    assert made.status_code == 201, made.text                                  # it happened, so it is accepted ...
    assert batch_on_hand(shop, "PHX-001")["PARA-NEAR"] == 15
    flagged = rows(shop, "select kind, severity, message from kernel.exception_item where kind = 'expired_stock_sold'")
    assert len(flagged) == 1 and flagged[0][1] == "high" and "PHX-001" in flagged[0][2]      # ... and flagged for a person


# --------------------------------------------------------------------------- the reference note at the till
def catalog(client, shop) -> dict[str, dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{POS}/catalog", headers=shop["cashier"], params={
        "branch_id": str(shop["branch_id"]), "location_id": shop["main"], "limit": 200})
    assert r.status_code == 200, r.text
    return {x["sku"]: x for x in r.json()}


def set_mode(client, shop, mode: str) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                     json={"sale_reference_prompt": mode})
    assert r.status_code == 200 and r.json()["sale_reference_prompt"] == mode, r.text


def test_the_till_asks_for_a_reference_only_when_the_business_says_so(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert catalog(client, shop)["PHX-024"]["reference_prompt"] == "off"       # off until the business chooses
    set_mode(client, shop, "ask")
    items = catalog(client, shop)
    assert items["PHX-024"]["reference_prompt"] == "ask" and items["PHX-001"]["reference_prompt"] == "off"
    set_mode(client, shop, "require")
    assert catalog(client, shop)["PHX-024"]["reference_prompt"] == "require"
    bad = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                       json={"sale_reference_prompt": "sometimes"})
    assert bad.status_code == 422
    set_mode(client, shop, "ask")


def test_a_reference_is_kept_on_the_sale_and_the_check_names_the_sales_without_one(client, shop) -> None:  # type: ignore[no-untyped-def]
    receive(client, shop, "PHX-024", [("DZP-1", "40", 300)])
    controlled = product(shop, "PHX-024")
    ok = sell(client, shop, lines=[{"product_id": controlled, "quantity": "2", "reference": "  SLIP-1042 "}],
              payments=[{"method": "cash", "amount": "20.00"}])
    assert ok.status_code == 201, ok.text
    assert ok.json()["lines"][0]["reference"] == "SLIP-1042"
    skipped = sell(client, shop, lines=[{"product_id": controlled, "quantity": "1"}],
                   payments=[{"method": "cash", "amount": "10.00"}])
    assert skipped.status_code == 201, skipped.text                           # "ask" lets the cashier skip
    plain = sell(client, shop, lines=[{"product_id": product(shop, "PHX-001"), "quantity": "1"}],
                 payments=[{"method": "cash", "amount": "10.00"}])
    assert plain.status_code == 201, plain.text
    run(shop, "pos.reference_missing")
    [finding] = open_findings(shop, "pos.reference_missing")
    assert skipped.json()["number"] in finding["summary"] and "needs a reference" in finding["summary"]
    assert ok.json()["number"] not in finding["summary"] and plain.json()["number"] not in finding["summary"]
    assert finding["severity"] == "medium"                                    # one sale: under the limit of 3
    assert rows(shop, "select count(*) from pos.sale_line where reference is not null") == [(1,)]
    # the check is silent once the business turns the prompt off
    set_mode(client, shop, "off")
    again = sell(client, shop, lines=[{"product_id": controlled, "quantity": "1"}],
                 payments=[{"method": "cash", "amount": "10.00"}])
    assert again.status_code == 201, again.text
    run(shop, "pos.reference_missing")
    assert len(open_findings(shop, "pos.reference_missing")) == 1             # the earlier one stays, nothing new


def test_the_check_has_plain_text_in_both_languages() -> None:
    from ziira.modules.intel.domain import plain

    for lang in plain.LANGS:
        p = plain.plain_check("pos.reference_missing", lang, fallback_title="x", area="controls",
                              params={"days": 7, "high_after": 3})
        assert p.title != "x" and p.why and p.todo and "{days}" in p.sentence


def test_the_templates_for_refill_reminders_exist_in_english_and_swahili() -> None:
    from ziira.kernel import templates

    for code in ("refill_reminder", "order_ready"):
        for lang in ("en", "sw"):
            subject, body = templates.render(code, lang, {"customer": "Amina", "business": "Green Pharmacy"})
            assert subject and "Amina" in body and "Green Pharmacy" in body
            assert ("STOP" if lang == "en" else "ACHA") in body                  # every message can be stopped

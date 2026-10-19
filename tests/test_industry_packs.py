"""Industry packs: the files are checked, switching a pack on seeds the units' own tables (idempotent, never
overwriting), what was seeded is logged so untouched items can be removed, packs show on the Add-ons catalogue, the
registration step picks one, and the kernel's industry socket and pack kit work."""

import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import editions, industry
from ziira.kernel.db import master_session
from ziira.kernel.manifest import load_manifest
from ziira.kernel.plugin_kit import check, scaffold
from ziira.kernel.registry import Registry, discover

PACK = "pack_demo_services"
REGISTER, VERIFY = "/api/v1/register", "/api/v1/register/verify"


def rows(tenant, sql: str, **params):  # type: ignore[no-untyped-def]
    with system(tenant) as s:
        return [tuple(r) for r in s.execute(text(sql), params)]


def services(tenant):  # type: ignore[no-untyped-def]
    return rows(tenant, "select sku, name, service_minutes, product_type, is_active from products.product "
                        "where sku like 'DEMO-%' order by sku")


# --------------------------------------------------------------------------- the files
def test_the_demo_pack_is_a_valid_industry_pack() -> None:
    units = discover()
    assert industry.is_industry(units[PACK]) and units[PACK].category == "industry"
    assert industry.check_pack(PACK) == []
    data = industry.load_pack(units[PACK])
    assert (data.units, data.editions) == (("products",), ("services",))
    assert data.unit_data("products")["service"][0]["sku"] == "DEMO-CONSULT"
    assert data.unit_data("nothing") == {}


def copy_pack(tmp_path: Path) -> Path:
    target = tmp_path / "pack_bad"
    shutil.copytree(discover()[PACK].path, target, ignore=shutil.ignore_patterns("__pycache__"))
    text_ = (target / "manifest.toml").read_text().replace("pack_demo_services", "pack_bad")
    (target / "manifest.toml").write_text(text_)
    return target


def problems(folder: Path) -> list[str]:
    units = discover()
    return industry.validate_pack(load_manifest(folder / "manifest.toml", "ziira_ext.pack_bad"), set(units),
                                  set(editions.load_editions()))


def test_a_pack_with_bad_files_is_reported_in_plain_words(tmp_path: Path) -> None:
    folder = copy_pack(tmp_path)
    assert problems(folder) == []
    (folder / "data" / "pack.toml").write_text('[pack]\nunits = ["products", "ghost"]\neditions = ["nowhere"]\n')
    (folder / "data" / "jobs.toml").write_text("x = 1\n")
    (folder / "data" / "products.toml").write_text("not = [valid")
    found = " | ".join(problems(folder))
    assert "'ghost', which is not a unit" in found and "'nowhere', which is not an edition" in found
    assert "jobs.toml feeds 'jobs'" in found and "products.toml is not valid TOML" in found
    (folder / "data" / "pack.toml").unlink()
    assert "pack.toml is missing" in problems(folder)[0]


def test_a_unit_listed_but_not_in_requires_or_optional_is_reported(tmp_path: Path) -> None:
    folder = copy_pack(tmp_path)
    (folder / "data" / "pack.toml").write_text('[pack]\nunits = ["products", "crm"]\n')
    assert any("'crm' is in [pack] units but not in the manifest" in p for p in problems(folder))


def test_the_pack_kit_writes_a_pack_that_passes_the_checks(tmp_path: Path) -> None:
    folder = scaffold.new_plugin("pack_kit_try", "industry", [], tmp_path)
    report = check.check_plugin(folder)
    assert report.ok, report.render()
    assert (folder / "data" / "products.toml").exists() and (folder / "data" / "pack.toml").exists()
    assert "category = \"industry\"" in (folder / "manifest.toml").read_text()


# --------------------------------------------------------------------------- seeding
@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_stock_shop(client, registry, "Industry Shop")


def test_switching_a_pack_on_seeds_services_and_fields_once(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    assert services(shop) == []
    registry.enable(shop["tenant_id"], PACK)
    assert services(shop) == [("DEMO-CONSULT", "Consultation", 30, "service", True),
                              ("DEMO-EXTENDED", "Extended service", 90, "service", True),
                              ("DEMO-STANDARD", "Standard service", 60, "service", True)]
    fields = rows(shop, "select key, kind, source, choices::text from kernel.custom_field_def where source like 'pack:%'")
    assert fields == [("skill_level", "choice", f"pack:{PACK}", '["Junior", "Senior", "Specialist"]')]
    log = rows(shop, "select seeder, item_type from kernel.pack_seed_log where pack = :p order by seeder, item_label",
               p=PACK)
    assert log.count(("products.services", "product")) == 3 and ("kernel.custom_fields", "custom_field_def") in log
    # again: nothing new, nothing duplicated
    assert industry.apply_to_tenant(Registry(), shop["tenant_id"]) == {}
    assert len(services(shop)) == 3
    assert rows(shop, "select count(*) from kernel.pack_seed_log")[0][0] == 4


def test_the_seeded_field_is_usable_on_a_product(client, shop) -> None:  # type: ignore[no-untyped-def]
    url = f"/api/v1/custom-fields/values/products.product/{shop['cement']}"
    assert client.put(url, headers=shop["owner"], json={"values": {"skill_level": "Senior"}}).status_code == 200
    assert client.put(url, headers=shop["owner"], json={"values": {"skill_level": "Wizard"}}).status_code == 422
    listed = client.get("/api/v1/custom-fields?entity_type=products.product", headers=shop["owner"]).json()
    assert [f["from_pack"] for f in listed if f["key"] == "skill_level"] == [True]


def test_service_minutes_show_on_the_product(client, shop) -> None:  # type: ignore[no-untyped-def]
    found = client.get("/api/v1/products/products?search=DEMO-CONSULT", headers=shop["owner"]).json()
    assert [(p["sku"], p["service_minutes"], p["product_type"]) for p in found] == [("DEMO-CONSULT", 30, "service")]


def test_seeding_never_overwrites_what_the_business_has(client, registry) -> None:  # type: ignore[no-untyped-def]
    mine = make_stock_shop(client, registry, "Industry Mine")
    created = client.post("/api/v1/products/products", headers=mine["owner"], json={
        "company_id": str(mine["company_id"]), "sku": "DEMO-STANDARD", "name": "My own haircut",
        "base_uom_id": mine["uom"], "tax_code_id": mine["tax"]})
    assert created.status_code == 201
    with system(mine) as s:
        s.execute(text("insert into kernel.custom_field_def (tenant_id, entity_type, key, label, kind, required) "
                       "values (kernel.current_tenant(), 'products.product', 'skill_level', 'My level', 'text', true)"))
    registry.enable(mine["tenant_id"], PACK)
    assert [r[:2] for r in services(mine)] == [("DEMO-CONSULT", "Consultation"), ("DEMO-EXTENDED", "Extended service"),
                                              ("DEMO-STANDARD", "My own haircut")]
    assert rows(mine, "select label, kind, required from kernel.custom_field_def where key = 'skill_level'") == [
        ("My level", "text", True)]
    logged = rows(mine, "select item_label from kernel.pack_seed_log where pack = :p and item_type = 'product'", p=PACK)
    assert sorted(r[0] for r in logged) == ["Consultation", "Extended service"]       # only what the pack added


def test_a_pack_switched_on_before_a_seeding_unit_seeds_when_it_arrives(client, registry) -> None:  # type: ignore[no-untyped-def]
    # The pack needs products, so the usual order is products first; a business that already has the pack but lost
    # nothing is covered by `apply-packs`. Here: remove a seeded service, run apply-packs, it comes back only once.
    again = make_stock_shop(client, registry, "Industry Again")
    registry.enable(again["tenant_id"], PACK)
    with system(again) as s:
        s.execute(text("delete from products.product where sku = 'DEMO-EXTENDED'"))
    from ziira.kernel import cli

    assert cli.main(["apply-packs", again["code"]]) == 0
    assert [r[0] for r in services(again)] == ["DEMO-CONSULT", "DEMO-EXTENDED", "DEMO-STANDARD"]


# --------------------------------------------------------------------------- switching off
def test_switching_off_keeps_data_and_untouched_items_can_be_removed(client, registry) -> None:  # type: ignore[no-untyped-def]
    t = make_stock_shop(client, registry, "Industry Off")
    registry.enable(t["tenant_id"], PACK)
    owner = t["owner"]
    assert client.post(f"/api/v1/units/{PACK}/disable", headers=owner).status_code == 200
    assert len(services(t)) == 3                                                          # data is kept
    seeded = client.get(f"/api/v1/industry/packs/{PACK}/seeded", headers=owner)
    assert seeded.status_code == 200 and len(seeded.json()) == 4
    assert all(r["untouched"] for r in seeded.json() if r["item_type"] == "product")
    # the business prices one service and uses a custom field: those are no longer untouched
    with system(t) as s:
        pid = s.execute(text("select id from products.product where sku = 'DEMO-STANDARD'")).scalar()
    lst = client.post("/api/v1/products/price-lists", headers=owner, json={
        "company_id": str(t["company_id"]), "name": "Main", "currency": "KES", "is_default": True})
    assert lst.status_code == 201, lst.text
    priced = client.put(f"/api/v1/products/price-lists/{lst.json()['id']}/prices", headers=owner, json={
        "product_id": str(pid), "uom_id": t["uom"], "price": "500", "valid_from": "2026-01-01"})
    assert priced.status_code in (200, 201), priced.text
    client.put(f"/api/v1/custom-fields/values/products.product/{t['cement']}", headers=owner,
               json={"values": {"skill_level": "Junior"}})
    after = {(r["item_type"], r["label"]): r["untouched"] for r in
             client.get(f"/api/v1/industry/packs/{PACK}/seeded", headers=owner).json()}
    assert after[("product", "Standard service")] is False and after[("product", "Consultation")] is True
    assert after[("custom_field_def", "products.product: Skill level needed")] is False
    removed = client.post(f"/api/v1/industry/packs/{PACK}/remove-untouched", headers=owner)
    assert removed.status_code == 200 and removed.json() == {"removed": 2}
    assert [(r[0], r[4]) for r in services(t)] == [("DEMO-CONSULT", False), ("DEMO-EXTENDED", False),
                                                  ("DEMO-STANDARD", True)]               # hidden, never deleted
    assert client.post("/api/v1/industry/packs/products/remove-untouched", headers=owner).status_code == 404
    assert client.get(f"/api/v1/industry/packs/{PACK}/seeded", headers=t["cashier"]).status_code == 403


# --------------------------------------------------------------------------- the Add-ons catalogue and registration
def test_the_catalogue_marks_industry_packs_and_their_editions(client, shop) -> None:  # type: ignore[no-untyped-def]
    cards = {c["name"]: c for c in client.get("/api/v1/units/catalog", headers=shop["owner"]).json()}
    assert (cards[PACK]["category"], cards[PACK]["editions"]) == ("industry", ["services"])
    assert cards["products"]["editions"] == []


def test_the_public_list_of_kinds_of_service_business(client) -> None:  # type: ignore[no-untyped-def]
    listed = client.get("/api/v1/industries")
    assert listed.status_code == 200
    mine = next(i for i in listed.json() if i["id"] == PACK)
    assert mine["title"] == "Demo services pack" and mine["summary"]
    assert PACK in [i["id"] for i in client.get("/api/v1/industries?edition=services").json()]
    assert PACK not in [i["id"] for i in client.get("/api/v1/industries?edition=retail").json()]


def register(client, **extra):  # type: ignore[no-untyped-def]
    with master_session() as s:
        s.execute(text("delete from master.registration"))
    body = {"business_name": f"Svc Co {uuid4().hex[:6]}", "owner_name": "Ada Owner",
            "email": f"o-{uuid4().hex[:8]}@svc.test", "password": "a-good-password-1", "currency": "usd",
            "phone_country_code": "44", **extra}
    return client.post(REGISTER, json=body), body


def test_registering_a_service_business_enables_the_chosen_pack(client, registry) -> None:  # type: ignore[no-untyped-def]
    asked, _ = register(client, edition="services", business_type=PACK)
    assert asked.status_code == 202, asked.text
    done = client.post(VERIFY, json={"token": asked.json()["dev_token"], "device_id": "dev-1"})
    assert done.status_code == 200, done.text
    tenant = {"tenant_id": done.json()["tenant_id"]}
    on = {r[0] for r in rows(tenant, "select unit_name from kernel.tenant_unit where status = 'enabled'")}
    assert PACK in on and "products" in on
    assert len(services(tenant)) == 3


def test_other_or_unknown_kinds_enable_no_pack(client, registry) -> None:  # type: ignore[no-untyped-def]
    asked, _ = register(client, edition="services", business_type="other")
    assert asked.status_code == 202
    done = client.post(VERIFY, json={"token": asked.json()["dev_token"], "device_id": "dev-1"})
    tenant = {"tenant_id": done.json()["tenant_id"]}
    assert PACK not in {r[0] for r in rows(tenant, "select unit_name from kernel.tenant_unit")}
    bad, _ = register(client, edition="services", business_type="pack_nonexistent")
    assert bad.status_code == 422


# --------------------------------------------------------------------------- editions
def test_the_services_edition_skips_units_that_do_not_exist_here() -> None:
    e = editions.get("services")
    assert e.landing == "/services/calendar" and e.menu_groups[0] == "services"
    assert [s.id for s in e.checklist] == ["services", "staff", "booking", "invoice"]


def test_every_industry_pack_names_real_editions() -> None:
    names = set(editions.load_editions())
    for m in industry.installed_packs(discover()):
        assert set(industry.load_pack(m).editions) <= names, m.name
        assert industry.check_pack(m.name) == [], m.name

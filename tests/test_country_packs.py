"""Country packs: the country list, picking a pack at registration, seeding a business's own tables from a pack
(idempotent, non-destructive), the international fallback, and the upgrade step that switches on a provider plugin."""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.people_helpers import make_people_shop
from tests.stock_helpers import system
from ziira.kernel import countries, packs
from ziira.kernel.db import master_session
from ziira.kernel.registry import Registry, discover

REGISTER, VERIFY = "/api/v1/register", "/api/v1/register/verify"


def one(tenant, sql: str, **params):  # type: ignore[no-untyped-def]
    with system({"tenant_id": tenant}) as s:
        return s.execute(text(sql), params).scalar()


def rows(tenant, sql: str, **params):  # type: ignore[no-untyped-def]
    with system({"tenant_id": tenant}) as s:
        return [tuple(r) for r in s.execute(text(sql), params)]


def register(client, **extra):  # type: ignore[no-untyped-def]
    with master_session() as s:
        s.execute(text("delete from master.registration"))
    body = {"business_name": f"Pack Co {uuid4().hex[:6]}", "owner_name": "Ada Owner",
            "email": f"o-{uuid4().hex[:8]}@pack.test", "password": "a-good-password-1", "currency": "usd",
            "phone_country_code": "44", "edition": "distribution", **extra}
    asked = client.post(REGISTER, json=body)
    assert asked.status_code == 202, asked.text
    done = client.post(VERIFY, json={"token": asked.json()["dev_token"], "device_id": "dev-1"})
    assert done.status_code == 200, done.text
    return done.json()["tenant_id"]


# --------------------------------------------------------------------------- the data files
def test_every_pack_is_well_formed() -> None:
    units = discover()
    packs_found = [m for m in units.values() if countries.is_pack(m)]
    assert {m.name for m in packs_found} >= {"pack_ke", "pack_international"}
    for m in packs_found:
        assert countries.check_pack_file(m) == [], m.name
        assert (m.path / "data").is_dir()


def test_the_country_list_has_every_country_and_packs_refine_theirs(client) -> None:  # type: ignore[no-untyped-def]
    listed = client.get("/api/v1/countries")
    assert listed.status_code == 200
    by_code = {c["code"]: c for c in listed.json()}
    assert len(by_code) > 150 and by_code["NZ"]["pack"] is None and by_code["NZ"]["calling"] == "64"
    ke = by_code["KE"]
    assert ke["pack"] == "pack_ke" and ke["pack_available"] is True
    assert (ke["currency"], ke["calling"], ke["zone"], ke["tax_id_label"]) == (
        "KES", "254", "Africa/Nairobi", "KRA PIN")
    assert [c["name"] for c in listed.json()] == sorted(c["name"] for c in listed.json())


def test_a_pack_is_chosen_by_country_with_the_international_pack_as_the_fallback() -> None:
    units = discover()
    assert countries.pack_for("ke", units).name == "pack_ke"                      # type: ignore[union-attr]
    assert countries.pack_for("NZ", units).name == "pack_international"           # type: ignore[union-attr]
    assert countries.pack_for(None, units).name == "pack_international"           # type: ignore[union-attr]
    assert countries.pack_for("KE", units, installed={"pack_international"}).name == "pack_international"  # type: ignore[union-attr]
    assert countries.pack_for("KE", units, installed=set()) is None


# --------------------------------------------------------------------------- registration
def test_registering_with_a_country_switches_on_its_pack_and_seeds_it(client, registry) -> None:  # type: ignore[no-untyped-def]
    tenant = register(client, country="ke", currency="kes", phone_country_code="254")
    units = {r[0] for r in rows(tenant, "select unit_name from kernel.tenant_unit where status = 'enabled'")}
    assert "pack_ke" in units and "pack_international" not in units
    codes = dict(rows(tenant, "select code, vat_rate::text from products.tax_code"))
    assert codes == {"VAT16": "16.00", "VAT8": "8.00", "ZERO": "0.00", "EXEMPT": "0.00", "NONVAT": "0.00"}
    assert one(tenant, "select authority_code from products.tax_code where code = 'VAT16'") == "B"


def test_an_unknown_country_still_registers_and_gets_the_international_pack(client, registry) -> None:  # type: ignore[no-untyped-def]
    for country in ("nz", None):
        extra = {"country": country} if country else {}
        tenant = register(client, **extra)
        units = {r[0] for r in rows(tenant, "select unit_name from kernel.tenant_unit where status = 'enabled'")}
        assert "pack_international" in units and "pack_ke" not in units
        assert {r[0] for r in rows(tenant, "select code from products.tax_code")} == {"NONE", "ZERO", "EXEMPT"}


# --------------------------------------------------------------------------- seeding
@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_people_shop(client, registry, "Pack Shop", finance=True)
    with system(s) as session:
        session.execute(text("update kernel.company set country = 'KE' where id = :c"), {"c": str(s["company_id"])})
    return s


def test_switching_a_pack_on_adds_what_is_missing_and_never_overwrites(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    tenant, company = shop["tenant_id"], shop["company_id"]
    # the business already has VAT16 (entered by hand, named "VAT") and its own PAYE table
    assert one(tenant, "select name from products.tax_code where code = 'VAT16'") == "VAT"
    own = {"name": "My income tax", "kind": "tax", "order": 30, "base": "taxable",
           "employee": {"method": "rate", "rate": "0.1"}}
    made = client.post("/api/v1/people/rules", headers=shop["finance"], json={
        "company_id": str(company), "code": "PAYE", "effective_from": "2020-01-01", "definition": own,
        "source_reference": "my own notice"})
    assert made.status_code == 201, made.text
    registry.enable(tenant, "pack_ke")

    names = dict(rows(tenant, "select code, name from products.tax_code"))
    assert names["VAT16"] == "VAT"                                           # untouched
    assert {"VAT8", "ZERO", "EXEMPT", "NONVAT"} <= set(names)                # added
    tables = {r[0]: r[1:] for r in rows(tenant, "select code, is_verified, effective_from::text, created_by is null "
                                                "from people.statutory_rate_table where company_id = :c", c=str(company))}
    assert set(tables) == {"PAYE", "NSSF", "SHIF", "AHL"}
    assert tables["PAYE"][1] == "2020-01-01" and tables["PAYE"][2] is False         # the business's own table, not ours
    assert all(tables[c][0] is False and tables[c][2] for c in ("NSSF", "SHIF", "AHL"))     # seeded: unverified, by system
    assert one(tenant, "select definition->>'name' from people.statutory_rate_table where code = 'PAYE'") == "My income tax"
    assert date.fromisoformat(tables["NSSF"][1])                                    # an effective date is always there


def test_a_new_companys_books_come_from_the_pack_template(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    tenant, company = shop["tenant_id"], shop["company_id"]
    registry.enable(tenant, "pack_ke")
    r = client.post(f"/api/v1/finance/companies/{company}/books", headers=shop["finance"])
    assert r.status_code in (200, 201), r.text
    accounts = {a[0]: a[1] for a in rows(tenant, "select code, name from finance.account where company_id = :c",
                                         c=str(company))}
    assert accounts["1030"] == "M-Pesa clearing" and accounts["2311"] == "PAYE payable"
    assert accounts["1010"] == "Till cash"                                          # the general chart is still there
    rules = rows(tenant, "select count(*) from finance.posting_rule where company_id = :c", c=str(company))[0][0]
    assert rules > 50


def test_seeding_twice_changes_nothing_and_respects_edits(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    tenant, company = shop["tenant_id"], shop["company_id"]
    registry.enable(tenant, "pack_ke")
    with system(shop) as s:
        s.execute(text("update finance.account set name = 'Our PAYE' where company_id = :c and code = '2311'"),
                  {"c": str(company)})
        s.execute(text("delete from products.tax_code where code = 'NONVAT'"))
    before = rows(tenant, "select code, name from finance.account where company_id = :c order by code", c=str(company))
    first = packs.apply_to_tenant(tenant)                                       # the tax code the business deleted returns
    second = packs.apply_to_tenant(tenant)
    assert second == {} or all(not v for v in second.values())                  # nothing more to add
    after = rows(tenant, "select code, name from finance.account where company_id = :c order by code", c=str(company))
    assert before == after and dict(after)["2311"] == "Our PAYE"                # the rename stands
    assert first                                                                # (only the deleted tax code came back)


def test_a_pack_for_another_country_adds_nothing_to_this_company(client, registry) -> None:  # type: ignore[no-untyped-def]
    s = make_people_shop(client, registry, "Pack Other", finance=True)
    with system(s) as session:
        session.execute(text("update kernel.company set country = 'NZ' where id = :c"), {"c": str(s["company_id"])})
    registry.enable(s["tenant_id"], "pack_international")
    registry.enable(s["tenant_id"], "pack_ke")                      # switched on, but the company is not in Kenya
    assert one(s["tenant_id"], "select count(*) from people.statutory_rate_table") == 0      # no payroll data invented
    assert {r[0] for r in rows(s["tenant_id"], "select code from products.tax_code")} == {
        "VAT16", "NONE", "ZERO", "EXEMPT"}                          # the shop's own, and the worldwide codes only


def test_a_unit_switched_on_later_is_seeded_from_the_pack_already_on(client, registry) -> None:  # type: ignore[no-untyped-def]
    from tests.stock_helpers import make_stock_shop

    s = make_stock_shop(client, registry, "Pack Late")
    with system(s) as session:
        session.execute(text("update kernel.company set country = 'KE' where id = :c"), {"c": str(s["company_id"])})
    registry.enable(s["tenant_id"], "pack_ke")
    assert one(s["tenant_id"], "select count(*) from products.tax_code") == 5          # products was on: seeded now
    registry.enable(s["tenant_id"], "people")                                           # people comes on afterwards
    assert one(s["tenant_id"], "select count(*) from people.statutory_rate_table") == 4


# --------------------------------------------------------------------------- the upgrade step for provider plugins
def test_a_business_using_a_provider_gets_its_plugin_switched_on_by_an_upgrade(client, registry) -> None:  # type: ignore[no-untyped-def]
    from tests.stock_helpers import make_stock_shop

    s = make_stock_shop(client, registry, "Upgrade Shop")
    tenant = s["tenant_id"]
    registry.enable(tenant, "payments")
    with system(s) as session:
        session.execute(text(
            "insert into payments.payment_account (tenant_id, company_id, kind, name, provider, shortcode, config) "
            "values (:t, :c, 'mobile_money', 'Old till', 'daraja', '600001', '{}')"),
            {"t": str(tenant), "c": str(s["company_id"])})
    assert "mpesa" not in registry.installed_in(tenant)
    registry.install("mpesa")                                                # `ziira install`: the upgrade runs
    with system(s) as session:
        enabled = {r[0] for r in session.execute(text("select unit_name from kernel.tenant_unit where status='enabled'"))}
    assert "mpesa" in enabled
    # a business with no such account is left alone
    other = make_stock_shop(client, registry, "Upgrade Other")
    registry.enable(other["tenant_id"], "payments")
    registry.install("mpesa")
    assert "mpesa" not in Registry().installed_in(other["tenant_id"])

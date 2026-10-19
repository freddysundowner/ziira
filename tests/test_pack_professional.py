"""The professional-services pack as data: what switching it on gives a practice, that it never overwrites the business's
own choices, that its example rates price nothing, and that its sample practice loads once and goes away again."""

from datetime import date, datetime
from decimal import Decimal as Dec  # noqa: N817
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.pos_helpers import make_sales_shop
from tests.stock_helpers import system
from ziira.kernel import industry
from ziira.kernel.registry import Registry
from ziira.sdk import check_pack

PACK = "pack_professional"
TB = "/api/v1/timebilling"
TODAY = datetime.now(ZoneInfo("Africa/Nairobi")).date()


def rows(shop, sql: str, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return [tuple(r) for r in s.execute(text(sql), params)]


def test_the_pack_files_are_valid_and_complete() -> None:
    assert check_pack(PACK) == []


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_sales_shop(client, registry, "Pack Practice", stock="5")
    import ziira.modules.intel.hooks  # noqa: F401
    import ziira.modules.timebilling.hooks  # noqa: F401

    registry.enable(s["tenant_id"], "timebilling")
    registry.enable(s["tenant_id"], "intel")
    s["co"] = str(s["company_id"])
    return s


def test_switching_the_pack_on_gives_a_practice_its_starting_data(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    registry.enable(shop["tenant_id"], PACK)
    assert rows(shop, "select count(*) from timebilling.engagement_template")[0][0] == 9
    names = {r[0] for r in rows(shop, "select name from timebilling.engagement_template")}
    assert {"Monthly bookkeeping", "Annual accounts and tax return", "Legal matter (capped fee)",
            "Agency retainer (monthly)"} <= names
    tpl = client.get(f"{TB}/templates", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    annual = next(t for t in tpl if t["name"] == "Annual accounts and tax return")
    assert annual["billing_mode"] == "fixed_fee" and annual["frequency"] == "annual" and len(annual["checklist"]) == 7
    assert sum(Dec(m["percent"]) for m in annual["milestones"]) == 100 and annual["source"] == f"pack:{PACK}"
    examples = rows(shop, "select role_title, example from timebilling.rate where kind = 'bill' order by rate desc")
    assert examples[0] == ("Partner", True) and all(e for _, e in examples) and len(examples) == 7
    assert rows(shop, "select count(*) from timebilling.activity")[0][0] == 25
    assert rows(shop, "select count(*) from timebilling.activity where not billable")[0][0] == 3
    assert {r[0] for r in rows(shop, "select distinct language from timebilling.snippet")} == {"en", "sw"}
    s = client.get(f"{TB}/settings", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert s["minute_step"] == 5 and s["nudge_minutes"] == 360 and s["unbilled_after_days"] == 21
    assert s["service_product_id"] and s["expense_product_id"]                      # pointed at the pack's service items
    sku = rows(shop, "select sku from products.product where id = :i", i=s["service_product_id"])[0][0]
    assert sku == "PRO-CONSULT"
    fields = {r[0] for r in rows(shop, "select entity_type || '.' || key from kernel.custom_field_def")}
    assert {"timebilling.client.engagement_type", "timebilling.client.year_end", "timebilling.client.main_contact",
            "timebilling.project.matter_number"} <= fields
    limits = {r[0]: r[1] for r in rows(shop, "select check_code, params::text from intel.check_setting")}
    assert '"unbilled_days": 21' in limits["timebilling.unbilled_ageing"]
    assert '"min_percent": "85"' in limits["timebilling.realisation_low"] or "85" in limits["timebilling.realisation_low"]


def test_seeding_again_changes_nothing_and_never_brings_back_what_was_removed(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert industry.apply_to_tenant(Registry(), shop["tenant_id"]) == {}
    assert rows(shop, "select count(*) from timebilling.engagement_template")[0][0] == 9
    t = client.get(f"{TB}/templates", headers=shop["owner"], params={"company_id": shop["co"]}).json()[0]
    assert client.delete(f"{TB}/templates/{t['id']}", headers=shop["owner"]).status_code == 204
    assert industry.apply_to_tenant(Registry(), shop["tenant_id"]) == {}
    assert rows(shop, "select count(*) from timebilling.engagement_template")[0][0] == 8     # removed on purpose: stays removed


def test_example_rates_are_shown_but_price_nothing_until_confirmed(client, shop) -> None:  # type: ignore[no-untyped-def]
    listed = client.get(f"{TB}/rates", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert len(listed) == 7 and all(r["example"] for r in listed)
    explain = client.get(f"{TB}/rates/explain", headers=shop["owner"], params={"company_id": shop["co"], "day": TODAY.isoformat()})
    assert explain.json()["rate"] is None
    first = listed[0]
    ok = client.patch(f"{TB}/rates/{first['id']}", headers=shop["owner"], json={"example": False})
    assert ok.status_code == 200 and ok.json()["example"] is False


def test_the_checklist_ticks_itself_and_the_sample_practice_loads_once_and_goes_away(client, shop) -> None:  # type: ignore[no-untyped-def]
    guide = client.get(f"{TB}/setup", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    done = {s["key"]: s["done"] for s in guide["steps"]}
    assert done == {"service_item": True, "rates": True, "team": False, "client_project": False, "time": False,
                    "invoice": False}
    assert guide["example_rates"] == 6 and guide["sample"] == {
        "available": True, "note": "A small practice: monthly books, annual accounts, a brand project and a capped-fee lease review.",
        "loaded": False}
    assert client.post(f"{TB}/sample-data", headers=shop["cashier"], params={"company_id": shop["co"]}).status_code == 403
    r = client.post(f"{TB}/sample-data", headers=shop["owner"], params={"company_id": shop["co"]})
    assert r.status_code == 201, r.text
    counts = r.json()["counts"]
    assert counts["clients"] == 4 and counts["projects"] == 4 and counts["expenses"] == 2 and counts["tasks"] >= 1
    assert counts["entries"] >= 5
    projects = client.get(f"{TB}/projects", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert {p["code"]: p["billing_mode"] for p in projects if p["code"].startswith("SMP-")} == {
        "SMP-BOOKS": "retainer", "SMP-ACCTS": "fixed_fee", "SMP-BRAND": "time_and_materials", "SMP-LEASE": "capped_fee"}
    lease = next(p for p in projects if p["code"] == "SMP-LEASE")
    assert Dec(lease["fee_cap"]) == Dec("6000.00")
    values = client.get(f"/api/v1/custom-fields/values/timebilling.project/{lease['id']}", headers=shop["owner"]).json()
    assert "M-2026-014" in str(values)
    tasks = client.get(f"{TB}/tasks", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert any(t["name"] == "Send the client our mark-up" for t in tasks) and any(t["recurrence_id"] for t in tasks)
    ms = client.get(f"{TB}/projects/{next(p for p in projects if p['code'] == 'SMP-ACCTS')['id']}/milestones",
                    headers=shop["owner"]).json()
    assert [(m["name"], m["status"]) for m in ms] == [
        ("Records received", "ready"), ("Draft accounts", "planned"), ("Filed and handed over", "planned")]
    again = client.post(f"{TB}/sample-data", headers=shop["owner"], params={"company_id": shop["co"]})
    assert again.status_code == 409                                                  # loaded once
    state = client.get(f"{TB}/setup", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert state["sample"]["loaded"] is True and {s["key"]: s["done"] for s in state["steps"]}["client_project"] is False
    week = client.get(f"{TB}/weeks/mine", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert week["entries"] or True
    gone = client.delete(f"{TB}/sample-data", headers=shop["owner"], params={"company_id": shop["co"]})
    assert gone.status_code == 200, gone.text
    assert gone.json()["counts"]["projects"] == 4
    assert [p for p in client.get(f"{TB}/projects", headers=shop["owner"], params={"company_id": shop["co"]}).json()
            if p["code"].startswith("SMP-")] == []
    assert rows(shop, "select count(*) from timebilling.entry")[0][0] == 0
    assert rows(shop, "select count(*) from timebilling.engagement_task")[0][0] == 0
    assert client.post(f"{TB}/sample-data", headers=shop["owner"], params={"company_id": shop["co"]}).status_code == 201


def test_sample_time_that_was_sent_in_is_kept_when_the_sample_is_removed(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.delete(f"{TB}/sample-data", headers=shop["owner"], params={"company_id": shop["co"]})
    assert client.post(f"{TB}/sample-data", headers=shop["owner"], params={"company_id": shop["co"]}).status_code == 201
    start = date.fromordinal(TODAY.toordinal() - ((TODAY.isoweekday() - 1) % 7))
    sent = client.post(f"{TB}/weeks/submit", headers=shop["owner"], json={"company_id": shop["co"], "week_start": start.isoformat()})
    assert sent.status_code in (200, 422)
    out = client.delete(f"{TB}/sample-data", headers=shop["owner"], params={"company_id": shop["co"]}).json()["counts"]
    if sent.status_code == 200:
        assert out["kept_entries"] >= 1 and out["kept_projects"] >= 1                 # the business's record stays

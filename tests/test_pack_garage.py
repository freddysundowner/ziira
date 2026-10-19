"""The garage pack: what switching it on sets up (stages, checklists, standard times, categories, photos, job types, bays,
steps, Intelligence limits), that it is idempotent and never overwrites, the first-run steps tick themselves, and the
sample week (with an insurer claim) loads and is taken away again."""

import pytest
from sqlalchemy import text

from tests.claims_helpers import make_claims_shop
from tests.jobs_helpers import JOBS
from tests.stock_helpers import system
from ziira.kernel import industry
from ziira.kernel.registry import Registry

PACK = "pack_garage"


def rows(tenant, sql: str, **params):  # type: ignore[no-untyped-def]
    with system(tenant) as s:
        return [tuple(r) for r in s.execute(text(sql), params)]


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    made = make_claims_shop(client, registry, "Pack Garage")
    registry.enable(made["tenant_id"], PACK)
    return made


def test_the_pack_files_are_valid() -> None:
    assert industry.check_pack(PACK) == []


def test_switching_it_on_sets_up_a_workshop(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    stages = {s["code"] for s in client.get(f"{JOBS}/workflow", headers=shop["owner"], params={"company_id": co}).json()}
    assert {"received", "waiting_for_insurer", "waiting_for_customer", "quality_check", "ready"} <= stages
    templates = {t["name"] for t in client.get(f"{JOBS}/checklist-templates", headers=shop["owner"],
                                              params={"company_id": co}).json()}
    assert {"Vehicle intake", "Insurer job", "Garment intake"} <= templates
    tasks = client.get(f"{JOBS}/labour-tasks", headers=shop["owner"], params={"company_id": co}).json()
    assert len(tasks) >= 20 and all(t["is_example"] for t in tasks)
    assert next(t for t in tasks if t["code"] == "brake-pads-front")["standard_hours"] == "1.50"
    types = client.get(f"{JOBS}/work-types", headers=shop["owner"], params={"company_id": co}).json()
    assert [t["code"] for t in types][:4] == ["mechanical", "body", "paint", "electrical"]
    assert all(t["hourly_rate"] is None for t in types)                       # no rate is invented
    categories = {c["code"]: c for c in client.get(f"{JOBS}/part-categories", headers=shop["owner"],
                                                  params={"company_id": co}).json()}
    assert categories["tyres"]["markup_percent"] in ("20", "20.00") and categories["used-parts"]["default_class"] == "used"
    kinds = client.get(f"{JOBS}/job-types", headers=shop["owner"], params={"company_id": co}).json()
    body = next(k for k in kinds if k["code"] == "body-repair")
    assert body["required_photos"][0] == {"category": "damage", "min": 2, "before": "quoted"}
    assert body["checklist_template_id"] is not None
    assert {p["code"] for p in client.get(f"{JOBS}/photo-categories", headers=shop["owner"],
                                         params={"company_id": co}).json()} >= {"damage", "odometer", "after"}
    assert len(client.get(f"{JOBS}/bays", headers=shop["owner"], params={"company_id": co}).json()) == 3
    settings = client.get(f"{JOBS}/settings", headers=shop["owner"], params={"company_id": co}).json()
    assert settings["release_unpaid"] == "warn" and settings["default_warranty_days"] == 30
    assert settings["labour_product_name"] == "Workshop labour" or settings["labour_product_id"] is not None
    fields = {r[0] for r in rows(shop, "select key from kernel.custom_field_def where source = 'pack:pack_garage'")}
    assert {"make", "vin", "imei", "m_chest"} <= fields


def test_it_is_idempotent_and_leaves_what_the_business_changed(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    task = next(t for t in client.get(f"{JOBS}/labour-tasks", headers=shop["owner"], params={"company_id": co}).json()
                if t["code"] == "oil-change")
    client.patch(f"{JOBS}/labour-tasks/{task['id']}", headers=shop["owner"], json={"standard_hours": "0.7"})
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
        "default_warranty_days": 90})
    before = rows(shop, "select count(*) from jobs.labour_task")[0][0]
    industry.apply_to_tenant(Registry(), shop["tenant_id"])
    assert rows(shop, "select count(*) from jobs.labour_task")[0][0] == before
    mine = client.get(f"{JOBS}/labour-tasks", headers=shop["owner"], params={"company_id": co}).json()
    changed = next(t for t in mine if t["code"] == "oil-change")
    assert changed["standard_hours"] == "0.70" and changed["is_example"] is False
    assert client.get(f"{JOBS}/settings", headers=shop["owner"], params={"company_id": co}).json()[
        "default_warranty_days"] == 90


def test_the_first_run_steps_tick_themselves(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    steps = client.get(f"{JOBS}/pack-steps", headers=shop["owner"], params={"company_id": co}).json()
    assert [s["step_id"] for s in steps][:2] == ["items", "rates"] and len(steps) == 7
    done = {s["step_id"]: s["done"] for s in steps}
    assert done["items"] is True and done["rates"] is False and done["job"] is False     # the items were linked by SKU
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
        "default_labour_rate": "100"})
    again = {s["step_id"]: s["done"] for s in client.get(f"{JOBS}/pack-steps", headers=shop["owner"],
                                                        params={"company_id": co}).json()}
    assert again["rates"] is True
    manual = next(s for s in steps if s["step_id"] == "insurers")
    assert client.post(f"{JOBS}/pack-steps/{manual['id']}/done", headers=shop["owner"]).status_code == 204
    assert client.post(f"{JOBS}/pack-steps/hide", headers=shop["rep"], params={"company_id": co}).status_code == 403


def test_the_sample_week_loads_with_an_insurer_claim_and_is_taken_away(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    status = client.get(f"{JOBS}/sample-data", headers=shop["owner"], params={"company_id": co}).json()
    assert status["available"] is True and status["loaded"] is False
    assert client.post(f"{JOBS}/sample-data", headers=shop["rep"], params={"company_id": co}).status_code == 403
    loaded = client.post(f"{JOBS}/sample-data", headers=shop["owner"], params={"company_id": co})
    assert loaded.status_code == 201, loaded.text
    assert loaded.json()["counts"]["jobs"] == 6 and loaded.json()["counts"]["claims"] == 1
    assert client.post(f"{JOBS}/sample-data", headers=shop["owner"], params={"company_id": co}).status_code == 409
    listed = client.get(f"{JOBS}/jobs", headers=shop["owner"], params={"limit": 50}).json()
    stages = {j["title"]: j["status"]["code"] for j in listed}
    assert stages["Full service"] == "ready" and stages["Clutch slipping"] == "waiting_for_parts"
    assert stages["Collision damage, front bumper and headlamp"] == "waiting_for_insurer"
    parts_wait = client.get(f"{JOBS}/jobs", headers=shop["owner"], params={"waiting_on": "parts"}).json()
    assert [j["title"] for j in parts_wait] == ["Clutch slipping"]
    insurer = next(j for j in listed if j["has_claim"])
    detail = client.get(f"{JOBS}/jobs/{insurer['id']}", headers=shop["owner"]).json()
    assert detail["claim"]["status"] == "draft" and detail["claim"]["excess"] == "5000.00"
    # the first steps know sample jobs do not count
    done = {s["step_id"]: s["done"] for s in client.get(f"{JOBS}/pack-steps", headers=shop["owner"],
                                                        params={"company_id": co}).json()}
    assert done["job"] is False
    gone = client.delete(f"{JOBS}/sample-data", headers=shop["owner"], params={"company_id": co})
    assert gone.status_code == 200, gone.text
    assert gone.json()["counts"]["jobs"] == 6 and gone.json()["counts"]["claims"] == 1
    assert client.get(f"{JOBS}/jobs", headers=shop["owner"], params={"limit": 50}).json() == []
    assert rows(shop, "select count(*) from jobs.asset")[0][0] == 0
    assert client.get(f"{JOBS}/sample-data", headers=shop["owner"], params={"company_id": co}).json()["loaded"] is False

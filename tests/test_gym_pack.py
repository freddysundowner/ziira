"""The fitness pack: valid files, the starting plans, packs and policies, example prices that are marked and cleared, nothing
overwritten, the pack switched off."""

import pytest
from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import cli, industry
from ziira.kernel.registry import discover

PACK = "pack_fitness"
M = "/api/v1/memberships"


def rows(tenant, sql: str, **params):  # type: ignore[no-untyped-def]
    with system(tenant) as s:
        return [tuple(r) for r in s.execute(text(sql), params)]


@pytest.fixture(scope="module")
def gym(client, registry):  # type: ignore[no-untyped-def]
    t = make_stock_shop(client, registry, "Pack Gym")
    registry.enable(t["tenant_id"], "crm")
    registry.enable(t["tenant_id"], "memberships")
    registry.enable(t["tenant_id"], PACK)
    return t


def test_the_pack_files_are_valid() -> None:
    assert industry.check_pack(PACK) == []
    data = industry.load_pack(discover()[PACK])
    assert set(data.units) == {"products", "memberships", "intel"} and data.editions == ("services",)


def test_it_sets_up_plans_packs_policies_terms_and_services(client, gym) -> None:  # type: ignore[no-untyped-def]
    plans = client.get(f"{M}/plans", headers=gym["owner"]).json()
    by_code = {p["code"]: p for p in plans}
    assert {"MONTHLY", "CONTRACT12", "ANNUAL", "OFFPEAK", "CLASSESONLY", "DAYPASS", "WEEKPASS", "TRIAL"} <= set(by_code)
    assert all(p["is_example"] for p in plans if p["code"] in by_code)
    assert by_code["MONTHLY"]["service_product_id"] and by_code["MONTHLY"]["joining_fee"] == "20.00"
    assert by_code["CONTRACT12"]["kind"] == "fixed_term" and by_code["CONTRACT12"]["term_periods"] == 12
    assert by_code["OFFPEAK"]["access_rules"][0]["from"] == "10:00" and by_code["OFFPEAK"]["classes_mode"] == "none"
    assert by_code["TRIAL"]["is_trial"] and by_code["TRIAL"]["valid_days"] == 3
    assert by_code["CLASSESONLY"]["gym_access"] is False
    packages = {p["code"]: p for p in client.get(f"{M}/packages", headers=gym["owner"]).json()}
    assert {"VISITS10", "CLASSES10", "PT5", "PT10"} <= set(packages) and packages["VISITS10"]["covered_services"] == ["gym"]
    assert packages["PT5"]["product_id"]
    settings = client.get(f"{M}/settings", headers=gym["owner"], params={"company_id": str(gym["company_id"])}).json()
    assert settings["waiver_required"] is True and settings["inactive_weeks"] == 3 and settings["dunning_days"] == "1,7,14"
    terms = client.get(f"{M}/waiver/versions", headers=gym["owner"], params={"company_id": str(gym["company_id"])}).json()
    assert len(terms) == 1 and "placeholder" in terms[0]["body"]
    assert rows(gym, "select count(*) from products.product where sku like 'GYM-%'")[0][0] == 8
    fields = rows(gym, "select entity_type, key from kernel.custom_field_def where entity_type like 'memberships.%' "
                       "order by key")
    assert ("memberships.profile", "goal") in fields and ("memberships.member", "preferred_trainer") in fields


def test_running_it_again_changes_nothing_and_never_overwrites(client, gym) -> None:  # type: ignore[no-untyped-def]
    plans = {p["code"]: p for p in client.get(f"{M}/plans", headers=gym["owner"]).json()}
    edited = client.patch(f"{M}/plans/{plans['MONTHLY']['id']}", headers=gym["owner"], json={"fee": "45.00"}).json()
    assert edited["is_example"] is False                                          # the owner made the price their own
    client.patch(f"{M}/plans/{plans['DAYPASS']['id']}", headers=gym["owner"], json={"status": "retired"})
    assert cli.main(["apply-packs", gym["code"]]) == 0
    after = {p["code"]: p for p in client.get(f"{M}/plans", headers=gym["owner"]).json()}
    assert len(after) == len(plans) and after["MONTHLY"]["fee"] == "45.00" and after["DAYPASS"]["status"] == "retired"
    assert rows(gym, "select count(*) from memberships.waiver_version")[0][0] == 1


def test_a_pack_plan_nobody_used_can_be_removed_but_a_used_one_stays(client, gym) -> None:  # type: ignore[no-untyped-def]
    owner = gym["owner"]
    seeded = client.get(f"/api/v1/industry/packs/{PACK}/seeded", headers=owner).json()
    kinds = {r["item_type"] for r in seeded}
    assert {"plan", "package", "setting", "waiver_version", "product", "custom_field_def"} <= kinds
    states = {r["label"]: r["untouched"] for r in seeded if r["item_type"] == "plan"}
    assert states["Monthly"] is False and states["Annual (paid once a year)"] is True      # edited vs not
    removed = client.post(f"/api/v1/industry/packs/{PACK}/remove-untouched", headers=owner)
    assert removed.status_code == 200 and removed.json()["removed"] >= 5
    plans = {p["code"]: p for p in client.get(f"{M}/plans", headers=owner).json()}
    assert plans["ANNUAL"]["status"] == "retired" and plans["MONTHLY"]["status"] == "active"


def test_the_first_run_checklist_follows_what_exists(client, registry) -> None:  # type: ignore[no-untyped-def]
    t = make_stock_shop(client, registry, "Pack Gym Steps")
    registry.enable(t["tenant_id"], "crm")
    registry.enable(t["tenant_id"], "memberships")
    co = str(t["company_id"])
    empty = {s["id"]: s["done"] for s in client.get(f"{M}/setup-steps", headers=t["owner"], params={"company_id": co}).json()}
    assert empty == {"plans": False, "services": False, "terms": False, "policies": False, "members": False,
                     "checkin": False}
    registry.enable(t["tenant_id"], PACK)
    steps = {s["id"]: s["done"] for s in client.get(f"{M}/setup-steps", headers=t["owner"], params={"company_id": co}).json()}
    assert steps["plans"] is False and steps["services"] is True and steps["terms"] is True and steps["policies"] is True
    for plan in client.get(f"{M}/plans", headers=t["owner"]).json():
        client.patch(f"{M}/plans/{plan['id']}", headers=t["owner"], json={"is_example": False})
    steps = {s["id"]: s["done"] for s in client.get(f"{M}/setup-steps", headers=t["owner"], params={"company_id": co}).json()}
    assert steps["plans"] is True and steps["members"] is False

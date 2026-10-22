"""The education pack as data: what switching it on gives a school or tutoring centre, that nothing is overwritten, that fees
reach the parent while the learner stays the learner, reports are attached with a visibility flag, and that the three checks
a school needs work end to end with the real engine."""

from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from tests.bookings_helpers import B, when, workday
from tests.files_helpers import pdf
from tests.gym_helpers import age_invoice, refresh
from tests.memberships_helpers import M, customer, make_member_shop, rows
from tests.stock_helpers import system
from ziira.kernel import cli, industry
from ziira.kernel.registry import discover
from ziira.modules.intel.services import engine
from ziira.sdk import check_pack, files

PACK = "pack_education"
INTEL = "/api/v1/intel"


def test_the_pack_files_are_valid() -> None:
    assert check_pack(PACK) == []
    data = industry.load_pack(discover()[PACK])
    assert set(data.units) == {"products", "memberships", "bookings", "intel"} and data.editions == ("services",)


@pytest.fixture(scope="module")
def school(client, registry):  # type: ignore[no-untyped-def]
    s = make_member_shop(client, registry, "Pack School")
    client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"], json={"timezone": "UTC"})
    for unit in ("bookings", "intel", PACK):
        registry.enable(s["tenant_id"], unit)
    s["co"] = str(s["company_id"])
    return s


def finding_rows(client, shop, code: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params={"check_code": code, "limit": 100})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- what it sets up
def test_it_sets_up_fee_plans_bundles_policies_terms_and_service_items(client, school) -> None:  # type: ignore[no-untyped-def]
    plans = {p["code"]: p for p in client.get(f"{M}/plans", headers=school["owner"]).json()}
    assert {"TERM", "TERM3", "TERM2", "TERM-SIB", "TERM3-SIB", "MONTHLY"} <= set(plans)
    assert all(plans[c]["is_example"] for c in ("TERM", "TERM3", "TERM-SIB"))
    assert plans["TERM3"]["kind"] == "fixed_term" and plans["TERM3"]["term_periods"] == 3
    assert plans["TERM"]["billing_interval"] == "quarter" and plans["TERM3"]["billing_interval"] == "month"
    assert plans["TERM3"]["service_product_id"]
    assert plans["MONTHLY"]["kind"] == "recurring"
    packages = {p["code"] for p in client.get(f"{M}/packages", headers=school["owner"]).json()}
    assert {"LESSONS5", "LESSONS10", "REVISION8"} <= packages
    settings = client.get(f"{M}/settings", headers=school["owner"], params={"company_id": school["co"]}).json()
    assert settings["waiver_required"] is False and settings["dunning_days"] == "7,14,30" and settings["inactive_weeks"] == 0
    terms = client.get(f"{M}/waiver/versions", headers=school["owner"], params={"company_id": school["co"]}).json()
    assert len(terms) == 1 and "placeholder" in terms[0]["body"]
    assert rows(school, "select count(*) from products.product where sku like 'EDU-%'")[0][0] == 14


def test_it_sets_up_classes_with_capacity_teachers_and_rooms(client, school) -> None:  # type: ignore[no-untyped-def]
    offers = {o["name"]: o for o in client.get(f"{B}/offers", headers=school["owner"], params={"company_id": school["co"]}).json()}
    assert len(offers) == 10
    maths = offers["Mathematics class"]
    assert maths["kind"] == "class" and maths["capacity"] == 12 and maths["resource_mode"] == "all"
    assert maths["price_is_example"] is True and maths["product_id"] and len(maths["resource_ids"]) == 2
    assert offers["Make-up session"]["capacity"] == 6 and offers["One-to-one lesson"]["kind"] == "appointment"
    resources = client.get(f"{B}/resources", headers=school["owner"]).json()
    assert [r["name"] for r in resources] == ["Teacher 1", "Teacher 2", "Classroom 1", "Classroom 2"]
    steps = client.get(f"{B}/pack-steps", headers=school["owner"], params={"company_id": school["co"]}).json()
    assert [s["step_id"] for s in steps] == ["prices", "staff", "link", "timetable", "attendance", "page"]
    assert next(s for s in steps if s["step_id"] == "link")["done"] is True
    assert not any(s["done"] for s in steps if s["step_id"] in ("prices", "timetable", "attendance"))


def test_learner_fields_exist_and_hold_no_health_data(school) -> None:  # type: ignore[no-untyped-def]
    found = rows(school, "select entity_type, key from kernel.custom_field_def where source = :s order by key",
                 s=f"pack:{PACK}")
    keys = {k for _, k in found}
    assert {"grade", "guardian_name", "guardian_phone", "guardian_relation", "collected_by", "class_group",
            "main_tutor"} <= keys
    assert not any(h in k for k in keys for h in ("health", "allerg", "medic", "diagnos", "disab"))


def test_check_limits_are_set_for_the_school_checks(school) -> None:  # type: ignore[no-untyped-def]
    limits = {r[0] for r in rows(school, "select check_code from intel.check_setting")}
    assert {"bookings.class_underfilled", "bookings.class_absences", "memberships.term_ending_unpaid",
            "memberships.payment_late"} <= limits


def test_running_it_again_changes_nothing_and_never_overwrites(client, school) -> None:  # type: ignore[no-untyped-def]
    plans = {p["code"]: p for p in client.get(f"{M}/plans", headers=school["owner"]).json()}
    edited = client.patch(f"{M}/plans/{plans['TERM']['id']}", headers=school["owner"], json={"fee": "450.00"}).json()
    assert edited["is_example"] is False
    client.patch(f"{M}/plans/{plans['TERM2']['id']}", headers=school["owner"], json={"status": "retired"})
    offers = client.get(f"{B}/offers", headers=school["owner"], params={"company_id": school["co"]}).json()
    before = {k: len(v) for k, v in {"offers": offers, "plans": plans}.items()}
    steps = len(client.get(f"{B}/pack-steps", headers=school["owner"], params={"company_id": school["co"]}).json())
    assert cli.main(["apply-packs", school["code"]]) == 0
    assert cli.main(["apply-packs", school["code"]]) == 0
    after = {p["code"]: p for p in client.get(f"{M}/plans", headers=school["owner"]).json()}
    assert len(after) == before["plans"] and after["TERM"]["fee"] == "450.00" and after["TERM2"]["status"] == "retired"
    assert len(client.get(f"{B}/offers", headers=school["owner"], params={"company_id": school["co"]}).json()) == before["offers"]
    assert len(client.get(f"{B}/pack-steps", headers=school["owner"], params={"company_id": school["co"]}).json()) == steps
    assert rows(school, "select count(*) from memberships.waiver_version")[0][0] == 1
    assert rows(school, "select count(*) from kernel.custom_field_def where source = :s", s=f"pack:{PACK}")[0][0] == 9


def test_switching_it_off_removes_only_what_nobody_changed_or_used(client, school) -> None:  # type: ignore[no-untyped-def]
    seeded = client.get(f"/api/v1/industry/packs/{PACK}/seeded", headers=school["owner"]).json()
    kinds = {r["item_type"] for r in seeded}
    assert {"plan", "package", "service_offer", "resource", "pack_step", "product"} <= kinds
    states = {r["label"]: r["untouched"] for r in seeded if r["item_type"] == "plan"}
    assert states["Term fees (paid once)"] is False and states["Term fees (3 monthly instalments)"] is True


# --------------------------------------------------------------------------- fees to the parent, reports to the file
def test_a_term_is_billed_to_the_parent_in_instalments_and_the_learner_stays_the_learner(client, school) -> None:  # type: ignore[no-untyped-def]
    parent = customer(client, school, "Mrs Wanjiru Parent")
    learner = customer(client, school, "Amina Learner")
    group = client.post(f"{M}/groups", headers=school["owner"], json={
        "company_id": school["co"], "name": "The Wanjirus", "kind": "household", "payer_customer_id": parent["id"]})
    assert group.status_code == 201, group.text
    assert client.put(f"{M}/profiles/by-customer/{learner['id']}/group", headers=school["owner"],
                      json={"group_id": group.json()["id"]}).status_code == 200
    plan = next(p for p in client.get(f"{M}/plans", headers=school["owner"]).json() if p["code"] == "TERM3")
    start = date(2026, 9, 1)
    r = client.post(f"{M}/members", headers=school["owner"], json={
        "plan_id": plan["id"], "customer_id": learner["id"], "branch_id": str(school["branch_id"]),
        "start_date": start.isoformat(), "end_date": date(2026, 11, 30).isoformat()})
    assert r.status_code == 201, r.text
    member = r.json()
    assert member["customer_id"] == learner["id"] and member["billing_customer_id"] == parent["id"]
    runs = client.get(f"{M}/invoice-runs", headers=school["owner"], params={"owner_id": member["id"]}).json()
    assert len(runs) == 1 and runs[0]["customer_id"] == parent["id"] and runs[0]["status"] == "issued"
    # the learner's profile carries the school fields; a report is attached and stays staff-only until it is shared
    profile = client.get(f"{M}/profiles/by-customer/{learner['id']}", headers=school["owner"]).json()
    with system(school) as s:
        made = files.attach(s, entity_type="memberships.profile", entity_id=profile["id"], data=pdf("Term 1 report"),
                            name="term-1-report.pdf", category="report", caption="Term 1 report")
        assert made.visibility == "staff"
        shared = files.update_file(s, made.id, visibility="shareable")
        assert shared.visibility == "shareable" and shared.category == "report"
        listed = files.list_files(s, "memberships.profile", profile["id"], category="report")
        assert [f.name for f in listed] == ["term-1-report.pdf"]
    school.update({"parent": parent, "learner": learner, "member": member})


def test_a_sibling_has_their_own_cheaper_plan_on_the_same_parent(client, school) -> None:  # type: ignore[no-untyped-def]
    sibling = customer(client, school, "Brian Learner")
    group = client.get(f"{M}/groups", headers=school["owner"], params={"company_id": school["co"]}).json()[0]
    client.put(f"{M}/profiles/by-customer/{sibling['id']}/group", headers=school["owner"], json={"group_id": group["id"]})
    plan = next(p for p in client.get(f"{M}/plans", headers=school["owner"]).json() if p["code"] == "TERM3-SIB")
    r = client.post(f"{M}/members", headers=school["owner"], json={
        "plan_id": plan["id"], "customer_id": sibling["id"], "branch_id": str(school["branch_id"]),
        "start_date": "2026-09-01", "end_date": "2026-11-30"})
    assert r.status_code == 201, r.text
    assert r.json()["billing_customer_id"] == school["parent"]["id"] and r.json()["price"] == "94.00"


def test_a_recurring_invoice_can_name_the_learner_it_is_for(client, school) -> None:  # type: ignore[no-untyped-def]
    other_parent = customer(client, school, "Mr Otieno Parent")
    kid = customer(client, school, "Carol Learner")
    r = client.post(f"{M}/recurring-invoices", headers=school["owner"], json={
        "company_id": school["co"], "branch_id": str(school["branch_id"]), "customer_id": other_parent["id"],
        "name": "Term 2 fees", "lines": [{"product_id": str(school["delivery"]), "quantity": "1", "unit_price": "110.00"}],
        "billing_interval": "month", "start_date": "2026-09-01", "max_runs": 3, "for_customer_id": kid["id"],
        "for_label": "Carol, Term 2"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["customer_id"] == other_parent["id"] and body["for_customer_id"] == kid["id"]
    assert client.get(f"{M}/arrears", headers=school["owner"], params={"company_id": school["co"]}).status_code == 200


# --------------------------------------------------------------------------- the checks, with the real engine
def make_class(client, shop, name: str, day: int, hour: int = 16, **extra: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    offer = next(o for o in client.get(f"{B}/offers", headers=shop["owner"], params={"company_id": shop["co"]}).json()
                 if o["name"] == name)
    r = client.post(f"{B}/sessions", headers=shop["owner"], json={"offer_id": offer["id"], "starts_at": when(day, hour), **extra})
    assert r.status_code == 201, r.text
    return r.json()["created"][0]


def learners(client, shop, n: int) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return [customer(client, shop, f"Learner {i} {shop['code']}") for i in range(n)]


def test_a_class_with_few_places_taken_is_flagged_and_a_full_one_is_not(client, school) -> None:  # type: ignore[no-untyped-def]
    pupils = learners(client, school, 9)
    quiet = make_class(client, school, "Mathematics class", 40)
    busy = make_class(client, school, "English class", 40, 17)
    for p in pupils[:2]:
        assert client.post(f"{B}/sessions/{quiet['id']}/book", headers=school["owner"], json={"customer_id": p["id"]}).status_code in (200, 201)
    for p in pupils[:9]:
        assert client.post(f"{B}/sessions/{busy['id']}/book", headers=school["owner"], json={"customer_id": p["id"]}).status_code in (200, 201)
    day = workday(40)
    with system(school) as s:
        result = engine.run_company(s, school["company_id"], today=day, only={"bookings.class_underfilled"})
    assert result.created == 1
    found = finding_rows(client, school, "bookings.class_underfilled")
    assert len(found) == 1 and "Mathematics class" in found[0]["summary"] and "2 of 12" in found[0]["summary"]
    for p in pupils[2:9]:                                   # the class fills up: the finding goes away by itself
        client.post(f"{B}/sessions/{quiet['id']}/book", headers=school["owner"], json={"customer_id": p["id"]})
    with system(school) as s:
        engine.run_company(s, school["company_id"], today=day, only={"bookings.class_underfilled"})
    assert finding_rows(client, school, "bookings.class_underfilled") == []


def test_a_learner_often_absent_is_flagged_and_one_who_came_is_not(client, school) -> None:  # type: ignore[no-untyped-def]
    away, present = learners(client, school, 2)
    sessions = [make_class(client, school, "Science class", 50 + i) for i in range(4)]
    for i, sess in enumerate(sessions):
        a = client.post(f"{B}/sessions/{sess['id']}/book", headers=school["owner"], json={"customer_id": away["id"]}).json()
        p = client.post(f"{B}/sessions/{sess['id']}/book", headers=school["owner"], json={"customer_id": present["id"]}).json()
        with system(school) as s:                            # marked in the tables: these classes have not happened yet
            s.execute(text("update bookings.appointment_attendee set status = :st where id = :i"),
                      {"st": "no_show" if i < 3 else "attended", "i": a["attendee_id"]})
            s.execute(text("update bookings.appointment_attendee set status = 'attended' where id = :i"), {"i": p["attendee_id"]})
    day = workday(54)
    with system(school) as s:
        result = engine.run_company(s, school["company_id"], today=day, only={"bookings.class_absences"})
    assert result.created == 1
    found = finding_rows(client, school, "bookings.class_absences")
    assert len(found) == 1 and away["name"] in found[0]["summary"] and "3 sessions" in found[0]["summary"]
    assert present["name"] not in found[0]["summary"]


def test_a_term_ending_with_fees_unpaid_is_flagged_and_goes_away_when_paid(client, school) -> None:  # type: ignore[no-untyped-def]
    member = school["member"]
    # the term of the first learner ends on 30 Nov 2026 and its first invoice is open
    with system(school) as s:
        s.execute(text("update memberships.invoice_run set outstanding = total, settle_state = 'open' where owner_id = :o"),
                  {"o": member["id"]})
    with system(school) as s:
        far = engine.run_company(s, school["company_id"], today=date(2026, 10, 1), only={"memberships.term_ending_unpaid"})
    assert far.created == 0                                  # the term ends in two months: silent
    with system(school) as s:
        near = engine.run_company(s, school["company_id"], today=date(2026, 11, 20), only={"memberships.term_ending_unpaid"})
    assert near.created >= 1
    found = finding_rows(client, school, "memberships.term_ending_unpaid")
    assert found and "still owe" in found[0]["summary"]
    with system(school) as s:                                # everything is paid
        s.execute(text("update memberships.invoice_run set outstanding = 0, settle_state = 'paid'"))   # the sibling's term ends too
    with system(school) as s:
        engine.run_company(s, school["company_id"], today=date(2026, 11, 20), only={"memberships.term_ending_unpaid"})
    assert finding_rows(client, school, "memberships.term_ending_unpaid") == []        # paid: it resolves by itself


def test_fees_overdue_use_the_existing_payment_late_check_with_the_school_limits(client, school) -> None:  # type: ignore[no-untyped-def]
    payer = customer(client, school, "Late Payer Parent")
    kid = customer(client, school, "Late Learner")
    group = client.post(f"{M}/groups", headers=school["owner"], json={
        "company_id": school["co"], "name": "Late family", "kind": "household", "payer_customer_id": payer["id"]}).json()
    client.put(f"{M}/profiles/by-customer/{kid['id']}/group", headers=school["owner"], json={"group_id": group["id"]})
    plan = next(p for p in client.get(f"{M}/plans", headers=school["owner"]).json() if p["code"] == "MONTHLY")
    m = client.post(f"{M}/members", headers=school["owner"], json={
        "plan_id": plan["id"], "customer_id": kid["id"], "branch_id": str(school["branch_id"]),
        "start_date": (date.today() - timedelta(days=1)).isoformat()}).json()
    run = client.get(f"{M}/invoice-runs", headers=school["owner"], params={"owner_id": m["id"]}).json()[0]
    age_invoice(school, run["invoice_number"], 12)
    refresh(school)
    with system(school) as s:
        result = engine.run_company(s, school["company_id"], today=date.today(), only={"memberships.payment_late"})
    assert result.created == 1

"""Gyms and studios, part 4: classes (credits used on attendance), trainers, lockers, guests, measurements, retention
messages, the owner's reports, the households' personal data."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D  # noqa: N817
from uuid import UUID, uuid4

import pytest

from tests.gym_helpers import M, customer, gym_plan, make_gym_shop, rows, scalar, today
from tests.stock_helpers import system
from ziira.modules.memberships.services import dues, notify, retention
from ziira.sdk import Event, publish


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_gym_shop(client, registry, "Gym Extras Co")
    s["classes"] = client.post(f"{M}/packages", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "code": "CLASS10", "name": "10 classes", "credits": "10", "price": "200.00",
        "expiry_days": 90, "covered_services": ["class", "yoga"], "product_id": s["delivery"]}).json()
    return s


def send_event(shop, name: str, payload: dict) -> None:  # type: ignore[type-arg]
    payload = {k: (UUID(v) if k in ("customer_id", "attendee_id") and isinstance(v, str) else v)
               for k, v in payload.items()}
    with system(shop) as s:
        publish(s, Event(name, "bookings.appointment", uuid4(), {
            "company_id": shop["company_id"], "branch_id": shop["branch_id"], **payload}))


def pack_balance(client, shop, sold_id: str) -> D:  # type: ignore[no-untyped-def]
    return D(client.get(f"{M}/sold-packages/{sold_id}", headers=shop["owner"]).json()["balance"])


# --------------------------------------------------------------------------- classes
def test_a_class_pack_is_used_on_attendance_once_and_given_back_when_undone(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Class Cleo")
    sp = client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["classes"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    attendee = uuid4()
    for _ in range(2):                                                          # a repeated event spends once
        send_event(shop, "class.attendee_attended", {"customer_id": cust["id"], "attendee_id": attendee})
    assert pack_balance(client, shop, sp["id"]) == 9
    send_event(shop, "class.attendee_reset", {"customer_id": cust["id"], "attendee_id": attendee})
    assert pack_balance(client, shop, sp["id"]) == 10
    send_event(shop, "class.attendee_attended", {"customer_id": cust["id"], "attendee_id": attendee})
    assert pack_balance(client, shop, sp["id"]) == 9                           # may spend again after a release


def test_a_late_cancellation_costs_the_credit_and_a_called_off_class_gives_it_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Late Lola")
    sp = client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["classes"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    early, late = uuid4(), uuid4()
    send_event(shop, "class.attendee_cancelled", {"customer_id": cust["id"], "attendee_id": early, "late": False})
    assert pack_balance(client, shop, sp["id"]) == 10
    send_event(shop, "class.attendee_cancelled", {"customer_id": cust["id"], "attendee_id": late, "late": True})
    assert pack_balance(client, shop, sp["id"]) == 9
    send_event(shop, "class.attendee_cancelled", {"customer_id": cust["id"], "attendee_id": late, "late": False,
                                                  "session_cancelled": True})
    assert pack_balance(client, shop, sp["id"]) == 10
    co = str(shop["company_id"])
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
        "late_cancel_consumes": False, "no_show_consumes": False})
    send_event(shop, "class.attendee_cancelled", {"customer_id": cust["id"], "attendee_id": uuid4(), "late": True})
    send_event(shop, "class.attendee_no_show", {"customer_id": cust["id"], "attendee_id": uuid4()})
    assert pack_balance(client, shop, sp["id"]) == 10                        # the business chose not to charge
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
        "late_cancel_consumes": True, "no_show_consumes": True})
    send_event(shop, "class.attendee_no_show", {"customer_id": cust["id"], "attendee_id": uuid4()})
    assert pack_balance(client, shop, sp["id"]) == 9


def test_a_plan_that_includes_classes_spends_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    included = gym_plan(client, shop, "ALLCLASSES", name="Classes included", classes_mode="included")
    cust = customer(client, shop, "Included Ivy")
    client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": included["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])})
    sp = client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["classes"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    send_event(shop, "class.attendee_attended", {"customer_id": cust["id"], "attendee_id": uuid4()})
    assert pack_balance(client, shop, sp["id"]) == 10
    credits_plan = gym_plan(client, shop, "CLASSCREDITS", name="Classes cost credits", classes_mode="credits",
                            credits_per_period="4", covered_services=["class"])
    cust2 = customer(client, shop, "Credit Cy")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": credits_plan["id"], "customer_id": cust2["id"], "branch_id": str(shop["branch_id"])}).json()
    send_event(shop, "class.attendee_attended", {"customer_id": cust2["id"], "attendee_id": uuid4()})
    assert D(client.get(f"{M}/members/{m['id']}", headers=shop["owner"]).json()["balance"]) == 3


# --------------------------------------------------------------------------- trainers
def test_a_trainer_earns_per_session_with_a_fixed_or_percent_rate(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    coach, other = str(uuid4()), str(uuid4())
    base = {"company_id": co, "trainer_ref": coach, "trainer_name": "Coach Kim"}
    assert client.put(f"{M}/trainers/rates", headers=shop["rep"], json={**base, "basis": "fixed", "amount": "20"}
                      ).status_code == 403
    assert client.put(f"{M}/trainers/rates", headers=shop["fm"], json={**base, "basis": "percent", "amount": "150"}
                      ).status_code == 422
    assert client.put(f"{M}/trainers/rates", headers=shop["fm"], json={**base, "basis": "percent", "amount": "40"}
                      ).status_code == 200
    assert client.put(f"{M}/trainers/rates", headers=shop["fm"], json={
        **base, "service_ref": "pt-pro", "basis": "fixed", "amount": "25.00"}).status_code == 200
    cust = customer(client, shop, "Trained Tim")
    done = uuid4()
    for ref in ("pt", "pt-pro"):
        with system(shop) as s:
            publish(s, Event("appointment.completed", "bookings.appointment", done if ref == "pt" else uuid4(), {
                "company_id": shop["company_id"], "branch_id": shop["branch_id"], "resource_ids": [UUID(coach), UUID(other)],
                "customer_id": UUID(cust["id"]), "service": ref, "product_id": None,
                "lines": [{"unit_price": "100.00", "quantity": "1"}]}))
    with system(shop) as s:                                                       # the same session twice: once
        publish(s, Event("appointment.completed", "bookings.appointment", done, {
            "company_id": shop["company_id"], "branch_id": shop["branch_id"], "resource_ids": [UUID(coach)],
            "service": "pt", "lines": [{"unit_price": "100.00", "quantity": "1"}]}))
    earned = rows(shop, "select amount, basis, service_ref from memberships.trainer_earning where trainer_ref = :t "
                        "order by amount", t=coach)
    assert [(x.amount, x.basis) for x in earned] == [(D("25.00"), "fixed"), (D("40.00"), "percent")]      # not the other resource
    table = client.get(f"{M}/trainers/earnings", headers=shop["fm"], params={"company_id": co}).json()
    mine = next(x for x in table if x["trainer_ref"] == coach)
    assert mine["sessions"] == 2 and D(mine["earned"]) == D("65.00")
    assert client.get(f"{M}/trainers/earnings", headers=shop["cashier"], params={"company_id": co}).status_code == 403
    paid = client.post(f"{M}/trainers/{coach}/mark-paid", headers=shop["fm"], params={"company_id": co},
                       json={"through": today().isoformat()})
    assert paid.json()["rows"] == 2
    rows_ = client.get(f"{M}/trainers/{coach}/earnings", headers=shop["fm"], params={"company_id": co}).json()
    assert {r["status"] for r in rows_} == {"paid"}


def test_a_member_shares_measurements_and_may_have_them_removed(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Measure Mia")
    url = f"{M}/customers/{cust['id']}/measurements"
    for day, kg in ((10, "74.5"), (3, "76.0")):
        r = client.post(url, headers=shop["rep"], json={"metric": " Weight ", "value": kg, "unit": "kg",
                                                         "taken_on": (today() - timedelta(days=day)).isoformat()})
        assert r.status_code == 201 and r.json()["metric"] == "weight"
    got = client.get(url, headers=shop["cashier"], params={"metric": "WEIGHT"}).json()
    assert [x["value"] for x in got] == ["76.000", "74.500"] or [D(x["value"]) for x in got] == [D("76"), D("74.5")]
    assert client.post(url, headers=shop["cashier"], json={"metric": "waist", "value": "80"}).status_code == 403
    assert client.delete(f"{M}/measurements/{got[0]['id']}", headers=shop["rep"]).status_code == 204
    assert len(client.get(url, headers=shop["rep"]).json()) == 1


# --------------------------------------------------------------------------- lockers and guests
def test_a_locker_is_rented_with_a_deposit_and_a_recurring_fee(client, shop) -> None:  # type: ignore[no-untyped-def]
    co, branch = str(shop["company_id"]), str(shop["branch_id"])
    made = client.post(f"{M}/lockers", headers=shop["rep"], json={
        "company_id": co, "branch_id": branch, "codes": ["L1", "L2", "L2", "L3"], "fee": "10.00", "deposit": "20.00",
        "product_id": shop["delivery"]})
    assert made.status_code == 201 and [x["code"] for x in made.json()] == ["L1", "L2", "L3"]
    assert client.post(f"{M}/lockers", headers=shop["rep"], json={
        "company_id": co, "branch_id": branch, "codes": ["L1"]}).status_code == 409
    cust = customer(client, shop, "Locker Lou")
    lid = made.json()[0]["id"]
    r = client.post(f"{M}/lockers/{lid}/assign", headers=shop["rep"], json={"customer_id": cust["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "assigned" and r.json()["schedule_id"] and r.json()["deposit_run_id"]
    deposit = client.get(f"{M}/invoice-runs/{r.json()['deposit_run_id']}", headers=shop["owner"]).json()
    assert D(deposit["total"]) == D("20.00") and deposit["for_label"] == "locker L1"
    sched = client.get(f"{M}/recurring-invoices/{r.json()['schedule_id']}", headers=shop["owner"]).json()
    assert sched["customer_id"] == cust["id"] and D(sched["total"]) == D("10.00") and sched["for_customer_id"] == cust["id"]
    assert client.post(f"{M}/lockers/{lid}/assign", headers=shop["rep"], json={"customer_id": cust["id"]}).status_code == 409
    back = client.post(f"{M}/lockers/{lid}/release", headers=shop["rep"])
    assert back.json()["status"] == "free"
    assert client.get(f"{M}/recurring-invoices/{r.json()['schedule_id']}", headers=shop["owner"]).json()["status"] == "ended"
    free = client.get(f"{M}/lockers", headers=shop["rep"], params={"company_id": co, "status": "free"}).json()
    assert {x["code"] for x in free} >= {"L1", "L2", "L3"}


def test_guest_passes_are_counted_per_period(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "GUESTY", name="With guests", guest_passes_per_period=2)
    cust = customer(client, shop, "Host Hugh")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    assert client.get(f"{M}/members/{m['id']}/guest-passes", headers=shop["rep"]).json() == {"left": 2}
    g = client.post(f"{M}/members/{m['id']}/guests", headers=shop["rep"], json={"guest_name": "Friend Fay"})
    assert g.status_code == 201
    client.post(f"{M}/members/{m['id']}/guests", headers=shop["rep"], json={"guest_name": "Friend Fred"})
    assert client.get(f"{M}/members/{m['id']}/guest-passes", headers=shop["rep"]).json() == {"left": 0}
    assert client.post(f"{M}/members/{m['id']}/guests", headers=shop["rep"], json={"guest_name": "Third"}).status_code == 422
    assert len(client.get(f"{M}/members/{m['id']}/guests", headers=shop["rep"]).json()) == 2


# --------------------------------------------------------------------------- retention
def test_inactive_members_birthdays_and_trials_are_messaged_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"phone_country_code": "254"})
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
        "inactive_weeks": 3, "birthday_messages": True})
    gone = customer(client, shop, "Gone Gail", phone="0744000111")
    client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": gone["id"], "branch_id": str(shop["branch_id"]),
        "start_date": (today() - timedelta(days=60)).isoformat()})
    born = customer(client, shop, "Born Bea", phone="0744000222")
    client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": born["id"], "branch_id": str(shop["branch_id"])})
    client.patch(f"{M}/profiles/by-customer/{born['id']}", headers=shop["rep"], json={
        "date_of_birth": f"1990-{today().month:02d}-{today().day:02d}"})
    at = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC).replace(hour=12)
    original = notify.route
    notify.route = lambda session, company_id, c: [("sms", c.phone)] if c.phone else []   # type: ignore[assignment]
    try:
        with system(shop) as s:
            first = retention.send_due(s, UUID(co), at)
            second = retention.send_due(s, UUID(co), at)
    finally:
        notify.route = original                                                        # type: ignore[assignment]
    assert first["inactive"] >= 1 and first["birthday"] >= 1 and second == {"inactive": 0, "birthday": 0, "trial": 0}
    kinds = {r.template for r in rows(shop, "select template from kernel.notification where ref_type = "
                                            "'memberships.profile'")}
    assert {"membership_inactive", "membership_birthday"} <= kinds
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
        "inactive_weeks": 0, "birthday_messages": False})


# --------------------------------------------------------------------------- reports
def test_the_owner_report_reads_the_records(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    r = client.get(f"{M}/reports/overview", headers=shop["owner"], params={"company_id": co})
    assert r.status_code == 200, r.text
    rep = r.json()
    active = scalar(shop, "select count(*) from memberships.member where status = 'active'")
    assert rep["members"]["active"] == active and D(rep["mrr"]) > 0
    assert sum(p["members"] for p in rep["by_plan"]) == active
    assert D(rep["mrr"]) == sum(D(p["mrr"]) for p in rep["by_plan"])
    assert rep["flow"] and rep["retention"] is not None and isinstance(rep["attendance"], list)
    assert set(rep["arrears"]) == {"owed", "people", "d7", "d30", "d60", "d60plus"}
    assert client.get(f"{M}/reports/overview", headers=shop["cashier"], params={"company_id": co}).status_code == 403
    assert client.get(f"{M}/reports/overview", headers=shop["manager"], params={"company_id": co}).status_code == 200
    bad = client.get(f"{M}/reports/overview", headers=shop["owner"], params={
        "company_id": co, "start": "2026-10-10", "end": "2026-10-01"})
    assert bad.status_code == 422
    export = client.get(f"{M}/exports/members", headers=shop["owner"], params={"company_id": co})
    assert export.status_code == 200 and export.text.startswith("Member number,Membership,Name")
    assert client.get(f"{M}/exports/nothing", headers=shop["owner"], params={"company_id": co}).status_code == 404
    assert rows(shop, "select 1 from kernel.audit_log where entity_type = 'memberships.report' and action = 'export'")


def test_attendance_is_counted_by_hour_and_weekday(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    cust = customer(client, shop, "Peak Pat")
    client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])})
    client.post(f"{M}/checkin", headers=shop["desk"], json={
        "company_id": co, "branch_id": str(shop["branch_id"]), "customer_id": cust["id"]})
    rep = client.get(f"{M}/reports/overview", headers=shop["owner"], params={"company_id": co}).json()
    assert rep["visits"] >= 1 and sum(a["visits"] for a in rep["attendance"]) >= 1
    assert all(0 <= a["hour"] <= 23 and 0 <= a["weekday"] <= 6 for a in rep["attendance"])


def test_money_owed_is_aged_in_the_report(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    with system(shop) as s:
        dues.refresh_runs(s, UUID(co))
    rep = client.get(f"{M}/reports/overview", headers=shop["owner"], params={"company_id": co}).json()
    a = rep["arrears"]
    assert D(a["owed"]) == D(a["d7"]) + D(a["d30"]) + D(a["d60"]) + D(a["d60plus"])


# --------------------------------------------------------------------------- personal data
def test_a_members_details_are_found_exported_and_erased(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.memberships.privacy import MembershipsPersonalData
    from ziira.sdk import Subject

    cust = customer(client, shop, "Privacy Pru")
    client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])})
    client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={
        "emergency_name": "Zuberi Kamau", "emergency_phone": "0722111999", "card_number": "PRIV-1"})
    client.post(f"{M}/customers/{cust['id']}/measurements", headers=shop["rep"], json={"metric": "weight", "value": "70"})
    provider, company = MembershipsPersonalData(), UUID(str(shop["company_id"]))
    with system(shop) as s:
        found = provider.find(s, company, Subject(raw="Zuberi Kamau", name="Zuberi Kamau"))
        assert [f.kind for f in found] == ["profile"]
        exported = provider.export(s, found[0])
        assert exported["profile"]["emergency_name"] == "Zuberi Kamau" and len(exported["measurements"]) == 1
        outcome = provider.anonymise(s, found[0], "requested")
        assert outcome.status == "anonymised" and outcome.kept
    p = client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"]).json()
    assert p["emergency_name"] is None and p["card_number"] is None
    assert client.get(f"{M}/customers/{cust['id']}/measurements", headers=shop["rep"]).json() == []
    assert p["number"]                                                                # the member number stays

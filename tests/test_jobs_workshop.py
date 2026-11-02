"""The garage's floor and till: mechanic clocks, the vehicle health check, deposits set against the invoice, storage that
ran after the invoice, reading a VIN, and a job made from a booked appointment."""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817

import pytest
from sqlalchemy import text

from tests.bookings_helpers import B, book, make_salon
from tests.jobs_helpers import JOBS, make_jobs_shop, move, new_job
from tests.stock_helpers import system
from ziira.modules.jobs.domain import vin as vin_domain


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_jobs_shop(client, registry, "Garage Workshop Floor")


def post(client, shop, path, body=None, who="owner", expect=(200, 201)):  # type: ignore[no-untyped-def]
    r = client.post(f"{JOBS}{path}", headers=shop[who], json=body or {})
    assert r.status_code in expect, r.text
    return r


def get_job(client, shop, job, who="owner"):  # type: ignore[no-untyped-def]
    r = client.get(f"{JOBS}/jobs/{job['id']}", headers=shop[who])
    assert r.status_code == 200, r.text
    return r.json()


def owed_on(shop, invoice_number: str) -> Dec:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        from ziira.modules.pos.public import invoice_balance

        inv = s.execute(text("select id from pos.sales_invoice where number = :n"), {"n": invoice_number}).scalar_one()
        return invoice_balance(s, inv) or Dec(0)


# --------------------------------------------------------------------------- mechanic clocks
def test_a_clock_puts_the_time_worked_on_the_job_as_labour(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Clutch replacement")
    other = new_job(client, shop, title="Second car")
    started = post(client, shop, f"/jobs/{job['id']}/timer/start", {"note": "Take the gearbox out"}).json()
    assert [t["mine"] for t in started["timers"]] == [True]
    mine = client.get(f"{JOBS}/me/timer", headers=shop["owner"]).json()
    assert mine["job_number"] == job["number"] and mine["timer"]["note"] == "Take the gearbox out"
    # one clock at a time, but asking again for the same job is harmless
    refused = post(client, shop, f"/jobs/{other['id']}/timer/start", expect=(409,))
    assert job["number"] in refused.text
    assert len(post(client, shop, f"/jobs/{job['id']}/timer/start").json()["timers"]) == 1
    with system(shop) as s:
        s.execute(text("update jobs.job_timer set started_at = now() - interval '90 minutes' where job_id = :j"),
                  {"j": job["id"]})
    done = post(client, shop, f"/jobs/{job['id']}/timer/stop", {}).json()
    line = done["labour"][0]
    assert line["source"] == "timer" and Dec(line["hours"]) == Dec("1.5") and Dec(line["booked_hours"]) == Dec("1.5")
    assert line["description"] == "Take the gearbox out" and done["timers"] == []
    assert Dec(line["total"]) == Dec("150.00")
    assert client.get(f"{JOBS}/me/timer", headers=shop["owner"]).json()["timer"] is None
    post(client, shop, f"/jobs/{job['id']}/timer/stop", {}, expect=(404,))               # no clock running


def test_a_clock_can_be_thrown_away_and_a_forgotten_one_is_not_billed(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Forgot to stop")
    post(client, shop, f"/jobs/{job['id']}/timer/start")
    post(client, shop, f"/jobs/{job['id']}/timer/stop", {"discard": True})
    assert get_job(client, shop, job)["labour"] == []
    post(client, shop, f"/jobs/{job['id']}/timer/start")
    with system(shop) as s:
        s.execute(text("update jobs.job_timer set started_at = now() - interval '3 days' where job_id = :j "
                       "and stopped_at is null"), {"j": job["id"]})
    refused = post(client, shop, f"/jobs/{job['id']}/timer/stop", {}, expect=(422,))
    assert "discard" in refused.text
    post(client, shop, f"/jobs/{job['id']}/timer/stop", {"discard": True})


# --------------------------------------------------------------------------- the vehicle health check
def test_the_health_check_starts_from_a_usual_list_and_the_customer_sees_what_needs_attention(  # type: ignore[no-untyped-def]
        client, shop) -> None:
    job = new_job(client, shop, title="Full service")
    empty = client.get(f"{JOBS}/jobs/{job['id']}/inspection", headers=shop["owner"]).json()
    assert empty["started"] is False and empty["items"] == []
    begun = post(client, shop, f"/jobs/{job['id']}/inspection/start").json()
    assert begun["started"] and len(begun["items"]) >= 25 and begun["pending"] == len(begun["items"])
    assert post(client, shop, f"/jobs/{job['id']}/inspection/start").json()["pending"] == begun["pending"]     # not twice
    first, second, third = begun["items"][:3]

    def mark(item, **body):  # type: ignore[no-untyped-def]
        r = client.patch(f"{JOBS}/jobs/{job['id']}/inspection/items/{item['id']}", headers=shop["owner"], json=body)
        assert r.status_code == 200, r.text
        return r.json()

    mark(first, rating="red", note="Pads worn to the metal")
    mark(second, rating="amber", note="About 3 mm left")
    after = mark(third, rating="green")
    assert (after["red"], after["amber"], after["green"]) == (1, 1, 1)
    assert client.patch(f"{JOBS}/jobs/{job['id']}/inspection/items/{third['id']}", headers=shop["owner"],
                        json={"rating": "purple"}).status_code == 422
    extra = post(client, shop, f"/jobs/{job['id']}/inspection/items", {"section": "Brakes", "label": "Brake hose"}).json()
    assert extra["items"][-1]["label"] == "Brake hose"
    assert get_job(client, shop, job)["inspection_counts"]["red"] == 1
    removed = client.delete(f"{JOBS}/jobs/{job['id']}/inspection/items/{extra['items'][-1]['id']}",
                            headers=shop["owner"])
    assert removed.status_code == 200 and len(removed.json()["items"]) == len(begun["items"])
    # the customer's page shows only the amber and red lines, worst first, with the notes
    est = client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["owner"], json={"lines": [
        {"kind": "labour", "description": "Brake pads", "quantity": "1"}]}).json()
    token = post(client, shop, f"/estimates/{est['id']}/send").json()["link_path"].removeprefix("/job-approval/")
    page = client.get(f"{JOBS}/public/job-approval/{token}").json()
    assert [(c["rating"], c["note"]) for c in page["health_check"]] == [("red", "Pads worn to the metal"),
                                                                       ("amber", "About 3 mm left")]


# --------------------------------------------------------------------------- deposits and storage on the invoice
def test_a_deposit_is_set_against_the_invoice(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Deposit job")
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "2"})                    # 200.00
    post(client, shop, f"/jobs/{job['id']}/deposit", {"amount": "80", "method": "cash"})
    done = post(client, shop, f"/jobs/{job['id']}/invoice").json()
    assert done["deposit_applied"] == "80.00"
    assert owed_on(shop, done["invoice_number"]) == Dec("120.00")
    assert any("set against invoice" in (e["note"] or "") for e in done["events"])


def test_a_deposit_and_a_payment_together_settle_the_invoice(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Deposit and cash")
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})                    # 100.00
    post(client, shop, f"/jobs/{job['id']}/deposit", {"amount": "30", "method": "cash"})
    done = post(client, shop, f"/jobs/{job['id']}/invoice", {"pay_method": "cash"}).json()
    assert done["deposit_applied"] == "30.00" and owed_on(shop, done["invoice_number"]) == 0


def test_a_deposit_larger_than_the_invoice_leaves_the_rest_on_account(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Big deposit")
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})                    # 100.00
    post(client, shop, f"/jobs/{job['id']}/deposit", {"amount": "250", "method": "cash"})
    done = post(client, shop, f"/jobs/{job['id']}/invoice").json()
    assert done["deposit_applied"] == "100.00" and owed_on(shop, done["invoice_number"]) == 0


def test_storage_that_ran_after_the_invoice_is_billed_when_the_car_is_collected(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
        "storage_fee_per_day": "50", "storage_grace_days": 3})
    try:
        job = new_job(client, shop, title="Invoiced and left behind")
        post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
        for code in ("in_progress", "ready"):
            assert move(client, shop, job, code).status_code == 200
        invoiced = post(client, shop, f"/jobs/{job['id']}/invoice").json()                  # no storage owed yet
        assert invoiced["charges"] == [] and invoiced["storage_invoice_number"] is None
        with system(shop) as s:
            s.execute(text("update jobs.job set ready_at = now() - interval '10 days' where id = :i"), {"i": job["id"]})
        collected = post(client, shop, f"/jobs/{job['id']}/collect", {"collected_by_name": "Wanjiku"}).json()
        number = collected["storage_invoice_number"]
        assert number and number != invoiced["invoice_number"]
        assert owed_on(shop, number) == Dec("350.00")                                       # 7 days after 3 free days
        assert any("Storage of 7 days billed" in (e["note"] or "") for e in collected["events"])
        again = get_job(client, shop, job)
        assert again["storage_invoice_number"] == number
    finally:
        client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={
            "storage_fee_per_day": "0"})


def test_no_storage_invoice_when_nothing_is_owed(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = new_job(client, shop, title="Collected at once")
    post(client, shop, f"/jobs/{job['id']}/labour", {"hours": "1"})
    for code in ("in_progress", "ready"):
        assert move(client, shop, job, code).status_code == 200
    post(client, shop, f"/jobs/{job['id']}/invoice")
    assert post(client, shop, f"/jobs/{job['id']}/collect").json()["storage_invoice_number"] is None


# --------------------------------------------------------------------------- reading a VIN
def test_a_vin_is_read_for_the_make_the_year_and_the_check_digit() -> None:
    honda = vin_domain.read("1hg cm82633a004352", today=date(2026, 11, 1))
    assert (honda.vin, honda.make, honda.year, honda.check_digit_ok) == ("1HGCM82633A004352", "Honda", 2003, True)
    assert vin_domain.read("1HGCM82634A004352").check_digit_ok is False
    toyota = vin_domain.read("JTDKN3DU0A0123456", today=date(2026, 11, 1))
    assert toyota.make == "Toyota" and toyota.year == 2010
    newer = vin_domain.read("JTDKN3DU0N0123456", today=date(2026, 11, 1))
    assert newer.year == 2022
    assert vin_domain.read("ABC").problem == "A VIN has 17 characters; this has 3"
    assert "never contains" in (vin_domain.read("1HGCM82633A00435O").problem or "")
    assert vin_domain.read("1HGCM82633A004352", today=date(2026, 11, 1)).problem is None


def test_the_vin_can_be_read_through_the_api(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{JOBS}/vin/1HGCM82633A004352", headers=shop["owner"])
    assert r.status_code == 200 and r.json()["make"] == "Honda" and r.json()["valid_shape"] is True
    assert client.get(f"{JOBS}/vin/short", headers=shop["owner"]).json()["valid_shape"] is False


# --------------------------------------------------------------------------- a booked appointment becomes a job
def test_a_booked_appointment_becomes_a_job_with_the_customer_filled_in(client, registry) -> None:  # type: ignore[no-untyped-def]
    garage = make_salon(client, registry, "Garage Booked Visits", units=("jobs",))
    made = book(client, garage, 1, 9, customer_id=garage["customer"]["id"])
    assert made.status_code == 201, made.text
    appt = made.json()
    assert client.get(f"{JOBS}/appointments/{appt['id']}/job", headers=garage["owner"]).json() is None
    with system(garage) as s:                                 # the booking is for the first workday; show it as today's
        s.execute(text("update bookings.appointment set starts_at = now(), ends_at = now() + interval '1 hour' "
                       "where id = :a"), {"a": appt["id"]})
    got = client.get(f"{JOBS}/appointments/waiting", headers=garage["owner"],
                     params={"branch_id": str(garage["branch_id"])})
    assert got.status_code == 200, got.text
    waiting = got.json()
    assert [w["number"] for w in waiting] == [appt["number"]]
    r = client.post(f"{JOBS}/appointments/{appt['id']}/job", headers=garage["owner"], json={
        "title": "Service as booked", "odometer_in": "80500",
        "new_asset": {"label": "Toyota Hilux KCD 123A", "kind": "vehicle"}})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["customer_id"] == garage["customer"]["id"] and job["appointment_id"] == appt["id"]
    assert job["asset"]["label"].startswith("Toyota Hilux") and job["odometer_in"] == "80500.0"
    assert any("Made from appointment" in (e["note"] or "") for e in job["events"])
    again = client.post(f"{JOBS}/appointments/{appt['id']}/job", headers=garage["owner"], json={})
    assert again.status_code == 409
    assert client.get(f"{JOBS}/appointments/waiting", headers=garage["owner"],
                      params={"branch_id": str(garage["branch_id"])}).json() == []          # taken in: no longer waiting
    link = client.get(f"{JOBS}/appointments/{appt['id']}/job", headers=garage["owner"]).json()
    assert link["number"] == job["number"]
    unknown = client.post(f"{JOBS}/appointments/00000000-0000-0000-0000-000000000000/job", headers=garage["owner"],
                          json={})
    assert unknown.status_code == 404
    assert B.startswith("/api")

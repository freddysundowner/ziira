"""Appointments and Bookings through the real application: set-up, booking, double booking (also at the same moment),
the life of an appointment, moving and cancelling with reasons, the waitlist, repeats, classes, walk-ins, invoicing,
permissions and tenant isolation."""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.bookings_helpers import WEEK, ZONE, B, book, make_salon, reason, when, workday
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_salon(client, registry, "Salon Co")
    s["cancel_client"] = reason(client, s, "appointment_cancel", "CLIENT")
    s["move_client"] = reason(client, s, "appointment_reschedule", "CLIENT")
    return s


def local(iso: str) -> str:
    """HH:MM on the business clock of an ISO moment the API answered in any offset."""
    return datetime.fromisoformat(iso).astimezone(ZONE).strftime("%H:%M")


def sql(shop, stmt: str, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


# --------------------------------------------------------------------------- set-up
def test_resources_and_offers_are_set_up_with_hours_and_the_service_item(client, shop) -> None:  # type: ignore[no-untyped-def]
    resources = client.get(f"{B}/resources", headers=shop["owner"]).json()
    assert [r["name"] for r in resources] == ["Anna", "Brian"]
    assert len(resources[0]["hours"]) == 5 and resources[0]["hours"][0]["start_time"] == "09:00:00"
    offer = client.get(f"{B}/offers/{shop['cut']}", headers=shop["owner"]).json()
    assert (offer["duration_minutes"], offer["buffer_after_minutes"], offer["price"]) == (60, 15, "58.00")
    assert sorted(offer["resource_ids"]) == sorted([shop["anna"], shop["brian"]])
    items = client.get(f"{B}/service-items", headers=shop["owner"], params={"company_id": str(shop["company_id"])})
    assert items.status_code == 200 and "DELIVERY" in [i["sku"] for i in items.json()]
    stocked = client.post(f"{B}/offers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "product_id": shop["cement"], "duration_minutes": 30})
    assert stocked.status_code == 422                                   # only service items can be sold by appointment


def test_hours_must_make_sense_and_time_off_reports_who_is_affected(client, shop) -> None:  # type: ignore[no-untyped-def]
    bad = client.put(f"{B}/resources/{shop['anna']}/hours", headers=shop["owner"], json=[
        {"weekday": 0, "start_time": "09:00", "end_time": "12:00"}, {"weekday": 0, "start_time": "11:00", "end_time": "13:00"}])
    assert bad.status_code == 422
    made = book(client, shop, 40, 10, resource_ids=[shop["anna"]])
    assert made.status_code == 201, made.text
    off = client.post(f"{B}/resources/{shop['anna']}/time-off", headers=shop["owner"], json={
        "starts_at": when(40, 9), "ends_at": when(40, 12), "reason": "Course"})
    assert off.status_code == 201 and off.json()["affected_appointments"] == 1
    assert client.post(f"{B}/resources/{shop['anna']}/time-off", headers=shop["owner"], json={
        "starts_at": when(41, 9), "ends_at": when(41, 12)}).json()["affected_appointments"] == 0
    refused = book(client, shop, 41, 10, resource_ids=[shop["anna"]])
    assert refused.status_code == 422 and "time off" in refused.json()["message"].lower()
    forced = book(client, shop, 41, 10, resource_ids=[shop["anna"]], allow_outside_hours=True)
    assert forced.status_code == 201                                    # the front desk may decide to override time off
    over = book(client, shop, 40, 10, resource_ids=[shop["anna"]], allow_outside_hours=True)
    assert over.status_code == 409                                      # but never over another appointment
    assert client.delete(f"{B}/time-off/{off.json()['id']}", headers=shop["owner"]).status_code == 204


# --------------------------------------------------------------------------- availability and booking
def test_availability_shows_free_starts_and_a_booking_removes_them(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = workday(1).isoformat()
    free = client.get(f"{B}/availability", headers=shop["owner"], params={"offer_id": shop["cut"], "date": day}).json()
    assert len(free) == 4 * 7 + 1 - 3 or len(free) > 20                  # every 15 minutes while a 60-minute service fits
    made = book(client, shop, 1, 9)
    assert made.status_code == 201, made.text
    booked = made.json()
    assert booked["status"] == "confirmed" and booked["number"].startswith("APT-") and len(booked["resource_ids"]) == 1
    after = client.get(f"{B}/availability", headers=shop["owner"], params={
        "offer_id": shop["cut"], "date": day, "resource_id": booked["resource_ids"][0]}).json()
    starts = [local(s["start"]) for s in after]
    assert "09:00" not in starts and "10:15" in starts and "09:30" not in starts      # 60 + 15 buffer held from 09:00


def test_the_second_booking_for_one_time_goes_to_the_other_chair_and_the_third_is_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = book(client, shop, 2, 11)
    b = book(client, shop, 2, 11)
    assert a.status_code == b.status_code == 201
    assert set(a.json()["resource_ids"]) != set(b.json()["resource_ids"])
    c = book(client, shop, 2, 11)
    assert c.status_code == 409 and "already taken" in c.json()["message"]
    chosen = book(client, shop, 2, 11, resource_ids=[shop["anna"]])
    assert chosen.status_code == 409
    refused = sql(shop, "select count(*) from bookings.booking_refusal where source = 'staff'")[0][0]
    assert refused >= 2                                                 # the attempts were noted for Intelligence


def test_the_database_itself_refuses_a_double_booking(client, shop) -> None:  # type: ignore[no-untyped-def]
    first = book(client, shop, 3, 9, resource_ids=[shop["anna"]]).json()
    second = book(client, shop, 3, 9, resource_ids=[shop["brian"]]).json()
    with pytest.raises(Exception, match="no_double_booking"):          # put the second one on Anna's chair too, behind the engine's back
        sql(shop, "insert into bookings.appointment_resource (tenant_id, appointment_id, resource_id, blocked) "
                  "select tenant_id, :b, resource_id, blocked from bookings.appointment_resource "
                  "where appointment_id = :a", a=first["id"], b=second["id"])


def test_two_people_booking_the_same_time_at_once_one_wins(client, shop) -> None:  # type: ignore[no-untyped-def]
    barrier = threading.Barrier(6)

    def go() -> int:
        barrier.wait()
        return book(client, shop, 4, 14, resource_ids=[shop["brian"]]).status_code

    with ThreadPoolExecutor(6) as pool:
        codes = Counter(pool.map(lambda _: go(), range(6)))
    assert codes == {201: 1, 409: 5}
    held = sql(shop, "select count(*) from bookings.appointment_resource ar join bookings.appointment a "
                     "on a.id = ar.appointment_id where ar.resource_id = :r and a.starts_at = :s", r=shop["brian"],
               s=when(4, 14))
    assert held[0][0] == 1


def test_a_retry_with_the_same_local_id_returns_the_first_booking(client, shop) -> None:  # type: ignore[no-untyped-def]
    one = book(client, shop, 5, 9, local_id="till-1")
    two = book(client, shop, 5, 9, local_id="till-1")
    assert one.status_code == two.status_code == 201 and one.json()["id"] == two.json()["id"]


# --------------------------------------------------------------------------- the life of an appointment
def test_the_life_from_confirmed_to_invoiced(client, shop) -> None:  # type: ignore[no-untyped-def]
    appt = book(client, shop, 6, 9, customer_id=shop["customer"]["id"], who="cashier").json()
    url = f"{B}/appointments/{appt['id']}"
    assert client.post(f"{url}/start", headers=shop["cashier"]).status_code == 422          # not checked in yet
    assert client.post(f"{url}/finish", headers=shop["cashier"]).status_code == 422
    assert client.post(f"{url}/check-in", headers=shop["cashier"]).json()["status"] == "checked_in"
    assert client.post(f"{url}/start", headers=shop["cashier"]).json()["status"] == "in_service"
    assert client.post(f"{url}/invoice", headers=shop["cashier"]).status_code == 422        # not finished yet
    done = client.post(f"{url}/finish", headers=shop["cashier"]).json()
    assert done["status"] == "completed" and done["minutes_worked"] is not None
    events = sql(shop, "select event_type from kernel.event_outbox where aggregate_id = :a order by id", a=appt["id"])
    completed = sql(shop, "select payload from kernel.event_outbox where aggregate_id = :a and event_type = 'appointment.completed'",
                    a=appt["id"])
    assert "appointment.completed" in [e[0] for e in events]
    line = completed[0][0]["lines"][0]
    assert (line["description"], line["quantity"], line["unit_price"]) == ("Product DELIVERY", "1", "58.00")
    assert completed[0][0]["resource_ids"] == appt["resource_ids"]
    first = client.post(f"{url}/invoice", headers=shop["cashier"])        # the front desk may bill: bookings.checkout
    assert first.status_code == 200, first.text
    number = first.json()["invoice_number"]
    assert number
    assert client.post(f"{url}/invoice", headers=shop["cashier"]).json()["invoice_number"] == number     # once
    invoice = sql(shop, "select total, status from pos.sales_invoice where number = :n", n=number)[0]
    assert str(invoice[0]) == "58.00"
    gone = client.post(f"{url}/cancel", headers=shop["cashier"], json={"reason_code_id": shop["cancel_client"]})
    assert gone.status_code == 422                                                           # finished: no way back


def test_invoicing_on_completion_and_the_message_when_it_cannot(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    on = client.patch(f"{B}/settings", params={"company_id": co}, headers=shop["owner"],
                      json={"invoice_on_completion": True})
    assert on.status_code == 200 and on.json()["invoicing_available"] is True
    with_customer = book(client, shop, 7, 9, customer_id=shop["customer"]["id"]).json()
    without = book(client, shop, 7, 10, client_name="Stranger").json()
    for a in (with_customer, without):
        for step in ("check-in", "start", "finish"):
            assert client.post(f"{B}/appointments/{a['id']}/{step}", headers=shop["owner"]).status_code == 200
    assert client.get(f"{B}/appointments/{with_customer['id']}", headers=shop["owner"]).json()["invoice_number"]
    stranger = client.get(f"{B}/appointments/{without['id']}", headers=shop["owner"]).json()
    assert stranger["status"] == "completed" and stranger["invoice_number"] is None                # not blocked
    flagged = sql(shop, "select message from kernel.exception_item where kind = 'invoice_not_made'")
    assert flagged and "customer" in flagged[0][0]
    client.patch(f"{B}/settings", params={"company_id": co}, headers=shop["owner"],
                 json={"invoice_on_completion": False})


def test_no_show_only_after_the_start_and_frees_the_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    future = book(client, shop, 8, 9).json()
    assert client.post(f"{B}/appointments/{future['id']}/no-show", headers=shop["owner"]).status_code == 422
    past = client.post(f"{B}/appointments", headers=shop["owner"], json={
        "offer_id": shop["cut"], "starts_at": "2020-03-02T09:00:00+03:00", "client_name": "Old", "allow_outside_hours": True})
    assert past.status_code == 201, past.text
    missed = client.post(f"{B}/appointments/{past.json()['id']}/no-show", headers=shop["owner"])
    assert missed.status_code == 200 and missed.json()["status"] == "no_show"
    held = sql(shop, "select holds from bookings.appointment_resource where appointment_id = :a", a=past.json()["id"])
    assert held == [(False,)]


def test_walk_in_starts_now_and_is_checked_in(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{B}/appointments/walk-in", headers=shop["cashier"], json={
        "offer_id": shop["cut"], "client_name": "Just passing", "local_id": "walk-1"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "checked_in" and r.json()["source"] == "walk_in"
    again = client.post(f"{B}/appointments/walk-in", headers=shop["cashier"], json={
        "offer_id": shop["cut"], "client_name": "Just passing", "local_id": "walk-1"})
    assert again.json()["id"] == r.json()["id"]


# --------------------------------------------------------------------------- moving and cancelling
def test_reschedule_needs_a_reason_and_moves_the_hold(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = book(client, shop, 9, 9, resource_ids=[shop["anna"]]).json()
    url = f"{B}/appointments/{a['id']}/reschedule"
    assert client.post(url, headers=shop["owner"], json={"starts_at": when(9, 13)}).status_code == 422
    r = client.post(url, headers=shop["owner"], json={"starts_at": when(9, 13), "reason_code_id": shop["move_client"]})
    assert r.status_code == 200 and local(r.json()["starts_at"]) == "13:00" and local(r.json()["ends_at"]) == "14:00"
    again = book(client, shop, 9, 9, resource_ids=[shop["anna"]])
    assert again.status_code == 201                                     # the old time is free again
    taken = client.post(url, headers=shop["owner"], json={"starts_at": when(9, 9), "reason_code_id": shop["move_client"]})
    assert taken.status_code == 409


def test_cancel_needs_a_reason_marks_late_ones_and_frees_the_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = book(client, shop, 10, 9, resource_ids=[shop["anna"]]).json()
    url = f"{B}/appointments/{a['id']}/cancel"
    assert client.post(url, headers=shop["owner"], json={"reason_code_id": shop["move_client"]}).status_code == 422
    done = client.post(url, headers=shop["owner"], json={"reason_code_id": shop["cancel_client"]})
    assert done.status_code == 200 and done.json()["status"] == "cancelled"
    assert done.json()["late_cancellation"] is False                    # days ahead, the window is 24 hours
    assert book(client, shop, 10, 9, resource_ids=[shop["anna"]]).status_code == 201
    soon = client.post(f"{B}/appointments", headers=shop["owner"], json={
        "offer_id": shop["cut"], "starts_at": "2030-01-07T09:00:00+03:00", "client_name": "Soon"}).json()
    sql(shop, "update bookings.appointment set starts_at = now() + interval '3 hours', ends_at = now() + interval '4 hours' "
              "where id = :a", a=soon["id"])
    late = client.post(f"{B}/appointments/{soon['id']}/cancel", headers=shop["owner"],
                       json={"reason_code_id": shop["cancel_client"]}).json()
    assert late["late_cancellation"] is True


# --------------------------------------------------------------------------- waitlist
def test_waitlist_offer_and_accept(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = workday(11).isoformat()
    full = [book(client, shop, 11, 9, resource_ids=[shop[c]]) for c in ("anna", "brian")]
    assert all(f.status_code == 201 for f in full)
    entry = client.post(f"{B}/waitlist", headers=shop["cashier"], json={
        "offer_id": shop["cut"], "branch_id": str(shop["branch_id"]), "wanted_from": day, "wanted_to": day,
        "client_name": "Hopeful", "client_phone": "0711000111"})
    assert entry.status_code == 201, entry.text
    taken = client.post(f"{B}/waitlist/{entry.json()['id']}/offer", headers=shop["cashier"], json={"starts_at": when(11, 9)})
    assert taken.status_code == 409                                     # not free: nothing is offered
    cancelled = client.post(f"{B}/appointments/{full[0].json()['id']}/cancel", headers=shop["cashier"],
                            json={"reason_code_id": shop["cancel_client"]})
    assert cancelled.json()["waitlist_matches"] == 1
    matches = client.get(f"{B}/appointments/{full[0].json()['id']}/waitlist-matches", headers=shop["cashier"]).json()
    assert [m["client_name"] for m in matches] == ["Hopeful"]
    offered = client.post(f"{B}/waitlist/{entry.json()['id']}/offer", headers=shop["cashier"], json={"starts_at": when(11, 9)})
    assert offered.status_code == 200 and offered.json()["status"] == "offered"
    accepted = client.post(f"{B}/waitlist/{entry.json()['id']}/accept", headers=shop["cashier"])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["entry"]["status"] == "booked" and accepted.json()["appointment"]["source"] == "waitlist"
    assert client.post(f"{B}/waitlist/{entry.json()['id']}/accept", headers=shop["cashier"]).status_code == 422


# --------------------------------------------------------------------------- repeats and classes
def test_a_weekly_series_books_what_fits_and_reports_the_rest(client, shop) -> None:  # type: ignore[no-untyped-def]
    day = workday(15)
    week_later = workday(20)                                            # five working days on: the same weekday next week
    assert (week_later - day).days == 7
    both = [book(client, shop, 20, 15, resource_ids=[shop[c]]) for c in ("anna", "brian")]
    assert all(b.status_code == 201 for b in both)                      # both chairs taken at 15:00 on that day
    r = client.post(f"{B}/appointments/series", headers=shop["owner"], json={
        "offer_id": shop["cut"], "starts_at": when(15, 15), "client_name": "Regular", "frequency": "weekly", "count": 3})
    assert r.status_code == 201, r.text
    series = r.json()
    assert len(series["created"]) == 2 and [c["index"] for c in series["conflicts"]] == [1]
    assert "taken" in series["conflicts"][0]["problem"]
    assert {a["series_id"] for a in series["created"]} == {series["series_id"]}
    assert [a["starts_at"][:10] for a in series["created"]] == [day.isoformat(), (day + timedelta(days=14)).isoformat()]
    assert {local(a["starts_at"]) for a in series["created"]} == {"15:00"}      # the same time of day each week
    listed = client.get(f"{B}/appointments", headers=shop["owner"], params={"series_id": series["series_id"]}).json()
    assert [a["series_index"] for a in listed] == [0, 2]


def test_a_class_has_a_capacity_and_a_list_of_people(client, shop) -> None:  # type: ignore[no-untyped-def]
    room = client.post(f"{B}/resources", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "name": "Studio", "kind": "room",
        "hours": WEEK}).json()
    yoga = client.post(f"{B}/offers", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "name": "Yoga", "kind": "class", "duration_minutes": 60, "capacity": 2,
        "price": "10.00", "resource_ids": [room["id"]]}).json()
    held = client.post(f"{B}/appointments", headers=shop["owner"], json={"offer_id": yoga["id"], "starts_at": when(25, 8 + 1)})
    assert held.status_code == 201, held.text
    url = f"{B}/appointments/{held.json()['id']}/attendees"
    assert client.post(url, headers=shop["owner"], json={"name": "One"}).status_code == 201
    assert client.post(url, headers=shop["owner"], json={"customer_id": shop["customer"]["id"]}).status_code == 201
    full = client.post(url, headers=shop["owner"], json={"name": "Three"})
    assert full.status_code == 409 and "full" in full.json()["message"]
    people = client.get(url, headers=shop["owner"]).json()
    assert [p["name"] for p in people] == ["One", "Wanjiku Client"]
    left = client.patch(f"{B}/attendees/{people[0]['id']}", headers=shop["owner"], json={"status": "cancelled"})
    assert left.status_code == 200
    assert client.post(url, headers=shop["owner"], json={"name": "Three"}).status_code == 201     # room again
    assert client.get(f"{B}/appointments/{held.json()['id']}", headers=shop["owner"]).json()["attendees"] == 2


# --------------------------------------------------------------------------- calendar and front desk
def test_calendar_and_front_desk_views(client, shop) -> None:  # type: ignore[no-untyped-def]
    start, end = when(1, 0), when(2, 0)
    cal = client.get(f"{B}/calendar", headers=shop["cashier"], params={
        "branch_id": str(shop["branch_id"]), "start": start, "end": end})
    assert cal.status_code == 200, cal.text
    body = cal.json()
    assert {r["name"] for r in body["resources"]} >= {"Anna", "Brian"} and body["timezone"] == "Africa/Nairobi"
    assert any(a["status"] == "confirmed" for a in body["appointments"])
    too_long = client.get(f"{B}/calendar", headers=shop["cashier"], params={
        "branch_id": str(shop["branch_id"]), "start": when(1, 0), "end": when(60, 0)})
    assert too_long.status_code == 422
    desk = client.get(f"{B}/front-desk", headers=shop["cashier"], params={"branch_id": str(shop["branch_id"])})
    assert desk.status_code == 200 and any(a["source"] == "walk_in" for a in desk.json()["appointments"])


# --------------------------------------------------------------------------- permissions and isolation
def test_who_may_do_what(client, shop) -> None:  # type: ignore[no-untyped-def]
    base = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "name": "Chair 9"}
    assert client.post(f"{B}/resources", headers=shop["cashier"], json=base).status_code == 403          # set-up is for managers
    assert client.post(f"{B}/resources", headers=shop["manager"], json=base).status_code == 201
    assert client.get(f"{B}/resources", headers=shop["cashier"]).status_code == 200
    assert client.get(f"{B}/resources", headers=shop["storekeeper"]).status_code == 403                  # no bookings rights
    assert book(client, shop, 30, 9, who="storekeeper").status_code == 403
    assert book(client, shop, 30, 9, who="juja_keeper").status_code == 403
    assert client.post(f"{B}/appointments", json={"offer_id": shop["cut"], "starts_at": when(30, 9),
                                                 "client_name": "x"}).status_code == 401
    accountant = shop["user"]("acc", "Accountant", None)
    assert client.get(f"{B}/appointments", headers=accountant).status_code == 200
    assert book(client, shop, 30, 10, who="cashier").status_code == 201
    juja = shop["user"]("jujamgr", "Branch Manager", shop["juja"])
    assert client.get(f"{B}/appointments", headers=juja).json() == []                                    # another branch's diary
    one = book(client, shop, 31, 9).json()
    assert client.get(f"{B}/appointments/{one['id']}", headers=juja).status_code == 404
    assert client.post(f"{B}/appointments/{one['id']}/check-in", headers=juja).status_code == 404


def test_another_business_sees_nothing(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    other = make_salon(client, registry, "Salon Rival")
    mine = book(client, shop, 32, 9).json()
    assert client.get(f"{B}/appointments/{mine['id']}", headers=other["owner"]).status_code == 404
    assert client.get(f"{B}/offers/{shop['cut']}", headers=other["owner"]).status_code == 404
    assert [r["id"] for r in client.get(f"{B}/resources", headers=other["owner"]).json()] != [shop["anna"]]
    sneaky = client.post(f"{B}/appointments", headers=other["owner"], json={
        "offer_id": shop["cut"], "starts_at": when(32, 9), "client_name": "x"})
    assert sneaky.status_code == 404

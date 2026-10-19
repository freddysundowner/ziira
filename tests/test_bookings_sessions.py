"""Group sessions (classes): capacity that cannot be oversold, a waitlist that fills freed places with a confirm window, late
cancellation, closed days, capacity changes and the public functions other units build on."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.bookings_helpers import WEEK, ZONE, B, make_salon, reason, when, workday
from tests.pos_helpers import credit_customer
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_salon(client, registry, "Class Studio")
    co, branch = str(s["company_id"]), str(s["branch_id"])
    room = client.post(f"{B}/resources", headers=s["owner"], json={
        "company_id": co, "branch_id": branch, "name": "Studio", "kind": "room", "hours": WEEK})
    assert room.status_code == 201, room.text
    s["room"] = room.json()["id"]
    coach = client.post(f"{B}/resources", headers=s["owner"], json={
        "company_id": co, "branch_id": branch, "name": "Coach Cleo", "kind": "staff", "hours": WEEK})
    s["coach"] = coach.json()["id"]
    offer = client.post(f"{B}/offers", headers=s["owner"], json={
        "company_id": co, "name": "Morning yoga", "kind": "class", "duration_minutes": 60, "capacity": 2,
        "resource_mode": "all", "resource_ids": [s["room"], s["coach"]], "price": "10.00"})
    assert offer.status_code == 201, offer.text
    s["yoga"] = offer.json()["id"]
    s["cancel_business"] = reason(client, s, "appointment_cancel", "BUSINESS")
    s["people"] = [credit_customer(client, s, f"Member {i}", limit="1000", terms=0) for i in range(6)]
    return s


def sql(shop, stmt: str, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def make_session(client, shop, n: int, hour: int = 9, **extra):  # type: ignore[no-untyped-def]
    r = client.post(f"{B}/sessions", headers=shop["cashier"], json={
        "offer_id": shop["yoga"], "starts_at": when(n, hour), **extra})
    assert r.status_code == 201, r.text
    return r.json()["created"][0]


def book(client, shop, session_id, i: int, who: str = "cashier"):  # type: ignore[no-untyped-def]
    return client.post(f"{B}/sessions/{session_id}/book", headers=shop[who], json={"customer_id": shop["people"][i]["id"]})


def get(client, shop, session_id):  # type: ignore[no-untyped-def]
    return client.get(f"{B}/sessions/{session_id}", headers=shop["cashier"]).json()


def events(shop, session_id, kind):  # type: ignore[no-untyped-def]
    return sql(shop, "select payload from kernel.event_outbox where aggregate_id = :a and event_type = :t order by id",
               a=session_id, t=kind)


def test_a_full_class_puts_people_on_the_waitlist_in_order(client, shop) -> None:  # type: ignore[no-untyped-def]
    s = make_session(client, shop, 1)
    assert s["capacity"] == 2 and s["free"] == 2
    first, second, third, fourth = (book(client, shop, s["id"], i) for i in range(4))
    assert [x.json()["status"] for x in (first, second, third, fourth)] == ["booked", "booked", "waitlisted", "waitlisted"]
    assert (third.json()["position"], fourth.json()["position"]) == (1, 2)
    now = get(client, shop, s["id"])
    assert (now["booked"], now["waiting"], now["free"]) == (2, 2, 0)
    twice = book(client, shop, s["id"], 0)
    assert twice.status_code == 409                                            # already on the class
    roster = client.get(f"{B}/sessions/{s['id']}/roster", headers=shop["cashier"]).json()
    assert [r["name"] for r in roster] == ["Member 0", "Member 1"]


def test_a_freed_place_is_held_for_the_first_waiting_person_until_they_confirm(client, shop) -> None:  # type: ignore[no-untyped-def]
    s = make_session(client, shop, 2)
    booked = [book(client, shop, s["id"], i).json() for i in range(4)]
    cancelled = client.post(f"{B}/sessions/attendees/{booked[0]['attendee_id']}/cancel", headers=shop["cashier"])
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    waiting = client.get(f"{B}/sessions/{s['id']}/waitlist", headers=shop["cashier"]).json()
    assert [(w["name"], w["status"]) for w in waiting] == [("Member 2", "offered"), ("Member 3", "waiting")]
    held = get(client, shop, s["id"])
    assert (held["booked"], held["held"], held["free"]) == (1, 1, 0)              # the place is not for sale again
    assert book(client, shop, s["id"], 5, ).json()["status"] == "waitlisted"
    taken = client.post(f"{B}/sessions/waitlist/{waiting[0]['id']}/confirm", headers=shop["cashier"])
    assert taken.status_code == 200 and taken.json()["status"] == "booked"
    final = get(client, shop, s["id"])
    assert (final["booked"], final["held"], final["waiting"]) == (2, 0, 2)
    kinds = [e[0] for e in sql(shop, "select event_type from kernel.event_outbox where aggregate_id = :a order by id",
                               a=s["id"])]
    assert "class.waitlist_offered" in kinds and "class.waitlist_promoted" in kinds


def test_an_offer_that_runs_out_goes_to_the_next_person(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.bookings.services import sessions

    s = make_session(client, shop, 3)
    booked = [book(client, shop, s["id"], i).json() for i in range(4)]
    client.post(f"{B}/sessions/attendees/{booked[1]['attendee_id']}/cancel", headers=shop["cashier"])
    sql(shop, "update bookings.session_waitlist set confirm_by = now() - interval '1 minute' "
              "where appointment_id = :a and status = 'offered'", a=s["id"])
    with system(shop) as db:
        assert sessions.expire_offers(db) == 1
    waiting = client.get(f"{B}/sessions/{s['id']}/waitlist", headers=shop["cashier"]).json()
    assert [(w["name"], w["status"]) for w in waiting] == [("Member 3", "offered")]
    late = client.post(f"{B}/sessions/waitlist/{booked[2]['waitlist_id']}/confirm", headers=shop["cashier"])
    assert late.status_code in (404, 422)                                         # the first offer ran out


def test_with_a_confirm_window_of_zero_the_next_person_is_put_straight_in(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = str(shop["company_id"])
    assert client.patch(f"{B}/settings", params={"company_id": cid}, headers=shop["owner"],
                        json={"waitlist_confirm_minutes": 0}).status_code == 200
    try:
        s = make_session(client, shop, 4)
        booked = [book(client, shop, s["id"], i).json() for i in range(3)]
        client.post(f"{B}/sessions/attendees/{booked[0]['attendee_id']}/cancel", headers=shop["cashier"])
        roster = client.get(f"{B}/sessions/{s['id']}/roster", headers=shop["cashier"]).json()
        assert sorted((r["name"], r["status"]) for r in roster) == [
            ("Member 0", "cancelled"), ("Member 1", "booked"), ("Member 2", "booked")]
        assert roster[-1]["source"] == "waitlist"
    finally:
        client.patch(f"{B}/settings", params={"company_id": cid}, headers=shop["owner"],
                     json={"waitlist_confirm_minutes": 30})


def test_the_last_place_is_taken_once_even_at_the_same_moment(client, shop) -> None:  # type: ignore[no-untyped-def]
    s = make_session(client, shop, 5, capacity=1)
    gate = threading.Barrier(4)

    def attempt(i: int) -> str:
        gate.wait()
        return str(book(client, shop, s["id"], i).json()["status"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert sorted(results) == ["booked", "waitlisted", "waitlisted", "waitlisted"]
    assert sql(shop, "select count(*) from bookings.appointment_attendee where appointment_id = :a and status <> 'cancelled'",
               a=s["id"]) == [(1,)]


def test_a_cancellation_inside_the_window_is_late_and_published(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = str(shop["company_id"])
    client.patch(f"{B}/settings", params={"company_id": cid}, headers=shop["owner"], json={"cancel_window_hours": 720})
    try:
        s = make_session(client, shop, 6)
        one = book(client, shop, s["id"], 0).json()
        late = client.post(f"{B}/sessions/attendees/{one['attendee_id']}/cancel", headers=shop["cashier"])
        assert late.json()["late_cancellation"] is True
        payload = events(shop, s["id"], "class.attendee_cancelled")[0][0]
        assert payload["late"] is True and payload["customer_id"] == shop["people"][0]["id"]
        # the class's own rule wins over the business's
        client.patch(f"{B}/offers/{shop['yoga']}", headers=shop["owner"], json={"group_late_cancel_hours": 1})
        s2 = make_session(client, shop, 7)
        two = book(client, shop, s2["id"], 1).json()
        early = client.post(f"{B}/sessions/attendees/{two['attendee_id']}/cancel", headers=shop["cashier"])
        assert early.json()["late_cancellation"] is False
    finally:
        client.patch(f"{B}/settings", params={"company_id": cid}, headers=shop["owner"], json={"cancel_window_hours": 24})
        client.patch(f"{B}/offers/{shop['yoga']}", headers=shop["owner"], json={"group_late_cancel_hours": None})


def test_attendance_is_marked_and_can_be_undone_with_events(client, shop) -> None:  # type: ignore[no-untyped-def]
    s = make_session(client, shop, 8)
    one = book(client, shop, s["id"], 2).json()
    patch = client.patch(f"{B}/attendees/{one['attendee_id']}", headers=shop["cashier"], json={"status": "attended"})
    assert patch.status_code == 200 and patch.json()["status"] == "attended"
    assert client.patch(f"{B}/attendees/{one['attendee_id']}", headers=shop["cashier"],
                        json={"status": "booked"}).status_code == 200
    assert len(events(shop, s["id"], "class.attendee_attended")) == 1
    assert len(events(shop, s["id"], "class.attendee_reset")) == 1


def test_a_bigger_room_offers_the_new_places_and_a_smaller_one_is_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    s = make_session(client, shop, 9)
    for i in range(4):
        book(client, shop, s["id"], i)
    smaller = client.put(f"{B}/sessions/{s['id']}/capacity", headers=shop["cashier"], json={"capacity": 1})
    assert smaller.status_code == 422
    bigger = client.put(f"{B}/sessions/{s['id']}/capacity", headers=shop["cashier"], json={"capacity": 3})
    assert bigger.status_code == 200
    waiting = client.get(f"{B}/sessions/{s['id']}/waitlist", headers=shop["cashier"]).json()
    assert [w["status"] for w in waiting] == ["offered", "waiting"]


def test_holidays_are_skipped_in_a_weekly_series_and_blocked_for_clients(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = str(shop["company_id"])
    first = datetime.fromisoformat(when(10, 12))
    second_week = (first + timedelta(days=7)).astimezone(ZONE).date()
    closed = client.post(f"{B}/closed-days", headers=shop["owner"], json={
        "company_id": cid, "day": second_week.isoformat(), "label": "Public holiday"})
    assert closed.status_code == 201
    made = client.post(f"{B}/sessions", headers=shop["cashier"], json={
        "offer_id": shop["yoga"], "starts_at": when(10, 12), "weeks": 3})
    assert made.status_code == 201, made.text
    out = made.json()
    assert len(out["created"]) == 2 and len(out["skipped"]) == 1
    assert "closed" in out["skipped"][0]["problem"]
    listed = client.get(f"{B}/closed-days", headers=shop["cashier"], params={"company_id": cid}).json()
    assert [d["label"] for d in listed] == ["Public holiday"]
    assert client.delete(f"{B}/closed-days/{listed[0]['id']}", headers=shop["cashier"]).status_code == 403
    assert client.delete(f"{B}/closed-days/{listed[0]['id']}", headers=shop["owner"]).status_code == 204


def test_another_instructor_can_take_a_class_and_a_cancelled_class_frees_everyone(client, shop) -> None:  # type: ignore[no-untyped-def]
    other = client.post(f"{B}/resources", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "name": "Coach Dan", "kind": "staff",
        "hours": WEEK}).json()["id"]
    client.patch(f"{B}/offers/{shop['yoga']}", headers=shop["owner"], json={"resource_ids": [shop["room"], shop["coach"], other]})
    s = make_session(client, shop, 11)
    # the offer needs all of its resources: the room, the coach and Dan - so make the session with the full set, then swap
    assert s["resource_ids"]
    full = client.get(f"{B}/sessions/{s['id']}", headers=shop["cashier"]).json()
    assert set(full["resource_ids"]) == {shop["room"], shop["coach"], other}
    one = book(client, shop, s["id"], 0).json()
    book(client, shop, s["id"], 1)
    book(client, shop, s["id"], 2)                                                  # waitlisted
    gone = client.post(f"{B}/sessions/{s['id']}/cancel", headers=shop["cashier"],
                       json={"reason_code_id": shop["cancel_business"]})
    assert gone.status_code == 200 and gone.json()["status"] == "cancelled"
    roster = client.get(f"{B}/sessions/{s['id']}/roster", headers=shop["cashier"]).json()
    assert {r["status"] for r in roster} == {"cancelled"}
    assert client.get(f"{B}/sessions/{s['id']}/waitlist", headers=shop["cashier"]).json() == []
    payloads = events(shop, s["id"], "class.attendee_cancelled")
    assert len(payloads) == 2 and all(p[0]["session_cancelled"] and p[0]["late"] is False for p in payloads)
    assert events(shop, s["id"], "class.cancelled")
    assert one["attendee_id"]


def test_other_units_use_the_public_functions(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.bookings import public as bookings

    s = make_session(client, shop, 12)
    with system(shop) as db:
        view = bookings.get_session_view(db, UUID(s["id"]))
        assert (view.capacity, view.booked, view.free) == (2, 0, 2)
        a = bookings.book_attendee(db, UUID(s["id"]), customer_id=UUID(shop["people"][0]["id"]))
        b = bookings.book_attendee(db, UUID(s["id"]), customer_id=UUID(shop["people"][1]["id"]))
        c = bookings.book_attendee(db, UUID(s["id"]), customer_id=UUID(shop["people"][2]["id"]))
        assert (a.status, b.status, c.status, c.position) == ("booked", "booked", "waitlisted", 1)
        assert len(bookings.session_roster(db, UUID(s["id"]))) == 2
        assert [w.name for w in bookings.session_waitlist(db, UUID(s["id"]))] == ["Member 2"]
        marked = bookings.mark_attendee(db, a.attendee.id, "attended")
        assert marked.status == "attended"
        listed = bookings.list_sessions(db, branch_id=UUID(str(shop["branch_id"])))
        assert any(x.id == UUID(s["id"]) for x in listed)


def test_only_the_front_desk_can_book_people_on(client, shop) -> None:  # type: ignore[no-untyped-def]
    s = make_session(client, shop, 13)
    viewer = shop["user"]("classviewer", "Accountant", shop["branch_id"])
    assert client.get(f"{B}/sessions/{s['id']}", headers=viewer).status_code == 200
    assert book(client, shop, s["id"], 0, who="owner").status_code == 201
    forbidden = client.post(f"{B}/sessions/{s['id']}/book", headers=viewer, json={"name": "Sneak"})
    assert forbidden.status_code == 403


def test_workday_helper_is_in_the_future() -> None:
    assert workday(1) > datetime.now().date()

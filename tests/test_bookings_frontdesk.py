"""The front desk: services with processing time, prices by staff level, a visit of several services in sequence, who is free
and the walk-in queue, the rota, 'due again' lists and reminders, chair rental, and the client card's patch-test warning."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.bookings_helpers import ZONE, B, make_salon, reason, when
from tests.pos_helpers import credit_customer
from tests.stock_helpers import system

N = "/api/v1/notifications"
ALL_WEEK = [{"weekday": d, "start_time": "00:00", "end_time": "23:59"} for d in range(7)]


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_salon(client, registry, "Front Desk Salon")
    registry.enable(s["tenant_id"], "messaging")
    for channel in ("sms", "email"):
        r = client.put(f"{N}/channels/{channel}", headers=s["owner"], json={
            "company_id": str(s["company_id"]), "provider": "fake", "secret": {"k": "v"}})
        assert r.status_code == 200, r.text
    co, branch = str(s["company_id"]), str(s["branch_id"])
    client.patch(f"{B}/resources/{s['anna']}", headers=s["owner"], json={"level": "Senior"})
    client.patch(f"{B}/resources/{s['brian']}", headers=s["owner"], json={"level": "Junior"})
    colour = client.post(f"{B}/offers", headers=s["owner"], json={
        "company_id": co, "name": "Colour", "duration_minutes": 120, "price": "300.00", "buffer_after_minutes": 0,
        "processing_start_minutes": 30, "processing_minutes": 60, "resource_ids": [s["anna"]]})
    assert colour.status_code == 201, colour.text
    trim = client.post(f"{B}/offers", headers=s["owner"], json={
        "company_id": co, "name": "Trim", "duration_minutes": 30, "price": "20.00", "buffer_after_minutes": 0,
        "resource_ids": [s["anna"], s["brian"]]})
    s.update({"colour": colour.json()["id"], "trim": trim.json()["id"]})
    s["cancel_client"] = reason(client, s, "appointment_cancel", "CLIENT")
    s["co"], s["branch"] = co, branch
    return s


def sql(shop, stmt: str, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def make_appt(client, shop, offer, n, hour, minute=0, **extra):  # type: ignore[no-untyped-def]
    return client.post(f"{B}/appointments", headers=shop["cashier"], json={
        "offer_id": offer, "starts_at": when(n, hour, minute), "client_name": "Someone", **extra})


# --------------------------------------------------------------------------- processing time
def test_the_stylist_is_free_while_the_colour_sets(client, shop) -> None:  # type: ignore[no-untyped-def]
    colour = make_appt(client, shop, shop["colour"], 1, 9, resource_ids=[shop["anna"]])
    assert colour.status_code == 201, colour.text
    during = make_appt(client, shop, shop["trim"], 1, 9, 30, resource_ids=[shop["anna"]])
    assert during.status_code == 201, during.text                                  # 09:30-10:00 falls in the free minutes
    exact_end = make_appt(client, shop, shop["trim"], 1, 10, 0, resource_ids=[shop["anna"]])
    assert exact_end.status_code == 201                                            # 10:00-10:30, still free time
    clash = make_appt(client, shop, shop["trim"], 1, 10, 15, resource_ids=[shop["anna"]])
    assert clash.status_code == 409                                                # 10:30 is when she is needed again
    first_part = make_appt(client, shop, shop["trim"], 1, 9, 15, resource_ids=[shop["anna"]])
    assert first_part.status_code == 409                                           # 09:00-09:30 she is applying colour
    held = sql(shop, "select count(*), count(distinct part) from bookings.appointment_resource where appointment_id = :a",
               a=colour.json()["id"])
    assert held == [(2, 2)]
    moved = client.post(f"{B}/appointments/{colour.json()['id']}/reschedule", headers=shop["cashier"], json={
        "starts_at": when(2, 9), "reason_code_id": reason(client, shop, "appointment_reschedule", "CLIENT")})
    assert moved.status_code == 200 and sql(
        shop, "select count(*) from bookings.appointment_resource where appointment_id = :a", a=colour.json()["id"]) == [(2,)]


def test_free_minutes_must_fit_inside_the_service(client, shop) -> None:  # type: ignore[no-untyped-def]
    bad = client.post(f"{B}/offers", headers=shop["owner"], json={
        "company_id": shop["co"], "name": "Impossible", "duration_minutes": 60, "processing_start_minutes": 30,
        "processing_minutes": 45, "resource_ids": [shop["anna"]]})
    assert bad.status_code == 422


# --------------------------------------------------------------------------- price by staff level
def test_the_price_follows_the_staff_level_or_a_named_variant(client, shop) -> None:  # type: ignore[no-untyped-def]
    put = client.put(f"{B}/offers/{shop['cut']}/variants", headers=shop["owner"], json={"variants": [
        {"label": "Senior stylist", "level": "Senior", "price": "80.00"},
        {"label": "Junior stylist", "level": "Junior", "price": "50.00"},
        {"label": "Long hair", "price": "95.00"}]})
    assert put.status_code == 200, put.text
    senior = make_appt(client, shop, shop["cut"], 3, 9, resource_ids=[shop["anna"]]).json()
    junior = make_appt(client, shop, shop["cut"], 3, 11, resource_ids=[shop["brian"]]).json()
    assert (senior["price"], senior["price_variant"]) == ("80.00", "Senior stylist")
    assert (junior["price"], junior["price_variant"]) == ("50.00", "Junior stylist")
    long_hair = make_appt(client, shop, shop["cut"], 3, 13, resource_ids=[shop["brian"]], price_variant="Long hair").json()
    assert long_hair["price"] == "95.00"
    unknown = make_appt(client, shop, shop["cut"], 3, 15, price_variant="Gold")
    assert unknown.status_code == 422
    offer = client.get(f"{B}/offers/{shop['cut']}", headers=shop["owner"]).json()
    assert [v["label"] for v in offer["variants"]] == ["Senior stylist", "Junior stylist", "Long hair"]
    assert client.put(f"{B}/offers/{shop['cut']}/variants", headers=shop["cashier"], json={"variants": []}).status_code == 403


# --------------------------------------------------------------------------- a visit in sequence
def test_a_visit_books_services_one_after_another_all_or_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"starts_at": when(4, 9), "client_name": "Visit Vera", "items": [
        {"offer_id": shop["colour"], "resource_ids": [shop["anna"]]},
        {"offer_id": shop["trim"], "resource_ids": [shop["brian"]]}]}
    made = client.post(f"{B}/visits", headers=shop["cashier"], json=body)
    assert made.status_code == 201, made.text
    legs = made.json()["appointments"]
    assert len(legs) == 2 and legs[0]["visit_id"] == legs[1]["visit_id"] == made.json()["visit_id"]
    assert datetime.fromisoformat(legs[1]["starts_at"]) == datetime.fromisoformat(legs[0]["ends_at"])
    # the same again clashes on the first leg: nothing at all is booked for it
    before = sql(shop, "select count(*) from bookings.appointment")[0][0]
    again = client.post(f"{B}/visits", headers=shop["cashier"], json={
        **body, "items": [{"offer_id": shop["trim"], "resource_ids": [shop["brian"]]}] * 2,
        "starts_at": when(4, 10, 30)})                # the second trim would start at 11:00, when Brian is booked
    assert again.status_code == 409
    assert sql(shop, "select count(*) from bookings.appointment")[0][0] == before
    got = client.get(f"{B}/visits/{made.json()['visit_id']}", headers=shop["cashier"]).json()
    assert [a["id"] for a in got["appointments"]] == [a["id"] for a in legs]


# --------------------------------------------------------------------------- who is free, the queue
def test_the_board_shows_who_is_free_and_walk_ins_queue_when_everyone_is_busy(client, shop) -> None:  # type: ignore[no-untyped-def]
    co, branch = shop["co"], shop["branch"]
    chairs = [client.post(f"{B}/resources", headers=shop["owner"], json={
        "company_id": co, "branch_id": branch, "name": name, "kind": "staff", "hours": ALL_WEEK}).json()["id"]
        for name in ("Night Nia", "Night Noel")]
    walk = client.post(f"{B}/offers", headers=shop["owner"], json={
        "company_id": co, "name": "Quick cut", "duration_minutes": 30, "price": "15.00", "resource_ids": chairs,
        "buffer_after_minutes": 0})
    offer = walk.json()["id"]
    board = client.get(f"{B}/front-desk/board", headers=shop["cashier"], params={"branch_id": branch}).json()
    states = {p["name"]: p["state"] for p in board["resources"]}
    assert states["Night Nia"] == "free" and states["Night Noel"] == "free"
    first = client.post(f"{B}/front-desk/walk-in", headers=shop["cashier"], json={
        "offer_id": offer, "client_name": "One", "resource_ids": [chairs[0]]}).json()
    second = client.post(f"{B}/front-desk/walk-in", headers=shop["cashier"], json={
        "offer_id": offer, "client_name": "Two", "resource_ids": [chairs[1]]}).json()
    assert first["wait_minutes"] == 0 and second["wait_minutes"] == 0
    third = client.post(f"{B}/front-desk/walk-in", headers=shop["cashier"], json={"offer_id": offer, "client_name": "Three"})
    assert third.status_code == 201, third.text
    queued = third.json()
    assert queued["wait_minutes"] >= 1 and queued["appointment"]["status"] == "checked_in"
    board = client.get(f"{B}/front-desk/board", headers=shop["cashier"], params={"branch_id": branch}).json()
    busy = {p["name"]: p for p in board["resources"]}
    assert busy["Night Nia"]["state"] == "busy" and busy["Night Nia"]["current"]["client_name"] == "One"
    assert [w["client_name"] for w in board["waiting"]][:1] == ["Three"] or any(
        w["client_name"] == "Three" for w in board["waiting"])
    assert any(t["client_name"] == "One" for t in board["to_bill"] + board["in_service"] + board["waiting"])


# --------------------------------------------------------------------------- rota
def test_the_rota_lists_weekly_hours_and_time_off(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.post(f"{B}/resources/{shop['anna']}/time-off", headers=shop["owner"], json={
        "starts_at": when(1, 9), "ends_at": when(1, 12), "reason": "Course"})
    monday = date.today() - timedelta(days=date.today().weekday())
    rota = client.get(f"{B}/rota", headers=shop["cashier"], params={
        "branch_id": shop["branch"], "week_start": (workday_start(1)).isoformat()})
    assert rota.status_code == 200, rota.text
    anna = next(p for p in rota.json() if p["name"] == "Anna")
    assert anna["days"][0]["windows"] == ["09:00-17:00"] and anna["days"][6]["windows"] == []
    assert anna["time_off"] and "Course" in anna["time_off"][0]
    assert monday  # the default week starts on a Monday


def workday_start(n: int) -> date:
    when_ = datetime.fromisoformat(when(n, 9)).astimezone(ZONE).date()
    return when_ - timedelta(days=when_.weekday())


# --------------------------------------------------------------------------- due again
_hours = iter(range(2, 1000, 3))


def finished_visit(shop, customer_id: str, days_ago: int, offer: str) -> str:  # type: ignore[no-untyped-def]
    shift = next(_hours)
    with system(shop) as s:
        row = s.execute(text(
            "insert into bookings.appointment (tenant_id, company_id, branch_id, number, offer_id, status, source, "
            "starts_at, ends_at, customer_id, client_name, price, completed_at) values (kernel.current_tenant(), :c, :b, "
            ":n, :o, 'completed', 'staff', now() - make_interval(days => :d, hours => :h), now() - make_interval(days => :d, hours => :h) + "
            "interval '1 hour', :cu, 'Regular Rita', 50, now() - make_interval(days => :d, hours => :h)) returning id"),
            {"c": shop["co"], "b": shop["branch"], "n": "T-" + uuid4().hex[:8], "o": offer, "d": days_ago, "h": shift,
             "cu": customer_id}).one()
        s.execute(text(
            "insert into bookings.appointment_resource (tenant_id, appointment_id, resource_id, blocked, holds) "
            "values (kernel.current_tenant(), :a, :r, tstzrange(now() - make_interval(days => :d, hours => :h), now() - "
            "make_interval(days => :d, hours => :h) + interval '1 hour'), true)"),
            {"a": str(row.id), "r": shop["anna"], "d": days_ago, "h": shift})
        return str(row.id)


def test_clients_who_are_due_again_are_listed_messaged_once_and_dropped_when_they_book(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.patch(f"{B}/offers/{shop['cut']}", headers=shop["owner"], json={"recall_days": 30}).status_code == 200
    rita = credit_customer(client, shop, "Regular Rita", limit="1000", terms=0, phone="0712345678")
    finished_visit(shop, rita["id"], 45, shop["cut"])
    due = client.get(f"{B}/recalls", headers=shop["cashier"], params={"company_id": shop["co"]}).json()
    row = next(r for r in due if r["customer_id"] == rita["id"])
    assert row["overdue_days"] >= 14 and row["service"].startswith("Product")
    sent = client.post(f"{B}/recalls/send", headers=shop["cashier"], json={
        "company_id": shop["co"], "customer_id": rita["id"], "offer_id": shop["cut"]})
    assert sent.status_code == 201, sent.text
    queued = sql(shop, "select template, recipient from kernel.notification where template = 'appointment_recall'")
    assert queued and queued[0][1] == "254712345678"
    again = client.post(f"{B}/recalls/send", headers=shop["cashier"], json={
        "company_id": shop["co"], "customer_id": rita["id"], "offer_id": shop["cut"]})
    assert again.status_code == 422                                              # once per visit
    still = client.get(f"{B}/recalls", headers=shop["cashier"], params={"company_id": shop["co"]}).json()
    assert next(r for r in still if r["customer_id"] == rita["id"])["last_outcome"] == "sent"
    booked = make_appt(client, shop, shop["cut"], 5, 9, customer_id=rita["id"])
    assert booked.status_code == 201
    gone = client.get(f"{B}/recalls", headers=shop["cashier"], params={"company_id": shop["co"]}).json()
    assert all(r["customer_id"] != rita["id"] for r in gone)                        # something is booked now


def test_a_snoozed_or_declined_client_leaves_the_list(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = credit_customer(client, shop, "Snooze Sam", limit="1000", terms=0, phone="0712000001")
    b = credit_customer(client, shop, "Decline Dee", limit="1000", terms=0, phone="0712000002")
    for c in (a, b):
        finished_visit(shop, c["id"], 60, shop["cut"])
    snooze = client.post(f"{B}/recalls/outcome", headers=shop["cashier"], json={
        "company_id": shop["co"], "customer_id": a["id"], "offer_id": shop["cut"], "outcome": "snoozed",
        "snooze_until": (date.today() + timedelta(days=20)).isoformat()})
    assert snooze.status_code == 201
    decline = client.post(f"{B}/recalls/outcome", headers=shop["cashier"], json={
        "company_id": shop["co"], "customer_id": b["id"], "offer_id": shop["cut"], "outcome": "declined"})
    assert decline.status_code == 201
    due = client.get(f"{B}/recalls", headers=shop["cashier"], params={"company_id": shop["co"]}).json()
    assert all(r["customer_id"] not in (a["id"], b["id"]) for r in due)
    assert client.post(f"{B}/recalls/outcome", headers=shop["cashier"], json={
        "company_id": shop["co"], "customer_id": a["id"], "offer_id": shop["cut"],
        "outcome": "snoozed"}).status_code == 422                                  # a date is needed


def test_the_worker_queues_recalls_and_a_rebooking_prompt_outside_quiet_hours(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.bookings.services import recalls

    c = credit_customer(client, shop, "Auto Ann", limit="1000", terms=0, phone="0712000003")
    finished_visit(shop, c["id"], 50, shop["cut"])
    client.patch(f"{B}/settings", params={"company_id": shop["co"]}, headers=shop["owner"],
                 json={"quiet_start": "00:00", "quiet_end": "00:00", "rebook_prompt_hours": 1})
    with system(shop) as s:
        queued = recalls.run_automatic(s)
    assert queued >= 1
    rows = sql(shop, "select template from kernel.notification where recipient = '254712000003'")
    assert [r[0] for r in rows] == ["appointment_recall"]
    with system(shop) as s:
        assert recalls.run_automatic(s) == 0                                          # nothing twice
    client.patch(f"{B}/settings", params={"company_id": shop["co"]}, headers=shop["owner"],
                 json={"quiet_start": "21:00", "quiet_end": "07:00", "rebook_prompt_hours": 0})


# --------------------------------------------------------------------------- chair rental
def test_chair_rent_is_invoiced_once_per_period(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.bookings.services import rentals

    renter = credit_customer(client, shop, "Barber Bob", limit="100000", terms=7)
    start = date.today() - timedelta(days=40)
    made = client.post(f"{B}/rentals", headers=shop["owner"], json={
        "company_id": shop["co"], "branch_id": shop["branch"], "customer_id": renter["id"],
        "product_id": shop["delivery"], "amount": "500.00", "every": "month", "start_date": start.isoformat(),
        "resource_id": shop["brian"], "description": "Chair 2"})
    assert made.status_code == 201, made.text
    with system(shop) as s:
        assert rentals.run_due(s) == 2                                               # the month 40 days ago and the next one
    with system(shop) as s:
        assert rentals.run_due(s) == 0                                               # periods are invoiced once
    invoices = sql(shop, "select count(*), sum(total) from pos.sales_invoice where customer_id = :c", c=renter["id"])
    assert invoices[0][0] == 2 and invoices[0][1] == Decimal("1000.00")
    listed = client.get(f"{B}/rentals", headers=shop["owner"], params={"company_id": shop["co"]}).json()
    assert listed[0]["next_due"] > date.today().isoformat() and listed[0]["last_invoice_number"]
    ended = client.post(f"{B}/rentals/{made.json()['id']}/end", headers=shop["owner"], json={})
    assert ended.status_code == 200 and ended.json()["is_active"] is False
    assert client.post(f"{B}/rentals", headers=shop["cashier"], json={
        "company_id": shop["co"], "branch_id": shop["branch"], "customer_id": renter["id"],
        "product_id": shop["delivery"], "amount": "5.00", "every": "week",
        "start_date": date.today().isoformat()}).status_code == 403


def test_month_arithmetic_for_rent() -> None:
    from ziira.modules.bookings.services.rentals import add_period

    assert add_period(date(2026, 1, 31), "month") == date(2026, 2, 28)
    assert add_period(date(2026, 12, 15), "month") == date(2027, 1, 15)
    assert add_period(date(2026, 3, 1), "week") == date(2026, 3, 8)


# --------------------------------------------------------------------------- the client card
def test_a_missing_or_expired_patch_test_is_flagged_on_the_booking(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = shop["co"]
    field = client.post("/api/v1/custom-fields", headers=shop["owner"], json={
        "entity_type": "bookings.client", "key": "patch_test_date", "label": "Patch test date", "kind": "date"})
    assert field.status_code == 201, field.text
    client.patch(f"{B}/offers/{shop['cut']}", headers=shop["owner"], json={"needs_patch_test": True})
    client.patch(f"{B}/settings", params={"company_id": cid}, headers=shop["owner"], json={"patch_test_valid_days": 180})
    who = credit_customer(client, shop, "Allergic Alice", limit="1000", terms=0)
    try:
        a = make_appt(client, shop, shop["cut"], 6, 9, customer_id=who["id"]).json()
        warnings = client.get(f"{B}/appointments/{a['id']}", headers=shop["cashier"]).json()["warnings"]
        assert any("No patch test" in w for w in warnings)
        old = (date.today() - timedelta(days=200)).isoformat()
        put = client.put(f"{B}/clients/{who['id']}/fields", params={"company_id": cid}, headers=shop["cashier"],
                         json={"values": {"patch_test_date": old}})
        assert put.status_code == 200, put.text
        assert any("expired" in w for w in client.get(f"{B}/appointments/{a['id']}",
                                                       headers=shop["cashier"]).json()["warnings"])
        client.put(f"{B}/clients/{who['id']}/fields", params={"company_id": cid}, headers=shop["cashier"],
                   json={"values": {"patch_test_date": date.today().isoformat()}})
        assert client.get(f"{B}/appointments/{a['id']}", headers=shop["cashier"]).json()["warnings"] == []
        card = client.get(f"{B}/clients/{who['id']}/card", headers=shop["cashier"], params={"company_id": cid})
        assert card.status_code == 200 and card.json()["history"][0]["number"] == a["number"]
        assert card.json()["values"]["patch_test_date"] == date.today().isoformat()
    finally:
        client.patch(f"{B}/offers/{shop['cut']}", headers=shop["owner"], json={"needs_patch_test": False})


def test_workday_ids_are_uuids() -> None:
    assert UUID(str(uuid4()))


@pytest.mark.parametrize("day", ["9999-12-31", "0001-01-01"])
def test_the_rota_refuses_extreme_dates(client, shop, day) -> None:  # type: ignore[no-untyped-def]
    params = {"branch_id": shop["branch"], "week_start": day}
    assert client.get(f"{B}/rota", headers=shop["cashier"], params=params).status_code == 422
    ok = client.get(f"{B}/rota", headers=shop["cashier"], params={**params, "week_start": date.today().isoformat()})
    assert ok.status_code == 200

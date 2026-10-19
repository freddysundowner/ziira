"""The online booking page, settings, and the messages clients get: confirmation, reminders (with quiet hours and
do-not-contact). The page is used without signing in, as a visitor would."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.bookings_helpers import ZONE, B, book, make_salon, when, workday
from tests.stock_helpers import system
from ziira.modules.bookings.services import notify

N = "/api/v1/notifications"
PUB = f"{B}/public/book"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_salon(client, registry, "Online Salon")
    registry.enable(s["tenant_id"], "messaging")
    for channel in ("sms", "email"):
        r = client.put(f"{N}/channels/{channel}", headers=s["owner"], json={
            "company_id": str(s["company_id"]), "provider": "fake", "secret": {"k": "v"}})
        assert r.status_code == 200, r.text
    s["slug"] = "online-salon-" + uuid4().hex[:6]
    return s


def settings(client, shop, **body):  # type: ignore[no-untyped-def]
    return client.patch(f"{B}/settings", params={"company_id": str(shop["company_id"])}, headers=shop["owner"], json=body)


def sql(shop, stmt: str, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def day_of(n: int) -> str:
    return workday(n).isoformat()


def request(shop, n: int, hour: int, *, phone: str, name: str = "Visitor", **extra):  # type: ignore[no-untyped-def]
    return {"service_id": shop["cut"], "start": when(n, hour), "name": name, "phone": phone, "consent": True, **extra}


def visit(client, shop, n: int, hour: int, key: str | None = None, **kw):  # type: ignore[no-untyped-def]
    return client.post(f"{PUB}/{shop['slug']}/appointments", json=request(shop, n, hour, **kw),
                       headers={"Idempotency-Key": key or uuid4().hex})


# --------------------------------------------------------------------------- settings
def test_settings_have_defaults_and_online_booking_needs_an_address(client, shop) -> None:  # type: ignore[no-untyped-def]
    got = client.get(f"{B}/settings", params={"company_id": str(shop["company_id"])}, headers=shop["manager"]).json()
    assert (got["online_enabled"], got["min_notice_minutes"], got["max_days_ahead"], got["cancel_window_hours"]) == (False, 120, 60, 24)
    assert got["slot_granularity_minutes"] == 15 and got["slug"] is None and got["invoicing_available"] is True
    no_address = settings(client, shop, online_enabled=True)
    assert no_address.status_code == 422 and "address" in no_address.json()["message"]
    assert settings(client, shop, slug="api").status_code == 422                    # kept back
    assert settings(client, shop, slug="No Spaces!").status_code == 422
    assert settings(client, shop, slot_granularity_minutes=7).status_code == 422
    ok = settings(client, shop, slug=shop["slug"], online_enabled=True, min_notice_minutes=60)
    assert ok.status_code == 200 and ok.json()["slug"] == shop["slug"] and ok.json()["min_notice_minutes"] == 60
    assert client.patch(f"{B}/settings", params={"company_id": str(shop["company_id"])}, headers=shop["cashier"],
                        json={"auto_confirm": True}).status_code == 403              # set-up is for managers


def test_an_address_belongs_to_one_business(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    other = make_salon(client, registry, "Rival Salon")
    taken = client.patch(f"{B}/settings", params={"company_id": str(other["company_id"])}, headers=other["owner"],
                         json={"slug": shop["slug"]})
    assert taken.status_code == 409


# --------------------------------------------------------------------------- the public page
def test_a_closed_or_unknown_page_says_so_and_reveals_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.get(f"{PUB}/no-such-business").status_code == 404
    settings(client, shop, online_enabled=False)
    closed = client.get(f"{PUB}/{shop['slug']}")
    assert closed.status_code == 404 and closed.json()["message"] == client.get(f"{PUB}/no-such-business").json()["message"]
    settings(client, shop, online_enabled=True)


def test_the_page_shows_services_and_only_the_people_the_business_chose(client, shop) -> None:  # type: ignore[no-untyped-def]
    page = client.get(f"{PUB}/{shop['slug']}")
    assert page.status_code == 200, page.text
    body = page.json()
    assert [s["name"] for s in body["services"]] == ["Product DELIVERY"] and body["services"][0]["duration_minutes"] == 60
    assert body["resources"] == [] and body["services"][0]["resource_ids"] == []            # people are hidden by default
    assert body["timezone"] == "Africa/Nairobi" and "agree" in body["consent_text"].lower()
    settings(client, shop, show_resources_publicly=True)
    shown = client.get(f"{PUB}/{shop['slug']}").json()
    assert sorted(r["name"] for r in shown["resources"]) == ["Anna", "Brian"]
    settings(client, shop, show_resources_publicly=False)
    assert "company_id" not in str(page.json()) and "tenant" not in str(page.json())


def test_only_free_times_are_offered_and_nothing_says_who_is_booked(client, shop) -> None:  # type: ignore[no-untyped-def]
    url = f"{PUB}/{shop['slug']}/slots"
    got = client.get(url, params={"service": shop["cut"], "date": day_of(3)})
    assert got.status_code == 200 and got.json()[0]["start"].endswith("+03:00") and set(got.json()[0]) == {"start", "end"}
    starts = [s["start"][11:16] for s in got.json()]
    assert "09:00" in starts and "16:00" in starts and "16:15" not in starts
    assert client.get(url, params={"service": shop["cut"], "date": "2020-01-01"}).json() == []         # the past
    assert client.get(url, params={"service": shop["cut"], "date": "2031-01-01"}).json() == []         # too far ahead
    assert client.get(url, params={"service": str(uuid4()), "date": day_of(3)}).status_code == 404
    both = [book(client, shop, 3, 9, resource_ids=[shop[c]]) for c in ("anna", "brian")]
    assert all(b.status_code == 201 for b in both)
    after = [s["start"][11:16] for s in client.get(url, params={"service": shop["cut"], "date": day_of(3)}).json()]
    assert "09:00" not in after and "10:15" in after


def test_a_visitor_books_and_becomes_a_customer(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = visit(client, shop, 4, 9, phone="0722000111", name="Neema Visitor", email="neema@example.test")
    assert r.status_code == 201, r.text
    done = r.json()
    assert done["status"] == "requested" and done["number"].startswith("APT-") and done["service"] == "Product DELIVERY"
    assert "Neema" not in str(client.get(f"{PUB}/{shop['slug']}").json())
    appt = sql(shop, "select source, status, customer_id, client_name, consent_given_at from bookings.appointment "
                     "where number = :n", n=done["number"])[0]
    assert appt[:2] == ("online", "requested") and appt[2] is not None and appt[4] is not None
    customer = sql(shop, "select name, phone, email from crm.customer where id = :i", i=appt[2])[0]
    assert customer == ("Neema Visitor", "254722000111", "neema@example.test")
    again = visit(client, shop, 5, 9, phone="0722 000 111", name="Neema V.")                   # the same person
    assert again.status_code == 201
    assert sql(shop, "select count(*) from crm.customer where phone = '254722000111'")[0][0] == 1


def test_the_owner_confirms_a_request_or_the_business_confirms_everything(client, shop) -> None:  # type: ignore[no-untyped-def]
    number = visit(client, shop, 6, 9, phone="0722000222").json()["number"]
    asked = client.get(f"{B}/appointments", headers=shop["cashier"], params={"search": number}).json()[0]
    assert asked["status"] == "requested"
    confirmed = client.post(f"{B}/appointments/{asked['id']}/confirm", headers=shop["cashier"])
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    settings(client, shop, auto_confirm=True)
    assert visit(client, shop, 6, 11, phone="0722000333").json()["status"] == "confirmed"
    settings(client, shop, auto_confirm=False)


def test_a_retry_with_the_same_key_books_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    key = uuid4().hex
    a = visit(client, shop, 7, 9, key=key, phone="0722000444")
    b = visit(client, shop, 7, 9, key=key, phone="0722000444")
    assert a.status_code == b.status_code == 201 and a.json() == b.json()
    assert sql(shop, "select count(*) from bookings.appointment where number = :n", n=a.json()["number"])[0][0] == 1
    different = visit(client, shop, 7, 11, key=key, phone="0722000444")
    assert different.status_code == 422                                                    # same key, other request


def test_consent_and_a_way_to_reach_the_visitor_are_needed(client, shop) -> None:  # type: ignore[no-untyped-def]
    no_consent = client.post(f"{PUB}/{shop['slug']}/appointments", json={**request(shop, 8, 9, phone="0722000555"), "consent": False})
    assert no_consent.status_code == 422 and "agree" in no_consent.json()["message"].lower()
    no_contact = client.post(f"{PUB}/{shop['slug']}/appointments", json={**request(shop, 8, 9, phone="0722000555"), "phone": None})
    assert no_contact.status_code == 422


def test_a_robot_that_fills_the_hidden_field_gets_a_success_and_nothing_is_kept(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = sql(shop, "select count(*) from bookings.appointment")[0][0]
    r = visit(client, shop, 8, 9, phone="0722000666", website="http://spam.example")
    assert r.status_code == 201 and r.json()["number"] is None
    assert sql(shop, "select count(*) from bookings.appointment")[0][0] == before
    assert sql(shop, "select count(*) from crm.customer where phone = '254722000666'")[0][0] == 0


def test_a_time_taken_a_moment_ago_and_times_outside_the_rules_are_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    for chair in ("anna", "brian"):
        assert book(client, shop, 9, 10, resource_ids=[shop[chair]]).status_code == 201
    taken = visit(client, shop, 9, 10, phone="0722000777")
    assert taken.status_code == 409 and "just taken" in taken.json()["message"]
    night = visit(client, shop, 9, 3, phone="0722000778")
    assert night.status_code == 422                                                         # outside working hours
    soon = client.post(f"{PUB}/{shop['slug']}/appointments", json={
        **request(shop, 9, 9, phone="0722000779"), "start": (datetime.now(ZONE) + timedelta(minutes=10)).isoformat()},
        headers={"Idempotency-Key": uuid4().hex})
    assert soon.status_code in (409, 422)
    far = client.post(f"{PUB}/{shop['slug']}/appointments", json={**request(shop, 9, 9, phone="0722000780"), "start": "2031-01-07T09:00:00+03:00"},
                      headers={"Idempotency-Key": uuid4().hex})
    assert far.status_code == 422


def test_guessing_is_slowed_down_per_phone(client, shop) -> None:  # type: ignore[no-untyped-def]
    codes = [visit(client, shop, 12, 9 + (i % 6), phone="0722000999").status_code for i in range(8)]
    assert 429 in codes and codes[0] == 201


# --------------------------------------------------------------------------- messages
def test_a_confirmation_is_queued_through_the_notification_layer(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = book(client, shop, 13, 9, client_name="Zawadi", client_phone="0711222333", client_email="zawadi@example.test")
    assert made.status_code == 201
    rows = sql(shop, "select channel, recipient, template, status from kernel.notification where ref_id = :a",
               a=made.json()["id"])
    assert rows and rows[0][2] == "appointment_confirmation" and rows[0][1] == "254711222333"
    walk = client.post(f"{B}/appointments/walk-in", headers=shop["owner"], json={"offer_id": shop["cut"], "client_name": "Walker", "client_phone": "0711222444"})
    assert sql(shop, "select count(*) from kernel.notification where ref_id = :a", a=walk.json()["id"])[0][0] == 0


def test_a_client_who_asked_not_to_be_messaged_is_skipped(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{N}/opt-outs", headers=shop["owner"], json={"company_id": str(shop["company_id"]), "recipient": "0711555666"})
    assert r.status_code in (200, 201), r.text
    made = book(client, shop, 14, 9, client_name="Quiet", client_phone="0711555666")
    rows = sql(shop, "select status from kernel.notification where ref_id = :a", a=made.json()["id"])
    assert rows == [("skipped",)]


def test_reminders_go_once_inside_the_lead_time_and_wait_out_quiet_hours(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = book(client, shop, 15, 14, client_name="Reminded", client_phone="0711888999").json()
    start = datetime.fromisoformat(made["starts_at"])

    def run(at: datetime) -> int:
        with system(shop) as s:
            return notify.send_due_reminders(s, at=at)

    def reminders() -> int:
        return sql(shop, "select count(*) from kernel.notification where ref_id = :a and template = 'appointment_reminder'",
                   a=made["id"])[0][0]

    run(start - timedelta(days=3))
    assert reminders() == 0                                                                 # not yet within 24 hours
    run(start - timedelta(hours=15))
    assert reminders() == 0                                                                 # 23:00 where the business is: quiet
    run(start - timedelta(hours=3))
    assert reminders() == 1
    run(start - timedelta(hours=2))
    assert reminders() == 1                                                                 # once per appointment
    run(start + timedelta(minutes=5))
    assert reminders() == 1                                                                 # never after the start
    settings(client, shop, reminders_enabled=False)
    other = book(client, shop, 16, 14, client_name="No reminder", client_phone="0711777888").json()
    run(datetime.fromisoformat(other["starts_at"]) - timedelta(hours=3))
    assert sql(shop, "select count(*) from kernel.notification where ref_id = :a and template = 'appointment_reminder'",
               a=other["id"])[0][0] == 0
    settings(client, shop, reminders_enabled=True)


def test_moving_an_appointment_tells_the_client_again_and_allows_a_new_reminder(client, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.bookings_helpers import reason

    made = book(client, shop, 17, 14, client_name="Mover", client_phone="0711999000").json()
    moved = client.post(f"{B}/appointments/{made['id']}/reschedule", headers=shop["owner"], json={
        "starts_at": when(17, 15), "reason_code_id": reason(client, shop, "appointment_reschedule", "CLIENT")})
    assert moved.status_code == 200
    n = sql(shop, "select count(*) from kernel.notification where ref_id = :a and template = 'appointment_confirmation'", a=made["id"])[0][0]
    assert n == 2
    gone = client.post(f"{B}/appointments/{made['id']}/cancel", headers=shop["owner"], json={
        "reason_code_id": reason(client, shop, "appointment_cancel", "BUSINESS")})
    assert gone.status_code == 200
    assert sql(shop, "select count(*) from kernel.notification where ref_id = :a and template = 'appointment_cancelled'", a=made["id"])[0][0] == 1

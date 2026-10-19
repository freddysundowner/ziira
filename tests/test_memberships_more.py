"""Memberships beyond the basics: events, reminders, personal data, custom fields, concurrency and the integrity check."""

import threading
from datetime import date, datetime, timedelta
from decimal import Decimal as D  # noqa: N817
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from tests.memberships_helpers import M, cancel_reason, customer, make_member_shop, rows, run_billing, scalar, sign_up
from tests.stock_helpers import system
from ziira.modules.memberships import public as memberships
from ziira.modules.memberships.services import reminders
from ziira.sdk import Subject, company_setting


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_member_shop(client, registry, "Members More Co")
    client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"], json={"timezone": "UTC"})
    return s


def events(shop, kind: str, aggregate: str | None = None) -> list[Any]:  # type: ignore[no-untyped-def]
    sql = "select payload from kernel.event_outbox where event_type = :k"
    if aggregate:
        return rows(shop, sql + " and aggregate_id = :a", k=kind, a=aggregate)
    return rows(shop, sql, k=kind)


# --------------------------------------------------------------------------- events
def test_each_step_of_a_membership_and_a_package_publishes_its_event(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Events Eve")
    m = sign_up(client, shop, cust, date(2026, 5, 1)).json()
    assert len(events(shop, "membership.activated", m["id"])) == 1
    run_billing(shop, date(2026, 6, 2))
    assert len(events(shop, "membership.renewed", m["id"])) == 1
    client.post(f"{M}/members/{m['id']}/pause", headers=shop["owner"], json={})
    client.post(f"{M}/members/{m['id']}/resume", headers=shop["owner"], json={})
    assert len(events(shop, "membership.paused", m["id"])) == 1 and len(events(shop, "membership.resumed", m["id"])) == 1
    client.post(f"{M}/members/{m['id']}/cancel", headers=shop["owner"], json={
        "reason_code_id": cancel_reason(client, shop), "at_period_end": False})
    cancelled = events(shop, "membership.cancelled", m["id"])
    assert len(cancelled) == 1 and cancelled[0].payload["customer_id"] == cust["id"]
    ended = sign_up(client, shop, customer(client, shop, "Ends Ed"), date(2026, 1, 1), end_date="2026-01-20").json()
    run_billing(shop, date(2026, 2, 5))
    assert len(events(shop, "membership.expired", ended["id"])) == 1
    p = client.post(f"{M}/sold-packages", headers=shop["owner"], json={
        "package_id": shop["package"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "purchased_on": date.today().isoformat()}).json()
    assert len(events(shop, "package.sold", p["id"])) == 1
    with system(shop) as s:
        memberships.consume_credit(s, customer_id=UUID(cust["id"]), service_ref="massage", quantity=D(1),
                                   source_type="booking", source_id=uuid4())
    used = events(shop, "package.used", p["id"])
    assert len(used) == 1 and D(used[0].payload["balance"]) == 9
    run_billing(shop, date.today() + timedelta(days=100))
    assert len(events(shop, "package.expired", p["id"])) == 1


# --------------------------------------------------------------------------- reminders
@pytest.fixture
def messages(monkeypatch):  # type: ignore[no-untyped-def]
    sent: list[dict[str, Any]] = []

    def fake(session, **kw):  # type: ignore[no-untyped-def]
        sent.append(kw)
        return uuid4()

    monkeypatch.setattr(reminders, "send_templated", fake)
    monkeypatch.setattr(reminders, "_route", lambda session, company_id, customer: [("sms", customer.phone or "0")])
    return sent


def at(shop, day: date, hour: int) -> datetime:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        zone = ZoneInfo(str(company_setting(s, shop["company_id"], "timezone")))
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=zone)


def send(shop, day: date, hour: int) -> dict[str, int]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return reminders.send_due(s, UUID(str(shop["company_id"])), at(shop, day, hour))


def test_a_renewal_reminder_is_queued_once_in_the_chosen_language(client, shop, messages) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    cust = customer(client, shop, "Remind Rhoda", phone="0712000111")
    m = sign_up(client, shop, cust, date(2026, 8, 20)).json()                   # renews 20 Sep
    assert send(shop, date(2026, 9, 5), 10) == {"renewals": 0, "packages": 0}           # 15 days away: too early
    assert [x for x in messages if x["ref_id"] == UUID(m["id"])] == []
    assert send(shop, date(2026, 9, 14), 10)["renewals"] == 1                            # 6 days away
    mine = [x for x in messages if x["ref_id"] == UUID(m["id"])]
    assert len(mine) == 1 and mine[0]["template"] == "membership_renewal" and mine[0]["language"] == "en"
    cur = scalar(shop, "select base_currency from kernel.company")
    assert mine[0]["variables"] == {"customer": "Remind Rhoda", "plan": "Gold", "amount": f"{cur} 100.00",
                                    "business": "Members More Co Ltd", "date": "20 Sep 2026"}
    assert mine[0]["dedupe_key"] == f"memberships:renewal:{m['id']}:2026-09-20"
    assert send(shop, date(2026, 9, 14), 11)["renewals"] == 0                            # the same renewal, once
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"message_language": "sw"})
    other = sign_up(client, shop, customer(client, shop, "Remind Rita", phone="0712000222"), date(2026, 8, 20)).json()
    send(shop, date(2026, 9, 14), 10)
    assert [x["language"] for x in messages if x["ref_id"] == UUID(other["id"])] == ["sw"]
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"message_language": "en"})


def test_no_reminder_in_quiet_hours_or_for_a_member_who_is_leaving(client, shop, messages) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Quiet Quentin", phone="0712000333")
    m = sign_up(client, shop, cust, date(2026, 8, 20)).json()
    assert send(shop, date(2026, 9, 14), 23) == {"renewals": 0, "packages": 0}          # 23:00 is in the quiet hours
    assert send(shop, date(2026, 9, 14), 3) == {"renewals": 0, "packages": 0}           # and so is 03:00
    assert [x for x in messages if x["ref_id"] == UUID(m["id"])] == []
    client.post(f"{M}/members/{m['id']}/cancel", headers=shop["owner"], json={"reason_code_id": cancel_reason(client, shop)})
    assert send(shop, date(2026, 9, 14), 10)["renewals"] == 0                            # cancelling: no reminder
    assert [x for x in messages if x["ref_id"] == UUID(m["id"])] == []


def test_a_package_expiring_soon_is_announced_and_reminded_once(client, shop, messages) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Expire Edna", phone="0712000444")
    p = client.post(f"{M}/sold-packages", headers=shop["owner"], json={
        "package_id": shop["package"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "purchased_on": "2026-07-01", "invoice": False}).json()                         # expires 29 Sep
    assert send(shop, date(2026, 9, 1), 10)["packages"] == 0                             # 28 days away
    assert send(shop, date(2026, 9, 20), 10)["packages"] == 1
    mine = [x for x in messages if x["ref_id"] == UUID(p["id"])]
    assert len(mine) == 1 and mine[0]["template"] == "package_expiring"
    assert mine[0]["variables"]["credits"] == "10.00" and mine[0]["variables"]["date"] == "29 Sep 2026"
    assert send(shop, date(2026, 9, 21), 10)["packages"] == 0
    assert len(events(shop, "package.expiring", p["id"])) == 1


def test_switching_reminders_off_still_announces_expiring_packages_to_other_units(client, shop, messages) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"reminders_enabled": False})
    cust = customer(client, shop, "Silent Sid", phone="0712000555")
    p = client.post(f"{M}/sold-packages", headers=shop["owner"], json={
        "package_id": shop["package"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "purchased_on": "2026-07-01", "invoice": False}).json()
    m = sign_up(client, shop, cust, date(2026, 8, 20)).json()
    assert send(shop, date(2026, 9, 20), 10) == {"renewals": 0, "packages": 0}
    assert not [x for x in messages if x["ref_id"] in (UUID(p["id"]), UUID(m["id"]))]
    assert len(events(shop, "package.expiring", p["id"])) == 1
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"reminders_enabled": True})


def test_reminders_really_queue_through_the_notification_layer_and_respect_do_not_contact(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"phone_country_code": "254"})
    cust = customer(client, shop, "Queued Quinn", phone="0712000666")
    m = sign_up(client, shop, cust, date(2026, 8, 20)).json()
    refused = customer(client, shop, "Refuser Rob", phone="0712000777")
    r = sign_up(client, shop, refused, date(2026, 8, 20)).json()
    client.post(f"/api/v1/crm/customers/{refused['id']}/do-not-contact", headers=shop["owner"], json={})
    with system(shop) as s:
        original = reminders._route
        reminders._route = lambda session, company_id, c: [("sms", c.phone or "")]      # type: ignore[assignment]
        try:
            reminders.send_due(s, UUID(co), at(shop, date(2026, 9, 14), 10))
        finally:
            reminders._route = original                                                   # type: ignore[assignment]
    queued = rows(shop, "select status, body, template from kernel.notification where ref_id = :i", i=m["id"])
    assert len(queued) == 1 and queued[0].status == "queued" and "Gold" in queued[0].body
    skipped = rows(shop, "select status from kernel.notification where ref_id = :i", i=r["id"])
    assert [x.status for x in skipped] == ["skipped"]


# --------------------------------------------------------------------------- personal data
def test_notes_are_found_exported_and_erased_without_touching_the_records(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.memberships.privacy import MembershipsPersonalData

    cust = customer(client, shop, "Privacy Pat")
    m = sign_up(client, shop, cust, date(2026, 9, 1), notes="Zainab Mwangi asked for the morning class").json()
    provider, company = MembershipsPersonalData(), UUID(str(shop["company_id"]))
    with system(shop) as s:
        found = provider.find(s, company, Subject(raw="Zainab Mwangi", name="Zainab Mwangi"))
        assert [(f.kind, str(f.record_id)) for f in found] == [("member", m["id"])]
        assert provider.find(s, company, Subject(raw="0712345678", phone="254712345678")) == []
        exported = provider.export(s, found[0])
        assert exported["membership"]["notes"].startswith("Zainab") and exported["history"][0]["action"] == "started"
        outcome = provider.anonymise(s, found[0], "requested")
        assert outcome.status == "anonymised" and outcome.kept
        assert provider.find(s, company, Subject(raw="Zainab Mwangi", name="Zainab Mwangi")) == []
        assert provider.retention(s, company)[0].unit == "memberships"
    assert rows(shop, "select notes from memberships.member where id = :i", i=m["id"])[0].notes is None
    assert client.get(f"{M}/members/{m['id']}", headers=shop["owner"]).status_code == 200      # the record stays


# --------------------------------------------------------------------------- custom fields
def test_a_member_can_carry_a_business_s_own_fields(client, shop) -> None:  # type: ignore[no-untyped-def]
    cf = "/api/v1/custom-fields"
    kinds = {k["entity_type"] for k in client.get(f"{cf}/entities", headers=shop["owner"]).json()}
    assert "memberships.member" in kinds
    made = client.post(cf, headers=shop["owner"], json={"entity_type": "memberships.member", "key": "locker",
                                                        "label": "Locker number", "kind": "text"})
    assert made.status_code == 201, made.text
    m = sign_up(client, shop, customer(client, shop, "Locker Lou"), date(2026, 9, 1)).json()
    url = f"{cf}/values/memberships.member/{m['id']}"
    assert client.put(url, headers=shop["rep"], json={"values": {"locker": "A12"}}).status_code == 200
    assert client.get(url, headers=shop["cashier"]).json()["values"] == {"locker": "A12"}
    assert client.put(url, headers=shop["cashier"], json={"values": {"locker": "B1"}}).status_code == 403   # may look only


# --------------------------------------------------------------------------- concurrency and integrity
def test_two_requests_spending_for_one_source_spend_the_credits_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Race Rhys")
    m = sign_up(client, shop, cust, date(2026, 10, 1)).json()
    source = str(uuid4())
    answers: list[int] = []

    def spend() -> None:
        r = client.post(f"{M}/credits/consume", headers=shop["owner"], json={
            "customer_id": cust["id"], "quantity": "2", "source_id": source})
        answers.append(r.status_code)

    threads = [threading.Thread(target=spend) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert answers == [200, 200]
    assert D(client.get(f"{M}/members/{m['id']}", headers=shop["owner"]).json()["balance"]) == 2     # 4 - 2, once
    assert scalar(shop, "select count(*) from memberships.credit_entry where entry_type = 'use' and holder_id = :h",
                  h=m["id"]) == 1


def test_the_integrity_check_finds_a_balance_below_zero_only_when_overdraw_is_off(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.memberships.hooks import CreditBalanceCheck

    cust = customer(client, shop, "Negative Nat")
    m = sign_up(client, shop, cust, date(2026, 10, 1)).json()
    with system(shop) as s:
        s.execute(text(
            "insert into memberships.credit_entry (tenant_id, company_id, customer_id, holder_type, holder_id, "
            "entry_type, quantity, business_date) values (kernel.current_tenant(), :c, :u, 'membership', :h, "
            "'adjustment', -9, current_date)"), {"c": str(shop["company_id"]), "u": cust["id"], "h": m["id"]})
        problems = CreditBalanceCheck().run(s)
    assert any(m["id"] in p for p in problems)


def test_a_failure_in_one_item_is_flagged_and_the_others_still_run(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.memberships.services import members

    a = sign_up(client, shop, customer(client, shop, "Boom Bea"), date(2026, 1, 1)).json()
    b = sign_up(client, shop, customer(client, shop, "Fine Finn"), date(2026, 1, 1)).json()
    real = members.process_member

    def flaky(session, member_id, today=None):  # type: ignore[no-untyped-def]
        if str(member_id) == a["id"]:
            raise RuntimeError("boom")
        return real(session, member_id, today)

    monkeypatch.setattr(members, "process_member", flaky)
    run_billing(shop, date(2026, 2, 3))
    assert client.get(f"{M}/members/{b['id']}", headers=shop["owner"]).json()["next_renewal_date"] == "2026-03-01"
    assert client.get(f"{M}/members/{a['id']}", headers=shop["owner"]).json()["next_renewal_date"] == "2026-02-01"
    flagged = rows(shop, "select message from kernel.exception_item where unit_name = 'memberships' "
                         "and kind = 'task_failed' and message like :m", m=f"%{a['number']}%")
    assert flagged


def test_the_daily_task_runs_for_each_company_in_its_own_date(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import jobs as kernel_jobs

    cust = customer(client, shop, "Hourly Hal")
    m = sign_up(client, shop, cust, (date.today() - timedelta(days=40))).json()
    assert m["next_renewal_date"] < date.today().isoformat()
    kernel_jobs.run_periodic(shop["tenant_id"], only="memberships.run_billing", force=True)
    assert client.get(f"{M}/members/{m['id']}", headers=shop["owner"]).json()["next_renewal_date"] > date.today().isoformat()


# --------------------------------------------------------------------------- scope and plans without a service item
def test_a_branch_level_grant_reaches_only_that_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    juja = str(shop["juja"])
    here = sign_up(client, shop, customer(client, shop, "Head Office Hal"), date(2026, 10, 1)).json()
    there = sign_up(client, shop, customer(client, shop, "Juja Jo"), date(2026, 10, 1), branch_id=juja).json()
    assert there["branch_id"] == juja
    refused = sign_up(client, shop, customer(client, shop, "Wrong Branch"), date(2026, 10, 1), who="rep", branch_id=juja)
    assert refused.status_code == 403                                      # the rep works at head office only
    listed = {m["id"] for m in client.get(f"{M}/members", headers=shop["rep"], params={"limit": 200}).json()}
    assert here["id"] in listed and there["id"] not in listed
    assert client.get(f"{M}/members/{there['id']}", headers=shop["rep"]).status_code == 404
    assert client.post(f"{M}/members/{there['id']}/pause", headers=shop["rep"], json={}).status_code in (403, 404)
    everyone = {m["id"] for m in client.get(f"{M}/members", headers=shop["owner"], params={"limit": 200}).json()}
    assert {here["id"], there["id"]} <= everyone


def test_a_plan_with_no_service_item_cannot_be_invoiced_from_here_but_still_works(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = client.post(f"{M}/plans", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": "FREE", "name": "Walk-in club", "fee": "40.00",
        "credits_per_period": "1"}).json()
    cust = customer(client, shop, "Club Cleo")
    insisting = sign_up(client, shop, cust, date(2026, 10, 1), plan_id=plan["id"], auto_invoice=True)
    assert insisting.status_code == 422 and "service item" in insisting.text.lower()
    m = sign_up(client, shop, cust, date(2026, 10, 1), plan_id=plan["id"]).json()
    assert m["auto_invoice"] is False and D(m["balance"]) == 1
    run_billing(shop, date(2026, 11, 3))                                    # renews without an invoice
    again = client.get(f"{M}/members/{m['id']}", headers=shop["owner"]).json()
    assert again["next_renewal_date"] == "2026-12-01"
    assert client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m["id"]}).json() == []

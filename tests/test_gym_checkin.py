"""Gyms and studios, part 3: check-in. One decision for the desk, the scanner, the card, the kiosk and a door controller;
overrides with a reason; visit packs; two desks at once; an offline desk; the access-decision API with an API key."""

import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.gym_helpers import M, age_invoice, customer, gym_plan, make_gym_shop, refresh, rows, scalar, today
from tests.stock_helpers import system

CI = f"{M}/checkin"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_gym_shop(client, registry, "Gym Door Co")
    co = str(s["company_id"])
    client.patch(f"{M}/settings", headers=s["owner"], params={"company_id": co}, json={"repeat_window_minutes": 0})
    s["visits"] = client.post(f"{M}/packages", headers=s["owner"], json={
        "company_id": co, "code": "VISITS5", "name": "5 visits", "credits": "5", "price": "50.00", "expiry_days": 60,
        "covered_services": ["gym"], "product_id": s["delivery"]}).json()
    return s


def member_with(client, shop, name: str, plan_id: str | None = None, **extra):  # type: ignore[no-untyped-def]
    cust = customer(client, shop, name)
    r = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan_id or shop["plan"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        **extra})
    assert r.status_code == 201, r.text
    p = client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"]).json()
    return cust, r.json(), p


def enter(client, shop, who: str = "desk", **body):  # type: ignore[no-untyped-def]
    payload = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "method": "desk", **body}
    return client.post(CI, headers=shop[who], json=payload)


def codes(res: dict) -> list[str]:  # type: ignore[type-arg]
    return [r["code"] for r in res["reasons"]]


def test_a_member_is_let_in_by_number_qr_card_or_the_desk_pick(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m, p = member_with(client, shop, "Door Dee")
    client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={"card_number": "WB-0001"})
    a = enter(client, shop, identifier=p["number"], method="scan")
    assert a.status_code == 200, a.text
    body = a.json()
    assert body["outcome"] == "allow" and body["allowed"] and body["person"]["name"] == "Door Dee"
    assert body["person"]["number"] == p["number"] and body["entitlement"].startswith("Gold")
    assert body["checkin_id"] and body["duplicate"] is False
    for variant in ({"identifier": f"ZM:{p['number']}", "method": "scan"}, {"identifier": "wb-0001", "method": "card"},
                    {"customer_id": cust["id"]}):
        r = enter(client, shop, **variant).json()
        assert r["outcome"] == "allow" and r["person"]["customer_id"] == cust["id"], variant
    assert scalar(shop, "select count(*) from memberships.checkin where customer_id = :c and counted",
                  c=cust["id"]) == 1                                                    # one visit a day, however often
    last = client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"]).json()
    assert last["last_visit_on"] == today().isoformat()


def test_an_unknown_number_is_refused_and_leaves_no_record(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = scalar(shop, "select count(*) from memberships.checkin")
    r = enter(client, shop, identifier="NOPE-999").json()
    assert r["outcome"] == "deny" and r["code"] == "not_found" and r["person"] is None and r["checkin_id"] is None
    assert scalar(shop, "select count(*) from memberships.checkin") == before
    assert enter(client, shop, who="cashier").status_code == 200            # a cashier is also a desk
    nobody = client.post(CI, json={"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"])})
    assert nobody.status_code in (401, 403)


def test_the_desk_finds_people_by_name_phone_number_or_card(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"phone_country_code": "254"})
    cust = customer(client, shop, "Search Sade", phone="0733555666")
    client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": shop["plan"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])})
    num = client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"]).json()["number"]
    for q in ("Sade", "0733555666", num, num.lower()):
        found = client.get(f"{CI}/search", headers=shop["desk"], params={"company_id": co, "q": q}).json()
        assert [x["name"] for x in found] == ["Search Sade"], q
        assert found[0]["plan_name"] == "Gold" and found[0]["membership_status"] == "active"


def test_every_kind_of_refusal_has_its_own_plain_reason(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m, p = member_with(client, shop, "Hold Hal")
    client.post(f"{M}/members/{m['id']}/pause", headers=shop["rep"], json={"frozen": True, "note": "Review"})
    r = enter(client, shop, identifier=p["number"]).json()
    assert r["outcome"] == "deny" and r["code"] == "frozen" and r["can_override"] is False      # a desk may not override
    boss = enter(client, shop, who="boss", identifier=p["number"]).json()
    assert boss["can_override"] is True
    cust2, m2, p2 = member_with(client, shop, "Gone Gus")
    client.post(f"{M}/members/{m2['id']}/cancel", headers=shop["rep"], json={
        "reason_code_id": [x["id"] for x in client.get("/api/v1/settings/reason-codes", headers=shop["owner"]).json()
                           if x["category"] == "membership_cancel"][0], "at_period_end": False})
    assert enter(client, shop, identifier=p2["number"]).json()["code"] == "ended"
    cust3 = customer(client, shop, "Nothing Nell")
    nothing = enter(client, shop, customer_id=cust3["id"]).json()
    assert nothing["outcome"] == "deny" and nothing["code"] == "no_membership"
    client.post(f"{M}/profiles/by-customer/{cust['id']}/block", headers=shop["rep"], json={"blocked": False})
    cust4, m4, p4 = member_with(client, shop, "Blocked Bo")
    client.post(f"{M}/profiles/by-customer/{cust4['id']}/block", headers=shop["rep"], json={
        "blocked": True, "reason": "Fighting"})
    b = enter(client, shop, identifier=p4["number"]).json()
    assert b["code"] == "blocked" and "Fighting" in b["message"]


def test_staff_let_a_refused_person_in_only_with_a_reason_and_the_right(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m, p = member_with(client, shop, "Override Ola")
    client.post(f"{M}/members/{m['id']}/pause", headers=shop["rep"], json={"frozen": True})
    denied = enter(client, shop, identifier=p["number"]).json()
    assert denied["outcome"] == "deny" and denied["checkin_id"]
    no_right = enter(client, shop, who="desk", identifier=p["number"], override_reason="Friend of the owner")
    assert no_right.status_code == 403
    no_reason = enter(client, shop, who="boss", identifier=p["number"], override_reason="  ")
    assert no_reason.status_code == 422
    ok = enter(client, shop, who="boss", identifier=p["number"], override_reason="Owner said so").json()
    assert ok["allowed"] is True and ok["overridden"] is True and ok["outcome"] == "deny" and ok["can_override"] is False
    row = rows(shop, "select overridden, override_reason, decision, counted from memberships.checkin "
                     "where id = :i", i=ok["checkin_id"])[0]
    assert row.overridden and row.override_reason == "Owner said so" and row.decision == "deny" and row.counted
    assert rows(shop, "select 1 from kernel.audit_log where action = 'override' and entity_id = :i", i=ok["checkin_id"])
    # the record of what happened is never edited
    with pytest.raises(Exception, match="immutable|cannot|not allowed|forbid"), system(shop) as s:
        s.execute(text("update memberships.checkin set decision = 'allow' where id = :i"), {"i": ok["checkin_id"]})


def test_late_payment_warns_in_the_grace_days_and_refuses_after(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m, p = member_with(client, shop, "Late Lena")
    inv = client.get(f"{M}/members/{m['id']}/dues", headers=shop["owner"]).json()[0]["invoice_number"]
    age_invoice(shop, inv, 3)
    refresh(shop)
    warn = enter(client, shop, identifier=p["number"]).json()
    assert warn["outcome"] == "warn" and warn["allowed"] and "payment_late" in codes(warn)
    assert D(warn["person"]["owed"]) == D("100.00")
    age_invoice(shop, inv, 20)
    refresh(shop)
    deny = enter(client, shop, identifier=p["number"]).json()
    assert deny["outcome"] == "deny" and deny["code"] == "payment_overdue"
    client.post(f"{M}/members/{m['id']}/payments", headers=shop["owner"], json={"amount": "100.00",
                                                                               "method": "mobile_money"})
    assert enter(client, shop, identifier=p["number"]).json()["outcome"] == "allow"          # paid: in at once


def test_plan_branch_and_hours_rules_decide(client, shop) -> None:  # type: ignore[no-untyped-def]
    other_day = (datetime.now(UTC).weekday() + 1) % 7
    offpeak = gym_plan(client, shop, "NOTNOW", name="Other days only", access_rules=[
        {"days": [other_day], "from": "00:00", "to": "23:59"}])
    cust, m, p = member_with(client, shop, "Hours Hana", plan_id=offpeak["id"])
    r = enter(client, shop, identifier=p["number"]).json()
    assert r["outcome"] == "deny" and r["code"] == "outside_hours"
    juja_only = gym_plan(client, shop, "JUJAONLY", name="Juja only", branch_ids=[str(shop["juja"])])
    cust2 = customer(client, shop, "Branch Bea")
    client.post(f"{M}/members", headers=shop["owner"], json={
        "plan_id": juja_only["id"], "customer_id": cust2["id"], "branch_id": str(shop["juja"])})
    here = enter(client, shop, customer_id=cust2["id"]).json()
    assert here["code"] == "wrong_branch"
    classes = gym_plan(client, shop, "CLASSESONLY", name="Classes only", gym_access=False)
    cust3, m3, p3 = member_with(client, shop, "Class Cat", plan_id=classes["id"])
    assert enter(client, shop, identifier=p3["number"]).json()["code"] == "classes_only"


def test_a_visit_pack_pays_one_visit_a_day_and_runs_out(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Pack Pete")
    sold = client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["visits"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])})
    assert sold.status_code == 201, sold.text
    first = enter(client, shop, customer_id=cust["id"]).json()
    assert first["outcome"] == "allow" and first["credits_left"] == "4.00" and first["entitlement"] == "5 visits"
    again = enter(client, shop, customer_id=cust["id"]).json()
    assert again["allowed"] and again["credits_left"] == "4.00"                              # the same day: free
    assert D(client.get(f"{M}/sold-packages/{sold.json()['id']}", headers=shop["rep"]).json()["balance"]) == 4
    # the other package (massage only) does not pay for the gym
    cust2 = customer(client, shop, "Massage Mo")
    client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["package"]["id"], "customer_id": cust2["id"], "branch_id": str(shop["branch_id"])})
    assert enter(client, shop, customer_id=cust2["id"]).json()["outcome"] == "deny"
    # take the visits down to the last and past it
    pid = sold.json()["id"]
    client.post(f"{M}/credits/adjust", headers=shop["manager"], json={
        "holder_type": "package", "holder_id": pid, "quantity": "-3", "note": "test"})
    cust3 = customer(client, shop, "Pack Pam")
    sp = client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["visits"]["id"], "customer_id": cust3["id"], "branch_id": str(shop["branch_id"])}).json()
    client.post(f"{M}/credits/adjust", headers=shop["manager"], json={
        "holder_type": "package", "holder_id": sp["id"], "quantity": "-4", "note": "down to one"})
    last = enter(client, shop, customer_id=cust3["id"]).json()
    assert last["outcome"] == "warn" and "no_credits" in codes(last) and last["credits_left"] == "0.00"
    # a visit taken by mistake is given back once
    back = client.post(f"{M}/checkins/{last['checkin_id']}/give-back", headers=shop["rep"], json={"reason": "Wrong person"})
    assert back.status_code == 200 and D(back.json()["visits_given_back"]) == 1
    assert client.post(f"{M}/checkins/{last['checkin_id']}/give-back", headers=shop["rep"], json={
        "reason": "again"}).json()["visits_given_back"] == "0"


def test_a_missing_signature_on_the_terms_refuses_entry_when_the_business_insists(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    cust, m, p = member_with(client, shop, "Waiver Wim")
    client.post(f"{M}/waiver/versions", headers=shop["fm"], json={"company_id": co, "title": "Terms", "body": "Rules."})
    assert enter(client, shop, identifier=p["number"]).json()["outcome"] == "allow"          # not required yet
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"waiver_required": True})
    r = enter(client, shop, identifier=p["number"]).json()
    assert r["outcome"] == "deny" and r["code"] == "waiver_missing"
    client.post(f"{M}/customers/{cust['id']}/waiver", headers=shop["rep"], json={"accepted_name": "Wim"})
    assert enter(client, shop, identifier=p["number"]).json()["outcome"] == "allow"
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"waiver_required": False})


def test_a_repeat_scan_in_the_window_is_one_visit_and_a_retry_is_safe(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={"repeat_window_minutes": 10})
    try:
        cust, m, p = member_with(client, shop, "Twice Tia")
        one = enter(client, shop, identifier=p["number"]).json()
        two = enter(client, shop, identifier=p["number"]).json()
        assert two["duplicate"] is True and two["checkin_id"] == one["checkin_id"] and "already_in" in codes(two)
        assert scalar(shop, "select count(*) from memberships.checkin where customer_id = :c", c=cust["id"]) == 1
    finally:
        client.patch(f"{M}/settings", headers=shop["owner"], params={"company_id": co}, json={
            "repeat_window_minutes": 0})
    cust2, m2, p2 = member_with(client, shop, "Retry Rob")
    key = str(uuid4())
    a = enter(client, shop, identifier=p2["number"], local_id=key).json()
    b = enter(client, shop, identifier=p2["number"], local_id=key).json()
    assert a["checkin_id"] == b["checkin_id"]
    assert scalar(shop, "select count(*) from memberships.checkin where customer_id = :c", c=cust2["id"]) == 1


def test_two_desks_at_once_take_one_visit_not_two(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Race Rena")
    sp = client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["visits"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    answers: list[int] = []

    def go() -> None:
        r = enter(client, shop, customer_id=cust["id"])
        answers.append(r.status_code)

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(a == 200 for a in answers)
    assert scalar(shop, "select count(*) from memberships.checkin where customer_id = :c and counted", c=cust["id"]) == 1
    assert D(client.get(f"{M}/sold-packages/{sp['id']}", headers=shop["rep"]).json()["balance"]) == 4


def test_the_last_visit_cannot_be_taken_twice(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Two different people share nothing, but one person's last visit read by two desks must still be one visit."""
    cust = customer(client, shop, "Last Lou")
    sp = client.post(f"{M}/sold-packages", headers=shop["rep"], json={
        "package_id": shop["visits"]["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    client.post(f"{M}/credits/adjust", headers=shop["manager"], json={
        "holder_type": "package", "holder_id": sp["id"], "quantity": "-4", "note": "one left"})
    results: list[dict] = []  # type: ignore[type-arg]

    def go() -> None:
        results.append(enter(client, shop, customer_id=cust["id"]).json())

    threads = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert D(client.get(f"{M}/sold-packages/{sp['id']}", headers=shop["rep"]).json()["balance"]) == 0
    assert scalar(shop, "select count(*) from memberships.checkin where customer_id = :c and counted", c=cust["id"]) == 1


def test_an_offline_desk_syncs_later_and_refused_entries_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    ok_c, ok_m, ok_p = member_with(client, shop, "Offline Ola")
    bad_c, bad_m, bad_p = member_with(client, shop, "Offline Bad")
    client.post(f"{M}/members/{bad_m['id']}/pause", headers=shop["rep"], json={"frozen": True})
    when = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    body = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "items": [
        {"local_id": f"off-{uuid4()}", "identifier": ok_p["number"], "occurred_at": when, "method": "desk"},
        {"local_id": f"off-{uuid4()}", "identifier": bad_p["number"], "occurred_at": when, "method": "desk"},
        {"local_id": f"off-{uuid4()}", "identifier": "NOBODY-1", "occurred_at": when, "method": "desk"},
        {"local_id": "x", "identifier": ok_p["number"], "occurred_at": (datetime.now(UTC) + timedelta(days=2)).isoformat()}]}
    r = client.post(f"{CI}/sync", headers=shop["desk"], json=body)
    assert r.status_code == 200, r.text
    res = r.json()["results"]
    assert [x["outcome"] for x in res] == ["allow", "deny", "deny", "deny"]
    assert [x["recorded"] for x in res] == [True, True, False, False]
    assert res[3]["code"] == "invalid"
    stored = rows(shop, "select occurred_at, offline, counted from memberships.checkin where customer_id = :c",
                  c=bad_c["id"])
    assert stored and stored[0].offline and stored[0].counted                       # they were in: it is a fact
    flagged = rows(shop, "select message from kernel.exception_item where kind = 'offline_checkin_refused'")
    assert any(bad_p["number"] in f.message for f in flagged)
    again = client.post(f"{CI}/sync", headers=shop["desk"], json=body)               # the same batch again
    assert again.status_code == 200
    assert scalar(shop, "select count(*) from memberships.checkin where customer_id = :c", c=ok_c["id"]) == 1


def test_the_roster_lets_a_desk_decide_without_the_network(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m, p = member_with(client, shop, "Roster Rey")
    r = client.get(f"{CI}/roster", headers=shop["desk"], params={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"])})
    assert r.status_code == 200, r.text
    entries = {e["number"]: e for e in r.json()["entries"]}
    assert entries[p["number"]]["outcome"] == "allow" and entries[p["number"]]["name"] == "Roster Rey"
    assert r.json()["valid_hours"] == 24


def test_a_door_controller_asks_with_an_api_key(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust, m, p = member_with(client, shop, "Turnstile Tom")
    client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={"card_number": "DOOR-1"})
    made = client.post("/api/v1/api-keys", headers=shop["owner"], json={
        "name": "Front turnstile", "scopes": ["memberships.checkin"], "company_id": str(shop["company_id"])})
    assert made.status_code == 201, made.text
    key = {"X-API-Key": made.json()["key"]}
    url = f"{M}/access/decision"
    body = {"branch_id": str(shop["branch_id"]), "identifier": "DOOR-1", "device": "turnstile-1"}
    r = client.post(url, headers=key, json=body)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["allowed"] is True and answer["decision"] == "allow" and answer["first_name"] == "Turnstile"
    assert answer["member_number"] == p["number"] and "phone" not in answer and "name" not in answer
    dry = client.post(url, headers=key, json={**body, "record": False}).json()
    assert dry["allowed"] is True and dry["checkin_id"] is None
    unknown = client.post(url, headers=key, json={**body, "identifier": "NOPE"}).json()
    assert unknown["allowed"] is False and unknown["code"] == "not_found"
    listed = client.get(f"{M}/access/allowed", headers=key, params={"branch_id": str(shop["branch_id"])})
    assert listed.status_code == 200
    assert "DOOR-1" in [e["card_number"] for e in listed.json()["members"]]
    assert all("name" not in e or e["name"] is None for e in listed.json()["members"])
    # the key reaches nothing else of memberships
    assert client.get(f"{M}/members", headers=key).status_code == 403
    assert client.get(f"{M}/profiles", headers=key, params={"company_id": str(shop["company_id"])}).status_code == 403
    # a read-only key cannot ask (it writes the check-in) ; and a key for another branch is refused
    ro = client.post("/api/v1/api-keys", headers=shop["owner"], json={
        "name": "Read only", "scopes": ["memberships.checkin"], "read_only": True,
        "company_id": str(shop["company_id"])}).json()
    assert client.post(url, headers={"X-API-Key": ro["key"]}, json=body).status_code == 403
    juja_key = client.post("/api/v1/api-keys", headers=shop["owner"], json={
        "name": "Juja door", "scopes": ["memberships.checkin"], "company_id": str(shop["company_id"]),
        "branch_id": str(shop["juja"])}).json()
    assert client.post(url, headers={"X-API-Key": juja_key["key"]}, json=body).status_code == 403
    # entries are published for a webhook
    catalogue = client.get("/api/v1/webhooks/events", headers=shop["owner"]).json()
    assert "checkin.recorded" in [e["type"] for e in catalogue]


def test_check_in_is_fast_with_thousands_of_members(client, shop) -> None:  # type: ignore[no-untyped-def]
    co, branch = str(shop["company_id"]), str(shop["branch_id"])
    plan = shop["plan"]["id"]
    tenant = str(shop["tenant_id"])
    with system(shop) as s:
        s.execute(text(
            "insert into memberships.profile (tenant_id, company_id, branch_id, customer_id, number) "
            "select :t, :c, :b, gen_random_uuid(), 'BULK-' || n from generate_series(1, 4000) n"),
            {"t": tenant, "c": co, "b": branch})
        s.execute(text(
            "insert into memberships.member (tenant_id, company_id, branch_id, number, customer_id, plan_id, plan_name, "
            "status, start_date, current_period_start, next_renewal_date, anchor_day, price, billing_interval) "
            "select :t, :c, :b, 'BULKM-' || p.number, p.customer_id, :p, 'Gold', 'active', current_date - 20, "
            "current_date - 20, current_date + 10, 1, 100, 'month' from memberships.profile p where p.number like 'BULK-%'"),
            {"t": tenant, "c": co, "b": branch, "p": plan})
    import random

    picks = random.Random(1).sample(range(1, 4001), 40)
    times = []
    for n in picks:
        started = time.perf_counter()
        r = enter(client, shop, identifier=f"bulk-{n}", method="scan")
        times.append(time.perf_counter() - started)
        assert r.status_code == 200 and r.json()["outcome"] == "allow"
    times.sort()
    assert times[len(times) // 2] < 0.25 and times[-3] < 0.6, f"median {times[len(times) // 2]:.3f}s slowest {times[-1]:.3f}s"
    started = time.perf_counter()
    r = client.get(f"{CI}/roster", headers=shop["desk"], params={"company_id": co, "branch_id": branch})
    assert r.status_code == 200 and len(r.json()["entries"]) >= 4000
    assert time.perf_counter() - started < 6.0
    assert scalar(shop, "select count(*) from memberships.member where number like 'BULKM-%'") == 4000

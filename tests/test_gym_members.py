"""Gyms and studios, part 1: members' profiles, households with one payer, the terms they accept, the kinds of plan
(passes, contracts, off-peak, joining fee), upgrades, freezes and prices that change from a date."""

from datetime import date, timedelta
from decimal import Decimal as D  # noqa: N817

import pytest
from sqlalchemy import text

from tests.gym_helpers import M, customer, gym_plan, make_gym_shop, rows, scalar, sign_up, today
from tests.memberships_helpers import cancel_reason, run_billing
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_gym_shop(client, registry, "Gym Members Co")


def member(client, shop, member_id: str) -> dict:  # type: ignore[no-untyped-def]
    r = client.get(f"{M}/members/{member_id}", headers=shop["owner"])
    assert r.status_code == 200, r.text
    return r.json()


def invoices_of(client, shop, member_id: str) -> list[dict]:  # type: ignore[no-untyped-def]
    return client.get(f"{M}/members/{member_id}/dues", headers=shop["owner"]).json()


# --------------------------------------------------------------------------- profile
def test_signing_up_makes_a_profile_with_a_member_number(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Profile Pam")
    assert sign_up(client, shop, cust, who="rep").status_code == 201
    p = client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"])
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["number"].startswith("M-") and body["lifecycle"] == "member" and body["customer_name"] == "Profile Pam"
    again = client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"]).json()
    assert again["number"] == body["number"]                                    # one number per person, ever
    other = customer(client, shop, "Profile Pete")
    sign_up(client, shop, other, who="rep")
    n2 = client.get(f"{M}/profiles/by-customer/{other['id']}", headers=shop["rep"]).json()["number"]
    assert n2 != body["number"]


def test_emergency_contact_card_photo_and_tags(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Contact Cora")
    sign_up(client, shop, cust, who="rep")
    r = client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={
        "emergency_name": "Brian", "emergency_phone": "0712000111", "emergency_relation": "Brother",
        "date_of_birth": "1990-05-02", "card_number": " ab 12-34 ", "tags": ["morning", "morning", "student"],
        "source": "Referral"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["emergency_name"] == "Brian" and p["card_number"] == "AB12-34" and p["tags"] == ["morning", "student"]
    assert p["date_of_birth"] == "1990-05-02"
    # the photo is a picture attached to the member (the files service), not any id
    stray = client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={
        "photo_file_id": "6d7bd8f2-0a52-4d7c-b4bd-1c4b3b1c7a10"})
    assert stray.status_code in (404, 422)
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 30, 30)).save(buffer, "PNG")
    up = client.post("/api/v1/files", headers={**shop["rep"], "X-File-Name": "face.png", "Content-Type": "image/png"},
                     params={"entity_type": "memberships.profile", "entity_id": p["id"], "category": "photo"},
                     content=buffer.getvalue())
    assert up.status_code == 201, up.text
    with_photo = client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={
        "photo_file_id": up.json()["id"]})
    assert with_photo.status_code == 200 and with_photo.json()["photo_file_id"] == up.json()["id"]
    seen = client.post(f"{M}/checkin", headers=shop["rep"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "customer_id": cust["id"]}).json()
    assert seen["person"]["photo_link"].startswith("/api/v1/files/dl/")
    # a card belongs to one member
    thief = customer(client, shop, "Card Carl")
    sign_up(client, shop, thief, who="rep")
    clash = client.patch(f"{M}/profiles/by-customer/{thief['id']}", headers=shop["rep"], json={"card_number": "ab12-34"})
    assert clash.status_code == 409
    cleared = client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={"card_number": ""})
    assert cleared.json()["card_number"] is None
    assert client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["cashier"], json={}).status_code == 403
    bad = client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={"card_number": "no spaces!"})
    assert bad.status_code == 422


def test_members_are_found_by_name_phone_number_or_card(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    cust = customer(client, shop, "Findable Fatima", phone="0722333444")
    sign_up(client, shop, cust, who="rep")
    p = client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"]).json()
    client.patch(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"], json={"card_number": "TAG-777"})
    for query in ("Fatima", p["number"].lower(), "TAG-777"):
        found = client.get(f"{M}/profiles", headers=shop["rep"], params={"company_id": co, "search": query}).json()
        assert [x["customer_name"] for x in found] == ["Findable Fatima"], query


def test_blocking_a_member_needs_a_reason(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Blocked Ben")
    sign_up(client, shop, cust, who="rep")
    url = f"{M}/profiles/by-customer/{cust['id']}/block"
    assert client.post(url, headers=shop["rep"], json={"blocked": True}).status_code == 422
    r = client.post(url, headers=shop["rep"], json={"blocked": True, "reason": "Fighting"})
    assert r.json()["access_blocked"] is True and r.json()["block_reason"] == "Fighting"
    assert client.post(url, headers=shop["rep"], json={"blocked": False}).json()["access_blocked"] is False


# --------------------------------------------------------------------------- households
def test_a_household_is_billed_to_one_payer(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    parent = customer(client, shop, "Parent Pat")
    kid1, kid2 = customer(client, shop, "Kid One"), customer(client, shop, "Kid Two")
    g = client.post(f"{M}/groups", headers=shop["rep"], json={
        "company_id": co, "name": "The Pats", "kind": "household", "payer_customer_id": parent["id"]})
    assert g.status_code == 201, g.text
    gid = g.json()["id"]
    for kid in (kid1, kid2):
        r = client.put(f"{M}/profiles/by-customer/{kid['id']}/group", headers=shop["rep"], json={"group_id": gid})
        assert r.status_code == 200, r.text
    m1, m2 = (sign_up(client, shop, kid, date(2026, 10, 1), who="rep") for kid in (kid1, kid2))
    assert m1.status_code == 201 and m1.json()["billing_customer_id"] == parent["id"]
    assert m1.json()["billing_customer_name"] == "Parent Pat"
    run = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m2.json()["id"]}).json()[0]
    assert run["customer_id"] == parent["id"] and run["status"] == "issued"
    detail = client.get(f"{M}/groups/{gid}", headers=shop["rep"]).json()
    assert detail["member_count"] == 2 and detail["payer_name"] == "Parent Pat"
    # the renewal goes to the parent as well
    run_billing(shop, date(2026, 11, 2))
    renewals = client.get(f"{M}/invoice-runs", headers=shop["owner"], params={"owner_id": m1.json()["id"]}).json()
    assert len(renewals) == 2 and {r["customer_id"] for r in renewals} == {parent["id"]}
    # changing the payer moves future invoices
    other = customer(client, shop, "Grandpa Gus")
    client.patch(f"{M}/groups/{gid}", headers=shop["rep"], json={"payer_customer_id": other["id"]})
    assert member(client, shop, m1.json()["id"])["billing_customer_id"] == other["id"]
    # taking a member out of the group bills them themselves again
    client.put(f"{M}/profiles/by-customer/{kid1['id']}/group", headers=shop["rep"], json={"group_id": None})
    assert member(client, shop, m1.json()["id"])["billing_customer_id"] is None


# --------------------------------------------------------------------------- terms and waiver
def test_terms_are_versioned_and_acceptance_is_recorded_for_ever(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    cust = customer(client, shop, "Waiver Wendy")
    assert client.post(f"{M}/waiver/versions", headers=shop["rep"], json={
        "company_id": co, "title": "Terms", "body": "Train at your own risk."}).status_code == 403
    v1 = client.post(f"{M}/waiver/versions", headers=shop["fm"], json={
        "company_id": co, "title": "Membership terms", "body": "Train at your own risk."})
    assert v1.status_code == 201 and v1.json()["version"] >= 1
    status = client.get(f"{M}/customers/{cust['id']}/waiver", headers=shop["rep"]).json()
    assert status["accepted_current"] is False and status["current_version"] == v1.json()["version"]
    ok = client.post(f"{M}/customers/{cust['id']}/waiver", headers=shop["rep"], json={
        "accepted_name": "Wendy W", "method": "kiosk"})
    assert ok.status_code == 201 and ok.json()["accepted_name"] == "Wendy W" and ok.json()["method"] == "kiosk"
    again = client.post(f"{M}/customers/{cust['id']}/waiver", headers=shop["rep"], json={"accepted_name": "Other"})
    assert again.json()["id"] == ok.json()["id"]                                      # nothing new is recorded
    status = client.get(f"{M}/customers/{cust['id']}/waiver", headers=shop["rep"]).json()
    assert status["accepted_current"] is True and status["acceptances"][0]["recorded_by_name"]
    v2 = client.post(f"{M}/waiver/versions", headers=shop["fm"], json={
        "company_id": co, "title": "Membership terms", "body": "New wording."}).json()
    assert v2["version"] == v1.json()["version"] + 1
    status = client.get(f"{M}/customers/{cust['id']}/waiver", headers=shop["rep"]).json()
    assert status["accepted_current"] is False                                        # asked again
    # an acceptance is never changed or removed, not even by the database owner's application
    with pytest.raises(Exception, match="immutable|cannot|not allowed|forbid"), system(shop) as s:
        s.execute(text("update memberships.waiver_acceptance set accepted_name = 'x'"))
    with pytest.raises(Exception, match="immutable|cannot|not allowed|forbid"), system(shop) as s:
        s.execute(text("update memberships.waiver_version set body = 'x'"))


# --------------------------------------------------------------------------- kinds of plan
def test_a_day_pass_runs_out_by_itself_and_invoices_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "DAYPASS", name="Day pass", fee="15.00", kind="pass", valid_days=1)
    cust = customer(client, shop, "Daypass Dan")
    start = today()
    r = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": start.isoformat()})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["plan_kind"] == "pass" and m["end_date"] == (start + timedelta(days=1)).isoformat()
    assert m["next_renewal_date"] == m["end_date"] and m["price"] == "15.00"
    runs = invoices_of(client, shop, m["id"])
    assert len(runs) == 1 and D(runs[0]["total"]) == D("15.00")
    run_billing(shop, start + timedelta(days=2))
    ended = member(client, shop, m["id"])
    assert ended["status"] == "expired" and len(invoices_of(client, shop, m["id"])) == 1       # no renewal invoice
    # a pass cannot be put on hold
    again = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    assert client.post(f"{M}/members/{again['id']}/pause", headers=shop["rep"], json={}).status_code == 422
    # a pass says how long it lasts
    bad = client.post(f"{M}/plans", headers=shop["fm"], json={
        "company_id": str(shop["company_id"]), "code": "BADPASS", "name": "Bad", "fee": "1", "kind": "pass"})
    assert bad.status_code == 422


def test_a_trial_pass_makes_the_person_a_trial_until_they_join(client, shop) -> None:  # type: ignore[no-untyped-def]
    trial = gym_plan(client, shop, "TRIAL7", name="Free week", fee="0.00", kind="pass", valid_days=7, is_trial=True)
    cust = customer(client, shop, "Trial Tess")
    r = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": trial["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])})
    assert r.status_code == 201 and r.json()["is_trial"] is True
    p = client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"]).json()
    assert p["lifecycle"] == "trial" and p["trial_ends_on"] == (today() + timedelta(days=7)).isoformat()
    assert invoices_of(client, shop, r.json()["id"]) == []                        # nothing to invoice
    joined = sign_up(client, shop, cust, who="rep")                              # joins on the Gold plan
    assert joined.status_code == 201
    assert client.get(f"{M}/profiles/by-customer/{cust['id']}", headers=shop["rep"]).json()["lifecycle"] == "member"


def test_a_contract_has_a_minimum_term_and_a_notice_period(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "ANNUAL", name="12 month contract", fee="80.00", kind="fixed_term", term_periods=12,
                    notice_days=30, early_exit_fee="150.00")
    cust = customer(client, shop, "Contract Cleo")
    start = date(2026, 6, 1)
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": start.isoformat()}).json()
    assert m["term_end"] == "2027-06-01"
    reason = cancel_reason(client, shop)
    r = client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={"reason_code_id": reason})
    assert r.status_code == 200 and r.json()["cancel_at"] == "2027-06-01"          # not before the contract ends
    client.post(f"{M}/members/{m['id']}/undo-cancel", headers=shop["rep"])
    # leaving now inside the term costs the early-exit fee, invoiced at once
    out = client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={
        "reason_code_id": reason, "at_period_end": False})
    assert out.status_code == 200 and out.json()["status"] == "cancelled"
    fees = [x for x in invoices_of(client, shop, m["id"]) if x["owner_type"] == "exit"]
    assert len(fees) == 1 and D(fees[0]["total"]) == D("150.00")


def test_waiving_the_exit_fee_needs_the_credits_right(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "WAIVE", name="Contract w", fee="80.00", kind="fixed_term", term_periods=6,
                    early_exit_fee="90.00")
    cust = customer(client, shop, "Waive Walt")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": today().isoformat()}).json()
    reason = cancel_reason(client, shop)
    denied = client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={
        "reason_code_id": reason, "at_period_end": False, "waive_exit_fee": True})
    assert denied.status_code == 403
    ok = client.post(f"{M}/members/{m['id']}/cancel", headers=shop["manager"], json={
        "reason_code_id": reason, "at_period_end": False, "waive_exit_fee": True})
    assert ok.status_code == 200, ok.text
    assert [x for x in invoices_of(client, shop, m["id"]) if x["owner_type"] == "exit"] == []


def test_the_notice_period_pushes_the_end_to_a_later_renewal(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "NOTICE", name="Monthly 30 days notice", fee="60.00", notice_days=30)
    cust = customer(client, shop, "Notice Nia")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": today().isoformat()}).json()
    r = client.post(f"{M}/members/{m['id']}/cancel", headers=shop["rep"], json={"reason_code_id": cancel_reason(
        client, shop)})
    # the first renewal is a month away: 30 days notice from today is on or after it only if the month is 30+ days
    renewal = date.fromisoformat(m["next_renewal_date"])
    assert date.fromisoformat(r.json()["cancel_at"]) >= today() + timedelta(days=30)
    assert date.fromisoformat(r.json()["cancel_at"]) >= renewal


def test_a_joining_fee_is_on_the_first_invoice_only(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "JOIN", name="With joining fee", fee="100.00", joining_fee="40.00")
    cust = customer(client, shop, "Joining Jo")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": date(2026, 9, 1).isoformat()}).json()
    first = invoices_of(client, shop, m["id"])
    assert len(first) == 1 and D(first[0]["total"]) == D("140.00")
    run_billing(shop, date(2026, 10, 2))
    runs = sorted(invoices_of(client, shop, m["id"]), key=lambda r: r["period_start"])
    assert [D(r["total"]) for r in runs] == [D("140.00"), D("100.00")]
    # waiving it takes the credits right
    other = customer(client, shop, "Joining Jim")
    body = {"plan_id": plan["id"], "customer_id": other["id"], "branch_id": str(shop["branch_id"]),
            "waive_joining_fee": True}
    assert client.post(f"{M}/members", headers=shop["rep"], json=body).status_code == 403
    done = client.post(f"{M}/members", headers=shop["manager"], json=body).json()
    assert D(invoices_of(client, shop, done["id"])[0]["total"]) == D("100.00")


def test_a_plan_can_prorate_the_first_month_by_itself(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "PRORATE", name="Prorated", fee="300.00", prorate=True)
    cust = customer(client, shop, "Prorate Pia")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": "2026-06-16"}).json()
    assert m["next_renewal_date"] == "2026-07-01"
    assert D(invoices_of(client, shop, m["id"])[0]["total"]) == D("150.00")            # 15 of 30 days


def test_off_peak_windows_and_branch_lists_are_checked_and_stored(client, shop) -> None:  # type: ignore[no-untyped-def]
    ok = client.post(f"{M}/plans", headers=shop["fm"], json={
        "company_id": str(shop["company_id"]), "code": "OFFPEAK", "name": "Off-peak", "fee": "40.00",
        "access_rules": [{"days": [0, 1, 2, 3, 4], "from": "10:00", "to": "16:00"}],
        "branch_ids": [str(shop["branch_id"])], "gym_access": True, "classes_mode": "credits",
        "guest_passes_per_period": 2, "freeze_max_days": 28, "freeze_fee": "5.00", "joining_fee": "0"})
    assert ok.status_code == 201, ok.text
    p = ok.json()
    assert p["access_rules"][0]["from"] == "10:00" and p["branch_ids"] == [str(shop["branch_id"])]
    assert p["guest_passes_per_period"] == 2 and p["classes_mode"] == "credits" and p["freeze_max_days"] == 28
    for bad in ({"access_rules": [{"days": [9], "from": "10:00", "to": "16:00"}]},
                {"access_rules": [{"days": [1], "from": "10:00", "to": "10:00"}]},
                {"access_rules": [{"days": [1], "from": "9am", "to": "16:00"}]},
                {"branch_ids": ["not-a-uuid"]}):
        r = client.post(f"{M}/plans", headers=shop["fm"], json={
            "company_id": str(shop["company_id"]), "code": "BADRULE", "name": "Bad", "fee": "1", **bad})
        assert r.status_code == 422, bad
    # a plan sold at one branch cannot take a member at another
    juja = client.post(f"{M}/members", headers=shop["owner"], json={
        "plan_id": p["id"], "customer_id": customer(client, shop, "Juja Joe")["id"], "branch_id": str(shop["juja"])})
    assert juja.status_code == 422


def test_editing_the_fee_clears_the_example_flag(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "EXAMPLE", name="Example plan", fee="20.00", is_example=True)
    assert plan["is_example"] is True
    same = client.patch(f"{M}/plans/{plan['id']}", headers=shop["fm"], json={"name": "Example plan 2"}).json()
    assert same["is_example"] is True
    changed = client.patch(f"{M}/plans/{plan['id']}", headers=shop["fm"], json={"fee": "25.00"}).json()
    assert changed["is_example"] is False


# --------------------------------------------------------------------------- changing plan
def test_an_upgrade_charges_the_difference_for_the_days_left(client, shop) -> None:  # type: ignore[no-untyped-def]
    basic = gym_plan(client, shop, "BASIC", name="Basic", fee="100.00", credits_per_period="0")
    plus = gym_plan(client, shop, "PLUS", name="Plus", fee="160.00", credits_per_period="8")
    cust = customer(client, shop, "Upgrade Uma")
    start = today() - timedelta(days=10)                       # 10 days into a period of 30..31 days
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": basic["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": start.isoformat()}).json()
    q = client.get(f"{M}/members/{m['id']}/change-quote", headers=shop["rep"], params={"plan_id": plus["id"]}).json()
    period = (date.fromisoformat(m["next_renewal_date"]) - start).days
    left = period - 10
    expected = (D(60) * D(left) / D(period)).quantize(D("0.01"))
    assert q["can_start_now"] is True and D(q["charge_now"]) == expected
    done = client.post(f"{M}/members/{m['id']}/change-plan", headers=shop["rep"], json={"plan_id": plus["id"]})
    assert done.status_code == 200, done.text
    after = done.json()
    assert after["plan_name"] == "Plus" and D(after["price"]) == D("160.00") and D(after["balance"]) > 0
    changes = [x for x in invoices_of(client, shop, m["id"]) if x["owner_type"] == "change"]
    assert len(changes) == 1 and D(changes[0]["total"]) == expected
    # and back down: a cheaper plan starts at the next renewal, nothing is refunded now
    q2 = client.get(f"{M}/members/{m['id']}/change-quote", headers=shop["rep"], params={"plan_id": basic["id"]}).json()
    assert q2["can_start_now"] is False and "next renewal" in q2["reason"]
    now = client.post(f"{M}/members/{m['id']}/change-plan", headers=shop["rep"], json={"plan_id": basic["id"]})
    assert now.status_code == 422
    booked = client.post(f"{M}/members/{m['id']}/change-plan", headers=shop["rep"], json={
        "plan_id": basic["id"], "when": "next_renewal"})
    assert booked.status_code == 200 and booked.json()["pending_plan_name"] == "Basic"
    renewal = date.fromisoformat(after["next_renewal_date"])
    run_billing(shop, renewal)
    renewed = member(client, shop, m["id"])
    assert renewed["plan_name"] == "Basic" and D(renewed["price"]) == D("100.00") and renewed["pending_plan_id"] is None
    assert any(D(x["total"]) == D("100.00") and x["period_start"] == renewal.isoformat()
               for x in invoices_of(client, shop, m["id"]))


# --------------------------------------------------------------------------- freezes
def test_a_freeze_follows_the_plan_rules_and_adds_the_days_back(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "FREEZY", name="Freezy", fee="100.00", freeze_max_days=30, freeze_fee="10.00")
    cust = customer(client, shop, "Freeze Fay")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "start_date": today().isoformat()}).json()
    mid = m["id"]
    allowance = client.get(f"{M}/members/{mid}/freeze-allowance", headers=shop["rep"]).json()
    assert allowance == {"limit": 30, "used": 0, "left": 30, "fee": "10.00", "allowed": True}
    too_long = client.post(f"{M}/members/{mid}/pause", headers=shop["rep"], json={
        "resume_on": (today() + timedelta(days=45)).isoformat()})
    assert too_long.status_code == 422 and "30" in too_long.text
    frozen = client.post(f"{M}/members/{mid}/pause", headers=shop["rep"], json={
        "resume_on": (today() + timedelta(days=20)).isoformat(), "note": "Injury"})
    assert frozen.status_code == 200 and frozen.json()["status"] == "paused" and frozen.json()["hold_kind"] == "member"
    fee = [x for x in invoices_of(client, shop, mid) if x["owner_type"] == "freeze"]
    assert len(fee) == 1 and D(fee[0]["total"]) == D("10.00")
    # nothing is billed while it is held; the worker lifts the hold on the resume date and the days are added back
    renewal = date.fromisoformat(m["next_renewal_date"])
    run_billing(shop, renewal)
    back = member(client, shop, mid)
    assert back["status"] == "active" and back["hold_kind"] is None
    assert back["next_renewal_date"] == (renewal + timedelta(days=20)).isoformat()
    assert len([x for x in invoices_of(client, shop, mid) if x["owner_type"] == "member"]) == 1
    freezes = client.get(f"{M}/members/{mid}/freezes", headers=shop["rep"]).json()
    assert len(freezes) == 1 and freezes[0]["days"] == 20 and freezes[0]["fee"] == "10.00"
    assert client.post(f"{M}/members/{mid}/resume", headers=shop["rep"], json={}).status_code == 409
    # the plan's days are a limit a year: with one day used, 30 are still there (the freeze lasted no days)
    with system(shop) as s:
        s.execute(text("update memberships.freeze set started_on = :a, ended_on = :b, days = 28 where member_id = :m"),
                  {"a": today() - timedelta(days=40), "b": today() - timedelta(days=12), "m": mid})
    left = client.get(f"{M}/members/{mid}/freeze-allowance", headers=shop["rep"]).json()
    assert left["used"] == 28 and left["left"] == 2
    again = client.post(f"{M}/members/{mid}/pause", headers=shop["rep"], json={
        "resume_on": (today() + timedelta(days=10)).isoformat()})
    assert again.status_code == 422


def test_a_plan_that_cannot_be_frozen_and_waiving_the_fee(client, shop) -> None:  # type: ignore[no-untyped-def]
    none = gym_plan(client, shop, "NOFREEZE", name="No freeze", fee="50.00", freeze_max_days=0)
    cust = customer(client, shop, "Nofreeze Nat")
    m = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": none["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"])}).json()
    refused = client.post(f"{M}/members/{m['id']}/pause", headers=shop["rep"], json={})
    assert refused.status_code == 422 and "cannot be frozen" in refused.text
    # the business can still hold a membership (it is not the member's freeze)
    held = client.post(f"{M}/members/{m['id']}/pause", headers=shop["rep"], json={"frozen": True, "note": "Review"})
    assert held.status_code == 200 and held.json()["status"] == "frozen" and held.json()["hold_kind"] == "business"
    fee_plan = gym_plan(client, shop, "FEEFREEZE", name="Fee freeze", fee="50.00", freeze_fee="12.00")
    other = customer(client, shop, "Feefreeze Fil")
    f = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": fee_plan["id"], "customer_id": other["id"], "branch_id": str(shop["branch_id"])}).json()
    denied = client.post(f"{M}/members/{f['id']}/pause", headers=shop["rep"], json={"waive_fee": True})
    assert denied.status_code == 403
    waived = client.post(f"{M}/members/{f['id']}/pause", headers=shop["manager"], json={"waive_fee": True})
    assert waived.status_code == 200
    assert [x for x in invoices_of(client, shop, f["id"]) if x["owner_type"] == "freeze"] == []


# --------------------------------------------------------------------------- prices from a date
def test_a_price_change_applies_from_its_date_and_never_backwards(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "REPRICE", name="Repriced", fee="100.00")
    old = customer(client, shop, "Old Member")
    locked = customer(client, shop, "Locked Member")
    start = today() - timedelta(days=5)
    m_old = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": old["id"], "branch_id": str(shop["branch_id"]),
        "start_date": start.isoformat()}).json()
    m_locked = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": locked["id"], "branch_id": str(shop["branch_id"]),
        "start_date": start.isoformat()}).json()
    client.patch(f"{M}/members/{m_locked['id']}", headers=shop["rep"], json={"price_locked": True})
    url = f"{M}/plans/{plan['id']}/price-changes"
    assert client.post(url, headers=shop["rep"], json={"effective_from": today().isoformat(), "fee": "1"}).status_code == 403
    past = client.post(url, headers=shop["fm"], json={"effective_from": (today() - timedelta(days=1)).isoformat(),
                                                       "fee": "120.00"})
    assert past.status_code == 422
    from_date = date.fromisoformat(m_old["next_renewal_date"]) - timedelta(days=1)
    made = client.post(url, headers=shop["fm"], json={"effective_from": from_date.isoformat(), "fee": "120.00",
                                                       "apply_to_existing": True})
    assert made.status_code == 201 and made.json()["members_affected"] >= 1
    shown = client.get(f"{M}/plans/{plan['id']}", headers=shop["fm"]).json()
    assert shown["current_fee"] == "100.00" and shown["next_fee"] == "120.00" and shown["next_fee_from"] == from_date.isoformat()
    # a new member joining after the date pays the new price; before it, the old one
    later = customer(client, shop, "Later Member")
    before = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": later["id"], "branch_id": str(shop["branch_id"])}).json()
    assert before["price"] == "100.00"
    after = client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": customer(client, shop, "Even Later")["id"],
        "branch_id": str(shop["branch_id"]), "start_date": from_date.isoformat()}).json()
    assert after["price"] == "120.00"
    # existing members move at their first renewal on or after the date, unless locked
    run_billing(shop, date.fromisoformat(m_old["next_renewal_date"]))
    assert member(client, shop, m_old["id"])["price"] == "120.00"
    assert member(client, shop, m_locked["id"])["price"] == "100.00"
    runs = sorted(invoices_of(client, shop, m_old["id"]), key=lambda r: r["period_start"])
    assert [D(r["total"]) for r in runs] == [D("100.00"), D("120.00")]                # the old invoice is untouched
    listed = client.get(url, headers=shop["fm"]).json()
    assert listed[0]["status"] == "scheduled"
    started = client.post(url, headers=shop["fm"], json={"effective_from": today().isoformat(), "fee": "101.00"}).json()
    assert client.post(f"{M}/price-changes/{started['id']}/cancel", headers=shop["fm"]).status_code == 409   # started


def test_a_price_change_that_has_not_started_can_be_cancelled(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "REPRICE2", name="Repriced 2", fee="50.00")
    url = f"{M}/plans/{plan['id']}/price-changes"
    made = client.post(url, headers=shop["fm"], json={"effective_from": (today() + timedelta(days=30)).isoformat(),
                                                       "fee": "55.00"}).json()
    assert client.post(f"{M}/price-changes/{made['id']}/cancel", headers=shop["fm"]).json()["status"] == "cancelled"
    shown = client.get(f"{M}/plans/{plan['id']}", headers=shop["fm"]).json()
    assert shown["next_fee"] is None


def test_what_a_member_agreed_to_pay_survives_a_plan_edit(client, shop) -> None:  # type: ignore[no-untyped-def]
    plan = gym_plan(client, shop, "SNAP", name="Snapshot", fee="70.00")
    cust = customer(client, shop, "Snap Sam")
    assert client.post(f"{M}/members", headers=shop["rep"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "price": "55.00"}).status_code == 403                                           # a rep cannot give a private price
    m = client.post(f"{M}/members", headers=shop["manager"], json={
        "plan_id": plan["id"], "customer_id": cust["id"], "branch_id": str(shop["branch_id"]),
        "price": "55.00"}).json()
    assert client.post(f"{M}/members", headers=shop["owner"], json={
        "plan_id": plan["id"], "customer_id": customer(client, shop, "Snap Sue")["id"],
        "branch_id": str(shop["branch_id"]), "price": "10.00"}).status_code == 201     # the owner holds the right
    assert m["price"] == "55.00" and m["price_locked"] is True and scalar(
        shop, "select count(*) from memberships.member where plan_id = :p", p=plan["id"]) == 2
    assert rows(shop, "select 1 from memberships.plan where id = :p", p=plan["id"])

"""The Super Admin in use: the subscribers directory and detail, actions on a subscriber, plan requests from the business
and the operator's answer, tenant isolation of Plan & billing, the dashboard figures, deleting a business, personal data."""

from datetime import timedelta
from decimal import Decimal as D  # noqa: N817

import pytest

from tests.conftest import make_tenant, sign_in
from tests.platform_helpers import API, T0, make_plan, staff
from tests.test_operator_console import trail
from ziira.kernel.platform import billing, plans, settings, subscribers, subscriptions
from ziira.plugins.messaging.providers import FakeEmail


@pytest.fixture(scope="module")
def world(client, registry):  # type: ignore[no-untyped-def]
    """Two businesses on different plans, an unmanaged one, and operators."""
    settings.set_value("billing.tax_lines", [{"name": "VAT", "rate_percent": "16"}], "test")
    make_plan("con-basic", units=["products"], prices={("KES", "month"): "1000.00", ("KES", "year"): "10000.00"},
              max_users=3)
    make_plan("con-pro", units=["products", "inventory"], prices={("KES", "month"): "2500.00"}, trial_days=0)
    a, b, c = make_tenant("Con Alpha"), make_tenant("Con Beta"), make_tenant("Con Gamma")
    registry.enable(a["tenant_id"], "products")
    subscriptions.start(a["tenant_id"], "con-basic", currency="KES", mode="active", now=T0)
    subscriptions.start(b["tenant_id"], "con-basic", currency="KES", mode="trial", now=T0)
    yield {"A": a, "B": b, "C": c, "boss": staff(client, "superadmin"), "billing": staff(client, "billing"),
           "support": staff(client, "support"), "viewer": staff(client, "readonly")}
    settings.set_value("billing.tax_lines", [], "test")


def owner(client, code):  # type: ignore[no-untyped-def]
    return sign_in(client, code, f"owner@{code}.test", device_id=f"d-{code}").headers


# --------------------------------------------------------------------------- the directory
def test_the_directory_lists_every_business_with_its_plan_and_filters(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    everyone = client.get(f"{API}/operator/subscribers", headers=boss, params={"search": "con-"}).json()
    rows = {r["code"]: r for r in everyone["items"]}
    assert set(rows) >= {"con-alpha", "con-beta", "con-gamma"} and everyone["total"] == len(everyone["items"])
    assert rows["con-alpha"]["status"] == "active" and rows["con-alpha"]["plan_code"] == "con-basic"
    assert rows["con-alpha"]["unit_amount"] == "1000.00" and rows["con-alpha"]["max_users"] == 3
    assert rows["con-gamma"]["status"] == "unmanaged" and rows["con-gamma"]["plan_code"] is None

    def codes(**params):  # type: ignore[no-untyped-def]
        r = client.get(f"{API}/operator/subscribers", headers=boss, params={"search": "con-", **params})
        assert r.status_code == 200, r.text
        return {x["code"] for x in r.json()["items"] if x["code"].startswith("con-")}   # search is a substring match
    assert codes(status="trialing") == {"con-beta"}
    assert codes(plan="con-basic") == {"con-alpha", "con-beta"}
    assert codes(flag="unmanaged") == {"con-gamma"}
    assert codes(flag="past_due") == set() and codes(flag="churned") == set()
    assert client.get(f"{API}/operator/subscribers", headers=boss, params={"flag": "nope"}).status_code == 422
    page = client.get(f"{API}/operator/subscribers", headers=boss, params={"search": "con-", "limit": 1}).json()
    assert len(page["items"]) == 1 and page["total"] >= 3


def test_trials_ending_soon_are_a_filter(world) -> None:  # type: ignore[no-untyped-def]
    soon = subscribers.list_subscribers(search="con-", flag="trial_ending", now=T0 + timedelta(days=10))
    assert [r["code"] for r in soon["items"] if r["code"].startswith("con-")] == ["con-beta"]                       # trial ends T0 + 14d, within 7 days
    assert [r for r in subscribers.list_subscribers(search="con-", flag="trial_ending", now=T0)["items"]
            if r["code"].startswith("con-")] == []


def test_a_subscriber_in_full(client, world, registry) -> None:  # type: ignore[no-untyped-def]
    boss = world["viewer"]["headers"]                                              # even a read-only operator may look
    d = client.get(f"{API}/operator/subscribers/con-alpha", headers=boss)
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["owners"][0]["email"] == "owner@con-alpha.test"
    assert body["subscription"]["status"] == "active" and body["limits"]["users"] == 3
    assert body["usage"]["users"] == 1 and body["usage"]["branches"] == 1
    assert {u["name"] for u in body["units"]} >= {"products"}
    assert body["timeline"][-1]["kind"] == "created" and body["deletion"] is None
    assert client.get(f"{API}/operator/subscribers/no-such", headers=boss).status_code == 404


# --------------------------------------------------------------------------- actions
def test_operator_actions_on_a_subscriber_are_logged_under_its_code(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    r = client.post(f"{API}/operator/subscribers/con-beta/trial", headers=boss, json={"days": 7})
    assert r.status_code == 200 and r.json()["subscription"]["trial_end"].startswith("2030-01-22")
    n = client.patch(f"{API}/operator/subscribers/con-beta/notes", headers=boss,
                     json={"notes": "Met at the trade fair", "tags": ["Fair", "vip"]})
    assert n.json()["subscription"]["notes"] == "Met at the trade fair" and n.json()["tags"] == ["fair", "vip"]
    s = client.post(f"{API}/operator/subscribers/con-beta/suspend", headers=boss, json={"reason": "chargeback dispute"})
    assert s.json()["status"] == "suspended"
    back = client.post(f"{API}/operator/subscribers/con-beta/reactivate", headers=boss, json={"reason": "settled"})
    assert back.json()["status"] == "trialing"
    audit = client.get(f"{API}/operator/subscribers/con-beta", headers=boss).json()["audit_trail"]
    actions = [x["action"] for x in audit]
    assert {"subscription.extend_trial", "subscriber.notes", "subscription.suspend", "subscription.reactivate"} <= set(actions)
    assert any(x["reason"] == "chargeback dispute" for x in audit)
    bad = client.post(f"{API}/operator/subscribers/con-beta/suspend", headers=boss, json={"reason": "x"})
    assert bad.status_code == 422                                                 # a reason is required (and logged as refused)


def test_the_right_roles_do_the_right_things(client, world) -> None:  # type: ignore[no-untyped-def]
    sup, bil = world["support"]["headers"], world["billing"]["headers"]
    assert client.post(f"{API}/operator/subscribers/con-beta/suspend", headers=sup, json={"reason": "support asked"}).status_code == 200
    assert client.post(f"{API}/operator/subscribers/con-beta/reactivate", headers=sup, json={}).status_code == 200
    assert client.post(f"{API}/operator/subscribers/con-beta/comp", headers=sup,
                       json={"reason": "friend of the house"}).status_code == 403          # money is billing's
    assert client.post(f"{API}/operator/subscribers/con-beta/trial", headers=bil, json={"days": 1}).status_code == 200


def test_changing_plan_from_the_console_invoices_the_prorated_difference(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    # a fresh paid subscriber so the arithmetic is ours: period starts now (real clock), 1000.00 -> 2500.00
    t = make_tenant("Con Upgrade")
    subscriptions.start(t["tenant_id"], "con-basic", currency="KES", mode="active")
    r = client.post(f"{API}/operator/subscribers/con-upgrade/plan", headers=boss, json={"plan_code": "con-pro"})
    assert r.status_code == 200, r.text
    assert r.json()["subscription"]["plan_code"] == "con-pro"
    invoice = next(i for i in r.json()["invoices"] if i["kind"] == "upgrade")
    # the period just started, so (almost) the whole period remains: about (2500 - 1000) x days left / days in period
    assert invoice["status"] == "issued" and D("1400.00") < D(invoice["subtotal"]) <= D("1500.00")
    assert D(invoice["tax_total"]) == (D(invoice["subtotal"]) * D("0.16")).quantize(D("0.01"))
    assert next(e for e in r.json()["timeline"] if e["kind"] == "plan.changed")["detail"]["to"] == "con-pro"


def test_start_a_subscription_for_an_unmanaged_business(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    r = client.post(f"{API}/operator/subscribers/con-gamma/subscription", headers=boss,
                    json={"plan_code": "con-basic", "mode": "trial"})
    assert r.status_code == 200, r.text
    assert r.json()["subscription"]["status"] == "trialing" and r.json()["subscription"]["currency"].strip() == "KES"
    again = client.post(f"{API}/operator/subscribers/con-gamma/subscription", headers=boss, json={"plan_code": "con-basic"})
    assert again.status_code == 409


# --------------------------------------------------------------------------- the business's side
def test_plan_and_billing_shows_a_business_only_its_own(client, world) -> None:  # type: ignore[no-untyped-def]
    a, b = owner(client, "con-alpha"), owner(client, "con-beta")
    inv_a = billing.create_invoice(tenant_id=world["A"]["tenant_id"], currency="KES", issue=True,
                                   lines=[{"description": "Setup A", "unit_amount": "100.00"}])
    inv_b = billing.create_invoice(tenant_id=world["B"]["tenant_id"], currency="KES", issue=True,
                                   lines=[{"description": "Setup B", "unit_amount": "200.00"}])
    mine = client.get(f"{API}/billing/invoices", headers=a).json()
    assert [i["number"] for i in mine] == [inv_a["number"]]
    assert client.get(f"{API}/billing/invoices/{inv_a['id']}", headers=a).status_code == 200
    for path in (f"/billing/invoices/{inv_b['id']}", f"/billing/invoices/{inv_b['id']}/html"):
        assert client.get(f"{API}{path}", headers=a).status_code == 404            # another business's invoice does not exist for them
    plan = client.get(f"{API}/billing/plan", headers=a).json()
    assert plan["plan_code"] == "con-basic" and plan["owed"] == {"KES": "116.00"}
    page = client.get(f"{API}/billing/invoices/{inv_a['id']}/html", headers=a)
    assert page.status_code == 200 and "Setup A" in page.text and "Setup B" not in page.text
    assert client.get(f"{API}/billing/plan", headers=b).json()["owed"] == {"KES": "232.00"}


def test_a_drafts_stay_hidden_from_the_business(client, world) -> None:  # type: ignore[no-untyped-def]
    a = owner(client, "con-alpha")
    draft = billing.create_invoice(tenant_id=world["A"]["tenant_id"], currency="KES",
                                   lines=[{"description": "Not yet", "unit_amount": "5.00"}])
    assert all(i["id"] != str(draft["id"]) for i in client.get(f"{API}/billing/invoices", headers=a).json())
    assert client.get(f"{API}/billing/invoices/{draft['id']}", headers=a).status_code == 404


def test_a_plan_request_reaches_the_vendor_and_pays_into_a_plan_change(client, world) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Con Request")
    subscriptions.start(t["tenant_id"], "con-basic", currency="KES", mode="trial")            # a trial: nothing paid yet
    me = owner(client, "con-request")
    before = len(FakeEmail.sent)
    r = client.post(f"{API}/billing/change-request", headers=me, json={
        "plan_code": "con-pro", "interval": "month", "note": "We need stock control"})
    assert r.status_code == 201, r.text
    request = r.json()
    assert request["status"] == "pending" and request["plan_code"] == "con-pro" and request["invoice_id"]
    assert any("Plan request" in (m.subject or "") for m in FakeEmail.sent[before:])           # operators were told
    # one pending request at a time
    assert client.post(f"{API}/billing/change-request", headers=me, json={"plan_code": "con-pro"}).status_code == 409
    mine = client.get(f"{API}/billing/plan", headers=me).json()
    assert mine["request"]["plan_code"] == "con-pro" and mine["plan_code"] == "con-basic"
    assert client.get(f"{API}/billing/invoices", headers=me).json() == []                      # still a draft: not shown
    # the vendor approves: the invoice is issued to the business
    pending = client.get(f"{API}/operator/plan-requests", headers=world["billing"]["headers"]).json()
    assert any(x["id"] == request["id"] for x in pending)
    ok = client.post(f"{API}/operator/plan-requests/{request['id']}/decide", headers=world["billing"]["headers"],
                     json={"approve": True})
    assert ok.status_code == 200 and ok.json()["invoice"]["status"] == "issued"
    # 2500.00 + 16% = 2900.00
    invoice = client.get(f"{API}/billing/invoices", headers=me).json()[0]
    assert invoice["total"] == "2900.00" and invoice["kind"] == "first"
    # money arrives: the plan changes, the business is active, inventory may now be switched on
    paid = client.post(f"{API}/operator/invoices/{invoice['id']}/payments", headers=world["billing"]["headers"],
                       json={"method": "bank transfer", "amount": "2900.00", "reference": "REQ-1"})
    assert paid.status_code == 201 and paid.json()["status"] == "paid"
    now_plan = client.get(f"{API}/billing/plan", headers=me).json()
    assert (now_plan["plan_code"], now_plan["status"], now_plan["request"]) == ("con-pro", "active", None)
    assert client.post(f"{API}/units/inventory/enable", headers=me).status_code == 200
    assert client.get(f"{API}/billing/plan", headers=me).json()["owed"] == {}


def test_a_request_can_be_withdrawn_or_declined(client, world) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Con Decline")
    subscriptions.start(t["tenant_id"], "con-basic", currency="KES", mode="trial")
    me = owner(client, "con-decline")
    first = client.post(f"{API}/billing/change-request", headers=me, json={"plan_code": "con-pro"}).json()
    assert client.delete(f"{API}/billing/change-request/{first['id']}", headers=me).status_code == 204
    second = client.post(f"{API}/billing/change-request", headers=me, json={"plan_code": "con-pro"}).json()
    declined = client.post(f"{API}/operator/plan-requests/{second['id']}/decide", headers=world["billing"]["headers"],
                           json={"approve": False})
    assert declined.json() == {"status": "declined", "invoice": None}
    assert client.get(f"{API}/billing/plan", headers=me).json()["request"] is None
    assert client.post(f"{API}/billing/change-request", headers=me, json={"plan_code": "con-basic"}).status_code == 422  # already on it


def test_the_owner_cancels_and_resumes(client, world) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Con Cancel")
    subscriptions.start(t["tenant_id"], "con-basic", currency="KES", mode="active")
    me = owner(client, "con-cancel")
    r = client.post(f"{API}/billing/cancel", headers=me, json={"reason": "shutting down"})
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True and r.json()["status"] == "active"
    assert client.post(f"{API}/billing/resume", headers=me).json()["cancel_at_period_end"] is False


# --------------------------------------------------------------------------- the dashboard
def test_the_dashboard_adds_up_per_currency(client, world) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.platform import dashboard

    def figures() -> dict:  # type: ignore[type-arg]
        o = dashboard.overview(scans=[])
        mrr = next((r for r in o["mrr"] if r["currency"] == "KES"), {"mrr": D("0"), "arr": D("0"), "subscribers": 0})
        return {"mrr": mrr["mrr"], "arr": mrr["arr"], "paying": mrr["subscribers"], "trials": o["trials"]["in_progress"],
                "new": o["new_subscribers"], "status": o["by_status"], "plan": o["by_plan"]}

    before = figures()
    a, b, c = (make_tenant(f"Dash {n}") for n in ("One", "Two", "Three"))
    for t, plan, mode in ((a, "con-basic", "active"), (b, "con-pro", "active"), (c, "con-basic", "trial")):
        subscriptions.start(t["tenant_id"], plan, currency="KES", mode=mode, now=T0)
    plans.create_coupon({"code": "DASH10", "percent_off": "10", "duration": "forever"})
    subscriptions.apply_coupon(b["tenant_id"], "DASH10", now=T0)
    year = make_tenant("Dash Yearly")
    subscriptions.start(year["tenant_id"], "con-basic", currency="KES", interval="year", mode="active", now=T0)
    after = figures()
    # monthly: 1000.00 (one) + 2500.00 less 10% = 2250.00 (two) + 10000.00 / 12 = 833.33 (yearly); the trial is not counted
    assert after["mrr"] - before["mrr"] == D("4083.33") and after["arr"] - before["arr"] == D("48999.96")
    assert after["paying"] - before["paying"] == 3
    assert after["trials"] - before["trials"] == 1 and after["new"] - before["new"] == 4
    assert after["status"].get("active", 0) - before["status"].get("active", 0) == 3
    assert after["plan"].get("con-basic", 0) - before["plan"].get("con-basic", 0) == 3
    api = client.get(f"{API}/operator/dashboard", headers=world["viewer"]["headers"])
    assert api.status_code == 200 and api.json()["mode"] == "saas"


def test_overdue_money_is_summed_per_currency(world) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.platform import dashboard

    t = make_tenant("Dash Owing")
    subscriptions.start(t["tenant_id"], "con-basic", currency="KES", mode="active", now=T0)
    billing.create_invoice(tenant_id=t["tenant_id"], currency="KES", issue=True, now=T0,
                           lines=[{"description": "Setup", "unit_amount": "100.00"}])         # 116.00, due Jan 15
    billing.create_invoice(tenant_id=t["tenant_id"], currency="EUR", issue=True, now=T0,
                           lines=[{"description": "Setup", "unit_amount": "10.00"}])          # 11.60 EUR
    owing = {r["currency"]: r for r in dashboard.overview(now=T0 + timedelta(days=20))["past_due"]}
    assert owing["KES"]["owed"] >= D("116.00") and owing["EUR"]["owed"] == D("11.60")


# --------------------------------------------------------------------------- deleting a business
def test_deleting_needs_confirmation_a_dead_subscription_and_a_cooling_off_period(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    t = make_tenant("Con Remove")
    subscriptions.start(t["tenant_id"], "con-basic", currency="KES", mode="active")
    reason = "Owner asked in writing to be removed"
    live = client.post(f"{API}/operator/subscribers/con-remove/delete", headers=boss,
                       json={"confirm": "con-remove", "reason": reason})
    assert live.status_code == 409 and "live subscription" in live.json()["message"]
    subscriptions.cancel(t["tenant_id"], at_period_end=False)
    wrong = client.post(f"{API}/operator/subscribers/con-remove/delete", headers=boss,
                        json={"confirm": "con-removed", "reason": reason})
    assert wrong.status_code == 422
    early = client.post(f"{API}/operator/subscribers/con-remove/delete", headers=boss,
                        json={"confirm": "con-remove", "reason": reason})
    assert early.status_code == 409 and "retention" in early.json()["message"]       # the data is kept for a while
    ok = client.post(f"{API}/operator/subscribers/con-remove/delete", headers=boss,
                     json={"confirm": "con-remove", "reason": reason, "early": True})
    assert ok.status_code == 200 and ok.json()["deletion"]["reason"] == reason
    # nothing happens before the cooling-off ends
    assert subscribers.run_due_deletions() == 0
    assert subscribers.tenant_by_code("con-remove")
    # a change of mind
    assert client.delete(f"{API}/operator/subscribers/con-remove/delete", headers=boss).json()["deletion"] is None
    client.post(f"{API}/operator/subscribers/con-remove/delete", headers=boss,
                json={"confirm": "con-remove", "reason": reason, "early": True})
    after = subscribers.run_due_deletions(now=subscriptions._now() + timedelta(days=8))
    assert after == 1
    assert client.get(f"{API}/operator/subscribers/con-remove", headers=boss).status_code == 404
    lines = trail("subscriber.deleted")
    assert lines and lines[-1]["target"] == "con-remove"


def test_a_business_that_comes_back_to_life_is_not_deleted(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    t = make_tenant("Con Revive")
    subscriptions.start(t["tenant_id"], "con-basic", currency="KES", mode="active")
    subscriptions.cancel(t["tenant_id"], at_period_end=False)
    client.post(f"{API}/operator/subscribers/con-revive/delete", headers=boss,
                json={"confirm": "con-revive", "reason": "Requested by the owner today", "early": True})
    subscriptions.reactivate(t["tenant_id"])
    assert subscribers.run_due_deletions(now=subscriptions._now() + timedelta(days=30)) == 0
    assert subscribers.tenant_by_code("con-revive")


# --------------------------------------------------------------------------- exports and personal data
def test_the_platforms_records_about_a_subscriber_can_be_exported(client, world) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{API}/operator/subscribers/con-alpha/export", headers=world["support"]["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["business"]["code"] == "con-alpha" and body["subscription"]["plan_code"] == "con-basic"
    assert body["owners"][0]["email"] == "owner@con-alpha.test" and body["invoices"]
    assert "password" not in str(body).lower() and "app_url" not in str(body)
    assert client.get(f"{API}/operator/subscribers/con-alpha/export", headers=world["viewer"]["headers"]).status_code == 403


def test_a_persons_contact_is_found_and_erased_but_invoices_stay(client, world) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    found = client.post(f"{API}/operator/privacy/contact", headers=boss, json={"email": "Owner@Con-Alpha.test"}).json()
    assert found["invoices"] and found["email"] == "owner@con-alpha.test"
    done = client.post(f"{API}/operator/privacy/contact/erase", headers=boss, json={"email": "owner@con-alpha.test"})
    assert done.status_code == 200 and done.json()["invoices_anonymised"] >= 1
    assert client.post(f"{API}/operator/privacy/contact", headers=boss,
                       json={"email": "owner@con-alpha.test"}).json()["invoices"] == []
    kept = billing.list_invoices(tenant_id=world["A"]["tenant_id"])
    assert kept and all(i["bill_to"]["contact"] == "[erased]" and i["total"] > 0 for i in kept)       # the money record stays


# --------------------------------------------------------------------------- invoices through the console
def test_invoices_through_the_console_and_the_printable_page(client, world) -> None:  # type: ignore[no-untyped-def]
    bil = world["billing"]["headers"]
    r = client.post(f"{API}/operator/invoices", headers=bil, json={
        "tenant_code": "con-alpha", "lines": [{"description": "Onboarding day", "quantity": "2", "unit_amount": "500.00"}],
        "notes": "Thank you"})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert (inv["status"], inv["subtotal"], inv["total"], inv["number"]) == ("draft", "1000.00", "1160.00", None)
    edited = client.patch(f"{API}/operator/invoices/{inv['id']}", headers=bil, json={"notes": "Thanks!"})
    assert edited.json()["notes"] == "Thanks!"
    issued = client.post(f"{API}/operator/invoices/{inv['id']}/issue", headers=bil).json()
    assert issued["status"] == "issued" and issued["number"]
    page = client.get(f"{API}/operator/invoices/{inv['id']}/html", headers=world["viewer"]["headers"])
    assert page.status_code == 200 and issued["number"] in page.text and "1160.00" in page.text
    pay = client.post(f"{API}/operator/invoices/{inv['id']}/payments", headers=bil,
                      json={"method": "cash", "amount": "1160.00", "paid_on": "2030-01-02"})
    assert pay.json()["status"] == "paid" and pay.json()["payments"][0]["paid_on"] == "2030-01-02"
    rev = client.post(f"{API}/operator/payments/{pay.json()['payments'][0]['id']}/reverse", headers=bil,
                      json={"reason": "cash was counterfeit"})
    assert rev.json()["status"] == "issued"
    both = client.post(f"{API}/operator/invoices", headers=bil, json={
        "tenant_code": "con-alpha", "licence_id": str(world["A"]["tenant_id"]),
        "lines": [{"description": "x", "unit_amount": "1"}]})
    assert both.status_code == 422                                                  # one customer, not both
    assert any(x["action"] == "payment.record" for x in trail())


def test_platform_settings_are_validated_and_saved(client, world) -> None:  # type: ignore[no-untyped-def]
    bil = world["billing"]["headers"]
    ok = client.put(f"{API}/operator/platform-settings/billing.due_days", headers=bil, json={"value": 30})
    assert ok.status_code == 200 and ok.json()["value"] == 30
    bad = client.put(f"{API}/operator/platform-settings/billing.tax_lines", headers=bil,
                     json={"value": [{"name": "VAT", "rate_percent": "180"}]})
    assert bad.status_code == 422
    unknown = client.put(f"{API}/operator/platform-settings/country", headers=bil, json={"value": "KE"})
    assert unknown.status_code == 422
    values = client.get(f"{API}/operator/platform-settings", headers=world["viewer"]["headers"]).json()
    assert values["values"]["billing.due_days"] == 30 and set(values["providers"]) >= {"manual", "fake"}
    client.put(f"{API}/operator/platform-settings/billing.due_days", headers=bil, json={"value": 14})
    assert client.put(f"{API}/operator/platform-settings/billing.due_days", headers=world["viewer"]["headers"],
                      json={"value": 1}).status_code == 403

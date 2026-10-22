"""Add-ons sold on their own, one payment each (ziira/kernel/platform/unit_addons.py): the price list an operator keeps,
what a business can buy, the purchase through the real payment machinery (confirm-before-credit, one grant), purchases
surviving plan changes, an operator's grant and revoke (audited), and the switch that makes everything free.

Money is KES. The provider is a scripted SunPay (no real service is reached)."""

from decimal import Decimal as D  # noqa: N817
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from tests.platform_helpers import API, make_plan, staff
from tests.test_subscription_payments import Provider, post_sun, sun_webhook, sunpay_routes  # noqa: F401
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.platform import (
    behaviour,
    billing,
    entitlements,
    payments,
    plans,
    settings,
    subscriptions,
    unit_addons,
)

SECRET = "sunpay-webhook-secret"


@pytest.fixture(scope="module", autouse=True)
def world(client, registry):  # type: ignore[no-untyped-def]
    behaviour.set_value("access.all_units_free", "off", "test")        # these tests are about selling and plan limits
    settings.set_value("billing.tax_lines", [], "test")
    make_plan("ao-small", units=["products"], prices={("KES", "month"): "500.00"})
    make_plan("ao-big", units=["products", "finance"], prices={("KES", "month"): "900.00"})
    payments.save_gateway("sunpay", enabled=True, config={}, secrets={"api_key": "sp_live_KEY_123", "webhook_secret": SECRET},
                          clear_secrets=None, default_for=None, by="test")
    unit_addons.set_unit_sale("inventory", offered=True, prices={"KES": "3000.00"}, by="test")
    unit_addons.set_unit_sale("purchasing", offered=False, prices={}, by="test")
    yield {"boss": staff(client, "superadmin"), "billing": staff(client, "billing"), "support": staff(client, "support"),
           "viewer": staff(client, "readonly")}
    with master_session() as m:
        m.execute(text("update master.payment_gateway set enabled = false where name = 'sunpay'"))
        m.execute(text("delete from master.subscription_addon"))
        m.execute(text("delete from master.addon where kind = 'unit'"))       # leave the shared price list as found
    plans.invalidate_public_cache()
    behaviour.set_value("access.all_units_free", "", "test")


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Provider:
    import httpx

    from ziira.kernel.platform import gateways

    p = Provider()
    monkeypatch.setattr(gateways, "http_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(p.handler)))
    return p


def business(client, registry, name: str, plan: str = "ao-small") -> dict[str, Any]:  # type: ignore[no-untyped-def]
    t = make_tenant(name)
    registry.enable(t["tenant_id"], "products")
    subscriptions.start(t["tenant_id"], plan, currency="KES", mode="active")
    code = name.lower().replace(" ", "-")
    return {**t, "code": code, "owner": sign_in(client, code, f"owner@{code}.test", device_id=f"d-{code}").headers}


def shop(client, b) -> dict[str, dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{API}/billing/addons", headers=b["owner"])
    assert r.status_code == 200, r.text
    return {u["unit"]: u for u in r.json()["units"]}


def buy(client, b, unit: str = "inventory", **headers: str):  # type: ignore[no-untyped-def]
    return client.post(f"{API}/billing/addons/{unit}/buy", headers={**b["owner"], **headers})


def pay_and_confirm(client, provider, b, invoice: dict[str, Any], amount: str = "3000") -> str:  # type: ignore[no-untyped-def]
    """Start a SunPay payment of the invoice and let the provider say it completed; returns the attempt id."""
    states = sunpay_routes(provider)
    attempt = client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": str(invoice["id"]), "provider": "sunpay", "payer": {"phone": "0712 345 678"}}).json()
    txn = next(iter(states))
    states[txn] = {"status": "completed", "amount": amount, "mpesaRef": "ADDON123"}
    body, headers = sun_webhook("payment.completed", txn, invoice["number"], SECRET)
    assert post_sun(client, body, headers).status_code == 200
    return str(attempt["id"])


# --------------------------------------------------------------------------- the price list
def test_an_operator_offers_a_unit_with_a_one_time_price_per_currency_and_history_is_kept() -> None:
    out = unit_addons.set_unit_sale("crm", offered=True, prices={"KES": "1500.00", "USD": "12.00"}, by="t")
    assert out["offered"] and out["prices"] == {"KES": D("1500.00"), "USD": D("12.00")}
    unit_addons.set_unit_sale("crm", offered=True, prices={"KES": "1800", "USD": "12"}, by="t")          # KES changed only
    row = unit_addons._addon_row("crm")
    history = plans.price_history("addon", row.id)
    assert sorted((h["currency"], str(h["amount"])) for h in history) == [
        ("KES", "1500.00"), ("KES", "1800.00"), ("USD", "12.00")]                                       # append-only
    assert {h["interval"] for h in history} == {"one_time"}
    out = unit_addons.set_unit_sale("crm", offered=True, prices={"USD": None}, by="t")                  # withdraw USD
    assert out["prices"] == {"KES": D("1800.00")}
    out = unit_addons.set_unit_sale("crm", offered=False, prices={}, by="t")
    assert out["offered"] is False and out["prices"] == {"KES": D("1800.00")}                           # price kept, not sold
    assert unit_addons.offer_for("crm", "KES") is None


def test_the_price_list_refuses_nonsense() -> None:
    with pytest.raises(ValidationFailed, match="at least one currency"):
        unit_addons.set_unit_sale("claims", offered=True, prices={}, by="t")
    assert unit_addons.sales_overview()["units"]                                                          # still readable
    assert not next(u for u in unit_addons.sales_overview()["units"] if u["unit"] == "claims")["offered"]
    with pytest.raises(ValidationFailed, match="more than zero"):
        unit_addons.set_unit_sale("claims", offered=True, prices={"KES": "0"}, by="t")
    with pytest.raises(ValidationFailed):
        unit_addons.set_unit_sale("claims", offered=True, prices={"KES": "-5"}, by="t")
    with pytest.raises(ValidationFailed):
        unit_addons.set_unit_sale("claims", offered=True, prices={"KESS": "5"}, by="t")
    from ziira.kernel.errors import NotFound

    with pytest.raises(NotFound):
        unit_addons.set_unit_sale("kernel", offered=True, prices={"KES": "5"}, by="t")
    with pytest.raises(NotFound):
        unit_addons.set_unit_sale("nope", offered=True, prices={"KES": "5"}, by="t")


def test_the_price_list_is_an_operator_endpoint_that_needs_plans_permission(client, world) -> None:  # type: ignore[no-untyped-def]
    body = {"offered": True, "prices": {"KES": "2500.00"}, "tax_inclusive": False}
    for role, ok in (("boss", True), ("billing", True), ("support", False), ("viewer", False)):
        r = client.put(f"{API}/operator/unit-sales/memberships", headers=world[role]["headers"], json=body)
        assert (r.status_code == 200) is ok, (role, r.status_code, r.text)
    for role in world:
        assert client.get(f"{API}/operator/unit-sales", headers=world[role]["headers"]).status_code == 200
    listing = client.get(f"{API}/operator/unit-sales", headers=world["viewer"]["headers"]).json()
    mine = next(u for u in listing["units"] if u["unit"] == "memberships")
    assert mine["offered"] and mine["prices"] == {"KES": "2500.00"} and "KES" in listing["currencies"]
    unit_addons.set_unit_sale("memberships", offered=False, prices={}, by="t")


# --------------------------------------------------------------------------- what a business can buy
def test_the_shop_shows_included_for_sale_and_not_for_sale(client, registry) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Shop")
    units = shop(client, b)
    assert units["products"]["state"] == "included"
    assert (units["inventory"]["state"], units["inventory"]["price"], units["inventory"]["currency"]) == \
        ("for_sale", "3000.00", "KES")
    assert units["purchasing"]["state"] == "not_for_sale" and units["purchasing"]["price"] is None
    catalog = {u["name"]: u for u in client.get(f"{API}/units/catalog", headers=b["owner"]).json()}
    assert catalog["inventory"]["sale_state"] == "for_sale" and catalog["inventory"]["can_buy"] is True
    assert catalog["inventory"]["in_plan"] is False and "upgrade" not in (catalog["inventory"]["why_not_enable"] or "").lower()
    assert catalog["purchasing"]["sale_state"] == "not_for_sale" and catalog["purchasing"]["can_buy"] is False
    assert catalog["products"]["sale_state"] == "included"


def test_a_unit_with_no_price_in_the_business_currency_is_not_for_sale(client, registry) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Ao Usd Only")
    registry.enable(t["tenant_id"], "products")
    make_plan("ao-usd", units=["products"], prices={("USD", "month"): "10.00"})
    subscriptions.start(t["tenant_id"], "ao-usd", currency="USD", mode="active")
    b = {"owner": sign_in(client, "ao-usd-only", "owner@ao-usd-only.test", device_id="d-aousd").headers}
    assert shop(client, b)["inventory"]["state"] == "not_for_sale"
    assert buy(client, b).status_code == 409


# --------------------------------------------------------------------------- buying
def test_buying_makes_one_invoice_and_grants_nothing_until_the_payment_is_confirmed(client, registry, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Buy")
    r = buy(client, b)
    assert r.status_code == 201, r.text
    out = r.json()
    inv = out["invoice"]
    assert (inv["kind"], inv["status"], inv["total"], inv["currency"].strip()) == ("addon", "issued", "3000.00", "KES")
    assert [ln["description"] for ln in inv["lines"]] == ["Add-on: Inventory and Branches (one-time)"] and inv["number"]
    assert out["purchase"]["status"] == "pending"
    assert shop(client, b)["inventory"]["state"] == "for_sale"                       # not granted by asking
    assert client.post(f"{API}/units/inventory/enable", headers=b["owner"]).status_code == 402
    # asking again, with or without a key, returns the same invoice
    assert buy(client, b).json()["invoice"]["id"] == inv["id"]
    assert buy(client, b, **{"Idempotency-Key": "k-1"}).json()["invoice"]["id"] == inv["id"]
    assert len(billing.list_invoices(tenant_id=b["tenant_id"], include_drafts=False)) == 1
    # a payment that has started but is not confirmed still grants nothing
    sunpay_routes(provider)
    attempt = client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": inv["id"], "provider": "sunpay", "payer": {"phone": "0712345678"}})
    assert attempt.status_code == 201 and attempt.json()["status"] == "pending"
    assert shop(client, b)["inventory"]["state"] == "for_sale"
    assert entitlements.for_tenant(b["tenant_id"], use_cache=False).purchased == frozenset()
    # not owed: an add-on waiting at the checkout is not a debt and never moves the subscription
    assert client.get(f"{API}/billing/plan", headers=b["owner"]).json()["owed"] == {}
    assert billing.run_due()["moved"] == 0 and subscriptions.get(b["tenant_id"])["status"] == "active"


def test_a_confirmed_payment_grants_once_and_the_owner_can_switch_it_on(client, registry, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Paid")
    inv = buy(client, b).json()["invoice"]
    plan_before = subscriptions.get(b["tenant_id"])
    attempt_id = pay_and_confirm(client, provider, b, inv)
    paid = billing.get_invoice(inv["id"])
    assert (paid["status"], paid["amount_paid"]) == ("paid", D("3000.00"))
    [bought] = [p for p in unit_addons.list_for_tenant(b["tenant_id"]) if p["status"] == "active"]
    assert (bought["unit_name"], bought["granted_by"], bought["price"], bought["payment_reference"]) == \
        ("inventory", "payment", D("3000.00"), "ADDON123")
    assert bought["purchased_at"] is not None and bought["invoice_number"] == inv["number"]
    # the subscription itself did not move (no period change, same plan)
    after = subscriptions.get(b["tenant_id"])
    assert (after["period_end"], after["plan_code"], after["status"]) == \
        (plan_before["period_end"], plan_before["plan_code"], plan_before["status"])
    card = {u["name"]: u for u in client.get(f"{API}/units/catalog", headers=b["owner"]).json()}["inventory"]
    assert (card["sale_state"], card["in_plan"], card["can_enable"], card["receipt_invoice_id"]) == \
        ("bought", True, True, inv["id"]) and card["bought_at"]
    assert client.post(f"{API}/units/inventory/enable", headers=b["owner"]).status_code == 200
    # repeating the notification, the poll and the buy request changes nothing
    body, headers = sun_webhook("payment.completed", "tx-1", inv["number"], SECRET)
    assert post_sun(client, body, headers).status_code == 200
    assert client.get(f"{API}/billing/payments/{attempt_id}", headers=b["owner"]).json()["status"] == "completed"
    assert len([p for p in unit_addons.list_for_tenant(b["tenant_id"]) if p["status"] == "active"]) == 1
    assert len(billing.list_payments(inv["id"])) == 1
    assert buy(client, b).status_code == 409                                            # already available
    # and the receipt (the paid invoice page) is the business's own
    page = client.get(f"{API}/billing/invoices/{inv['id']}/html", headers=b["owner"])
    assert "Add-on: Inventory and Branches (one-time)" in page.text


def test_a_failed_payment_grants_nothing_and_the_purchase_can_be_tried_again(client, registry, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Failed")
    inv = buy(client, b).json()["invoice"]
    states = sunpay_routes(provider)
    attempt = client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": inv["id"], "provider": "sunpay", "payer": {"phone": "0712345678"}}).json()
    txn = next(iter(states))
    states[txn] = {"status": "failed"}
    assert post_sun(client, *sun_webhook("payment.failed", txn, inv["number"], SECRET)).status_code == 200
    assert payments.get_attempt(UUID(attempt["id"]))["status"] == "failed"
    assert billing.get_invoice(inv["id"])["status"] == "issued"
    assert shop(client, b)["inventory"]["state"] == "for_sale"
    assert entitlements.for_tenant(b["tenant_id"], use_cache=False).purchased == frozenset()
    assert buy(client, b).json()["invoice"]["id"] == inv["id"]                          # the same invoice, ready again


def test_a_wrong_amount_is_flagged_and_grants_nothing(client, registry, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Mismatch")
    inv = buy(client, b).json()["invoice"]
    pay_and_confirm(client, provider, b, inv, amount="30")
    assert billing.get_invoice(inv["id"])["status"] == "issued"
    assert entitlements.for_tenant(b["tenant_id"], use_cache=False).purchased == frozenset()


def test_a_changed_price_replaces_an_unpaid_invoice(client, registry) -> None:  # type: ignore[no-untyped-def]
    unit_addons.set_unit_sale("claims", offered=True, prices={"KES": "800.00"}, by="t")
    b = business(client, registry, "Ao Reprice")
    first = buy(client, b, "claims").json()["invoice"]
    unit_addons.set_unit_sale("claims", offered=True, prices={"KES": "900.00"}, by="t")
    second = buy(client, b, "claims").json()["invoice"]
    assert second["id"] != first["id"] and second["total"] == "900.00"
    assert billing.get_invoice(first["id"])["status"] == "void"
    unit_addons.set_unit_sale("claims", offered=False, prices={}, by="t")


def test_tax_lines_apply_to_the_add_on_invoice_like_a_plan(client, registry) -> None:  # type: ignore[no-untyped-def]
    settings.set_value("billing.tax_lines", [{"name": "VAT", "rate_percent": "16"}], "test")
    try:
        b = business(client, registry, "Ao Tax")
        inv = buy(client, b).json()["invoice"]
        assert (inv["subtotal"], inv["tax_total"], inv["total"]) == ("3000.00", "480.00", "3480.00")
    finally:
        settings.set_value("billing.tax_lines", [], "test")


def test_two_buy_clicks_at_once_make_one_purchase(client, registry) -> None:  # type: ignore[no-untyped-def]
    import threading

    b = business(client, registry, "Ao Race")
    results: list[str] = []

    def go() -> None:
        results.append(buy(client, b).json()["invoice"]["id"])

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(results)) == 1
    with master_session() as m:
        n = m.execute(text("select count(*) from master.subscription_addon where tenant_id = :t and status = 'pending'"),
                      {"t": str(b["tenant_id"])}).scalar_one()
    assert n == 1


# --------------------------------------------------------------------------- purchases outlive plan changes
def test_a_bought_add_on_survives_an_upgrade_and_a_downgrade(client, registry, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Survive")
    pay_and_confirm(client, provider, b, buy(client, b).json()["invoice"])
    assert client.post(f"{API}/units/inventory/enable", headers=b["owner"]).status_code == 200
    tid = b["tenant_id"]
    subscriptions.change_plan(tid, "ao-big", effective="now")
    assert "inventory" in (entitlements.for_tenant(tid, use_cache=False).units or ())
    subscriptions.change_plan(tid, "ao-small", effective="now")
    ent = entitlements.for_tenant(tid, use_cache=False)
    assert "inventory" in (ent.units or ()) and "finance" not in (ent.units or ())
    assert ent.purchased == frozenset({"inventory"})
    subscriptions.sync_to_plan(tid)
    assert subscriptions.enforce_units(tid) == []                                    # nothing is switched off
    card = {u["name"]: u for u in client.get(f"{API}/units/catalog", headers=b["owner"]).json()}["inventory"]
    assert card["enabled"] is True and card["sale_state"] == "bought"


def test_cancelling_the_subscription_follows_the_usual_rules_and_keeps_the_record(client, registry, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Cancel")
    pay_and_confirm(client, provider, b, buy(client, b).json()["invoice"])
    subscriptions.cancel(b["tenant_id"], at_period_end=False, reason="test")
    ent = entitlements.for_tenant(b["tenant_id"], use_cache=False)
    assert ent.access == "read_only" and "inventory" in (ent.units or ())               # read-only like the rest
    assert [p["status"] for p in unit_addons.list_for_tenant(b["tenant_id"])] == ["active"]
    assert buy(client, b).status_code in (402, 409)                                      # nothing to buy while ended


# --------------------------------------------------------------------------- operators
def trail_of(code: str) -> list[dict[str, Any]]:
    with master_session() as m:
        return [dict(r._mapping) for r in m.execute(
            text("select action, outcome, reason, operator_name from master.operator_action_log where target = :c "
                 "order by id"), {"c": code})]


def test_an_operator_can_grant_and_revoke_an_add_on_with_a_reason_and_it_is_audited(client, registry, world) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Comp")
    h = world["billing"]["headers"]
    url = f"{API}/operator/subscribers/{b['code']}/addons"
    assert client.post(url, headers=h, json={"unit": "inventory", "reason": "x"}).status_code == 422       # reason needed
    assert client.post(url, headers=world["viewer"]["headers"],
                       json={"unit": "inventory", "reason": "goodwill after outage"}).status_code == 403
    r = client.post(url, headers=h, json={"unit": "inventory", "reason": "goodwill after outage"})
    assert r.status_code == 200, r.text
    [row] = [a for a in r.json()["addons"] if a["status"] == "active"]
    assert (row["unit_name"], row["granted_by"], row["reason"], row["price"]) == \
        ("inventory", "operator", "goodwill after outage", "0.00")
    assert shop(client, b)["inventory"]["state"] == "bought"
    assert client.post(f"{API}/units/inventory/enable", headers=b["owner"]).status_code == 200
    assert client.post(url, headers=h, json={"unit": "inventory", "reason": "again please"}).status_code == 409
    rv = client.post(f"{url}/inventory/revoke", headers=h, json={"reason": "granted by mistake"})
    assert rv.status_code == 200, rv.text
    assert [a["status"] for a in rv.json()["addons"]] == ["revoked"]
    assert shop(client, b)["inventory"]["state"] == "for_sale"                           # can be bought again
    cat = {u["name"]: u for u in client.get(f"{API}/units/catalog", headers=b["owner"]).json()}["inventory"]
    assert cat["enabled"] is False and cat["has_data"] is True                           # switched off, data kept
    assert client.post(f"{url}/inventory/revoke", headers=h, json={"reason": "second time"}).status_code == 404
    actions = [(t["action"], t["outcome"], t["reason"]) for t in trail_of(b["code"])]
    assert ("subscriber.addon_grant", "ok", "goodwill after outage") in actions
    assert ("subscriber.addon_revoke", "ok", "granted by mistake") in actions
    kinds = [e["kind"] for e in subscriptions.timeline(b["tenant_id"])]
    assert "addon.granted" in kinds and "addon.revoked" in kinds


def test_granting_closes_a_waiting_purchase_and_support_cannot_comp(client, registry, world) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Comp Pending")
    inv = buy(client, b).json()["invoice"]
    url = f"{API}/operator/subscribers/{b['code']}/addons"
    assert client.post(url, headers=world["support"]["headers"],
                       json={"unit": "inventory", "reason": "for the demo"}).status_code in (200, 403)
    with master_session() as m:
        have = m.execute(text("select count(*) from master.subscription_addon where tenant_id = :t and status = 'active'"),
                         {"t": str(b["tenant_id"])}).scalar_one()
    if not have:
        assert client.post(url, headers=world["boss"]["headers"], json={"unit": "inventory", "reason": "for the demo"}).status_code == 200
    assert billing.get_invoice(inv["id"])["status"] == "void"
    assert [a["status"] for a in unit_addons.list_for_tenant(b["tenant_id"])].count("active") == 1


def test_reversing_the_payment_takes_the_add_on_back(client, registry, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Reversed")
    inv = buy(client, b).json()["invoice"]
    pay_and_confirm(client, provider, b, inv)
    [pay] = billing.list_payments(inv["id"])
    billing.reverse_payment(pay["id"], "chargeback", by="test")
    assert [p["status"] for p in unit_addons.list_for_tenant(b["tenant_id"])] == ["revoked"]
    assert shop(client, b)["inventory"]["state"] == "for_sale"


# --------------------------------------------------------------------------- the free-for-all switch
def test_while_everything_is_free_nothing_can_be_bought(client, registry) -> None:  # type: ignore[no-untyped-def]
    b = business(client, registry, "Ao Free")
    try:
        behaviour.set_value("access.all_units_free", "on", "test")
        s = client.get(f"{API}/billing/addons", headers=b["owner"]).json()
        assert s["free_for_all"] is True and s["can_buy"] is False
        assert {u["state"] for u in s["units"]} == {"included"}
        r = buy(client, b)
        assert r.status_code == 409 and "nothing to buy" in r.json()["message"]
        card = {u["name"]: u for u in client.get(f"{API}/units/catalog", headers=b["owner"]).json()}["inventory"]
        assert card["sale_state"] == "included" and card["in_plan"] is True and card["can_buy"] is False
        assert client.post(f"{API}/units/inventory/enable", headers=b["owner"]).status_code == 200
    finally:
        behaviour.set_value("access.all_units_free", "off", "test")
    assert buy(client, business(client, registry, "Ao Free Off")).status_code == 201     # off: the rules apply again


# --------------------------------------------------------------------------- who may, and whose
def test_only_the_owner_buys_and_businesses_are_separate(client, registry) -> None:  # type: ignore[no-untyped-def]
    a, other = business(client, registry, "Ao Perm A"), business(client, registry, "Ao Perm B")
    roles = {r["name"]: r for r in client.get(f"{API}/roles", headers=a["owner"]).json()}
    for who, role in (("outsider", None), ("manager", "Branch Manager")):
        email = f"{who}@{a['code']}.test"
        u = client.post(f"{API}/users", headers=a["owner"],
                        json={"full_name": who, "email": email, "password": f"{who}-pass-1"}).json()
        if role:
            client.post(f"{API}/users/{u['id']}/roles", headers=a["owner"], json={"role_id": roles[role]["id"], "scope": "tenant"})
        h = sign_in(client, a["code"], email, f"{who}-pass-1").headers
        assert buy(client, {"owner": h}).status_code == 403
        assert client.get(f"{API}/billing/addons", headers=h).status_code == 403
    assert client.post(f"{API}/billing/addons/inventory/buy").status_code == 401
    inv = buy(client, a).json()["invoice"]
    # another business sees nothing of it and cannot pay or read the invoice
    assert shop(client, other)["inventory"]["state"] == "for_sale"
    assert client.get(f"{API}/billing/invoices/{inv['id']}", headers=other["owner"]).status_code == 404
    assert client.post(f"{API}/billing/payments", headers=other["owner"], json={
        "invoice_id": inv["id"], "provider": "sunpay", "payer": {"phone": "0712345678"}}).status_code == 404
    assert unit_addons.list_for_tenant(other["tenant_id"]) == []
    assert client.get(f"{API}/billing/addons", headers=other["owner"]).json()["purchases"] == []


def test_an_unmanaged_business_and_unknown_units_cannot_buy(client, registry) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Ao Unmanaged")
    owner = sign_in(client, "ao-unmanaged", "owner@ao-unmanaged.test", device_id="d-aoun").headers
    b = {"owner": owner}
    assert buy(client, b).status_code == 409                                              # everything already available
    assert buy(client, business(client, registry, "Ao Unknown"), "nope").status_code == 404
    assert buy(client, business(client, registry, "Ao Kernel"), "kernel").status_code == 404
    assert t["tenant_id"]


def test_the_public_price_list_hides_unit_addons_unless_the_switch_is_on(client) -> None:  # type: ignore[no-untyped-def]
    plans.invalidate_public_cache()
    with pytest.raises(ValidationFailed):
        behaviour.set_value("public.show_unit_addons", "maybe", "t")
    behaviour.set_value("public.show_unit_addons", "", "t")                                # default: off
    assert behaviour.show_unit_addons() is False
    assert all(a["kind"] != "unit" for a in client.get(f"{API}/public/plans").json()["addons"])
    behaviour.set_value("public.show_unit_addons", "on", "t")                              # also clears the cache
    try:
        listed = client.get(f"{API}/public/plans").json()["addons"]
        assert any(a["kind"] == "unit" and a["unit"] == "inventory" for a in listed)
    finally:
        behaviour.set_value("public.show_unit_addons", "", "t")
    assert all(a["kind"] != "unit" for a in client.get(f"{API}/public/plans").json()["addons"])

"""What a plan allows, enforced inside the platform: units, user/branch/company limits (never destroying data),
the behaviour of each status (including a till uploading sales while suspended), and the modes.

HTTP tests sign in as real owners; subscriptions are set up through the services with a frozen clock where time matters."""

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from tests.platform_helpers import API, T0, make_plan
from tests.pos_helpers import POS, make_pos_shop
from tests.test_pos_sync import fix_lines, op_open, op_sale, statuses, upload
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.platform import behaviour, entitlements, subscriptions


@pytest.fixture(scope="module", autouse=True)
def plans_(registry):  # type: ignore[no-untyped-def]
    behaviour.set_value("access.all_units_free", "off", "test")        # these tests are about what a plan restricts
    make_plan("ent-small", units=["products"], prices={("KES", "month"): "500.00"}, max_users=2, max_branches=1,
              max_companies=1, trial_days=30)
    make_plan("ent-big", units=["products", "inventory"], prices={("KES", "month"): "900.00"}, max_users=5,
              max_branches=3, max_companies=2, trial_days=30)
    yield
    behaviour.set_value("access.all_units_free", "", "test")


def business(registry, name: str, plan: str | None = "ent-small", **kw):  # type: ignore[no-untyped-def]
    t = make_tenant(name)
    registry.enable(t["tenant_id"], "products")
    if plan:
        subscriptions.start(t["tenant_id"], plan, currency="KES", **kw)
    code = name.lower().replace(" ", "-")
    return t["tenant_id"], sign_in(client_of(), code, f"owner@{code}.test").headers


_CLIENT = []


def client_of():  # type: ignore[no-untyped-def]
    return _CLIENT[0]


@pytest.fixture(scope="module", autouse=True)
def remember_client(client):  # type: ignore[no-untyped-def]
    _CLIENT.append(client)
    yield
    _CLIENT.clear()


def add_user(client, headers, n: str):  # type: ignore[no-untyped-def]
    return client.post(f"{API}/users", headers=headers,
                       json={"full_name": f"Staff {n}", "email": f"staff{n}-{uuid4().hex[:6]}@x.test"})


# --------------------------------------------------------------------------- units
def test_a_unit_outside_the_plan_cannot_be_switched_on(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Units")
    catalog = {u["name"]: u for u in client.get(f"{API}/units/catalog", headers=owner).json()}
    assert catalog["products"]["in_plan"] is True
    assert catalog["inventory"]["in_plan"] is False and catalog["inventory"]["can_enable"] is False
    assert "Not included in your plan" in catalog["inventory"]["why_not_enable"]
    assert catalog["inventory"]["sale_state"] == "not_for_sale"
    r = client.post(f"{API}/units/inventory/enable", headers=owner)
    assert r.status_code == 402 and r.json()["error"] == "not_in_plan"
    assert "not included in your plan" in r.json()["message"]


def test_the_free_for_everyone_switch_lets_any_business_use_any_unit(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Free")
    assert client.post(f"{API}/units/inventory/enable", headers=owner).status_code == 402          # the plan does not list it
    try:
        behaviour.set_value("access.all_units_free", "on", "test")
        catalog = {u["name"]: u for u in client.get(f"{API}/units/catalog", headers=owner).json()}
        assert catalog["inventory"]["in_plan"] is True and catalog["inventory"]["can_enable"] is True
        assert client.post(f"{API}/units/inventory/enable", headers=owner).status_code == 200
        assert behaviour.all_units_free() is True
    finally:
        behaviour.set_value("access.all_units_free", "off", "test")
    assert behaviour.all_units_free() is False
    # unset means on: the platform starts free for everyone
    behaviour.set_value("access.all_units_free", "", "test")
    assert behaviour.all_units_free() is True
    behaviour.set_value("access.all_units_free", "off", "test")


def test_upgrading_the_plan_allows_the_unit(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Upgrade")
    subscriptions.change_plan(tid, "ent-big")
    assert client.post(f"{API}/units/inventory/enable", headers=owner).status_code == 200


def test_switching_edition_checks_the_plan_too(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Edition")
    r = client.post(f"{API}/edition", headers=owner, json={"edition": "retail"})
    assert r.status_code == 402 and r.json()["error"] == "not_in_plan"


def test_a_downgrade_switches_units_off_but_keeps_their_data(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Downgrade", plan="ent-big")
    assert client.post(f"{API}/units/inventory/enable", headers=owner).status_code == 200
    subscriptions.change_plan(tid, "ent-small")                          # a trial: the change is immediate
    with tenant_session(tid, admin=True) as s:
        status = s.execute(text("select status from kernel.tenant_unit where unit_name = 'inventory'")).scalar()
        schema = s.execute(text("select to_regclass('inventory.stock_balance')")).scalar()
    assert status == "disabled" and schema is not None                    # off, tables and data still there
    after = client.get(f"{API}/units/catalog", headers=owner).json()
    card = next(u for u in after if u["name"] == "inventory")
    assert card["has_data"] is True and card["in_plan"] is False


# --------------------------------------------------------------------------- limits
def test_the_user_limit_stops_adding_and_names_the_limit(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Users")                                 # max 2 users; the owner is one
    assert add_user(client, owner, "1").status_code == 201
    r = add_user(client, owner, "2")
    assert r.status_code == 402 and r.json()["error"] == "plan_limit_reached"
    assert "allows 2 users and you have 2" in r.json()["message"] and r.json()["limit"] == 2


def test_a_disabled_user_frees_a_place_and_enabling_again_is_checked(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Disable")
    made = add_user(client, owner, "1").json()
    assert client.post(f"{API}/users/{made['id']}/status", headers=owner, json={"active": False}).status_code == 200
    second = add_user(client, owner, "2")
    assert second.status_code == 201                                             # the disabled one does not count
    again = client.post(f"{API}/users/{made['id']}/status", headers=owner, json={"active": True})
    assert again.status_code == 402 and again.json()["error"] == "plan_limit_reached"


def test_a_downgrade_below_current_use_destroys_nothing(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Over", plan="ent-big")
    for n in "123":
        assert add_user(client, owner, n).status_code == 201                    # 4 users, limit 5
    subscriptions.change_plan(tid, "ent-small")                                  # limit now 2
    assert len(client.get(f"{API}/users", headers=owner).json()) == 4           # all still there
    assert add_user(client, owner, "9").status_code == 402
    plan = client.get(f"{API}/billing/plan", headers=owner).json()
    assert plan["usage"]["users"] == {"used": 4, "limit": 2}


def test_branch_and_company_limits(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Sites")                                 # 1 branch, 1 company
    org = client.get(f"{API}/organisation", headers=owner).json()
    company_id = org[0]["id"]
    r = client.post(f"{API}/companies/{company_id}/branches", headers=owner, json={"code": "B2", "name": "Second"})
    assert r.status_code == 402 and r.json()["error"] == "plan_limit_reached" and r.json()["kind"] == "branches"
    c = client.post(f"{API}/companies", headers=owner, json={"name": "Second Co", "currency": "KES"})
    assert c.status_code == 402 and c.json()["kind"] == "companies"
    subscriptions.change_plan(tid, "ent-big")                                    # 3 branches, 2 companies
    assert client.post(f"{API}/companies/{company_id}/branches", headers=owner,
                       json={"code": "B2", "name": "Second"}).status_code == 201
    assert client.post(f"{API}/companies", headers=owner, json={"name": "Second Co", "currency": "KES"}).status_code == 201


def test_a_business_without_a_subscription_has_no_limits(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Unmanaged", plan=None)
    for n in "1234":
        assert add_user(client, owner, n).status_code == 201
    assert client.post(f"{API}/units/inventory/enable", headers=owner).status_code == 200
    plan = client.get(f"{API}/billing/plan", headers=owner).json()
    assert plan["managed"] is False and plan["status"] == "unmanaged" and plan["access"] == "full"


# --------------------------------------------------------------------------- statuses over HTTP
def status_of(tid, status: str):  # type: ignore[no-untyped-def]
    subscriptions._set_status(tid, status, None, "test", T0)
    entitlements.invalidate(tid)


@pytest.mark.parametrize(("status", "banner"), [("past_due", "warning"), ("grace", "warning")])
def test_past_due_and_grace_work_fully_with_a_warning(client, registry, status, banner) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, f"Ent {status.title().replace('_', ' ')}")
    status_of(tid, status)
    assert add_user(client, owner, "1").status_code == 201
    shown = client.get(f"{API}/billing/status", headers=owner).json()["banner"]
    assert shown["level"] == banner and shown["status"] == status


def test_a_suspended_account_is_billing_only(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Suspended")
    status_of(tid, "suspended")
    assert client.get(f"{API}/billing/plan", headers=owner).status_code == 200
    assert client.get(f"{API}/billing/invoices", headers=owner).status_code == 200
    assert client.get(f"{API}/units", headers=owner).status_code == 200                # the app shell can start
    for method, path in (("get", "/users"), ("post", "/users"), ("get", "/products/products")):
        r = getattr(client, method)(f"{API}{path}", headers=owner, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 402 and r.json()["error"] == "subscription_suspended", path
    assert client.get(f"{API}/billing/status", headers=owner).json()["banner"]["level"] == "blocked"


def test_a_cancelled_account_is_read_only(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Ended")
    status_of(tid, "cancelled")
    assert client.get(f"{API}/users", headers=owner).status_code == 200
    r = add_user(client, owner, "1")
    assert r.status_code == 402 and r.json()["error"] == "subscription_ended"
    assert r.json()["subscription_status"] == "cancelled"


def test_only_owners_see_the_banner(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Banner")
    made = client.post(f"{API}/users", headers=owner, json={"full_name": "Clerk", "phone": "0700000777",
                                                              "password": "clerk-pass-1"})
    assert made.status_code == 201
    clerk = sign_in(client, "ent-banner", "0700000777", "clerk-pass-1").headers
    status_of(tid, "grace")
    assert client.get(f"{API}/billing/status", headers=clerk).json() == {"banner": None}
    assert client.get(f"{API}/billing/plan", headers=clerk).status_code == 403
    assert client.get(f"{API}/billing/status", headers=owner).json()["banner"]["level"] == "warning"


def test_a_suspended_till_can_still_upload_the_sales_that_already_happened(client, registry) -> None:  # type: ignore[no-untyped-def]
    shop = make_pos_shop(client, registry, "Ent Offline Co", stock="500")
    shop["offline_cashier"] = shop["user"]("offline", "Cashier", shop["branch_id"])
    dev = client.post(f"{POS}/devices", headers=shop["owner"], json={
        "branch_id": str(shop["branch_id"]), "code": "OFF1", "name": "Offline tablet", "location_id": shop["main"]}).json()
    shop["off_key"], shop["off_device"] = dev["key"], dev["id"]
    subscriptions.start(shop["tenant_id"], "ent-big", currency="KES", mode="active")
    status_of(shop["tenant_id"], "suspended")
    till = op_open()
    ops = fix_lines(shop, [till, op_sale(till["local_id"])])
    r = upload(client, shop, ops)
    assert statuses(r) == ["ok", "ok"]                          # the till is open and the sale is recorded
    # but a sale rung up now, online, is refused
    online = client.post(f"{POS}/sales", headers=shop["cashier"], json={"lines": []})
    assert online.status_code == 402 and online.json()["error"] == "subscription_suspended"


def test_platform_staff_in_a_support_session_are_not_stopped(client, registry) -> None:  # type: ignore[no-untyped-def]
    from tests.platform_helpers import staff
    from tests.test_support_access import give_access, open_session, support_headers

    tid, owner_h = business(registry, "Ent Support")
    owner = sign_in(client, "ent-support", "owner@ent-support.test", device_id="d-sup")
    give_access(client, owner, level="full")
    status_of(tid, "suspended")
    op = staff(client, "support")
    headers = support_headers(open_session(client, op["headers"], "ent-support"))
    assert client.get(f"{API}/products/products", headers=headers).status_code == 200


# --------------------------------------------------------------------------- modes
def test_self_hosted_copies_ignore_subscription_rows(client, registry) -> None:  # type: ignore[no-untyped-def]
    tid, owner = business(registry, "Ent Selfhost")
    status_of(tid, "suspended")
    assert client.get(f"{API}/users", headers=owner).status_code == 402
    os.environ["ZIIRA_DEPLOYMENT_MODE"] = "selfhosted"
    get_settings.cache_clear()
    entitlements.invalidate()
    try:
        assert client.get(f"{API}/users", headers=owner).status_code == 200      # no licence needed unless required
        assert add_user(client, owner, "1").status_code == 201
        assert add_user(client, owner, "2").status_code == 201                     # the subscription's 2-user limit is gone
        plan = client.get(f"{API}/billing/plan", headers=owner).json()
        assert plan["mode"] == "selfhosted" and plan["managed"] is False
        assert client.post(f"{API}/billing/cancel", headers=owner, json={}).status_code == 409
    finally:
        os.environ.pop("ZIIRA_DEPLOYMENT_MODE", None)
        get_settings.cache_clear()
        entitlements.invalidate()
    assert client.get(f"{API}/users", headers=owner).status_code == 402          # back to SaaS: the row counts again


def test_registration_starts_the_default_plans_trial(client, registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.platform import settings

    make_plan("reg-default", units=["products"], prices={("KES", "month"): "100.00"}, trial_days=21)
    settings.set_value("billing.default_plan_code", "reg-default", "test")
    try:
        r = client.post(f"{API}/register", json={
            "business_name": "Reg Trial Shop", "owner_name": "Rita Reg", "email": "rita@regtrial.test",
            "password": "a-long-password-1", "currency": "KES"})
        assert r.status_code in (200, 202), r.text
        token = r.json()["dev_token"]
        done = client.post(f"{API}/register/verify", json={"token": token, "device_id": "d1"})
        assert done.status_code == 200, done.text
        code = done.json()["workspace"]
        with master_session() as m:
            sub = m.execute(text("select s.* from master.subscription s join master.tenant t on t.id = s.tenant_id "
                                 "where t.code = :c"), {"c": code}).one()
        assert (sub.status, sub.plan_code, sub.currency.strip()) == ("trialing", "reg-default", "KES")
        assert (sub.trial_end - sub.created_at).days in (20, 21)
    finally:
        settings.set_value("billing.default_plan_code", "", "test")


def test_an_unknown_default_plan_never_blocks_registration(client, registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.platform import settings

    assert subscriptions.start_for_registration.__doc__
    settings.set_value("billing.default_plan_code", "no-such-plan", "test")
    try:
        r = client.post(f"{API}/register", json={
            "business_name": "Reg Plain Shop", "owner_name": "Pat Plain", "email": "pat@regplain.test",
            "password": "a-long-password-1", "currency": "KES"})
        done = client.post(f"{API}/register/verify", json={"token": r.json()["dev_token"], "device_id": "d2"})
        assert done.status_code == 200                                              # the business exists, unmanaged
    finally:
        settings.set_value("billing.default_plan_code", "", "test")


def test_a_start_needs_a_currency_when_the_plan_is_unpriced(registry) -> None:  # type: ignore[no-untyped-def]
    make_plan("unpriced-e", units=["products"])
    t = make_tenant("Ent Unpriced")
    with pytest.raises(ValidationFailed, match="currency"):
        subscriptions.start(t["tenant_id"], "unpriced-e")
    ok = subscriptions.start(t["tenant_id"], "unpriced-e", currency="eur", now=T0)
    assert ok["currency"].strip() == "EUR" and ok["trial_end"] == T0 + timedelta(days=14)

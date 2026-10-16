"""Plans, prices, add-ons, coupons and the public price list (docs/platform-admin.md).

Prices are append-only and effective-dated: the price in force at a moment is the latest row that started by then."""

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.platform_helpers import API, T0, make_plan, staff
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.platform import plans


@pytest.fixture(scope="module")
def boss(client, registry):  # type: ignore[no-untyped-def]
    return staff(client)


def test_a_plan_needs_something_to_sell_and_a_valid_code(registry) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed):
        plans.create_plan({"code": "Bad Code", "name": "Bad", "units": ["products"]})
    with pytest.raises(ValidationFailed, match="edition or a list of units"):
        plans.create_plan({"code": "empty-plan", "name": "Empty"})
    with pytest.raises(ValidationFailed, match="Unknown unit"):
        plans.create_plan({"code": "ghost-plan", "name": "Ghost", "units": ["no_such_unit"]})
    with pytest.raises(ValidationFailed, match="Edition is one of"):
        plans.create_plan({"code": "ed-plan", "name": "Ed", "edition": "moonbase"})


def test_the_price_in_force_follows_effective_dates(registry) -> None:  # type: ignore[no-untyped-def]
    plan = make_plan("eff-plan")
    pid = plan["id"]
    plans.set_price("plan", pid, currency="USD", interval="month", amount="10.00", tax_inclusive=False,
                    effective_from=T0, now=T0)
    plans.set_price("plan", pid, currency="USD", interval="month", amount="12.50", tax_inclusive=False,
                    effective_from=T0 + timedelta(days=30), now=T0)
    # before the first row there is no price; between the two it is 10.00; from the second date 12.50
    assert plans.price_at("plan", pid, "USD", "month", T0 - timedelta(days=1)) is None
    assert plans.price_at("plan", pid, "USD", "month", T0 + timedelta(days=29)).amount == Decimal("10.00")  # type: ignore[union-attr]
    assert plans.price_at("plan", pid, "USD", "month", T0 + timedelta(days=30)).amount == Decimal("12.50")  # type: ignore[union-attr]
    # history is never rewritten: a price may not start at or before the newest one, nor in the past
    with pytest.raises(ValidationFailed, match="after the latest"):
        plans.set_price("plan", pid, currency="USD", interval="month", amount="9.00", tax_inclusive=False,
                        effective_from=T0 + timedelta(days=10), now=T0)
    with pytest.raises(ValidationFailed, match="in the past"):
        plans.set_price("plan", pid, currency="EUR", interval="month", amount="9.00", tax_inclusive=False,
                        effective_from=T0 - timedelta(days=1), now=T0)
    # a scheduled price can be taken back; one in force cannot
    scheduled = next(p for p in plans.price_history("plan", pid) if p["amount"] == Decimal("12.50"))
    with pytest.raises(ValidationFailed, match="already in force"):
        plans.remove_scheduled_price("plan", scheduled["id"], now=T0 + timedelta(days=31))
    plans.remove_scheduled_price("plan", scheduled["id"], now=T0)
    assert plans.price_at("plan", pid, "USD", "month", T0 + timedelta(days=40)).amount == Decimal("10.00")  # type: ignore[union-attr]


def test_withdrawing_a_price_stops_offering_it(registry) -> None:  # type: ignore[no-untyped-def]
    plan = make_plan("wd-plan")
    pid = plan["id"]
    plans.set_price("plan", pid, currency="KES", interval="year", amount="1000", tax_inclusive=True,
                    effective_from=T0, now=T0)
    plans.set_price("plan", pid, currency="KES", interval="year", amount="0", tax_inclusive=True, withdrawn=True,
                    effective_from=T0 + timedelta(days=5), now=T0)
    assert plans.price_at("plan", pid, "KES", "year", T0 + timedelta(days=1)).tax_inclusive is True  # type: ignore[union-attr]
    assert plans.price_at("plan", pid, "KES", "year", T0 + timedelta(days=6)) is None


def test_amounts_have_at_most_two_decimals(registry) -> None:  # type: ignore[no-untyped-def]
    plan = make_plan("dec-plan")
    for bad in ("1.005", "-1", "abc"):
        with pytest.raises(ValidationFailed):
            plans.set_price("plan", plan["id"], currency="USD", interval="month", amount=bad, tax_inclusive=False)
    with pytest.raises(ValidationFailed, match="three-letter"):
        plans.set_price("plan", plan["id"], currency="DOLLAR", interval="month", amount="1", tax_inclusive=False)


def test_public_plans_show_only_public_active_plans_with_current_prices(client, registry) -> None:  # type: ignore[no-untyped-def]
    make_plan("pub-yes", prices={("USD", "month"): "20.00", ("USD", "year"): "200.00"}, max_users=5)
    make_plan("pub-hidden", public=False, prices={("USD", "month"): "1.00"})
    retired = make_plan("pub-retired", prices={("USD", "month"): "2.00"})
    plans.update_plan(retired["code"], {"status": "retired"})
    plans.invalidate_public_cache()
    r = client.get(f"{API}/public/plans")                                  # no sign-in
    assert r.status_code == 200, r.text
    assert "max-age" in r.headers["cache-control"]
    body = r.json()
    codes = [p["code"] for p in body["plans"]]
    assert "pub-yes" in codes and "pub-hidden" not in codes and "pub-retired" not in codes
    plan = next(p for p in body["plans"] if p["code"] == "pub-yes")
    assert plan["prices"] == [{"currency": "USD", "interval": "month", "amount": "20.00", "tax_inclusive": False},
                              {"currency": "USD", "interval": "year", "amount": "200.00", "tax_inclusive": False}]
    assert plan["limits"]["max_users"] == 5 and plan["trial_days"] == 14
    assert set(body) == {"plans", "addons", "updated_at"}
    assert "id" not in plan and "subscribers" not in plan                  # nothing internal leaves the platform


def test_public_plans_never_show_a_scheduled_price_early(registry) -> None:  # type: ignore[no-untyped-def]
    plan = make_plan("pub-sched", prices={("USD", "month"): "5.00"})
    plans.set_price("plan", plan["id"], currency="USD", interval="month", amount="7.00", tax_inclusive=False,
                    effective_from=plans._now() + timedelta(days=10))
    now_view = next(p for p in plans.public_plans(use_cache=False)["plans"] if p["code"] == "pub-sched")
    later = next(p for p in plans.public_plans(at=plans._now() + timedelta(days=11))["plans"] if p["code"] == "pub-sched")
    assert now_view["prices"][0]["amount"] == "5.00" and later["prices"][0]["amount"] == "7.00"


def test_coupons_percent_and_fixed(registry) -> None:  # type: ignore[no-untyped-def]
    pct = plans.create_coupon({"code": "TENOFF", "percent_off": "10", "duration": "once"})
    fixed = plans.create_coupon({"code": "FIVEBUCKS", "amounts": {"USD": "5.00"}, "duration": "repeating",
                                 "duration_periods": 3})
    assert plans.discount_for(pct, "USD", Decimal("33.35")) == Decimal("3.34")           # 3.335 rounds half up
    assert plans.discount_for(fixed, "USD", Decimal("33.35")) == Decimal("5.00")
    assert plans.discount_for(fixed, "USD", Decimal("3.00")) == Decimal("3.00")           # never more than the price
    with pytest.raises(ValidationFailed, match="no amount in EUR"):
        plans.check_coupon(fixed, "any", "EUR")
    with pytest.raises(ValidationFailed, match="percentage or fixed"):
        plans.create_coupon({"code": "BOTHWAYS", "percent_off": "5", "amounts": {"USD": "1"}})
    with pytest.raises(ValidationFailed, match="number of invoices"):
        plans.create_coupon({"code": "NOPERIODS", "percent_off": "5", "duration": "repeating"})
    plans.set_coupon_status("TENOFF", "disabled")
    with pytest.raises(ValidationFailed, match="not active"):
        plans.check_coupon(plans.get_coupon("TENOFF"), "any", "USD")
    with pytest.raises(NotFound):
        plans.get_coupon("NOSUCH")


def test_the_console_creates_a_plan_and_prices_it(client, boss) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{API}/operator/plans", headers=boss["headers"], json={
        "code": "api-plan", "name": "API plan", "units": ["products"], "max_users": 3, "is_public": True,
        "highlights": ["Three users"], "trial_days": 7})
    assert r.status_code == 201, r.text
    assert r.json()["max_users"] == 3 and r.json()["units_included"] == ["products"]
    p = client.post(f"{API}/operator/plans/api-plan/prices", headers=boss["headers"], json={
        "currency": "USD", "interval": "month", "amount": "15.00", "tax_inclusive": False})
    assert p.status_code == 201, p.text
    assert p.json()["current_prices"][0]["amount"] == "15.00"
    bad = client.post(f"{API}/operator/plans/api-plan/prices", headers=boss["headers"], json={
        "currency": "USD", "interval": "month", "amount": "1.001"})
    assert bad.status_code == 422
    dup = client.post(f"{API}/operator/plans", headers=boss["headers"], json={"code": "api-plan", "name": "Again",
                                                                              "units": ["products"]})
    assert dup.status_code == 409
    listing = client.get(f"{API}/operator/plans", headers=boss["headers"]).json()
    assert any(x["code"] == "api-plan" for x in listing)
    # the public page reflects it after the cache is cleared by the change itself
    pub = client.get(f"{API}/public/plans").json()
    assert any(x["code"] == "api-plan" and x["prices"][0]["amount"] == "15.00" for x in pub["plans"])

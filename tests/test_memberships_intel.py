"""Intelligence checks and Command Center figures over Memberships, with the real engine. A real business; today is
2026-10-14 for the checks."""

from datetime import date
from decimal import Decimal as D  # noqa: N817
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.memberships_helpers import M, cancel_reason, customer, make_member_shop, rows, run_billing, sign_up
from tests.stock_helpers import system
from ziira.modules.command.services import pulse
from ziira.modules.intel.public import CheckContext, IntelCheck
from ziira.modules.intel.services import engine
from ziira.modules.memberships.intel_checks import (
    MembershipRevenueAtRisk,
    MembershipsEnding,
    PackagesExpiringUnused,
    RecurringInvoiceFailed,
)

TODAY = date(2026, 10, 14)
INTEL = "/api/v1/intel"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_member_shop(client, registry, "Members Intel Co")
    client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"], json={"timezone": "UTC"})
    for unit in ("intel", "command"):
        registry.enable(s["tenant_id"], unit)
    return s


def run_check(shop, code: str):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=TODAY, only={code})


def findings(client, shop, code: str, *statuses: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {"check_code": code, "limit": 100}
    named = [s for s in statuses if s != "open"]             # "open" is what the list returns when no status is named
    if named:
        params["status"] = named
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


def direct(shop, check: IntelCheck, **params: Any):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        ctx = CheckContext(company_id=shop["company_id"], today=TODAY, params={**check.params, **params},
                           baseline=lambda metric, key: None)
        return check.run(s, ctx)


def sql(shop, stmt: str, **params: Any) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text(stmt), params)


# --------------------------------------------------------------------------- income at risk
def test_income_at_risk_is_shown_only_when_a_real_share_of_the_income_is_leaving(client, shop) -> None:  # type: ignore[no-untyped-def]
    cur = rows(shop, "select base_currency from kernel.company")[0][0]
    made = [sign_up(client, shop, customer(client, shop, f"Risk {n}"), date(2026, 9, 20)).json() for n in range(4)]
    assert run_check(shop, "memberships.revenue_at_risk").created == 0                    # nobody is leaving yet
    for m in made[:2]:
        client.post(f"{M}/members/{m['id']}/cancel", headers=shop["owner"], json={"reason_code_id": cancel_reason(client, shop)})
    client.post(f"{M}/members/{made[2]['id']}/pause", headers=shop["owner"], json={})
    result = run_check(shop, "memberships.revenue_at_risk")
    assert result.created == 1 and not result.failed
    found = findings(client, shop, "memberships.revenue_at_risk")[0]
    assert found["summary"] == (f"3 memberships worth {cur} 300.00 a month (75.0% of monthly membership income) are "
                                "cancelling, on hold or not being billed.")
    assert found["severity"] == "high" and D(found["amount"]) == 300 and D(found["value"]) == D("75.0")
    assert found["branch_id"] is None
    assert direct(shop, MembershipRevenueAtRisk(), min_members=5) == []                    # tuned: needs more members
    assert direct(shop, MembershipRevenueAtRisk(), min_percent="80.0") == []              # tuned: only above 80%
    levels = {c.severity for c in direct(shop, MembershipRevenueAtRisk(), high_percent="90.0")}
    assert levels == {"medium"}
    for m in made[:2]:                                                                    # the cancellations are withdrawn
        client.post(f"{M}/members/{m['id']}/undo-cancel", headers=shop["owner"])
    client.post(f"{M}/members/{made[2]['id']}/resume", headers=shop["owner"], json={})
    run_check(shop, "memberships.revenue_at_risk")
    assert findings(client, shop, "memberships.revenue_at_risk", "open") == []            # closed by itself


# --------------------------------------------------------------------------- memberships ending
def test_memberships_that_are_about_to_end_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    soon = sign_up(client, shop, customer(client, shop, "Leaving Soon"), date(2026, 9, 20)).json()       # renews 20 Oct
    later = sign_up(client, shop, customer(client, shop, "Leaving Later"), date(2026, 8, 1)).json()
    far = sign_up(client, shop, customer(client, shop, "Staying"), date(2026, 9, 20)).json()
    for m in (soon, later):
        client.post(f"{M}/members/{m['id']}/cancel", headers=shop["owner"], json={"reason_code_id": cancel_reason(client, shop)})
    sql(shop, "update memberships.member set cancel_at = :d where id = :i", d=date(2026, 12, 1), i=later["id"])
    result = run_check(shop, "memberships.ending")
    assert result.created == 1
    items = findings(client, shop, "memberships.ending")
    assert len(items) == 1 and items[0]["summary"].startswith(f"Membership {soon['number']} (Gold) is cancelling on 20 Oct 2026, in 6 days")
    assert items[0]["severity"] == "low" and items[0]["branch_id"] == str(shop["branch_id"]) and D(items[0]["value"]) == 6
    assert len(direct(shop, MembershipsEnding(), days=60)) == 2                           # tuned: a longer look ahead
    assert far["id"] not in str(items)
    client.post(f"{M}/members/{soon['id']}/undo-cancel", headers=shop["owner"])
    run_check(shop, "memberships.ending")
    assert findings(client, shop, "memberships.ending", "open") == []


# --------------------------------------------------------------------------- packages about to expire
def test_packages_that_expire_with_credits_left_are_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    def sold(name: str) -> dict[str, Any]:
        return client.post(f"{M}/sold-packages", headers=shop["owner"], json={
            "package_id": shop["package"]["id"], "customer_id": customer(client, shop, name)["id"],
            "branch_id": str(shop["branch_id"]), "purchased_on": "2026-09-01", "invoice": False}).json()

    left, used_up, later = sold("Has Credits"), sold("All Used"), sold("Later Expiry")
    sql(shop, "update memberships.sold_package set expires_on = :d where id = :i", d=date(2026, 10, 20), i=left["id"])
    sql(shop, "update memberships.sold_package set expires_on = :d where id = :i", d=date(2026, 10, 20), i=used_up["id"])
    sql(shop, "update memberships.sold_package set expires_on = :d where id = :i", d=date(2027, 1, 20), i=later["id"])
    assert client.post(f"{M}/credits/adjust", headers=shop["owner"], json={
        "holder_type": "package", "holder_id": left["id"], "quantity": "-6", "note": "Used earlier"}).status_code == 201
    assert client.post(f"{M}/credits/adjust", headers=shop["owner"], json={
        "holder_type": "package", "holder_id": used_up["id"], "quantity": "-10", "note": "All used"}).status_code == 201
    assert run_check(shop, "memberships.packages_expiring").created == 1
    f = findings(client, shop, "memberships.packages_expiring")[0]
    assert f["summary"] == (f"Package {left['number']} (10 massages) expires on 20 Oct 2026, in 6 days, with 4.00 of 10.00 "
                            "credits unused.")
    assert D(f["amount"]) == D("200.00") and f["severity"] == "low"                       # 4 of 10 credits of 500.00
    assert direct(shop, PackagesExpiringUnused(), min_credits=5) == []                    # tuned: 4 left is not enough
    assert len(direct(shop, PackagesExpiringUnused(), days=120)) == 2                     # tuned: looks further ahead
    client.post(f"{M}/credits/adjust", headers=shop["owner"], json={
        "holder_type": "package", "holder_id": left["id"], "quantity": "-4", "note": "Used"})
    run_check(shop, "memberships.packages_expiring")
    assert findings(client, shop, "memberships.packages_expiring", "open") == []


# --------------------------------------------------------------------------- recurring invoices that failed
def test_a_recurring_invoice_that_failed_is_flagged_urgent_when_it_stays_failed(client, shop) -> None:  # type: ignore[no-untyped-def]
    cust = customer(client, shop, "Failing Fay", limit="50")
    made = client.post(f"{M}/recurring-invoices", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "customer_id": cust["id"],
        "name": "Retainer", "start_date": "2026-10-01", "billing_interval": "month",
        "lines": [{"product_id": shop["delivery"], "quantity": "1", "unit_price": "250.00"}]})
    assert made.status_code == 201, made.text
    run_billing(shop, date(2026, 10, 2))
    result = run_check(shop, "memberships.recurring_invoice_failed")
    assert result.created == 1
    f = findings(client, shop, "memberships.recurring_invoice_failed")[0]
    assert f["summary"].startswith("The invoice for Retainer for the period starting 1 Oct 2026 could not be issued (")
    assert f["severity"] == "medium"
    sql(shop, "update memberships.invoice_run set created_at = :t where status = 'failed' and customer_id = :c",
        t=date(2026, 10, 9), c=cust["id"])                                                  # failing for five days
    assert {c.severity for c in direct(shop, RecurringInvoiceFailed())} == {"high"}
    assert {c.severity for c in direct(shop, RecurringInvoiceFailed(), high_after_days=10)} == {"medium"}
    assert direct(shop, RecurringInvoiceFailed(), lookback_days=2) == []                   # too old to look at
    client.post(f"/api/v1/crm/customers/{cust['id']}/credit", headers=shop["fm"], json={
        "credit_limit": "100000", "payment_terms_days": 14, "reason": "Raised"})
    run_billing(shop, date(2026, 10, 3))
    run_check(shop, "memberships.recurring_invoice_failed")
    assert findings(client, shop, "memberships.recurring_invoice_failed", "open") == []


# --------------------------------------------------------------------------- figures for the Command Center
def test_the_command_center_gets_membership_figures_by_company_and_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    quarterly = client.post(f"{M}/plans", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "code": "QTR", "name": "Quarterly", "fee": "300.00",
        "billing_interval": "quarter", "service_product_id": shop["delivery"]}).json()
    sign_up(client, shop, customer(client, shop, "Quarterly Quin"), date(2026, 10, 10), plan_id=quarterly["id"])
    with system(shop) as s:
        pulse.refresh_company(s, shop["company_id"], TODAY)
        figs = {(r.metric, r.branch_id): D(r.value) for r in s.execute(text(
            "select metric, branch_id, value from command.pulse_figure where company_id = :c and day = :d"),
            {"c": str(shop["company_id"]), "d": TODAY})}
        active = s.execute(text("select count(*) from memberships.member where status = 'active'")).scalar_one()
        monthly = D(s.execute(text(
            "select coalesce(sum(price / (case billing_interval when 'month' then 1 when 'quarter' then 3 else 12 end)), 0) "
            "from memberships.member where status = 'active'")).scalar_one())
    assert figs[("memberships.active_members", None)] == active > 0
    assert figs[("memberships.active_members", UUID(str(shop["branch_id"])))] == active
    assert figs[("memberships.monthly_income", None)] == monthly
    assert ("memberships.failed_recurring_invoices", None) in figs and ("memberships.packages_expiring_30_days", None) in figs
    assert monthly % D("100.00") == 0 or monthly > 0

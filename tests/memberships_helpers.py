"""Shared setup for the Memberships tests: a sales shop (invoices work) with memberships on, a monthly plan and a package."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from tests.pos_helpers import credit_customer, make_sales_shop
from tests.stock_helpers import system

M = "/api/v1/memberships"


def make_member_shop(client, registry, name: str):  # type: ignore[no-untyped-def]
    """The sales shop with Memberships on; users `rep` (Sales Rep at HQ), `acct` (Accountant); a GOLD plan (fee 100.00 a
    month, 4 credits, 10 percent off services, invoiced as the DELIVERY service item) and a TEN package (10 credits for
    500.00, 90 days, invoiced as DELIVERY)."""
    shop = make_sales_shop(client, registry, name, stock="10")
    registry.enable(shop["tenant_id"], "memberships")
    shop["rep"] = shop["user"]("rep", "Sales Rep", shop["branch_id"])
    shop["acct"] = shop["user"]("acct", "Accountant", None)
    co = str(shop["company_id"])
    plan = client.post(f"{M}/plans", headers=shop["owner"], json={
        "company_id": co, "code": "GOLD", "name": "Gold", "fee": "100.00", "billing_interval": "month",
        "credits_per_period": "4", "discount_percent": "10", "service_product_id": shop["delivery"]})
    assert plan.status_code == 201, plan.text
    package = client.post(f"{M}/packages", headers=shop["owner"], json={
        "company_id": co, "code": "TEN", "name": "10 massages", "credits": "10", "price": "500.00", "expiry_days": 90,
        "covered_services": ["massage"], "product_id": shop["delivery"]})
    assert package.status_code == 201, package.text
    shop.update({"plan": plan.json(), "package": package.json()})
    return shop


def customer(client, shop, name: str = "Amina Member", limit: str = "100000", **kw: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return credit_customer(client, shop, name=name, limit=limit, terms=14, **kw)


def sign_up(client, shop, cust, start: date | None = None, who: str = "owner", **extra: Any):  # type: ignore[no-untyped-def]
    body: dict[str, Any] = {"plan_id": shop["plan"]["id"], "customer_id": cust["id"],
                            "branch_id": str(shop["branch_id"]), **extra}
    if start:
        body["start_date"] = start.isoformat()
    return client.post(f"{M}/members", headers=shop[who], json=body)


def rows(shop, sql: str, **params: Any) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return list(s.execute(text(sql), params))


def scalar(shop, sql: str, **params: Any) -> Any:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text(sql), params).scalar_one()


def run_billing(shop, day: date) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Do what the hourly task does for the company on `day`."""
    from ziira.modules.memberships import jobs

    with system(shop) as s:
        return jobs.bill_company(s, UUID(str(shop["company_id"])), day)


def cancel_reason(client, shop) -> str:  # type: ignore[no-untyped-def]
    for r in client.get("/api/v1/settings/reason-codes", headers=shop["owner"]).json():
        if r["category"] == "membership_cancel":
            return str(r["id"])
    raise AssertionError("no cancellation reasons were seeded")

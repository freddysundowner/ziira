"""What each default role may do in Inventory, checked through the API (roles are company-wide here)."""

from decimal import Decimal as Dec
from uuid import uuid4

import pytest

from tests.stock_helpers import INV, make_stock_shop

ROLES = ["Owner", "Branch Manager", "Finance Manager", "Storekeeper", "Cashier", "Sales Rep", "Accountant", "HR"]

# permission needed -> roles that hold it by default
ALLOWED = {
    "view": {"Owner", "Branch Manager", "Finance Manager", "Storekeeper", "Cashier", "Sales Rep", "Accountant"},
    "locations": {"Owner", "Branch Manager"},
    "adjust": {"Owner", "Branch Manager", "Storekeeper"},
    "transfer": {"Owner", "Branch Manager", "Storekeeper"},
    "count": {"Owner", "Branch Manager", "Storekeeper"},
    "cost": {"Owner", "Branch Manager", "Finance Manager", "Accountant"},
}


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_stock_shop(client, registry, "Role Co")
    s["people"] = {"Owner": s["owner"]}
    for role in ROLES[1:]:
        s["people"][role] = s["user"]("role" + role.lower().replace(" ", ""), role, None)   # company-wide
    r = client.post(f"{INV}/opening-stock", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "location_id": s["main"],
        "lines": [{"product_id": s["cement"], "quantity": "50", "unit_cost": "100"}]})
    assert r.status_code == 201, r.text
    s["reason"] = next(x["id"] for x in client.get("/api/v1/settings/reason-codes", headers=s["owner"]).json()
                       if x["category"] == "stock_adjustment" and x["code"] == "FOUND")
    return s


def status_of(client, shop, role: str, action: str) -> int:  # type: ignore[no-untyped-def]
    headers = shop["people"][role]
    co = str(shop["company_id"])
    if action == "view":
        return client.get(f"{INV}/balances", headers=headers).status_code
    if action == "locations":
        return client.post(f"{INV}/locations", headers=headers, json={
            "company_id": co, "branch_id": str(shop["branch_id"]), "code": f"L{uuid4().hex[:8]}", "name": "x"}
        ).status_code
    if action == "adjust":
        return client.post(f"{INV}/adjustments", headers=headers, json={
            "company_id": co, "location_id": shop["main"], "reason_code_id": shop["reason"],
            "lines": [{"product_id": shop["cement"], "qty_change": "1"}]}).status_code
    if action == "transfer":
        return client.post(f"{INV}/transfers", headers=headers, json={
            "company_id": co, "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
            "lines": [{"product_id": shop["cement"], "quantity": "1"}]}).status_code
    if action == "count":
        r = client.post(f"{INV}/counts", headers=headers, json={
            "company_id": co, "location_id": shop["juja_store"]})
        if r.status_code == 201:                                         # leave no count open for the next role
            client.post(f"{INV}/counts/{r.json()['id']}/cancel", headers=headers)
        return r.status_code
    raise AssertionError(action)


@pytest.mark.parametrize("action", ["view", "locations", "adjust", "transfer", "count"])
@pytest.mark.parametrize("role", ROLES)
def test_each_role_can_do_exactly_what_it_should(client, shop, role: str, action: str) -> None:  # type: ignore[no-untyped-def]
    status = status_of(client, shop, role, action)
    if role in ALLOWED[action]:
        assert status in (200, 201), f"{role} should be able to {action}, got {status}"
    else:
        assert status == 403, f"{role} should not be able to {action}, got {status}"


@pytest.mark.parametrize("role", [r for r in ROLES if r in ALLOWED["view"]])
def test_only_some_roles_see_what_stock_cost(client, shop, role: str) -> None:  # type: ignore[no-untyped-def]
    headers = shop["people"][role]
    movement = client.get(f"{INV}/movements", headers=headers, params={"product_id": shop["cement"]}).json()[0]
    stock = client.get(f"{INV}/products/{shop['cement']}/stock", headers=headers).json()
    if role in ALLOWED["cost"]:
        assert Dec(movement["unit_cost"]) == 100 and Dec(stock["average_cost"]) == 100
    else:
        assert movement["unit_cost"] is None and movement["value"] is None and stock["average_cost"] is None
    assert Dec(stock["quantity"]) >= 50                                  # everyone who may view stock sees quantities


def test_nobody_gets_in_without_signing_in(client, shop) -> None:  # type: ignore[no-untyped-def]
    for path in ("balances", "movements", "locations", "adjustments", "transfers", "counts"):
        r = client.get(f"{INV}/{path}", headers={"X-Tenant-ID": ""})
        assert r.status_code in (401, 403, 422), path


def test_the_endpoints_are_off_when_the_unit_is_disabled(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import make_tenant, sign_in

    plain = make_tenant("No Stock Co")
    registry.enable(plain["tenant_id"], "products")
    owner = sign_in(client, "no-stock-co", "owner@no-stock-co.test").headers
    r = client.get(f"{INV}/balances", headers=owner)
    assert r.status_code == 404 and r.json()["error"] == "unit_not_enabled"

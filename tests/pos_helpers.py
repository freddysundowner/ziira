"""Shared setup for the POS tests: a shop with prices, stock, a device and a cashier ready to sell."""

from decimal import Decimal
from uuid import UUID, uuid4

from tests.payments_helpers import PAY, SHORTCODE, make_payments_shop
from tests.stock_helpers import INV, P, system

POS = "/api/v1/pos"


def make_pos_shop(client, registry, name: str, *, finance: bool = False, stock: str = "100", cost: str = "50"):  # type: ignore[no-untyped-def]
    """The payments shop with POS on: a default price list (CEM 116.00, PAINT 232.00, DELIVERY 58.00, all VAT 16%
    inclusive), `stock` of CEM and PAINT at MAIN costing `cost`, an HQ device D1 selling from MAIN, an M-Pesa till
    account, and the cashier with an open till (float 1000). Extra roles: `fm` (Finance Manager)."""
    shop = make_payments_shop(client, registry, name, finance=finance)
    registry.enable(shop["tenant_id"], "pos")
    owner, co = shop["owner"], str(shop["company_id"])
    default = client.post(f"{P}/price-lists", headers=owner, json={"company_id": co, "name": "Retail", "is_default": True})
    assert default.status_code == 201, default.text
    lst = default.json()["id"]
    for product, price in ((shop["cement"], "116.00"), (shop["paint"], "232.00"), (shop["delivery"], "58.00")):
        r = client.put(f"{P}/price-lists/{lst}/prices", headers=owner, json={
            "product_id": product, "price": price, "valid_from": "2026-01-01"})
        assert r.status_code == 200, r.text
    if Decimal(stock) > 0:
        r = client.post(f"{INV}/opening-stock", headers=owner, json={
            "company_id": co, "location_id": shop["main"], "lines": [
                {"product_id": shop["cement"], "quantity": stock, "unit_cost": cost},
                {"product_id": shop["paint"], "quantity": stock, "unit_cost": cost, "batch_no": "B1",
                 "expiry_date": "2030-01-01"}]})
        assert r.status_code == 201, r.text
    dev = client.post(f"{POS}/devices", headers=owner, json={
        "branch_id": str(shop["branch_id"]), "code": "D1", "name": "Counter 1", "location_id": shop["main"]})
    assert dev.status_code == 201, dev.text
    shop.update({"price_list": lst, "device": dev.json()["id"], "device_key": dev.json()["key"],
                 "fm": shop["user"]("fm", "Finance Manager", None), "tills": {}})
    shop["devices"] = {"cashier": shop["device"]}
    for who, code in (("manager", "D2"), ("boss", "D3")):
        d = client.post(f"{POS}/devices", headers=owner, json={
            "branch_id": str(shop["branch_id"]), "code": code, "name": f"Device {code}", "location_id": shop["main"]})
        assert d.status_code == 201, d.text
        shop["devices"][who] = d.json()["id"]
    shop["reasons"] = reasons(client, owner)
    return shop


def reasons(client, owner) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """First reason code id of each category."""
    found: dict[str, str] = {}
    for r in client.get("/api/v1/settings/reason-codes", headers=owner).json():
        found.setdefault(r["category"], r["id"])
    return found


def open_till(client, shop, who: str = "cashier", device: str | None = None, float_: str = "1000.00",  # type: ignore[no-untyped-def]
              local_id: str | None = None):
    body = {"device_id": device or shop["devices"].get(who) or shop["device"], "opening_float": float_}
    if local_id:
        body["local_id"] = local_id
    return client.post(f"{POS}/tills", headers=shop[who], json=body)


def ensure_till(client, shop, who: str = "cashier") -> str:  # type: ignore[no-untyped-def]
    """The id of this person's open till (opened if needed, on their own device)."""
    known = shop["tills"].get(who)
    if known and client.get(f"{POS}/tills/{known}", headers=shop[who]).json().get("status") == "open":
        return str(known)
    created = open_till(client, shop, who)
    assert created.status_code == 201, created.text
    shop["tills"][who] = created.json()["id"]
    return str(shop["tills"][who])


def line(shop, product: str = "cement", qty: str = "1", **kw):  # type: ignore[no-untyped-def]
    return {"product_id": shop[product], "quantity": qty, **kw}


def sell(client, shop, lines=None, payments=None, who: str = "cashier", till: str | None = None, **kw):  # type: ignore[no-untyped-def]
    body = {"till_session_id": till or ensure_till(client, shop, who), "lines": lines or [line(shop)],
            "payments": payments or [{"method": "cash", "amount": "116.00"}], **kw}
    return client.post(f"{POS}/sales", headers=shop[who], json=body)


def stock(shop, product: str = "cement") -> Decimal:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    with system(shop) as s:
        return Decimal(s.execute(text(
            "select coalesce(sum(quantity), 0) from inventory.stock_balance where location_id = :l and "
            "product_id = :p"), {"l": shop["main"], "p": shop[product]}).scalar_one())


__all__ = ["PAY", "SHORTCODE", "UUID", "uuid4"]

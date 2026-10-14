"""Shared setup for the purchasing tests: stock shop with Purchasing, Payments and Finance, suppliers and users."""

from decimal import Decimal

from tests.payments_helpers import make_payments_shop
from tests.stock_helpers import INV

PUR = "/api/v1/purchasing"
FIN = "/api/v1/finance"


def make_purchasing_shop(client, registry, name: str, *, finance: bool = True):  # type: ignore[no-untyped-def]
    """The payments shop (stock, HQ and JUJA, cash/M-Pesa/bank accounts) with Purchasing on, one supplier (TOTAL01,
    30 days) and users: `buyer` (Branch Manager at HQ), `fm` and `fm2` (Finance Managers), `clerk` (Accountant)."""
    shop = make_payments_shop(client, registry, name, finance=finance)
    registry.enable(shop["tenant_id"], "purchasing")
    owner, co = shop["owner"], str(shop["company_id"])
    sup = client.post(f"{PUR}/suppliers", headers=owner, json={
        "company_id": co, "code": "TOTAL01", "name": "Total Supplies", "tax_id": "P051234567A",
        "payment_terms_days": 30})
    assert sup.status_code == 201, sup.text
    shop.update({"supplier": sup.json()["id"], "buyer": shop["manager"],
                 "fm": shop["user"]("fm", "Finance Manager", None), "fm2": shop["user"]("fm2", "Finance Manager", None),
                 "clerk": shop["user"]("clerk", "Accountant", None)})
    reasons = {}
    for r in client.get("/api/v1/settings/reason-codes", headers=owner).json():
        reasons.setdefault(r["category"], r["id"])
    shop["reasons"] = reasons
    return shop


def new_order(client, shop, qty="10", cost="50.00", product="cement", who="owner", **kw):  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "supplier_id": shop["supplier"],
            "deliver_to_location_id": shop["main"],
            "lines": [{"product_id": shop[product], "quantity": qty, "unit_cost": cost}], **kw}
    r = client.post(f"{PUR}/orders", headers=shop[who], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def approved_order(client, shop, **kw):  # type: ignore[no-untyped-def]
    order = new_order(client, shop, **kw)
    r = client.post(f"{PUR}/orders/{order['id']}/submit", headers=shop["owner"])
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    return r.json()


def receive(client, shop, order, qty=None, who="owner", **kw):  # type: ignore[no-untyped-def]
    lines = [{"order_line_id": x["id"], "quantity": qty or x["quantity"]} for x in order["lines"]]
    return client.post(f"{PUR}/receipts", headers=shop[who], json={"order_id": order["id"], "lines": lines, **kw})


def bill_for(client, shop, receipt, cost=None, qty=None, invoice="INV-1", who="owner", **kw):  # type: ignore[no-untyped-def]
    lines = [{"receipt_line_id": x["id"], "quantity": qty or x["quantity"], "unit_cost": cost or x["unit_cost"]}
             for x in receipt["lines"]]
    return client.post(f"{PUR}/bills", headers=shop[who], json={
        "supplier_id": shop["supplier"], "supplier_invoice_no": invoice, "bill_date": "2026-10-13", "lines": lines,
        **kw})


def stock_of(shop, product="cement") -> Decimal:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from tests.stock_helpers import system

    with system(shop) as s:
        return Decimal(s.execute(text(
            "select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = :p and "
            "location_id = :l"), {"p": shop[product], "l": shop["main"]}).scalar_one())


__all__ = ["INV"]

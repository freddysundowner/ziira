"""Shared setup for the Jobs tests: a sales shop (stock, POS, CRM, Finance) with Jobs on, a labour rate, the service
item labour and parts are invoiced under, a customer and a technician."""

from decimal import Decimal

from tests.pos_helpers import credit_customer, make_sales_shop
from tests.stock_helpers import system

JOBS = "/api/v1/jobs"


def make_jobs_shop(client, registry, name: str, *, stock: str = "10"):  # type: ignore[no-untyped-def]
    """The sales shop (CEM 116.00 with `stock` at cost 50 in MAIN, DELIVERY 58.00 as a service, VAT 16% inclusive) with
    Jobs, Intelligence and the Command Center on, labour at 100.00 an hour and DELIVERY as both the Labour and the
    Parts item. Users: `tech` (Sales Rep at HQ), plus the sales shop's manager, storekeeper and cashier. `customer`
    is a customer record."""
    shop = make_sales_shop(client, registry, name, stock=stock)
    for unit in ("jobs", "intel", "command"):
        registry.enable(shop["tenant_id"], unit)
    owner, co = shop["owner"], str(shop["company_id"])
    client.patch(f"/api/v1/companies/{co}/settings", headers=owner, json={"timezone": "UTC"})
    r = client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=owner, json={
        "default_labour_rate": "100.00", "labour_product_id": shop["delivery"], "parts_product_id": shop["delivery"]})
    assert r.status_code == 200, r.text
    shop["tech"] = shop["user"]("tech", "Sales Rep", shop["branch_id"])
    shop["customer"] = credit_customer(client, shop, name="Wanjiku Motors", limit="100000", terms=14,
                                       phone="254712345678")
    shop["users"] = {u["email"].split("@")[0]: u["id"] for u in client.get("/api/v1/users", headers=owner).json()}
    return shop


def new_job(client, shop, who: str = "owner", **extra):  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "title": "Brake pads worn",
            "customer_id": shop["customer"]["id"], **extra}
    r = client.post(f"{JOBS}/jobs", headers=shop[who], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def stage(client, shop, code: str):  # type: ignore[no-untyped-def]
    """The id of the company's stage with this code."""
    found = client.get(f"{JOBS}/workflow", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    return next(s["id"] for s in found if s["code"] == code)


def move(client, shop, job, code: str, who: str = "owner", **extra):  # type: ignore[no-untyped-def]
    return client.post(f"{JOBS}/jobs/{job['id']}/status", headers=shop[who],
                       json={"to_status_id": stage(client, shop, code), **extra})


def stock_on_hand(shop, product: str = "cement") -> Decimal:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    with system(shop) as s:
        return Decimal(s.execute(text(
            "select coalesce(sum(quantity), 0) from inventory.stock_balance where product_id = :p "
            "and location_id = :l"), {"p": shop[product], "l": shop["main"]}).scalar_one())

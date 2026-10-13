"""Shared setup for the CRM and sales-on-credit tests."""

from tests.stock_helpers import make_stock_shop

CRM = "/api/v1/crm"


def make_crm_shop(client, registry, name: str):  # type: ignore[no-untyped-def]
    """The stock shop with CRM on and users: `fm` (Finance Manager), `rep` (Sales Rep at HQ)."""
    shop = make_stock_shop(client, registry, name)
    registry.enable(shop["tenant_id"], "crm")
    shop["fm"] = shop["user"]("fm", "Finance Manager", None)
    shop["rep"] = shop["user"]("rep", "Sales Rep", shop["branch_id"])
    return shop


def new_customer(client, shop, who="owner", **kw):  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "name": "Wanjiku Hardware", **kw}
    r = client.post(f"{CRM}/customers", headers=shop[who], json=body)
    assert r.status_code == 201, r.text
    return r.json()

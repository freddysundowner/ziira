"""Shared test setup for the inventory tests: a business with stock, branches, products and users."""

from uuid import UUID, uuid4

from sqlalchemy import text

from tests.conftest import make_tenant, sign_in

P, INV = "/api/v1/products", "/api/v1/inventory"


def system(t):  # type: ignore[no-untyped-def]
    """A system transaction for the tenant (acts with every permission)."""
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session

    system_context(t["tenant_id"])
    return tenant_session(t["tenant_id"])


def make_stock_shop(client, registry, name: str):  # type: ignore[no-untyped-def]
    """A tenant with Inventory, two branches (HQ and JUJA), three products (plain CEM with reorder level 10,
    batch-tracked PAINT, service DELIVERY), a location per branch (MAIN, JUJA-STORE), and users: a manager
    (branch manager), a storekeeper and a cashier at HQ, and a storekeeper at JUJA."""
    code = name.lower().replace(" ", "-")
    t = make_tenant(name)
    registry.enable(t["tenant_id"], "inventory")
    juja = uuid4()
    with system(t) as s:
        s.execute(text("insert into kernel.branch (id, tenant_id, company_id, code, name) "
                       "values (:i, :t, :c, 'JUJA', 'Juja')"),
                  {"i": str(juja), "t": str(t["tenant_id"]), "c": str(t["company_id"])})
    owner = sign_in(client, code, f"owner@{code}.test").headers
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner).json()}

    def user(user_name: str, role: str, branch: UUID | None) -> dict[str, str]:
        email = f"{user_name}@{code}.test"
        u = client.post("/api/v1/users", headers=owner,
                        json={"full_name": user_name, "email": email, "password": f"{user_name}-pass-1"}).json()
        body = {"role_id": roles[role], "scope": "branch" if branch else "company",
                "company_id": str(t["company_id"]), "branch_id": str(branch) if branch else None}
        r = client.post(f"/api/v1/users/{u['id']}/roles", headers=owner, json=body)
        assert r.status_code == 201, r.text
        return sign_in(client, code, email, f"{user_name}-pass-1").headers

    uom = client.post(f"{P}/uoms", headers=owner, json={"code": "PCS", "name": "Pieces"}).json()["id"]
    tax = client.post(f"{P}/tax-codes", headers=owner,
                      json={"code": "VAT16", "name": "VAT", "vat_rate": "16", "etims_tax_type": "B"}).json()["id"]

    def product(sku: str, **extra) -> str:  # type: ignore[no-untyped-def]
        r = client.post(f"{P}/products", headers=owner, json={
            "company_id": str(t["company_id"]), "sku": sku, "name": f"Product {sku}", "base_uom_id": uom,
            "tax_code_id": tax, **extra})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def location(loc_code: str, branch: UUID) -> str:
        r = client.post(f"{INV}/locations", headers=owner, json={
            "company_id": str(t["company_id"]), "branch_id": str(branch), "code": loc_code, "name": loc_code})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return {
        **t, "code": code, "juja": juja, "owner": owner, "roles": roles, "uom": uom, "tax": tax,
        "cement": product("CEM", reorder_level="10"), "paint": product("PAINT", is_batch_tracked=True),
        "delivery": product("DELIVERY", product_type="service"),
        "main": location("MAIN", t["branch_id"]), "juja_store": location("JUJA-STORE", juja),
        "manager": user("manager", "Branch Manager", t["branch_id"]),
        "storekeeper": user("storekeeper", "Storekeeper", t["branch_id"]),
        "cashier": user("cashier", "Cashier", t["branch_id"]),
        "juja_keeper": user("jujakeeper", "Storekeeper", juja),
        "boss": user("boss", "Branch Manager", None),         # company-wide: may decide approvals
        "user": user,
    }

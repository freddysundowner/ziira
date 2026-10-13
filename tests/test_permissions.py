"""Permission and scope tests (a phase 1 exit criterion, specification section 21).

Each role can do exactly what it should: permission checks on endpoints, company and branch
scope, default roles seeded per unit, no privilege escalation, API key scopes, and no
cross-tenant access with a valid token.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in

WS = "scope-co"
OWNER = "owner@scope-co.test"
P = "/api/v1/products"


@pytest.fixture(scope="module")
def setup(client, registry):  # type: ignore[no-untyped-def]
    """Tenant with two companies (HQ branch + a second branch in company 1), products enabled,
    base data, and users: a cashier (branch), a manager (company 1), and an outsider (no role)."""
    from ziira.kernel.db import tenant_session

    t = make_tenant("Scope Co")
    registry.enable(t["tenant_id"], "products")
    co2, br2 = uuid4(), uuid4()
    with tenant_session(t["tenant_id"], admin=True) as s:
        s.execute(text("insert into kernel.company (id, tenant_id, name) values (:i, :t, 'Other Ltd')"),
                  {"i": str(co2), "t": str(t["tenant_id"])})
        s.execute(text("insert into kernel.branch (id, tenant_id, company_id, code, name) "
                       "values (:i, :t, :c, 'JUJA', 'Juja')"),
                  {"i": str(br2), "t": str(t["tenant_id"]), "c": str(t["company_id"])})
    owner = sign_in(client, WS, OWNER).headers
    roles = {r["name"]: r for r in client.get("/api/v1/roles", headers=owner).json()}
    uom = client.post(f"{P}/uoms", headers=owner, json={"code": "PCS", "name": "Pieces"}).json()
    tax = client.post(f"{P}/tax-codes", headers=owner,
                      json={"code": "VAT16", "name": "VAT", "vat_rate": "16", "etims_tax_type": "B"}).json()

    def user(name: str, role: str | None, scope: str = "tenant", company: UUID | None = None,
             branch: UUID | None = None) -> dict[str, str]:
        email = f"{name}@scope-co.test"
        u = client.post("/api/v1/users", headers=owner,
                        json={"full_name": name, "email": email, "password": f"{name}-pass-1"}).json()
        if role:
            r = client.post(f"/api/v1/users/{u['id']}/roles", headers=owner,
                            json={"role_id": roles[role]["id"], "scope": scope,
                                  "company_id": str(company) if company else None,
                                  "branch_id": str(branch) if branch else None})
            assert r.status_code == 201, r.text
        return sign_in(client, WS, email, f"{name}-pass-1").headers

    return {
        **t, "co2": co2, "br2": br2, "owner": owner, "roles": roles, "uom": uom["id"], "tax": tax["id"],
        "cashier": user("cashier", "Cashier", "branch", t["company_id"], t["branch_id"]),
        "manager": user("manager", "Branch Manager", "company", t["company_id"]),
        "outsider": user("outsider", None),
    }


def product(setup, company, sku: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {"company_id": str(company), "sku": sku, "name": sku, "base_uom_id": setup["uom"],
            "tax_code_id": setup["tax"]}


def test_default_roles_receive_unit_permissions_on_enable(setup) -> None:  # type: ignore[no-untyped-def]
    roles = setup["roles"]
    assert {"products.view", "products.manage", "users.manage"} <= set(roles["Owner"]["permissions"])
    assert roles["Cashier"]["permissions"] == ["products.view"]
    assert set(roles["Branch Manager"]["permissions"]) == {"approvals.decide", "products.view", "products.manage"}
    assert roles["HR"]["permissions"] == []


def test_user_without_a_role_is_refused(client, setup) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{P}/products", headers=setup["outsider"])
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"
    assert client.get("/api/v1/users", headers=setup["outsider"]).status_code == 403


def test_cashier_can_view_but_not_manage(client, setup) -> None:  # type: ignore[no-untyped-def]
    assert client.get(f"{P}/products", headers=setup["cashier"]).status_code == 200
    r = client.post(f"{P}/products", headers=setup["cashier"], json=product(setup, setup["company_id"], "C-1"))
    assert r.status_code == 403


def test_company_scope_limits_writes_and_reads(client, setup) -> None:  # type: ignore[no-untyped-def]
    other = client.post(f"{P}/products", headers=setup["owner"], json=product(setup, setup["co2"], "OTHER-1"))
    assert other.status_code == 201
    mine = client.post(f"{P}/products", headers=setup["manager"], json=product(setup, setup["company_id"], "MINE-1"))
    assert mine.status_code == 201, mine.text
    # Manager of company 1 cannot create in company 2
    r = client.post(f"{P}/products", headers=setup["manager"], json=product(setup, setup["co2"], "OTHER-2"))
    assert r.status_code == 403
    # ... and cannot see company 2's products
    skus = {p["sku"] for p in client.get(f"{P}/products", headers=setup["manager"]).json()}
    assert "MINE-1" in skus and "OTHER-1" not in skus
    assert client.get(f"{P}/products/{other.json()['id']}", headers=setup["manager"]).status_code == 404
    # A branch-scoped cashier still reads the products of the branch's company
    skus = {p["sku"] for p in client.get(f"{P}/products", headers=setup["cashier"]).json()}
    assert "MINE-1" in skus and "OTHER-1" not in skus
    # The owner sees both
    skus = {p["sku"] for p in client.get(f"{P}/products", headers=setup["owner"]).json()}
    assert {"MINE-1", "OTHER-1"} <= skus


def test_tenant_level_actions_need_a_tenant_wide_grant(client, setup) -> None:  # type: ignore[no-untyped-def]
    # Units are shared by every company, so a company-scoped manager cannot create them
    r = client.post(f"{P}/uoms", headers=setup["manager"], json={"code": "BOX", "name": "Box"})
    assert r.status_code == 403


def test_branch_grant_cannot_change_company_records(client, setup) -> None:  # type: ignore[no-untyped-def]
    owner = setup["owner"]
    role = client.post("/api/v1/roles", headers=owner,
                       json={"name": "Branch Products", "permissions": ["products.view", "products.manage"]}).json()
    u = client.post("/api/v1/users", headers=owner, json={"full_name": "Branch Clerk", "email": "bclerk@scope-co.test",
                                                          "password": "bclerk-pass-1"}).json()
    client.post(f"/api/v1/users/{u['id']}/roles", headers=owner,
                json={"role_id": role["id"], "scope": "branch", "company_id": str(setup["company_id"]),
                      "branch_id": str(setup["branch_id"])})
    clerk = sign_in(client, WS, "bclerk@scope-co.test", "bclerk-pass-1").headers
    r = client.post(f"{P}/products", headers=clerk, json=product(setup, setup["company_id"], "BR-1"))
    assert r.status_code == 403      # a product belongs to the whole company


def test_invalid_scopes_are_rejected(client, setup) -> None:  # type: ignore[no-untyped-def]
    owner, cashier_role = setup["owner"], setup["roles"]["Cashier"]["id"]
    u = client.get("/api/v1/users", headers=owner).json()[0]
    bad = [{"scope": "tenant", "company_id": str(setup["company_id"])},
           {"scope": "company"},
           {"scope": "branch", "company_id": str(setup["co2"]), "branch_id": str(setup["branch_id"])}]
    for body in bad:
        r = client.post(f"/api/v1/users/{u['id']}/roles", headers=owner, json={"role_id": cashier_role, **body})
        assert r.status_code == 422, body


def test_no_privilege_escalation(client, setup) -> None:  # type: ignore[no-untyped-def]
    owner, roles = setup["owner"], setup["roles"]
    admin_role = client.post("/api/v1/roles", headers=owner,
                             json={"name": "User Admin", "permissions": ["users.manage"]}).json()
    u = client.post("/api/v1/users", headers=owner, json={"full_name": "User Admin", "email": "uadmin@scope-co.test",
                                                          "password": "uadmin-pass-1"}).json()
    client.post(f"/api/v1/users/{u['id']}/roles", headers=owner, json={"role_id": admin_role["id"], "scope": "tenant"})
    uadmin = sign_in(client, WS, "uadmin@scope-co.test", "uadmin-pass-1").headers
    # May manage users ...
    assert client.get("/api/v1/users", headers=uadmin).status_code == 200
    # ... but cannot make themselves Owner, nor hand out permissions they lack
    r = client.post(f"/api/v1/users/{u['id']}/roles", headers=uadmin,
                    json={"role_id": roles["Owner"]["id"], "scope": "tenant"})
    assert r.status_code == 403
    r = client.post(f"/api/v1/users/{u['id']}/roles", headers=uadmin,
                    json={"role_id": roles["Cashier"]["id"], "scope": "tenant"})
    assert r.status_code == 403
    # ... and cannot edit roles at all
    assert client.post("/api/v1/roles", headers=uadmin, json={"name": "X", "permissions": []}).status_code == 403


def test_owner_role_is_protected(client, setup) -> None:  # type: ignore[no-untyped-def]
    owner, roles = setup["owner"], setup["roles"]
    r = client.put(f"/api/v1/roles/{roles['Owner']['id']}/permissions", headers=owner, json={"permissions": []})
    assert r.status_code == 422
    me = client.get("/api/v1/auth/me", headers=owner).json()
    owner_user = client.get("/api/v1/users", headers=owner).json()
    owner_id = next(u["id"] for u in owner_user if u["email"] == OWNER)
    [grant] = [g for g in client.get(f"/api/v1/users/{owner_id}/roles", headers=owner).json()
               if g["role_name"] == "Owner"]
    r = client.delete(f"/api/v1/users/{owner_id}/roles/{grant['id']}", headers=owner)
    assert r.status_code == 422 and "owner" in r.json()["message"]
    assert me["roles"][0]["role_name"] == "Owner"


def test_role_changes_apply_to_existing_sessions(client, setup) -> None:  # type: ignore[no-untyped-def]
    owner, roles = setup["owner"], setup["roles"]
    hr = roles["HR"]
    u = client.post("/api/v1/users", headers=owner, json={"full_name": "HR Person", "email": "hr@scope-co.test",
                                                          "password": "hrperson-pass-1"}).json()
    client.post(f"/api/v1/users/{u['id']}/roles", headers=owner, json={"role_id": hr["id"], "scope": "tenant"})
    person = sign_in(client, WS, "hr@scope-co.test", "hrperson-pass-1").headers
    assert client.get(f"{P}/products", headers=person).status_code == 403
    r = client.put(f"/api/v1/roles/{hr['id']}/permissions", headers=owner, json={"permissions": ["products.view"]})
    assert r.status_code == 200
    assert client.get(f"{P}/products", headers=person).status_code == 200


def test_api_key_scopes(client, setup) -> None:  # type: ignore[no-untyped-def]
    owner = setup["owner"]
    bad = client.post("/api/v1/api-keys", headers=owner, json={"name": "x", "scopes": ["no.such"]})
    assert bad.status_code == 422
    created = client.post("/api/v1/api-keys", headers=owner, json={"name": "Shop sync", "scopes": ["products.view"]})
    assert created.status_code == 201
    key = {"X-API-Key": created.json()["key"]}
    assert client.get(f"{P}/products", headers=key).status_code == 200
    r = client.post(f"{P}/products", headers=key, json=product(setup, setup["company_id"], "KEY-1"))
    assert r.status_code == 403
    listed = client.get("/api/v1/api-keys", headers=owner).json()
    assert "key" not in listed[0] and listed[0]["name"] == "Shop sync"
    assert client.delete(f"/api/v1/api-keys/{created.json()['id']}", headers=owner).status_code == 204
    assert client.get(f"{P}/products", headers=key).status_code == 401
    # A key whose tenant part is altered finds nothing
    _, tenant_hex, secret = created.json()["key"].split("_", 2)
    forged = {"X-API-Key": f"zk_{uuid4().hex}_{secret}"}
    assert client.get(f"{P}/products", headers=forged).status_code == 401


def test_a_valid_token_never_reaches_another_tenant(client, setup, registry) -> None:  # type: ignore[no-untyped-def]
    other = make_tenant("Neighbour Co")
    registry.enable(other["tenant_id"], "products")
    theirs_owner = sign_in(client, "neighbour-co", "owner@neighbour-co.test").headers
    uom = client.post(f"{P}/uoms", headers=theirs_owner, json={"code": "PCS", "name": "Pieces"}).json()
    tax = client.post(f"{P}/tax-codes", headers=theirs_owner,
                      json={"code": "VAT0", "name": "Zero", "vat_rate": "0", "etims_tax_type": "A"}).json()
    theirs = client.post(f"{P}/products", headers=theirs_owner,
                         json={"company_id": str(other["company_id"]), "sku": "THEIRS-1", "name": "Theirs",
                               "base_uom_id": uom["id"], "tax_code_id": tax["id"]}).json()
    owner = setup["owner"]
    assert client.get(f"{P}/products/{theirs['id']}", headers=owner).status_code == 404
    assert theirs["id"] not in {p["id"] for p in client.get(f"{P}/products", headers=owner).json()}
    # Naming the other tenant's company is refused (foreign keys alone would accept it)
    r = client.post(f"{P}/products", headers=owner, json=product(setup, other["company_id"], "SNEAK-1"))
    assert r.status_code == 422 and r.json()["message"] == "Company not found"


def test_unit_permissions_do_not_bypass_a_disabled_unit(client, setup, registry) -> None:  # type: ignore[no-untyped-def]
    registry.enable(setup["tenant_id"], "catalog_stats")
    owner = setup["owner"]
    assert client.get("/api/v1/plugins/catalog-stats", headers=owner).status_code == 200
    registry.disable(setup["tenant_id"], "catalog_stats")
    r = client.get("/api/v1/plugins/catalog-stats", headers=owner)
    assert r.status_code == 404 and r.json()["error"] == "unit_not_enabled"



def test_companies_list_follows_scope(client, setup) -> None:  # type: ignore[no-untyped-def]
    owner = {c["name"]: c for c in client.get("/api/v1/companies", headers=setup["owner"]).json()}
    assert set(owner) == {"Scope Co Ltd", "Other Ltd"}
    assert {b["code"] for b in owner["Scope Co Ltd"]["branches"]} == {"HQ", "JUJA"}
    manager = client.get("/api/v1/companies", headers=setup["manager"]).json()
    assert [c["name"] for c in manager] == ["Scope Co Ltd"]          # company-scoped role
    cashier = client.get("/api/v1/companies", headers=setup["cashier"]).json()
    assert [c["name"] for c in cashier] == ["Scope Co Ltd"]          # branch role: its company

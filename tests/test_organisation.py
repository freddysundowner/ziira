"""Companies and branches after registration: adding, editing, closing; who may; and that a new branch works at once."""

import pytest
from sqlalchemy import text

from tests.conftest import sign_in
from tests.pos_helpers import POS, line, make_pos_shop, sell
from tests.stock_helpers import INV, system

ORG = "/api/v1/organisation"


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_pos_shop(client, registry, "Org Co", finance=True)


@pytest.fixture(scope="module")
def other(client, registry):  # type: ignore[no-untyped-def]
    """A second, unrelated business."""
    return make_pos_shop(client, registry, "Org Other", finance=True)


def company_of(client, headers, company_id: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return next(c for c in client.get(ORG, headers=headers).json() if c["id"] == company_id)


def new_branch(client, shop, code: str, **extra) -> dict:  # type: ignore[no-untyped-def,type-arg]
    r = client.post(f"/api/v1/companies/{shop['company_id']}/branches", headers=shop["owner"],
                    json={"code": code, "name": f"Branch {code}", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_only_the_owner_holds_the_permission_by_default(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.get(ORG, headers=shop["owner"]).status_code == 200
    for who in ("boss", "manager", "cashier", "fm"):
        assert client.get(ORG, headers=shop[who]).status_code == 403, who
        assert client.post("/api/v1/companies", headers=shop[who], json={"name": "X", "currency": "USD"}
                           ).status_code == 403
    assert client.get(ORG).status_code in (401, 403)


def test_list_shows_branches_with_counts(client, shop) -> None:  # type: ignore[no-untyped-def]
    mine = company_of(client, shop["owner"], str(shop["company_id"]))
    assert mine["currency"] == "KES" or len(mine["currency"]) == 3
    hq = next(b for b in mine["branches"] if b["code"] == "HQ")
    assert hq["is_active"] is True
    # The shop has users with branch roles at HQ, three devices, and the MAIN location
    assert hq["counts"]["users"] >= 2
    assert hq["counts"]["devices"] == 3
    assert hq["counts"]["locations"] >= 1
    juja = next(b for b in mine["branches"] if b["code"] == "JUJA")
    assert juja["counts"]["devices"] == 0 and juja["counts"]["locations"] == 1


def test_add_a_company_with_its_first_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/companies", headers=shop["owner"], json={
        "name": "Org Co Uganda", "currency": "ugx", "country": "ug", "tax_id": "T-1", "timezone": "Africa/Kampala",
        "branch_code": "kla", "branch_name": "Kampala"})
    assert r.status_code == 201, r.text
    made = r.json()
    assert (made["currency"], made["country"], made["timezone"], made["tax_id"]) == ("UGX", "UG", "Africa/Kampala", "T-1")
    assert [b["code"] for b in made["branches"]] == ["KLA"]
    # it shows in the ordinary company list the pickers use, and has its own settings
    assert any(c["name"] == "Org Co Uganda" for c in client.get("/api/v1/companies", headers=shop["owner"]).json())
    st = client.get(f"/api/v1/companies/{made['id']}/settings", headers=shop["owner"]).json()
    assert st["timezone"] == "Africa/Kampala"
    # the calling code of the business carries over to the new company
    assert st["phone_country_code"] == client.get(
        f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"]).json()["phone_country_code"]
    # its books are made when first needed: it can have a chart straight away
    assert client.get("/api/v1/finance/accounts", headers=shop["owner"], params={"company_id": made["id"]}
                      ).status_code == 200


def test_company_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    own = shop["owner"]
    bad = [{"name": "  ", "currency": "USD"}, {"name": "A1", "currency": "US1"}, {"name": "A2", "currency": "USD",
           "country": "USA"}, {"name": "A3", "currency": "USD", "timezone": "Mars/Base"},
           {"name": "A4", "currency": "USD", "branch_code": "X"}]
    for body in bad:
        assert client.post("/api/v1/companies", headers=own, json=body).status_code == 422, body
    assert client.post("/api/v1/companies", headers=own, json={"name": "org co uganda", "currency": "USD"}
                       ).status_code == 409                                         # same name, any case


def test_edit_a_company(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = client.post("/api/v1/companies", headers=shop["owner"], json={"name": "Edit Me", "currency": "USD"}).json()
    r = client.patch(f"/api/v1/companies/{made['id']}", headers=shop["owner"], json={
        "name": "Edited Ltd", "tax_id": "P000", "vat_registered": True, "timezone": "Europe/London",
        "currency": "EUR"})                       # no postings yet: the currency may still change
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["name"], got["tax_id"], got["vat_registered"], got["timezone"], got["currency"]) == (
        "Edited Ltd", "P000", True, "Europe/London", "EUR")
    assert client.patch(f"/api/v1/companies/{made['id']}", headers=shop["owner"], json={"name": "Org Co Uganda"}
                        ).status_code == 409
    assert client.patch(f"/api/v1/companies/{made['id']}", headers=shop["owner"], json={"nonsense": 1}
                        ).status_code == 422


def test_currency_is_fixed_once_the_company_has_postings(client, shop) -> None:  # type: ignore[no-untyped-def]
    sale = sell(client, shop)
    assert sale.status_code == 201, sale.text
    r = client.patch(f"/api/v1/companies/{shop['company_id']}", headers=shop["owner"], json={"currency": "XTS"})
    assert r.status_code == 409
    assert "already has" in r.json()["message"] and "sales recorded" in r.json()["message"]
    assert company_of(client, shop["owner"], str(shop["company_id"]))["currency_locked"] is True
    # saying the same currency again is no change
    cur = company_of(client, shop["owner"], str(shop["company_id"]))["currency"]
    assert client.patch(f"/api/v1/companies/{shop['company_id']}", headers=shop["owner"], json={"currency": cur}
                        ).status_code == 200
    # other fields stay editable
    assert client.patch(f"/api/v1/companies/{shop['company_id']}", headers=shop["owner"], json={"tax_id": "Z-9"}
                        ).status_code == 200


def test_branch_codes_and_names(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = new_branch(client, shop, "msa", address="Moi Avenue", phone="0700 000 000")
    assert made["code"] == "MSA" and made["address"] == "Moi Avenue" and made["is_active"] is True
    co = str(shop["company_id"])
    for body in ({"code": "MSA", "name": "Dup"}, ):
        assert client.post(f"/api/v1/companies/{co}/branches", headers=shop["owner"], json=body).status_code == 409
    for body in ({"code": "has space", "name": "x"}, {"code": "", "name": "x"}, {"code": "TOOLONGCODE1", "name": "x"},
                 {"code": "OK", "name": "   "}):
        assert client.post(f"/api/v1/companies/{co}/branches", headers=shop["owner"], json=body).status_code == 422, body
    r = client.patch(f"/api/v1/branches/{made['id']}", headers=shop["owner"], json={
        "name": "Mombasa Road", "code": "mrd", "phone": None})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["code"], r.json()["phone"], r.json()["address"]) == (
        "Mombasa Road", "MRD", None, "Moi Avenue")
    assert client.patch(f"/api/v1/branches/{made['id']}", headers=shop["owner"], json={"code": "HQ"}).status_code == 409


def test_scope_a_company_role_manages_only_its_company(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    owner = shop["owner"]
    second = client.post("/api/v1/companies", headers=owner, json={
        "name": "Org Co Second", "currency": "USD", "branch_code": "S1", "branch_name": "Second shop"}).json()
    perms = client.post("/api/v1/roles", headers=owner, json={"name": "Org admin", "permissions": ["organisation.manage"]})
    assert perms.status_code == 201, perms.text
    u = client.post("/api/v1/users", headers=owner, json={
        "full_name": "Org Admin", "email": "orgadmin@org-co.test", "password": "orgadmin-pass-1"}).json()
    r = client.post(f"/api/v1/users/{u['id']}/roles", headers=owner, json={
        "role_id": perms.json()["id"], "scope": "company", "company_id": second["id"]})
    assert r.status_code == 201, r.text
    admin = sign_in(client, shop["code"], "orgadmin@org-co.test", "orgadmin-pass-1").headers

    listed = client.get(ORG, headers=admin).json()
    assert [c["id"] for c in listed] == [second["id"]]                        # only the company they manage
    assert client.post(f"/api/v1/companies/{second['id']}/branches", headers=admin,
                       json={"code": "S2", "name": "Another"}).status_code == 201
    assert client.patch(f"/api/v1/companies/{second['id']}", headers=admin, json={"tax_id": "OK-1"}).status_code == 200
    # not the other company, its branches, nor a new company
    assert client.patch(f"/api/v1/companies/{shop['company_id']}", headers=admin, json={"tax_id": "NO"}).status_code == 403
    assert client.post(f"/api/v1/companies/{shop['company_id']}/branches", headers=admin,
                       json={"code": "ZZ", "name": "No"}).status_code == 403
    assert client.patch(f"/api/v1/branches/{shop['branch_id']}", headers=admin, json={"name": "No"}).status_code == 403
    assert client.post(f"/api/v1/branches/{shop['branch_id']}/deactivate", headers=admin).status_code == 403
    assert client.post("/api/v1/companies", headers=admin, json={"name": "Third", "currency": "USD"}).status_code == 403
    # a branch-scoped holder cannot manage the company either
    b = client.post("/api/v1/users", headers=owner, json={
        "full_name": "Branch Admin", "email": "branchadmin@org-co.test", "password": "branchadmin-pass-1"}).json()
    client.post(f"/api/v1/users/{b['id']}/roles", headers=owner, json={
        "role_id": perms.json()["id"], "scope": "branch", "company_id": second["id"], "branch_id": second["branches"][0]["id"]})
    branch_admin = sign_in(client, shop["code"], "branchadmin@org-co.test", "branchadmin-pass-1").headers
    assert client.post(f"/api/v1/companies/{second['id']}/branches", headers=branch_admin,
                       json={"code": "S3", "name": "Nope"}).status_code == 403


def test_no_access_across_businesses(client, shop, other) -> None:  # type: ignore[no-untyped-def]
    mine_company, mine_branch = str(shop["company_id"]), str(shop["branch_id"])
    assert client.patch(f"/api/v1/companies/{mine_company}", headers=other["owner"], json={"name": "Hijacked"}
                        ).status_code == 404
    assert client.post(f"/api/v1/companies/{mine_company}/branches", headers=other["owner"],
                       json={"code": "EVIL", "name": "x"}).status_code == 404
    assert client.patch(f"/api/v1/branches/{mine_branch}", headers=other["owner"], json={"name": "Hijacked"}).status_code == 404
    assert client.post(f"/api/v1/branches/{mine_branch}/deactivate", headers=other["owner"]).status_code == 404
    seen = {c["id"] for c in client.get(ORG, headers=other["owner"]).json()}
    assert mine_company not in seen
    assert company_of(client, shop["owner"], mine_company)["name"] != "Hijacked"


def test_a_branch_with_work_in_progress_cannot_be_closed(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co = shop["owner"], str(shop["company_id"])
    # HQ has the cashier's open till, so it may not close (and the reason says so)
    sale = sell(client, shop)                                                   # makes sure the till is open
    assert sale.status_code == 201, sale.text
    r = client.post(f"/api/v1/branches/{shop['branch_id']}/deactivate", headers=owner)
    assert r.status_code == 409 and "till" in r.json()["message"], r.text
    # a transfer in transit from JUJA's store to HQ's blocks JUJA
    r = client.post(f"{INV}/transfers", headers=owner, json={
        "company_id": co, "from_location_id": shop["main"], "to_location_id": shop["juja_store"],
        "lines": [{"product_id": shop["cement"], "quantity": "1"}]})
    assert r.status_code == 201, r.text
    transfer = r.json()["id"]
    r = client.post(f"/api/v1/branches/{shop['juja']}/deactivate", headers=owner)
    assert r.status_code == 409 and "not posted" in r.json()["message"], r.text          # still a draft
    dispatched = client.post(f"{INV}/transfers/{transfer}/dispatch", headers=owner)
    assert dispatched.status_code == 200, dispatched.text
    r = client.post(f"/api/v1/branches/{shop['juja']}/deactivate", headers=owner)
    assert r.status_code == 409 and "in transit" in r.json()["message"], r.text
    assert client.post(f"{INV}/transfers/{transfer}/receive", headers=owner).status_code == 200
    # nothing else holds JUJA: it closes, disappears from the pickers, history stays, and reopens
    r = client.post(f"/api/v1/branches/{shop['juja']}/deactivate", headers=owner)
    assert r.status_code == 200 and r.json()["is_active"] is False, r.text
    pickers = client.get("/api/v1/companies", headers=owner).json()
    mine = next(c for c in pickers if c["id"] == co)
    assert "JUJA" not in [b["code"] for b in mine["branches"]]
    assert "JUJA" in [b["code"] for b in company_of(client, owner, co)["branches"]]
    assert client.get(f"{INV}/locations", headers=owner).status_code == 200
    r = client.post(f"/api/v1/branches/{shop['juja']}/reactivate", headers=owner)
    assert r.status_code == 200 and r.json()["is_active"] is True


def test_the_last_open_branch_stays(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = client.post("/api/v1/companies", headers=shop["owner"], json={
        "name": "Solo Ltd", "currency": "USD", "branch_code": "ONE", "branch_name": "Only"}).json()
    r = client.post(f"/api/v1/branches/{made['branches'][0]['id']}/deactivate", headers=shop["owner"])
    assert r.status_code == 409 and "only open branch" in r.json()["message"]


def test_everything_is_audited(client, shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        actions = {(r.action, r.entity_type) for r in s.execute(text(
            "select action, entity_type from kernel.audit_log where entity_type in ('kernel.company', 'kernel.branch')"))}
    assert {("create", "kernel.company"), ("update", "kernel.company"), ("create", "kernel.branch"),
            ("update", "kernel.branch"), ("deactivate", "kernel.branch"), ("reactivate", "kernel.branch")} <= actions


def test_a_new_branch_works_at_once_and_its_sales_stay_in_its_scope(client, shop) -> None:  # type: ignore[no-untyped-def]
    owner, co = shop["owner"], str(shop["company_id"])
    nb = new_branch(client, shop, "NEWB")
    # a location, stocked, and a till device for the new branch
    loc = client.post(f"{INV}/locations", headers=owner, json={
        "company_id": co, "branch_id": nb["id"], "code": "NEWB-STORE", "name": "New store"})
    assert loc.status_code == 201, loc.text
    stocked = client.post(f"{INV}/opening-stock", headers=owner, json={
        "company_id": co, "location_id": loc.json()["id"], "lines": [
            {"product_id": shop["cement"], "quantity": "20", "unit_cost": "50"}]})
    assert stocked.status_code == 201, stocked.text
    device = client.post(f"{POS}/devices", headers=owner, json={
        "branch_id": nb["id"], "code": "NB1", "name": "New till", "location_id": loc.json()["id"]})
    assert device.status_code == 201, device.text
    # a cashier scoped to the new branch only
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner).json()}
    made = client.post("/api/v1/users", headers=owner, json={
        "full_name": "Nia Newb", "email": "nia@org-co.test", "password": "nia-pass-12345"}).json()
    r = client.post(f"/api/v1/users/{made['id']}/roles", headers=owner, json={
        "role_id": roles["Cashier"], "scope": "branch", "company_id": co, "branch_id": nb["id"]})
    assert r.status_code == 201, r.text
    nia = sign_in(client, shop["code"], "nia@org-co.test", "nia-pass-12345").headers
    shop["nia"] = nia
    # the branch list shows what was added
    counts = next(b for b in company_of(client, owner, co)["branches"] if b["id"] == nb["id"])["counts"]
    assert counts == {"devices": 1, "locations": 1, "users": 1}

    # she opens a till on her device and sells; stock at the new location goes down
    till = client.post(f"{POS}/tills", headers=nia, json={"device_id": device.json()["id"], "opening_float": "100.00"})
    assert till.status_code == 201, till.text
    sale = client.post(f"{POS}/sales", headers=nia, json={
        "till_session_id": till.json()["id"], "lines": [line(shop)], "payments": [{"method": "cash", "amount": "116.00"}]})
    assert sale.status_code == 201, sale.text
    assert sale.json()["branch_id"] == nb["id"]
    # HQ's cashier has sold too (the earlier tests); each sees only their own branch
    hq_sale = sell(client, shop)
    assert hq_sale.status_code == 201
    mine = client.get(f"{POS}/sales", headers=nia).json()
    assert {x["branch_id"] for x in mine} == {nb["id"]} and len(mine) == 1
    hq_list = client.get(f"{POS}/sales", headers=shop["cashier"]).json()
    assert nb["id"] not in {x["branch_id"] for x in hq_list} and len(hq_list) >= 2
    # and the other branch's ids are refused
    assert client.get(f"{POS}/sales/{hq_sale.json()['id']}", headers=nia).status_code in (403, 404)
    assert client.get(f"{POS}/sales/{sale.json()['id']}", headers=shop["cashier"]).status_code in (403, 404)
    # the owner sees both
    both = {x["branch_id"] for x in client.get(f"{POS}/sales", headers=owner).json()}
    assert {nb["id"], str(shop["branch_id"])} <= both
    # a till is open there now, so the branch cannot be closed
    r = client.post(f"/api/v1/branches/{nb['id']}/deactivate", headers=owner)
    assert r.status_code == 409 and "till" in r.json()["message"]
    # closed tills (and nothing in progress) let it go, and its signed-in cashier can no longer open a till
    report = client.get(f"{POS}/tills/{till.json()['id']}/report", headers=nia).json()
    assert client.post(f"{POS}/tills/{till.json()['id']}/close", headers=nia,
                       json={"counted_cash": report["expected_cash"]}).status_code == 200
    r = client.post(f"/api/v1/branches/{nb['id']}/deactivate", headers=owner)
    assert r.status_code == 200, r.text
    # a closed branch takes no new locations, devices or tills
    assert client.post(f"{INV}/locations", headers=owner, json={
        "company_id": co, "branch_id": nb["id"], "code": "NEWB-2", "name": "x"}).status_code == 422
    assert client.post(f"{POS}/devices", headers=owner, json={
        "branch_id": nb["id"], "code": "NB2", "name": "x", "location_id": loc.json()["id"]}).status_code == 422
    again = client.post(f"{POS}/tills", headers=nia, json={"device_id": device.json()["id"], "opening_float": "1.00"})
    assert again.status_code == 422 and "closed" in again.json()["message"], again.text


def test_a_kernel_upgrade_gives_existing_owners_the_new_permission(client, registry, other) -> None:  # type: ignore[no-untyped-def]
    """Businesses made before the permission existed get it for their Owner role when the kernel is upgraded."""
    with system(other) as s:
        s.execute(text("delete from kernel.role_permission where permission_code = 'organisation.manage'"))
    assert client.get(ORG, headers=other["owner"]).status_code in (401, 403)       # (the token carries the old grants)
    registry.install("kernel")
    fresh = sign_in(client, other["code"], f"owner@{other['code']}.test").headers
    assert client.get(ORG, headers=fresh).status_code == 200

"""Employees, pay setup (terms, items, bank details) and the business's own statutory rules."""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.people_helpers import HEALTH, PENSION, PEOPLE, TAX, make_people_shop, new_employee
from tests.stock_helpers import system


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_people_shop(client, registry, "People Co")


def db(shop, sql, **params):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return s.execute(text(sql), params).all()


# --------------------------------------------------------------------------- employees
def test_an_employee_is_registered_with_private_details_protected(client, shop) -> None:  # type: ignore[no-untyped-def]
    dept = client.post(f"{PEOPLE}/departments", headers=shop["hr"], json={"company_id": shop["company"],
                                                                         "name": "Sales"})
    assert dept.status_code == 201, dept.text
    assert client.post(f"{PEOPLE}/departments", headers=shop["hr"], json={
        "company_id": shop["company"], "name": "Sales"}).status_code == 409
    e = new_employee(client, shop, branch_id=str(shop["branch_id"]), department_id=dept.json()["id"],
                     national_id="98 765 432", tax_id="a123456789z", phone="0712 345 678", email="Amina@Shop.TEST",
                     registrations={"pension": "PEN-001", "health": "H/77"}, exempt_rules=["pension", "pension"])
    assert e["employee_no"] == "EMP-000001" and e["status"] == "active"
    assert e["national_id_masked"] == "*****432" and "98765432" not in str(e)               # only the end is shown
    assert e["tax_id"] == "A123456789Z" and e["phone"] == "254712345678" and e["email"] == "amina@shop.test"
    assert e["registrations"] == {"PENSION": "PEN-001", "HEALTH": "H/77"} and e["exempt_rules"] == ["PENSION"]
    raw = db(shop, "select national_id_ciphertext from people.employee where id = :i", i=e["id"])[0][0]
    assert b"98765432" not in bytes(raw) and len(raw) > 20                                    # stored encrypted
    assert new_employee(client, shop, name="Second Person")["employee_no"] == "EMP-000002"
    got = client.get(f"{PEOPLE}/employees/{e['id']}", headers=shop["hr"]).json()
    assert got == e


def test_the_company_phone_code_decides_how_national_numbers_are_read(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert new_employee(client, shop, name="Intl One", phone="+44 7911 123456")["phone"] == "447911123456"
    assert new_employee(client, shop, name="Intl Two", phone="0044 7911 123457")["phone"] == "447911123457"
    assert new_employee(client, shop, name="Local", phone="712345679")["phone"] == "254712345679"
    patched = client.patch(f"/api/v1/companies/{shop['company']}/settings", headers=shop["owner"],
                           json={"phone_country_code": "44"})
    assert patched.status_code == 200
    assert new_employee(client, shop, name="Brit", phone="07911 123458")["phone"] == "447911123458"
    client.patch(f"/api/v1/companies/{shop['company']}/settings", headers=shop["owner"],
                 json={"phone_country_code": ""})
    refused = client.post(f"{PEOPLE}/employees", headers=shop["hr"], json={
        "company_id": shop["company"], "full_name": "No Code", "hire_date": "2025-01-06", "phone": "0712345678"})
    assert refused.status_code == 422 and "country code" in refused.json()["message"]
    assert new_employee(client, shop, name="Plus Only", phone="+254712345680")["phone"] == "254712345680"
    client.patch(f"/api/v1/companies/{shop['company']}/settings", headers=shop["owner"],
                 json={"phone_country_code": "254"})


def test_employee_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    base = {"company_id": shop["company"], "full_name": "Test Person", "hire_date": "2025-01-06"}
    for bad in ({"full_name": "   "}, {"tax_id": "!!"}, {"national_id": "x"}, {"phone": "12"}, {"email": "nope"},
                {"registrations": {"1bad": "x"}}, {"registrations": {"PENSION": "!"}}, {"employee_no": "x" * 31},
                {"residency": "alien"}, {"department_id": str(uuid4())}, {"branch_id": str(uuid4())},
                {"user_id": str(uuid4())}, {"hire_date": "soon"}, {"exempt_rules": ["x" * 21]}):
        assert client.post(f"{PEOPLE}/employees", headers=shop["hr"], json={**base, **bad}).status_code in (
            404, 422), bad
    first = new_employee(client, shop, name="Numbered", employee_no="staff-9")
    assert first["employee_no"] == "STAFF-9"
    assert client.post(f"{PEOPLE}/employees", headers=shop["hr"], json={**base, "employee_no": "STAFF-9"}
                       ).status_code == 409


def test_an_employee_can_be_linked_to_a_user_changed_and_terminated(client, shop) -> None:  # type: ignore[no-untyped-def]
    users = client.get("/api/v1/users", headers=shop["owner"]).json()
    manager_id = next(u["id"] for u in users if u["email"].startswith("manager@"))
    e = new_employee(client, shop, name="Linked", user_id=manager_id)
    assert e["user_id"] == manager_id
    assert client.post(f"{PEOPLE}/employees", headers=shop["hr"], json={
        "company_id": shop["company"], "full_name": "Twin", "hire_date": "2025-01-06", "user_id": manager_id}
    ).status_code == 409                                                                      # one person, one record
    path = f"{PEOPLE}/employees/{e['id']}"
    changed = client.patch(path, headers=shop["hr"], json={"full_name": "  Linked   Renamed ", "tax_id": "p000000001a",
                                                           "branch_id": str(shop["juja"])})
    assert changed.status_code == 200 and changed.json()["full_name"] == "Linked Renamed"
    assert changed.json()["tax_id"] == "P000000001A" and changed.json()["branch_id"] == str(shop["juja"])
    assert client.patch(path, headers=shop["hr"], json={"employee_no": "NEW"}).status_code == 422   # not changeable
    early = client.post(f"{path}/terminate", headers=shop["hr"], json={"termination_date": "2024-01-01"})
    assert early.status_code == 422
    left = client.post(f"{path}/terminate", headers=shop["hr"], json={"termination_date": "2025-06-30",
                                                                    "reason": "Resigned"})
    assert left.status_code == 200 and left.json()["status"] == "terminated"
    assert client.post(f"{path}/terminate", headers=shop["hr"], json={"termination_date": "2025-07-01"}
                       ).status_code == 409
    assert client.patch(path, headers=shop["hr"], json={"full_name": "Late"}).status_code == 409


def test_employee_lists_and_who_sees_whom(client, shop) -> None:  # type: ignore[no-untyped-def]
    new_employee(client, shop, name="At Headquarters", branch_id=str(shop["branch_id"]))
    new_employee(client, shop, name="At Juja", branch_id=str(shop["juja"]))
    everyone = client.get(f"{PEOPLE}/employees", headers=shop["hr"], params={"company_id": shop["company"],
                                                                           "limit": 200}).json()
    assert len(everyone) >= 5
    seen = client.get(f"{PEOPLE}/employees", headers=shop["manager"], params={"limit": 200}).json()   # branch manager
    assert seen and all(x["branch_id"] == str(shop["branch_id"]) for x in seen)
    juja = next(x for x in everyone if x["full_name"] == "At Juja")
    assert client.get(f"{PEOPLE}/employees/{juja['id']}", headers=shop["manager"]).status_code == 404
    found = client.get(f"{PEOPLE}/employees", headers=shop["hr"], params={"search": "juja"}).json()
    assert [x["full_name"] for x in found] == ["At Juja"]
    left = client.get(f"{PEOPLE}/employees", headers=shop["hr"], params={"status": "terminated"}).json()
    assert left and all(x["status"] == "terminated" for x in left)
    assert client.get(f"{PEOPLE}/employees", headers=shop["hr"], params={"status": "weird"}).status_code == 422
    assert client.get(f"{PEOPLE}/employees", headers=shop["cashier"]).status_code == 403
    assert client.post(f"{PEOPLE}/employees", headers=shop["manager"], json={
        "company_id": shop["company"], "full_name": "Nope", "hire_date": "2025-01-06"}).status_code == 403
    assert client.get(f"{PEOPLE}/departments", headers=shop["manager"]).status_code == 200


# --------------------------------------------------------------------------- pay: components, terms, items
def test_pay_components(client, shop) -> None:  # type: ignore[no-untyped-def]
    path = f"{PEOPLE}/pay-components"
    house = client.post(path, headers=shop["hr"], json={"company_id": shop["company"], "code": "house",
                                                        "name": "House allowance", "kind": "earning"})
    assert house.status_code == 201 and house.json()["code"] == "HOUSE"
    assert client.post(path, headers=shop["hr"], json={"company_id": shop["company"], "code": "HOUSE", "name": "x",
                                                       "kind": "earning"}).status_code == 409
    for code in ("BASIC", "UNPAID_LEAVE", "PENSION_ER", "1ABC", "bad code", "x" * 21, ""):
        r = client.post(path, headers=shop["hr"], json={"company_id": shop["company"], "code": code, "name": "x",
                                                        "kind": "earning"})
        assert r.status_code == 422, code
    assert client.post(path, headers=shop["hr"], json={"company_id": shop["company"], "code": "X", "name": "x",
                                                       "kind": "gift"}).status_code == 422
    assert client.post(path, headers=shop["manager"], json={"company_id": shop["company"], "code": "Z", "name": "x",
                                                            "kind": "earning"}).status_code == 403
    assert [c["code"] for c in client.get(path, headers=shop["hr"], params={"company_id": shop["company"]}).json()
            ] == ["HOUSE"]


def test_basic_pay_is_proposed_then_approved_by_someone_else(client, shop) -> None:  # type: ignore[no-untyped-def]
    e = new_employee(client, shop, name="Paid Person", hire_date="2025-03-01")
    path = f"{PEOPLE}/employees/{e['id']}/terms"
    assert client.post(path, headers=shop["hr"], json={"basic_pay": "50000", "valid_from": "2025-02-01"}
                       ).status_code == 422                                                   # before they were hired
    proposed = client.post(path, headers=shop["hr"], json={"basic_pay": "50000", "valid_from": "2025-03-01",
                                                           "note": "Offer letter"})
    assert proposed.status_code == 201 and proposed.json()["approved_by"] is None
    t1 = proposed.json()["id"]
    assert client.post(path, headers=shop["hr"], json={"basic_pay": "1", "valid_from": "2025-04-01"}
                       ).status_code == 409                                                   # one waiting at a time
    assert client.post(f"{PEOPLE}/terms/{t1}/approve", headers=shop["hr"]).status_code == 403   # not their own
    approved = client.post(f"{PEOPLE}/terms/{t1}/approve", headers=shop["finance"])
    assert approved.status_code == 200 and approved.json()["approved_by"]
    assert client.post(f"{PEOPLE}/terms/{t1}/approve", headers=shop["finance"]).status_code == 409
    assert client.post(path, headers=shop["hr"], json={"basic_pay": "60000", "valid_from": "2025-03-01"}
                       ).status_code == 422                                                   # must start later
    raise_ = client.post(path, headers=shop["hr"], json={"basic_pay": "60000", "valid_from": "2025-07-01"}).json()
    assert client.post(f"{PEOPLE}/terms/{raise_['id']}/approve", headers=shop["finance2"]).status_code == 200
    history = client.get(path, headers=shop["hr"]).json()
    assert [(t["basic_pay"], t["valid_from"], t["valid_to"]) for t in history] == [
        ("60000.00", "2025-07-01", None), ("50000.00", "2025-03-01", "2025-06-30")]            # the old one is closed
    declined = client.post(path, headers=shop["hr"], json={"basic_pay": "99999", "valid_from": "2025-09-01"}).json()
    assert client.post(f"{PEOPLE}/terms/{declined['id']}/reject", headers=shop["finance"]).json()["rejected"] is True
    assert client.post(f"{PEOPLE}/terms/{declined['id']}/approve", headers=shop["finance"]).status_code == 409
    for bad in ({"basic_pay": "-1"}, {"basic_pay": "abc"}, {"basic_pay": "1000000000"}):
        assert client.post(path, headers=shop["hr"], json={**bad, "valid_from": "2026-01-01"}).status_code == 422, bad
    assert client.get(path, headers=shop["manager"]).status_code == 403                       # pay is not for managers
    assert client.get(path, headers=shop["cashier"]).status_code == 403
    assert client.post(f"{PEOPLE}/terms/{uuid4()}/approve", headers=shop["finance"]).status_code == 404


def test_pay_items_recurring_and_one_off(client, shop) -> None:  # type: ignore[no-untyped-def]
    e = new_employee(client, shop, name="Item Person")
    house = client.get(f"{PEOPLE}/pay-components", headers=shop["hr"]).json()[0]["id"]
    path = f"{PEOPLE}/employees/{e['id']}/pay-items"
    item = client.post(path, headers=shop["hr"], json={"component_id": house, "amount": "5000",
                                                      "valid_from": "2025-01-06"})
    assert item.status_code == 201 and item.json()["recurring"] is True
    bonus = client.post(path, headers=shop["hr"], json={"component_id": house, "amount": "1000",
                                                       "valid_from": "2025-03-15", "recurring": False})
    assert bonus.status_code == 201
    for bad in ({"amount": "0"}, {"amount": "-5"}, {"component_id": str(uuid4())},
                {"recurring": False, "valid_to": "2025-04-01"}, {"valid_to": "2024-01-01"}):
        r = client.post(path, headers=shop["hr"], json={"component_id": house, "amount": "10",
                                                        "valid_from": "2025-01-06", **bad})
        assert r.status_code == 422, bad
    ended = client.post(f"{PEOPLE}/pay-items/{item.json()['id']}/end", headers=shop["hr"], json={"valid_to": "2025-12-31"})
    assert ended.status_code == 200 and ended.json()["valid_to"] == "2025-12-31"
    assert client.post(f"{PEOPLE}/pay-items/{item.json()['id']}/end", headers=shop["hr"],
                       json={"valid_to": "2026-06-30"}).status_code == 409                    # it already ends sooner
    assert client.post(f"{PEOPLE}/pay-items/{bonus.json()['id']}/end", headers=shop["hr"],
                       json={"valid_to": "2025-12-31"}).status_code == 422                    # one-off: nothing to end
    assert client.post(f"{PEOPLE}/pay-items/{uuid4()}/end", headers=shop["hr"], json={"valid_to": "2025-12-31"}
                       ).status_code == 404
    assert len(client.get(path, headers=shop["hr"]).json()) == 2
    assert client.post(path, headers=shop["manager"], json={"component_id": house, "amount": "1",
                                                           "valid_from": "2025-01-06"}).status_code == 403


# --------------------------------------------------------------------------- salary bank details
def test_bank_details_are_proposed_approved_masked_and_encrypted(client, shop) -> None:  # type: ignore[no-untyped-def]
    e = new_employee(client, shop, name="Bank Person")
    path = f"{PEOPLE}/employees/{e['id']}/bank-accounts"
    proposed = client.post(path, headers=shop["hr"], json={"method": "bank", "bank_name": "First Bank",
                                                          "account_no": "0123 4567 89"})
    assert proposed.status_code == 201, proposed.text
    b = proposed.json()
    assert b["account_no_masked"] == "******6789" and "0123456789" not in str(b) and b["approved_by"] is None
    raw = db(shop, "select account_no_ciphertext from people.employee_bank_account where id = :i", i=b["id"])[0][0]
    assert b"0123456789" not in bytes(raw)
    assert client.post(path, headers=shop["hr"], json={"method": "mobile_money", "account_no": "0712345678"}
                       ).status_code == 409
    assert client.post(f"{PEOPLE}/bank-accounts/{b['id']}/approve", headers=shop["hr"]).status_code == 403
    assert client.post(f"{PEOPLE}/bank-accounts/{b['id']}/approve", headers=shop["finance"]).status_code == 200
    second = client.post(path, headers=shop["hr"], json={"method": "mobile_money", "account_no": "0712 345 678"}).json()
    assert second["account_no_masked"] == "********5678"                                        # 254712345678
    assert client.post(f"{PEOPLE}/bank-accounts/{second['id']}/approve", headers=shop["finance2"]).status_code == 200
    rows = client.get(path, headers=shop["hr"]).json()
    assert [(r["method"], r["valid_to"] is None) for r in rows] == [("mobile_money", True), ("bank", False)]
    third = client.post(path, headers=shop["hr"], json={"method": "bank", "bank_name": "Other", "account_no": "999999"}
                        ).json()
    assert client.post(f"{PEOPLE}/bank-accounts/{third['id']}/reject", headers=shop["finance"]).json()["rejected"]
    for bad in ({"method": "cheque"}, {"method": "bank", "account_no": "12"}, {"method": "bank"},
                {"method": "mobile_money", "account_no": "abc"}, {"method": "bank", "bank_name": "B", "account_no": "!"}):
        body = {"account_no": "123456", **bad}
        assert client.post(path, headers=shop["hr"], json=body).status_code == 422, bad
    assert client.get(path, headers=shop["manager"]).status_code == 403


# --------------------------------------------------------------------------- the business's statutory rules
def rule(client, shop, code="PENSION", start="2025-01-01", definition=PENSION, who="hr", **kw):  # type: ignore[no-untyped-def]
    return client.post(f"{PEOPLE}/rules", headers=shop[who], json={
        "company_id": shop["company"], "code": code, "effective_from": start, "definition": definition,
        "source_reference": "Pension Act, section 5", **kw})


def test_a_business_defines_its_own_rules_and_someone_else_verifies_them(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert rule(client, shop).status_code == 403                                              # HR holds no rates permission
    finance_rule = rule(client, shop, who="finance")
    assert finance_rule.status_code == 201, finance_rule.text
    r = finance_rule.json()
    assert r["is_verified"] is False and r["verified_by"] is None and r["definition"]["name"] == "Pension"
    assert rule(client, shop, who="finance").status_code == 422                               # same code and start
    assert client.post(f"{PEOPLE}/rules/{finance_rule.json()['id']}/verify", headers=shop["finance"], json={}
                       ).status_code == 403                                                   # not your own entry
    done = client.post(f"{PEOPLE}/rules/{finance_rule.json()['id']}/verify", headers=shop["finance2"],
                       json={"note": "Checked against the notice"})
    assert done.status_code == 200 and done.json()["is_verified"] and done.json()["verified_by"] == "finance2"
    assert client.post(f"{PEOPLE}/rules/{finance_rule.json()['id']}/verify", headers=shop["finance2"], json={}
                       ).status_code == 409
    newer = rule(client, shop, start="2026-02-01", who="finance", definition={
        **PENSION, "employee": {"method": "rate", "rate": "0.07", "base_maximum": "108000"}})
    assert newer.status_code == 201
    rows = client.get(f"{PEOPLE}/rules", headers=shop["finance"], params={"company_id": shop["company"],
                                                                         "code": "pension"}).json()
    assert [x["effective_from"] for x in rows] == ["2026-02-01", "2025-01-01"]
    assert client.delete(f"{PEOPLE}/rules/{newer.json()['id']}", headers=shop["finance"]).status_code == 204
    assert client.get(f"{PEOPLE}/rules/{newer.json()['id']}", headers=shop["finance"]).status_code == 404
    assert client.get(f"{PEOPLE}/rules/{finance_rule.json()['id']}", headers=shop["hr"]).status_code == 200


def test_rule_validation_and_codes(client, shop) -> None:  # type: ignore[no-untyped-def]
    for code in ("pension2x", "BASIC", "PENSION_ER", "1X", "A B", "x" * 21):
        status = rule(client, shop, code=code, start="2027-01-01", who="finance").status_code
        assert status in (201, 422), code
        assert (status == 201) == (code == "pension2x"), code
    for definition in ({}, {"name": "x"}, {**PENSION, "employee": {"method": "magic"}}, {**HEALTH, "base": "net"},
                       {**TAX, "employee": {"method": "bands", "bands": [{"up_to": "5", "rate": "0.1"}]}}):
        assert rule(client, shop, code="BAD", start="2027-01-01", who="finance", definition=definition
                    ).status_code == 422
    assert rule(client, shop, code="OK", start="2027-01-01", who="finance", source_reference="x").status_code == 422
    assert rule(client, shop, code="OK2", start="2027-01-01", who="finance", effective_to="2026-01-01"
                ).status_code == 422
    house = client.get(f"{PEOPLE}/pay-components", headers=shop["hr"]).json()[0]["code"]
    assert rule(client, shop, code=house, start="2027-01-01", who="finance").status_code == 409   # names a component
    clash = client.post(f"{PEOPLE}/pay-components", headers=shop["hr"], json={
        "company_id": shop["company"], "code": "PENSION", "name": "x", "kind": "earning"})
    assert clash.status_code == 409                                                           # and the other way round
    assert client.get(f"{PEOPLE}/rules", headers=shop["cashier"], params={"company_id": shop["company"]}
                      ).status_code == 403
    assert client.get(f"{PEOPLE}/rules", headers=shop["finance"], params={"company_id": str(uuid4())}
                      ).status_code == 404
    assert date.fromisoformat("2027-01-01") and Dec("1")

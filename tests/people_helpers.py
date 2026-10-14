"""Shared setup for the people and payroll tests: a business with People (and Finance) on, and the people who work it."""

from tests.stock_helpers import make_stock_shop

PEOPLE = "/api/v1/people"

# A business's own statutory rules (the numbers are the test's; they say nothing about any country's law)
PENSION = {"name": "Pension", "kind": "contribution", "order": 10, "base": "gross", "reduces_taxable": True,
           "employee": {"method": "rate", "rate": "0.06", "base_maximum": "72000"},
           "employer": {"method": "rate", "rate": "0.06", "base_maximum": "72000"}}
HEALTH = {"name": "Health cover", "kind": "contribution", "order": 20, "base": "gross", "reduces_taxable": True,
          "employee": {"method": "rate", "rate": "0.0275", "minimum": "300"}}
TAX = {"name": "Income tax", "kind": "tax", "order": 30, "base": "taxable", "applies_to": "resident",
       "employee": {"method": "bands", "credit": "2400", "bands": [
           {"up_to": "24000", "rate": "0.10"}, {"up_to": "32333", "rate": "0.25"}, {"up_to": "500000", "rate": "0.30"},
           {"up_to": "800000", "rate": "0.325"}, {"up_to": None, "rate": "0.35"}]}}


def make_people_shop(client, registry, name: str, *, finance: bool = False, calling_code: str = "254"):  # type: ignore[no-untyped-def]
    """The stock shop (HQ and JUJA branches, users) with People on: `hr` (HR), `finance` (Finance Manager), `manager`
    (branch manager at HQ), `cashier`. The company's phone calling code is set so national numbers can be read."""
    shop = make_stock_shop(client, registry, name)
    if finance:
        registry.enable(shop["tenant_id"], "finance")
    registry.enable(shop["tenant_id"], "people")
    shop["company"] = str(shop["company_id"])
    shop["hr"] = shop["user"]("hr", "HR", None)
    shop["finance"] = shop["user"]("finance", "Finance Manager", None)
    shop["finance2"] = shop["user"]("finance2", "Finance Manager", None)
    changed = client.patch(f"/api/v1/companies/{shop['company']}/settings", headers=shop["owner"],
                           json={"phone_country_code": calling_code})
    assert changed.status_code == 200, changed.text
    return shop


def new_employee(client, shop, name="Amina Otieno", **kw):  # type: ignore[no-untyped-def]
    body = {"company_id": shop["company"], "full_name": name, "hire_date": "2025-01-06", **kw}
    r = client.post(f"{PEOPLE}/employees", headers=shop["hr"], json=body)
    assert r.status_code == 201, r.text
    return r.json()

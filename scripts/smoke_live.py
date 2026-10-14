"""A live smoke test of a running Ziira API: the same journey as tests/test_end_to_end.py, over real HTTP.

    python scripts/smoke_live.py http://localhost:8000 <workspace> <owner-email> <owner-password>

It creates its own catalogue, stock, customers and documents inside the workspace (use a scratch one), prints each
step and exits non-zero on the first disagreement. Needs pos, finance, crm, purchasing and people enabled.
"""

import random
import string
import sys
from datetime import date
from decimal import Decimal as D  # noqa: N817
from uuid import uuid4

import httpx

base, workspace, email, password = sys.argv[1:5]
today = date.today().isoformat()
month = {"date_from": today[:8] + "01", "date_to": today[:8] + "31"}
client = httpx.Client(base_url=base, timeout=30)
steps = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global steps
    steps += 1
    print(("PASS " if condition else "FAIL ") + label + ("" if condition else f"  -> {detail}"))
    if not condition:
        sys.exit(1)


def call(method: str, path: str, expect: tuple[int, ...] = (200, 201, 204), **kw):  # type: ignore[no-untyped-def]
    r = client.request(method, path, headers=headers, **kw)
    check(f"{method} {path} -> {r.status_code}", r.status_code in expect, r.text[:300])
    return r.json() if r.content else None


signin = client.post("/api/v1/auth/sign-in", json={"workspace": workspace, "login": email, "password": password,
                                                   "device_id": "smoke-script"})
check("sign in", signin.status_code == 200, signin.text[:300])
headers = {"Authorization": f"Bearer {signin.json()['access_token']}"}

me = call("GET", "/api/v1/companies")
company = me[0]["id"]
branch = me[0]["branches"][0]["id"]
suffix = "".join(random.choices(string.ascii_uppercase, k=5))          # letters: a unit code is letters only

# ---- catalogue, prices, stock
uom = call("POST", "/api/v1/products/uoms", json={"code": f"U{suffix}", "name": "Unit"})["id"]
tax = call("POST", "/api/v1/products/tax-codes", json={"code": f"V{suffix}", "name": "VAT 19%", "vat_rate": "19"})["id"]
widget = call("POST", "/api/v1/products/products", json={
    "company_id": company, "sku": f"W{suffix}", "name": "Widget", "base_uom_id": uom, "tax_code_id": tax})["id"]
plist = call("POST", "/api/v1/products/price-lists", json={"company_id": company, "name": "Retail", "is_default": True})
check("the price list is in the company's currency", plist["currency"] == "EUR", plist["currency"])
call("PUT", f"/api/v1/products/price-lists/{plist['id']}/prices", json={
    "product_id": widget, "price": "119.00", "valid_from": "2020-01-01"})
store = call("POST", "/api/v1/inventory/locations", json={
    "company_id": company, "branch_id": branch, "code": f"S{suffix}", "name": "Store"})["id"]
call("POST", "/api/v1/inventory/opening-stock", json={
    "company_id": company, "location_id": store,
    "lines": [{"product_id": widget, "quantity": "50", "unit_cost": "60"}]})

# ---- till and sales
device = call("POST", "/api/v1/pos/devices", json={
    "branch_id": branch, "code": f"D{suffix}", "name": "Counter", "location_id": store})["id"]
till = call("POST", "/api/v1/pos/tills", json={"device_id": device, "opening_float": "100"})["id"]
sale = call("POST", "/api/v1/pos/sales", json={
    "till_session_id": till, "lines": [{"product_id": widget, "quantity": "2"}],
    "payments": [{"method": "cash", "amount": "238.00"}]})
check("a sale of 2 widgets at 119.00 is 238.00 with 38.00 VAT", D(sale["total"]) == 238 and D(sale["tax_total"]) == 38)
local = str(uuid4())
body = {"till_session_id": till, "local_id": local, "lines": [{"product_id": widget, "quantity": "1"}],
        "payments": [{"method": "cash", "amount": "119.00"}]}
first, second = client.post("/api/v1/pos/sales", headers=headers, json=body), client.post(
    "/api/v1/pos/sales", headers=headers, json=body)
check("the same sale sent twice is one sale",
      first.status_code == 201 and second.status_code == 200 and first.json()["id"] == second.json()["id"])
report = call("GET", f"/api/v1/pos/tills/{till}/report")
check("the till expects the float and the cash sales", D(report["expected_cash"]) == 100 + 238 + 119, report)
closed = call("POST", f"/api/v1/pos/tills/{till}/close", json={"counted_cash": "457.00"})
check("the till closes with no variance", D(closed["variance"]) == 0)

# ---- a customer on credit, with a phone number in the company's own country
customer = call("POST", "/api/v1/crm/customers", json={
    "company_id": company, "name": "Müller GmbH", "phone": "0171 2345678", "tax_id": "DE 987654321"})
check("the phone number is read with the company's calling code", customer["phone"] == "491712345678",
      customer["phone"])

# ---- the books and the reports
tb = call("GET", "/api/v1/finance/reports/trial-balance", params={"company_id": company, "as_of": month["date_to"]})
check("the trial balance balances", tb["balanced"] is True and D(tb["total_debit"]) == D(tb["total_credit"]))
pnl = call("GET", "/api/v1/finance/reports/profit-and-loss", params={"company_id": company, **month})["consolidated"]
check("income is the 3 widgets' price before VAT (3 x 100)", D(pnl["total_income"]) == 300, pnl["total_income"])
check("cost of sales is 3 widgets at 60", D(pnl["total_cost_of_sales"]) == 180, pnl["total_cost_of_sales"])
vat = call("GET", "/api/v1/finance/reports/vat-summary", params={"company_id": company, **month})
check("VAT charged is 19% of 300", D(vat["output_vat"]) == 57, vat["output_vat"])
sheet = call("GET", "/api/v1/finance/reports/balance-sheet", params={"company_id": company, "as_of": month["date_to"]})
check("the balance sheet balances and carries the profit",
      sheet["balanced"] is True and D(sheet["accumulated_profit"]) == D(pnl["net_profit"]))
csv = client.get("/api/v1/finance/exports/journal", headers=headers, params={"company_id": company, **month})
check("the journal exports as CSV", csv.status_code == 200 and csv.text.count("\n") > 5)

# ---- payroll with the business's own rules
rule = call("POST", "/api/v1/people/rules", json={
    "company_id": company, "code": "SOCIAL", "effective_from": "2020-01-01", "source_reference": "Smoke test",
    "definition": {"name": "Social insurance", "kind": "contribution", "order": 10, "base": "gross",
                   "reduces_taxable": True, "employee": {"method": "rate", "rate": "0.10"},
                   "employer": {"method": "rate", "rate": "0.10"}}})
check("a rule starts unverified", rule["is_verified"] is False)
employee = call("POST", "/api/v1/people/employees", json={
    "company_id": company, "full_name": "Ada Lovelace", "hire_date": "2020-01-01", "branch_id": branch})
call("POST", f"/api/v1/people/employees/{employee['id']}/terms", json={"basic_pay": "3000", "valid_from": "2020-01-01"})

print(f"\nAll {steps} checks passed against {base} ({workspace}).")

"""A payroll run from calculation to payment, posted to the books, with every figure worked out by hand.

The business defines its own rules (see people_helpers): a pension (6% of pay up to 72000, the employer matches; reduces
taxable pay), a health cover (2.75%, at least 300; reduces taxable pay) and an income tax (bands, a credit of 2400, on
taxable pay) which is owed through its own account. Three employees for September 2026:

  Ann   HQ    basic 50000                                  bank account
  Ben   HQ    basic 20000 + house allowance 5000, a staff loan deduction of 1000      mobile money
  Cara  JUJA  basic 100000 + a company car benefit of 4000                               no payment details
"""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.finance_helpers import FIN, balance, entries
from tests.people_helpers import HEALTH, PENSION, PEOPLE, TAX, make_people_shop, new_employee
from tests.stock_helpers import system

RUNS = f"{PEOPLE}/payroll-runs"
SEPT = {"period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_people_shop(client, registry, "Payroll Co", finance=True)
    co = s["company"]
    books = client.post(f"{FIN}/companies/{co}/books", headers=s["owner"]).json()
    s["acc"] = {a["code"]: a["id"] for a in books}
    tax_payable = client.post(f"{FIN}/accounts", headers=s["owner"], json={
        "company_id": co, "code": "2400", "name": "Income tax payable", "type": "liability"})
    assert tax_payable.status_code == 201, tax_payable.text
    s["tax_account"] = tax_payable.json()["id"]
    s["notliab"] = s["acc"]["6100"]
    # the business's rules: entered by one person, verified by another (later, in the test)
    s["rules"] = {}
    for code, definition, extra in (("PENSION", PENSION, {}), ("HEALTH", HEALTH, {}),
                                    ("INCOME_TAX", TAX, {"payable_account_id": s["tax_account"]})):
        r = client.post(f"{PEOPLE}/rules", headers=s["finance"], json={
            "company_id": co, "code": code, "effective_from": "2025-01-01", "definition": definition,
            "source_reference": "The business's own notice", **extra})
        assert r.status_code == 201, r.text
        s["rules"][code] = r.json()["id"]
    house = client.post(f"{PEOPLE}/pay-components", headers=s["hr"], json={
        "company_id": co, "code": "HOUSE", "name": "House allowance", "kind": "earning"}).json()["id"]
    loan = client.post(f"{PEOPLE}/pay-components", headers=s["hr"], json={
        "company_id": co, "code": "LOAN", "name": "Staff loan", "kind": "deduction"}).json()["id"]
    car = client.post(f"{PEOPLE}/pay-components", headers=s["hr"], json={
        "company_id": co, "code": "CAR", "name": "Company car", "kind": "benefit"}).json()["id"]
    s["components"] = {"HOUSE": house, "LOAN": loan, "CAR": car}
    hq, juja = str(s["branch_id"]), str(s["juja"])
    s["ann"] = staff(client, s, "Ann Otieno", hq, "50000", bank=("bank", "01234567890", "First Bank"))
    s["ben"] = staff(client, s, "Ben Kamau", hq, "20000", bank=("mobile_money", "0712345678", None),
                     items=[("HOUSE", "5000"), ("LOAN", "1000")])
    s["cara"] = staff(client, s, "Cara Wanjiru", juja, "100000", items=[("CAR", "4000")])
    return s


def staff(client, shop, name, branch, basic, bank=None, items=(), hire="2025-01-06", start="2025-01-06"):  # type: ignore[no-untyped-def]
    e = new_employee(client, shop, name, branch_id=branch, hire_date=hire)
    terms = client.post(f"{PEOPLE}/employees/{e['id']}/terms", headers=shop["hr"], json={
        "basic_pay": basic, "valid_from": start}).json()
    assert client.post(f"{PEOPLE}/terms/{terms['id']}/approve", headers=shop["finance"]).status_code == 200
    for code, amount in items:
        r = client.post(f"{PEOPLE}/employees/{e['id']}/pay-items", headers=shop["hr"], json={
            "component_id": shop["components"][code], "amount": amount, "valid_from": start})
        assert r.status_code == 201, r.text
    if bank:
        method, number, name_ = bank
        b = client.post(f"{PEOPLE}/employees/{e['id']}/bank-accounts", headers=shop["hr"], json={
            "method": method, "account_no": number, "bank_name": name_}).json()
        assert client.post(f"{PEOPLE}/bank-accounts/{b['id']}/approve", headers=shop["finance"]).status_code == 200
    return e


def run(client, shop, who="finance", **kw):  # type: ignore[no-untyped-def]
    return client.post(RUNS, headers=shop[who], json={"company_id": shop["company"], **SEPT, **kw})


def act(client, shop, run_id, action, who="finance", **body):  # type: ignore[no-untyped-def]
    return client.post(f"{RUNS}/{run_id}/{action}", headers=shop[who], json=body or None)


def codes(run_json, severity=None):  # type: ignore[no-untyped-def]
    return sorted(e["code"] for e in run_json["exceptions"] if severity in (None, e["severity"]))


def slips(client, shop, run_id, who="finance"):  # type: ignore[no-untyped-def]
    rows = client.get(f"{RUNS}/{run_id}/payslips", headers=shop[who]).json()
    return {r["full_name"].split()[0]: r for r in rows}


# --------------------------------------------------------------------------- creating and calculating
def test_a_run_needs_a_sensible_period_and_does_not_overlap(client, shop) -> None:  # type: ignore[no-untyped-def]
    for bad in ({"period_end": "2026-10-31"}, {"period_end": "2026-08-31"}, {"pay_date": "2026-08-30"},
                {"period_start": "soon"}):
        assert run(client, shop, **bad).status_code == 422, bad
    first = run(client, shop)
    assert first.status_code == 201, first.text
    shop["sept"] = first.json()["id"]
    assert first.json()["status"] == "draft" and first.json()["totals"] == {}
    overlap = run(client, shop, period_start="2026-09-20", period_end="2026-10-10", pay_date="2026-10-10")
    assert overlap.status_code == 409 and "overlaps" in overlap.json()["message"]
    cancelled = run(client, shop, period_start="2026-07-01", period_end="2026-07-31", pay_date="2026-07-31").json()
    assert act(client, shop, cancelled["id"], "cancel").json()["status"] == "cancelled"
    assert run(client, shop, period_start="2026-07-01", period_end="2026-07-31",
               pay_date="2026-07-31").status_code == 201                                     # the period is free again
    assert run(client, shop, who="hr").status_code == 403 and run(client, shop, who="cashier").status_code == 403


def test_unverified_rules_stop_a_run_being_submitted(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = act(client, shop, shop["sept"], "calculate")
    assert r.status_code == 200, r.text
    assert codes(r.json(), "blocker") == ["unverified_rule"] * 3
    submit = act(client, shop, shop["sept"], "submit")
    assert submit.status_code == 422 and "has not been verified" in submit.json()["message"]
    for rule_id in shop["rules"].values():
        assert client.post(f"{PEOPLE}/rules/{rule_id}/verify", headers=shop["finance2"], json={}).status_code == 200


def test_the_figures_of_each_payslip(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = act(client, shop, shop["sept"], "calculate").json()
    assert r["status"] == "calculated" and codes(r, "blocker") == []
    assert codes(r) == ["bank_changed", "bank_changed", "no_payment_details"]               # Cara has no details yet
    t = r["totals"]
    assert t["employees"] == 3 and Dec(t["gross_cash"]) == 175000 and Dec(t["net_pay"]) == Dec("132834.30")
    assert Dec(t["total_deductions"]) == Dec("42165.70") and Dec(t["employer_cost"]) == 8820
    assert Dec(t["other_deductions"]) == 1000 and Dec(t["benefits"]) == 4000
    by_rule = t["by_rule"]
    assert Dec(by_rule["PENSION"]["employee"]) == 8820 and Dec(by_rule["PENSION"]["employer"]) == 8820
    assert Dec(by_rule["HEALTH"]["employee"]) == Dec("4812.50") and Dec(by_rule["HEALTH"]["employer"]) == 0
    assert Dec(by_rule["INCOME_TAX"]["employee"]) == Dec("27533.20")
    assert by_rule["INCOME_TAX"]["payable_account_id"] == shop["tax_account"]
    rows = slips(client, shop, shop["sept"])
    ann, ben, cara = rows["Ann"], rows["Ben"], rows["Cara"]
    # Ann: pension 3000, health 1375, taxable 45625, tax 2400 + 2083.25 + 13292*.3 (3987.60) - 2400 = 6070.85
    assert (Dec(ann["gross_pay"]), Dec(ann["taxable_pay"]), Dec(ann["total_deductions"]), Dec(ann["net_pay"])) == (
        Dec(50000), Dec("45625.00"), Dec("10445.85"), Dec("39554.15"))
    # Ben: 25000 cash, pension 1500, health 687.50, taxable 22812.50, tax 2281.25 is covered by the credit; loan 1000
    assert (Dec(ben["taxable_pay"]), Dec(ben["total_deductions"]), Dec(ben["net_pay"])) == (
        Dec("22812.50"), Dec("3187.50"), Dec("21812.50"))
    # Cara: pension capped at 4320, health 2750, taxable 100000 + 4000 car - 7070 = 96930, tax 23862.35 - 2400
    assert (Dec(cara["gross_pay"]), Dec(cara["taxable_pay"]), Dec(cara["net_pay"])) == (
        Dec(104000), Dec("96930.00"), Dec("71467.65"))
    assert ann["pay_method"] == "bank" and ben["pay_method"] == "mobile_money" and cara["pay_method"] is None
    detail = client.get(f"{PEOPLE}/payslips/{ben['id']}", headers=shop["finance"]).json()
    lines = {x["code"]: (x["kind"], Dec(x["amount"])) for x in detail["lines"]}
    assert lines == {"BASIC": ("earning", Dec(20000)), "HOUSE": ("earning", Dec(5000)),
                     "PENSION": ("deduction", Dec(1500)), "HEALTH": ("deduction", Dec("687.50")),
                     "INCOME_TAX": ("deduction", Dec("0.00")), "LOAN": ("deduction", Dec(1000)),
                     "PENSION_ER": ("employer_contribution", Dec(1500))}
    assert detail["detail"]["rules"]["INCOME_TAX"]["credit"] == "2281.25"
    assert detail["period_start"] == "2026-09-01" and detail["status"] == "calculated"
    # a payslip belongs to payroll staff (and, once approved, to its employee)
    assert client.get(f"{PEOPLE}/payslips/{ben['id']}", headers=shop["hr"]).status_code == 404
    assert client.get(f"{PEOPLE}/payslips/{ben['id']}", headers=shop["cashier"]).status_code == 404
    assert client.get(f"{RUNS}/{shop['sept']}/payslips", headers=shop["hr"]).status_code == 403


# --------------------------------------------------------------------------- approval and posting
def test_a_run_is_approved_by_someone_else_and_posted_to_the_books(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert act(client, shop, shop["sept"], "approve", who="owner").status_code == 409          # not submitted yet
    sent = act(client, shop, shop["sept"], "submit")
    assert sent.status_code == 200 and sent.json()["status"] == "pending_approval"
    assert act(client, shop, shop["sept"], "calculate").status_code == 409                     # waiting for approval
    assert act(client, shop, shop["sept"], "approve", who="finance").status_code == 403         # not the preparer
    assert act(client, shop, shop["sept"], "approve", who="finance2").status_code == 403        # no approval permission
    assert act(client, shop, shop["sept"], "reject", who="owner", note=" ").status_code == 422
    back = act(client, shop, shop["sept"], "reject", who="owner", note="Check Cara's details")
    assert back.json()["status"] == "calculated" and back.json()["reject_note"] == "Check Cara's details"
    assert act(client, shop, shop["sept"], "submit").status_code == 200
    before = {c: balance(shop, c) for c in ("6100", "6110", "2300", "2310", "2320", "2400")}
    done = act(client, shop, shop["sept"], "approve", who="owner")
    assert done.status_code == 200, done.text
    run_ = done.json()
    assert run_["status"] == "posted" and run_["approved_by"] and run_["journal_entry_id"]
    after = {c: balance(shop, c) - before[c] for c in before}
    assert after == {"6100": 175000, "6110": 8820, "2300": Dec("-132834.30"), "2310": Dec("-22452.50"),
                     "2320": -1000, "2400": Dec("-27533.20")}
    entry = next(e for e in entries(shop, source_type="payroll"))
    by_branch: dict[tuple[str, str], Dec] = {}
    for code, debit, credit, branch in entry[2]:
        key = (code, "HQ" if branch == shop["branch_id"] else "JUJA")
        by_branch[key] = by_branch.get(key, Dec(0)) + debit - credit
    assert by_branch[("6100", "HQ")] == 75000 and by_branch[("6100", "JUJA")] == 100000
    assert by_branch[("6110", "HQ")] == 4500 and by_branch[("6110", "JUJA")] == 4320
    assert by_branch[("2300", "JUJA")] == Dec("-71467.65") and by_branch[("2400", "JUJA")] == Dec("-21462.35")
    assert by_branch[("2310", "HQ")] == Dec("-11062.50") and by_branch[("2320", "HQ")] == -1000
    assert entry[3] == date(2026, 9, 30) and "Payroll 2026-09-01 to 2026-09-30" in (entry[4] or "")
    assert act(client, shop, shop["sept"], "approve", who="owner").status_code == 409
    assert act(client, shop, shop["sept"], "cancel").status_code == 409
    assert act(client, shop, shop["sept"], "calculate").status_code == 409
    approved = slips(client, shop, shop["sept"])
    assert {s["status"] for s in approved.values()} == {"approved"}
    with system(shop) as s:                                                                   # the database agrees
        assert s.execute(text("select approved_by <> prepared_by from people.payroll_run where id = :i"),
                         {"i": shop["sept"]}).scalar_one() is True
        assert s.execute(text("select count(*) from people.payslip_line where payslip_id in (select id from "
                              "people.payslip where run_id = :i) and rate_table_id is not null"),
                         {"i": shop["sept"]}).scalar_one() == 12
    # an approved month is final: attendance inside it cannot be changed
    attendance = client.post(f"{PEOPLE}/attendance", headers=shop["hr"], json={
        "employee_id": shop["ann"]["id"], "work_date": "2026-09-15", "hours": "8"})
    assert attendance.status_code == 409 and "approved" in attendance.json()["message"]


def test_an_employee_reads_their_own_payslip_once_the_run_is_approved(client, shop) -> None:  # type: ignore[no-untyped-def]
    users = {u["email"].split("@")[0]: u["id"] for u in client.get("/api/v1/users", headers=shop["owner"]).json()}
    linked = client.patch(f"{PEOPLE}/employees/{shop['ann']['id']}", headers=shop["hr"],
                          json={"user_id": users["cashier"]})
    assert linked.status_code == 200, linked.text
    mine = client.get(f"{PEOPLE}/me/payslips", headers=shop["cashier"]).json()
    assert [m["full_name"] for m in mine] == ["Ann Otieno"] and Dec(mine[0]["net_pay"]) == Dec("39554.15")
    own = client.get(f"{PEOPLE}/payslips/{mine[0]['id']}", headers=shop["cashier"])
    assert own.status_code == 200 and own.json()["lines"]
    other = slips(client, shop, shop["sept"])["Ben"]["id"]
    assert client.get(f"{PEOPLE}/payslips/{other}", headers=shop["cashier"]).status_code == 404
    assert client.get(f"{PEOPLE}/me/payslips", headers=shop["manager"]).json() == []           # no employee record


# --------------------------------------------------------------------------- paying
def test_the_payment_file_and_paying_the_run(client, shop) -> None:  # type: ignore[no-untyped-def]
    path = f"{RUNS}/{shop['sept']}"
    assert client.get(f"{path}/payment-file", headers=shop["hr"]).status_code == 403          # sensitive: payroll.pay only
    assert client.get(f"{path}/payment-file", headers=shop["cashier"]).status_code == 403
    got = client.get(f"{path}/payment-file", headers=shop["finance"])
    assert got.status_code == 200, got.text
    rows = {r["name"].split()[0]: r for r in got.json()}
    assert rows["Ann"]["account_no"] == "01234567890" and rows["Ann"]["bank_name"] == "First Bank"
    assert Dec(rows["Ann"]["amount"]) == Dec("39554.15") and rows["Ann"]["reference"] == "Salary 2026-09-01 to 2026-09-30"
    assert rows["Ben"]["method"] == "mobile_money" and rows["Ben"]["account_no"] == "254712345678"
    assert rows["Cara"]["method"] == "none" and rows["Cara"]["account_no"] == ""             # nowhere to send it
    csv = client.get(f"{path}/payment-file", headers=shop["finance"], params={"format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[0].startswith("employee_no,name")
    with system(shop) as s:
        audited = s.execute(text("select count(*) from kernel.audit_log where action = 'download_payment_file'")
                            ).scalar_one()
    assert audited == 2                                                                       # every download is recorded
    before = {c: balance(shop, c) for c in ("2300", "1020", "1030")}
    assert client.post(f"{path}/pay", headers=shop["hr"], json={}).status_code == 403
    assert client.post(f"{path}/pay", headers=shop["finance"], json={"paid_on": "2026-08-31"}).status_code == 422
    paid = client.post(f"{path}/pay", headers=shop["finance"], json={"paid_on": "2026-09-30"})
    assert paid.status_code == 200 and paid.json()["status"] == "paid" and paid.json()["paid_at"]
    moved = {c: balance(shop, c) - before[c] for c in before}
    assert moved == {"2300": Dec("132834.30"), "1020": Dec("-111021.80"), "1030": Dec("-21812.50")}
    assert {s["status"] for s in slips(client, shop, shop["sept"]).values()} == {"paid"}
    assert client.post(f"{path}/pay", headers=shop["finance"], json={}).status_code == 409
    assert balance(shop, "2300") == 0                                                         # nothing is owed to staff


# --------------------------------------------------------------------------- a second month: part months, leave, overtime
OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31", "pay_date": "2026-10-31"}


def lines_of(client, shop, slip_id):  # type: ignore[no-untyped-def]
    got = client.get(f"{PEOPLE}/payslips/{slip_id}", headers=shop["finance"]).json()
    return {x["code"]: Dec(x["amount"]) for x in got["lines"]}, got


def test_october_with_a_raise_a_new_joiner_a_leaver_unpaid_leave_and_overtime(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.people.domain.payroll import overtime_pay

    hq = str(shop["branch_id"])
    raise_ = client.post(f"{PEOPLE}/employees/{shop['ann']['id']}/terms", headers=shop["hr"], json={
        "basic_pay": "55000", "valid_from": "2026-10-15"}).json()
    assert client.post(f"{PEOPLE}/terms/{raise_['id']}/approve", headers=shop["finance"]).status_code == 200
    dan = staff(client, shop, "Dan Joiner", hq, "31000", hire="2026-10-16", start="2026-10-16")
    eli = staff(client, shop, "Eli Leaver", hq, "62000")
    left = client.post(f"{PEOPLE}/employees/{eli['id']}/terminate", headers=shop["hr"],
                       json={"termination_date": "2026-10-10"})
    assert left.status_code == 200
    fay = staff(client, shop, "Fay Worker", hq, "30000")
    gus = new_employee(client, shop, "Gus NoPay", branch_id=hq, hire_date="2026-10-01")       # no approved pay
    unpaid = client.post(f"{PEOPLE}/leave-types", headers=shop["hr"], json={
        "company_id": shop["company"], "name": "Unpaid leave", "is_paid": False}).json()
    leave = client.post(f"{PEOPLE}/leave-requests", headers=shop["hr"], json={
        "employee_id": fay["id"], "leave_type_id": unpaid["id"], "start_date": "2026-10-12", "end_date": "2026-10-14"})
    assert leave.status_code == 201 and Dec(leave.json()["days"]) == 3
    assert client.post(f"{PEOPLE}/leave-requests/{leave.json()['id']}/approve", headers=shop["hr"], json={}
                       ).status_code == 200
    for day, extra in (("2026-10-02", "4"), ("2026-10-05", "2")):
        r = client.post(f"{PEOPLE}/attendance", headers=shop["hr"], json={
            "employee_id": fay["id"], "work_date": day, "hours": "10", "overtime_hours": extra})
        assert r.status_code == 201, r.text
    made = client.post(RUNS, headers=shop["finance"], json={"company_id": shop["company"], **OCT})
    assert made.status_code == 201, made.text
    shop["oct"] = made.json()["id"]
    r = act(client, shop, shop["oct"], "calculate").json()
    assert codes(r, "blocker") == [] and r["totals"]["employees"] == 6                         # all but Gus (no approved pay)
    found = {(e["code"], e["employee_no"]) for e in r["exceptions"]}
    assert ("new_employee", dan["employee_no"]) in found and ("left", eli["employee_no"]) in found
    assert ("pay_changed", shop["ann"]["employee_no"]) in found and ("no_pay_terms", gus["employee_no"]) in found
    rows = slips(client, shop, shop["oct"])
    # Ann is paid at 55000, the rate in force at the end: pension 3300, health 1512.50, taxable 50187.50
    # tax 2400 + 2083.25 + 17854.50*.3 (5356.35) - 2400 = 7439.60; net 55000 - 3300 - 1512.50 - 7439.60
    assert Dec(rows["Ann"]["net_pay"]) == Dec("42747.90") and Dec(rows["Ann"]["taxable_pay"]) == Dec("50187.50")
    # Dan joined on the 16th: 16 of 31 days of 31000 = 16000; pension 960, health 440, no tax
    assert Dec(rows["Dan"]["gross_pay"]) == Dec("16000.00") and Dec(rows["Dan"]["net_pay"]) == Dec("14600.00")
    # Eli left on the 10th: 10 of 31 days of 62000 = 20000; pension 1200, health 550
    assert Dec(rows["Eli"]["gross_pay"]) == Dec("20000.00") and Dec(rows["Eli"]["net_pay"]) == Dec("18250.00")
    lines, fay_slip = lines_of(client, shop, rows["Fay"]["id"])
    assert lines["UNPAID_LEAVE"] == Dec("-3000.00")                                          # 30000 / 30 * 3
    assert lines["OVERTIME"] == overtime_pay(Dec(30000), Dec(6), Dec("1.5"), Dec("173.33"))
    assert Dec(fay_slip["detail"]["overtime_hours"]) == 6 and Dec(fay_slip["detail"]["unpaid_leave_days"]) == 3
    assert Dec(fay_slip["gross_pay"]) == Dec(27000) + lines["OVERTIME"]


def test_a_run_whose_inputs_changed_after_review_cannot_be_approved(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert act(client, shop, shop["oct"], "submit").status_code == 200
    users = client.get(f"{PEOPLE}/employees", headers=shop["hr"], params={"search": "Fay"}).json()[0]
    row = client.get(f"{PEOPLE}/attendance", headers=shop["hr"], params={"employee_id": users["id"]}).json()[0]
    changed = client.patch(f"{PEOPLE}/attendance/{row['id']}", headers=shop["hr"], json={"overtime_hours": "6"})
    assert changed.status_code == 200
    stale = act(client, shop, shop["oct"], "approve", who="owner")
    assert stale.status_code == 409 and "changed since this run was calculated" in stale.json()["message"]
    assert act(client, shop, shop["oct"], "reject", who="owner", note="Overtime changed").status_code == 200
    assert act(client, shop, shop["oct"], "calculate").status_code == 200
    assert act(client, shop, shop["oct"], "submit").status_code == 200
    before = balance(shop, "6100")
    done = act(client, shop, shop["oct"], "approve", who="owner")
    assert done.status_code == 200 and done.json()["status"] == "posted", done.text
    assert balance(shop, "6100") - before == Dec(done.json()["totals"]["gross_cash"])


def test_a_rule_changes_from_a_date_and_a_used_rule_cannot_be_deleted(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.delete(f"{PEOPLE}/rules/{shop['rules']['PENSION']}", headers=shop["finance"]).status_code == 409
    v2 = client.post(f"{PEOPLE}/rules", headers=shop["finance"], json={
        "company_id": shop["company"], "code": "PENSION", "effective_from": "2026-11-01",
        "definition": {**PENSION, "employee": {"method": "rate", "rate": "0.07", "base_maximum": "72000"}},
        "source_reference": "Amended notice"})
    assert v2.status_code == 201, v2.text
    nov = client.post(RUNS, headers=shop["finance"], json={
        "company_id": shop["company"], "period_start": "2026-11-01", "period_end": "2026-11-30",
        "pay_date": "2026-11-30"}).json()
    first = act(client, shop, nov["id"], "calculate").json()
    assert codes(first, "blocker") == ["unverified_rule"] and "from 2026-11-01" in first["exceptions"][0]["message"]
    assert client.post(f"{PEOPLE}/rules/{v2.json()['id']}/verify", headers=shop["finance2"], json={}).status_code == 200
    second = act(client, shop, nov["id"], "calculate").json()
    assert codes(second, "blocker") == []
    rows = slips(client, shop, nov["id"])
    assert "Eli" not in rows and "Dan" in rows                                                # Eli left in October
    ann_lines, _ = lines_of(client, shop, rows["Ann"]["id"])
    assert ann_lines["PENSION"] == Dec("3850.00")                                             # 7% of 55000 from 1 November
    october = lines_of(client, shop, slips(client, shop, shop["oct"])["Ann"]["id"])[0]
    assert october["PENSION"] == Dec("3300.00")                                               # October kept its own rate
    assert act(client, shop, nov["id"], "cancel").json()["status"] == "cancelled"
    assert client.delete(f"{PEOPLE}/rules/{v2.json()['id']}", headers=shop["finance"]).status_code == 409
    gone = client.post(f"{PEOPLE}/rules", headers=shop["finance"], json={
        "company_id": shop["company"], "code": "PENSION", "effective_from": "2030-01-01",
        "definition": PENSION, "source_reference": "Scratch"}).json()
    assert client.delete(f"{PEOPLE}/rules/{gone['id']}", headers=shop["finance"]).status_code == 204


def test_who_may_see_payroll(client, shop) -> None:  # type: ignore[no-untyped-def]
    for who in ("hr", "cashier", "manager", "storekeeper"):
        assert client.get(RUNS, headers=shop[who]).status_code == 403, who
        assert client.get(f"{RUNS}/{shop['sept']}", headers=shop[who]).status_code == 403, who
        assert client.get(f"{RUNS}/{shop['sept']}/payslips", headers=shop[who]).status_code == 403, who
    listed = client.get(RUNS, headers=shop["finance"], params={"company_id": shop["company"]}).json()
    assert [r["period_start"] for r in listed][:2] == ["2026-11-01", "2026-10-01"]
    assert client.get(RUNS, headers=shop["finance"], params={"status": "paid"}).json()[0]["period_start"] == "2026-09-01"
    assert client.get(f"{RUNS}/{uuid4()}", headers=shop["finance"]).status_code == 404
    assert client.get(f"{PEOPLE}/payslips/{uuid4()}", headers=shop["finance"]).status_code == 404
    assert client.post(f"{RUNS}/{uuid4()}/calculate", headers=shop["finance"]).status_code == 404


def test_the_books_still_balance_after_two_payrolls(client, shop) -> None:  # type: ignore[no-untyped-def]
    tb = client.get(f"{FIN}/reports/trial-balance", headers=shop["finance"],
                    params={"company_id": shop["company"], "as_of": "2026-12-31"})
    assert tb.status_code in (200, 403)
    tb = client.get(f"{FIN}/reports/trial-balance", headers=shop["owner"],
                    params={"company_id": shop["company"], "as_of": "2026-12-31"}).json()
    assert tb["balanced"] is True
    pnl = client.get(f"{FIN}/reports/profit-and-loss", headers=shop["owner"], params={
        "company_id": shop["company"], "date_from": "2026-09-01", "date_to": "2026-09-30", "by_branch": "true"}).json()
    by_branch = {b["branch_name"]: b["statement"] for b in pnl["branches"]}
    assert Dec(by_branch["Juja"]["total_expenses"]) == 104320 and Dec(by_branch["Head office"]["total_expenses"]) == 79500

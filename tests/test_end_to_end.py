"""One business, start to finish, through the HTTP API: buy, receive, pay the supplier, sell (cash, mobile money, card, on
credit), void, return, close the till and the day, move money, report, reconcile the bank, record an expense, run payroll,
and check that every module's figures agree with the books.

The business is not Kenyan: its currency is USD and its phone numbers are British (calling code 44). Every figure that
matters is also checked against an independent source (the stock ledger, the customer and supplier sub-ledgers, the trial
balance), so a posting that goes wrong in one module shows up as a disagreement with another.
"""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest
from sqlalchemy import text

import tests.conftest as conftest
from tests.finance_helpers import FIN, balance
from tests.payments_helpers import PAY, one
from tests.people_helpers import HEALTH, PENSION, PEOPLE, TAX
from tests.pos_helpers import POS, credit_customer, credit_sale, ensure_till, line, make_sales_shop, sell, stock
from tests.purchasing_helpers import PUR, approved_order, bill_for, receive, stock_of
from tests.stock_helpers import system

TODAY = date.today().isoformat()
MONTH = {"date_from": f"{TODAY[:8]}01", "date_to": f"{TODAY[:8]}31"}


@pytest.fixture(scope="module")
def biz(client, registry):  # type: ignore[no-untyped-def]
    saved = dict(conftest.LOCALE)
    conftest.LOCALE.update({"currency": "USD", "phone_country_code": "44"})
    try:
        s = make_sales_shop(client, registry, "Globex Trading", stock="100", cost="50")
    finally:
        conftest.LOCALE.update(saved)
    registry.enable(s["tenant_id"], "purchasing")
    registry.enable(s["tenant_id"], "people")
    co = str(s["company_id"])
    s["co"] = co
    s["clerk"] = s["user"]("clerk", "Accountant", None)
    s["hr"] = s["user"]("hr", "HR", None)
    s["fm2"] = s["user"]("fm2", "Finance Manager", None)
    s["buyer"] = s["manager"]
    sup = client.post(f"{PUR}/suppliers", headers=s["owner"], json={
        "company_id": co, "code": "ACME", "name": "Acme Wholesale", "tax_id": "GB 123 456 789", "payment_terms_days": 30})
    assert sup.status_code == 201, sup.text
    s["supplier"] = sup.json()["id"]
    s["state"] = {}
    return s


def books(biz, *codes):  # type: ignore[no-untyped-def]
    return {c: balance(biz, c) for c in codes}


def moved(before, after):  # type: ignore[no-untyped-def]
    return {c: after[c] - before[c] for c in after if after[c] != before[c]}


def report(client, biz, name, who="owner", **params):  # type: ignore[no-untyped-def]
    r = client.get(f"{FIN}/reports/{name}", headers=biz[who], params={"company_id": biz["co"], **params})
    assert r.status_code == 200, (name, r.text)
    return r.json()


# --------------------------------------------------------------------------- 1. a business anywhere
def test_the_business_is_set_up_for_its_own_country(client, biz) -> None:  # type: ignore[no-untyped-def]
    assert one(biz, "select base_currency from kernel.company") == "USD"
    assert one(biz, "select settings->>'phone_country_code' from kernel.company") == "44"
    lists = client.get("/api/v1/products/price-lists", headers=biz["owner"], params={"company_id": biz["co"]}).json()
    assert lists and all(p["currency"] == "USD" for p in lists)                        # copied from the company
    acme = credit_customer(client, biz, "Acme Retail", limit="5000", phone="07911 123456", tax_id="GB 987 654 321")
    assert acme["phone"] == "447911123456" and acme["tax_id"] == "GB 987 654 321"
    biz["state"]["customer"] = acme
    units = {r[0] for r in system_rows(biz, "select unit_name from kernel.tenant_unit where status = 'enabled'")}
    assert {"inventory", "products", "payments", "pos", "crm", "finance", "purchasing", "people"} <= units
    assert client.post(f"{FIN}/companies/{biz['co']}/books", headers=biz["owner"]).status_code == 200


def system_rows(biz, sql, **params):  # type: ignore[no-untyped-def]
    with system(biz) as s:
        return s.execute(text(sql), params).all()


# --------------------------------------------------------------------------- 2. buy, receive, bill, pay
def test_buying_stock_from_a_supplier_and_paying_for_it(client, biz) -> None:  # type: ignore[no-untyped-def]
    before, stock_before = books(biz, "1200", "2100", "2000", "1300", "1010", "1020"), stock_of(biz)
    order = approved_order(client, biz, qty="40", cost="60.00")
    assert order["status"] == "approved"
    got = receive(client, biz, order)
    assert got.status_code == 201, got.text
    receipt = got.json()
    assert stock_of(biz) == stock_before + 40
    assert moved(before, books(biz, "1200", "2100", "2000", "1300", "1010", "1020")) == {
        "1200": 2400, "2100": -2400}                                                        # stock in, owed not invoiced
    bill = bill_for(client, biz, receipt, invoice="E2E-1")
    assert bill.status_code == 201, bill.text
    posted = client.post(f"{PUR}/bills/{bill.json()['id']}/submit", headers=biz["clerk"]).json()
    assert posted["status"] == "posted" and Dec(posted["total"]) == Dec("2784.00")          # 2400 + 16% VAT
    assert moved(before, books(biz, "1200", "2100", "2000", "1300", "1010", "1020")) == {
        "1200": 2400, "1300": 384, "2000": -2784}                                          # not invoiced -> payable
    pay = f"{PUR}/bills/{posted['id']}/pay"
    assert client.post(pay, headers=biz["fm"], json={"amount": "1000.00", "method": "cash"}).status_code == 200
    paid = client.post(pay, headers=biz["fm"], json={"amount": "1784.00", "method": "bank",
                                                     "payment_account_id": biz["bank"], "external_ref": "WIRE-E2E-1"})
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    assert moved(before, books(biz, "1200", "2100", "2000", "1300", "1010", "1020")) == {
        "1200": 2400, "1300": 384, "1010": -1000, "1020": -1784}                           # the supplier is owed nothing
    ledger = client.post(f"{PUR}/suppliers/{biz['supplier']}/statement-reconciliation", headers=biz["fm"], json={
        "lines": [{"date": TODAY, "reference": "E2E-1", "kind": "invoice", "amount": "2784.00"},
                  {"date": TODAY, "reference": "WIRE-E2E-1", "kind": "payment", "amount": "1784.00"},
                  {"date": TODAY, "reference": "CASH", "kind": "payment", "amount": "1000.00"}]}).json()
    assert Dec(ledger["our_balance"]) == 0 and ledger["summary"]["missing_here"] <= 1      # the supplier's view equals ours
    biz["state"]["cost_after_purchase"] = balance(biz, "1200")


# --------------------------------------------------------------------------- 3. sell at the till
def test_selling_cash_mobile_money_and_card_then_voiding_one(client, biz) -> None:  # type: ignore[no-untyped-def]
    st = biz["state"]
    inventory_before = balance(biz, "1200")
    cement_before, paint_before = stock(biz, "cement"), stock(biz, "paint")
    till = ensure_till(client, biz, "cashier")
    st["till"] = till
    cash = sell(client, biz, who="cashier", lines=[line(biz, "cement", "2")],
                payments=[{"method": "cash", "amount": "232.00"}])
    assert cash.status_code == 201, cash.text
    st["cash_sale"] = cash.json()
    mm = sell(client, biz, who="cashier", lines=[line(biz, "paint", "1")],
              payments=[{"method": "mobile_money", "amount": "232.00", "external_ref": "MM-E2E-" + uuid4().hex[:6]}])
    assert mm.status_code == 201, mm.text
    card = sell(client, biz, who="cashier", lines=[line(biz, "cement", "1")],
                payments=[{"method": "card", "amount": "116.00", "external_ref": "SLIP-E2E"}])
    assert card.status_code == 201, card.text
    assert stock(biz, "cement") == cement_before - 3 and stock(biz, "paint") == paint_before - 1
    # the same till record sent twice (a flaky connection) is one sale
    local = str(uuid4())
    first = sell(client, biz, who="cashier", local_id=local, lines=[line(biz, "delivery", "1")],
                 payments=[{"method": "cash", "amount": "58.00"}])
    again = sell(client, biz, who="cashier", local_id=local, lines=[line(biz, "delivery", "1")],
                 payments=[{"method": "cash", "amount": "58.00"}])
    assert first.status_code == 201 and again.status_code == 200 and again.json()["id"] == first.json()["id"]
    # what left the books as cost of goods equals what left the stock ledger
    assert inventory_before - balance(biz, "1200") > 0
    stock_cost = one(biz, "select coalesce(sum(-value), 0) from inventory.stock_movement where source_type = 'sale' "
                          "and created_at > now() - interval '1 hour'")
    assert Dec(stock_cost) == inventory_before - balance(biz, "1200")
    # a manager voids the card sale: stock and money go back
    ensure_till(client, biz, "manager")
    void = client.post(f"{POS}/sales/{card.json()['id']}/void", headers=biz["manager"],
                       json={"reason_code_id": biz["reasons"]["void"]})
    assert void.status_code == 200 and void.json()["status"] == "voided"
    assert stock(biz, "cement") == cement_before - 2
    st["card_sale"] = card.json()


def test_a_return_and_a_credit_sale_with_the_customer_paying(client, biz) -> None:  # type: ignore[no-untyped-def]
    st = biz["state"]
    sale = st["cash_sale"]
    back = client.post(f"{POS}/sales/{sale['id']}/returns", headers=biz["manager"], json={
        "lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
        "reason_code_id": biz["reasons"]["sale_return"], "refund_method": "cash"})
    assert back.status_code == 201, back.text
    customer = st["customer"]
    credit = credit_sale(client, biz, customer, qty="3")                                    # 348 on account
    assert credit.status_code == 201, credit.text
    assert Dec(client.get(f"/api/v1/crm/customers/{customer['id']}", headers=biz["owner"]).json()["credit_limit"]) == 5000
    too_big = credit_sale(client, biz, customer, qty="60")                                  # 6960 is over the limit
    assert too_big.status_code != 201
    receipt = client.post(f"{POS}/receipts", headers=biz["fm"], json={
        "customer_id": customer["id"], "amount": "200.00", "method": "bank", "branch_id": str(biz["branch_id"]),
        "payment_account_id": biz["bank"], "external_ref": "CUSTPAY-1"})
    assert receipt.status_code == 201, receipt.text
    credit_back = client.post(f"{POS}/sales/{credit.json()['id']}/returns", headers=biz["manager"], json={
        "lines": [{"sale_line_id": credit.json()["lines"][0]["id"], "quantity": "1"}],
        "reason_code_id": biz["reasons"]["sale_return"], "refund_method": "credit_note"})
    assert credit_back.status_code == 201, credit_back.text
    # 348 owed - 116 credit note - 200 paid = 32 still owed, by the customer's statement and by the books
    statement = client.get(f"{POS}/customers/{customer['id']}/statement", headers=biz["fm"]).json()
    assert Dec(statement["closing_balance"]) == 32
    assert balance(biz, "1100") == 32
    ageing = client.get(f"{POS}/receivables/ageing", headers=biz["fm"]).json()
    assert Dec(ageing["total"]) == 32 and [c["customer_id"] for c in ageing["customers"]] == [customer["id"]]
    st["customer_owes"] = Dec(32)


def test_closing_the_till_banking_the_cash_and_moving_money_between_accounts(client, biz) -> None:  # type: ignore[no-untyped-def]
    st = biz["state"]
    x = client.get(f"{POS}/tills/{st['till']}/report", headers=biz["cashier"]).json()
    expected = Dec(x["expected_cash"])
    assert expected == 1000 + 232 + 58 - 0                                                  # float + cash sales (refund was
    # paid from the manager's till, not this one)
    z = client.post(f"{POS}/tills/{st['till']}/close", headers=biz["cashier"], json={"counted_cash": str(expected)})
    assert z.status_code == 200 and Dec(z.json()["variance"]) == 0 and z.json()["status"] == "closed"
    before = books(biz, "1010", "1020", "1030", "6400")
    dep = client.post(f"{PAY}/cash-deposits", headers=biz["owner"], json={
        "company_id": biz["co"], "branch_id": str(biz["branch_id"]), "bank_account_id": biz["bank"],
        "amount": "290.00", "business_date": TODAY, "reference": "SLIP-E2E-1"})
    assert dep.status_code == 201, dep.text
    settle = client.post(f"{PAY}/settlements", headers=biz["owner"], json={
        "from_account_id": biz["till"], "to_account_id": biz["bank"], "amount": "196.00", "fee": "4.00",
        "business_date": TODAY, "reference": "SETTLE-E2E-1"})
    assert settle.status_code == 201, settle.text
    assert moved(before, books(biz, "1010", "1020", "1030", "6400")) == {
        "1010": -290, "1020": 290 + 196, "1030": -200, "6400": 4}


# --------------------------------------------------------------------------- 4. the books, reports and the bank
def test_an_expense_with_vat_is_approved_and_posted(client, biz) -> None:  # type: ignore[no-untyped-def]
    acc = {a["code"]: a["id"] for a in client.get(f"{FIN}/accounts", headers=biz["owner"],
                                                  params={"company_id": biz["co"]}).json()}
    biz["acc"] = acc
    before = books(biz, "6200", "1300", "1010")
    made = client.post(f"{FIN}/expenses", headers=biz["clerk"], json={
        "company_id": biz["co"], "branch_id": str(biz["branch_id"]), "expense_date": TODAY,
        "description": "Electricity", "account_id": acc["6200"], "amount": "116.00", "tax_amount": "16.00",
        "paid_from": "cash", "payee": "Power Co", "receipt_ref": "R-77"})
    assert made.status_code == 201, made.text
    done = client.post(f"{FIN}/expenses/{made.json()['id']}/submit", headers=biz["clerk"])
    assert done.status_code == 200 and done.json()["status"] == "posted", done.text
    assert moved(before, books(biz, "6200", "1300", "1010")) == {"6200": 100, "1300": 16, "1010": -116}


def test_the_reports_agree_with_each_other_and_with_the_ledgers(client, biz) -> None:  # type: ignore[no-untyped-def]
    tb = client.get(f"{FIN}/reports/trial-balance", headers=biz["owner"],
                    params={"company_id": biz["co"], "as_of": MONTH["date_to"]}).json()
    assert tb["balanced"] is True and Dec(tb["total_debit"]) == Dec(tb["total_credit"]) > 0
    pnl = report(client, biz, "profit-and-loss", **MONTH)["consolidated"]
    # sales net of voids and returns: cash 200 + mobile money 200 + delivery 50 + credit 300 - returns 100 - credit note 100
    assert Dec(pnl["total_income"]) == 550
    gross = Dec(pnl["gross_profit"])
    assert gross == Dec(pnl["total_income"]) - Dec(pnl["total_cost_of_sales"]) and Dec(pnl["total_cost_of_sales"]) > 0
    assert {x["code"] for x in pnl["expenses"]} >= {"6200", "6400"}
    sheet = report(client, biz, "balance-sheet", as_of=MONTH["date_to"])
    assert sheet["balanced"] is True and Dec(sheet["accumulated_profit"]) == Dec(pnl["net_profit"])
    assert Dec(sheet["total_assets"]) == Dec(sheet["total_liabilities_and_equity"])
    vat = report(client, biz, "vat-summary", **MONTH)
    assert Dec(vat["output_vat"]) == Dec("88.00")                                           # 16% of the 550 sold
    assert Dec(vat["input_vat"]) == 384 + 16 and Dec(vat["net_payable"]) == Dec("88.00") - 400
    flow = report(client, biz, "cash-flow", **MONTH)
    assert flow["reconciles"] is True
    cash_like = sum(balance(biz, c) for c in ("1010", "1020", "1030", "1040"))
    assert Dec(flow["closing"]) == cash_like
    by_branch = report(client, biz, "profit-and-loss", by_branch=True, **MONTH)
    assert sum(Dec(b["statement"]["net_profit"]) for b in by_branch["branches"]) == Dec(
        by_branch["consolidated"]["net_profit"])


def test_the_bank_account_is_reconciled_to_a_statement(client, biz) -> None:  # type: ignore[no-untyped-def]
    on_books = balance(biz, "1020")                                                          # -1784 + 200 + 290 + 196
    assert on_books == -1784 + 200 + 290 + 196
    started = client.post(f"{FIN}/bank-reconciliations", headers=biz["clerk"], json={
        "company_id": biz["co"], "account_id": biz["acc"]["1020"], "statement_date": TODAY,
        "statement_balance": str(on_books)})
    assert started.status_code == 201, started.text
    rid = started.json()["id"]
    assert Dec(started.json()["difference"]) == on_books                                    # nothing cleared yet
    cleared = client.post(f"{FIN}/bank-reconciliations/{rid}/clear", headers=biz["clerk"], json={"until": TODAY}).json()
    assert Dec(cleared["difference"]) == 0 and cleared["uncleared"] == []
    assert client.post(f"{FIN}/bank-reconciliations/{rid}/complete", headers=biz["clerk"]).status_code == 200


def test_the_journal_exports_as_a_balanced_csv(client, biz) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{FIN}/exports/journal", headers=biz["owner"], params={"company_id": biz["co"], **MONTH})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = [line.split(",") for line in r.text.splitlines()[1:] if line]
    debit = sum(Dec(x[-2]) for x in rows if len(x) >= 9 and x[-2] not in ("",))
    credit = sum(Dec(x[-1]) for x in rows if len(x) >= 9 and x[-1] not in ("",))
    assert len(rows) > 30 and debit == credit


# --------------------------------------------------------------------------- 5. people and payroll
def test_payroll_for_the_month_posts_to_the_books_and_is_paid(client, biz) -> None:  # type: ignore[no-untyped-def]
    co = biz["co"]
    rules = {}
    for code, definition in (("PENSION", PENSION), ("HEALTH", HEALTH), ("INCOME_TAX", TAX)):
        r = client.post(f"{PEOPLE}/rules", headers=biz["fm"], json={
            "company_id": co, "code": code, "effective_from": "2020-01-01", "definition": definition,
            "source_reference": "The business's own notice"})
        assert r.status_code == 201, r.text
        rules[code] = r.json()["id"]
        assert client.post(f"{PEOPLE}/rules/{r.json()['id']}/verify", headers=biz["fm2"], json={}).status_code == 200
    staff = []
    for name, basic, phone in (("Ann Smith", "50000", "07700 900111"), ("Bob Jones", "20000", "07700 900222")):
        e = client.post(f"{PEOPLE}/employees", headers=biz["hr"], json={
            "company_id": co, "full_name": name, "hire_date": "2020-01-06", "branch_id": str(biz["branch_id"]),
            "phone": phone})
        assert e.status_code == 201, e.text
        assert e.json()["phone"].startswith("44")                                            # read with the UK code
        t = client.post(f"{PEOPLE}/employees/{e.json()['id']}/terms", headers=biz["hr"], json={
            "basic_pay": basic, "valid_from": "2020-01-06"}).json()
        assert client.post(f"{PEOPLE}/terms/{t['id']}/approve", headers=biz["fm"]).status_code == 200
        staff.append(e.json())
    before = books(biz, "6100", "6110", "2300", "2310")
    month = TODAY[:8]
    run = client.post(f"{PEOPLE}/payroll-runs", headers=biz["fm"], json={
        "company_id": co, "period_start": f"{month}01", "period_end": f"{month}28", "pay_date": TODAY}).json()
    calc = client.post(f"{PEOPLE}/payroll-runs/{run['id']}/calculate", headers=biz["fm"]).json()
    assert [e for e in calc["exceptions"] if e["severity"] == "blocker"] == []
    assert Dec(calc["totals"]["gross_cash"]) == 70000 and calc["totals"]["employees"] == 2
    assert client.post(f"{PEOPLE}/payroll-runs/{run['id']}/submit", headers=biz["fm"]).status_code == 200
    assert client.post(f"{PEOPLE}/payroll-runs/{run['id']}/approve", headers=biz["fm"]).status_code == 403
    approved = client.post(f"{PEOPLE}/payroll-runs/{run['id']}/approve", headers=biz["owner"])
    assert approved.status_code == 200 and approved.json()["status"] == "posted", approved.text
    after = books(biz, "6100", "6110", "2300", "2310")
    assert after["6100"] - before["6100"] == 70000 and after["6110"] - before["6110"] > 0
    assert before["2300"] - after["2300"] == Dec(calc["totals"]["net_pay"])
    paid = client.post(f"{PEOPLE}/payroll-runs/{run['id']}/pay", headers=biz["fm"], json={"paid_on": TODAY})
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    assert balance(biz, "2300") == 0                                                         # nothing owed to staff
    pnl = report(client, biz, "profit-and-loss", **MONTH)["consolidated"]
    assert {"6100", "6110"} <= {x["code"] for x in pnl["expenses"]}


# --------------------------------------------------------------------------- 6. every ledger agrees with the books
def test_the_sub_ledgers_and_the_stock_ledger_equal_the_control_accounts(client, biz) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    # what customers owe (sales documents) = accounts receivable; what suppliers are owed = accounts payable
    customers = system_rows(biz, "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice "
                                 "where status in ('issued', 'part_paid')")[0][0]
    assert Dec(customers) == balance(biz, "1100") == 32
    suppliers = system_rows(biz, "select coalesce(sum(total - amount_paid - credited), 0) from purchasing.supplier_bill "
                                 "where status in ('posted', 'part_paid')")[0][0]
    assert Dec(suppliers) == -balance(biz, "2000") == 0
    # the stock ledger is worth what the inventory accounts say
    stock_value = system_rows(biz, "select coalesce(sum(value), 0) from inventory.stock_movement")[0][0]
    assert Dec(stock_value) == balance(biz, "1200") + balance(biz, "1210")
    # every journal entry balances and none is half-posted
    unbalanced = system_rows(biz, "select e.id from finance.journal_entry e join finance.journal_line l on l.entry_id = "
                                  "e.id group by e.id having sum(l.debit) <> sum(l.credit)")
    assert unbalanced == []
    # the platform's own integrity checks (books, stock, customers) report nothing wrong
    assert cli.main(["verify", biz["code"]]) == 0
    assert cli.main(["stock-verify"]) == 0

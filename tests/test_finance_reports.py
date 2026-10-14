"""Financial statements and exports, end to end: they reconcile to the journal lines and respect who may see what."""

from decimal import Decimal as Dec  # noqa: N817
from uuid import uuid4

import pytest

from tests.finance_helpers import FIN, make_books_shop, publish_sale

OCT = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_books_shop(client, registry, "Reports Co")
    s["accountant"] = s["user"]("accountant", "Accountant", None)
    s["company"] = str(s["company_id"])
    accounts = client.post(f"{FIN}/companies/{s['company']}/books", headers=s["owner"]).json()
    s["acc"] = {a["code"]: a["id"] for a in accounts}
    # HQ sells 1000 + 160 VAT in cash, JUJA 500 + 80 VAT in cash, both in October
    publish_sale(s, net="1000", tax="160", business_date="2026-10-05")
    publish_sale({**s, "branch_id": s["juja"]}, net="500", tax="80", business_date="2026-10-06")
    manual(client, s, "2026-10-10", [("6000", "300", None), ("1020", None, "300")], "=HYPERLINK(\"http://x\")")     # rent
    manual(client, s, "2026-10-12", [("6200", "300", None), ("1300", "48", None), ("1020", None, "348")], "Power")
    manual(client, s, "2026-09-20", [("6000", "100", None), ("1020", None, "100")], "September rent")
    return s


def manual(client, shop, day, lines, description):  # type: ignore[no-untyped-def]
    body = [{"account_id": shop["acc"][code], **({"debit": d} if d else {"credit": c})} for code, d, c in lines]
    made = client.post(f"{FIN}/manual-journals", headers=shop["accountant"], json={
        "company_id": shop["company"], "entry_date": day, "description": description, "lines": body})
    assert made.status_code == 201, made.text
    done = client.post(f"{FIN}/manual-journals/{made.json()['id']}/submit", headers=shop["accountant"])
    assert done.status_code == 200 and done.json()["status"] == "posted", done.text


def report(client, shop, name, who="accountant", **params):  # type: ignore[no-untyped-def]
    return client.get(f"{FIN}/reports/{name}", headers=shop[who], params={"company_id": shop["company"], **params})


def amounts(lines):  # type: ignore[no-untyped-def]
    return {x["code"]: Dec(x["amount"]) for x in lines}


# --------------------------------------------------------------------------- profit and loss
def test_profit_and_loss_for_a_month(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = report(client, shop, "profit-and-loss", **OCT)
    assert r.status_code == 200, r.text
    pnl = r.json()["consolidated"]
    assert amounts(pnl["income"]) == {"4000": 1500} and Dec(pnl["total_income"]) == 1500
    assert amounts(pnl["expenses"]) == {"6000": 300, "6200": 300} and Dec(pnl["total_expenses"]) == 600
    assert Dec(pnl["gross_profit"]) == 1500 and Dec(pnl["net_profit"]) == 900 and pnl["cost_of_sales"] == []
    assert r.json()["branches"] == []
    september = report(client, shop, "profit-and-loss", date_from="2026-09-01", date_to="2026-09-30").json()
    assert Dec(september["consolidated"]["net_profit"]) == -100                    # only September's rent


def test_profit_and_loss_split_by_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = report(client, shop, "profit-and-loss", by_branch=True, **OCT).json()
    by_name = {b["branch_name"]: b["statement"] for b in r["branches"]}
    assert len(by_name) == 3 and "Not tied to a branch" in by_name
    incomes = sorted(Dec(b["total_income"]) for b in by_name.values())
    assert incomes == [0, 500, 1000]
    assert Dec(by_name["Not tied to a branch"]["total_expenses"]) == 600
    assert sum(Dec(b["net_profit"]) for b in by_name.values()) == Dec(r["consolidated"]["net_profit"])
    one = report(client, shop, "profit-and-loss", branch_id=str(shop["juja"]), **OCT).json()
    assert Dec(one["consolidated"]["total_income"]) == 500 and Dec(one["consolidated"]["net_profit"]) == 500


# --------------------------------------------------------------------------- balance sheet
def test_balance_sheet_balances_and_matches_the_books(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = report(client, shop, "balance-sheet", as_of="2026-10-31")
    assert r.status_code == 200, r.text
    sheet = r.json()
    assert amounts(sheet["assets"]) == {"1010": 1740, "1020": -748, "1300": 48}
    assert amounts(sheet["liabilities"]) == {"2200": 240}
    assert Dec(sheet["total_assets"]) == 1040 and Dec(sheet["accumulated_profit"]) == 800
    assert Dec(sheet["total_liabilities_and_equity"]) == 1040 and sheet["balanced"] is True
    earlier = report(client, shop, "balance-sheet", as_of="2026-09-30").json()           # reproducible for a past date
    assert amounts(earlier["assets"]) == {"1020": -100} and Dec(earlier["accumulated_profit"]) == -100
    assert earlier["balanced"] is True
    tb = client.get(f"{FIN}/reports/trial-balance", headers=shop["accountant"],
                    params={"company_id": shop["company"], "as_of": "2026-10-31"}).json()
    assert tb["balanced"] and Dec(tb["total_debit"]) == Dec(tb["total_credit"])


# --------------------------------------------------------------------------- cash flow and VAT
def test_cash_flow_explains_the_change(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = report(client, shop, "cash-flow", **OCT)
    assert r.status_code == 200, r.text
    flow = r.json()
    assert Dec(flow["opening"]) == -100 and Dec(flow["closing"]) == 992 and flow["reconciles"] is True
    assert {m["label"]: Dec(m["amount"]) for m in flow["movements"]} == {"Sales": 1740, "Manual journals": -648}
    assert Dec(flow["net_movement"]) == 1092


def test_vat_summary(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = report(client, shop, "vat-summary", **OCT)
    assert r.status_code == 200, r.text
    v = r.json()
    assert Dec(v["sales_net"]) == 1500 and Dec(v["output_vat"]) == 240 and Dec(v["input_vat"]) == 48
    assert Dec(v["net_payable"]) == 192
    assert {x["label"]: Dec(x["amount"]) for x in v["output_by_source"]} == {"Sales": 240}
    assert {x["label"]: Dec(x["amount"]) for x in v["input_by_source"]} == {"Manual journals": 48}
    assert Dec(report(client, shop, "vat-summary", **OCT, branch_id=str(shop["juja"])).json()["output_vat"]) == 80


# --------------------------------------------------------------------------- csv and exports
def test_reports_as_csv(client, shop) -> None:  # type: ignore[no-untyped-def]
    for name, params, first in (("profit-and-loss", OCT, "Section,Code,Account,Amount"),
                                ("balance-sheet", {"as_of": "2026-10-31"}, "Section,Code,Account,Amount"),
                                ("cash-flow", OCT, "Line,Amount"), ("vat-summary", OCT, "Line,Amount")):
        r = report(client, shop, name, format="csv", **params)
        assert r.status_code == 200, (name, r.text)
        assert r.headers["content-type"].startswith("text/csv") and ".csv" in r.headers["content-disposition"]
        assert r.text.splitlines()[0] == first, name
    assert "Net profit,900.00" in report(client, shop, "profit-and-loss", format="csv", **OCT).text.replace('"', "")


def test_journal_export_in_three_layouts_with_account_mapping(client, shop) -> None:  # type: ignore[no-untyped-def]
    path = f"{FIN}/exports/journal"
    params = {"company_id": shop["company"], **OCT}
    generic = client.get(path, headers=shop["accountant"], params=params)
    assert generic.status_code == 200 and generic.text.splitlines()[0].startswith("Entry,Date,Source")
    lines = generic.text.splitlines()[1:]
    debit = sum(Dec(row.split(",")[-2] or 0) for row in lines if row.count(",") >= 8 and '"' not in row)
    assert len(lines) >= 4 and debit > 0
    quick = client.get(path, headers=shop["accountant"], params={**params, "format": "quickbooks"}).text
    assert "*JournalNo" in quick and "6000 Rent" in quick
    sage = client.get(path, headers=shop["accountant"], params={**params, "format": "sage"}).text
    assert sage.splitlines()[0].startswith("Type,Account Reference") and "JD,,6000," in sage and "JC,,1020," in sage
    mapping = f"{FIN}/account-mappings/{shop['acc']['6000']}"
    put = client.put(mapping, headers=shop["accountant"], params={"company_id": shop["company"]},
                     json={"external_code": "7100", "external_name": "Office rent"})
    assert put.status_code == 200 and put.json()["external_code"] == "7100"
    quick = client.get(path, headers=shop["accountant"], params={**params, "format": "quickbooks"}).text
    sage = client.get(path, headers=shop["accountant"], params={**params, "format": "sage"}).text
    assert "Office rent" in quick and "6000 Rent" not in quick and "JD,,7100," in sage
    client.put(mapping, headers=shop["accountant"], params={"company_id": shop["company"]},
               json={"external_code": "7100", "external_name": "=HYPERLINK(1)"})
    assert "'=HYPERLINK(1)" in client.get(path, headers=shop["accountant"], params={**params, "format": "quickbooks"}).text
    listed = client.get(f"{FIN}/account-mappings", headers=shop["accountant"], params={"company_id": shop["company"]})
    assert [m["external_code"] for m in listed.json()] == ["7100"]
    assert client.delete(mapping, headers=shop["accountant"], params={"company_id": shop["company"]}).status_code == 204
    assert client.delete(mapping, headers=shop["accountant"], params={"company_id": shop["company"]}).status_code == 404
    assert "6000 Rent" in client.get(path, headers=shop["accountant"], params={**params, "format": "quickbooks"}).text


# --------------------------------------------------------------------------- rules and permissions
def test_validation(client, shop) -> None:  # type: ignore[no-untyped-def]
    backwards = {"date_from": "2026-10-31", "date_to": "2026-10-01"}
    for name in ("profit-and-loss", "cash-flow", "vat-summary"):
        assert report(client, shop, name, **backwards).status_code == 422, name
    assert client.get(f"{FIN}/exports/journal", headers=shop["accountant"],
                      params={"company_id": shop["company"], **backwards}).status_code == 422
    assert client.get(f"{FIN}/exports/journal", headers=shop["accountant"], params={
        "company_id": shop["company"], **OCT, "format": "xero"}).status_code == 422
    assert report(client, shop, "profit-and-loss", format="pdf", **OCT).status_code == 422
    assert report(client, shop, "balance-sheet", as_of="not a date").status_code == 422
    stranger = {"company_id": str(uuid4())}
    assert client.get(f"{FIN}/reports/vat-summary", headers=shop["accountant"], params={**stranger, **OCT}
                      ).status_code in (404, 422)
    mapping = f"{FIN}/account-mappings/{shop['acc']['6000']}"
    q = {"company_id": shop["company"]}
    assert client.put(mapping, headers=shop["accountant"], params=q, json={}).status_code == 422
    assert client.put(mapping, headers=shop["accountant"], params=q, json={"external_code": "x" * 41}).status_code == 422
    assert client.put(f"{FIN}/account-mappings/{uuid4()}", headers=shop["accountant"], params=q,
                      json={"external_code": "1"}).status_code == 404


def test_who_may_see_the_reports(client, shop) -> None:  # type: ignore[no-untyped-def]
    for name, params in (("profit-and-loss", OCT), ("balance-sheet", {"as_of": "2026-10-31"}),
                         ("cash-flow", OCT), ("vat-summary", OCT)):
        assert report(client, shop, name, who="cashier", **params).status_code == 403, name
        assert report(client, shop, name, who="storekeeper", **params).status_code == 403, name
    assert client.get(f"{FIN}/exports/journal", headers=shop["cashier"], params={
        "company_id": shop["company"], **OCT}).status_code == 403
    mapping = f"{FIN}/account-mappings/{shop['acc']['6000']}"
    assert client.put(mapping, headers=shop["manager"], params={"company_id": shop["company"]},
                      json={"external_code": "1"}).status_code == 403                  # may read reports, not change the chart
    # a branch manager sees only that branch's lines
    pnl = report(client, shop, "profit-and-loss", who="manager", **OCT).json()["consolidated"]
    assert Dec(pnl["total_income"]) == 1000 and pnl["expenses"] == []
    vat = report(client, shop, "vat-summary", who="manager", **OCT).json()
    assert Dec(vat["output_vat"]) == 160 and Dec(vat["input_vat"]) == 0

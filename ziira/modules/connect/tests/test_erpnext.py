"""ERPNext connector: requests, mapping to the canonical model, cursors, errors and secrecy, on a mock server."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.connect.connectors import erpnext
from ziira.modules.connect.connectors._http import RetryAfterError
from ziira.modules.connect.connectors.erpnext import ErpNextConnector
from ziira.modules.connect.public import ConnectorError, Invoice, Party, Sale
from ziira.modules.connect.tests.api_helpers import FakeSystem, drain, fixture, json_reply, records

D = Decimal
CONFIG = {"base_url": "https://shop.erpnext.example", "timezone": "Africa/Nairobi"}
SECRETS = {"api_key": "abc123key", "api_secret": "s3cr3tvalue"}
TOKEN = "token abc123key:s3cr3tvalue"


def doctype_of(request: httpx.Request) -> tuple[str, str | None]:
    parts = unquote(request.url.path).removeprefix("/api/resource/").split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else None


def serve(lists: dict[str, Any], details: dict[str, Any] | None = None) -> FakeSystem:
    """A fake ERPNext: `lists` maps a doctype to its list reply (a list of replies pages in order of request),
    `details` maps 'DocType/name' to a detail reply."""
    details = details or {}
    served: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["Authorization"] == TOKEN
        if request.url.path == "/api/method/frappe.auth.get_logged_user":
            return json_reply({"message": "ziira-readonly@shop.test"})
        doctype, name = doctype_of(request)
        if name is not None:
            key = f"{doctype}/{name}"
            return json_reply(details[key]) if key in details else json_reply({"exc_type": "DoesNotExistError"}, 404)
        reply = lists.get(doctype, {"data": []})
        if isinstance(reply, list):                      # pages in order
            index = served.get(doctype, 0)
            served[doctype] = index + 1
            reply = reply[min(index, len(reply) - 1)]
        return json_reply(reply)

    return FakeSystem(handler)


def connector(system: FakeSystem) -> ErpNextConnector:
    c = ErpNextConnector()
    system.attach(c)
    return c


def params(request: httpx.Request) -> dict[str, Any]:
    q = request.url.params
    return {"fields": json.loads(q["fields"]), "filters": json.loads(q.get("filters", "[]")),
            "order_by": q.get("order_by"), "start": int(q.get("limit_start", 0)),
            "length": int(q.get("limit_page_length", 0))}


# --------------------------------------------------------------------------- check
def test_check_ok_uses_two_light_reads() -> None:
    system = serve({"Sales Invoice": {"data": [{"name": "X"}]}})
    result = connector(system).check(CONFIG, SECRETS)
    assert result.ok and "ziira-readonly@shop.test" in result.message
    assert result.details == {"system": "ERPNext", "user": "ziira-readonly@shop.test"}
    assert system.paths() == ["/api/method/frappe.auth.get_logged_user", "/api/resource/Sales Invoice"]
    assert params(system.requests[1])["length"] == 1 and system.methods() == {"GET"}


@pytest.mark.parametrize("status,words", [(401, "did not accept"), (403, "not allowed to read"), (404, "web address"),
                                          (500, "not available"), (429, "slow down")])
def test_check_failures_are_friendly(status: int, words: str) -> None:
    system = FakeSystem(lambda r: json_reply({"message": "nope"}, status))
    result = connector(system).check(CONFIG, SECRETS)
    assert not result.ok and words in result.message
    assert "abc123key" not in result.message and "s3cr3tvalue" not in result.message


def test_check_guest_means_wrong_key() -> None:
    system = FakeSystem(lambda r: json_reply({"message": "Guest"}))
    assert "guest" in connector(system).check(CONFIG, SECRETS).message


def test_check_login_page_instead_of_data() -> None:
    system = FakeSystem(lambda r: httpx.Response(200, text="<html>Login</html>"))
    result = connector(system).check(CONFIG, SECRETS)
    assert not result.ok and "login page" in result.message


def test_check_cannot_reach_and_timeouts() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    assert "Could not reach" in connector(FakeSystem(refuse)).check(CONFIG, SECRETS).message
    assert "did not answer in time" in connector(FakeSystem(slow)).check(CONFIG, SECRETS).message


def test_check_bad_inputs() -> None:
    c = connector(FakeSystem(lambda r: json_reply({})))
    assert "missing" in c.check({"base_url": ""}, SECRETS).message
    assert "API key" in c.check(CONFIG, {"api_key": "", "api_secret": ""}).message
    assert "time zone" in c.check({**CONFIG, "timezone": "Mars/Base"}, SECRETS).message


def test_private_addresses_refused_in_production_rules() -> None:
    from ziira.modules.connect.connectors._http import normalise_base_url

    for bad in ("https://127.0.0.1", "https://10.1.2.3/x", "https://192.168.0.5", "https://localhost", "https://erp",
                "https://169.254.169.254", "http://erp.example.com", "https://[::1]"):
        with pytest.raises(ConnectorError):
            normalise_base_url(bad, system="ERPNext", allow_private=False)
    assert normalise_base_url("Erp.Example.com/", system="ERPNext", allow_private=False) == "https://Erp.Example.com"
    assert normalise_base_url("http://localhost:8080/", system="x", allow_private=True) == "http://localhost:8080"
    with pytest.raises(ConnectorError):
        normalise_base_url("https://user:pw@erp.example.com", system="x", allow_private=True)


# --------------------------------------------------------------------------- sales
def sales_system() -> FakeSystem:
    return serve(
        {"POS Invoice": fixture("erpnext_pos_invoice_list.json"),
         "Sales Invoice": fixture("erpnext_sales_invoice_list.json")},
        {"POS Invoice/POS-INV-2024-00001": fixture("erpnext_pos_invoice_detail_1.json"),
         "Sales Invoice/ACC-SINV-2024-00007": fixture("erpnext_sales_invoice_detail_7.json"),
         "Sales Invoice/ACC-SINV-2024-00009": fixture("erpnext_sales_invoice_detail_9.json")})


def test_sales_mapped_field_by_field() -> None:
    system = sales_system()
    batches = drain(connector(system).pull(CONFIG, SECRETS, "sales", None))
    sales = {s.ref: s for s in records(batches)}
    assert set(sales) == {"POS-INV-2024-00001", "POS-INV-2024-00002", "ACC-SINV-2024-00007", "ACC-SINV-2024-00009"}
    pos = sales["POS-INV-2024-00001"]
    assert isinstance(pos, Sale)
    # 14:22:10 in Nairobi (UTC+3) is 11:22:10 UTC
    assert pos.occurred_at == datetime(2024, 5, 3, 11, 22, 10, 123456, tzinfo=UTC)
    assert pos.entered_at == datetime(2024, 5, 3, 11, 22, 11, tzinfo=UTC)
    assert (pos.total, pos.tax_total, pos.status, pos.number) == (D("1160"), D("160"), "posted", "POS-INV-2024-00001")
    assert (pos.branch_ref, pos.cashier_ref, pos.customer_ref, pos.currency) == (
        "Main Store - Z", "cashier1@shop.test", "Walk-in", "KES")
    # line discount money = per-unit discount x quantity = 50 x 2
    assert pos.lines[0].product_ref == "HAM-001" and pos.lines[0].quantity == D("2")
    assert (pos.lines[0].unit_price, pos.lines[0].list_price, pos.lines[0].discount) == (D("450"), D("500"), D("100"))
    assert pos.lines[1].list_price is None and pos.lines[1].discount == D(0)
    assert pos.discount_total == D("100")
    # 340 change given back comes off the cash handed over: 1000 - 340; zero-amount card row dropped
    assert [(p.method, p.amount) for p in pos.payments] == [("cash", D("660")), ("mobile_money", D("500"))]
    voided = sales["POS-INV-2024-00002"]
    assert voided.status == "voided" and voided.voided_by_ref == "manager@shop.test" and voided.total == D("500")
    assert voided.lines == () and voided.branch_ref is None
    credit = sales["ACC-SINV-2024-00007"]
    assert credit.payments[0].method == "credit" and credit.payments[0].amount == D("2000")
    ret = sales["ACC-SINV-2024-00009"]
    assert ret.status == "refunded" and ret.total == D("-900") and ret.lines[0].quantity == D("-2")
    # the consolidated summary invoice is not a sale of its own
    assert "ACC-SINV-2024-00008" not in sales
    assert system.methods() == {"GET"}


def test_sales_request_shape_and_cursor() -> None:
    system = sales_system()
    batches = drain(connector(system).pull(CONFIG, SECRETS, "sales", None))
    first = params(system.requests[0])
    assert doctype_of(system.requests[0])[0] == "POS Invoice"
    assert first["order_by"] == "modified asc, name asc" and first["start"] == 0
    assert ["docstatus", "in", [1, 2]] in first["filters"] and "is_consolidated" in first["fields"]
    assert not any(f[0] == "modified" for f in first["filters"])               # first pull: no time filter
    final = batches[-1]
    assert final.complete
    cursor = json.loads(final.cursor or "")
    # newest POS modification 16:30:00 Nairobi = 13:30:00 UTC, minus the 5 minute overlap
    assert cursor["POS Invoice"] == "2024-05-03T13:25:00.000000+00:00"
    assert cursor["Sales Invoice"] == "2024-05-05T06:55:05.000000+00:00"       # 10:00:05 Nairobi = 07:00:05 UTC, - 5 min


def test_resume_uses_cursor_in_server_clock_and_keeps_other_sources() -> None:
    system = sales_system()
    since = json.dumps({"POS Invoice": "2024-05-03T13:25:00.000000+00:00"})
    drain(connector(system).pull(CONFIG, SECRETS, "sales", since))
    pos_filters = params(system.requests[0])["filters"]
    assert ["modified", ">", "2024-05-03 16:25:00.000000"] in pos_filters       # back in Nairobi time


def test_plain_timestamp_cursor_is_accepted_and_empty_pull_keeps_cursor() -> None:
    system = serve({})
    since = "2024-05-03T13:25:00.000000+00:00"
    batches = drain(connector(system).pull(CONFIG, SECRETS, "branches", since))
    assert len(batches) == 1 and batches[0].records == () and batches[0].complete
    assert batches[0].cursor == since


def test_paging_is_in_order_and_stops_on_short_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(erpnext, "PAGE", 2)
    pages = [{"data": [{"name": "W1", "warehouse_name": "Main", "modified": "2024-01-01 10:00:00.000000"},
                       {"name": "W2", "warehouse_name": None, "modified": "2024-01-01 10:00:00.000000"}]},
             {"data": [{"name": "W3", "warehouse_name": "Third", "modified": "2024-01-02 10:00:00.000000"}]}]
    system = serve({"Warehouse": pages})
    batches = drain(connector(system).pull(CONFIG, SECRETS, "branches", None))
    assert [b.complete for b in batches] == [False, True]
    assert [(r.ref, r.name) for r in records(batches)] == [("W1", "Main"), ("W2", "W2"), ("W3", "Third")]
    assert [params(r)["start"] for r in system.requests] == [0, 2]
    assert ["is_group", "=", 0] in params(system.requests[0])["filters"]
    # an interrupted read can resume from the first batch's cursor: nothing at or after it was skipped
    assert json.loads(batches[0].cursor or "")["Warehouse"] == "2024-01-01T06:55:00.000000+00:00"   # 10:00 - 3h - 5 min


def test_exact_page_boundary_asks_once_more_and_the_last_real_batch_is_complete(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(erpnext, "PAGE", 1)
    pages = [{"data": [{"name": "W1", "warehouse_name": "Main", "modified": "2024-01-01 10:00:00.000000"}]},
             {"data": []}]
    system = serve({"Warehouse": pages})
    batches = drain(connector(system).pull(CONFIG, SECRETS, "branches", None))
    assert [b.complete for b in batches] == [True] and len(batches[0].records) == 1
    assert len(system.requests) == 2


def test_limit_stops_early_and_says_more_remain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(erpnext, "PAGE", 1)
    page = {"data": [{"name": "W1", "warehouse_name": "Main", "modified": "2024-01-01 10:00:00.000000"}]}
    batches = drain(connector(serve({"Warehouse": page})).pull(CONFIG, SECRETS, "branches", None, limit=1))
    assert len(batches) == 1 and not batches[0].complete and batches[0].cursor


def test_missing_optional_field_is_dropped_and_remembered() -> None:
    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fields = json.loads(request.url.params["fields"])
        calls.append(fields)
        if "is_consolidated" in fields:
            return json_reply({"exc_type": "OperationalError", "exception": "Unknown column 'is_consolidated'"}, 500)
        return json_reply({"data": []})

    drain(connector(FakeSystem(handler)).pull(CONFIG, SECRETS, "sales", None))
    # POS Invoice: refused once, retried without; then the same for Sales Invoice (remembered per doctype)
    assert ["is_consolidated" in c for c in calls] == [True, False, True, False]


def test_server_error_without_a_field_name_is_retryable_not_swallowed() -> None:
    with pytest.raises(RetryAfterError):
        drain(connector(FakeSystem(lambda r: json_reply({"exc": "x"}, 502))).pull(CONFIG, SECRETS, "sales", None))


# --------------------------------------------------------------------------- the other entities
def test_parties_with_null_contact_details() -> None:
    cust = {"data": [{"name": "Acme", "customer_name": "Acme Builders", "creation": "2023-01-01 09:00:00.000000",
                      "modified": "2024-01-01 09:00:00.000000", "tax_id": "P0123", "mobile_no": "0712000000",
                      "email_id": None},
                     {"name": "Zed", "customer_name": None, "creation": None, "modified": "2024-01-02 09:00:00.000000",
                      "tax_id": None}]}
    sup = {"data": [{"name": "Bolt", "supplier_name": "Bolt Supplies", "creation": "2023-02-01 09:00:00.000000",
                     "modified": "2024-01-03 09:00:00.000000", "tax_id": None, "mobile_no": None, "email_id": "b@x.test"}]}
    batches = drain(connector(serve({"Customer": cust, "Supplier": sup})).pull(CONFIG, SECRETS, "parties", None))
    parties = {p.ref: p for p in records(batches)}
    assert isinstance(parties["Acme"], Party)
    assert (parties["Acme"].kind, parties["Acme"].name, parties["Acme"].phone, parties["Acme"].tax_id) == (
        "customer", "Acme Builders", "0712000000", "P0123")
    assert parties["Acme"].created_at == datetime(2023, 1, 1, 6, 0, tzinfo=UTC)
    assert (parties["Zed"].name, parties["Zed"].created_at, parties["Zed"].email) == ("Zed", None, None)
    assert (parties["Bolt"].kind, parties["Bolt"].email) == ("supplier", "b@x.test")
    assert set(json.loads(batches[-1].cursor or "")) == {"Customer", "Supplier"}


def test_products_cost_zero_means_unknown() -> None:
    items = {"data": [{"name": "HAM-001", "item_name": "Hammer", "item_group": "Tools", "valuation_rate": 300.5,
                       "standard_rate": 450, "modified": "2024-01-01 09:00:00.000000"},
                      {"name": "SRV", "item_name": None, "item_group": None, "valuation_rate": 0, "standard_rate": None,
                       "modified": "2024-01-01 09:00:00.000000"}]}
    products = records(drain(connector(serve({"Item": items})).pull(CONFIG, SECRETS, "products", None)))
    assert (products[0].sku, products[0].category, products[0].unit_cost, products[0].unit_price) == (
        "HAM-001", "Tools", D("300.5"), D("450"))
    assert (products[1].name, products[1].unit_cost, products[1].unit_price) == ("SRV", None, None)


def test_users_roles_from_detail_without_automatic_roles() -> None:
    users = {"data": [{"name": "cashier1@shop.test", "full_name": "Cash Ier", "creation": "2023-01-01 00:00:00",
                       "modified": "2024-01-01 00:00:00"}]}
    detail = {"data": {"roles": [{"role": "All"}, {"role": "Sales User"}, {"role": "Desk User"}, {"role": "POS Cashier"}]}}
    system = serve({"User": users}, {"User/cashier1@shop.test": detail})
    user = records(drain(connector(system).pull(CONFIG, SECRETS, "users", None)))[0]
    assert (user.name, user.role, user.email) == ("Cash Ier", "Sales User, POS Cashier", "cashier1@shop.test")
    assert ["name", "not in", ["Administrator", "Guest"]] in params(system.requests[0])["filters"]


def test_stock_movements_kinds_and_cancelled_entries() -> None:
    entries = {"data": [{"name": "MAT-STE-1", "purpose": "Material Transfer"}, {"name": "MAT-STE-2", "purpose": "Material Receipt"}]}
    system = serve({"Stock Ledger Entry": fixture("erpnext_stock_ledger.json"), "Stock Entry": entries})
    moves = {m.ref: m for m in records(drain(connector(system).pull(CONFIG, SECRETS, "stock_movements", None)))}
    sale = moves["MAT-SLE-1"]
    assert (sale.kind, sale.quantity, sale.unit_cost, sale.branch_ref, sale.user_ref) == (
        "sale", D("-2"), D("300"), "Main Store - Z", "cashier1@shop.test")
    assert sale.occurred_at == datetime(2024, 5, 3, 11, 22, 10, tzinfo=UTC)
    assert (moves["MAT-SLE-2"].kind, moves["MAT-SLE-2"].reason, moves["MAT-SLE-2"].unit_cost) == (
        "transfer_in", "Material Transfer", D("290"))
    assert moves["MAT-SLE-2"].occurred_at == datetime(2024, 5, 3, 5, 0, tzinfo=UTC)         # "8:00:00" padded
    assert (moves["MAT-SLE-3"].kind, moves["MAT-SLE-3"].reason) == ("adjustment", "Material Receipt")
    # a cancelled entry is kept with zero quantity so the earlier copy is neutralised when it is upserted
    assert (moves["MAT-SLE-4"].quantity, moves["MAT-SLE-4"].reason) == (D(0), "cancelled")
    assert moves["MAT-SLE-5"].kind == "count" and moves["MAT-SLE-5"].quantity == D("-3")  # no is_cancelled field at all
    lookup = system.requests[1]
    assert doctype_of(lookup)[0] == "Stock Entry"
    assert json.loads(lookup.url.params["filters"]) == [["name", "in", ["MAT-STE-1", "MAT-STE-2"]]]


def test_payments_direction_invoice_link_and_cancelled() -> None:
    system = serve({"Payment Entry": fixture("erpnext_payment_entry.json")},
                   {"Payment Entry/ACC-PAY-2024-00001": fixture("erpnext_payment_entry_detail_1.json")})
    pays = {p.ref: p for p in records(drain(connector(system).pull(CONFIG, SECRETS, "payments", None)))}
    inbound = pays["ACC-PAY-2024-00001"]
    assert (inbound.direction, inbound.amount, inbound.method, inbound.reference, inbound.invoice_ref) == (
        "in", D("3000"), "mobile_money", "SHK12ABC34", "ACC-SINV-2024-00007")
    assert (inbound.party_ref, inbound.party_name, inbound.account, inbound.currency) == (
        "Acme Builders", "Acme Builders Ltd", "Mpesa - Z", "KES")
    assert inbound.occurred_at == datetime(2024, 5, 4, 7, 0, tzinfo=UTC)          # created the same day: its time
    gone = pays["ACC-PAY-2024-00002"]
    assert (gone.direction, gone.amount, gone.method, gone.party_name, gone.account) == (
        "out", D(0), "other", None, "Bank - Z")
    assert gone.occurred_at == datetime(2024, 5, 1, 21, 0, tzinfo=UTC)            # posting date 2 May midnight Nairobi
    assert ["payment_type", "in", ["Receive", "Pay"]] in params(system.requests[0])["filters"]


def test_invoices_customer_and_supplier() -> None:
    purchase = {"data": [{"name": "ACC-PINV-1", "posting_date": "2024-05-02", "creation": "2024-05-02 08:00:00.000000",
                          "modified": "2024-05-02 08:00:00.000000", "owner": "buyer@shop.test", "docstatus": 1,
                          "supplier": "Bolt", "currency": "KES", "grand_total": 700.0, "rounded_total": 0.0,
                          "outstanding_amount": 0.0, "due_date": "2024-06-01", "bill_no": "INV-77", "is_return": 0},
                         {"name": "ACC-PINV-2", "posting_date": "2024-05-03", "creation": "2024-05-03 08:00:00.000000",
                          "modified": "2024-05-03 08:00:00.000000", "owner": "buyer@shop.test", "docstatus": 2,
                          "supplier": "Bolt", "currency": "KES", "grand_total": 100.0, "rounded_total": 0.0,
                          "outstanding_amount": 100.0, "due_date": None, "bill_no": None, "is_return": 0}]}
    system = serve({"Sales Invoice": fixture("erpnext_sales_invoice_list.json"), "Purchase Invoice": purchase})
    invoices = {i.ref: i for i in records(drain(connector(system).pull(CONFIG, SECRETS, "invoices", None)))}
    assert "ACC-SINV-2024-00008" not in invoices                                   # consolidated summary
    open_inv = invoices["ACC-SINV-2024-00007"]
    assert isinstance(open_inv, Invoice)
    assert (open_inv.kind, open_inv.total, open_inv.paid, open_inv.status, open_inv.issue_date, open_inv.due_date) == (
        "customer", D("5000"), D("3000"), "open", date(2024, 5, 4), date(2024, 6, 3))
    assert (open_inv.party_ref, open_inv.created_by_ref) == ("Acme Builders", "acct@shop.test")
    bill = invoices["ACC-PINV-1"]
    assert (bill.kind, bill.status, bill.paid, bill.number, bill.party_ref) == ("supplier", "paid", D("700"),
                                                                                "INV-77", "Bolt")
    cancelled = invoices["ACC-PINV-2"]
    assert cancelled.status == "cancelled" and cancelled.paid == D(0) and cancelled.number == "ACC-PINV-2"


def test_expenses_and_journals() -> None:
    claims = {"data": [{"name": "HR-EXP-1", "employee": "E1", "employee_name": "Jo", "posting_date": "2024-05-06",
                        "creation": "2024-05-06 08:00:00.000000", "modified": "2024-05-06 08:00:00.000000",
                        "owner": "jo@shop.test", "docstatus": 1, "total_claimed_amount": 1200.0,
                        "total_sanctioned_amount": 1000.0},
                       {"name": "HR-EXP-2", "employee": "E1", "employee_name": None, "posting_date": "2024-05-07",
                        "creation": "2024-05-07 08:00:00.000000", "modified": "2024-05-07 08:00:00.000000",
                        "owner": "jo@shop.test", "docstatus": 1, "total_claimed_amount": 300.0,
                        "total_sanctioned_amount": 0}]}
    expenses = records(drain(connector(serve({"Expense Claim": claims})).pull(CONFIG, SECRETS, "expenses", None)))
    assert [(e.amount, e.category, e.description) for e in expenses] == [(D("1000"), "Expense Claim", "Jo"),
                                                                       (D("300"), "Expense Claim", None)]
    system = serve({"Journal Entry": fixture("erpnext_journal_entry.json")},
                   {"Journal Entry/ACC-JV-2024-00001": fixture("erpnext_journal_entry_detail_1.json")})
    journals = {j.ref: j for j in records(drain(connector(system).pull(CONFIG, SECRETS, "journal_entries", None)))}
    manual = journals["ACC-JV-2024-00001"]
    assert [(ln.account, ln.debit, ln.credit, ln.party_ref) for ln in manual.lines] == [
        ("Rent - Z", D("15000"), D(0), None), ("Creditors - Z", D(0), D("15000"), "Landlord")]
    assert (manual.is_manual, manual.memo, manual.entry_date, manual.created_by_ref) == (
        True, "Rent accrual", date(2024, 5, 6), "acct@shop.test")
    auto = journals["ACC-JV-2024-00002"]
    assert (auto.is_manual, auto.lines, auto.memo) == (False, (), "cancelled")


def test_unknown_entity_and_unexpected_null_rows() -> None:
    with pytest.raises(ConnectorError):
        connector(serve({})).pull(CONFIG, SECRETS, "salaries", None)
    odd = {"data": [{"name": "W1", "warehouse_name": None, "modified": None}, "garbage", None]}
    batches = drain(connector(serve({"Warehouse": odd})).pull(CONFIG, SECRETS, "branches", None))
    assert [r.ref for r in records(batches)] == ["W1"]


# --------------------------------------------------------------------------- errors during a pull
def test_pull_errors_map_to_retryable_or_not() -> None:
    def run(status: int, headers: dict[str, str] | None = None) -> ConnectorError:
        system = FakeSystem(lambda r: json_reply({"message": "x"}, status, headers))
        with pytest.raises(ConnectorError) as info:
            drain(connector(system).pull(CONFIG, SECRETS, "sales", None))
        return info.value

    assert run(401).retryable is False and run(403).retryable is False
    throttled = run(429, {"Retry-After": "42"})
    assert isinstance(throttled, RetryAfterError) and throttled.retryable and throttled.retry_after == 42
    assert run(503).retryable is True


def test_malformed_json_and_timeout_during_pull() -> None:
    bad = FakeSystem(lambda r: httpx.Response(200, text="{not json"))
    with pytest.raises(ConnectorError, match="not data"):
        drain(connector(bad).pull(CONFIG, SECRETS, "branches", None))

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("t", request=request)

    with pytest.raises(RetryAfterError, match="did not answer"):
        drain(connector(FakeSystem(slow)).pull(CONFIG, SECRETS, "branches", None))


@settings(max_examples=40, deadline=None)
@given(key=st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=6, max_size=20),
       secret=st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=6, max_size=20),
       status=st.sampled_from([400, 401, 403, 404, 417, 429, 500, 502]))
def test_secrets_never_appear_in_messages_even_if_the_server_echoes_them(key: str, secret: str, status: int) -> None:
    """A server that echoes the Authorization header in its error body must not leak it through our messages."""
    system = FakeSystem(lambda r: json_reply({"message": f"bad credentials token {key}:{secret} rejected"}, status))
    c = connector(system)
    creds = {"api_key": key, "api_secret": secret}
    result = c.check(CONFIG, creds)
    assert key not in result.message and secret not in result.message
    with pytest.raises(ConnectorError) as info:
        drain(c.pull(CONFIG, creds, "sales", None))
    assert key not in str(info.value) and secret not in str(info.value)


def test_auth_header_is_the_only_place_the_secret_travels() -> None:
    system = serve({})
    drain(connector(system).pull(CONFIG, SECRETS, "branches", None))
    for request in system.requests:
        assert "s3cr3tvalue" not in str(request.url) and "abc123key" not in str(request.url)

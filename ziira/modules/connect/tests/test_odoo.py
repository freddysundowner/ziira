"""Odoo connector on a mock JSON-RPC server: read-only guard, mapping, version differences, skipping, errors."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.connect.connectors import odoo
from ziira.modules.connect.connectors._http import ReadOnlyViolation, RetryAfterError
from ziira.modules.connect.connectors.odoo import READ_METHODS, OdooConnector, OdooRpc
from ziira.modules.connect.public import ConnectorError
from ziira.modules.connect.tests.api_helpers import FakeSystem, drain, fixture, json_reply, records

D = Decimal
CONFIG = {"url": "https://shop.odoo.example", "database": "shopdb", "login": "ziira@shop.test"}
SECRETS = {"api_key": "k3y-0123456789abcdef"}
ALL_FIELDS = ["name", "phone", "mobile", "email", "vat", "create_date", "customer_rank", "supplier_rank", "login",
              "default_code", "categ_id", "standard_price", "lst_price", "date_order", "amount_total", "amount_tax",
              "state", "config_id", "user_id", "partner_id", "write_uid", "order_id", "product_id", "qty", "price_unit",
              "discount", "pos_order_id", "payment_method_id", "amount", "transaction_id", "date", "payment_type",
              "journal_id", "payment_method_line_id", "payment_reference", "ref", "currency_id",
              "reconciled_invoice_ids", "qty_done", "location_id", "location_dest_id", "reference", "create_uid",
              "move_type", "invoice_date", "invoice_date_due", "amount_residual", "payment_state", "total_amount",
              "employee_id", "description", "narration", "move_id", "account_id", "debit", "credit", "usage",
              "warehouse_id"]


class FakeOdoo:
    """A tiny Odoo: `pages` maps a model to the pages its main search_read returns in turn; `lookups` serves the
    side reads (lines, payments, locations, journals) whatever their domain."""

    def __init__(self, pages: dict[str, list[list[dict[str, Any]]]] | None = None,
                 lookups: dict[str, list[dict[str, Any]]] | None = None, fields: dict[str, list[str]] | None = None,
                 faults: dict[str, tuple[str, str]] | None = None) -> None:
        self.pages = pages or {}
        self.lookups = lookups or {}
        self.fields = fields or {}
        self.faults = faults or {}
        self.calls: list[tuple[str, str, list[Any], dict[str, Any]]] = []     # (model, method, args, kwargs)
        self.served: dict[str, int] = {}
        self.system = FakeSystem(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/jsonrpc"
        params = json.loads(request.content)["params"]
        service, method, args = params["service"], params["method"], params["args"]
        if service == "common" and method == "version":
            return self.result({"server_version": "17.0", "server_version_info": [17, 0, 0, "final", 0, ""]})
        if service == "common" and method == "authenticate":
            assert args[0] == "shopdb" and args[1] == "ziira@shop.test"
            return self.result(7 if args[2] == SECRETS["api_key"] else False)
        assert (service, method) == ("object", "execute_kw")
        db, uid, key, model, rpc_method, call_args, kwargs = args
        assert (db, uid, key) == ("shopdb", 7, SECRETS["api_key"])
        self.calls.append((model, rpc_method, call_args, kwargs))
        if model in self.faults:
            name, message = self.faults[model]
            return json_reply({"jsonrpc": "2.0", "id": 1, "error": {"code": 200, "message": "Odoo Server Error",
                                                                     "data": {"name": name, "message": message}}})
        if rpc_method == "fields_get":
            return self.result({f: {"type": "char"} for f in self.fields.get(model, ALL_FIELDS)})
        if rpc_method == "read":
            return self.result([{"id": call_args[0][0], "name": "Ziira Reader"}])
        assert rpc_method == "search_read"
        if "limit" in kwargs:                                        # the main, paged read
            pages = self.pages.get(model, [[]])
            index = self.served.get(model, 0)
            self.served[model] = index + 1
            return self.result(pages[min(index, len(pages) - 1)] if index < len(pages) else [])
        return self.result(self.lookups.get(model, []))

    @staticmethod
    def result(value: Any) -> httpx.Response:
        return json_reply({"jsonrpc": "2.0", "id": 1, "result": value})

    def connector(self) -> OdooConnector:
        c = OdooConnector()
        self.system.attach(c)
        return c

    def main_domains(self, model: str) -> list[list[Any]]:
        """The domains of the paged reads of `model` (JSON turns tuples into lists: turn the terms back)."""
        return [[tuple(t) if isinstance(t, list) else t for t in c[2][0]]
                for c in self.calls if c[0] == model and c[1] == "search_read" and "limit" in c[3]]


# --------------------------------------------------------------------------- the read-only guard
def test_write_methods_are_refused_before_anything_is_sent() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return json_reply({"result": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rpc = OdooRpc(client, "https://x.example", "db", "login", "key12345")
    rpc.uid = 7
    for method in ("write", "create", "unlink", "copy", "action_post", "button_confirm", "execute", "name_create",
                   "message_post", "_write", "SEARCH_READ", "search_read ", ""):
        with pytest.raises(ReadOnlyViolation) as info:
            rpc.execute("res.partner", method, [[1]], {})
        assert info.value.retryable is False
    with pytest.raises(ReadOnlyViolation):
        rpc._call("object", "execute", ["db", 7, "key12345", "res.partner", "read", [[1]]])     # the legacy call
    with pytest.raises(ReadOnlyViolation):
        rpc._call("object", "exec_workflow", ["db", 7, "key12345", "sale.order", "x", 1, "confirm"])
    with pytest.raises(ReadOnlyViolation):
        rpc._call("common", "login", ["db", "login", "key12345"])
    with pytest.raises(ReadOnlyViolation):
        rpc._call("db", "drop", ["admin", "db"])
    assert sent == []
    for method in READ_METHODS:                                           # and the allowed ones do go through
        rpc.execute("res.partner", method, [[1]], {})
    assert len(sent) == len(READ_METHODS)


@settings(max_examples=100, deadline=None)
@given(method=st.text(max_size=30).filter(lambda m: m not in READ_METHODS))
def test_no_method_outside_the_whitelist_is_ever_allowed(method: str) -> None:
    assert not OdooRpc.allowed("object", "execute_kw", ["db", 1, "k", "m", method, [], {}])
    assert not OdooRpc.allowed("object", method, ["db", 1, "k", "m", "read", [], {}]) or method == "execute_kw"


def test_every_call_of_a_full_sync_is_a_read() -> None:
    fake = FakeOdoo(pages={"stock.warehouse": [[{"id": 1, "name": "Main", "write_date": "2024-05-01 10:00:00"}]]})
    c = fake.connector()
    for entity in c.entities:
        drain(c.pull(CONFIG, SECRETS, entity, None))
    assert fake.calls and {m for _, m, _, _ in fake.calls} <= READ_METHODS
    assert fake.system.methods() == {"POST"}


# --------------------------------------------------------------------------- check
def test_check_ok() -> None:
    fake = FakeOdoo()
    result = fake.connector().check(CONFIG, SECRETS)
    assert result.ok and result.message == "Connected to Odoo 17.0 as Ziira Reader."
    assert result.details == {"system": "Odoo 17.0", "user": "Ziira Reader"}


def test_check_wrong_key_and_missing_parts() -> None:
    fake = FakeOdoo()
    bad = fake.connector().check(CONFIG, {"api_key": "wrong-key-value"})
    assert not bad.ok and "did not accept the login" in bad.message and "wrong-key-value" not in bad.message
    assert "needed" in fake.connector().check({**CONFIG, "database": ""}, SECRETS).message


def test_check_other_failures() -> None:
    def respond(status: int, body: Any = None) -> str:
        system = FakeSystem(lambda r: json_reply(body or {"message": "x"}, status))
        c = OdooConnector()
        system.attach(c)
        result = c.check(CONFIG, SECRETS)
        assert not result.ok
        return result.message

    assert "Custom plan" in respond(403)
    assert "Custom plan" in respond(404)
    assert "not available" in respond(502)
    assert "slow down" in respond(429)
    denied = {"jsonrpc": "2.0", "error": {"code": 100, "message": "Odoo Server Error",
                                          "data": {"name": "odoo.exceptions.AccessDenied", "message": "Access Denied"}}}
    assert "did not accept the login" in respond(200, denied)
    nodb = {"jsonrpc": "2.0", "error": {"code": 200, "message": "x", "data": {
        "name": "psycopg2.OperationalError", "message": 'database "shopdb" does not exist'}}}
    assert "database with that name" in respond(200, nodb)
    page = FakeSystem(lambda r: httpx.Response(200, text="<html>Odoo login</html>"))
    c = OdooConnector()
    page.attach(c)
    assert "login page" in c.check(CONFIG, SECRETS).message


def test_check_warns_about_untested_versions() -> None:
    fake = FakeOdoo()
    original = fake.handle

    def newer(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["params"]["method"] == "version":
            return fake.result({"server_version": "19.0"})
        return original(request)

    fake.system.handler = newer
    result = fake.connector().check(CONFIG, SECRETS)
    assert result.ok and "outside the versions we have tested" in result.message


# --------------------------------------------------------------------------- mapping
def test_pos_orders_mapped_field_by_field() -> None:
    fake = FakeOdoo(pages={"pos.order": [fixture("odoo_pos_orders.json")]},
                    lookups={"pos.order.line": fixture("odoo_pos_order_lines.json"),
                             "pos.payment": fixture("odoo_pos_payments.json")})
    sales = {s.ref: s for s in records(drain(fake.connector().pull(CONFIG, SECRETS, "sales", None)))}
    sale = sales["101"]
    assert sale.occurred_at == datetime(2024, 5, 3, 11, 22, 10, tzinfo=UTC)
    assert (sale.number, sale.total, sale.tax_total, sale.status) == ("Shop/0001", D("1160"), D("160"), "posted")
    assert (sale.branch_ref, sale.cashier_ref, sale.customer_ref) == ("pos.config:1", "7", None)
    # 10% off 2 x 500: charged 450 each, 100 off the line
    first = sale.lines[0]
    assert (first.product_ref, first.quantity, first.unit_price, first.list_price, first.discount) == (
        "11", D("2"), D("450"), D("500"), D("100"))
    assert sale.discount_total == D("100")
    assert [(p.method, p.amount, p.reference) for p in sale.payments] == [
        ("cash", D("660"), None), ("mobile_money", D("500"), "SHK12ABC34")]
    voided = sales["102"]
    assert (voided.status, voided.voided_by_ref, voided.customer_ref, voided.lines) == ("voided", "3", "55", ())
    refund = sales["103"]
    assert (refund.status, refund.total, refund.branch_ref, refund.cashier_ref) == ("refunded", D("-300"), None, None)
    assert refund.lines[0].quantity == D("-1") and refund.payments[0].amount == D("-300")
    domain = fake.main_domains("pos.order")[0]
    assert ("state", "in", ["paid", "done", "invoiced", "cancel"]) in domain         # drafts are never read
    kwargs = [c[3] for c in fake.calls if c[0] == "pos.order" and "limit" in c[3]][0]
    assert kwargs["order"] == "write_date asc, id asc" and kwargs["limit"] == odoo.PAGE


def test_invoices_refunds_bills_and_cancelled() -> None:
    fake = FakeOdoo(pages={"account.move": [fixture("odoo_account_moves.json")]})
    inv = {i.ref: i for i in records(drain(fake.connector().pull(CONFIG, SECRETS, "invoices", None)))}
    a = inv["501"]
    assert (a.kind, a.total, a.paid, a.status, a.issue_date, a.due_date, a.number, a.currency) == (
        "customer", D("5000"), D("3000"), "open", date(2024, 5, 4), date(2024, 6, 3), "INV/2024/0001", "KES")
    assert (a.party_ref, a.created_by_ref) == ("55", "3")
    credit = inv["502"]                                   # a credit note is negative; fully "paid" means used up
    assert (credit.total, credit.paid, credit.status, credit.due_date) == (D("-900"), D("-900"), "paid", None)
    bill = inv["503"]
    assert (bill.kind, bill.status, bill.paid, bill.created_by_ref, bill.currency) == (
        "supplier", "paid", D("700"), None, None)
    cancelled = inv["504"]
    assert (cancelled.status, cancelled.paid, cancelled.party_ref) == ("cancelled", D(0), None)
    assert cancelled.issue_date == date(2024, 5, 6)                     # no invoice date: the accounting date
    domain = fake.main_domains("account.move")[0]
    assert ("state", "in", ["posted", "cancel"]) in domain and ("move_type", "in", [
        "out_invoice", "out_refund", "in_invoice", "in_refund"]) in domain


def test_stock_lines_kinds_and_warehouses_v16_field_names() -> None:
    fake = FakeOdoo(pages={"stock.move.line": [fixture("odoo_move_lines.json")]},
                    lookups={"stock.location": fixture("odoo_locations.json")})
    moves = {m.ref: m for m in records(drain(fake.connector().pull(CONFIG, SECRETS, "stock_movements", None)))}
    sale = moves["901"]
    assert (sale.kind, sale.quantity, sale.branch_ref, sale.product_ref, sale.user_ref) == (
        "sale", D("-2"), "stock.warehouse:1", "11", "7")
    assert sale.occurred_at == datetime(2024, 5, 3, 11, 22, 12, tzinfo=UTC) and sale.reason == "Shop/0001"
    assert (moves["902"].kind, moves["902"].quantity, moves["902"].branch_ref) == ("purchase", D("10"),
                                                                                 "stock.warehouse:1")
    assert (moves["903:out"].kind, moves["903:out"].quantity, moves["903:out"].branch_ref) == (
        "transfer_out", D("-4"), "stock.warehouse:1")
    assert (moves["903:in"].kind, moves["903:in"].quantity, moves["903:in"].branch_ref) == (
        "transfer_in", D("4"), "stock.warehouse:2")
    assert "904" not in moves                                            # shelf to shelf inside one branch
    assert (moves["905"].kind, moves["905"].quantity, moves["905"].user_ref) == ("adjustment", D("3"), None)
    assert "906" not in moves                                            # no product: nothing to record
    assert ("state", "=", "done") in fake.main_domains("stock.move.line")[0]


def test_stock_quantity_field_of_odoo_17() -> None:
    lines = [{"id": 1, "date": "2024-05-03 11:00:00", "product_id": [11, "Hammer"], "quantity": 6.0,
              "location_id": [8, "x"], "location_dest_id": [5, "y"], "reference": "R", "create_uid": [1, "u"],
              "create_date": "2024-05-03 11:00:00", "write_date": "2024-05-03 11:00:01"}]
    fields = [f for f in ALL_FIELDS if f != "qty_done"] + ["quantity"]
    fake = FakeOdoo(pages={"stock.move.line": [lines]}, lookups={"stock.location": fixture("odoo_locations.json")},
                    fields={"stock.move.line": fields})
    moves = records(drain(fake.connector().pull(CONFIG, SECRETS, "stock_movements", None)))
    assert [(m.quantity, m.kind) for m in moves] == [(D("-6"), "sale")]
    requested = [c[3]["fields"] for c in fake.calls if c[0] == "stock.move.line" and "limit" in c[3]][0]
    assert "quantity" in requested and "qty_done" not in requested        # only fields the version has are asked for


def test_payments_methods_from_journals_and_cancelled() -> None:
    rows = [{"id": 70, "name": "BNK1/2024/0001", "date": "2024-05-04", "amount": 3000.0, "payment_type": "inbound",
             "partner_id": [55, "Acme Builders"], "journal_id": [3, "Bank"], "payment_method_line_id": [1, "Manual Payment"],
             "payment_reference": "SHK12ABC34", "ref": False, "state": "posted", "currency_id": [125, "KES"],
             "reconciled_invoice_ids": [501], "write_date": "2024-05-04 10:00:00"},
            {"id": 71, "name": "CSH1/2024/0001", "date": "2024-05-05", "amount": 80.0, "payment_type": "outbound",
             "partner_id": False, "journal_id": [4, "Cash"], "payment_method_line_id": False, "payment_reference": False,
             "ref": "petty", "state": "cancel", "currency_id": False, "reconciled_invoice_ids": [],
             "write_date": "2024-05-05 10:00:00"}]
    journals = [{"id": 3, "type": "bank", "name": "Bank"}, {"id": 4, "type": "cash", "name": "Cash"}]
    fake = FakeOdoo(pages={"account.payment": [rows]}, lookups={"account.journal": journals})
    pays = {p.ref: p for p in records(drain(fake.connector().pull(CONFIG, SECRETS, "payments", None)))}
    a = pays["70"]
    assert (a.direction, a.amount, a.method, a.reference, a.party_ref, a.party_name, a.account, a.invoice_ref,
            a.currency) == ("in", D("3000"), "bank", "SHK12ABC34", "55", "Acme Builders", "Bank", "501", "KES")
    b = pays["71"]
    assert (b.direction, b.amount, b.method, b.reference, b.party_name, b.invoice_ref) == (
        "out", D(0), "cash", "petty", None, None)                        # a cancelled payment counts for nothing
    assert ("state", "not in", ["draft"]) in fake.main_domains("account.payment")[0]


def test_parties_products_users_with_false_values() -> None:
    partners = [{"id": 55, "name": "Acme Builders", "phone": "020111", "mobile": "0712000000", "email": False,
                 "vat": "P0123", "create_date": "2023-01-01 09:00:00", "customer_rank": 3, "supplier_rank": 0,
                 "write_date": "2024-01-01 09:00:00"},
                {"id": 60, "name": "Bolt Supplies", "phone": False, "mobile": False, "email": "b@x.test", "vat": False,
                 "create_date": False, "customer_rank": 0, "supplier_rank": 5, "write_date": "2024-01-02 09:00:00"}]
    products = [{"id": 11, "name": "Hammer", "default_code": "HAM-001", "categ_id": [2, "All / Tools"],
                 "standard_price": 300.5, "lst_price": 450.0, "write_date": "2024-01-01 09:00:00"},
                {"id": 12, "name": "Service", "default_code": False, "categ_id": False, "standard_price": 0.0,
                 "lst_price": 0.0, "write_date": "2024-01-02 09:00:00"}]
    users = [{"id": 7, "name": "Cash Ier", "login": "cashier@shop.test", "email": False,
              "create_date": "2023-01-01 09:00:00", "write_date": "2024-01-01 09:00:00"},
             {"id": 8, "name": "", "login": "admin", "email": False, "create_date": False,
              "write_date": "2024-01-01 09:00:00"}]
    fake = FakeOdoo(pages={"res.partner": [partners], "product.product": [products], "res.users": [users]})
    c = fake.connector()
    p = {x.ref: x for x in records(drain(c.pull(CONFIG, SECRETS, "parties", None)))}
    assert (p["55"].kind, p["55"].phone, p["55"].email, p["55"].tax_id) == ("customer", "0712000000", None, "P0123")
    assert (p["60"].kind, p["60"].created_at, p["60"].email) == ("supplier", None, "b@x.test")
    pr = {x.ref: x for x in records(drain(c.pull(CONFIG, SECRETS, "products", None)))}
    assert (pr["11"].sku, pr["11"].category, pr["11"].unit_cost, pr["11"].unit_price) == (
        "HAM-001", "All / Tools", D("300.5"), D("450"))
    assert (pr["12"].sku, pr["12"].category, pr["12"].unit_cost, pr["12"].unit_price) == (None, None, None, None)
    us = {x.ref: x for x in records(drain(c.pull(CONFIG, SECRETS, "users", None)))}
    assert (us["7"].email, us["7"].created_at) == ("cashier@shop.test", datetime(2023, 1, 1, 9, tzinfo=UTC))
    assert (us["8"].name, us["8"].email) == ("admin", None)
    assert fake.main_domains("res.partner")[0] == ["|", ("customer_rank", ">", 0), ("supplier_rank", ">", 0)]


def test_journal_entries_with_lines_manual_flag_and_cancelled() -> None:
    moves = [{"id": 601, "name": "MISC/2024/0001", "date": "2024-05-06", "ref": "Rent accrual", "narration": False,
              "state": "posted", "journal_id": [1, "Miscellaneous"], "create_uid": [3, "Accountant"],
              "create_date": "2024-05-06 12:00:00", "write_date": "2024-05-06 12:00:00"},
             {"id": 602, "name": "CABA/2024/0001", "date": "2024-05-07", "ref": False, "narration": "auto",
              "state": "posted", "journal_id": [9, "Cash Basis"], "create_uid": False, "create_date": False,
              "write_date": "2024-05-07 12:00:00"},
             {"id": 603, "name": "MISC/2024/0002", "date": "2024-05-08", "ref": "oops", "narration": False,
              "state": "cancel", "journal_id": [1, "Miscellaneous"], "create_uid": [3, "Accountant"],
              "create_date": "2024-05-08 12:00:00", "write_date": "2024-05-08 12:00:00"}]
    lines = [{"id": 1, "move_id": [601, "x"], "account_id": [12, "600100 Rent"], "debit": 15000.0, "credit": 0.0,
              "partner_id": False},
             {"id": 2, "move_id": [601, "x"], "account_id": [13, "210000 Creditors"], "debit": 0.0, "credit": 15000.0,
              "partner_id": [70, "Landlord"]}]
    journals = [{"id": 1, "type": "general", "name": "Miscellaneous"}, {"id": 9, "type": "general2", "name": "CB"}]
    fake = FakeOdoo(pages={"account.move": [moves]}, lookups={"account.move.line": lines, "account.journal": journals})
    out = {j.ref: j for j in records(drain(fake.connector().pull(CONFIG, SECRETS, "journal_entries", None)))}
    a = out["601"]
    assert [(ln.account, ln.debit, ln.credit, ln.party_ref) for ln in a.lines] == [
        ("600100 Rent", D("15000"), D(0), None), ("210000 Creditors", D(0), D("15000"), "70")]
    assert (a.is_manual, a.memo, a.number, a.created_by_ref, a.entry_date) == (
        True, "Rent accrual", "MISC/2024/0001", "3", date(2024, 5, 6))
    assert (out["602"].is_manual, out["602"].memo, out["602"].entered_at) == (False, "auto", None)
    assert (out["603"].lines, out["603"].memo) == ((), "cancelled")
    assert ("move_type", "=", "entry") in fake.main_domains("account.move")[0]


def test_expenses_and_a_missing_model_is_skipped_with_a_note() -> None:
    rows = [{"id": 5, "name": "Fuel", "date": "2024-05-06", "total_amount": 2500.0, "employee_id": [4, "Jo"],
             "product_id": [9, "Fuel"], "state": "approved", "description": False, "create_date": "2024-05-06 08:00:00",
             "write_date": "2024-05-06 08:00:00"},
            {"id": 6, "name": "Lunch", "date": "2024-05-07", "total_amount": 900.0, "employee_id": False,
             "product_id": False, "state": "refused", "description": "no", "write_date": "2024-05-07 08:00:00"}]
    fake = FakeOdoo(pages={"hr.expense": [rows]})
    exp = records(drain(fake.connector().pull(CONFIG, SECRETS, "expenses", None)))
    assert [(e.amount, e.category, e.description, e.user_ref) for e in exp] == [
        (D("2500"), "Fuel", "Fuel", "4"), (D(0), None, "Lunch", None)]
    missing = FakeOdoo(faults={"hr.expense": ("builtins.KeyError", "'hr.expense'")})
    c = missing.connector()
    batches = drain(c.pull(CONFIG, SECRETS, "expenses", "keep-me"))
    assert len(batches) == 1 and batches[0].records == () and batches[0].complete and batches[0].cursor == "keep-me"
    assert c.notes and "hr.expense" in c.notes[0]


def test_one_missing_model_does_not_stop_the_others() -> None:
    fake = FakeOdoo(pages={"stock.warehouse": [[{"id": 1, "name": "Main", "write_date": "2024-05-01 10:00:00"}]]},
                    faults={"pos.config": ("odoo.exceptions.AccessError", "You are not allowed to access 'pos.config'")})
    c = fake.connector()
    batches = drain(c.pull(CONFIG, SECRETS, "branches", None))
    assert [(r.ref, r.name) for r in records(batches)] == [("stock.warehouse:1", "Main")]
    assert batches[-1].complete and any("pos.config" in n for n in c.notes)


def test_required_model_without_permission_is_a_clear_non_retryable_error() -> None:
    fake = FakeOdoo(faults={"account.move": ("odoo.exceptions.AccessError", "no access")})
    with pytest.raises(ConnectorError) as info:
        drain(fake.connector().pull(CONFIG, SECRETS, "invoices", None))
    assert info.value.retryable is False and "not allowed to read account.move" in str(info.value)


# --------------------------------------------------------------------------- cursors and paging
def test_keyset_paging_and_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odoo, "PAGE", 2)
    pages = [[{"id": 1, "name": "A", "write_date": "2024-05-01 10:00:00"},
              {"id": 2, "name": "B", "write_date": "2024-05-01 10:00:00"}],
             [{"id": 3, "name": "C", "write_date": "2024-05-01 11:00:00"}]]
    fake = FakeOdoo(pages={"stock.warehouse": pages})
    batches = drain(fake.connector().pull(CONFIG, SECRETS, "branches", None))
    assert [b.complete for b in batches] == [False, True]
    assert [r.name for r in records(batches)] == ["A", "B", "C"]
    d0, d1 = fake.main_domains("stock.warehouse")
    assert d0 == []                                                       # first pull, nothing to resume from
    assert d1 == ["|", ("write_date", ">", "2024-05-01 10:00:00"), "&", ("write_date", "=", "2024-05-01 10:00:00"),
                  ("id", ">", 2)]                                          # two rows share a time: id breaks the tie
    assert json.loads(batches[0].cursor or "")["stock.warehouse"] == "2024-05-01T09:55:00.000000+00:00"
    assert json.loads(batches[-1].cursor or "")["stock.warehouse"] == "2024-05-01T10:55:00.000000+00:00"
    resumed = FakeOdoo(pages={"stock.warehouse": [[]]})
    drain(resumed.connector().pull(CONFIG, SECRETS, "branches", batches[-1].cursor))
    assert resumed.main_domains("stock.warehouse")[0] == [("write_date", ">", "2024-05-01 10:55:00")]


def test_limit_marks_the_read_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odoo, "PAGE", 1)
    fake = FakeOdoo(pages={"stock.warehouse": [[{"id": 1, "name": "A", "write_date": "2024-05-01 10:00:00"}]]})
    batches = drain(fake.connector().pull(CONFIG, SECRETS, "branches", None, limit=1))
    assert len(batches) == 1 and batches[0].complete is False


# --------------------------------------------------------------------------- errors and secrecy
def test_pull_errors() -> None:
    def run(status: int, headers: dict[str, str] | None = None) -> ConnectorError:
        system = FakeSystem(lambda r: json_reply({"x": 1}, status, headers))
        c = OdooConnector()
        system.attach(c)
        with pytest.raises(ConnectorError) as info:
            drain(c.pull(CONFIG, SECRETS, "branches", None))
        return info.value

    assert run(401).retryable is False
    throttled = run(429, {"Retry-After": "30"})
    assert isinstance(throttled, RetryAfterError) and throttled.retry_after == 30
    assert run(500).retryable is True
    assert run(403).retryable is False and "Custom plan" in str(run(403))


def test_wrong_key_in_pull_is_not_retryable() -> None:
    fake = FakeOdoo()
    with pytest.raises(ConnectorError) as info:
        drain(fake.connector().pull(CONFIG, {"api_key": "wrong-key-value"}, "branches", None))
    assert info.value.retryable is False


def test_unknown_entity_malformed_reply_and_timeout() -> None:
    with pytest.raises(ConnectorError):
        FakeOdoo().connector().pull(CONFIG, SECRETS, "salaries", None)
    bad = FakeSystem(lambda r: httpx.Response(200, text="not json"))
    c = OdooConnector()
    bad.attach(c)
    with pytest.raises(ConnectorError, match="not data"):
        drain(c.pull(CONFIG, SECRETS, "branches", None))

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("t", request=request)

    t = OdooConnector()
    FakeSystem(slow).attach(t)
    with pytest.raises(RetryAfterError):
        drain(t.pull(CONFIG, SECRETS, "branches", None))


@settings(max_examples=30, deadline=None)
@given(key=st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=30))
def test_api_key_never_leaks_through_errors(key: str) -> None:
    """Odoo may echo the key in a fault message; it must not reach the owner."""
    echo = {"jsonrpc": "2.0", "error": {"code": 200, "message": "x", "data": {
        "name": "odoo.exceptions.UserError", "message": f"bad call with key {key} in it"}}}
    system = FakeSystem(lambda r: json_reply(echo))
    c = OdooConnector()
    system.attach(c)
    assert key not in c.check(CONFIG, {"api_key": key}).message
    with pytest.raises(ConnectorError) as info:
        drain(c.pull(CONFIG, {"api_key": key}, "branches", None))
    assert key not in str(info.value)

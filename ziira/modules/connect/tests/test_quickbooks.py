"""QuickBooks Online connector: OAuth, refresh-token rotation, query paging, mapping and errors on a mock server."""

import base64
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.connect.connectors import _http as h
from ziira.modules.connect.connectors import quickbooks
from ziira.modules.connect.connectors.quickbooks import QuickBooksConnector
from ziira.modules.connect.public import ConnectorError
from ziira.modules.connect.tests.api_helpers import FakeSystem, drain, fixture, json_reply, records

D = Decimal
CONFIG: dict[str, Any] = {"environment": "production", "realm_id": "9130350000000001"}
SECRETS = {"client_id": "ABclientid123", "client_secret": "cl13nt-s3cret-value", "refresh_token": "RT-original-0001"}
TOKEN = {"access_token": "AT-eyJlbmMiOiJBMTI4", "refresh_token": "RT-original-0001", "expires_in": 3600,
         "x_refresh_token_expires_in": 8726400, "token_type": "bearer"}


def qr(entity: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"QueryResponse": {entity: rows, "startPosition": 1, "maxResults": len(rows)} if rows else {},
            "time": "2024-05-06T07:00:00.123-07:00"}


class FakeIntuit:
    """Mock Intuit: `entities` maps a QuickBooks entity to a reply, or a list of replies served page by page."""

    def __init__(self, entities: dict[str, Any] | None = None, token_replies: list[Any] | None = None,
                 api_host: str = "quickbooks.api.intuit.com") -> None:
        self.entities = entities or {}
        self.token_replies = token_replies or [TOKEN]
        self.api_host = api_host
        self.token_calls = 0
        self.served: dict[str, int] = {}
        self.statements: list[str] = []
        self.system = FakeSystem(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth.platform.intuit.com":
            assert request.method == "POST" and request.url.path == "/oauth2/v1/tokens/bearer"
            assert request.headers["Authorization"].startswith("Basic ")
            reply = self.token_replies[min(self.token_calls, len(self.token_replies) - 1)]
            self.token_calls += 1
            return reply if isinstance(reply, httpx.Response) else json_reply(reply)
        assert request.method == "GET" and request.url.host == self.api_host
        assert request.headers["Authorization"].startswith("Bearer AT-") and request.headers["Accept"] == "application/json"
        assert request.url.params["minorversion"] == quickbooks.MINOR_VERSION
        if "/companyinfo/" in request.url.path:
            return json_reply({"CompanyInfo": {"CompanyName": "Shop Inc", "Id": "1"}})
        assert request.url.path == "/v3/company/9130350000000001/query"
        statement = request.url.params["query"]
        self.statements.append(statement)
        entity = re.search(r"from (\w+)", statement).group(1)            # type: ignore[union-attr]
        reply = self.entities.get(entity, qr(entity, []))
        if isinstance(reply, list):
            index = self.served.get(entity, 0)
            self.served[entity] = index + 1
            reply = reply[min(index, len(reply) - 1)]
        return reply if isinstance(reply, httpx.Response) else json_reply(reply)

    def connector(self) -> QuickBooksConnector:
        c = QuickBooksConnector()
        self.system.attach(c)
        c.sleep = lambda s: None
        return c

    def last(self, entity: str) -> str:
        return [s for s in self.statements if f"from {entity}" in s][-1]


# --------------------------------------------------------------------------- OAuth
def test_authorization_url_uses_intuit_and_the_accounting_scope() -> None:
    url = QuickBooksConnector.authorization_url(client_id="ABcid", redirect_uri="https://api.ziira.test/cb",
                                                state="st4te")
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://appcenter.intuit.com/connect/oauth2"
    assert q["scope"] == ["com.intuit.quickbooks.accounting"] and q["response_type"] == ["code"]
    assert q["state"] == ["st4te"] and q["client_id"] == ["ABcid"]


def test_exchange_code_returns_secrets_and_the_company() -> None:
    intuit = FakeIntuit(token_replies=[{**TOKEN, "refresh_token": "RT-first"}])
    result = intuit.connector().exchange_code(client_id="cid", client_secret="csecret1", code="c0de",
                                              redirect_uri="https://x/cb", realm_id="9130350000000001",
                                              environment="sandbox")
    assert result.secrets == {"client_id": "cid", "client_secret": "csecret1", "refresh_token": "RT-first"}
    assert result.config == {"environment": "sandbox", "realm_id": "9130350000000001"}
    request = intuit.system.requests[0]
    form = parse_qs(request.content.decode())
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["c0de"]
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:csecret1").decode()
    assert "c0de" not in str(request.url) and "csecret1" not in str(request.url)


def test_exchange_code_problems() -> None:
    bad = FakeIntuit(token_replies=[json_reply({"error": "invalid_grant"}, 400)])
    with pytest.raises(ConnectorError) as info:
        bad.connector().exchange_code(client_id="cid", client_secret="csecret1", code="c0de", redirect_uri="https://x",
                                      realm_id="123")
    assert info.value.retryable is False and "csecret1" not in str(info.value)
    ok = FakeIntuit()
    with pytest.raises(ConnectorError, match="which company"):
        ok.connector().exchange_code(client_id="c", client_secret="s1234", code="x", redirect_uri="https://x",
                                     realm_id="")
    with pytest.raises(ConnectorError, match="production or sandbox"):
        ok.connector().exchange_code(client_id="c", client_secret="s1234", code="x", redirect_uri="https://x",
                                     realm_id="1", environment="moon")


# --------------------------------------------------------------------------- tokens and rotation
def test_refresh_token_rotation_is_exposed_for_the_framework_to_save() -> None:
    rotated = {**TOKEN, "refresh_token": "RT-rotated-0002"}
    intuit = FakeIntuit({"Customer": qr("Customer", [])}, [rotated])
    c = intuit.connector()
    batches = drain(c.pull(CONFIG, SECRETS, "parties", None))
    assert c.updated_secrets == {"refresh_token": "RT-rotated-0002"}
    form = parse_qs(intuit.system.requests[0].content.decode())
    assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["RT-original-0001"]
    assert batches[-1].complete


def test_unchanged_refresh_token_means_nothing_to_save() -> None:
    c = FakeIntuit().connector()
    drain(c.pull(CONFIG, SECRETS, "parties", None))
    assert c.updated_secrets is None


def test_rotation_is_exposed_even_when_the_pull_then_fails() -> None:
    intuit = FakeIntuit({"Customer": json_reply({"x": 1}, 503)}, [{**TOKEN, "refresh_token": "RT-rotated-0002"}])
    c = intuit.connector()
    with pytest.raises(h.RetryAfterError):
        drain(c.pull(CONFIG, SECRETS, "parties", None))
    assert c.updated_secrets == {"refresh_token": "RT-rotated-0002"}


def test_a_revoked_or_expired_connection_says_connect_again() -> None:
    intuit = FakeIntuit(token_replies=[json_reply({"error": "invalid_grant"}, 400)])
    result = intuit.connector().check(CONFIG, SECRETS)
    assert not result.ok and "Connect QuickBooks Online again" in result.message
    assert SECRETS["refresh_token"] not in result.message and SECRETS["client_secret"] not in result.message
    with pytest.raises(ConnectorError) as info:
        drain(intuit.connector().pull(CONFIG, SECRETS, "parties", None))
    assert info.value.retryable is False


def test_check_ok_and_sandbox_host() -> None:
    result = FakeIntuit().connector().check(CONFIG, SECRETS)
    assert result.ok and result.message == "Connected to QuickBooks Online: Shop Inc."
    assert result.details["environment"] == "production"
    sandbox = FakeIntuit(api_host="sandbox-quickbooks.api.intuit.com")
    assert sandbox.connector().check({**CONFIG, "environment": "sandbox"}, SECRETS).ok


def test_check_with_bad_config() -> None:
    c = FakeIntuit().connector()
    assert "approved yet" in c.check({"environment": "production"}, SECRETS).message
    assert "incomplete" in c.check(CONFIG, {"client_id": "x"}).message
    assert "production or sandbox" in c.check({**CONFIG, "environment": "x"}, SECRETS).message


# --------------------------------------------------------------------------- pulling
def test_query_shape_paging_and_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quickbooks, "PAGE", 1)
    page1 = qr("Invoice", [fixture("qb_invoices.json")["QueryResponse"]["Invoice"][0]])
    page2 = qr("Invoice", [fixture("qb_invoices.json")["QueryResponse"]["Invoice"][1]])
    intuit = FakeIntuit({"Invoice": [page1, page2, qr("Invoice", [])], "Bill": qr("Bill", [])})
    batches = drain(intuit.connector().pull(CONFIG, SECRETS, "invoices", None))
    invoice_queries = [s for s in intuit.statements if "from Invoice" in s]
    assert invoice_queries == [
        "select * from Invoice order by Metadata.LastUpdatedTime startposition 1 maxresults 1",
        "select * from Invoice order by Metadata.LastUpdatedTime startposition 2 maxresults 1",
        "select * from Invoice order by Metadata.LastUpdatedTime startposition 3 maxresults 1"]
    assert {r.method for r in intuit.system.requests if r.url.host.endswith("intuit.com")} == {"GET", "POST"}
    assert all(r.method == "GET" for r in intuit.system.requests if r.url.path.startswith("/v3"))
    assert [b.complete for b in batches] == [False, True]
    cursor = json.loads(batches[-1].cursor or "")
    assert cursor["Invoice"] == "2024-05-05T17:55:00.000000+00:00"          # 11:00 -07:00 = 18:00 UTC, minus 5 minutes
    assert "Bill" not in cursor
    resumed = FakeIntuit({"Invoice": qr("Invoice", []), "Bill": qr("Bill", [])})
    drain(resumed.connector().pull(CONFIG, SECRETS, "invoices", batches[-1].cursor))
    assert resumed.last("Invoice") == ("select * from Invoice where Metadata.LastUpdatedTime > "
                                       "'2024-05-05T17:55:00+00:00' order by Metadata.LastUpdatedTime "
                                       "startposition 1 maxresults 1")


def test_invoices_and_bills() -> None:
    bill = {"Id": "55", "MetaData": {"CreateTime": "2024-05-02T08:00:00-07:00", "LastUpdatedTime": "2024-05-02T08:00:00-07:00"},
            "DocNumber": "INV-77", "TxnDate": "2024-05-02", "DueDate": "2024-06-01", "VendorRef": {"value": "9"},
            "TotalAmt": 700.0, "Balance": 0}
    intuit = FakeIntuit({"Invoice": fixture("qb_invoices.json"), "Bill": qr("Bill", [bill])})
    inv = {i.ref: i for i in records(drain(intuit.connector().pull(CONFIG, SECRETS, "invoices", None)))}
    a = inv["invoice:130"]
    assert (a.kind, a.total, a.paid, a.status, a.issue_date, a.due_date, a.number, a.party_ref, a.currency) == (
        "customer", D("513"), D("313"), "open", date(2024, 5, 4), date(2024, 6, 3), "1037", "customer:20", "USD")
    voided = inv["invoice:131"]
    assert (voided.status, voided.paid, voided.total) == ("cancelled", D(0), D(0))
    b = inv["bill:55"]
    assert (b.kind, b.status, b.paid, b.party_ref, b.due_date, b.number, b.currency) == (
        "supplier", "paid", D("700"), "vendor:9", date(2024, 6, 1), "INV-77", None)


def test_sales_from_invoices_receipts_credit_memos_and_refunds() -> None:
    methods = qr("PaymentMethod", [{"Id": "3", "Name": "M-Pesa"}, {"Id": "1", "Name": "Cash"}])
    credit = {"Id": "8", "MetaData": {"CreateTime": "2024-05-07T10:00:00-07:00", "LastUpdatedTime": "2024-05-07T10:00:00-07:00"},
              "TxnDate": "2024-05-07", "CustomerRef": {"value": "20"}, "TotalAmt": 100.0,
              "Line": [{"Amount": 100.0, "DetailType": "SalesItemLineDetail",
                        "SalesItemLineDetail": {"ItemRef": {"value": "11"}, "UnitPrice": 50, "Qty": 2}}],
              "TxnTaxDetail": {"TotalTax": 10}}
    refund = {**credit, "Id": "9", "PaymentMethodRef": {"value": "1"}, "PaymentRefNum": "RR1"}
    intuit = FakeIntuit({"SalesReceipt": fixture("qb_salesreceipts.json"), "Invoice": fixture("qb_invoices.json"),
                         "CreditMemo": qr("CreditMemo", [credit]), "RefundReceipt": qr("RefundReceipt", [refund]),
                         "PaymentMethod": methods})
    sales = {s.ref: s for s in records(drain(intuit.connector().pull(CONFIG, SECRETS, "sales", None)))}
    assert set(sales) == {"salesreceipt:77", "invoice:130", "invoice:131", "creditmemo:8", "refundreceipt:9"}
    r = sales["salesreceipt:77"]
    assert r.occurred_at == datetime(2024, 5, 2, 21, 0, tzinfo=UTC)               # 3 May 00:00 at +03:00
    assert r.entered_at == datetime(2024, 5, 3, 11, 22, 11, tzinfo=UTC) and r.customer_ref is None
    assert (r.number, r.total, r.status) == ("SR-9", D("1000"), "posted")
    assert [(p.method, p.amount, p.reference) for p in r.payments] == [("mobile_money", D("1000"), "SHK12ABC34")]
    assert [(ln.product_ref, ln.quantity, ln.unit_price) for ln in r.lines] == [("11", D("2"), D("500"))]
    inv = sales["invoice:130"]
    assert (inv.total, inv.tax_total, inv.discount_total, inv.branch_ref, inv.customer_ref, inv.currency) == (
        D("513"), D("38"), D("50"), "1", "customer:20", "USD")
    assert [(ln.product_ref, ln.quantity, ln.unit_price) for ln in inv.lines] == [("11", D("10"), D("50")),
                                                                                  ("12", D("1"), D("25"))]
    assert [(p.method, p.amount) for p in inv.payments] == [("credit", D("200"))]
    assert sales["invoice:131"].status == "voided"
    cm = sales["creditmemo:8"]
    assert (cm.status, cm.total, cm.tax_total, cm.lines[0].quantity, cm.payments) == ("refunded", D("-100"), D("-10"),
                                                                                    D("-2"), ())
    rr = sales["refundreceipt:9"]
    assert [(p.method, p.amount) for p in rr.payments] == [("cash", D("-100"))]
    assert sum(1 for s in intuit.statements if "from PaymentMethod" in s) == 1     # looked up once per pull


def test_payments_in_and_out() -> None:
    pay = {"Id": "400", "MetaData": {"CreateTime": "2024-05-04T10:00:00-07:00", "LastUpdatedTime": "2024-05-04T10:00:00-07:00"},
           "TxnDate": "2024-05-04", "TotalAmt": 313.0, "CustomerRef": {"value": "20", "name": "Acme Builders"},
           "PaymentMethodRef": {"value": "3"}, "PaymentRefNum": "SHK12ABC34",
           "DepositToAccountRef": {"value": "35", "name": "Undeposited Funds"},
           "Line": [{"Amount": 313.0, "LinkedTxn": [{"TxnId": "130", "TxnType": "Invoice"}]}]}
    pay2 = {"Id": "401", "MetaData": {"CreateTime": "2024-05-05T10:00:00-07:00", "LastUpdatedTime": "2024-05-05T10:00:00-07:00"},
            "TxnDate": "2024-05-05", "TotalAmt": 5.0, "CustomerRef": None, "Line": []}
    billpay = {"Id": "500", "MetaData": {"CreateTime": "2024-05-05T10:00:00-07:00", "LastUpdatedTime": "2024-05-05T10:00:00-07:00"},
               "TxnDate": "2024-05-05", "TotalAmt": 700.0, "VendorRef": {"value": "9", "name": "Bolt"},
               "PayType": "Check", "DocNumber": "CHK-1", "CheckPayment": {"BankAccountRef": {"name": "Checking"}},
               "Line": [{"Amount": 700.0, "LinkedTxn": [{"TxnId": "55", "TxnType": "Bill"}]}]}
    card = {**billpay, "Id": "501", "PayType": "CreditCard", "CheckPayment": None,
            "CreditCardPayment": {"CCAccountRef": {"name": "Visa"}}, "Line": [{"LinkedTxn": [{"TxnType": "VendorCredit"}]}]}
    intuit = FakeIntuit({"Payment": qr("Payment", [pay, pay2]), "BillPayment": qr("BillPayment", [billpay, card]),
                         "PaymentMethod": qr("PaymentMethod", [{"Id": "3", "Name": "M-Pesa"}])})
    pays = {p.ref: p for p in records(drain(intuit.connector().pull(CONFIG, SECRETS, "payments", None)))}
    a = pays["payment:400"]
    assert (a.direction, a.amount, a.method, a.reference, a.party_ref, a.party_name, a.account, a.invoice_ref) == (
        "in", D("313"), "mobile_money", "SHK12ABC34", "customer:20", "Acme Builders", "Undeposited Funds",
        "invoice:130")
    assert (pays["payment:401"].method, pays["payment:401"].party_ref, pays["payment:401"].invoice_ref) == (
        "other", None, None)
    b = pays["billpayment:500"]
    assert (b.direction, b.method, b.reference, b.account, b.invoice_ref, b.party_ref) == (
        "out", "bank", "CHK-1", "Checking", "bill:55", "vendor:9")
    assert (pays["billpayment:501"].method, pays["billpayment:501"].account, pays["billpayment:501"].invoice_ref) == (
        "card", "Visa", None)


def test_expenses_journals_and_deposits() -> None:
    purchase = {"Id": "60", "MetaData": {"CreateTime": "2024-05-06T08:00:00-07:00", "LastUpdatedTime": "2024-05-06T08:00:00-07:00"},
                "TxnDate": "2024-05-06", "PaymentType": "Cash", "TotalAmt": 2500.0, "EntityRef": {"value": "9", "type": "Vendor"},
                "PrivateNote": None, "Line": [{"Amount": 2500.0, "Description": "Fuel for van",
                                               "DetailType": "AccountBasedExpenseLineDetail",
                                               "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "7", "name": "Fuel"}}}]}
    refund = {**purchase, "Id": "61", "Credit": True, "EntityRef": None, "Line": []}
    exp = {e.ref: e for e in records(drain(FakeIntuit({"Purchase": qr("Purchase", [purchase, refund])}).connector()
                                           .pull(CONFIG, SECRETS, "expenses", None)))}
    assert (exp["purchase:60"].amount, exp["purchase:60"].category, exp["purchase:60"].description,
            exp["purchase:60"].party_ref) == (D("2500"), "Fuel", "Fuel for van", "vendor:9")
    assert (exp["purchase:61"].amount, exp["purchase:61"].category, exp["purchase:61"].party_ref) == (D("-2500"), None,
                                                                                                    None)
    deposit = {"Id": "700", "MetaData": {"CreateTime": "2024-05-06T09:00:00-07:00", "LastUpdatedTime": "2024-05-06T09:00:00-07:00"},
               "TxnDate": "2024-05-06", "TotalAmt": 800.0, "DepositToAccountRef": {"name": "Checking"},
               "Line": [{"Amount": 500.0, "DetailType": "DepositLineDetail",
                         "DepositLineDetail": {"AccountRef": {"name": "Undeposited Funds"}, "Entity": {"value": "20"}}},
                        {"Amount": 300.0, "DetailType": "DepositLineDetail",
                         "DepositLineDetail": {"AccountRef": {"name": "Sales"}}}]}
    intuit = FakeIntuit({"JournalEntry": fixture("qb_journalentries.json"), "Deposit": qr("Deposit", [deposit])})
    entries = {j.ref: j for j in records(drain(intuit.connector().pull(CONFIG, SECRETS, "journal_entries", None)))}
    je = entries["journalentry:301"]
    assert [(ln.account, ln.debit, ln.credit, ln.party_ref) for ln in je.lines] == [
        ("Rent", D("1500"), D(0), None), ("Accounts Payable", D(0), D("1500"), "vendor:9")]
    assert (je.is_manual, je.memo, je.number, je.entry_date) == (True, "Rent accrual", "JE-1", date(2024, 5, 6))
    dep = entries["deposit:700"]
    assert [(ln.account, ln.debit, ln.credit, ln.party_ref) for ln in dep.lines] == [
        ("Checking", D("800"), D(0), None), ("Undeposited Funds", D(0), D("500"), "customer:20"),
        ("Sales", D(0), D("300"), None)]
    assert dep.is_manual is False
    assert sum(ln.debit for ln in dep.lines) == sum(ln.credit for ln in dep.lines)


def test_parties_items_employees_and_departments() -> None:
    customer = {"Id": "20", "DisplayName": "Acme Builders", "CompanyName": "Acme Ltd",
                "PrimaryPhone": {"FreeFormNumber": "020 111"}, "Mobile": None, "PrimaryEmailAddr": {"Address": "a@x.test"},
                "MetaData": {"CreateTime": "2023-01-01T09:00:00-07:00", "LastUpdatedTime": "2024-01-01T09:00:00-07:00"}}
    vendor = {"Id": "20", "DisplayName": None, "CompanyName": "Bolt Ltd", "TaxIdentifier": "XXXXX1234",
              "Mobile": {"FreeFormNumber": "0712"}, "MetaData": {"LastUpdatedTime": "2024-01-02T09:00:00-07:00"}}
    parties = {p.ref: p for p in records(drain(FakeIntuit({"Customer": qr("Customer", [customer]),
                                                           "Vendor": qr("Vendor", [vendor])}).connector()
                                               .pull(CONFIG, SECRETS, "parties", None)))}
    assert set(parties) == {"customer:20", "vendor:20"}                    # the same number in two lists stays distinct
    assert (parties["customer:20"].kind, parties["customer:20"].name, parties["customer:20"].phone,
            parties["customer:20"].email) == ("customer", "Acme Builders", "020 111", "a@x.test")
    assert (parties["vendor:20"].kind, parties["vendor:20"].name, parties["vendor:20"].phone,
            parties["vendor:20"].tax_id, parties["vendor:20"].created_at) == ("supplier", "Bolt Ltd", "0712",
                                                                              "XXXXX1234", None)
    items: list[dict[str, Any]] = [{"Id": "1", "Name": "Hammer", "Type": "Inventory", "Sku": "HAM-1", "FullyQualifiedName": "Tools:Hammer",
              "UnitPrice": 50, "PurchaseCost": 30.5, "MetaData": {"LastUpdatedTime": "2024-01-01T09:00:00-07:00"}},
             {"Id": "2", "Name": "Tools", "Type": "Category", "MetaData": {"LastUpdatedTime": "2024-01-01T09:00:00-07:00"}},
             {"Id": "3", "Name": "Labour", "Type": "Service", "UnitPrice": 0, "PurchaseCost": None, "Sku": None,
              "MetaData": {"LastUpdatedTime": "2024-01-01T09:00:00-07:00"}}]
    intuit = FakeIntuit({"Item": qr("Item", items), "Employee": qr("Employee", [
        {"Id": "5", "DisplayName": "Jo", "PrimaryEmailAddr": None,
         "MetaData": {"CreateTime": "2023-01-01T00:00:00Z", "LastUpdatedTime": "2024-01-01T09:00:00-07:00"}}]),
        "Department": qr("Department", [{"Id": "1", "Name": "Main", "FullyQualifiedName": "Main",
                                         "MetaData": {"LastUpdatedTime": "2024-01-01T09:00:00-07:00"}}])})
    c = intuit.connector()
    products = {p.ref: p for p in records(drain(c.pull(CONFIG, SECRETS, "products", None)))}
    assert set(products) == {"1", "3"}
    assert (products["1"].category, products["1"].unit_cost, products["1"].sku) == ("Tools", D("30.5"), "HAM-1")
    assert (products["3"].category, products["3"].unit_price, products["3"].unit_cost) == ("Service", None, None)
    assert records(drain(c.pull(CONFIG, SECRETS, "users", None)))[0].email is None
    assert [(b.ref, b.name) for b in records(drain(c.pull(CONFIG, SECRETS, "branches", None)))] == [("1", "Main")]
    assert "Active IN (true, false)" in intuit.last("Item")                   # inactive ones too: history matters


# --------------------------------------------------------------------------- errors
def test_http_errors_during_pull() -> None:
    def run(reply: httpx.Response) -> ConnectorError:
        intuit = FakeIntuit({"Customer": reply})
        with pytest.raises(ConnectorError) as info:
            drain(intuit.connector().pull(CONFIG, SECRETS, "parties", None))
        return info.value

    auth = run(json_reply({"fault": {"error": [{"message": "message=AuthenticationFailed; errorCode=003200",
                                                "detail": "Token expired", "code": "3200"}], "type": "AUTHENTICATION"}},
                          401))
    assert auth.retryable is False and "did not accept" in str(auth)
    assert run(json_reply({"Fault": {"Error": [{"Message": "ApplicationAuthorizationFailed"}]}}, 403)).retryable is False
    throttled = run(json_reply({"Fault": {"Error": [{"Message": "ThrottleExceeded"}]}}, 429, {"Retry-After": "20"}))
    assert isinstance(throttled, h.RetryAfterError) and throttled.retry_after == 20
    assert run(json_reply({}, 500)).retryable is True
    parse = run(json_reply({"Fault": {"Error": [{"Message": "QueryParserError", "Detail": "bad token"}],
                                      "type": "ValidationFault"}, "time": "x"}, 400))
    assert parse.retryable is False
    assert run(httpx.Response(200, text="<html></html>")).retryable is True
    fault_200 = run(json_reply({"Fault": {"Error": [{"Message": "Something", "Detail": "odd"}]}}, 200))
    assert fault_200.retryable is False and "Something" in str(fault_200)


def test_unknown_entity_and_timeout() -> None:
    with pytest.raises(ConnectorError):
        FakeIntuit().connector().pull(CONFIG, SECRETS, "stock_movements", None)

    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth.platform.intuit.com":
            return json_reply(TOKEN)
        raise httpx.ReadTimeout("t", request=request)

    c = QuickBooksConnector()
    FakeSystem(slow).attach(c)
    with pytest.raises(h.RetryAfterError):
        drain(c.pull(CONFIG, SECRETS, "parties", None))


def test_limit_stops_early(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quickbooks, "PAGE", 1)
    inv = fixture("qb_invoices.json")["QueryResponse"]["Invoice"]
    intuit = FakeIntuit({"Invoice": qr("Invoice", inv[:1]), "Bill": qr("Bill", [])})
    batches = drain(intuit.connector().pull(CONFIG, SECRETS, "invoices", None, limit=1))
    assert len(batches) == 1 and batches[0].complete is False


@settings(max_examples=30, deadline=None)
@given(secret=st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=30),
       refresh=st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=30))
def test_secrets_never_leak_even_if_intuit_echoes_them(secret: str, refresh: str) -> None:
    creds = {"client_id": "ABcid", "client_secret": secret, "refresh_token": refresh}
    echo = f"bad request secret {secret} token {refresh} bearer AT-eyJlbmMiOiJBMTI4"
    intuit = FakeIntuit({"Customer": json_reply({"Fault": {"Error": [{"Message": echo}]}}, 400),
                         "Vendor": json_reply({"Fault": {"Error": [{"Message": echo}]}}, 400)},
                        [{**TOKEN, "refresh_token": refresh}])
    c = intuit.connector()
    with pytest.raises(ConnectorError) as info:
        drain(c.pull(CONFIG, creds, "parties", None))
    for value in (secret, refresh, "AT-eyJlbmMiOiJBMTI4"):
        assert value not in str(info.value)
    revoked = FakeIntuit(token_replies=[json_reply({"error": f"invalid {secret} {refresh}"}, 400)]).connector()
    message = revoked.check(CONFIG, creds).message
    assert secret not in message and refresh not in message

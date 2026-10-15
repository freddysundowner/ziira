"""Zoho Books connector: OAuth, token refresh, pacing, mapping, cursors and errors on a mock server."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ziira.modules.connect.connectors import _http as h
from ziira.modules.connect.connectors.zoho_books import ZohoBooksConnector, data_centre_urls
from ziira.modules.connect.public import ConnectorError
from ziira.modules.connect.tests.api_helpers import FakeSystem, drain, fixture, json_reply, records

D = Decimal
CONFIG: dict[str, Any] = {"data_centre": "eu", "organization_id": "10234695"}
SECRETS = {"client_id": "1000.CLIENTID", "client_secret": "cl13nt-s3cret-value", "refresh_token": "1000.r3fresh.t0ken"}
OK_TOKEN = {"access_token": "AT-1", "expires_in": 3600, "api_domain": "https://www.zohoapis.eu",
            "token_type": "Bearer"}


class FakeZoho:
    """Mock accounts.zoho.eu and www.zohoapis.eu. `routes` maps an API path to a reply or a list of replies."""

    def __init__(self, routes: dict[str, Any] | None = None, token_replies: list[Any] | None = None) -> None:
        self.routes = routes or {}
        self.token_replies = token_replies or [OK_TOKEN]
        self.token_calls = 0
        self.served: dict[str, int] = {}
        self.sleeps: list[float] = []
        self.system = FakeSystem(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.zoho.eu":
            assert request.method == "POST" and request.url.path == "/oauth/v2/token"
            reply = self.token_replies[min(self.token_calls, len(self.token_replies) - 1)]
            self.token_calls += 1
            if isinstance(reply, httpx.Response):
                return reply
            return json_reply(reply)
        assert request.method == "GET" and request.url.host == "www.zohoapis.eu"
        assert request.headers["Authorization"].startswith("Zoho-oauthtoken AT-")
        path = request.url.path.removeprefix("/books/v3")
        if path != "/organizations":
            assert request.url.params["organization_id"] == "10234695"
        key = path
        if f"{path}?page={request.url.params.get('page')}" in self.routes:
            key = f"{path}?page={request.url.params.get('page')}"
        reply = self.routes.get(key, {"code": 0, "message": "success"})
        if isinstance(reply, list):
            index = self.served.get(key, 0)
            self.served[key] = index + 1
            reply = reply[min(index, len(reply) - 1)]
        if isinstance(reply, httpx.Response):
            return reply
        return json_reply(reply)

    def connector(self) -> ZohoBooksConnector:
        c = ZohoBooksConnector()
        self.system.attach(c)
        c.sleep = self.sleeps.append
        return c

    def api_requests(self) -> list[httpx.Request]:
        return [r for r in self.system.requests if r.url.host == "www.zohoapis.eu"]


def query(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}


def test_data_centres_are_data() -> None:
    assert data_centre_urls("eu")["accounts"] == "https://accounts.zoho.eu"
    assert data_centre_urls("com.au")["api"] == "https://www.zohoapis.com.au"
    assert data_centre_urls("zoho.in")["api"] == "https://www.zohoapis.in"
    assert data_centre_urls(None)["accounts"] == "https://accounts.zoho.com"
    with pytest.raises(ConnectorError):
        data_centre_urls("evil.example/x")


# --------------------------------------------------------------------------- OAuth
def test_authorization_url() -> None:
    url = ZohoBooksConnector.authorization_url(data_centre="eu", client_id="1000.CID", state="st4te",
                                               redirect_uri="https://api.ziira.test/api/v1/connect/oauth/callback")
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://accounts.zoho.eu/oauth/v2/auth"
    assert q["client_id"] == ["1000.CID"] and q["state"] == ["st4te"] and q["access_type"] == ["offline"]
    assert q["response_type"] == ["code"] and q["prompt"] == ["consent"]
    scopes = q["scope"][0].split(",")
    assert scopes and all(s.startswith("ZohoBooks.") and s.endswith(".READ") for s in scopes)   # read scopes only
    assert q["redirect_uri"] == ["https://api.ziira.test/api/v1/connect/oauth/callback"]


def test_exchange_code_stores_refresh_token_and_picks_the_only_organisation() -> None:
    single = {"code": 0, "organizations": [{"organization_id": "10234695", "name": "Shop Ltd"}]}
    zoho = FakeZoho({"/organizations": single}, [{**OK_TOKEN, "refresh_token": "1000.new.refresh"}])
    result = zoho.connector().exchange_code(data_centre="eu", client_id="cid", client_secret="csecret1", code="c0de",
                                            redirect_uri="https://api.ziira.test/cb")
    assert result.secrets == {"client_id": "cid", "client_secret": "csecret1", "refresh_token": "1000.new.refresh"}
    assert result.config["organization_id"] == "10234695" and result.config["organization_name"] == "Shop Ltd"
    token_request = zoho.system.requests[0]
    form = parse_qs(token_request.content.decode())
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["c0de"]
    assert form["redirect_uri"] == ["https://api.ziira.test/cb"]
    assert "c0de" not in str(token_request.url)                               # secrets travel in the body only


def test_exchange_code_with_several_organisations_prefers_the_default() -> None:
    zoho = FakeZoho({"/organizations": fixture("zoho_organizations.json")}, [{**OK_TOKEN, "refresh_token": "r1"}])
    result = zoho.connector().exchange_code(data_centre="eu", client_id="cid", client_secret="csecret1", code="c",
                                            redirect_uri="https://x/cb")
    assert result.config["organization_id"] == "10234695"
    assert [o["id"] for o in result.config["organizations"]] == ["10234695", "10234999"]


def test_exchange_code_refused_has_a_friendly_non_retryable_error() -> None:
    zoho = FakeZoho(token_replies=[{"error": "invalid_code"}])
    with pytest.raises(ConnectorError) as info:
        zoho.connector().exchange_code(data_centre="eu", client_id="cid", client_secret="csecret1", code="c0de",
                                       redirect_uri="https://x/cb")
    assert info.value.retryable is False and "csecret1" not in str(info.value) and "c0de" not in str(info.value)
    no_refresh = FakeZoho(token_replies=[OK_TOKEN])
    with pytest.raises(ConnectorError, match="long-lived"):
        no_refresh.connector().exchange_code(data_centre="eu", client_id="c", client_secret="s1234", code="x",
                                             redirect_uri="https://x/cb")


# --------------------------------------------------------------------------- check and tokens
def test_check_ok_refreshes_the_token_then_reads_organisations() -> None:
    zoho = FakeZoho({"/organizations": fixture("zoho_organizations.json")})
    result = zoho.connector().check(CONFIG, SECRETS)
    assert result.ok and result.message == "Connected to Zoho Books: Shop Ltd."
    refresh = parse_qs(zoho.system.requests[0].content.decode())
    assert refresh["grant_type"] == ["refresh_token"] and refresh["refresh_token"] == [SECRETS["refresh_token"]]
    assert "organization_id" not in query(zoho.api_requests()[0])              # /organizations is not per-organisation


def test_check_asks_for_an_organisation_when_none_is_set() -> None:
    zoho = FakeZoho({"/organizations": fixture("zoho_organizations.json")})
    result = zoho.connector().check({"data_centre": "eu"}, SECRETS)
    assert not result.ok and "Shop Ltd (10234695)" in result.message and "Shop Two (10234999)" in result.message
    wrong = zoho.connector().check({**CONFIG, "organization_id": "999"}, SECRETS)
    assert not wrong.ok and "not one this approval can reach" in wrong.message


def test_check_with_withdrawn_approval() -> None:
    zoho = FakeZoho(token_replies=[{"error": "invalid_client"}])
    result = zoho.connector().check(CONFIG, SECRETS)
    assert not result.ok and "Connect again" in result.message
    assert SECRETS["client_secret"] not in result.message and SECRETS["refresh_token"] not in result.message


def test_expired_access_token_is_refreshed_once_and_the_request_repeated() -> None:
    zoho = FakeZoho({"/contacts": [json_reply({"code": 14, "message": "invalid token"}, 401),
                                   {"code": 0, "contacts": []}]},
                    [OK_TOKEN, {**OK_TOKEN, "access_token": "AT-2"}])
    # the mock insists on the "AT-" prefix; AT-1 then AT-2 are both fine
    drain(zoho.connector().pull(CONFIG, SECRETS, "parties", None))
    assert zoho.token_calls == 2
    assert [r.headers["Authorization"] for r in zoho.api_requests()] == ["Zoho-oauthtoken AT-1",
                                                                         "Zoho-oauthtoken AT-2"]


def test_endless_token_rejection_stops_with_a_reconnect_message() -> None:
    zoho = FakeZoho({"/contacts": json_reply({"code": 14}, 401)})
    with pytest.raises(ConnectorError) as info:
        drain(zoho.connector().pull(CONFIG, SECRETS, "parties", None))
    assert info.value.retryable is False and "Connect Zoho Books again" in str(info.value)
    assert zoho.token_calls <= 3


# --------------------------------------------------------------------------- pulling
def sales_zoho(**extra: Any) -> FakeZoho:
    routes: dict[str, Any] = {
        "/invoices?page=1": fixture("zoho_invoices_page1.json"), "/invoices?page=2": fixture("zoho_invoices_page2.json"),
        "/invoices/982000000567114": fixture("zoho_invoice_detail_114.json"),
        "/invoices/982000000567117": fixture("zoho_invoice_detail_117.json")}
    routes.update(extra)
    return FakeZoho(routes)


def test_sales_mapped_field_by_field_across_pages() -> None:
    zoho = sales_zoho()
    batches = drain(zoho.connector().pull(CONFIG, SECRETS, "sales", None))
    assert [b.complete for b in batches] == [False, True]
    sales = {s.ref: s for s in records(batches)}
    assert set(sales) == {"982000000567114", "982000000567116", "982000000567117"}      # the draft is not read
    a = sales["982000000567114"]
    assert a.occurred_at == datetime(2024, 5, 3, 21, 0, tzinfo=UTC)                     # 4 May 00:00 at +03:00
    assert a.entered_at == datetime(2024, 5, 4, 6, 0, 5, tzinfo=UTC)
    assert (a.number, a.total, a.status, a.customer_ref, a.currency) == ("INV-000001", D("5000"), "posted",
                                                                          "982000000567001", "KES")
    assert (a.tax_total, a.cashier_ref) == (D("689.65"), "982000000100001")
    # 10% of 10 x 500 -> 500 given as discount_amount; 20 given as a plain amount; none on delivery
    l1, l2, l3 = a.lines
    assert (l1.product_ref, l1.quantity, l1.unit_price, l1.list_price, l1.discount) == (
        "982000000030049", D("10"), D("450"), D("500"), D("500"))
    assert (l2.unit_price, l2.list_price, l2.discount) == (D("240"), D("250"), D("20"))
    assert (l3.product_ref, l3.unit_price, l3.list_price, l3.discount) == (None, D("20"), None, D(0))
    assert a.discount_total == D("520")
    assert [(p.method, p.amount, p.reference) for p in a.payments] == [("mobile_money", D("3000"), "SHK12ABC34"),
                                                                       ("credit", D("2000"), None)]
    void = sales["982000000567116"]
    assert (void.status, void.lines, void.payments) == ("voided", (), ())
    assert sales["982000000567117"].customer_ref is None and sales["982000000567117"].currency is None


def test_request_shape_paging_pacing_and_cursor() -> None:
    zoho = sales_zoho()
    batches = drain(zoho.connector().pull(CONFIG, SECRETS, "sales", None))
    lists = [r for r in zoho.api_requests() if r.url.path.endswith("/invoices")]
    assert [query(r)["page"] for r in lists] == ["1", "2"]
    first = query(lists[0])
    assert first["sort_column"] == "last_modified_time" and first["sort_order"] == "A" and first["per_page"] == "200"
    assert "last_modified_time" not in first
    assert zoho.system.methods() == {"GET", "POST"}
    assert {r.method for r in zoho.api_requests()} == {"GET"}
    # newest change: 6 May 10:00:05 +03:00 = 07:00:05 UTC; cursor is 5 minutes earlier
    assert json.loads(batches[-1].cursor or "")["invoices"] == "2024-05-06T06:55:05.000000+00:00"
    resumed = sales_zoho()
    drain(resumed.connector().pull(CONFIG, SECRETS, "sales", batches[-1].cursor))
    assert query([r for r in resumed.api_requests() if r.url.path.endswith("/invoices")][0])[
        "last_modified_time"] == "2024-05-06T06:55:05+0000"


def test_rows_older_than_the_cursor_are_dropped_even_if_zoho_ignores_the_filter() -> None:
    zoho = sales_zoho()
    since = json.dumps({"invoices": "2024-05-05T08:00:00.000000+00:00"})      # after the first invoice, before void
    sales = records(drain(zoho.connector().pull(CONFIG, SECRETS, "sales", since)))
    assert [s.ref for s in sales] == ["982000000567116", "982000000567117"]


def test_fetch_details_off_costs_only_list_requests() -> None:
    zoho = sales_zoho()
    sales = records(drain(zoho.connector().pull({**CONFIG, "fetch_details": "no"}, SECRETS, "sales", None)))
    assert all(s.lines == () for s in sales)
    assert [r.url.path for r in zoho.api_requests()] == ["/books/v3/invoices", "/books/v3/invoices"]
    credit = [s for s in sales if s.ref == "982000000567114"][0]
    assert [p.method for p in credit.payments] == ["credit"]                  # only the balance is known without detail


def test_request_budget_stops_the_run_cleanly_and_says_more_remain() -> None:
    zoho = sales_zoho()
    c = zoho.connector()
    batches = drain(c.pull({**CONFIG, "max_requests_per_run": "2"}, SECRETS, "sales", None))
    assert len(zoho.api_requests()) <= 2
    assert batches[-1].complete is False
    assert any("allowance" in n for n in c.notes)


def test_throttling_is_paced_and_retried_once() -> None:
    zoho = FakeZoho({"/contacts": [json_reply({"code": 45, "message": "too many requests"}, 400,
                                              {"Retry-After": "7"}), {"code": 0, "contacts": []}]})
    c = zoho.connector()
    drain(c.pull(CONFIG, SECRETS, "parties", None))
    assert zoho.sleeps == [7]                                                 # honoured the header
    always = FakeZoho({"/contacts": json_reply({"code": 0}, 429, {"Retry-After": "11"})})
    with pytest.raises(h.RetryAfterError) as info:
        drain(always.connector().pull(CONFIG, SECRETS, "parties", None))
    assert info.value.retryable and info.value.retry_after == 11 and always.sleeps == [11]


def test_pacer_waits_when_the_minute_allowance_is_full() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    pacer = h.Pacer(2, sleep=sleep, clock=lambda: now[0])
    pacer.wait()
    now[0] = 10
    pacer.wait()
    pacer.wait()                                                              # third inside the minute: waits
    assert sleeps == [50.0] and pacer.used == 3
    limited = h.Pacer(5, budget=2, sleep=sleep, clock=lambda: now[0])
    limited.wait()
    limited.wait()
    assert limited.exhausted


def test_invoices_bills_payments_expenses_journals_and_directory() -> None:
    zoho = FakeZoho({
        "/invoices": fixture("zoho_invoices_page2.json"), "/bills": fixture("zoho_bills.json"),
        "/customerpayments": fixture("zoho_customerpayments.json"),
        "/customerpayments/982000000700501": fixture("zoho_customerpayment_detail_501.json"),
        "/customerpayments/982000000700502": {"code": 0, "payment": {}},
        "/vendorpayments": {"code": 0, "vendorpayments": [
            {"payment_id": "vp1", "date": "2024-05-02", "amount": 700.0, "payment_mode": "Bank Transfer",
             "vendor_id": "v1", "vendor_name": "Bolt Supplies", "reference_number": "TRF9",
             "paid_through_account_name": "Equity Bank", "created_time": "2024-05-02T08:00:00+0300",
             "last_modified_time": "2024-05-02T08:00:00+0300"}]},
        "/vendorpayments/vp1": {"code": 0, "payment": {"bills": [{"bill_id": "982000000600001"}]}},
        "/expenses": {"code": 0, "expenses": [
            {"expense_id": "e1", "date": "2024-05-06", "account_name": "Fuel", "total": 2500.0, "description": None,
             "vendor_id": None, "created_time": "2024-05-06T08:00:00+0300",
             "last_modified_time": "2024-05-06T08:00:00+0300"},
            {"expense_id": "e2", "date": "2024-05-07", "account_name": None, "amount": 90, "total": None,
             "created_time": "2024-05-07T08:00:00+0300", "last_modified_time": "2024-05-07T08:00:00+0300"}]},
        "/journals": {"code": 0, "journals": [
            {"journal_id": "982000000800001", "journal_date": "2024-05-06", "entry_number": "7", "notes": "Rent",
             "created_time": "2024-05-06T12:00:00+0300", "last_modified_time": "2024-05-06T12:00:00+0300"}]},
        "/journals/982000000800001": fixture("zoho_journal_detail.json"),
        "/contacts": {"code": 0, "contacts": [
            {"contact_id": "c1", "contact_name": "Acme", "company_name": "Acme Ltd", "contact_type": "customer",
             "email": "a@x.test", "phone": "020", "mobile": None, "gst_no": "P0123",
             "created_time": "2023-01-01T09:00:00+0300", "last_modified_time": "2024-01-01T09:00:00+0300"},
            {"contact_id": "c2", "contact_name": "", "company_name": "Bolt Ltd", "contact_type": "vendor",
             "email": None, "phone": None, "mobile": "0712", "created_time": None,
             "last_modified_time": "2024-01-02T09:00:00+0300"}]},
        "/items": {"code": 0, "items": [
            {"item_id": "i1", "name": "Cement", "sku": "CEM-50", "rate": 500, "purchase_rate": 420.5,
             "category_name": "Building", "last_modified_time": "2024-01-01T09:00:00+0300"},
            {"item_id": "i2", "name": "Service", "sku": "", "rate": 0, "purchase_rate": None,
             "last_modified_time": "2024-01-01T09:00:00+0300"}]},
        "/users": {"code": 0, "users": [{"user_id": "u1", "name": "Owner", "email": "o@x.test", "user_role": "admin",
                                          "created_time": "2023-01-01T09:00:00+0300"}]}})
    c = zoho.connector()
    inv = {i.ref: i for i in records(drain(c.pull(CONFIG, SECRETS, "invoices", None)))}
    assert (inv["982000000567116"].status, inv["982000000567116"].paid) == ("cancelled", D(0))
    assert (inv["982000000567117"].status, inv["982000000567117"].paid, inv["982000000567117"].party_ref) == (
        "paid", D("1160"), None)
    bills = {k: v for k, v in inv.items() if v.kind == "supplier"}
    assert set(bills) == {"982000000600001", "982000000600002", "982000000600003"}
    assert (bills["982000000600001"].status, bills["982000000600002"].status, bills["982000000600002"].paid) == (
        "paid", "open", D(0))
    assert bills["982000000600001"].number == "INV-77" and bills["982000000600003"].status == "cancelled"
    pays = {p.ref: p for p in records(drain(c.pull(CONFIG, SECRETS, "payments", None)))}
    cp = pays["982000000700501"]
    assert (cp.direction, cp.amount, cp.method, cp.reference, cp.party_name, cp.account, cp.invoice_ref) == (
        "in", D("3000"), "mobile_money", "SHK12ABC34", "Acme Builders", "Mpesa Till", "982000000567114")
    assert (pays["982000000700502"].method, pays["982000000700502"].party_ref, pays["982000000700502"].invoice_ref) == (
        "other", None, None)
    vp = pays["vp1"]
    assert (vp.direction, vp.method, vp.account, vp.invoice_ref, vp.party_ref) == ("out", "bank", "Equity Bank",
                                                                                   "982000000600001", "v1")
    exp = {e.ref: e for e in records(drain(c.pull(CONFIG, SECRETS, "expenses", None)))}
    assert (exp["e1"].amount, exp["e1"].category, exp["e2"].amount, exp["e2"].category) == (D("2500"), "Fuel", D("90"),
                                                                                           None)
    jrn = records(drain(c.pull(CONFIG, SECRETS, "journal_entries", None)))[0]
    assert [(ln.account, ln.debit, ln.credit, ln.party_ref) for ln in jrn.lines] == [
        ("Rent Expense", D("15000"), D(0), None), ("Accounts Payable", D(0), D("15000"), "982000000700001")]
    assert (jrn.number, jrn.memo, jrn.created_by_ref, jrn.entry_date, jrn.is_manual) == (
        "7", "Rent", "982000000100001", date(2024, 5, 6), True)
    parties = {p.ref: p for p in records(drain(c.pull(CONFIG, SECRETS, "parties", None)))}
    assert (parties["c1"].kind, parties["c1"].name, parties["c1"].phone, parties["c1"].tax_id) == (
        "customer", "Acme", "020", "P0123")
    assert (parties["c2"].kind, parties["c2"].name, parties["c2"].phone, parties["c2"].created_at) == (
        "supplier", "Bolt Ltd", "0712", None)
    products = {p.ref: p for p in records(drain(c.pull(CONFIG, SECRETS, "products", None)))}
    assert (products["i1"].unit_cost, products["i1"].unit_price, products["i1"].category) == (
        D("420.5"), D("500"), "Building")
    assert (products["i2"].sku, products["i2"].unit_cost, products["i2"].unit_price) == (None, None, None)
    users = drain(c.pull(CONFIG, SECRETS, "users", "ignored"))
    assert records(users)[0].role == "admin" and users[-1].cursor is None and users[-1].complete   # full list each time
    assert "last_modified_time" not in query([r for r in zoho.api_requests() if r.url.path.endswith("/users")][0])


def test_unsupported_entity_and_bad_config() -> None:
    with pytest.raises(ConnectorError):
        FakeZoho().connector().pull(CONFIG, SECRETS, "stock_movements", None)
    with pytest.raises(ConnectorError, match="organisation"):
        drain(FakeZoho().connector().pull({"data_centre": "eu"}, SECRETS, "parties", None))
    with pytest.raises(ConnectorError, match="whole numbers"):
        drain(FakeZoho().connector().pull({**CONFIG, "requests_per_minute": "lots"}, SECRETS, "parties", None))


# --------------------------------------------------------------------------- errors
def test_http_errors_during_pull() -> None:
    def run(reply: httpx.Response) -> ConnectorError:
        zoho = FakeZoho({"/contacts": reply})
        with pytest.raises(ConnectorError) as info:
            drain(zoho.connector().pull(CONFIG, SECRETS, "parties", None))
        return info.value

    forbidden = run(json_reply({"code": 57, "message": "not authorized"}, 200))
    assert forbidden.retryable is False and "not allowed" in str(forbidden)
    assert run(json_reply({"message": "x"}, 403)).retryable is False
    assert run(json_reply({}, 503)).retryable is True
    assert run(json_reply({"code": 1002, "message": "Invoice does not exist."}, 404)).retryable is False
    assert run(httpx.Response(200, text="<html>nope</html>")).retryable is True
    odd = run(json_reply({"code": 2, "message": "Invalid value passed for page"}, 200))
    assert odd.retryable is False and "Invalid value" in str(odd)


def test_timeout_is_retryable() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.zoho.eu":
            return json_reply(OK_TOKEN)
        raise httpx.ReadTimeout("t", request=request)

    c = ZohoBooksConnector()
    FakeSystem(slow).attach(c)
    with pytest.raises(h.RetryAfterError):
        drain(c.pull(CONFIG, SECRETS, "parties", None))


@settings(max_examples=30, deadline=None)
@given(secret=st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=30),
       refresh=st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=30))
def test_secrets_never_leak_even_if_zoho_echoes_them(secret: str, refresh: str) -> None:
    creds = {"client_id": "1000.CID", "client_secret": secret, "refresh_token": refresh}
    echo = f"bad request for {secret} using {refresh} and AT-1"
    zoho = FakeZoho({"/contacts": json_reply({"code": 2, "message": echo}, 200),
                     "/organizations": json_reply({"code": 2, "message": echo}, 200)},
                    token_replies=[OK_TOKEN])
    c = zoho.connector()
    message = c.check(CONFIG, creds).message
    assert secret not in message and refresh not in message and "AT-1" not in message
    with pytest.raises(ConnectorError) as info:
        drain(c.pull(CONFIG, creds, "parties", None))
    assert secret not in str(info.value) and refresh not in str(info.value) and "AT-1" not in str(info.value)
    refused = FakeZoho(token_replies=[{"error": f"invalid {secret} {refresh}"}]).connector()
    assert secret not in refused.check(CONFIG, creds).message and refresh not in refused.check(CONFIG, creds).message

"""Zoho Books connector: OAuth2 (authorization code, refresh token) and the Books REST API v3, read only.

Written from Zoho's published documentation; **not yet run against a real Zoho Books organisation**.

Zoho limits what an app may read: a per-minute limit per organisation and a daily limit that depends on the
business's Zoho plan. This connector paces itself (`requests_per_minute`, default 60), honours `Retry-After`, stops
a run early when it has used `max_requests_per_run` requests (the next run carries on from the saved cursor), and
reads line items and payment links one by one only when `fetch_details` is on (it costs one request per document).
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from ziira.modules.connect.connectors import _http as h
from ziira.modules.connect.public import (
    CanonicalBatch,
    ConfigField,
    ConnectionCheck,
    Connector,
    ConnectorError,
    Expense,
    Invoice,
    JournalEntry,
    JournalLine,
    Party,
    Payment,
    Product,
    Record,
    Sale,
    SaleLine,
    SalePayment,
    User,
)
from ziira.sdk import provides

log = logging.getLogger("ziira.connect.zoho")

SYSTEM = "Zoho Books"
PAGE = 200
Row = dict[str, Any]

# Zoho runs separate data centres; a business's account lives in exactly one. This is data, not logic.
DATA_CENTRES: dict[str, dict[str, str]] = {
    "com": {"label": "United States (zoho.com)", "accounts": "https://accounts.zoho.com",
            "api": "https://www.zohoapis.com"},
    "eu": {"label": "Europe (zoho.eu)", "accounts": "https://accounts.zoho.eu", "api": "https://www.zohoapis.eu"},
    "in": {"label": "India (zoho.in)", "accounts": "https://accounts.zoho.in", "api": "https://www.zohoapis.in"},
    "com.au": {"label": "Australia (zoho.com.au)", "accounts": "https://accounts.zoho.com.au",
               "api": "https://www.zohoapis.com.au"},
    "jp": {"label": "Japan (zoho.jp)", "accounts": "https://accounts.zoho.jp", "api": "https://www.zohoapis.jp"},
    "ca": {"label": "Canada (zohocloud.ca)", "accounts": "https://accounts.zohocloud.ca",
           "api": "https://www.zohoapis.ca"},
    "sa": {"label": "Saudi Arabia (zoho.sa)", "accounts": "https://accounts.zoho.sa", "api": "https://www.zohoapis.sa"},
    "cn": {"label": "China (zoho.com.cn)", "accounts": "https://accounts.zoho.com.cn",
           "api": "https://www.zohoapis.com.cn"},
}
SCOPES = ("ZohoBooks.contacts.READ", "ZohoBooks.settings.READ", "ZohoBooks.invoices.READ",
          "ZohoBooks.customerpayments.READ", "ZohoBooks.bills.READ", "ZohoBooks.vendorpayments.READ",
          "ZohoBooks.expenses.READ", "ZohoBooks.accountants.READ")
# Zoho error codes in a 200/4xx body that mean "slow down" (per-minute, daily) and "not allowed".
_THROTTLE_CODES = (44, 45)
_DENIED_CODES = (36, 57)


@dataclass
class _Ctx:
    client: httpx.Client
    api: str
    accounts: str
    org: str
    config: dict[str, Any]
    secrets: dict[str, Any]
    pacer: h.Pacer
    token: str | None = None
    refreshes: int = 0

    @property
    def secret_values(self) -> tuple[object, ...]:
        return (self.secrets.get("client_secret"), self.secrets.get("refresh_token"), self.token)


@dataclass
class _Source:
    key: str
    path: str
    list_key: str
    build: Callable[["ZohoBooksConnector", "_DetailCtx", list[Row]], list[Record]]
    incremental: bool = True
    skip_status: tuple[str, ...] = ()
    detail: bool = False                               # needs a request per document (when fetch_details is on)


class _OutOfBudget(Exception):
    """This run has used its allowance of requests."""


def data_centre_urls(code: object) -> dict[str, str]:
    key = str(code or "com").strip().lower().removeprefix("zoho.")
    if key not in DATA_CENTRES:
        raise ConnectorError(f"'{code}' is not a Zoho data centre we know ({', '.join(DATA_CENTRES)}). It is the "
                             "ending of the web address you sign in to Zoho at, for example eu for zoho.eu.",
                             retryable=False)
    return DATA_CENTRES[key]


@provides("connect.connector")
class ZohoBooksConnector(Connector):
    kind = "zoho_books"
    title = "Zoho Books"
    description = ("Reads invoices, bills, payments, expenses, journals, contacts and items from your Zoho Books "
                   "organisation after you approve Ziira with one click. Read-only; nothing is written back.")
    entities = ("parties", "products", "users", "sales", "payments", "invoices", "expenses", "journal_entries")
    config_fields = (
        ConfigField("data_centre", "Zoho data centre", example="com",
                    help="The ending of the address you sign in to Zoho at: com, eu, in, com.au, jp, ca, sa or cn."),
        ConfigField("organization_id", "Organisation id", required=False,
                    help="Filled in for you when you approve; see Zoho Books > Settings > Organization Profile."),
        ConfigField("client_id", "Client id", secret=True, required=False,
                    help="Only if you registered your own Zoho API client (the platform may supply one)."),
        ConfigField("client_secret", "Client secret", secret=True, required=False),
        ConfigField("fetch_details", "Read line items and payment links", required=False, example="yes",
                    help="yes or no. Yes gives item-level checks but uses one Zoho request per document."),
        ConfigField("requests_per_minute", "Requests per minute", required=False, example="60",
                    help="Zoho allows about 100 a minute per organisation; we stay well under."),
        ConfigField("max_requests_per_run", "Requests per run", required=False, example="500",
                    help="Zoho's daily allowance depends on your plan; a run stops here and carries on next time."),
    )
    needs_oauth = True
    freshness = "daily"
    how_to = (
        "1. Choose 'Connect Zoho Books' and pick the data centre your Zoho account is in (the ending of the address "
        "you sign in at, for example zoho.eu is eu).\n"
        "2. Zoho shows what Ziira asks to read. Every permission is read-only; none allows changes. Click Accept.\n"
        "3. Pick the organisation to connect if you have several.\n"
        "4. To withdraw access later: in Zoho go to your profile > Sessions / Connected Apps and remove Ziira, or "
        "in the Zoho API console delete the client. Access stops at once.\n"
        "For a more careful setup, approve while signed in as a Zoho user whose role is read-only (for example a "
        "custom role with View permission only): the app can never read more than that user can.")

    def __init__(self) -> None:
        self.notes: list[str] = []
        self.sleep: Callable[[float], None] | None = None          # tests replace it so nothing waits

    # ------------------------------------------------------------------ OAuth
    @staticmethod
    def authorization_url(*, data_centre: str, client_id: str, redirect_uri: str, state: str) -> str:
        urls = data_centre_urls(data_centre)
        query = urlencode({"scope": ",".join(SCOPES), "client_id": client_id, "response_type": "code",
                           "access_type": "offline", "prompt": "consent", "redirect_uri": redirect_uri,
                           "state": state})
        return f"{urls['accounts']}/oauth/v2/auth?{query}"

    def exchange_code(self, *, data_centre: str, client_id: str, client_secret: str, code: str,
                      redirect_uri: str) -> h.OAuthResult:
        """Trade the one-time code for a refresh token, and find the organisation."""
        urls = data_centre_urls(data_centre)
        with self.client() as client:
            try:
                response = client.post(f"{urls['accounts']}/oauth/v2/token", data={
                    "grant_type": "authorization_code", "code": code, "client_id": client_id,
                    "client_secret": client_secret, "redirect_uri": redirect_uri})
            except httpx.HTTPError as exc:
                raise h.transport_error(exc, system=SYSTEM) from None
            body = self._token_body(response, (client_secret, code))
            refresh = str(body.get("refresh_token") or "")
            if not refresh:
                raise ConnectorError("Zoho did not give long-lived access. Try connecting again.", retryable=False)
            secrets = {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh}
            config: dict[str, Any] = {"data_centre": data_centre}
            ctx = _Ctx(client, urls["api"], urls["accounts"], "", config, secrets, h.Pacer(60))
            ctx.token = str(body.get("access_token") or "")
            orgs = self._organizations(ctx)
            default = next((o for o in orgs if o.get("is_default_org")), None)
            chosen = orgs[0] if len(orgs) == 1 else default
            if chosen is not None:
                config["organization_id"] = str(chosen.get("organization_id"))
                config["organization_name"] = str(chosen.get("name") or "")
            config["organizations"] = [{"id": str(o.get("organization_id")), "name": str(o.get("name") or "")}
                                       for o in orgs]
            return h.OAuthResult(secrets, config)

    # ------------------------------------------------------------------ tokens and requests
    def _token_body(self, response: httpx.Response, secrets: tuple[object, ...]) -> dict[str, Any]:
        """Zoho reports a refused token request with HTTP 200 and an `error` field."""
        if response.status_code >= 500 or response.status_code == 429:
            h.raise_for_status(response, system=SYSTEM, secrets=secrets)
        body = h.json_body(response, system=SYSTEM)
        if not isinstance(body, dict):
            raise ConnectorError("Zoho replied in an unexpected way.", retryable=True)
        error = str(body.get("error") or "")
        if error:
            if "too many" in error.lower() or "too_many" in error.lower():
                raise h.RetryAfterError("Zoho is limiting how often we may sign in. We will try again later.")
            raise ConnectorError(
                "Zoho no longer accepts the saved approval for Ziira (it may have been withdrawn, or the client "
                f"details are wrong). Connect again. ({h.scrub(error, secrets)})", retryable=False)
        return body

    def _refresh(self, ctx: _Ctx) -> None:
        secrets = ctx.secrets
        if not secrets.get("refresh_token") or not secrets.get("client_id") or not secrets.get("client_secret"):
            raise ConnectorError("The Zoho approval is incomplete. Connect Zoho Books again.", retryable=False)
        ctx.refreshes += 1
        if ctx.refreshes > 3:
            raise ConnectorError("Zoho keeps refusing the access token. Connect Zoho Books again.", retryable=False)
        try:
            response = ctx.client.post(f"{ctx.accounts}/oauth/v2/token", data={
                "grant_type": "refresh_token", "refresh_token": secrets["refresh_token"],
                "client_id": secrets["client_id"], "client_secret": secrets["client_secret"]})
        except httpx.HTTPError as exc:
            raise h.transport_error(exc, system=SYSTEM) from None
        body = self._token_body(response, ctx.secret_values)
        ctx.token = str(body.get("access_token") or "")
        if not ctx.token:
            raise ConnectorError("Zoho did not give an access token.", retryable=True)

    def _organizations(self, ctx: _Ctx) -> list[Row]:
        body = self._api(ctx, "/organizations", {}, with_org=False)
        return [o for o in body.get("organizations") or [] if isinstance(o, dict)]

    def _api(self, ctx: _Ctx, path: str, params: dict[str, Any], with_org: bool = True) -> Row:
        """One GET with pacing, a single token refresh on expiry, one polite retry after a throttle."""
        throttled = False
        while True:
            if ctx.pacer.exhausted:
                raise _OutOfBudget
            if ctx.token is None:
                self._refresh(ctx)
            ctx.pacer.wait()
            query = dict(params)
            if with_org:
                query["organization_id"] = ctx.org
            try:
                response = ctx.client.get(f"{ctx.api}/books/v3{path}", params=query,
                                          headers={"Authorization": f"Zoho-oauthtoken {ctx.token}"})
            except httpx.HTTPError as exc:
                raise h.transport_error(exc, system=SYSTEM) from None
            body: Row = {}
            if response.status_code < 500:
                try:
                    parsed = response.json()
                    body = parsed if isinstance(parsed, dict) else {}
                except ValueError:
                    body = {}
            code = body.get("code")
            if response.status_code == 401 or code == 14:               # access token expired: get a fresh one
                ctx.token = None
                if ctx.refreshes >= 3:
                    raise ConnectorError("Zoho no longer accepts Ziira's access. Connect Zoho Books again.",
                                         retryable=False)
                continue
            if response.status_code == 429 or code in _THROTTLE_CODES:
                if throttled:
                    raise h.RetryAfterError(
                        "Zoho says we have used up our allowance of requests (per minute or per day). "
                        "We will carry on later.", retry_after=h.retry_after_seconds(response))
                throttled = True
                ctx.pacer.back_off(h.retry_after_seconds(response))
                continue
            if code in _DENIED_CODES or response.status_code == 403:
                raise ConnectorError("Zoho accepted the approval but the user is not allowed to read this. Approve "
                                     "again as a user who can view it.", retryable=False)
            h.raise_for_status(response, system=SYSTEM, secrets=ctx.secret_values, what="this part of Zoho Books")
            if not body:
                raise ConnectorError("Zoho replied with something that is not data.", retryable=True)
            if code not in (0, None):
                problem = h.scrub(str(body.get("message") or code), ctx.secret_values)
                raise ConnectorError(f"Zoho Books reported a problem: {problem}", retryable=False)
            return body

    # ------------------------------------------------------------------ check
    def _context(self, client: httpx.Client, config: dict[str, Any], secrets: dict[str, Any],
                 require_org: bool = True) -> _Ctx:
        urls = data_centre_urls(config.get("data_centre"))
        org = str(config.get("organization_id") or "").strip()
        if require_org and not org:
            raise ConnectorError("No Zoho Books organisation has been chosen yet. Connect Zoho Books again and pick "
                                 "one.", retryable=False)
        try:
            per_minute = max(1, min(int(str(config.get("requests_per_minute") or 60)), 90))
            budget = max(1, int(str(config.get("max_requests_per_run") or 500)))
        except ValueError:
            raise ConnectorError("The request limits must be whole numbers.", retryable=False) from None
        pacer = h.Pacer(per_minute, budget=budget)
        if self.sleep is not None:
            pacer = h.Pacer(per_minute, budget=budget, sleep=self.sleep)
        return _Ctx(client, urls["api"], urls["accounts"], org, config, secrets, pacer)

    def check(self, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectionCheck:
        try:
            with self.client() as client:
                ctx = self._context(client, config, secrets, require_org=False)
                orgs = self._organizations(ctx)
                if not orgs:
                    return ConnectionCheck(False, "Zoho accepted the approval but shows no Zoho Books organisation.")
                names = {str(o.get("organization_id")): str(o.get("name") or "") for o in orgs}
                if not ctx.org:
                    listing = ", ".join(f"{n} ({i})" for i, n in names.items())
                    return ConnectionCheck(False, f"Choose which organisation to read: {listing}.")
                if ctx.org not in names:
                    return ConnectionCheck(False, "That organisation id is not one this approval can reach.")
                return ConnectionCheck(True, f"Connected to Zoho Books: {names[ctx.org]}.",
                                       {"system": SYSTEM, "organization": names[ctx.org]})
        except _OutOfBudget:
            return ConnectionCheck(False, "Zoho request allowance used up for now.")
        except ConnectorError as exc:
            return ConnectionCheck(False, str(exc))
        except httpx.HTTPError as exc:
            return ConnectionCheck(False, str(h.transport_error(exc, system=SYSTEM)))

    # ------------------------------------------------------------------ streaming
    def pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
             limit: int | None = None) -> Iterator[CanonicalBatch]:
        if entity not in self.entities:
            raise ConnectorError(f"Zoho Books connector cannot read '{entity}'.", retryable=False)
        self.notes = []
        return self._pull(config, secrets, entity, since, limit)

    def _pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
              limit: int | None) -> Iterator[CanonicalBatch]:
        stopped = {"early": False}
        details = str(config.get("fetch_details", "yes")).strip().lower() not in ("no", "false", "0", "off")
        with self.client() as client:
            ctx = self._context(client, config, secrets)
            parts = self._parts(ctx, self._sources(entity), since, limit, stopped, details)
            yield from h.seal(entity, parts, since, lambda: stopped["early"])

    def _parts(self, ctx: _Ctx, sources: list[_Source], since: str | None, limit: int | None,
               stopped: dict[str, bool], details: bool) -> Iterator[tuple[tuple[Record, ...], str | None]]:
        cursor = h.decode_cursor(since)
        seen = 0
        for source in sources:
            start = h.parse_cursor_time(cursor.get(source.key)) if source.incremental else None
            params: dict[str, Any] = {"per_page": PAGE, "sort_order": "A"}
            if source.incremental:
                params["sort_column"] = "last_modified_time"
            if start is not None:
                params["last_modified_time"] = start.strftime("%Y-%m-%dT%H:%M:%S+0000")
            page = 1
            newest: datetime | None = None
            while True:
                try:
                    body = self._api(ctx, source.path, {**params, "page": page})
                    rows = [r for r in body.get(source.list_key) or [] if isinstance(r, dict)]
                    # Zoho may ignore the time filter on some lists: never rely on it alone.
                    if start is not None:
                        rows = [r for r in rows if (h.parse_dt(r.get("last_modified_time")) or start) >= start]
                    keep = [r for r in rows if str(r.get("status") or "") not in source.skip_status]
                    if source.detail and details and ctx.pacer.budget is not None and \
                            ctx.pacer.budget - ctx.pacer.used < len(keep):
                        raise _OutOfBudget                # not enough allowance to finish this page properly
                    records = source.build(self, _DetailCtx(ctx, details), keep) if keep else []
                except _OutOfBudget:
                    stopped["early"] = True
                    self.notes.append("Stopped early to stay within the Zoho request allowance; "
                                      "the next run carries on.")
                    return
                for row in rows:
                    moment = h.parse_dt(row.get("last_modified_time"))
                    if moment is not None and (newest is None or moment > newest):
                        newest = moment
                if newest is not None and source.incremental:
                    cursor[source.key] = h.cursor_time(newest)
                if rows or body.get(source.list_key):
                    yield tuple(records), h.encode_cursor(cursor) if source.incremental else None
                seen += len(rows)
                context = body.get("page_context") or {}
                if limit is not None and seen >= limit:
                    stopped["early"] = True
                    return
                if not (isinstance(context, dict) and context.get("has_more_page")):
                    break
                page += 1

    # ------------------------------------------------------------------ what each entity reads
    def _sources(self, entity: str) -> list[_Source]:
        sources: dict[str, list[_Source]] = {
            "parties": [_Source("contacts", "/contacts", "contacts", _contacts)],
            "products": [_Source("items", "/items", "items", _items)],
            "users": [_Source("users", "/users", "users", _users, incremental=False)],
            "sales": [_Source("invoices", "/invoices", "invoices", _sales, skip_status=("draft",), detail=True)],
            "invoices": [_Source("invoices", "/invoices", "invoices", _invoices("customer"), skip_status=("draft",)),
                         _Source("bills", "/bills", "bills", _invoices("supplier"), skip_status=("draft",))],
            "payments": [_Source("customerpayments", "/customerpayments", "customerpayments", _payments("in"),
                                 detail=True),
                         _Source("vendorpayments", "/vendorpayments", "vendorpayments", _payments("out"),
                                 detail=True)],
            "expenses": [_Source("expenses", "/expenses", "expenses", _expenses)],
            "journal_entries": [_Source("journals", "/journals", "journals", _journals, detail=True)],
        }
        return sources[entity]


@dataclass
class _DetailCtx:
    """What a mapper needs: the context and whether to read each document."""

    ctx: _Ctx
    details: bool

    def detail(self, connector: "ZohoBooksConnector", path: str, key: str) -> Row:
        if not self.details:
            return {}
        body = connector._api(self.ctx, path, {})
        value = body.get(key)
        return value if isinstance(value, dict) else {}


# --------------------------------------------------------------------------- mappers
def _created(r: Row) -> datetime | None:
    return h.parse_dt(r.get("created_time"))


def _aware(value: object) -> datetime | None:
    """A Zoho time keeping the offset it was written with (e.g. '2024-05-03T14:22:10+0300')."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _when(r: Row, date_key: str = "date") -> datetime | None:
    """A document's date as an instant: midnight on that date at the offset Zoho used for its creation time."""
    day = h.parse_date(r.get(date_key))
    if day is None:
        return None
    created = _aware(r.get("created_time")) or _aware(r.get("last_modified_time"))
    zone = created.tzinfo if created else UTC
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)


def _contacts(c: ZohoBooksConnector, d: _DetailCtx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        kind: Literal["customer", "supplier"] = "supplier" if r.get("contact_type") == "vendor" else "customer"
        out.append(Party(
            ref=str(r["contact_id"]), kind=kind,
            name=h.text_or_none(r.get("contact_name")) or h.text_or_none(r.get("company_name")) or str(r["contact_id"]),
            phone=h.text_or_none(r.get("mobile")) or h.text_or_none(r.get("phone")),
            email=h.text_or_none(r.get("email")),
            tax_id=h.text_or_none(r.get("tax_id")) or h.text_or_none(r.get("gst_no")), created_at=_created(r)))
    return out


def _items(c: ZohoBooksConnector, d: _DetailCtx, rows: list[Row]) -> list[Record]:
    return [Product(ref=str(r["item_id"]), name=h.text_or_none(r.get("name")) or str(r["item_id"]),
                    sku=h.text_or_none(r.get("sku")), category=h.text_or_none(r.get("category_name")),
                    unit_cost=h.dec_or_none(r.get("purchase_rate")), unit_price=h.dec_or_none(r.get("rate")))
            for r in rows]


def _users(c: ZohoBooksConnector, d: _DetailCtx, rows: list[Row]) -> list[Record]:
    return [User(ref=str(r["user_id"]), name=h.text_or_none(r.get("name")) or str(r["user_id"]),
                 role=h.text_or_none(r.get("user_role")) or h.text_or_none(r.get("role_name")),
                 email=h.text_or_none(r.get("email")), created_at=_created(r)) for r in rows]


def _line_discount(line: Row, quantity: Decimal, rate: Decimal) -> Decimal:
    """Money off a line. Zoho gives `discount_amount` when it computed one; `discount` may be '10%' or a number."""
    if line.get("discount_amount") not in (None, ""):
        return h.dec(line.get("discount_amount"))
    raw = str(line.get("discount") or "").strip()
    if raw.endswith("%"):
        return abs(quantity) * rate * h.dec(raw[:-1]) / 100
    return h.dec(raw)


def _sales(c: ZohoBooksConnector, d: _DetailCtx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        occurred = _when(r)
        if occurred is None:
            continue
        detail = d.detail(c, f"/invoices/{r['invoice_id']}", "invoice") if r.get("status") != "void" else {}
        lines: list[SaleLine] = []
        for ln in detail.get("line_items") or []:
            if not isinstance(ln, dict):
                continue
            qty, rate = h.dec(ln.get("quantity")), h.dec(ln.get("rate"))
            discount = _line_discount(ln, qty, rate)
            lines.append(SaleLine(product_ref=h.text_or_none(ln.get("item_id")), quantity=qty,
                                  unit_price=rate - (discount / abs(qty) if qty else Decimal(0)), discount=discount,
                                  list_price=rate if discount else None))
        payments = [SalePayment(h.payment_method(p.get("payment_mode")), h.dec(p.get("amount")),
                                h.text_or_none(p.get("reference_number")))
                    for p in detail.get("payments") or [] if isinstance(p, dict)]
        balance = h.dec(r.get("balance"))
        if balance > 0 and r.get("status") != "void":
            payments.append(SalePayment("credit", balance))
        out.append(Sale(
            ref=str(r["invoice_id"]), occurred_at=occurred, total=h.dec(r.get("total")),
            status="voided" if r.get("status") == "void" else "posted", number=h.text_or_none(r.get("invoice_number")),
            customer_ref=h.text_or_none(r.get("customer_id")), tax_total=h.dec(detail.get("tax_total")),
            discount_total=sum((ln.discount for ln in lines), Decimal(0)),
            currency=h.text_or_none(r.get("currency_code")),
            cashier_ref=h.text_or_none(detail.get("created_by_id")), lines=tuple(lines), payments=tuple(payments),
            entered_at=_created(r)))
    return out


Builder = Callable[[ZohoBooksConnector, _DetailCtx, list[Row]], list[Record]]


def _invoices(kind: Literal["customer", "supplier"]) -> Builder:
    id_key, number_key, party_key = (("invoice_id", "invoice_number", "customer_id") if kind == "customer"
                                     else ("bill_id", "bill_number", "vendor_id"))

    def build(c: ZohoBooksConnector, d: _DetailCtx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        for r in rows:
            issued = h.parse_date(r.get("date"))
            if issued is None:
                continue
            total, balance = h.dec(r.get("total")), h.dec(r.get("balance"))
            void = r.get("status") == "void"
            out.append(Invoice(
                ref=str(r[id_key]), kind=kind, issue_date=issued, total=total,
                paid=Decimal(0) if void else total - balance, due_date=h.parse_date(r.get("due_date")),
                number=h.text_or_none(r.get(number_key)), party_ref=h.text_or_none(r.get(party_key)),
                status="cancelled" if void else ("paid" if balance <= 0 else "open"),
                currency=h.text_or_none(r.get("currency_code"))))
        return out

    return build


def _payments(direction: Literal["in", "out"]) -> Builder:
    party_key, name_key, list_key = (("customer_id", "customer_name", "invoices") if direction == "in"
                                     else ("vendor_id", "vendor_name", "bills"))
    detail_path, detail_key = (("customerpayments", "payment") if direction == "in" else ("vendorpayments", "payment"))
    id_key = "invoice_id" if direction == "in" else "bill_id"

    def build(c: ZohoBooksConnector, d: _DetailCtx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        for r in rows:
            occurred = _when(r)
            if occurred is None:
                continue
            detail = d.detail(c, f"/{detail_path}/{r['payment_id']}", detail_key)
            applied = [x for x in detail.get(list_key) or [] if isinstance(x, dict) and x.get(id_key)]
            out.append(Payment(
                ref=str(r["payment_id"]), occurred_at=occurred, direction=direction, amount=h.dec(r.get("amount")),
                method=h.payment_method(r.get("payment_mode")), reference=h.text_or_none(r.get("reference_number")),
                party_ref=h.text_or_none(r.get(party_key)), party_name=h.text_or_none(r.get(name_key)),
                account=h.text_or_none(r.get("account_name")) or h.text_or_none(r.get("paid_through_account_name")),
                invoice_ref=str(applied[0][id_key]) if applied else None,
                currency=h.text_or_none(r.get("currency_code"))))
        return out

    return build


def _expenses(c: ZohoBooksConnector, d: _DetailCtx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        occurred = _when(r)
        if occurred is None:
            continue
        out.append(Expense(
            ref=str(r["expense_id"]), occurred_at=occurred, amount=h.dec(r.get("total") if r.get("total") is not None
                                                                         else r.get("amount")),
            category=h.text_or_none(r.get("account_name")), description=h.text_or_none(r.get("description")),
            party_ref=h.text_or_none(r.get("vendor_id"))))
    return out


def _journals(c: ZohoBooksConnector, d: _DetailCtx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        day = h.parse_date(r.get("journal_date"))
        if day is None:
            continue
        detail = d.detail(c, f"/journals/{r['journal_id']}", "journal")
        lines = tuple(JournalLine(
            account=h.text_or_none(x.get("account_name")) or h.text_or_none(x.get("account_id")) or "unknown",
            debit=h.dec(x.get("amount")) if x.get("debit_or_credit") == "debit" else Decimal(0),
            credit=h.dec(x.get("amount")) if x.get("debit_or_credit") == "credit" else Decimal(0),
            party_ref=h.text_or_none(x.get("customer_id")) or h.text_or_none(x.get("vendor_id")))
            for x in detail.get("line_items") or [] if isinstance(x, dict))
        out.append(JournalEntry(
            ref=str(r["journal_id"]), entry_date=day, lines=lines,
            number=h.text_or_none(r.get("entry_number")) or h.text_or_none(r.get("journal_number")),
            entered_at=_created(r), created_by_ref=h.text_or_none(detail.get("created_by_id")),
            memo=h.text_or_none(r.get("notes")) or h.text_or_none(r.get("reference_number")), is_manual=True))
    return out


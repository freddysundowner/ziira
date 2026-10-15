"""QuickBooks Online connector: OAuth2 with Intuit and the accounting Query API, read only.

Written from Intuit's published documentation; **not yet run against a real QuickBooks company** (use a sandbox
company first: docs/connectors.md).

Intuit's OAuth scope for accounting (`com.intuit.quickbooks.accounting`) is read AND write: there is no read-only scope.
Ziira's read-only promise is kept by this connector sending only `GET` queries (and the token request), and the
business can withdraw access at any time from Intuit.

Refresh tokens ROTATE: every refresh may return a new refresh token and the old one stops working after a grace period.
The connector puts the newest one in `self.updated_secrets`; whoever runs the connector MUST save it over the stored
secrets (also when a pull then fails), or the next run will find the connection expired.
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
    Branch,
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

log = logging.getLogger("ziira.connect.quickbooks")

SYSTEM = "QuickBooks Online"
PAGE = 500                                  # Intuit allows up to 1000 per query page
MINOR_VERSION = "75"
AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE = "com.intuit.quickbooks.accounting"
# Production and sandbox are different servers; which one a connection uses is data the business chooses.
API_BASES = {"production": "https://quickbooks.api.intuit.com", "sandbox": "https://sandbox-quickbooks.api.intuit.com"}
Row = dict[str, Any]


@dataclass
class _Ctx:
    client: httpx.Client
    base: str
    realm: str
    token: str
    pacer: h.Pacer
    secrets: tuple[object, ...]
    _cache: dict[str, Any]
    fetch: Callable[[str], Row] | None = None            # run a query statement (set once signed in)


@dataclass
class _Source:
    key: str                                           # the QuickBooks entity name, also the cursor key
    build: Callable[["_Ctx", list[Row]], list[Record]]
    where: str = ""                                    # extra condition, e.g. "Active IN (true, false)"


def _ref(entity: str, row: Row) -> str:
    return f"{entity.lower()}:{row['Id']}"


def _name(value: object) -> str | None:
    return h.text_or_none(value.get("name")) if isinstance(value, dict) else None


def _value(value: object) -> str | None:
    return h.text_or_none(value.get("value")) if isinstance(value, dict) else None


def _meta(row: Row, key: str) -> datetime | None:
    meta = row.get("MetaData")
    return h.parse_dt(meta.get(key)) if isinstance(meta, dict) else None


def _tx_moment(row: Row) -> datetime | None:
    """TxnDate is a calendar date; give it the offset QuickBooks used when the record was created."""
    day = h.parse_date(row.get("TxnDate"))
    if day is None:
        return None
    raw = str((row.get("MetaData") or {}).get("CreateTime") or "")
    zone = UTC
    if len(raw) > 19:
        try:
            parsed = datetime.fromisoformat(raw)
            zone = parsed.tzinfo or UTC                       # type: ignore[assignment]
        except ValueError:
            pass
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)


@provides("connect.connector")
class QuickBooksConnector(Connector):
    kind = "quickbooks"
    title = "QuickBooks Online"
    description = ("Reads customers, vendors, items, sales, bills, payments, expenses and journal entries from your "
                   "QuickBooks Online company after you approve Ziira. Read-only; nothing is written back.")
    entities = ("branches", "parties", "products", "users", "sales", "payments", "invoices", "expenses",
                "journal_entries")
    config_fields = (
        ConfigField("environment", "Environment", example="production",
                    help="production for your real company; sandbox only for a test company from Intuit."),
        ConfigField("realm_id", "Company id (realm)", required=False,
                    help="Filled in for you when you approve; also shown in QuickBooks under Account and settings."),
        ConfigField("client_id", "Client id", secret=True, required=False,
                    help="Only if you registered your own Intuit app (the platform may supply one)."),
        ConfigField("client_secret", "Client secret", secret=True, required=False),
    )
    needs_oauth = True
    freshness = "daily"
    how_to = (
        "1. Choose 'Connect QuickBooks Online'. You are sent to Intuit to sign in.\n"
        "2. Sign in as a QuickBooks user who may view the company (a user with reports-only or view-only access is "
        "best: Ziira can never read more than that user can) and choose the company.\n"
        "3. Intuit shows what Ziira asks for and you click Connect. Intuit's permission wording covers reading and "
        "writing accounting data because Intuit offers no read-only choice; Ziira only reads.\n"
        "4. To withdraw access later: in QuickBooks open Apps > My Apps, find Ziira and choose Disconnect, or "
        "disconnect it from the Intuit developer dashboard. Access stops at once.\n"
        "Note: Intuit charges apps for reading data above a free monthly allowance; Ziira reads only what changed.")

    def __init__(self) -> None:
        self.notes: list[str] = []
        self.updated_secrets = None
        self.sleep: Callable[[float], None] | None = None

    # ------------------------------------------------------------------ OAuth
    @staticmethod
    def authorization_url(*, client_id: str, redirect_uri: str, state: str, **_ignored: object) -> str:
        query = urlencode({"client_id": client_id, "response_type": "code", "scope": SCOPE,
                           "redirect_uri": redirect_uri, "state": state})
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, *, client_id: str, client_secret: str, code: str, redirect_uri: str, realm_id: str,
                      environment: str = "production") -> h.OAuthResult:
        if environment not in API_BASES:
            raise ConnectorError("The environment must be production or sandbox.", retryable=False)
        if not realm_id.strip().isdigit():
            raise ConnectorError("Intuit did not say which company was approved. Try connecting again.",
                                 retryable=False)
        with self.client() as client:
            body = self._token_request(client, client_id, client_secret,
                                       {"grant_type": "authorization_code", "code": code,
                                        "redirect_uri": redirect_uri}, (client_secret, code))
        refresh = str(body.get("refresh_token") or "")
        if not refresh:
            raise ConnectorError("Intuit did not give long-lived access. Try connecting again.", retryable=False)
        return h.OAuthResult({"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh},
                             {"environment": environment, "realm_id": realm_id.strip()})

    def _token_request(self, client: httpx.Client, client_id: str, client_secret: str, form: dict[str, str],
                       secrets: tuple[object, ...]) -> Row:
        try:
            response = client.post(TOKEN_URL, data=form, auth=(client_id, client_secret),
                                   headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise h.transport_error(exc, system=SYSTEM) from None
        if response.status_code in (400, 401):
            detail = h.scrub(h._error_text(response), secrets)
            raise ConnectorError("Intuit no longer accepts the saved approval for Ziira (it may have been "
                                 f"disconnected, expired after months of no use, or the app details are wrong). "
                                 f"Connect QuickBooks Online again. {detail}".strip(), retryable=False)
        h.raise_for_status(response, system=SYSTEM, secrets=secrets)
        body = h.json_body(response, system=SYSTEM)
        if not isinstance(body, dict) or not body.get("access_token"):
            raise ConnectorError("Intuit replied in an unexpected way.", retryable=True)
        return body

    def _sign_in(self, client: httpx.Client, config: dict[str, Any], secrets: dict[str, Any]) -> _Ctx:
        environment = str(config.get("environment") or "production")
        if environment not in API_BASES:
            raise ConnectorError("The environment must be production or sandbox.", retryable=False)
        realm = str(config.get("realm_id") or "").strip()
        if not realm.isdigit():
            raise ConnectorError("No QuickBooks company has been approved yet. Connect QuickBooks Online again.",
                                 retryable=False)
        client_id, client_secret, refresh = (str(secrets.get(k) or "") for k in
                                             ("client_id", "client_secret", "refresh_token"))
        if not (client_id and client_secret and refresh):
            raise ConnectorError("The QuickBooks approval is incomplete. Connect QuickBooks Online again.",
                                 retryable=False)
        self.updated_secrets = None
        body = self._token_request(client, client_id, client_secret,
                                   {"grant_type": "refresh_token", "refresh_token": refresh},
                                   (client_secret, refresh))
        rotated = str(body.get("refresh_token") or "")
        if rotated and rotated != refresh:
            self.updated_secrets = {"refresh_token": rotated}          # the old one is now on borrowed time
        token = str(body["access_token"])
        pacer = h.Pacer(300) if self.sleep is None else h.Pacer(300, sleep=self.sleep)
        ctx = _Ctx(client, API_BASES[environment], realm, token, pacer,
                   (client_secret, rotated or refresh, refresh, token), {})
        ctx.fetch = lambda statement: self._get(ctx, "/query", {"query": statement})
        return ctx

    # ------------------------------------------------------------------ requests
    def _get(self, ctx: _Ctx, path: str, params: dict[str, str]) -> Row:
        ctx.pacer.wait()
        try:
            response = ctx.client.get(f"{ctx.base}/v3/company/{ctx.realm}{path}",
                                      params={**params, "minorversion": MINOR_VERSION},
                                      headers={"Authorization": f"Bearer {ctx.token}", "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise h.transport_error(exc, system=SYSTEM) from None
        h.raise_for_status(response, system=SYSTEM, secrets=ctx.secrets, what="this part of QuickBooks")
        body = h.json_body(response, system=SYSTEM)
        if not isinstance(body, dict):
            raise ConnectorError("QuickBooks replied in an unexpected way.", retryable=True)
        fault = body.get("Fault")
        if fault:
            text = h.scrub(h._error_text(httpx.Response(200, json=body)), ctx.secrets)
            raise ConnectorError(f"QuickBooks reported a problem: {text}", retryable=False)
        return body

    def _query(self, ctx: _Ctx, entity: str, where: str, start: int) -> list[Row]:
        statement = (f"select * from {entity}{where} order by Metadata.LastUpdatedTime "
                     f"startposition {start} maxresults {PAGE}")
        body = self._get(ctx, "/query", {"query": statement})
        found = (body.get("QueryResponse") or {}).get(entity) or []
        return [r for r in found if isinstance(r, dict)]

    # ------------------------------------------------------------------ check
    def check(self, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectionCheck:
        try:
            with self.client() as client:
                ctx = self._sign_in(client, config, secrets)
                info = self._get(ctx, f"/companyinfo/{ctx.realm}", {}).get("CompanyInfo") or {}
                name = h.text_or_none(info.get("CompanyName")) or "your company"
                return ConnectionCheck(True, f"Connected to QuickBooks Online: {name}.",
                                       {"system": SYSTEM, "company": name,
                                        "environment": str(config.get("environment") or "production")})
        except ConnectorError as exc:
            return ConnectionCheck(False, str(exc))
        except httpx.HTTPError as exc:
            return ConnectionCheck(False, str(h.transport_error(exc, system=SYSTEM)))

    # ------------------------------------------------------------------ streaming
    def pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
             limit: int | None = None) -> Iterator[CanonicalBatch]:
        if entity not in self.entities:
            raise ConnectorError(f"QuickBooks connector cannot read '{entity}'.", retryable=False)
        self.notes = []
        return self._pull(config, secrets, entity, since, limit)

    def _pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
              limit: int | None) -> Iterator[CanonicalBatch]:
        stopped = {"early": False}
        with self.client() as client:
            ctx = self._sign_in(client, config, secrets)
            parts = self._parts(ctx, self._sources(entity), since, limit, stopped)
            yield from h.seal(entity, parts, since, lambda: stopped["early"])

    def _parts(self, ctx: _Ctx, sources: list[_Source], since: str | None, limit: int | None,
               stopped: dict[str, bool]) -> Iterator[tuple[tuple[Record, ...], str | None]]:
        cursor = h.decode_cursor(since)
        seen = 0
        for source in sources:
            start = h.parse_cursor_time(cursor.get(source.key))
            conditions = [source.where] if source.where else []
            if start is not None:
                stamp = start.strftime("%Y-%m-%dT%H:%M:%S+00:00")
                conditions.append(f"Metadata.LastUpdatedTime > '{stamp}'")
            where = f" where {' and '.join(conditions)}" if conditions else ""
            position = 1
            newest: datetime | None = None
            while True:
                rows = self._query(ctx, source.key, where, position)
                if not rows:
                    break
                records = source.build(ctx, rows)
                for row in rows:
                    moment = _meta(row, "LastUpdatedTime")
                    if moment is not None and (newest is None or moment > newest):
                        newest = moment
                if newest is not None:
                    cursor[source.key] = h.cursor_time(newest)
                yield tuple(records), h.encode_cursor(cursor)
                seen += len(rows)
                position += len(rows)
                if limit is not None and seen >= limit:
                    stopped["early"] = True
                    return
                if len(rows) < PAGE:
                    break

    # ------------------------------------------------------------------ what each entity reads
    def _sources(self, entity: str) -> list[_Source]:
        sources: dict[str, list[_Source]] = {
            "branches": [_Source("Department", _departments, "Active IN (true, false)")],
            "parties": [_Source("Customer", _customers, "Active IN (true, false)"),
                        _Source("Vendor", _vendors, "Active IN (true, false)")],
            "products": [_Source("Item", _items, "Active IN (true, false)")],
            "users": [_Source("Employee", _employees, "Active IN (true, false)")],
            "sales": [_Source("SalesReceipt", _sales("SalesReceipt")), _Source("Invoice", _sales("Invoice")),
                      _Source("CreditMemo", _sales("CreditMemo")), _Source("RefundReceipt", _sales("RefundReceipt"))],
            "invoices": [_Source("Invoice", _invoices("Invoice", "customer")),
                         _Source("Bill", _invoices("Bill", "supplier"))],
            "payments": [_Source("Payment", _payments("Payment")), _Source("BillPayment", _payments("BillPayment"))],
            "expenses": [_Source("Purchase", _expenses)],
            "journal_entries": [_Source("JournalEntry", _journals), _Source("Deposit", _deposits)],
        }
        return sources[entity]


# --------------------------------------------------------------------------- mappers
def _departments(ctx: _Ctx, rows: list[Row]) -> list[Record]:
    return [Branch(ref=str(r["Id"]), name=h.text_or_none(r.get("FullyQualifiedName"))
                   or h.text_or_none(r.get("Name")) or str(r["Id"])) for r in rows]


def _customers(ctx: _Ctx, rows: list[Row]) -> list[Record]:
    return [_party("customer", "Customer", r) for r in rows]


def _vendors(ctx: _Ctx, rows: list[Row]) -> list[Record]:
    return [_party("supplier", "Vendor", r) for r in rows]


def _party(kind: Literal["customer", "supplier"], entity: str, r: Row) -> Party:
    def get(*path: str) -> object:
        value: object = r
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        return value

    return Party(ref=_ref(entity, r), kind=kind,
                 name=h.text_or_none(r.get("DisplayName")) or h.text_or_none(r.get("CompanyName")) or str(r["Id"]),
                 phone=h.text_or_none(get("Mobile", "FreeFormNumber"))
                 or h.text_or_none(get("PrimaryPhone", "FreeFormNumber")),
                 email=h.text_or_none(get("PrimaryEmailAddr", "Address")),
                 tax_id=h.text_or_none(r.get("PrimaryTaxIdentifier")) or h.text_or_none(r.get("TaxIdentifier")),
                 created_at=_meta(r, "CreateTime"))


def _items(ctx: _Ctx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        if r.get("Type") == "Category":                      # a grouping of items, not something sold
            continue
        full = h.text_or_none(r.get("FullyQualifiedName")) or ""
        out.append(Product(ref=str(r["Id"]), name=h.text_or_none(r.get("Name")) or str(r["Id"]),
                           sku=h.text_or_none(r.get("Sku")),
                           category=full.rsplit(":", 1)[0] if ":" in full else h.text_or_none(r.get("Type")),
                           unit_cost=h.dec_or_none(r.get("PurchaseCost")),
                           unit_price=h.dec_or_none(r.get("UnitPrice"))))
    return out


def _employees(ctx: _Ctx, rows: list[Row]) -> list[Record]:
    return [User(ref=str(r["Id"]), name=h.text_or_none(r.get("DisplayName")) or str(r["Id"]),
                 role=None, email=h.text_or_none((r.get("PrimaryEmailAddr") or {}).get("Address")),
                 created_at=_meta(r, "CreateTime")) for r in rows]


def _is_void(r: Row) -> bool:
    """QuickBooks voids keep the record but zero the amount and write 'Voided' in the note."""
    return h.dec(r.get("TotalAmt")) == 0 and "void" in str(r.get("PrivateNote") or "").lower()


def _payment_method_names(ctx: _Ctx) -> dict[str, str]:
    """PaymentMethod id -> name (a short list), read once per pull."""
    if "methods" not in ctx._cache:
        names: dict[str, str] = {}
        assert ctx.fetch is not None
        body = ctx.fetch("select * from PaymentMethod maxresults 200")
        for m in (body.get("QueryResponse") or {}).get("PaymentMethod") or []:
            if isinstance(m, dict) and m.get("Id"):
                names[str(m["Id"])] = str(m.get("Name") or "")
        ctx._cache["methods"] = names
    result: dict[str, str] = ctx._cache["methods"]
    return result


def _sales(entity: str) -> Callable[[_Ctx, list[Row]], list[Record]]:
    negative = entity in ("CreditMemo", "RefundReceipt")

    def build(ctx: _Ctx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        sign = Decimal(-1) if negative else Decimal(1)
        for r in rows:
            occurred = _tx_moment(r)
            if occurred is None:
                continue
            lines: list[SaleLine] = []
            discount = Decimal(0)
            for ln in r.get("Line") or []:
                if not isinstance(ln, dict):
                    continue
                kind = ln.get("DetailType")
                if kind == "DiscountLineDetail":
                    discount += h.dec(ln.get("Amount"))
                elif kind in ("SalesItemLineDetail", "GroupLineDetail"):
                    detail = ln.get("SalesItemLineDetail") or {}
                    qty = h.dec(detail.get("Qty"), Decimal(1)) if detail.get("Qty") is not None else Decimal(1)
                    amount = h.dec(ln.get("Amount"))
                    price = h.dec(detail.get("UnitPrice")) if detail.get("UnitPrice") is not None else (
                        amount / qty if qty else Decimal(0))
                    lines.append(SaleLine(product_ref=_value(detail.get("ItemRef")), quantity=sign * qty,
                                          unit_price=price))
            total = h.dec(r.get("TotalAmt"))
            payments: list[SalePayment] = []
            balance = h.dec(r.get("Balance"))
            if entity in ("SalesReceipt", "RefundReceipt"):
                method = _payment_method_names(ctx).get(_value(r.get("PaymentMethodRef")) or "", "")
                if total:
                    payments.append(SalePayment(h.payment_method(method), sign * total,
                                                h.text_or_none(r.get("PaymentRefNum"))))
            elif entity == "Invoice" and balance > 0:
                payments.append(SalePayment("credit", balance))
            tax = (r.get("TxnTaxDetail") or {}).get("TotalTax")
            out.append(Sale(
                ref=_ref(entity, r), occurred_at=occurred, total=sign * total,
                status="voided" if _is_void(r) else ("refunded" if negative else "posted"),
                number=h.text_or_none(r.get("DocNumber")), branch_ref=_value(r.get("DepartmentRef")),
                customer_ref=f"customer:{_value(r.get('CustomerRef'))}" if _value(r.get("CustomerRef")) else None,
                tax_total=sign * h.dec(tax), discount_total=discount, currency=_value(r.get("CurrencyRef")),
                lines=tuple(lines), payments=tuple(payments), entered_at=_meta(r, "CreateTime")))
        return out

    return build


def _invoices(entity: str, kind: Literal["customer", "supplier"]) -> Callable[[_Ctx, list[Row]], list[Record]]:
    party_key, party_prefix = ("CustomerRef", "customer") if kind == "customer" else ("VendorRef", "vendor")

    def build(ctx: _Ctx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        for r in rows:
            issued = h.parse_date(r.get("TxnDate"))
            if issued is None:
                continue
            total, balance = h.dec(r.get("TotalAmt")), h.dec(r.get("Balance"))
            void = _is_void(r)
            party = _value(r.get(party_key))
            out.append(Invoice(
                ref=_ref(entity, r), kind=kind, issue_date=issued, total=total,
                paid=Decimal(0) if void else total - balance, due_date=h.parse_date(r.get("DueDate")),
                number=h.text_or_none(r.get("DocNumber")), party_ref=f"{party_prefix}:{party}" if party else None,
                status="cancelled" if void else ("paid" if balance == 0 else "open"),
                currency=_value(r.get("CurrencyRef"))))
        return out

    return build


def _payments(entity: str) -> Callable[[_Ctx, list[Row]], list[Record]]:
    inbound = entity == "Payment"

    def build(ctx: _Ctx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        names = _payment_method_names(ctx) if inbound else {}
        for r in rows:
            occurred = _tx_moment(r)
            if occurred is None:
                continue
            party = r.get("CustomerRef" if inbound else "VendorRef")
            party_id = _value(party)
            linked = [t for ln in r.get("Line") or [] if isinstance(ln, dict)
                      for t in ln.get("LinkedTxn") or [] if isinstance(t, dict)]
            target = next((t for t in linked if t.get("TxnType") == ("Invoice" if inbound else "Bill")), None)
            if inbound:
                method = h.payment_method(names.get(_value(r.get("PaymentMethodRef")) or "", ""))
                account = _name(r.get("DepositToAccountRef"))
            else:
                pay_type = str(r.get("PayType") or "")
                method = "card" if pay_type == "CreditCard" else "bank"
                account = _name((r.get("CheckPayment") or {}).get("BankAccountRef")) or _name(
                    (r.get("CreditCardPayment") or {}).get("CCAccountRef"))
            out.append(Payment(
                ref=_ref(entity, r), occurred_at=occurred, direction="in" if inbound else "out",
                amount=h.dec(r.get("TotalAmt")), method=method,
                reference=h.text_or_none(r.get("PaymentRefNum")) or h.text_or_none(r.get("DocNumber")),
                party_ref=f"{'customer' if inbound else 'vendor'}:{party_id}" if party_id else None,
                party_name=_name(party), account=account,
                invoice_ref=f"{'invoice' if inbound else 'bill'}:{target['TxnId']}" if target and target.get("TxnId")
                else None, currency=_value(r.get("CurrencyRef"))))
        return out

    return build


def _expenses(ctx: _Ctx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        occurred = _tx_moment(r)
        if occurred is None:
            continue
        category, description = None, h.text_or_none(r.get("PrivateNote"))
        for ln in r.get("Line") or []:
            if not isinstance(ln, dict):
                continue
            detail = ln.get("AccountBasedExpenseLineDetail") or ln.get("ItemBasedExpenseLineDetail") or {}
            category = category or _name(detail.get("AccountRef")) or _name(detail.get("ItemRef"))
            description = description or h.text_or_none(ln.get("Description"))
        entity = r.get("EntityRef")
        party = _value(entity)
        prefix = "vendor" if isinstance(entity, dict) and entity.get("type") != "Customer" else "customer"
        amount = h.dec(r.get("TotalAmt"))
        out.append(Expense(ref=_ref("Purchase", r), occurred_at=occurred, amount=-amount if r.get("Credit") else amount,
                           category=category, description=description,
                           party_ref=f"{prefix}:{party}" if party else None))
    return out


def _journals(ctx: _Ctx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        day = h.parse_date(r.get("TxnDate"))
        if day is None:
            continue
        lines: list[JournalLine] = []
        for ln in r.get("Line") or []:
            detail = ln.get("JournalEntryLineDetail") if isinstance(ln, dict) else None
            if not isinstance(detail, dict):
                continue
            amount = h.dec(ln.get("Amount"))
            entity = (detail.get("Entity") or {}).get("EntityRef")
            party = _value(entity)
            prefix = "vendor" if isinstance(entity, dict) and entity.get("type") == "Vendor" else "customer"
            lines.append(JournalLine(
                account=_name(detail.get("AccountRef")) or _value(detail.get("AccountRef")) or "unknown",
                debit=amount if detail.get("PostingType") == "Debit" else Decimal(0),
                credit=amount if detail.get("PostingType") == "Credit" else Decimal(0),
                party_ref=f"{prefix}:{party}" if party else None))
        out.append(JournalEntry(ref=_ref("JournalEntry", r), entry_date=day, lines=tuple(lines),
                                number=h.text_or_none(r.get("DocNumber")), entered_at=_meta(r, "CreateTime"),
                                memo=h.text_or_none(r.get("PrivateNote")), is_manual=True))
    return out


def _deposits(ctx: _Ctx, rows: list[Row]) -> list[Record]:
    """A bank deposit as a double entry: the bank account is debited, each source credited."""
    out: list[Record] = []
    for r in rows:
        day = h.parse_date(r.get("TxnDate"))
        if day is None:
            continue
        bank = _name(r.get("DepositToAccountRef")) or "Bank"
        lines = [JournalLine(account=bank, debit=h.dec(r.get("TotalAmt")))]
        for ln in r.get("Line") or []:
            detail = ln.get("DepositLineDetail") if isinstance(ln, dict) else None
            if isinstance(detail, dict):
                entity = detail.get("Entity")
                party = _value(entity)
                lines.append(JournalLine(account=_name(detail.get("AccountRef")) or "Undeposited Funds",
                                         credit=h.dec(ln.get("Amount")),
                                         party_ref=f"customer:{party}" if party else None))
        out.append(JournalEntry(ref=_ref("Deposit", r), entry_date=day, lines=tuple(lines),
                                number=h.text_or_none(r.get("DocNumber")), entered_at=_meta(r, "CreateTime"),
                                memo=h.text_or_none(r.get("PrivateNote")), is_manual=False))
    return out

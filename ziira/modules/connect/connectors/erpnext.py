"""ERPNext (Frappe) connector: reads a business's ERPNext site over its REST API with a read-only API key.

Written from Frappe's published REST documentation; **not yet run against a real ERPNext site**. See docs/connectors.md
for the checklist to run against a demo site first.

Reads only: every request is a `GET`. Lists are read in modification order with `limit_start`/`limit_page_length`;
documents with child tables (invoices, payment entries, journal entries) are then read one by one with
`GET /api/resource/<DocType>/<name>`. Only submitted documents (`docstatus` 1) and cancelled ones (2, mapped to
voided/cancelled) are read; drafts never are.
"""

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import quote

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
    StockMovement,
    User,
)
from ziira.sdk import provides

log = logging.getLogger("ziira.connect.erpnext")

SYSTEM = "ERPNext"
PAGE = 200
Row = dict[str, Any]

# Frappe answers "unknown field" in several ways depending on version; these statuses may carry that message.
_FIELD_ERROR_STATUSES = (400, 403, 417, 500)

_SALE_FIELDS = ["name", "posting_date", "posting_time", "creation", "modified", "modified_by", "owner", "docstatus",
                "is_return", "customer", "currency", "grand_total", "rounded_total", "total_taxes_and_charges",
                "discount_amount", "outstanding_amount", "due_date", "set_warehouse", "change_amount"]

_STOCK_ENTRY_TRANSFER = ("Material Transfer", "Material Transfer for Manufacture", "Send to Subcontractor")
_SYSTEM_JOURNALS = ("Depreciation Entry", "Exchange Rate Revaluation", "Exchange Gain Or Loss")
_AUTOMATIC_ROLES = ("Guest", "All", "Desk User", "Administrator")


@dataclass
class _Ctx:
    client: httpx.Client
    base: str
    headers: dict[str, str]
    tz: str | None
    secrets: tuple[object, ...]
    missing: set[str] = field(default_factory=set)


@dataclass
class _Source:
    key: str
    doctype: str
    fields: list[str]
    build: Callable[["_Ctx", list[Row]], list[Record]]
    optional: list[str] = field(default_factory=list)
    filters: list[list[Any]] = field(default_factory=list)


@provides("connect.connector")
class ErpNextConnector(Connector):
    kind = "erpnext"
    title = "ERPNext"
    description = ("Reads sales, purchases, payments, stock movements, expenses and journal entries from your "
                   "ERPNext site with a read-only API key. Nothing is ever written back.")
    entities = ("branches", "parties", "products", "users", "sales", "payments", "stock_movements", "invoices",
                "expenses", "journal_entries")
    config_fields = (
        ConfigField("base_url", "ERPNext web address", help="The address you open ERPNext at, without any page name.",
                    example="https://mybusiness.erpnext.com"),
        ConfigField("api_key", "API key", secret=True, help="From the read-only user's API Access section."),
        ConfigField("api_secret", "API secret", secret=True, help="Shown once when the key is generated."),
        ConfigField("timezone", "Time zone of the ERPNext server", required=False, example="Africa/Nairobi",
                    help="ERPNext sends times without a zone. Use the System Settings > Time Zone value there; "
                         "blank means UTC."),
    )
    needs_oauth = False
    freshness = "daily"
    how_to = (
        "1. In ERPNext, open Users and add a new user just for Ziira (for example ziira-readonly@yourdomain). Do not "
        "reuse a person's account.\n"
        "2. Give that user only the roles that can read: Accounts User, Stock User, Sales User, Purchase User and HR "
        "User are read-heavy, but if you can, create a custom role with Read (and Report) permission only on the "
        "documents Ziira reads (listed in the guide), and give the user just that role.\n"
        "3. Open that user, find 'API Access' and click 'Generate Keys'. Copy the API Secret now (it is shown once) "
        "and the API Key.\n"
        "4. Paste the web address, API key and API secret here. To withdraw access later: disable the user or generate "
        "new keys.")

    def __init__(self) -> None:
        self.notes: list[str] = []

    # ------------------------------------------------------------------ connection
    def _context(self, client: httpx.Client, config: dict[str, Any], secrets: dict[str, Any]) -> _Ctx:
        key, secret = str(secrets.get("api_key") or ""), str(secrets.get("api_secret") or "")
        if not key or not secret:
            raise ConnectorError("The API key or API secret is missing.", retryable=False)
        base = h.normalise_base_url(config.get("base_url"), system=SYSTEM)
        return _Ctx(client, base, {"Authorization": f"token {key}:{secret}", "Accept": "application/json"},
                    h.validate_timezone(config.get("timezone")), (key, secret))

    def check(self, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectionCheck:
        try:
            with self.client() as client:
                ctx = self._context(client, config, secrets)
                user = self._get(ctx, "/api/method/frappe.auth.get_logged_user").get("message")
                if not user or user == "Guest":
                    return ConnectionCheck(False, "ERPNext did not recognise the key: it signed in as a guest. "
                                                  "Check the API key and secret.")
                self._get(ctx, "/api/resource/Sales Invoice", {"fields": '["name"]', "limit_page_length": 1},
                          what="sales invoices")
                return ConnectionCheck(True, f"Connected to ERPNext as {user}.", {"system": SYSTEM, "user": str(user)})
        except ConnectorError as exc:
            return ConnectionCheck(False, str(exc))
        except httpx.HTTPError as exc:
            return ConnectionCheck(False, str(h.transport_error(exc, system=SYSTEM)))

    # ------------------------------------------------------------------ requests (GET only)
    def _get(self, ctx: _Ctx, path: str, params: dict[str, Any] | None = None, what: str = "the data") -> Any:
        url = ctx.base + quote(path, safe="/:")
        try:
            response = ctx.client.get(url, params=params, headers=ctx.headers)
        except httpx.HTTPError as exc:
            raise h.transport_error(exc, system=SYSTEM) from None
        h.raise_for_status(response, system=SYSTEM, secrets=ctx.secrets, what=what)
        return h.json_body(response, system=SYSTEM)

    def _list(self, ctx: _Ctx, source: _Source, filters: list[list[Any]], offset: int) -> list[Row]:
        """One page of a doctype, oldest modification first. Optional fields that this version lacks are dropped."""
        optional = [f for f in source.optional if f"{source.doctype}.{f}" not in ctx.missing]
        for _attempt in range(3):
            params: dict[str, Any] = {"fields": json.dumps(source.fields + optional), "filters": json.dumps(filters),
                      "order_by": "modified asc, name asc", "limit_start": offset, "limit_page_length": PAGE}
            try:
                response = ctx.client.get(f"{ctx.base}/api/resource/{quote(source.doctype)}", params=params,
                                          headers=ctx.headers)
            except httpx.HTTPError as exc:
                raise h.transport_error(exc, system=SYSTEM) from None
            if response.status_code in _FIELD_ERROR_STATUSES:
                unknown = [f for f in optional if f in response.text]
                if unknown:
                    ctx.missing.update(f"{source.doctype}.{f}" for f in unknown)
                    optional = [f for f in optional if f not in unknown]
                    continue
            h.raise_for_status(response, system=SYSTEM, secrets=ctx.secrets, what=f"{source.doctype} records")
            data = h.json_body(response, system=SYSTEM).get("data")
            return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
        raise ConnectorError(f"ERPNext could not list {source.doctype} records.", retryable=True)

    def _detail(self, ctx: _Ctx, doctype: str, name: str) -> Row | None:
        try:
            data = self._get(ctx, f"/api/resource/{doctype}/{name}", what=f"{doctype} records").get("data")
        except ConnectorError as exc:
            if "did not find" in str(exc):             # deleted since it was listed
                return None
            raise
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------------ streaming
    def pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
             limit: int | None = None) -> Iterator[CanonicalBatch]:
        if entity not in self.entities:
            raise ConnectorError(f"ERPNext connector cannot read '{entity}'.", retryable=False)
        self.notes = []
        return self._pull(config, secrets, entity, since, limit)

    def _pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
              limit: int | None) -> Iterator[CanonicalBatch]:
        stopped = {"early": False}
        with self.client() as client:
            ctx = self._context(client, config, secrets)
            sources = self._sources(entity)
            parts = self._parts(ctx, sources, since, limit, stopped)
            yield from h.seal(entity, parts, since, lambda: stopped["early"])

    def _parts(self, ctx: _Ctx, sources: list[_Source], since: str | None, limit: int | None,
               stopped: dict[str, bool]) -> Iterator[tuple[tuple[Record, ...], str | None]]:
        cursor = h.decode_cursor(since)
        seen = 0
        for source in sources:
            start = h.parse_cursor_time(cursor.get(source.key))
            filters = list(source.filters)
            if start is not None:
                filters.append(["modified", ">", h.to_zone(start, ctx.tz).strftime("%Y-%m-%d %H:%M:%S.%f")])
            offset = 0
            newest: datetime | None = None
            while True:
                rows = self._list(ctx, source, filters, offset)
                if not rows:
                    break
                records = source.build(ctx, rows)
                for row in rows:
                    moment = h.parse_dt(row.get("modified"), ctx.tz)
                    if moment is not None and (newest is None or moment > newest):
                        newest = moment
                if newest is not None:
                    cursor[source.key] = h.cursor_time(newest)
                yield tuple(records), h.encode_cursor(cursor)
                offset += len(rows)
                seen += len(rows)
                if limit is not None and seen >= limit:
                    stopped["early"] = True
                    return
                if len(rows) < PAGE:
                    break

    # ------------------------------------------------------------------ what each entity reads
    def _sources(self, entity: str) -> list[_Source]:
        sources: dict[str, list[_Source]] = {
            "branches": [_Source("Warehouse", "Warehouse", ["name", "warehouse_name", "modified"], self._branches,
                                 filters=[["is_group", "=", 0]])],
            "parties": [
                _Source("Customer", "Customer", ["name", "customer_name", "creation", "modified", "tax_id"],
                        self._parties("customer"), optional=["mobile_no", "email_id"]),
                _Source("Supplier", "Supplier", ["name", "supplier_name", "creation", "modified", "tax_id"],
                        self._parties("supplier"), optional=["mobile_no", "email_id"]),
            ],
            "products": [_Source("Item", "Item", ["name", "item_name", "item_group", "valuation_rate",
                                                  "standard_rate", "modified"], self._products)],
            "users": [_Source("User", "User", ["name", "full_name", "creation", "modified"], self._users,
                              filters=[["name", "not in", ["Administrator", "Guest"]]])],
            "sales": [
                _Source("POS Invoice", "POS Invoice", _SALE_FIELDS, self._sales("POS Invoice"),
                        optional=["is_consolidated"], filters=[["docstatus", "in", [1, 2]]]),
                _Source("Sales Invoice", "Sales Invoice", _SALE_FIELDS, self._sales("Sales Invoice"),
                        optional=["is_consolidated"], filters=[["docstatus", "in", [1, 2]]]),
            ],
            "payments": [_Source("Payment Entry", "Payment Entry",
                                 ["name", "payment_type", "posting_date", "creation", "modified", "owner", "docstatus",
                                  "party", "party_name", "paid_amount", "received_amount", "paid_from", "paid_to",
                                  "mode_of_payment", "reference_no", "paid_from_account_currency",
                                  "paid_to_account_currency"], self._payments,
                                 filters=[["docstatus", "in", [1, 2]], ["payment_type", "in", ["Receive", "Pay"]]])],
            "stock_movements": [_Source("Stock Ledger Entry", "Stock Ledger Entry",
                                        ["name", "item_code", "warehouse", "actual_qty", "incoming_rate",
                                         "valuation_rate", "voucher_type", "voucher_no", "posting_date",
                                         "posting_time", "creation", "modified", "owner"], self._stock,
                                        optional=["is_cancelled"])],
            "invoices": [
                _Source("Sales Invoice", "Sales Invoice", _SALE_FIELDS + ["bill_no"], self._invoices("customer"),
                        optional=["is_consolidated"], filters=[["docstatus", "in", [1, 2]]]),
                _Source("Purchase Invoice", "Purchase Invoice",
                        ["name", "posting_date", "creation", "modified", "owner", "docstatus", "supplier", "currency",
                         "grand_total", "rounded_total", "outstanding_amount", "due_date", "bill_no", "is_return"],
                        self._invoices("supplier"), filters=[["docstatus", "in", [1, 2]]]),
            ],
            "expenses": [_Source("Expense Claim", "Expense Claim",
                                 ["name", "employee", "employee_name", "posting_date", "creation", "modified", "owner",
                                  "docstatus", "total_claimed_amount", "total_sanctioned_amount"], self._expenses,
                                 filters=[["docstatus", "in", [1, 2]]])],
            "journal_entries": [_Source("Journal Entry", "Journal Entry",
                                        ["name", "voucher_type", "posting_date", "creation", "modified", "owner",
                                         "docstatus", "user_remark", "cheque_no"], self._journals,
                                        filters=[["docstatus", "in", [1, 2]]])],
        }
        return sources[entity]

    # ------------------------------------------------------------------ mappers
    @staticmethod
    def _branches(ctx: _Ctx, rows: list[Row]) -> list[Record]:
        return [Branch(ref=str(r["name"]), name=h.text_or_none(r.get("warehouse_name")) or str(r["name"]))
                for r in rows]

    @staticmethod
    def _parties(kind: Literal["customer", "supplier"]) -> Callable[[_Ctx, list[Row]], list[Record]]:
        name_key = "customer_name" if kind == "customer" else "supplier_name"

        def build(ctx: _Ctx, rows: list[Row]) -> list[Record]:
            return [Party(ref=str(r["name"]), kind=kind, name=h.text_or_none(r.get(name_key)) or str(r["name"]),
                          phone=h.text_or_none(r.get("mobile_no")),
                          email=h.text_or_none(r.get("email_id")), tax_id=h.text_or_none(r.get("tax_id")),
                          created_at=h.parse_dt(r.get("creation"), ctx.tz)) for r in rows]

        return build

    @staticmethod
    def _products(ctx: _Ctx, rows: list[Row]) -> list[Record]:
        return [Product(ref=str(r["name"]), name=h.text_or_none(r.get("item_name")) or str(r["name"]),
                        sku=str(r["name"]), category=h.text_or_none(r.get("item_group")),
                        unit_cost=h.dec_or_none(r.get("valuation_rate")),
                        unit_price=h.dec_or_none(r.get("standard_rate"))) for r in rows]

    def _users(self, ctx: _Ctx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        for r in rows:
            detail = self._detail(ctx, "User", str(r["name"])) or r
            roles = [str(x.get("role")) for x in detail.get("roles") or [] if isinstance(x, dict)
                     and x.get("role") and x.get("role") not in _AUTOMATIC_ROLES]
            email = str(r["name"]) if "@" in str(r["name"]) else None
            out.append(User(ref=str(r["name"]), name=h.text_or_none(r.get("full_name")) or str(r["name"]),
                            role=", ".join(roles[:3]) or None, email=email,
                            created_at=h.parse_dt(r.get("creation"), ctx.tz)))
        return out

    def _sales(self, doctype: str) -> Callable[[_Ctx, list[Row]], list[Record]]:
        def build(ctx: _Ctx, rows: list[Row]) -> list[Record]:
            out: list[Record] = []
            for r in rows:
                if r.get("is_consolidated") in (1, True):      # a summary of POS invoices that are read themselves
                    continue
                doc = r
                if r.get("docstatus") == 1:
                    doc = self._detail(ctx, doctype, str(r["name"])) or r
                    doc = {**r, **doc}
                out.append(_sale(ctx, doc))
            return out

        return build

    def _invoices(self, kind: Literal["customer", "supplier"]) -> Callable[[_Ctx, list[Row]], list[Record]]:
        def build(ctx: _Ctx, rows: list[Row]) -> list[Record]:
            out: list[Record] = []
            for r in rows:
                if r.get("is_consolidated") in (1, True):
                    continue
                total = _total(r)
                outstanding = h.dec(r.get("outstanding_amount"))
                cancelled = r.get("docstatus") == 2
                party = r.get("customer") if kind == "customer" else r.get("supplier")
                issued = h.parse_date(r.get("posting_date"))
                if issued is None:
                    continue
                out.append(Invoice(
                    ref=str(r["name"]), kind=kind,
                    issue_date=issued, total=total, paid=Decimal(0) if cancelled else total - outstanding,
                    due_date=h.parse_date(r.get("due_date")),
                    number=h.text_or_none(r.get("bill_no")) or str(r["name"]),
                    party_ref=h.text_or_none(party), status="cancelled" if cancelled else
                    ("paid" if outstanding == 0 else "open"), created_by_ref=h.text_or_none(r.get("owner")),
                    currency=h.text_or_none(r.get("currency"))))
            return out

        return build

    def _payments(self, ctx: _Ctx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        for r in rows:
            inbound = r.get("payment_type") == "Receive"
            amount = h.dec(r.get("received_amount") if inbound else r.get("paid_amount"))
            if r.get("docstatus") == 2:
                amount = Decimal(0)
            invoice_ref = None
            if r.get("docstatus") == 1:
                detail = self._detail(ctx, "Payment Entry", str(r["name"])) or {}
                refs = [x for x in detail.get("references") or [] if isinstance(x, dict) and x.get("reference_name")]
                invoice_ref = str(refs[0]["reference_name"]) if refs else None
            occurred = _day_or_creation(ctx, r)
            if occurred is None:
                continue
            out.append(Payment(
                ref=str(r["name"]), occurred_at=occurred, direction="in" if inbound else "out", amount=amount,
                method=h.payment_method(r.get("mode_of_payment")), reference=h.text_or_none(r.get("reference_no")),
                party_ref=h.text_or_none(r.get("party")), party_name=h.text_or_none(r.get("party_name")),
                account=h.text_or_none(r.get("paid_to") if inbound else r.get("paid_from")), invoice_ref=invoice_ref,
                currency=h.text_or_none(r.get("paid_to_account_currency" if inbound else
                                              "paid_from_account_currency"))))
        return out

    def _stock(self, ctx: _Ctx, rows: list[Row]) -> list[Record]:
        entries = [str(r["voucher_no"]) for r in rows if r.get("voucher_type") == "Stock Entry"]
        purposes = self._stock_entry_purposes(ctx, entries) if entries else {}
        out: list[Record] = []
        for r in rows:
            occurred = h.parse_dt(f"{r.get('posting_date')} {_clock(r.get('posting_time'))}", ctx.tz)
            if occurred is None or not r.get("item_code"):
                continue
            qty = h.dec(r.get("actual_qty"))
            purpose = purposes.get(str(r.get("voucher_no")))
            cancelled = r.get("is_cancelled") in (1, True)
            kind = _movement_kind(str(r.get("voucher_type")), qty, purpose)
            out.append(StockMovement(
                ref=str(r["name"]), occurred_at=occurred, product_ref=str(r["item_code"]),
                quantity=Decimal(0) if cancelled else qty, kind="other" if cancelled else kind,
                branch_ref=h.text_or_none(r.get("warehouse")), user_ref=h.text_or_none(r.get("owner")),
                reason="cancelled" if cancelled else (purpose or h.text_or_none(r.get("voucher_type"))),
                unit_cost=h.dec_or_none(r.get("incoming_rate") if qty > 0 else r.get("valuation_rate")),
                entered_at=h.parse_dt(r.get("creation"), ctx.tz)))
        return out

    def _stock_entry_purposes(self, ctx: _Ctx, names: list[str]) -> dict[str, str]:
        data = self._get(ctx, "/api/resource/Stock Entry",
                         {"fields": '["name","purpose"]', "filters": json.dumps([["name", "in", sorted(set(names))]]),
                          "limit_page_length": len(set(names)) + 1}, what="stock entries").get("data") or []
        return {str(x["name"]): str(x["purpose"]) for x in data if isinstance(x, dict) and x.get("purpose")}

    @staticmethod
    def _expenses(ctx: _Ctx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        for r in rows:
            occurred = _day_or_creation(ctx, r)
            if occurred is None:
                continue
            amount = h.dec(r.get("total_sanctioned_amount")) or h.dec(r.get("total_claimed_amount"))
            out.append(Expense(ref=str(r["name"]), occurred_at=occurred,
                               amount=Decimal(0) if r.get("docstatus") == 2 else amount, category="Expense Claim",
                               description=h.text_or_none(r.get("employee_name")),
                               user_ref=h.text_or_none(r.get("owner"))))
        return out

    def _journals(self, ctx: _Ctx, rows: list[Row]) -> list[Record]:
        out: list[Record] = []
        for r in rows:
            day = h.parse_date(r.get("posting_date"))
            if day is None:
                continue
            lines: tuple[JournalLine, ...] = ()
            if r.get("docstatus") == 1:
                detail = self._detail(ctx, "Journal Entry", str(r["name"])) or {}
                lines = tuple(JournalLine(account=str(x.get("account")), debit=h.dec(x.get("debit")),
                                          credit=h.dec(x.get("credit")), party_ref=h.text_or_none(x.get("party")))
                              for x in detail.get("accounts") or [] if isinstance(x, dict) and x.get("account"))
            out.append(JournalEntry(
                ref=str(r["name"]), entry_date=day, lines=lines, number=str(r["name"]),
                entered_at=h.parse_dt(r.get("creation"), ctx.tz), created_by_ref=h.text_or_none(r.get("owner")),
                memo="cancelled" if r.get("docstatus") == 2 else h.text_or_none(r.get("user_remark")),
                is_manual=r.get("voucher_type") not in _SYSTEM_JOURNALS))
        return out


# --------------------------------------------------------------------------- pure mapping helpers
def _clock(value: object) -> str:
    """'14:22:10', '14:22:10.123456' or '1 day, 2:03:04' style times as HH:MM:SS(.ffffff)."""
    text = str(value or "00:00:00").strip()
    if "," in text:
        text = text.rsplit(",", 1)[1].strip()
    parts = text.split(":")
    if len(parts) == 3 and len(parts[0]) == 1:
        text = "0" + text
    return text


def _total(r: Row) -> Decimal:
    return h.dec(r.get("rounded_total")) or h.dec(r.get("grand_total"))


def _day_or_creation(ctx: _Ctx, r: Row) -> datetime | None:
    """Documents that carry only a posting date: use the time it was created when that is the same day."""
    day = h.parse_date(r.get("posting_date"))
    if day is None:
        return None
    created = h.parse_dt(r.get("creation"), ctx.tz)
    if created is not None and h.to_zone(created, ctx.tz).date() == day:
        return created
    return h.at_midnight(day, ctx.tz)


def _movement_kind(voucher_type: str, qty: Decimal, purpose: str | None) -> h.MovementKind:
    if voucher_type in ("Delivery Note", "Sales Invoice", "POS Invoice"):
        return "return" if qty > 0 else "sale"
    if voucher_type in ("Purchase Receipt", "Purchase Invoice"):
        return "return" if qty < 0 else "purchase"
    if voucher_type == "Stock Reconciliation":
        return "count"
    if voucher_type == "Stock Entry":
        if purpose in _STOCK_ENTRY_TRANSFER:
            return "transfer_in" if qty > 0 else "transfer_out"
        return "adjustment"
    return "other"


def _sale(ctx: _Ctx, doc: Row) -> Sale:
    cancelled = doc.get("docstatus") == 2
    is_return = doc.get("is_return") in (1, True)
    occurred = h.parse_dt(f"{doc.get('posting_date')} {_clock(doc.get('posting_time'))}", ctx.tz) \
        or h.at_midnight(h.parse_date(doc.get("posting_date")) or datetime.now().date(), ctx.tz)
    items = [i for i in doc.get("items") or [] if isinstance(i, dict)]
    lines = tuple(SaleLine(
        product_ref=h.text_or_none(i.get("item_code")), quantity=h.dec(i.get("qty")), unit_price=h.dec(i.get("rate")),
        discount=h.dec(i.get("discount_amount")) * abs(h.dec(i.get("qty"))),
        list_price=h.dec_or_none(i.get("price_list_rate"))) for i in items)
    payments = _sale_payments(doc)
    outstanding = h.dec(doc.get("outstanding_amount"))
    if doc.get("docstatus") == 1 and outstanding > 0:
        payments += (SalePayment("credit", outstanding),)
    discount = h.dec(doc.get("discount_amount")) + sum((ln.discount for ln in lines), Decimal(0))
    warehouse = h.text_or_none(doc.get("set_warehouse")) or next(
        (str(i["warehouse"]) for i in items if i.get("warehouse")), None)
    return Sale(
        ref=str(doc["name"]), occurred_at=occurred, total=_total(doc),
        status="voided" if cancelled else ("refunded" if is_return else "posted"), number=str(doc["name"]),
        branch_ref=warehouse, cashier_ref=h.text_or_none(doc.get("owner")),
        customer_ref=h.text_or_none(doc.get("customer")), tax_total=h.dec(doc.get("total_taxes_and_charges")),
        discount_total=discount, currency=h.text_or_none(doc.get("currency")),
        voided_by_ref=h.text_or_none(doc.get("modified_by")) if cancelled else None, lines=lines, payments=payments,
        entered_at=h.parse_dt(doc.get("creation"), ctx.tz))


def _sale_payments(doc: Row) -> tuple[SalePayment, ...]:
    rows = [p for p in doc.get("payments") or [] if isinstance(p, dict) and h.dec(p.get("amount")) != 0]
    change = h.dec(doc.get("change_amount"))
    out: list[SalePayment] = []
    for p in rows:
        method = h.payment_method(p.get("mode_of_payment"), p.get("type"))
        amount = h.dec(p.get("amount"))
        if change > 0 and method == "cash":                       # cash handed over minus the change given back
            amount, change = amount - min(change, amount), change - min(change, amount)
        out.append(SalePayment(method, amount, h.text_or_none(p.get("reference_no"))))
    if change > 0 and out:
        out[0] = SalePayment(out[0].method, out[0].amount - min(change, out[0].amount), out[0].reference)
    return tuple(out)

"""Odoo connector: reads a business's Odoo database over JSON-RPC (`/jsonrpc`) with a user and an API key.

Written from Odoo's published external-API documentation; **not yet run against a real Odoo**. Versions 14 to 17 are
handled by asking each model which fields it has (`fields_get`) and reading only those, so a field renamed between
versions (`qty_done` became `quantity`, `payment_method_id` became `payment_method_line_id`) does not break a pull.

Reads only. Every call goes through one wrapper (`OdooRpc`) that refuses anything but the read methods
`search_read`, `read`, `search_count`, `fields_get` (on `object`) and `version`, `authenticate` (on `common`). A model
that is not installed, or that the user may not read, is skipped with a note and never fails the whole sync.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

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

log = logging.getLogger("ziira.connect.odoo")

SYSTEM = "Odoo"
PAGE = 200
Row = dict[str, Any]

READ_METHODS = frozenset({"search_read", "read", "search_count", "fields_get"})
COMMON_METHODS = frozenset({"version", "authenticate"})
TESTED_VERSIONS = (14, 17)


class OdooFault(ConnectorError):
    """An error reported by Odoo itself (as opposed to the network): `name` is Odoo's exception class."""

    def __init__(self, message: str, name: str, *, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)
        self.name = name

    @property
    def model_unavailable(self) -> bool:
        """True when the model is not installed or this user may not read it (safe to skip that entity)."""
        text = f"{self.name} {self}".lower()
        return any(w in text for w in ("accesserror", "keyerror", "doesn't exist", "does not exist", "missingerror",
                                       "not allowed to access", "access denied"))


class OdooRpc:
    """The only way this connector talks to Odoo. Anything that is not a read is refused before it is sent."""

    def __init__(self, client: httpx.Client, url: str, db: str, login: str, key: str) -> None:
        self.client, self.url, self.db, self.login, self._key = client, url, db, login, key
        self.uid: int | None = None
        self._ids = 0
        self.requests_made = 0

    # -- the guard
    @staticmethod
    def allowed(service: str, method: str, args: list[Any]) -> bool:
        if service == "common":
            return method in COMMON_METHODS
        if service == "object":
            return method == "execute_kw" and len(args) >= 5 and args[4] in READ_METHODS
        return False

    def _call(self, service: str, method: str, args: list[Any]) -> Any:
        if not self.allowed(service, method, args):
            what = args[4] if service == "object" and len(args) >= 5 else method
            raise h.ReadOnlyViolation(f"Refused to call '{service}.{what}': Ziira connectors only read.")
        self._ids += 1
        self.requests_made += 1
        body = {"jsonrpc": "2.0", "method": "call", "id": self._ids,
                "params": {"service": service, "method": method, "args": args}}
        secrets = (self._key,)
        try:
            response = self.client.post(f"{self.url}/jsonrpc", json=body)
        except httpx.HTTPError as exc:
            raise h.transport_error(exc, system=SYSTEM) from None
        if response.status_code in (403, 404):
            raise ConnectorError(
                "Odoo does not allow outside programs on this address. Check the web address; on Odoo's own hosted "
                "service this is only available on the Custom plan (otherwise use daily file exports).",
                retryable=False)
        h.raise_for_status(response, system=SYSTEM, secrets=secrets)
        reply = h.json_body(response, system=SYSTEM)
        if not isinstance(reply, dict):
            raise ConnectorError("Odoo replied in an unexpected way.", retryable=True)
        error = reply.get("error")
        if error:
            data = error.get("data") or {} if isinstance(error, dict) else {}
            name = str(data.get("name") or "")
            message = h.scrub(str(data.get("message") or error.get("message") or "error"), secrets)
            if "AccessDenied" in name:
                raise OdooFault("Odoo did not accept the login and API key. Check the database name, the login and "
                                "that the key has not been withdrawn.", name)
            if "does not exist" in message and "database" in message.lower():
                raise OdooFault("Odoo does not have a database with that name. Check the database name.", name)
            raise OdooFault(f"Odoo reported a problem: {message}", name)
        return reply.get("result")

    # -- allowed operations
    def version(self) -> dict[str, Any]:
        result = self._call("common", "version", [])
        return result if isinstance(result, dict) else {}

    def authenticate(self) -> int:
        uid = self._call("common", "authenticate", [self.db, self.login, self._key, {}])
        if not uid or not isinstance(uid, int):
            raise ConnectorError("Odoo did not accept the login and API key. Check the database name, the login and "
                                 "that the key has not been withdrawn.", retryable=False)
        self.uid = uid
        return uid

    def execute(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        if self.uid is None:
            self.authenticate()
        return self._call("object", "execute_kw",
                          [self.db, self.uid, self._key, model, method, args, kwargs or {}])

    def search_read(self, model: str, domain: list[Any], fields: list[str], **kwargs: Any) -> list[Row]:
        rows = self.execute(model, "search_read", [domain], {"fields": fields, **kwargs})
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def fields_get(self, model: str) -> dict[str, Any]:
        result = self.execute(model, "fields_get", [], {"attributes": ["type"]})
        return result if isinstance(result, dict) else {}


@dataclass
class _Ctx:
    rpc: OdooRpc
    _fields: dict[str, set[str]] = field(default_factory=dict)
    _cache: dict[str, Any] = field(default_factory=dict)

    def fields(self, model: str, wanted: list[str]) -> list[str]:
        """The wanted fields this model really has (always with id and write_date)."""
        if model not in self._fields:
            self._fields[model] = set(self.rpc.fields_get(model))
        have = self._fields[model]
        return ["id", "write_date"] + [f for f in wanted if f in have and f not in ("id", "write_date")]

    def has(self, model: str, name: str) -> bool:
        self.fields(model, [])
        return name in self._fields[model]

    def cached(self, key: str, make: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = make()
        return self._cache[key]


@dataclass
class _Source:
    key: str                                          # the model: also the cursor key
    wanted: list[str]
    build: Callable[["OdooConnector", _Ctx, list[Row]], list[Record]]
    domain: list[Any] = field(default_factory=list)
    optional: bool = False                            # model may be missing (module not installed): skip with a note


def m2o(value: object) -> tuple[int, str] | None:
    """A many-to-one value: Odoo gives [id, name] or False."""
    if isinstance(value, list | tuple) and len(value) == 2 and isinstance(value[0], int):
        return value[0], str(value[1])
    return None


def m2o_id(value: object) -> str | None:
    pair = m2o(value)
    return str(pair[0]) if pair else None


def _odoo_time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


@provides("connect.connector")
class OdooConnector(Connector):
    kind = "odoo"
    title = "Odoo"
    description = ("Reads sales (including point of sale), invoices, payments, stock movements and journal entries "
                   "from your Odoo database with a read-only user and an API key. Nothing is ever written back.")
    entities = ("branches", "parties", "products", "users", "sales", "payments", "stock_movements", "invoices",
                "expenses", "journal_entries")
    config_fields = (
        ConfigField("url", "Odoo web address", example="https://mybusiness.example.com",
                    help="The address you open Odoo at. Self-hosted Odoo works; Odoo's own hosted service allows "
                         "this only on the Custom plan."),
        ConfigField("database", "Database name", example="mybusiness",
                    help="Shown on the sign-in page, or in the database manager."),
        ConfigField("login", "Login of the read-only user", example="ziira@mybusiness.example.com"),
        ConfigField("api_key", "API key", secret=True, help="Created in the user's Account Security tab."),
    )
    needs_oauth = False
    freshness = "daily"
    how_to = (
        "1. In Odoo, go to Settings > Users and create a new user just for Ziira (not a person's account).\n"
        "2. Give it the lowest access that can read what you want us to see: for example Invoicing: Read-only (or "
        "Auditor), Sales: User, Inventory: User, Point of Sale: User. Avoid any Administrator or Manager level.\n"
        "3. Sign in as that user, open My Profile > Account Security > New API Key, give it the name 'Ziira' and "
        "copy the key (shown once).\n"
        "4. Paste the web address, database name, login and key here. To withdraw access later: delete the key, or "
        "archive the user.")

    def __init__(self) -> None:
        self.notes: list[str] = []

    # ------------------------------------------------------------------ connection
    def _rpc(self, client: httpx.Client, config: dict[str, Any], secrets: dict[str, Any]) -> OdooRpc:
        key = str(secrets.get("api_key") or "")
        db, login = str(config.get("database") or "").strip(), str(config.get("login") or "").strip()
        if not key or not db or not login:
            raise ConnectorError("The database name, login and API key are all needed.", retryable=False)
        return OdooRpc(client, h.normalise_base_url(config.get("url"), system=SYSTEM), db, login, key)

    def check(self, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectionCheck:
        try:
            with self.client() as client:
                rpc = self._rpc(client, config, secrets)
                version = str(rpc.version().get("server_version") or "unknown")
                uid = rpc.authenticate()
                rows = rpc.execute("res.users", "read", [[uid]], {"fields": ["name"]})
                name = str(rows[0].get("name")) if rows and isinstance(rows[0], dict) else rpc.login
                message = f"Connected to Odoo {version} as {name}."
                major = _major(version)
                if major is not None and not TESTED_VERSIONS[0] <= major <= TESTED_VERSIONS[1]:
                    message += (f" Odoo {major} is outside the versions we have tested "
                                f"({TESTED_VERSIONS[0]} to {TESTED_VERSIONS[1]}): some figures may be missing.")
                return ConnectionCheck(True, message, {"system": f"Odoo {version}", "user": name})
        except ConnectorError as exc:
            return ConnectionCheck(False, str(exc))
        except httpx.HTTPError as exc:
            return ConnectionCheck(False, str(h.transport_error(exc, system=SYSTEM)))

    # ------------------------------------------------------------------ streaming
    def pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
             limit: int | None = None) -> Iterator[CanonicalBatch]:
        if entity not in self.entities:
            raise ConnectorError(f"Odoo connector cannot read '{entity}'.", retryable=False)
        self.notes = []
        return self._pull(config, secrets, entity, since, limit)

    def _pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
              limit: int | None) -> Iterator[CanonicalBatch]:
        stopped = {"early": False}
        with self.client() as client:
            ctx = _Ctx(self._rpc(client, config, secrets))
            parts = self._parts(ctx, self._sources(entity), since, limit, stopped)
            yield from h.seal(entity, parts, since, lambda: stopped["early"])

    def _parts(self, ctx: _Ctx, sources: list[_Source], since: str | None, limit: int | None,
               stopped: dict[str, bool]) -> Iterator[tuple[tuple[Record, ...], str | None]]:
        cursor = h.decode_cursor(since)
        seen = 0
        for source in sources:
            start = h.parse_cursor_time(cursor.get(source.key))
            last_time = _odoo_time(start) if start else None
            last_id = 0
            newest: datetime | None = None
            while True:
                try:
                    fields = ctx.fields(source.key, source.wanted)
                    rows = ctx.rpc.search_read(source.key, source.domain + _keyset(last_time, last_id), fields,
                                               order="write_date asc, id asc", limit=PAGE,
                                               context={"active_test": False})
                    records = source.build(self, ctx, rows) if rows else []
                except OdooFault as exc:
                    if source.optional and exc.model_unavailable:
                        self.notes.append(f"Skipped {source.key}: not installed, or this user may not read it.")
                        break
                    if exc.model_unavailable:
                        raise ConnectorError(f"The Odoo user is not allowed to read {source.key}. Give it read access "
                                             "to that area and try again.", retryable=False) from None
                    raise
                if not rows:
                    break
                for row in rows:
                    moment = h.parse_dt(row.get("write_date"))
                    if moment is not None and (newest is None or moment > newest):
                        newest = moment
                last_time, last_id = str(rows[-1].get("write_date")), int(rows[-1]["id"])
                if newest is not None:
                    cursor[source.key] = h.cursor_time(newest)
                yield tuple(records), h.encode_cursor(cursor)
                seen += len(rows)
                if limit is not None and seen >= limit:
                    stopped["early"] = True
                    return
                if len(rows) < PAGE:
                    break

    # ------------------------------------------------------------------ what each entity reads
    def _sources(self, entity: str) -> list[_Source]:
        posted = [("state", "in", ["posted", "cancel"])]
        sources: dict[str, list[_Source]] = {
            "branches": [_Source("stock.warehouse", ["name"], _warehouses),
                         _Source("pos.config", ["name"], _pos_configs, optional=True)],
            "parties": [_Source("res.partner", ["name", "phone", "mobile", "email", "vat", "create_date",
                                                "customer_rank", "supplier_rank"], _parties,
                                domain=["|", ("customer_rank", ">", 0), ("supplier_rank", ">", 0)])],
            "products": [_Source("product.product", ["name", "default_code", "categ_id", "standard_price",
                                                     "lst_price"], _products)],
            "users": [_Source("res.users", ["name", "login", "email", "create_date"], _users)],
            "sales": [_Source("pos.order", ["name", "date_order", "amount_total", "amount_tax", "state", "config_id",
                                            "user_id", "partner_id", "create_date", "write_uid"], _pos_orders,
                              domain=[("state", "in", ["paid", "done", "invoiced", "cancel"])], optional=True)],
            "payments": [_Source("account.payment", ["name", "date", "amount", "payment_type", "partner_id",
                                                     "journal_id", "payment_method_line_id", "payment_method_id",
                                                     "payment_reference", "ref", "state", "currency_id",
                                                     "reconciled_invoice_ids"], _account_payments,
                                 domain=[("state", "not in", ["draft"]),
                                         ("payment_type", "in", ["inbound", "outbound"])])],
            "stock_movements": [_Source("stock.move.line", ["date", "product_id", "qty_done", "quantity",
                                                            "location_id", "location_dest_id", "reference",
                                                            "create_uid", "create_date"], _move_lines,
                                        domain=[("state", "=", "done")])],
            "invoices": [_Source("account.move", ["name", "move_type", "invoice_date", "invoice_date_due", "date",
                                                  "amount_total", "amount_residual", "payment_state", "state",
                                                  "partner_id", "create_uid", "currency_id", "ref"], _invoices,
                                 domain=posted + [("move_type", "in", ["out_invoice", "out_refund", "in_invoice",
                                                                        "in_refund"])])],
            "expenses": [_Source("hr.expense", ["name", "date", "total_amount", "employee_id", "product_id", "state",
                                                "description", "create_date"], _expenses,
                                 domain=[("state", "in", ["approved", "done", "reported", "refused"])],
                                 optional=True)],
            "journal_entries": [_Source("account.move", ["name", "date", "ref", "narration", "state", "journal_id",
                                                         "create_uid", "create_date"], _journals,
                                        domain=posted + [("move_type", "=", "entry")])],
        }
        return sources[entity]


# --------------------------------------------------------------------------- helpers
def _major(version: str) -> int | None:
    head = version.split(".")[0].replace("saas~", "")
    return int(head) if head.isdigit() else None


def _keyset(last_time: str | None, last_id: int) -> list[Any]:
    """Domain terms for 'after (last_time, last_id)' in (write_date, id) order, so no page boundary can lose a row."""
    if last_time is None:
        return []
    if last_id == 0:
        return [("write_date", ">", last_time)]
    return ["|", ("write_date", ">", last_time), "&", ("write_date", "=", last_time), ("id", ">", last_id)]


def wh(warehouse_id: str | None) -> str | None:
    return f"stock.warehouse:{warehouse_id}" if warehouse_id else None


# What a stock move is, from the kind of place the other end is (Odoo's location "usage").
_KIND_IN: dict[str, h.MovementKind] = {"supplier": "purchase", "customer": "return", "inventory": "adjustment",
                                       "transit": "transfer_in"}
_KIND_OUT: dict[str, h.MovementKind] = {"customer": "sale", "supplier": "return", "inventory": "adjustment",
                                        "transit": "transfer_out"}


def _created(row: Row) -> datetime | None:
    return h.parse_dt(row.get("create_date"))


# --------------------------------------------------------------------------- mappers
def _warehouses(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    return [Branch(ref=f"stock.warehouse:{r['id']}", name=h.text_or_none(r.get("name")) or str(r["id"])) for r in rows]


def _pos_configs(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    return [Branch(ref=f"pos.config:{r['id']}", name=h.text_or_none(r.get("name")) or str(r["id"])) for r in rows]


def _parties(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        customer, supplier = int(r.get("customer_rank") or 0), int(r.get("supplier_rank") or 0)
        kind: Literal["customer", "supplier"] = "customer" if customer >= supplier and customer > 0 else "supplier"
        out.append(Party(ref=str(r["id"]), kind=kind, name=h.text_or_none(r.get("name")) or str(r["id"]),
                         phone=h.text_or_none(r.get("mobile")) or h.text_or_none(r.get("phone")),
                         email=h.text_or_none(r.get("email")), tax_id=h.text_or_none(r.get("vat")),
                         created_at=_created(r)))
    return out


def _products(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        category = m2o(r.get("categ_id"))
        out.append(Product(ref=str(r["id"]), name=h.text_or_none(r.get("name")) or str(r["id"]),
                           sku=h.text_or_none(r.get("default_code")), category=category[1] if category else None,
                           unit_cost=h.dec_or_none(r.get("standard_price")),
                           unit_price=h.dec_or_none(r.get("lst_price"))))
    return out


def _users(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        login = h.text_or_none(r.get("login"))
        out.append(User(ref=str(r["id"]), name=h.text_or_none(r.get("name")) or login or str(r["id"]),
                        email=h.text_or_none(r.get("email")) or (login if login and "@" in login else None),
                        created_at=_created(r)))
    return out


def _pos_orders(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    ids = [r["id"] for r in rows]
    lines_by_order: dict[int, list[Row]] = {}
    for line in ctx.rpc.search_read(
            "pos.order.line", [("order_id", "in", ids)],
            ctx.fields("pos.order.line", ["order_id", "product_id", "qty", "price_unit", "discount"])):
        order = m2o_id(line.get("order_id"))
        if order:
            lines_by_order.setdefault(int(order), []).append(line)
    pays_by_order: dict[int, list[Row]] = {}
    for pay in ctx.rpc.search_read(
            "pos.payment", [("pos_order_id", "in", ids)],
            ctx.fields("pos.payment", ["pos_order_id", "payment_method_id", "amount", "transaction_id"])):
        order = m2o_id(pay.get("pos_order_id"))
        if order:
            pays_by_order.setdefault(int(order), []).append(pay)
    out: list[Record] = []
    for r in rows:
        occurred = h.parse_dt(r.get("date_order"))
        if occurred is None:
            continue
        lines = []
        for ln in lines_by_order.get(r["id"], []):
            qty, price, percent = h.dec(ln.get("qty")), h.dec(ln.get("price_unit")), h.dec(ln.get("discount"))
            lines.append(SaleLine(product_ref=m2o_id(ln.get("product_id")), quantity=qty,
                                  unit_price=price * (1 - percent / 100), discount=abs(qty) * price * percent / 100,
                                  list_price=price if price else None))
        pays = tuple(SalePayment(h.payment_method((m2o(p.get("payment_method_id")) or (0, ""))[1]),
                                 h.dec(p.get("amount")), h.text_or_none(p.get("transaction_id")))
                     for p in pays_by_order.get(r["id"], []))
        total = h.dec(r.get("amount_total"))
        cancelled = r.get("state") == "cancel"
        config = m2o_id(r.get("config_id"))
        out.append(Sale(
            ref=str(r["id"]), occurred_at=occurred, total=total,
            status="voided" if cancelled else ("refunded" if total < 0 else "posted"),
            number=h.text_or_none(r.get("name")),
            branch_ref=f"pos.config:{config}" if config else None, cashier_ref=m2o_id(r.get("user_id")),
            customer_ref=m2o_id(r.get("partner_id")), tax_total=h.dec(r.get("amount_tax")),
            discount_total=sum((ln.discount for ln in lines), Decimal(0)),
            voided_by_ref=m2o_id(r.get("write_uid")) if cancelled else None,
            lines=tuple(lines), payments=pays, entered_at=_created(r)))
    return out


def _invoices(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        move_type = str(r.get("move_type"))
        issued = h.parse_date(r.get("invoice_date")) or h.parse_date(r.get("date"))
        if issued is None:
            continue
        sign = Decimal(-1) if move_type.endswith("_refund") else Decimal(1)
        total = sign * h.dec(r.get("amount_total"))
        state, pay_state = r.get("state"), r.get("payment_state")
        cancelled = state == "cancel" or pay_state == "reversed"
        paid = Decimal(0) if cancelled else total - sign * h.dec(r.get("amount_residual"))
        kind: Literal["customer", "supplier"] = "customer" if move_type.startswith("out_") else "supplier"
        currency = m2o(r.get("currency_id"))
        out.append(Invoice(
            ref=str(r["id"]), kind=kind, issue_date=issued, total=total, paid=paid,
            due_date=h.parse_date(r.get("invoice_date_due")), number=h.text_or_none(r.get("name")),
            party_ref=m2o_id(r.get("partner_id")),
            status="cancelled" if cancelled else ("paid" if pay_state in ("paid", "in_payment") else "open"),
            created_by_ref=m2o_id(r.get("create_uid")), currency=currency[1] if currency else None))
    return out


def _account_payments(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    journals = ctx.cached("journals", lambda: {
        j["id"]: j for j in ctx.rpc.search_read("account.journal", [], ["id", "type", "name"],
                                                context={"active_test": False})})
    out: list[Record] = []
    for r in rows:
        occurred = h.parse_dt(r.get("date"))
        if occurred is None:
            continue
        journal = m2o(r.get("journal_id"))
        journal_row = journals.get(journal[0]) if journal else None
        method_name = (m2o(r.get("payment_method_line_id")) or m2o(r.get("payment_method_id")) or (0, ""))[1]
        partner = m2o(r.get("partner_id"))
        reconciled = r.get("reconciled_invoice_ids")
        currency = m2o(r.get("currency_id"))
        cancelled = r.get("state") in ("cancel", "cancelled")
        out.append(Payment(
            ref=str(r["id"]), occurred_at=occurred, direction="in" if r.get("payment_type") == "inbound" else "out",
            amount=Decimal(0) if cancelled else h.dec(r.get("amount")),
            method=h.payment_method(method_name, journal_row.get("type") if journal_row else None),
            reference=h.text_or_none(r.get("payment_reference")) or h.text_or_none(r.get("ref")),
            party_ref=str(partner[0]) if partner else None, party_name=partner[1] if partner else None,
            account=journal[1] if journal else None,
            invoice_ref=str(reconciled[0]) if isinstance(reconciled, list) and reconciled else None,
            currency=currency[1] if currency else None))
    return out


def _move(row: Row, occurred: datetime, product: str, ref: str, quantity: Decimal, kind: h.MovementKind,
          warehouse: str | None) -> StockMovement:
    return StockMovement(ref=ref, occurred_at=occurred, product_ref=product, quantity=quantity, kind=kind,
                         branch_ref=wh(warehouse), user_ref=m2o_id(row.get("create_uid")),
                         reason=h.text_or_none(row.get("reference")), entered_at=_created(row))


def _move_lines(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    locations: dict[int, Row] = ctx.cached("locations", lambda: {
        loc["id"]: loc for loc in ctx.rpc.search_read(
            "stock.location", [], ctx.fields("stock.location", ["usage", "warehouse_id"]),
            context={"active_test": False})})
    out: list[Record] = []
    for r in rows:
        occurred = h.parse_dt(r.get("date"))
        product = m2o_id(r.get("product_id"))
        qty = h.dec(r.get("qty_done") if "qty_done" in r else r.get("quantity"))
        src, dst = m2o(r.get("location_id")), m2o(r.get("location_dest_id"))
        if occurred is None or product is None or qty == 0 or src is None or dst is None:
            continue
        src_loc, dst_loc = locations.get(src[0], {}), locations.get(dst[0], {})
        src_use, dst_use = str(src_loc.get("usage") or ""), str(dst_loc.get("usage") or "")
        src_wh, dst_wh = m2o_id(src_loc.get("warehouse_id")), m2o_id(dst_loc.get("warehouse_id"))
        if src_use == "internal" and dst_use == "internal":
            if src_wh is not None and src_wh == dst_wh:
                continue                                              # moved inside one branch: no change for it
            out.append(_move(r, occurred, product, f"{r['id']}:out", -qty, "transfer_out", src_wh))
            out.append(_move(r, occurred, product, f"{r['id']}:in", qty, "transfer_in", dst_wh))
        elif dst_use == "internal":
            out.append(_move(r, occurred, product, str(r["id"]), qty, _KIND_IN.get(src_use, "other"), dst_wh))
        elif src_use == "internal":
            out.append(_move(r, occurred, product, str(r["id"]), -qty, _KIND_OUT.get(dst_use, "other"), src_wh))
    return out


def _expenses(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    out: list[Record] = []
    for r in rows:
        occurred = h.parse_dt(r.get("date"))
        if occurred is None:
            continue
        product, employee = m2o(r.get("product_id")), m2o(r.get("employee_id"))
        out.append(Expense(ref=str(r["id"]), occurred_at=occurred,
                           amount=Decimal(0) if r.get("state") == "refused" else h.dec(r.get("total_amount")),
                           category=product[1] if product else None,
                           description=h.text_or_none(r.get("name")) or h.text_or_none(r.get("description")),
                           user_ref=str(employee[0]) if employee else None))
    return out


def _journals(c: OdooConnector, ctx: _Ctx, rows: list[Row]) -> list[Record]:
    journals = ctx.cached("journals", lambda: {
        j["id"]: j for j in ctx.rpc.search_read("account.journal", [], ["id", "type", "name"],
                                                context={"active_test": False})})
    live = [r["id"] for r in rows if r.get("state") == "posted"]
    lines_by_move: dict[int, list[Row]] = {}
    if live:
        for line in ctx.rpc.search_read("account.move.line", [("move_id", "in", live)],
                                        ctx.fields("account.move.line", ["move_id", "account_id", "debit", "credit",
                                                                         "partner_id"])):
            move = m2o_id(line.get("move_id"))
            if move:
                lines_by_move.setdefault(int(move), []).append(line)
    out: list[Record] = []
    for r in rows:
        day = h.parse_date(r.get("date"))
        if day is None:
            continue
        journal = m2o(r.get("journal_id"))
        journal_type = (journals.get(journal[0]) or {}).get("type") if journal else None
        lines = tuple(JournalLine(account=(m2o(ln.get("account_id")) or (0, "unknown"))[1],
                                  debit=h.dec(ln.get("debit")), credit=h.dec(ln.get("credit")),
                                  party_ref=m2o_id(ln.get("partner_id"))) for ln in lines_by_move.get(r["id"], []))
        out.append(JournalEntry(
            ref=str(r["id"]), entry_date=day, lines=lines, number=h.text_or_none(r.get("name")),
            entered_at=_created(r), created_by_ref=m2o_id(r.get("create_uid")),
            memo="cancelled" if r.get("state") == "cancel" else (h.text_or_none(r.get("ref"))
                                                                 or h.text_or_none(r.get("narration"))),
            is_manual=journal_type == "general"))
    return out

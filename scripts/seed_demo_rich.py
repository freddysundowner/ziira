# ruff: noqa: N806, E501
"""Fill a development business with about 90 days of believable trading, so every screen shows a living company.

    .venv/bin/python scripts/seed_demo_rich.py                          # demo-hardware, full scale (about 5 minutes)
    .venv/bin/python scripts/seed_demo_rich.py --scale small            # 45 days, a faster look
    .venv/bin/python scripts/seed_demo_rich.py --tenant demo-sales      # another demo-* business
    .venv/bin/python scripts/seed_demo_rich.py --reset --confirm demo-hardware   # drop and recreate the demo business, then fill it

Development only: refuses ZIIRA_ENV=production, refuses any tenant whose code does not start with `demo` (unless
--i-know is given) and refuses `aluta-*` always. `--reset` only works for the code `demo-hardware` or a code starting
with `demo-`, and needs `--confirm CODE`. Running it twice on a business it already filled does nothing.
What it creates, the logins and the planted stories (with the finding each should cause): docs/demo-data.md.

How the data is made. Everything goes through the real API in this process (permissions, numbering, audit, events, the
books), signed in as the people who would do it. The API only knows "now", so each business day is run as if it were
today and the rows it made are then moved to their real day: a *phase* is the stretch of real time that one simulated
day took; afterwards every timestamp inside a phase is stretched onto that day's trading hours and every date made in
it is moved back by the number of days. This is done in one pass at the end, with the tables' immutability triggers
switched off for the length of that one pass only and back on afterwards; it rewrites no amounts, numbers or links, so
`ziira verify` and the trial balance prove the result (the script runs them and fails if they are not clean).
"""

import argparse
import contextlib
import io
import json
import logging
import math
import os
import random
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = os.environ.get("ZIIRA_DEMO_PASSWORD", "demo-pass-123")   # every demo login uses this (set ZIIRA_DEMO_PASSWORD on a public server)
MARKER_SKU = "HWD-MARK"                          # a product that says "this business was filled by this script"
SEED = 20261014

# ------------------------------------------------------------------------------------------------------ scales
# days: history length; branches: how many of THK/JUJ/RUI; sales: till sales over the whole history
SCALES: dict[str, dict[str, Any]] = {
    "tiny": dict(days=14, branches=1, sales=20, products=12, customers=4, suppliers=4, employees=3, payroll_runs=1,
                 stories={2, 6, 7}, receipts_per_supplier=2, expense_every=3),
    "small": dict(days=45, branches=3, sales=600, products=45, customers=14, suppliers=12, employees=14, payroll_runs=1,
                  stories={2, 3, 5, 6, 7, 8, 9, 10}, receipts_per_supplier=3, expense_every=3),
    "full": dict(days=90, branches=3, sales=1800, products=45, customers=25, suppliers=12, employees=14, payroll_runs=2,
                 stories={1, 2, 3, 4, 5, 6, 7, 8, 9, 10}, receipts_per_supplier=5, expense_every=3),
}

BRANCHES = [("THK", "Thika", 0.42), ("JUJ", "Juja", 0.33), ("RUI", "Ruiru", 0.25)]
OPEN_AT, CLOSE_AT = dtime(7, 45), dtime(20, 15)       # a business day's stretch of real time lands between these
DOW_FACTOR = [1.0, 0.95, 0.95, 1.0, 1.15, 1.55, 0.5]  # Monday .. Sunday


def log(message: str, started: float | None = None) -> None:
    suffix = f"  ({time.time() - started:.1f}s)" if started else ""
    print(f"[demo] {message}{suffix}", flush=True)


def rng_extra(rng: random.Random) -> int:
    """A few odd units on an order, so two orders are never worth exactly the same."""
    return rng.randint(0, 3)


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------------------------------------------ master data
UOMS = [("PCS", "Pieces"), ("BAG", "Bag"), ("KG", "Kilogram"), ("LTR", "Litre"), ("MTR", "Metre"), ("BOX", "Box"),
        ("ROLL", "Roll"), ("SET", "Set")]
# code, name, VAT rate in percent (fixtures: a business enters its own)
TAXES = [("STD", "Standard rate", "16"), ("ZERO", "Zero rate", "0"), ("EXEMPT", "Exempt", "0"),
         ("RED", "Reduced rate", "8")]
CATEGORIES = ["Cement and building materials", "Roofing and timber", "Plumbing", "Electrical", "Paints and finishes",
              "Tools and fasteners"]
# supplier index: see SUPPLIERS. price is tax-inclusive; cost is before tax. weight: how often it is bought.
# (sku, name, category index, uom, tax, cost, price, weight, supplier index)
PRODUCTS: list[tuple[str, str, int, str, str, int, int, float, int]] = [
    ("CEM-50KG", "Cement 50kg", 0, "BAG", "STD", 600, 780, 10, 0),
    ("CEM-WHT5", "White cement 5kg", 0, "PCS", "STD", 420, 560, 1.5, 0),
    ("SND-50KG", "Building sand 50kg bag", 0, "BAG", "RED", 120, 170, 4, 10),
    ("BAL-50KG", "Ballast 3/4 inch 50kg bag", 0, "BAG", "RED", 130, 180, 3.5, 10),
    ("BLK-6IN", "Concrete block 6 inch", 0, "PCS", "RED", 62, 90, 6, 10),
    ("STL-Y10", "Reinforcement bar Y10 x 12m", 0, "PCS", "STD", 850, 1150, 4, 1),
    ("STL-Y12", "Reinforcement bar Y12 x 12m", 0, "PCS", "STD", 1180, 1580, 3, 1),
    ("MSH-A98", "Welded mesh A98 2.4 x 4.8m", 0, "PCS", "STD", 4300, 5600, 0.8, 1),
    ("WIR-BND", "Binding wire 1kg roll", 0, "KG", "STD", 180, 250, 3, 1),
    ("ROOF-G30", "Roofing sheet gauge 30, 3m", 1, "PCS", "STD", 780, 1050, 5, 3),
    ("ROF-G28", "Roofing sheet gauge 28, 3m", 1, "PCS", "STD", 980, 1300, 2.5, 3),
    ("ROF-RDG", "Roofing ridge cap 2m", 1, "PCS", "STD", 520, 700, 1.5, 3),
    ("ROF-NLS", "Roofing nails 3 inch, 1kg", 1, "KG", "STD", 190, 260, 3, 3),
    ("TMB-2X2", "Timber cypress 2x2 inch, 12ft", 1, "PCS", "STD", 210, 290, 4, 7),
    ("TMB-4X2", "Timber cypress 4x2 inch, 12ft", 1, "PCS", "STD", 480, 640, 4, 7),
    ("PLY-18", "Plywood 18mm 8x4", 1, "PCS", "STD", 2650, 3450, 1, 7),
    ("PVC-1IN", "PVC pipe 1 inch, 6m", 2, "PCS", "STD", 520, 700, 3, 5),
    ("PVC-2IN", "PVC pipe 2 inch, 6m", 2, "PCS", "STD", 880, 1180, 2.5, 5),
    ("PVC-4IN", "PVC pipe 4 inch, 6m", 2, "PCS", "STD", 1650, 2200, 1.5, 5),
    ("ELB-1IN", "PVC elbow 1 inch", 2, "PCS", "STD", 45, 70, 5, 5),
    ("TAP-BIB", "Bib tap 1/2 inch brass", 2, "PCS", "STD", 360, 490, 2.5, 5),
    ("WTK-1000", "Water tank 1000L", 2, "PCS", "EXEMPT", 9800, 11400, 0.6, 5),
    ("TEF-TAPE", "PTFE thread seal tape", 2, "ROLL", "STD", 22, 40, 4, 5),
    ("SINK-SS", "Kitchen sink, stainless steel", 2, "PCS", "STD", 3400, 4500, 0.5, 9),
    ("CAB-25", "Twin and earth cable 2.5mm, 100m", 3, "ROLL", "STD", 7900, 10200, 1.2, 4),
    ("CAB-15", "Twin and earth cable 1.5mm, 100m", 3, "ROLL", "STD", 5200, 6900, 1.2, 4),
    ("SWT-1G", "Light switch 1 gang", 3, "PCS", "STD", 95, 150, 4, 4),
    ("SKT-13A", "Socket outlet 13A double", 3, "PCS", "STD", 230, 340, 3.5, 4),
    ("BLB-LED9", "LED bulb 9W", 3, "PCS", "STD", 110, 180, 5, 4),
    ("MCB-32A", "Circuit breaker 32A", 3, "PCS", "STD", 420, 590, 1.5, 4),
    ("CND-20", "Conduit pipe 20mm, 3m", 3, "PCS", "STD", 85, 130, 3, 4),
    ("SOL-LAMP", "Solar lantern, rechargeable", 3, "PCS", "ZERO", 750, 1100, 1, 4),
    ("PAINT-W4L", "White emulsion paint 4L", 4, "PCS", "STD", 1800, 2400, 4, 2),
    ("PNT-W20", "White emulsion paint 20L", 4, "PCS", "STD", 7600, 9800, 1.5, 2),
    ("PNT-GL4", "Gloss enamel paint 4L", 4, "PCS", "STD", 2100, 2800, 2, 2),
    ("PNT-RO4", "Roof paint red oxide 4L", 4, "PCS", "STD", 2000, 2650, 1.5, 2),
    ("BRS-3IN", "Paint brush 3 inch", 4, "PCS", "STD", 120, 190, 3, 2),
    ("RLR-9IN", "Paint roller 9 inch with tray", 4, "SET", "STD", 320, 450, 2, 2),
    ("PUT-5KG", "Wall putty 5kg", 4, "PCS", "STD", 650, 880, 2.5, 2),
    ("NAIL-4IN", "Wire nails 4 inch, 1kg", 5, "KG", "STD", 150, 210, 6, 6),
    ("NAL-3IN", "Wire nails 3 inch, 1kg", 5, "KG", "STD", 155, 215, 4, 6),
    ("SCR-WD200", "Wood screws assorted, box of 200", 5, "BOX", "STD", 280, 390, 2, 6),
    ("HMR-16", "Claw hammer 16oz", 5, "PCS", "STD", 520, 720, 1.2, 6),
    ("PAD-50", "Padlock 50mm", 5, "PCS", "STD", 340, 480, 2, 6),
    ("GLV-WRK", "Work gloves, pair", 5, "PCS", "STD", 95, 150, 3, 6),
]
UNCONFIRMED = {8, 11}      # suppliers whose proposed bank details nobody has confirmed yet (no purchases from them)
# name, bank, how fast they are paid (days of terms)
SUPPLIERS: list[tuple[str, str, str, int]] = [
    ("Mombasa Road Cement Distributors", "Commerce Bank", "0123456001", 30),
    ("Rift Valley Steel and Wire Ltd", "Highland Bank", "0123456002", 30),
    ("Kijani Paints Kenya Ltd", "Commerce Bank", "0123456003", 45),
    ("Umoja Roofing Systems", "Savannah Bank", "0123456004", 30),
    ("Tazama Electricals Ltd", "Highland Bank", "0123456005", 30),
    ("Baraka Plumbing Wholesalers", "Savannah Bank", "0123456006", 21),
    ("Nyota Tools and Fasteners", "Commerce Bank", "0123456007", 30),
    ("Lakeview Timber Merchants", "Lakeside Bank", "0123456008", 14),
    ("Sunrise Ceramics and Tiles", "Lakeside Bank", "0123456009", 30),
    ("Delta Hardware Imports", "Highland Bank", "0123456010", 45),
    ("Eastlands Aggregates and Sand", "Savannah Bank", "0123456011", 14),
    ("Pwani Safety and Workwear", "Commerce Bank", "0123456012", 30),
]
# name, kind, group, credit limit, terms, home branch index, bulk buyer (invoiced) or counter credit
CUSTOMERS: list[tuple[str, str, str | None, int, int, int, str]] = [
    ("Kamau and Sons Hardware", "business", "wholesale", 250000, 30, 0, "shop"),
    ("Njeri Building Contractors", "business", "wholesale", 400000, 30, 0, "contractor"),
    ("Thika Road Plumbers Ltd", "business", "wholesale", 150000, 30, 0, "contractor"),
    ("St. Mary's Primary School", "business", None, 120000, 45, 0, "school"),
    ("Hope Community NGO", "business", None, 200000, 45, 1, "ngo"),
    ("Mwangi Electrical Services", "business", "wholesale", 100000, 30, 1, "contractor"),
    ("Juja Farm Estate Developers", "business", "wholesale", 500000, 30, 1, "contractor"),
    ("Ruiru Homes Developers", "business", "wholesale", 450000, 30, 2, "contractor"),
    ("Otieno Construction Co", "business", "wholesale", 150000, 15, 1, "contractor"),
    ("Greenview Academy", "business", None, 180000, 45, 2, "school"),
    ("Bidii Welding Works", "business", None, 60000, 14, 0, "shop"),
    ("Jacaranda Gardens Estate", "business", None, 220000, 30, 2, "contractor"),
    ("Wanjiku Interiors", "business", None, 80000, 30, 0, "shop"),
    ("Savanna Lodge Ltd", "business", None, 140000, 30, 2, "contractor"),
    ("Eastern Farmers Sacco", "business", None, 300000, 30, 1, "shop"),
    ("Riverside Water Project", "business", None, 350000, 45, 1, "ngo"),
    ("Muthoni Tiling and Flooring", "business", None, 90000, 30, 0, "shop"),
    ("Abdi Roofing Contractors", "business", "wholesale", 260000, 30, 2, "contractor"),
    ("Kijiji Health Centre", "business", None, 110000, 45, 2, "school"),
    ("Mutua Carpentry Workshop", "business", None, 70000, 14, 1, "shop"),
    ("Bright Future Foundation", "business", None, 160000, 45, 0, "ngo"),
    ("Ndungu Fabricators", "business", None, 85000, 21, 2, "shop"),
    ("Tumaini Church Building Committee", "business", None, 240000, 60, 1, "ngo"),
    ("Chege Fundis Group", "business", "wholesale", 130000, 30, 0, "contractor"),
    ("Lakeside Resort", "business", None, 280000, 30, 0, "contractor"),
]
FIRST_NAMES = ["Wanjiru", "Kevin", "Mercy", "Brian", "Faith", "Dennis", "Lucy", "Samuel", "Naomi", "Joseph", "Grace",
               "Peter", "Esther", "Daniel", "Ruth", "Moses"]
LAST_NAMES = ["Kamau", "Otieno", "Wafula", "Njoroge", "Achieng", "Mwangi", "Kiptoo", "Mutua", "Chebet", "Odhiambo",
              "Wambui", "Ndegwa", "Karanja", "Omondi", "Njeri", "Kariuki"]
# expense accounts the demo adds to the standard chart (which has rent, utilities, transport and bank charges)
EXPENSE_ACCOUNTS = [("6310", "Fuel", ""), ("6600", "Cleaning and supplies", ""), ("6700", "Security", ""),
                    ("6910", "Repairs and maintenance", "")]
LEAD_NAMES = ["Kiambu Mixed Day School", "Karanja Builders", "Gatundu Hotel Project", "Juja Student Hostels",
              "Ruiru Dairy Cooperative", "Maina Plumbing Works", "Thika Medical Clinic", "Kenyatta Road Apartments",
              "Wangari Interior Designers", "Ndarugu Farm Supplies", "Biashara Street Traders", "Githurai Lodge",
              "Makongeni Church Extension", "Zimmerman Estate Managers", "Kahawa Tile Centre"]

# ------------------------------------------------------------------------------------------------------ shapes


@dataclass
class Product:
    sku: str
    name: str
    weight: float
    cost: Decimal
    price: Decimal
    supplier: int
    id: UUID | None = None
    wholesale: Decimal | None = None


@dataclass
class PlannedSale:
    day: date
    branch: int                  # index into the branches in use
    at: float                    # 0..1 through the trading day
    device: str                  # D1 counter (cashier) or D2 manager's counter
    cashier: str                 # user key
    lines: list[tuple[str, Decimal]]            # (sku, quantity)
    method: str                  # cash | mobile_money | card | credit | split
    customer: str | None = None
    void: bool = False
    refund: bool = False
    discount: Decimal = Decimal(0)
    tag: str = ""


@dataclass
class Phase:
    t0: datetime
    t1: datetime
    day: date
    shift_days: int
    a: datetime
    b: datetime


@dataclass
class InvoicePlan:
    ref: str
    day: date
    customer: str
    branch: int
    lines: list[tuple[str, Decimal]]
    pay_day: date | None          # None: this one is never paid
    fraction: float = 1.0         # share of the invoice paid on pay_day (the rest is left, or paid later)


@dataclass
class DayPlan:
    day: date
    sales: list[PlannedSale] = field(default_factory=list)
    invoices: list[InvoicePlan] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)       # purchase orders placed today
    deliveries: list[str] = field(default_factory=list)              # refs of purchase orders delivered today
    transfers: list[dict[str, Any]] = field(default_factory=list)    # sent today
    receives: list[str] = field(default_factory=list)                # refs of transfers received today
    adjustments: list[dict[str, Any]] = field(default_factory=list)
    expenses: list[tuple[int, str, int, str, str, Decimal]] = field(default_factory=list)
    special: dict[str, Any] = field(default_factory=dict)
    follow: list[tuple[str, dict[str, Any]]] = field(default_factory=list)   # work made by earlier days (bills, payments)


class Fail(Exception):
    """A step the script cannot go on without."""


# ------------------------------------------------------------------------------------------------------ the API
class Api:
    """The application's HTTP API called in this process, signed in as whoever does the job."""

    def __init__(self, workspace: str) -> None:
        from fastapi.testclient import TestClient

        from ziira.kernel.app import create_app

        self.client = TestClient(create_app())
        self.workspace = workspace
        self.creds: dict[str, tuple[str, str]] = {}
        self.tokens: dict[str, dict[str, str]] = {}
        self.calls = 0

    def register(self, key: str, login: str, password: str = PASSWORD) -> None:
        self.creds[key] = (login, password)
        self.tokens.pop(key, None)

    def headers(self, key: str) -> dict[str, str]:
        if key not in self.tokens:
            login, password = self.creds[key]
            r = self.client.post("/api/v1/auth/sign-in", json={
                "workspace": self.workspace, "login": login, "password": password, "device_id": f"demo-seed-{key}"})
            if r.status_code != 200:
                raise Fail(f"cannot sign in as {key} ({login}): {r.status_code} {r.text[:200]}")
            self.tokens[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return self.tokens[key]

    def raw(self, key: str, method: str, path: str, **kw: Any) -> Any:
        for attempt in (0, 1):
            r = self.client.request(method, f"/api/v1{path}", headers=self.headers(key), **kw)
            self.calls += 1
            if r.status_code == 401 and attempt == 0:
                self.tokens.pop(key, None)
                continue
            return r
        return r

    def call(self, key: str, method: str, path: str, *, expect: tuple[int, ...] = (200, 201, 204), **kw: Any) -> Any:
        r = self.raw(key, method, path, **kw)
        if r.status_code not in expect:
            body = (kw.get("json") and json.dumps(kw["json"], default=str)[:300]) or ""
            raise Fail(f"{method} {path} as {key} -> {r.status_code}: {r.text[:400]}  {body}")
        return r.json() if r.content and r.status_code != 204 else None

    def get(self, key: str, path: str, **params: Any) -> Any:
        return self.call(key, "GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, key: str, path: str, body: dict[str, Any] | None = None, **kw: Any) -> Any:
        return self.call(key, "POST", path, json=body if body is not None else {}, **kw)


# ------------------------------------------------------------------------------------------------------ the seeder
class Seeder:
    def __init__(self, code: str, scale: str, *, owner_email: str | None = None, owner_password: str = PASSWORD,
                 quiet: bool = False) -> None:
        self.code = code
        self.scale = scale
        self.cfg = SCALES[scale]
        self.rng = random.Random(SEED)
        self.owner_email = owner_email or f"owner@{code}.test"
        self.owner_password = owner_password
        self.domain = f"{code}.test"
        self.phases: list[Phase] = []
        self.branches = BRANCHES[: self.cfg["branches"]]
        self.products: dict[str, Product] = {}
        self.t_started = time.time()
        self.counts: dict[str, int] = defaultdict(int)
        self.skipped: dict[str, int] = defaultdict(int)
        self.first_error: dict[str, str] = {}
        self.story_data: dict[str, Any] = {}
        self.bill_n = 0
        self.skipped_all = False

    # ---------------------------------------------------------------- database helpers
    @contextmanager
    def db(self) -> Iterator[Any]:
        from ziira.kernel.db import tenant_session

        with tenant_session(self.tenant_id, admin=True) as s:
            yield s

    def sql(self, statement: str, **params: Any) -> Any:
        with self.db() as s:
            r = s.execute(text(statement), {"t": str(self.tenant_id), "c": str(getattr(self, "company_id", "")), **params})
            return r.all() if r.returns_rows else None

    def one(self, statement: str, **params: Any) -> Any:
        rows = self.sql(statement, **params)
        return rows[0][0] if rows else None

    def db_now(self) -> datetime:
        return self.one("select clock_timestamp()")  # type: ignore[no-any-return]

    # ---------------------------------------------------------------- the clock: phases
    @contextmanager
    def phase(self, day: date, *, start: dtime = OPEN_AT, end: dtime = CLOSE_AT, shift: bool = True) -> Iterator[None]:
        """Everything done inside is made as 'now'; at the end it is moved to `day`, between `start` and `end`."""
        t0 = self.db_now()
        try:
            yield
        finally:
            t1 = self.db_now()
            if t1 <= t0:
                t1 = t0 + timedelta(milliseconds=1)
            a = datetime.combine(day, start, tzinfo=self.zone)
            b = datetime.combine(day, end, tzinfo=self.zone)
            if b <= a:
                b = a + timedelta(seconds=30)
            self.phases.append(Phase(t0, t1, day, (self.today - day).days if shift else 0, a, b))

    # ---------------------------------------------------------------- start up
    def connect(self) -> None:
        from ziira.kernel.context import system_context
        from ziira.kernel.registry import load_event_handlers
        from ziira.kernel.tenants import find_tenant

        load_event_handlers()
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        def _fast_commits(dbapi_connection: Any, _record: Any) -> None:     # demo data only: no waiting for the disk
            cursor = dbapi_connection.cursor()
            cursor.execute("set synchronous_commit = off")
            cursor.close()
            dbapi_connection.commit()

        self._fast_commits = _fast_commits
        event.listen(Engine, "connect", _fast_commits)

        record = find_tenant(self.code)
        self.tenant_id = record.id
        system_context(self.tenant_id)
        self.api = Api(self.code)
        self.api.register("owner", self.owner_email, self.owner_password)
        self.company_id = self.one("select id from kernel.company order by created_at limit 1")
        self.company = str(self.company_id)
        self.zone = ZoneInfo(self._tz_from_api())
        self.today = datetime.now(UTC).astimezone(self.zone).date()
        self.currency = str(self.one("select base_currency from kernel.company where id = :c"))

    def restore(self) -> None:
        """Take back what connect() set up for the length of the run."""
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        with contextlib.suppress(Exception):
            event.remove(Engine, "connect", self._fast_commits)

    def _tz_from_api(self) -> str:
        settings = self.api.get("owner", f"/companies/{self.company}/settings")
        return str(settings.get("timezone") or "UTC")

    def already_filled(self) -> bool:
        self.enable_units()
        return bool(self.one("select 1 from products.product where sku = 'STL-Y10'")) \
            and (self.one("select count(*) from pos.till_session where status = 'closed'") or 0) >= 3

    # ---------------------------------------------------------------- 1. the business, users and reference data
    def enable_units(self) -> None:
        from ziira.kernel.db import tenant_session
        from ziira.kernel.registry import Registry, seed_unit_defaults

        reg = Registry()
        for unit in ("pos", "crm", "finance", "purchasing", "people", "intel", "command", "imports", "catalog_stats",
                     "mpesa"):                     # mpesa: the provider plugin the demo's mobile-money tills use
            reg.enable(self.tenant_id, unit)
        # a business whose units were switched on at different times can lack default grants the others have
        # (a Cashier without the till permission): add what is missing to the default roles, as enabling would
        with tenant_session(self.tenant_id, admin=True) as s:
            for unit in ("products", "inventory", "payments", "pos", "crm", "finance", "purchasing", "people", "intel",
                         "command", "imports"):
                seed_unit_defaults(s, reg.get(unit))

    def setup_branches(self) -> None:
        self.branch_ids: list[UUID] = []
        for i, (code, name, _) in enumerate(self.branches):
            found = self.one("select id from kernel.branch where company_id = :c and code = :code", code=code)
            if found is None and i == 0:
                found = self.one("select id from kernel.branch where company_id = :c order by created_at limit 1")
            if found is None:
                found = self.one(
                    "insert into kernel.branch (tenant_id, company_id, code, name) values (:t, :c, :code, :n) "
                    "returning id", code=code, n=name)
            self.branch_ids.append(found)
        # the demo's own short names are used in logins and keys, whatever the first branch is called in the database
        self.branch_codes = [code for code, _, _ in self.branches]
        self.branch_names = [name for _, name, _ in self.branches]

    def setup_users(self) -> None:
        roles = {r["name"]: r["id"] for r in self.api.get("owner", "/roles")}
        self.role_ids = roles
        existing = {u["email"]: u for u in self.api.get("owner", "/users", limit=200)}
        k = self.branch_codes
        specs: list[tuple[str, str, str, str, int | None]] = [   # key, name, email-local, role, branch index (None: company)
            ("finance", "Faith Wambui", "finance", "Finance Manager", None),
            ("accountant", "Peter Kariuki", "accountant", "Accountant", None),
            ("hr", "Hannah Achieng", "hr", "HR", None),
            ("rep", "Samuel Ndegwa", "salesrep", "Sales Rep", None),
            ("store", "Joseph Karanja", "storekeeper", "Storekeeper", 0),
        ]
        names = {"THK": ("Grace Njeri", "Lucy Chebet"), "JUJ": ("Daniel Omondi", "Esther Wafula"),
                 "RUI": ("Moses Mutua", "Ruth Kiptoo")}
        extra = {"JUJ": "Brian Mwangi"}             # the second Juja cashier (story 1)
        for i, code in enumerate(k):
            word = self.branch_names[i].lower()
            mgr, cash = names[code]
            specs.append((f"mgr.{code}", mgr, f"manager.{word}", "Branch Manager", i))
            specs.append((f"cash.{code}", cash, f"cashier.{word}", "Cashier", i))
            if code in extra:
                specs.append((f"cash2.{code}", extra[code], f"cashier2.{word}", "Cashier", i))
        self.users: dict[str, dict[str, Any]] = {"owner": {"name": "Demo Owner", "email": self.owner_email,
                                                           "role": "Owner", "branch": None}}
        self.api.register("owner", self.owner_email, self.owner_password)
        for key, name, local, role, bi in specs:
            email = f"{local}@{self.domain}"
            user = existing.get(email)
            if user is None:
                user = self.api.post("owner", "/users", {"full_name": name, "email": email, "password": PASSWORD})
                self.api.post("owner", f"/users/{user['id']}/roles", {
                    "role_id": roles[role], "scope": "branch" if bi is not None else "company",
                    "company_id": self.company, "branch_id": str(self.branch_ids[bi]) if bi is not None else None})
            self.api.register(key, email)
            self.users[key] = {"name": name, "email": email, "role": role, "id": user["id"],
                               "branch": None if bi is None else self.branch_codes[bi]}
        me = self.api.get("owner", "/auth/me")
        self.users["owner"]["id"] = me.get("user_id") or me.get("id")


    def all(self, who: str, path: str, **params: Any) -> list[dict[str, Any]]:
        """Every row of a list endpoint (paged)."""
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.api.get(who, path, limit=200, offset=offset, **params)
            if isinstance(page, dict):
                page = page.get("items", [])
            out += page
            if len(page) < 200:
                return out
            offset += 200

    def pick_products(self) -> list[tuple[Any, ...]]:
        """The products of this scale, with the shop's selling prices (tax included): about 18% over the table's, whose
        figures are the supplier's side; cement is sold close to cost, as it is in real shops."""
        if self.scale == "tiny":
            wanted = ["CEM-50KG", "SND-50KG", "STL-Y10", "ROOF-G30", "ROF-NLS", "PVC-1IN", "SWT-1G", "BLB-LED9",
                      "PAINT-W4L", "BRS-3IN", "NAIL-4IN", "HMR-16"]
            rows = [p for p in PRODUCTS if p[0] in wanted]
        else:
            rows = PRODUCTS[: self.cfg["products"]]
        out = []
        for sku, name, cat, uom, tax, cost, price, weight, sup in rows:
            shop = 820 if sku == "CEM-50KG" else int(round(price * 1.18 / 5) * 5)
            out.append((sku, name, cat, uom, tax, cost, shop, weight, sup))
        return out

    def setup_catalogue(self) -> None:
        started = time.time()
        co = self.company
        owner = "owner"
        uoms = {u["code"]: u["id"] for u in self.api.get(owner, "/products/uoms")}
        for code, name in UOMS:
            if code not in uoms:
                uoms[code] = self.api.post(owner, "/products/uoms", {"code": code, "name": name})["id"]
        taxes = {t["code"]: t["id"] for t in self.api.get(owner, "/products/tax-codes")}
        for code, name, rate in TAXES:
            if code not in taxes:
                taxes[code] = self.api.post(owner, "/products/tax-codes", {"code": code, "name": name, "vat_rate": rate})["id"]
        # the business may already have a tax code the old demo made (VAT16): the seeded products use the new ones
        self.uoms, self.taxes = uoms, taxes
        chosen = self.pick_products()
        existing = {p["sku"]: p for p in self.all(owner, "/products/products")}
        for sku, name, _cat, uom, tax, cost, price, weight, sup in chosen:
            product = existing.get(sku)
            if product is None:
                product = self.api.post(owner, "/products/products", {
                    "company_id": co, "sku": sku, "name": name, "base_uom_id": uoms[uom], "tax_code_id": taxes[tax],
                    "reorder_level": str(max(2, int(weight * 1.5)))})
            self.products[sku] = Product(sku, product["name"], weight, Decimal(cost), Decimal(price), sup, UUID(product["id"]))
        # categories and barcodes have no endpoint yet: written directly, like an import would
        cat_ids = []
        for name in CATEGORIES:
            found = self.one("select id from products.category where name = :n", n=name)
            cat_ids.append(found or self.one(
                "insert into products.category (tenant_id, name) values (:t, :n) returning id", n=name))
        for i, (sku, _name, cat, *_rest) in enumerate(chosen):
            self.sql("update products.product set category_id = :cat where id = :p and category_id is null",
                     cat=str(cat_ids[cat]), p=str(self.products[sku].id))
            self.sql("insert into products.barcode (tenant_id, product_id, code) values (:t, :p, :code) "
                     "on conflict do nothing", p=str(self.products[sku].id), code=f"6{(i + 1) * 7919:012d}")
        # price lists: Retail (default) and Wholesale (for customers in the wholesale group)
        lists = {pl["name"]: pl for pl in self.api.get(owner, "/products/price-lists")}
        retail = lists.get("Retail") or lists.get(next(iter(lists), "")) if lists else None
        if retail is None:
            retail = self.api.post(owner, "/products/price-lists", {"company_id": co, "name": "Retail", "is_default": True})
        wholesale = lists.get("Wholesale") or self.api.post(owner, "/products/price-lists", {
            "company_id": co, "name": "Wholesale", "customer_group": "wholesale"})
        self.price_list_ids = {"retail": retail["id"], "wholesale": wholesale["id"]}
        if "DELIVERY" not in existing:
            delivery = self.api.post(owner, "/products/products", {
                "company_id": co, "sku": "DELIVERY", "name": "Delivery within town", "base_uom_id": uoms["PCS"],
                "tax_code_id": taxes["STD"], "product_type": "service"})
            self.api.call(owner, "PUT", f"/products/price-lists/{self.price_list_ids["retail"]}/prices", json={
                "product_id": delivery["id"], "price": "500", "valid_from": (self.today - timedelta(days=self.cfg["days"] + 30)).isoformat()},
                expect=(200, 201, 204, 409))
        valid_from = (self.today - timedelta(days=self.cfg["days"] + 30)).isoformat()
        for p in self.products.values():
            self.api.call(owner, "PUT", f"/products/price-lists/{retail['id']}/prices",
                          json={"product_id": str(p.id), "price": str(p.price), "valid_from": valid_from},
                          expect=(200, 201, 204, 409))
            p.wholesale = money(p.price * Decimal("0.93"))
            self.api.call(owner, "PUT", f"/products/price-lists/{wholesale['id']}/prices",
                          json={"product_id": str(p.id), "price": str(p.wholesale), "valid_from": valid_from},
                          expect=(200, 201, 204, 409))
        # a business that already had prices (the old demo) keeps them: the plan follows what the price lists say today
        for key, plist in (("retail", retail), ("wholesale", wholesale)):
            rows = self.api.get(owner, f"/products/price-lists/{plist['id']}/prices")
            rows = rows if isinstance(rows, list) else rows.get("items", [])
            latest: dict[str, tuple[str, Decimal]] = {}
            today = self.today.isoformat()
            for row in rows:
                current = row["valid_from"] <= today and (not row.get("valid_to") or row["valid_to"] >= today)
                if current and (row["product_id"] not in latest or row["valid_from"] >= latest[row["product_id"]][0]):
                    latest[row["product_id"]] = (row["valid_from"], Decimal(str(row["price"])))
            for p in self.products.values():
                if str(p.id) in latest:
                    if key == "retail":
                        p.price = latest[str(p.id)][1]
                    else:
                        p.wholesale = latest[str(p.id)][1]
        log(f"{len(uoms)} units of measure, {len(taxes)} tax codes, {len(self.products)} products, 2 price lists", started)

    def setup_places(self) -> None:
        """Locations, payment accounts and tills for each branch; the chart of accounts."""
        started = time.time()
        co, owner = self.company, "owner"
        self.api.post(owner, f"/finance/companies/{co}/books", expect=(200, 201, 204, 409))
        locs = self.all(owner, "/inventory/locations")
        accounts = self.all(owner, "/payments/accounts")
        devices = self.all("owner", "/pos/devices")
        self.locations: list[str] = []
        self.pay_accounts: list[dict[str, str]] = []
        self.devices: dict[tuple[int, str], str] = {}
        for i, bid in enumerate(self.branch_ids):
            code = self.branch_codes[i]
            loc = next((x for x in locs if x["branch_id"] == str(bid) and x["kind"] in ("store", "warehouse")), None)
            if loc is None:
                loc = self.api.post(owner, "/inventory/locations", {
                    "company_id": co, "branch_id": str(bid), "code": f"{code}-STORE", "name": f"{self.branch_names[i]} store"})
            self.locations.append(loc["id"])
            accts: dict[str, str] = {}
            for kind, label, extra in (("cash", "till cash", {}), ("mobile_money", "mobile money",
                                       {"shortcode": f"60{i}638", "provider": "fake", "provider_config": {"till_type": "till"}}),
                                       ("card", "card terminal", {})):
                found = next((a for a in accounts if a["branch_id"] == str(bid) and a["kind"] == kind), None)
                if found is None:
                    found = self.api.post(owner, "/payments/accounts", {
                        "company_id": co, "branch_id": str(bid), "kind": kind,
                        "name": f"{self.branch_names[i]} {label}", **extra})
                accts[kind] = found["id"]
            self.pay_accounts.append(accts)
            for dcode, dname in (("D1", "counter 1"), ("D2", "manager counter")):
                found = next((d for d in devices if d["branch_id"] == str(bid) and d["code"] == dcode), None)
                if found is None:
                    found = self.api.post(owner, "/pos/devices", {
                        "branch_id": str(bid), "code": dcode, "name": f"{self.branch_names[i]} {dname}",
                        "location_id": loc["id"]})
                self.devices[(i, dcode)] = found["id"]
        bank = next((a for a in accounts if a["kind"] == "bank"), None) or self.api.post(owner, "/payments/accounts", {
            "company_id": co, "kind": "bank", "name": "Main bank account", "bank_account_masked": "****4821"})
        self.bank_account = bank["id"]
        ledger = {a["code"]: a for a in self.all(owner, "/finance/accounts")}
        self.ledger = ledger
        for code, name, _ in EXPENSE_ACCOUNTS:
            if code not in ledger:
                ledger[code] = self.api.post(owner, "/finance/accounts", {
                    "company_id": co, "code": code, "name": name, "type": "expense"})
        if "2400" not in ledger:
            ledger["2400"] = self.api.post(owner, "/finance/accounts", {
                "company_id": co, "code": "2400", "name": "Income tax payable", "type": "liability"})
        if "2410" not in ledger:
            ledger["2410"] = self.api.post(owner, "/finance/accounts", {
                "company_id": co, "code": "2410", "name": "Retirement fund payable", "type": "liability"})
        if "2420" not in ledger:
            ledger["2420"] = self.api.post(owner, "/finance/accounts", {
                "company_id": co, "code": "2420", "name": "Health levy payable", "type": "liability"})
        log(f"{len(self.branch_ids)} branches with stores, payment accounts and tills; ledger accounts", started)


    def put_in_capital(self) -> None:
        """The owner's money in the bank when the history starts, so the bank is not overdrawn by the first supplier payment."""
        if self.one("select 1 from finance.manual_journal where description = :d limit 1", d="Owner's capital paid into the bank"):
            return                       # an earlier run that stopped half way already did this
        day = self.start - timedelta(days=2)
        j = self.api.post("finance", "/finance/manual-journals", {
            "company_id": self.company, "entry_date": day.isoformat(), "description": "Owner's capital paid into the bank",
            "lines": [{"account_id": self.ledger["1020"]["id"], "debit": "1500000", "description": "Capital paid in"},
                      {"account_id": self.ledger["3000"]["id"], "credit": "1500000", "description": "Owner's capital"}]})
        self.api.post("finance", f"/finance/manual-journals/{j['id']}/submit")
        self.settle_approvals("owner")

    # ---------------------------------------------------------------- approvals, customers, suppliers
    def setup_rules(self) -> None:
        """Approval rules a real business would have: big orders and bills, big credit limits, adjustments, expenses."""
        co, owner = self.company, "owner"
        roles = self.role_ids
        have = {(r["doc_type"], r["step"]) for r in self.api.get(owner, "/approvals/rules")}
        rules = [("purchase_order", "Finance Manager", 150000), ("supplier_bill", "Finance Manager", 250000),
                 ("credit_limit_change", "Owner", 200000), ("stock_adjustment", "Finance Manager", 5000),
                 ("expense", "Finance Manager", 30000), ("sales_return", "Finance Manager", 12000),
                 ("supplier_bank_change", "Finance Manager", 0)]
        for doc_type, role, minimum in rules:
            if (doc_type, 1) not in have:
                self.api.post(owner, "/approvals/rules", {
                    "company_id": co, "doc_type": doc_type, "approver_role_id": roles[role], "step": 1,
                    "min_amount": str(minimum), "forbid_creator": True})
        for category, code, label, note in (
                ("price_override", "CONTRACTOR_RATE", "Agreed contractor rate", False),
                ("stock_adjustment", "WATER_DAMAGE", "Stock spoiled by water", False),
                ("void", "PRICE_DISPUTE", "Customer disputed the price", False),
                ("write_off", "SCRAP", "Sold as scrap metal", True)):
            self.api.post(owner, "/settings/reason-codes", {"category": category, "code": code, "label": label,
                                                            "requires_note": note}, expect=(200, 201, 409))
        self.api.call(owner, "PATCH", f"/companies/{co}/settings", json={
            "count_variance_threshold": "5000", "weekend_days": ["sat", "sun"]},
            expect=(200, 201, 204, 422))

    def settle_approvals(self, who: str, limit: int = 100) -> int:
        """Approve whatever is waiting for this person (used for rules the demo owner/finance manager works through)."""
        done = 0
        for req in self.api.get(who, "/approvals/pending")[:limit]:
            r = self.api.raw(who, "POST", f"/approvals/{req['id']}/decision", json={"approve": True, "note": "Checked"})
            if r.status_code in (200, 201, 204):
                done += 1
        return done

    def setup_parties(self) -> None:
        started = time.time()
        co = self.company
        existing_c = {c["name"]: c for c in self.all("owner", "/crm/customers")}
        self.customers: dict[str, dict[str, Any]] = {}
        chosen = CUSTOMERS[: self.cfg["customers"]]
        for i, (name, kind, group, limit, terms, home, how) in enumerate(chosen):
            c = existing_c.get(name)
            if c is None:
                c = self.api.post("rep", "/crm/customers", {
                    "company_id": co, "name": name, "kind": kind, "customer_group": group, "payment_terms_days": terms,
                    "phone": f"+2547{10000000 + i * 137531:08d}"[:13], "email": f"accounts{i + 1}@{self._slug(name)}.test",
                    "tax_id": f"P05{100000 + i * 7919:07d}A" if i % 3 == 0 else None})
            self.customers[name] = {"id": c["id"], "limit": limit, "terms": terms, "home": min(home, len(self.branches) - 1),
                                    "how": how, "group": group}
        for c in self.customers.values():
            if self.one("select 1 from crm.customer where id = :i and credit_limit = :l", i=str(c["id"]), l=c["limit"]):
                continue
            self.api.post("finance", f"/crm/customers/{c['id']}/credit", {
                "credit_limit": str(c["limit"]), "payment_terms_days": c["terms"], "reason": "Opening terms agreed with the owner"})
        self.settle_approvals("owner")
        # suppliers: the ones the chosen products use, then the rest up to the scale
        used = {p.supplier for p in self.products.values()}
        wanted = sorted(used | set(range(self.cfg["suppliers"])))
        existing_s = {s["name"]: s for s in self.all("owner", "/purchasing/suppliers")}
        self.suppliers: dict[int, dict[str, Any]] = {}
        for idx in wanted:
            name, bank, acct, terms = SUPPLIERS[idx]
            s = existing_s.get(name)
            if s is None:
                s = self.api.post("accountant", "/purchasing/suppliers", {
                    "company_id": co, "code": f"S{idx + 1:03d}", "name": name, "payment_terms_days": terms,
                    "phone": f"+2547{20000000 + idx * 91733:08d}"[:13], "email": f"sales@{self._slug(name)}.test",
                    "tax_id": f"P05{200000 + idx * 4421:07d}B"})
            self.suppliers[idx] = {"id": s["id"], "name": name, "terms": terms, "bank": (bank, acct),
                                   "inv": f"{''.join(w[0] for w in name.split()[:3]).upper()}"}
        confirmed = 0
        for idx, s in self.suppliers.items():
            bank, acct = s["bank"]
            if self.one("select 1 from purchasing.supplier_bank_account where supplier_id = :s limit 1", s=str(s["id"])):
                continue
            b = self.api.post("finance", f"/purchasing/suppliers/{s['id']}/bank-accounts", {
                "method": "bank", "account_no": acct, "bank_name": bank, "account_name": s["name"]})
            if idx in UNCONFIRMED and len(self.suppliers) > 4:
                continue                      # two stay "proposed": waiting for someone to confirm them
            self.api.post("owner", f"/purchasing/bank-accounts/{b['id']}/confirm", {
                "confirmation_method": "phone_callback", "note": "Called the supplier on the number on their contract"})
            confirmed += 1
        self.settle_approvals("finance")
        log(f"{len(self.customers)} customers with credit, {len(self.suppliers)} suppliers "
            f"({confirmed} bank accounts confirmed)", started)

    @staticmethod
    def _slug(name: str) -> str:
        return "".join(ch for ch in name.lower() if ch.isalnum())[:24] or "example"

    # ---------------------------------------------------------------- the run
    def adopt_earlier_attempt(self) -> None:
        """A run that stopped half way left its set-up rows made 'now'. They are moved with this run's set-up, so the
        business never shows reference data made today under a history that starts months ago."""
        marker = self.one("select min(created_at) from kernel.branch where company_id = :c and code in ('JUJ', 'RUI')") \
            if len(self.branches) > 1 else None
        marker = marker or self.one("select created_at from products.product where sku = 'STL-Y10'")
        if marker is None:
            return
        log("an earlier run stopped half way: its set-up is kept and finished")
        began = marker - timedelta(seconds=2)
        now = self.db_now()
        self.phases.append(Phase(began, now, self.start - timedelta(days=2), 0,
                                 datetime.combine(self.start - timedelta(days=2), dtime(8, 0), tzinfo=self.zone),
                                 datetime.combine(self.start - timedelta(days=2), dtime(9, 0), tzinfo=self.zone)))

    def make_consistent_first(self) -> None:
        """The business must be consistent before anything is added to it (the old demo posted its opening stock before
        Finance was switched on): `ziira verify`, and `--fix` when it reports something, as the CLI offers."""
        from ziira.kernel import cli

        def verify(*extra: str) -> int:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return int(cli.main(["verify", self.code, *extra]))

        if verify() != 0:
            log("the business was not consistent to begin with: running `ziira verify --fix` first")
            verify("--fix")
            if verify() != 0:
                raise Fail("`ziira verify` still reports problems in the business before any demo data is added: "
                           "fix those first, or start over with --reset")

    def run(self, stop_after: str | None = None) -> None:
        self.ok = True
        self.moved = 0
        self.make_consistent_first()
        self.seed_started = self.db_now()
        self.start = self.today - timedelta(days=self.cfg["days"])
        steps: list[tuple[str, Callable[[], None]]] = [
            ("branches", self.setup_branches), ("users", self.setup_users),
            ("catalogue", self.setup_catalogue), ("places", self.setup_places), ("rules", self.setup_rules),
            ("capital", self.put_in_capital), ("parties", self.setup_parties),
        ]
        self.adopt_earlier_attempt()
        with self.phase(self.start - timedelta(days=2), start=dtime(9, 0), end=dtime(11, 0), shift=False):
            for name, step in steps:
                step()
                if stop_after == name:
                    return
        self.plan()
        if stop_after == "plan":
            return
        self.ensure_periods()
        self.execute()
        self.people()
        self.crm_pipeline()
        self.seed_end = self.db_now()
        self.move_phases()
        self.after_move()
        self.finish()

    # ================================================================ the plan (pure Python, no database writes)
    def typical_qty(self, sku: str) -> float:
        return max(1.0, min(10.0, 2500.0 / float(self.products[sku].price)))

    def draw_qty(self, sku: str, scale: float = 1.0) -> int:
        mean = self.typical_qty(sku) * scale
        return max(1, int(self.rng.gauss(mean, mean * 0.6) + 0.5))

    def plan(self) -> None:
        """Decide what happens on each day: sales, orders and deliveries, transfers, counts, invoices, expenses.
        The stock the shops hold is followed in `self.mirror` so no sale, transfer or invoice needs stock that is not there."""
        rng, cfg = self.rng, self.cfg
        nb = len(self.branches)
        self.days = [self.today - timedelta(days=n) for n in range(cfg["days"], 0, -1)]
        self.start = self.days[0]
        self.plans: dict[date, DayPlan] = {d: DayPlan(d) for d in self.days}
        self.ref_n = 0
        shares = [b[2] for b in self.branches]
        shares = [s / sum(shares) for s in shares]
        factor = {}
        for d in self.days:
            f = DOW_FACTOR[d.weekday()] * (1.25 if d.day in (25, 26, 27, 28, 1, 2, 3) else 1.0) * rng.uniform(0.88, 1.12)
            factor[d] = f
        total_factor = sum(factor.values())
        skus = list(self.products)
        W = sum(p.weight for p in self.products.values())
        # expected units a day of each product at each branch (counter + invoices), for stocking
        per_day = [cfg["sales"] * s / len(self.days) for s in shares]
        self.rate = {(b, sku): per_day[b] * 2.4 * (self.products[sku].weight / W) * self.typical_qty(sku) * 1.35
                     for b in range(nb) for sku in skus}
        stories: set[int] = cfg["stories"]
        story_product = "PAINT-W4L" if (5 in stories and nb >= 3 and "PAINT-W4L" in self.products) else None
        self.story_product = story_product
        # ---- the stock at the start: what the business already has, and opening stock for the rest
        have = self.stock_now()
        self.opening: dict[int, list[tuple[str, int, Decimal]]] = defaultdict(list)
        self.mirror: dict[tuple[int, str], Decimal] = {}
        for b in range(nb):
            for sku in skus:
                key = (b, sku)
                if key in have:
                    self.mirror[key] = have[key][0]
                    continue
                cover = rng.uniform(28, 42)
                qty = max(4 if self.products[sku].price < 3000 else 2, math.ceil(self.rate[key] * cover))
                if story_product and b == 2 and sku == story_product:
                    qty = math.ceil(self.rate[key] * len(self.days) * 0.93)
                self.opening[b].append((sku, qty, self.products[sku].cost))
                self.mirror[key] = Decimal(qty)
        self.on_order: dict[tuple[int, str], Decimal] = defaultdict(Decimal)
        self.po_list: list[dict[str, Any]] = []
        order_dow = {0: (0,), 1: (1,), 2: (2,)} if nb > 1 else {0: (0,)}
        lead = {0: 3, 1: 3, 2: 3, 3: 4, 4: 3, 5: 2, 6: 3, 7: 2, 8: 3, 9: 5, 10: 2, 11: 4}
        incoming: dict[date, list[tuple[int, str, int]]] = defaultdict(list)
        transfers_in: dict[date, list[tuple[int, str, int]]] = defaultdict(list)
        self.exposure: dict[str, float] = defaultdict(float)
        # ---- customers' invoices: when each is raised
        inv_days: dict[date, list[str]] = defaultdict(list)
        for name, c in self.customers.items():
            if name == "Otieno Construction Co" and 4 in cfg["stories"]:
                for back in (85, 60, 35):
                    if self.today - timedelta(days=back) in self.plans:
                        inv_days[self.today - timedelta(days=back)].append(name)
                continue
            n = {"contractor": 7, "shop": 5, "school": 3, "ngo": 4}[c["how"]]
            n = max(1 if len(self.days) < 20 else 2, round(n * len(self.days) / 90))
            pool = [d for d in self.days[3:-1] if d.weekday() < 6]
            for d in sorted(rng.sample(pool, min(n, len(pool)))):
                inv_days[d].append(name)
        transfer_days = set(rng.sample(self.days[5:-2], min(max(2, len(self.days) // 8), len(self.days) - 8))) \
            if nb > 1 and len(self.days) > 12 else set()
        adjust_days = set(rng.sample(self.days[4:-3], min(5, max(1, len(self.days) // 15)))) if len(self.days) > 8 else set()
        story_days = self.story_days()
        for d in self.days:
            dp = self.plans[d]
            # morning: deliveries and transfers arrive
            for b, sku, qty in incoming.pop(d, []):
                self.mirror[(b, sku)] += qty
                self.on_order[(b, sku)] -= qty
            for b, sku, qty in transfers_in.pop(d, []):
                self.mirror[(b, sku)] += qty
            # invoices raised today (bulk buyers, delivered from their home branch)
            for name in inv_days.get(d, []):
                inv = self.plan_invoice(d, name, story_days)
                if inv:
                    dp.invoices.append(inv)
            # sales
            self.plan_sales(d, dp, factor[d] / total_factor, shares, story_days)
            # stock transfers between branches
            if d in transfer_days:
                self.plan_transfer(d, dp, transfers_in)
            if d in adjust_days:
                self.plan_adjustment(d, dp)
            # ordering from suppliers, on each branch's order days
            for b in range(nb):
                if d.weekday() in order_dow[b if nb > 1 else 0] and ((d - self.start).days // 7) % 2 == b % 2:
                    self.plan_orders(d, b, dp, lead, incoming)      # each branch orders every second week
            self.plan_special(d, dp, story_days)
        self.plan_cement_prices()
        self.plan_expenses(story_days)
        n_sales = sum(len(dp.sales) for dp in self.plans.values())
        log(f"plan: {len(self.days)} days, {n_sales} counter sales, {sum(len(dp.invoices) for dp in self.plans.values())} "
            f"invoices, {len(self.po_list)} purchase orders, {len(transfer_days)} transfers")

    def story_days(self) -> dict[str, date]:
        t = self.today
        return {"voids": t - timedelta(days=1), "short": t - timedelta(days=4 if len(self.days) > 20 else 3),
                "writeoff": t - timedelta(days=3), "dup_bill": t - timedelta(days=8), "expense": t - timedelta(days=2),
                "count": t - timedelta(days=min(14, len(self.days) // 3)), "ghost_credit": t - timedelta(days=3)}

    def stock_now(self) -> dict[tuple[int, str], tuple[Decimal, Decimal]]:
        """What each branch already holds of the products used (before anything is made)."""
        rows = self.sql(
            "select l.branch_id, p.sku, sum(b.quantity) from inventory.stock_balance b "
            "join inventory.location l on l.id = b.location_id join products.product p on p.id = b.product_id "
            "where l.kind in ('store', 'warehouse') group by 1, 2")
        index = {str(b): i for i, b in enumerate(self.branch_ids)}
        out: dict[tuple[int, str], tuple[Decimal, Decimal]] = {}
        for branch_id, sku, qty in rows:
            if str(branch_id) in index and sku in self.products:
                out[(index[str(branch_id)], sku)] = (Decimal(qty), Decimal(0))
        # a product that has had stock at the place (even sold down to nothing) cannot take opening stock again
        hist = self.sql("select l.branch_id, p.sku from inventory.stock_movement m "
                        "join inventory.location l on l.id = m.location_id join products.product p on p.id = m.product_id "
                        "group by 1, 2")
        for branch_id, sku in hist:
            if str(branch_id) in index and sku in self.products:
                out.setdefault((index[str(branch_id)], sku), (Decimal(0), Decimal(0)))
        return out

    # ---------------------------------------------------------------- sales of a day
    def cashier_for(self, d: date, b: int) -> str:
        code = self.branch_codes[b]
        if f"cash2.{code}" in self.users:
            recent = d >= self.today - timedelta(days=10) and 1 in self.cfg["stories"]
            if recent or d.weekday() in (2, 3, 4):
                return f"cash2.{code}"
        return f"cash.{code}"

    def plan_sales(self, d: date, dp: "DayPlan", weight: float, shares: list[float], story_days: dict[str, date]) -> None:
        rng, cfg = self.rng, self.cfg
        nb = len(self.branches)
        counter_customers = [n for n, c in self.customers.items() if c["how"] in ("shop", "school", "ngo", "contractor")]
        for b in range(nb):
            expected = cfg["sales"] * shares[b] * weight
            n = int(expected) + (1 if rng.random() < expected - int(expected) else 0)
            if 9 in cfg["stories"] and d == self.today - timedelta(days=1) and b == 0 and nb > 1:
                n = 0                                           # story 9: the busiest branch sells nothing that day
            if 1 in cfg["stories"] and b == 1 and d >= self.today - timedelta(days=3):
                n = max(n, 11)                                  # enough sales for the void rate to mean something
            if 1 in cfg["stories"] and b == 1 and self.today - timedelta(days=10) <= d < self.today - timedelta(days=3):
                n = max(n, 8)
            stamps = sorted(self.sale_time(rng) for _ in range(n))
            for at in stamps:
                s = self.plan_one_sale(d, b, at, counter_customers)
                if s is not None:
                    dp.sales.append(s)
        dp.sales.sort(key=lambda x: x.at)
        self.plan_voids(d, dp, story_days)

    @staticmethod
    def sale_time(rng: random.Random) -> float:
        pick = rng.random()
        centre = 0.18 if pick < 0.30 else (0.50 if pick < 0.62 else 0.78)
        return min(0.99, max(0.01, rng.gauss(centre, 0.09)))

    def plan_one_sale(self, d: date, b: int, at: float, counter_customers: list[str]) -> "PlannedSale | None":
        rng = self.rng
        manager = rng.random() < 0.13
        device = "D2" if manager else "D1"
        cashier = f"mgr.{self.branch_codes[b]}" if manager else self.cashier_for(d, b)
        n_lines = rng.choices([1, 2, 3, 4, 5, 6], weights=[40, 32, 16, 8, 3, 1])[0]
        skus = list(self.products)
        weights = [self.products[s].weight for s in skus]
        lines: list[tuple[str, Decimal]] = []
        chosen: set[str] = set()
        for _ in range(n_lines):
            sku = rng.choices(skus, weights)[0]
            if sku in chosen:
                continue
            chosen.add(sku)
            have = self.mirror[(b, sku)]
            qty = min(Decimal(self.draw_qty(sku, 1.4 if manager else 1.0)), have)
            if qty <= 0:
                continue
            if self.story_product == sku and b == 2 and have <= 0:
                continue
            lines.append((sku, qty))
            self.mirror[(b, sku)] -= qty
        if not lines:
            return None
        method = rng.choices(["cash", "mobile_money", "card", "split"], weights=[43, 37, 14, 6])[0]
        customer = None
        total = sum(float(self.products[s].price) * float(q) for s, q in lines)
        if counter_customers and rng.random() < 0.07:
            name = rng.choice(counter_customers)
            c = self.customers[name]
            if (c["home"] == b or rng.random() < 0.3) and self.exposure[name] + total < 0.5 * c["limit"]:
                customer, method = name, "credit"
                self.exposure[name] += total
        discount = Decimal(0)
        if manager and rng.random() < 0.3 and total < 25000:
            discount = money(Decimal(total) * Decimal(rng.choice([0.02, 0.03, 0.04])))
        return PlannedSale(d, b, at, device, cashier, lines, method, customer, discount=discount)

    def plan_voids(self, d: date, dp: "DayPlan", story_days: dict[str, date]) -> None:
        rng, cfg = self.rng, self.cfg
        t = self.today
        for s in dp.sales:
            if s.device == "D1" and rng.random() < 0.02:
                s.void = True
        if 1 in cfg["stories"] and len(self.branches) > 1:
            quota = {t - timedelta(days=1): 3, t - timedelta(days=2): 2, t - timedelta(days=3): 1,
                     t - timedelta(days=5): 1, t - timedelta(days=8): 1}
            if d in quota:
                mine = [s for s in dp.sales if s.cashier == "cash2.JUJ" and s.device == "D1"]
                for s in mine:
                    s.void = False
                for s in rng.sample(mine, min(quota[d], len(mine))):
                    s.void = True
                    s.tag = "story1"
            elif d >= t - timedelta(days=10):
                for s in dp.sales:
                    if s.cashier == "cash2.JUJ":
                        s.void = False
        # a few returns, each decided the day of the sale
        for s in dp.sales:
            if not s.void and rng.random() < 0.012 and s.method != "credit":
                s.refund = True

    def plan_invoice(self, d: date, name: str, story_days: dict[str, date]) -> "InvoicePlan | None":
        rng = self.rng
        c = self.customers[name]
        b = c["home"]
        bulk = [s for s in self.products if self.products[s].price >= 150 or self.products[s].weight >= 4]
        weights = [self.products[s].weight for s in bulk]
        lines: list[tuple[str, Decimal]] = []
        chosen: set[str] = set()
        scale = {"contractor": 7.0, "shop": 4.0, "school": 3.0, "ngo": 5.0}[c["how"]]
        for _ in range(rng.randint(2, 5)):
            sku = rng.choices(bulk, weights)[0]
            if sku in chosen:
                continue
            chosen.add(sku)
            qty = min(Decimal(self.draw_qty(sku, scale)), self.mirror[(b, sku)] - 2)
            if qty < 1 or (self.story_product == sku and b == 2):
                continue
            lines.append((sku, qty))
        if not lines:
            return None
        total = sum(float(self.products[s].price) * float(q) for s, q in lines)
        if self.exposure[name] + total > 0.85 * c["limit"]:
            return None
        for sku, qty in lines:
            self.mirror[(b, sku)] -= qty
        self.exposure[name] += total
        behaviour = self.behaviour(name)
        terms = c["terms"]
        if behaviour == "good":
            delay = rng.randint(-5, 8)
        elif behaviour == "slow":
            delay = rng.randint(12, 38)
        else:
            delay = rng.randint(40, 120)
        pay_day: date | None = d + timedelta(days=terms + delay)
        if name == "Otieno Construction Co" and d == self.today - timedelta(days=85):
            pay_day = None                                  # story 4: this invoice is never paid
        self.ref_n += 1
        return InvoicePlan(f"inv{self.ref_n}", d, name, b, lines, pay_day, 1.0 if behaviour != "slow" or rng.random() < 0.7 else 0.5)

    def behaviour(self, name: str) -> str:
        i = [n for n in self.customers].index(name)
        if name == "Otieno Construction Co":
            return "good"
        return ["good", "good", "slow", "good", "slow", "good", "bad", "good", "slow", "good", "good", "slow"][i % 12]

    def plan_transfer(self, d: date, dp: "DayPlan", transfers_in: dict[date, list[tuple[int, str, int]]]) -> None:
        rng = self.rng
        nb = len(self.branches)
        src = 0 if rng.random() < 0.7 else rng.randrange(nb)
        dst = rng.choice([b for b in range(nb) if b != src])
        lines: list[tuple[str, Decimal]] = []
        for sku in rng.sample(list(self.products), 12):
            need = math.ceil(self.rate[(dst, sku)] * 9)
            spare = self.mirror[(src, sku)] - math.ceil(self.rate[(src, sku)] * 14)
            if self.story_product == sku:
                continue
            qty = min(need, int(spare))
            if qty >= 2 and len(lines) < 5:
                lines.append((sku, Decimal(qty)))
        if not lines:
            return
        for sku, qty in lines:
            self.mirror[(src, sku)] -= qty
        receive = d + timedelta(days=1)
        left_in_transit = d == self.today - timedelta(days=6) or receive > self.today - timedelta(days=1)
        self.ref_n += 1
        dp.transfers.append({"ref": f"tr{self.ref_n}", "src": src, "dst": dst, "lines": lines, "receive_on": None if left_in_transit else receive})
        if not left_in_transit:
            self.plans[receive].receives.append(f"tr{self.ref_n}")
            for sku, qty in lines:
                transfers_in[receive].append((dst, sku, int(qty)))

    def plan_adjustment(self, d: date, dp: "DayPlan") -> None:
        rng = self.rng
        b = rng.randrange(len(self.branches))
        cheap = [s for s in self.products if self.products[s].cost <= 260 and self.mirror[(b, s)] > 12]
        if not cheap:
            return
        sku = rng.choice(cheap)
        qty = rng.randint(1, 4)
        self.mirror[(b, sku)] -= qty
        reason = rng.choice(["DAMAGED", "DAMAGED", "EXPIRED"])
        dp.adjustments.append({"branch": b, "sku": sku, "qty": -qty, "reason": reason, "note": "Found damaged in the store"})

    def plan_orders(self, d: date, b: int, dp: "DayPlan", lead: dict[int, int],
                    incoming: dict[date, list[tuple[int, str, int]]]) -> None:
        by_supplier: dict[int, list[tuple[str, int]]] = defaultdict(list)
        for sku, p in self.products.items():
            if self.story_product == sku and b == 2:
                continue
            key = (b, sku)
            proj = self.mirror[key] + self.on_order[key]
            if proj >= self.rate[key] * 20:
                continue
            pack = 10 if p.price < 500 else (5 if p.price < 2000 else 1)
            qty = max(pack, math.ceil((self.rate[key] * 40 - float(proj)) / pack) * pack) + rng_extra(self.rng)
            by_supplier[p.supplier].append((sku, qty))
        for sup, lines in sorted(by_supplier.items()):
            recv = d + timedelta(days=lead[sup])
            self.ref_n += 1
            po = {"ref": f"po{self.ref_n}", "supplier": sup, "branch": b, "lines": lines, "order_day": d, "recv_day": recv}
            self.po_list.append(po)
            dp.orders.append(po)
            for sku, qty in lines:
                self.on_order[(b, sku)] += qty
                if recv in self.plans:
                    incoming[recv].append((b, sku, qty))
            if recv in self.plans:
                self.plans[recv].deliveries.append(str(po["ref"]))

    def plan_cement_prices(self) -> None:
        """Story 3: the cement supplier's price creeps up over the last three deliveries, about 18% above the earlier ones."""
        base = self.products["CEM-50KG"].cost
        done = sorted((po for po in self.po_list if po["recv_day"] < self.today and any(s == "CEM-50KG" for s, _ in po["lines"])),
                      key=lambda po: po["recv_day"])
        for po in self.po_list:
            po["cost"] = {}
        for i, po in enumerate(done):
            from_end = len(done) - 1 - i
            mult = {0: Decimal("1.19"), 1: Decimal("1.07"), 2: Decimal("1.02")}.get(from_end, Decimal(1)) \
                if 3 in self.cfg["stories"] and len(done) >= 4 else Decimal(1)
            po["cost"]["CEM-50KG"] = money(base * mult)
        self.cement_orders = len(done)

    def plan_expenses(self, story_days: dict[str, date]) -> None:
        rng, cfg = self.rng, self.cfg
        nb = len(self.branches)
        rent = [60000, 42000, 38000]
        power = [9800, 6900, 6100]
        sec = [16000, 12000, 10000]
        every = cfg["expense_every"]
        for b in range(nb):
            for i, d in enumerate(self.days):
                dp = self.plans[d]
                if d.day == 1 or (i == 0 and len(self.days) > 20):
                    dp.expenses.append((b, "6000", rent[b], "bank", "Shop rent", Decimal(0)))
                if d.day == 5:
                    dp.expenses.append((b, "6200", round(power[b] * rng.uniform(0.9, 1.15)), "bank", "Electricity and water", Decimal("0.16")))
                if d.day == 3:
                    dp.expenses.append((b, "6700", sec[b], "bank", "Security guards", Decimal(0)))
                if d.weekday() == 4 and b == 0 and d.day % 2 == 0:
                    dp.expenses.append((b, "6400", round(rng.uniform(450, 900)), "bank", "Bank and mobile money charges", Decimal(0)))
                if d.weekday() == 2 and (d - self.start).days // 7 % 2 == b % 2:
                    dp.expenses.append((b, "6300", round(rng.uniform(1800, 4200)), "mobile_money", "Delivery to customer sites", Decimal(0)))
                if d.weekday() == 0 and (d - self.start).days // 7 % 2 != b % 2:
                    dp.expenses.append((b, "6600", round(rng.uniform(600, 1500)), "cash", "Cleaning supplies and stationery", Decimal(0)))
                if (b == 0 and i % every == 0) or (b > 0 and d.weekday() == 4):
                    dp.expenses.append((b, "6310", round(rng.uniform(700, 1100)), "cash", "Fuel for the delivery pickup", Decimal(0)))
                if rng.random() < 0.02:
                    dp.expenses.append((b, "6910", round(rng.uniform(1500, 6500)), "cash", "Repairs to shelving and doors", Decimal(0)))
        if 10 in cfg["stories"]:
            d = story_days["expense"]
            self.plans[d].expenses.append((0, "6310", 16500, "cash", "Fuel for the delivery pickup", Decimal(0)))
            self.story_expense_day = d

    def plan_special(self, d: date, dp: "DayPlan", story_days: dict[str, date]) -> None:
        """The days things are planted on (see docs/demo-data.md)."""
        cfg = self.cfg
        if 2 in cfg["stories"] and d == story_days["short"]:
            b = 2 if len(self.branches) > 2 else 0
            dp.special["short_till"] = {"branch": b, "amount": Decimal("8400")}
            if not any(s.branch == b and s.device == "D1" for s in dp.sales):       # the till must have been opened
                sku = next((s for s in self.products if self.mirror[(b, s)] > 5 and self.products[s].price < 1500), None)
                if sku is not None:
                    dp.sales.append(PlannedSale(d, b, 0.5, "D1", self.cashier_for(d, b), [(sku, Decimal(2))], "cash", None))
                    self.mirror[(b, sku)] -= 2
                    dp.sales.sort(key=lambda x: x.at)
        if 7 in cfg["stories"] and d == story_days["writeoff"]:
            def needed(code: str) -> int:
                return math.ceil(Decimal("1060") / Decimal(self.products[code].cost))      # as write_off() computes it

            # a product with enough on hand (after the day's plan) to write off just over the limit
            options = [c for c in ("TMB-2X2", "SND-50KG") if c in self.products]
            options += [c for c in self.products if c not in options and self.products[c].cost > 0]
            sku = next((c for c in options if self.mirror[(0, c)] >= needed(c)),
                       max(options, key=lambda c: self.mirror[(0, c)] - needed(c)))
            dp.special["writeoff"] = {"branch": 0, "sku": sku}
            self.mirror[(0, sku)] -= needed(sku)
        if 6 in cfg["stories"] and d == story_days["dup_bill"]:
            dp.special["dup_bill"] = {"supplier": 5 if 5 in self.suppliers else next(iter(self.suppliers))}
        if self.story_product and d == self.today - timedelta(days=2):
            left = self.mirror[(2, self.story_product)]
            if left > 0:
                dp.sales.append(PlannedSale(d, 2, 0.45, "D2", "mgr.RUI", [(self.story_product, left)], "cash", None,
                                            tag="story5"))
                self.mirror[(2, self.story_product)] = Decimal(0)
                dp.sales.sort(key=lambda x: x.at)
        if d == self.today - timedelta(days=1):
            dp.special["open_requests"] = True
        if 4 in cfg["stories"] and "Otieno Construction Co" in self.customers and d == self.today - timedelta(days=3):
            b = self.customers["Otieno Construction Co"]["home"]
            lines = [(sku, Decimal(q)) for sku, q in (("CEM-50KG", 12), ("NAIL-4IN", 10)) if sku in self.products
                     and self.mirror[(b, sku)] > q + 3]
            if lines:
                for sku, q in lines:
                    self.mirror[(b, sku)] -= q
                dp.sales.append(PlannedSale(d, b, 0.55, "D2", f"mgr.{self.branch_codes[b]}", lines, "credit",
                                            "Otieno Construction Co", tag="story4"))
                dp.sales.sort(key=lambda x: x.at)
        if 4 in cfg["stories"] and "Njeri Building Contractors" in self.customers and d == self.today - timedelta(days=6):
            dp.special["credit_request"] = {"customer": "Njeri Building Contractors", "limit": 650000}
        if d == story_days["count"] and "store" in self.users and len(self.branches) > 1:
            dp.special["count"] = True
        if d == self.today - timedelta(days=min(25, len(self.days) // 2)) and "HMR-16" in self.products:
            b = 1 if len(self.branches) > 1 else 0
            if self.mirror[(b, "HMR-16")] > 16:       # a big adjustment: above the approval limit, so Finance has to approve
                self.mirror[(b, "HMR-16")] -= 12
                dp.adjustments.append({"branch": b, "sku": "HMR-16", "qty": -12, "reason": "THEFT",
                                       "note": "Twelve hammers missing from the tool shelf after the monthly check"})

    # ================================================================ doing it: the days
    def attempt(self, what: str, fn: Callable[..., Any], *args: Any) -> Any:
        """Do one step of the day; if a service refuses it, note why and go on (the report lists what was refused)."""
        try:
            return fn(*args)
        except Fail as error:
            self.skipped[what] += 1
            self.first_error.setdefault(what, str(error)[:300])
            return None

    def reason(self, category: str, code: str) -> str:
        return str(self.reasons[(category, code)])

    def mpesa_code(self) -> str:
        self.mpesa_n += 1
        n = self.mpesa_n * 7919 + 10_000_019
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        return "R" + letters[n % 24] + letters[(n // 24) % 24] + str(n % 100000).zfill(5) + letters[(n // 576) % 24]

    def execute(self) -> None:
        started = time.time()
        self.mpesa_n = 0
        self.refs: dict[str, dict[str, Any]] = {}
        self.pending_send: list[tuple[str, str]] = []
        self.keep_pending: set[str] = set()
        self.reasons = {(r["category"], r["code"]): r["id"] for r in self.all("owner", "/settings/reason-codes")}
        self.tills_open: dict[tuple[int, str], dict[str, Any]] = {}
        self.cash_day: dict[tuple[int, date], Decimal] = defaultdict(Decimal)
        self.mm_day: dict[tuple[int, date], Decimal] = defaultdict(Decimal)
        self.cash_banked_to: dict[int, date] = {}
        self.settled_to: dict[int, date] = {}
        self.stats: dict[str, int] = defaultdict(int)
        with self.phase(self.start - timedelta(days=1), start=dtime(14, 0), end=dtime(15, 0)):
            for b, lines in self.opening.items():
                if lines:
                    self.api.post(f"mgr.{self.branch_codes[b]}", "/inventory/opening-stock", {
                        "company_id": self.company, "location_id": self.locations[b],
                        "lines": [{"product_id": str(self.products[sku].id), "quantity": str(q), "unit_cost": str(cost)}
                                  for sku, q, cost in lines]})
        for i, d in enumerate(self.days):
            self.run_day(d)
            if i % 10 == 9 or i == len(self.days) - 1:
                log(f"day {i + 1}/{len(self.days)} ({d}): {self.stats['sales']} sales so far, {self.api.calls} calls "
                    f"in {time.time() - started:.0f}s")
        self.run_today()
        log(f"history made: {dict(self.stats)}", started)
        if self.skipped:
            log(f"NOT accepted by the services (skipped): {dict(self.skipped)}")
            for what, why in self.first_error.items():
                log(f"  first {what} refusal: {why}")

    def run_day(self, d: date) -> None:
        dp = self.plans[d]
        with self.phase(d):
            self.morning(d, dp)
            self.counter(d, dp)
            self.afternoon(d, dp)
            self.close_tills(d, dp)
            self.settle()
            if d.weekday() == 0 or d in self.settlement_days():
                self.bank_the_week(d)
        if "writeoff" in dp.special:
            with self.phase(d, start=dtime(23, 40), end=dtime(23, 41)):
                self.write_off(dp.special["writeoff"])

    # ---------------------------------------------------------------- the morning: deliveries, bills, payments
    def morning(self, d: date, dp: DayPlan) -> None:
        for ref in dp.deliveries:
            self.attempt("goods receipt", self.receive_goods, d, ref)
        for ref in dp.receives:
            tr = self.refs.get(ref)
            if tr and self.attempt("transfer receipt", self.api.post, f"mgr.{self.branch_codes[tr['dst']]}",
                                   f"/inventory/transfers/{tr['id']}/receive") is not None:
                self.stats["transfers_received"] += 1
        for tr in dp.transfers:
            self.attempt("transfer", self.send_transfer, tr)
        for kind, data in list(dp.follow):
            self.attempt(kind, getattr(self, f"do_{kind}"), d, data)
        for inv in dp.invoices:
            self.attempt("invoice", self.issue_invoice, d, inv)
        if "credit_request" in dp.special:
            c = self.customers[dp.special["credit_request"]["customer"]]
            self.attempt("credit request", self.api.post, "finance", f"/crm/customers/{c['id']}/credit", {
                "credit_limit": str(dp.special["credit_request"]["limit"]), "payment_terms_days": c["terms"],
                "reason": "Takes on a bigger site next quarter; asks for a higher limit"})

    def receive_goods(self, d: date, ref: str) -> None:
        po = self.refs.get(ref)
        if not po or po.get("status") != "sent":
            return
        b = po["branch"]
        who = f"mgr.{self.branch_codes[b]}"
        lines = [{"order_line_id": lid, "quantity": str(q)} for lid, q in po["line_qty"]]
        receipt = self.api.post(who, "/purchasing/receipts", {
            "order_id": po["id"], "lines": lines, "delivery_note_no": f"DN-{self.rng.randint(10000, 99999)}"})
        po["status"] = "received"
        po["receipt"] = receipt
        self.stats["goods_receipts"] += 1
        due = d + timedelta(days=self.rng.randint(1, 3))
        if due in self.plans:
            self.plans[due].follow.append(("bill", {"ref": ref}))

    def do_bill(self, d: date, data: dict[str, Any]) -> None:
        po = self.refs[data["ref"]]
        sup = po["supplier"]
        self.bill_n += 1
        lines = [{"quantity": str(line["quantity"]), "unit_cost": str(line["unit_cost"]), "receipt_line_id": line["id"]}
                 for line in po["receipt"]["lines"]]
        bill = self.api.post("accountant", "/purchasing/bills", {
            "supplier_id": self.suppliers[sup]["id"], "supplier_invoice_no": f"{self.suppliers[sup]['inv']}-{self.bill_n:05d}",
            "bill_date": self.today.isoformat(), "lines": lines})
        bill = self.api.post("accountant", f"/purchasing/bills/{bill['id']}/submit")
        self.stats["bills"] += 1
        if sup in UNCONFIRMED:
            return
        late = {2: 22, 9: 32}.get(sup, 0)
        pay_day = d + timedelta(days=self.suppliers[sup]["terms"] + late + self.rng.randint(-6, 3))
        unpaid = self.rng.random() < 0.03
        if not unpaid and pay_day in self.plans:
            self.plans[pay_day].follow.append(("pay_bill", {"bill": bill["id"], "total": bill["total"], "supplier": sup,
                                                            "part": self.rng.random() < 0.15}))

    def do_pay_bill(self, d: date, data: dict[str, Any]) -> None:
        total = Decimal(data["total"])
        amount = money(total * Decimal("0.5")) if data.get("part") else total
        r = self.api.raw("finance", "POST", f"/purchasing/bills/{data['bill']}/pay", json={
            "amount": str(amount), "method": "bank", "payment_account_id": self.bank_account,
            "external_ref": f"EFT{self.rng.randint(100000, 999999)}"})
        if r.status_code in (200, 201):
            self.stats["supplier_payments"] += 1
        else:
            self.skipped["supplier payment"] += 1

    def do_bill2(self, d: date, data: dict[str, Any]) -> None:
        """Story 6: the same bill from the same supplier entered again two days later."""
        self.dup_bill(d, data["supplier"], data["amount"], "HL-20431-A")

    def dup_bill(self, d: date, supplier: int, amount: str, number: str) -> None:
        bill = self.api.post("accountant", "/purchasing/bills", {
            "supplier_id": self.suppliers[supplier]["id"], "supplier_invoice_no": number, "bill_date": self.today.isoformat(),
            "lines": [{"quantity": "1", "unit_cost": amount, "expense_account_id": self.ledger["6300"]["id"],
                       "description": "Haulage of materials from the depot", "tax_code_id": self.taxes["STD"]}]})
        self.api.post("accountant", f"/purchasing/bills/{bill['id']}/submit")
        self.stats["bills"] += 1

    def do_customer_pay(self, d: date, data: dict[str, Any]) -> None:
        c = self.customers[data["customer"]]
        method = data["method"]
        body = {"customer_id": c["id"], "amount": data["amount"], "method": method,
                "branch_id": str(self.branch_ids[c["home"]]),
                "allocations": [{"invoice_id": data["invoice"], "amount": data["amount"]}]}
        if method == "mobile_money":
            body["external_ref"] = self.mpesa_code()
        elif method == "bank":
            body["external_ref"] = f"BANK{self.rng.randint(100000, 999999)}"
        who = "finance" if method == "bank" else f"cash.{self.branch_codes[c['home']]}"
        r = self.api.raw(who, "POST", "/pos/receipts", json=body)
        if r.status_code in (200, 201):
            self.stats["customer_receipts"] += 1
        else:
            self.skipped["customer receipt"] += 1
            self.first_error.setdefault("customer receipt", r.text[:200])

    def schedule_customer_payment(self, invoice_id: str, total: Decimal, customer: str, pay_day: date | None,
                                  fraction: float = 1.0) -> None:
        if pay_day is None or pay_day not in self.plans:
            return
        c = self.customers[customer]
        method = self.rng.choices(["bank", "mobile_money", "cash"], weights=[5, 3, 2] if c["how"] != "shop" else [2, 4, 4])[0]
        first = money(total * Decimal(str(fraction)))
        self.plans[pay_day].follow.append(("customer_pay", {"customer": customer, "invoice": invoice_id,
                                                           "amount": str(first), "method": method}))
        if fraction < 1.0:
            later = pay_day + timedelta(days=self.rng.randint(14, 30))
            if later in self.plans:
                self.plans[later].follow.append(("customer_pay", {
                    "customer": customer, "invoice": invoice_id, "amount": str(total - first), "method": method}))

    def issue_invoice(self, d: date, inv: InvoicePlan) -> None:
        c = self.customers[inv.customer]
        b = inv.branch
        lines = [{"product_id": str(self.products[sku].id), "quantity": str(q)} for sku, q in inv.lines]
        r = self.api.raw("rep", "POST", "/pos/invoices", json={
            "customer_id": c["id"], "lines": lines, "branch_id": str(self.branch_ids[b]), "location_id": self.locations[b]})
        if r.status_code not in (200, 201):
            self.skipped["invoice"] += 1
            self.first_error.setdefault("invoice", r.text[:300])
            return
        body = r.json()
        self.stats["invoices"] += 1
        self.refs[inv.ref] = {"id": body["id"], "total": body["total"]}
        self.schedule_customer_payment(body["id"], Decimal(body["total"]), inv.customer, inv.pay_day, inv.fraction)

    # ---------------------------------------------------------------- transfers
    def send_transfer(self, tr: dict[str, Any]) -> None:
        src, dst = tr["src"], tr["dst"]
        who = f"mgr.{self.branch_codes[src]}"
        t = self.api.post(who, "/inventory/transfers", {
            "company_id": self.company, "from_location_id": self.locations[src], "to_location_id": self.locations[dst],
            "lines": [{"product_id": str(self.products[sku].id), "quantity": str(q)} for sku, q in tr["lines"]]})
        self.api.post(who, f"/inventory/transfers/{t['id']}/dispatch")
        self.refs[tr["ref"]] = {"id": t["id"], "dst": dst}
        self.stats["transfers"] += 1

    # ---------------------------------------------------------------- the counter
    def unit_price(self, sku: str, customer: str | None) -> Decimal:
        p = self.products[sku]
        if customer and self.customers[customer]["group"] == "wholesale":
            return p.wholesale or p.price
        return p.price

    def open_till(self, d: date, b: int, device: str, who: str, float_: str = "2000.00") -> dict[str, Any]:
        key = (b, device)
        if key not in self.tills_open:
            self.tills_open[key] = self.api.post(who, "/pos/tills", {
                "device_id": self.devices[key], "opening_float": float_})
            self.tills_open[key]["who"] = who
        return self.tills_open[key]

    def counter(self, d: date, dp: DayPlan) -> None:
        done: list[tuple[PlannedSale, dict[str, Any]]] = []
        for s in dp.sales:
            if s.tag == "story5":              # sell what is really left (a return may have put a unit back)
                sku = s.lines[0][0]
                real = self.one("select coalesce(sum(quantity), 0) from inventory.stock_balance where location_id = :l "
                                "and product_id = :p", l=self.locations[s.branch], p=str(self.products[sku].id))
                if not real or real <= 0:
                    continue
                s.lines = [(sku, Decimal(real))]
            short = dp.special.get("short_till")
            big_float = "15000.00" if short and short["branch"] == s.branch and s.device == "D1" else "2000.00"
            till = self.open_till(d, s.branch, s.device, s.cashier, big_float)
            sale = self.ring_up(s, till)
            if sale is None:
                continue
            done.append((s, sale))
            if s.void:
                voided = self.api.raw(f"mgr.{self.branch_codes[s.branch]}", "POST", f"/pos/sales/{sale['id']}/void", json={
                    "reason_code_id": self.reason("void", self.rng.choice(["CASHIER_ERROR", "CUSTOMER_LEFT", "WRONG_ITEM"]))})
                if voided.status_code in (200, 201):
                    self.stats["voids"] += 1
        for s, sale in done:
            if s.refund and not s.void:
                line = sale["lines"][0]
                method = "mobile_money" if s.method == "mobile_money" else "cash"
                if method == "cash":
                    self.open_till(d, s.branch, "D2", f"mgr.{self.branch_codes[s.branch]}", "20000.00")
                r = self.api.raw(f"mgr.{self.branch_codes[s.branch]}", "POST", f"/pos/sales/{sale['id']}/returns", json={
                    "lines": [{"sale_line_id": line["id"], "quantity": "1"}],
                    "reason_code_id": self.reason("sale_return", self.rng.choice(["FAULTY", "NOT_WANTED", "WRONG_ITEM"])),
                    "refund_method": method})
                if r.status_code in (200, 201):
                    self.stats["returns"] += 1
                else:
                    self.skipped["return"] += 1
                    self.first_error.setdefault("return", r.text[:200])

    def ring_up(self, s: PlannedSale, till: dict[str, Any]) -> dict[str, Any] | None:
        lines: list[dict[str, Any]] = []
        total = Decimal(0)
        gross = []
        for sku, qty in s.lines:
            unit = self.unit_price(sku, s.customer)
            gross.append(unit * qty)
            total += unit * qty
            lines.append({"product_id": str(self.products[sku].id), "quantity": str(qty)})
        if s.discount > 0 and lines:
            big = gross.index(max(gross))
            disc = min(s.discount, gross[big] / 2)
            lines[big]["discount"] = str(disc)
            lines[big]["reason_code_id"] = self.reason("price_override", self.rng.choice(["BULK", "MANAGER_APPROVED", "MATCH_COMPETITOR"]))
            total -= disc
        total = money(total)
        if s.method == "cash":
            tendered = (total / 50).to_integral_value(rounding="ROUND_CEILING") * 50
            payments = [{"method": "cash", "amount": str(tendered)}]
        elif s.method == "mobile_money":
            payments = [{"method": "mobile_money", "amount": str(total), "external_ref": self.mpesa_code()}]
        elif s.method == "card":
            payments = [{"method": "card", "amount": str(total), "external_ref": f"SLIP{self.rng.randint(100000, 999999)}"}]
        elif s.method == "credit":
            payments = [{"method": "credit", "amount": str(total)}]
        else:   # split between cash and mobile money
            part = (total * Decimal("0.4") / 10).to_integral_value() * 10
            payments = [{"method": "cash", "amount": str(part)},
                        {"method": "mobile_money", "amount": str(total - part), "external_ref": self.mpesa_code()}]
        body: dict[str, Any] = {"till_session_id": till["id"], "lines": lines, "payments": payments, "local_id": str(uuid4())}
        if s.customer:
            body["customer_id"] = self.customers[s.customer]["id"]
        r = self.api.raw(s.cashier, "POST", "/pos/sales", json=body)
        if r.status_code not in (200, 201):
            self.skipped["sale"] += 1
            self.first_error.setdefault("sale", f"{r.status_code} {r.text[:250]}")
            return None
        sale = r.json()
        self.stats["sales"] += 1
        if not s.void:
            for leg in payments:
                if leg["method"] == "cash":
                    self.cash_day[(s.branch, s.day)] += min(Decimal(leg["amount"]), total)
                elif leg["method"] == "mobile_money":
                    self.mm_day[(s.branch, s.day)] += Decimal(leg["amount"])
        if s.method == "credit" and s.customer:
            invoice_id = self.one("select id from pos.sales_invoice where sale_id = :s", s=sale["id"])
            if invoice_id and s.tag != "story4":
                c = self.customers[s.customer]
                beh = self.behaviour(s.customer)
                delay = {"good": self.rng.randint(-4, 6), "slow": self.rng.randint(15, 35), "bad": self.rng.randint(45, 100)}[beh]
                self.schedule_customer_payment(str(invoice_id), Decimal(sale["total"]), s.customer,
                                               s.day + timedelta(days=c["terms"] + delay))
        return sale  # type: ignore[no-any-return]

    def close_tills(self, d: date, dp: DayPlan) -> None:
        for (b, device), till in sorted(self.tills_open.items()):
            who = till["who"]
            report = self.api.get(who, f"/pos/tills/{till['id']}/report")
            expected = Decimal(report["expected_cash"])
            short = dp.special.get("short_till")
            roll = self.rng.random()
            reason = None
            if short and short["branch"] == b and device == "D1":
                variance, reason = -short["amount"], "UNKNOWN"
            elif roll < 0.62:
                variance = Decimal(0)
            elif roll < 0.992:
                variance = Decimal(self.rng.choice([-50, -40, -20, -10, 10, 20, 30, 40, 60, -80, 100, -150, 200, -250]))
                reason = "CHANGE_ERROR" if variance < 0 else "UNRECORDED_SALE"
            else:
                variance = Decimal(self.rng.choice([-650, -720, 900, -980]))
                reason = "UNRECORDED_PAYOUT" if variance < 0 else "UNRECORDED_SALE"
            if expected + variance < 0:
                variance = Decimal(0) if expected >= 0 else -expected
            body: dict[str, Any] = {"counted_cash": str(max(expected + variance, Decimal(0)))}
            if variance != 0:
                body["reason_code_id"] = self.reason("till_variance", reason or "UNKNOWN")
                body["note"] = "Counted twice with the branch manager" if abs(variance) >= 500 else "Small difference at closing"
            if self.attempt("till close", self.api.post, who, f"/pos/tills/{till['id']}/close", body) is None:
                body = {"counted_cash": str(max(expected, Decimal(0)))}
                self.attempt("till close (again)", self.api.post, who, f"/pos/tills/{till['id']}/close", body)
            self.stats["tills"] += 1
        self.tills_open.clear()

    # ---------------------------------------------------------------- the afternoon: orders, expenses, adjustments
    def afternoon(self, d: date, dp: DayPlan) -> None:
        for po in dp.orders:
            self.attempt("purchase order", self.place_order, d, po)
        for b, code, amount, paid_from, desc, vat in dp.expenses:
            self.attempt("expense", self.expense, d, b, code, amount, paid_from, desc, vat)
        for adj in dp.adjustments:
            self.attempt("adjustment", self.adjustment, adj)
        if "dup_bill" in dp.special:
            s = dp.special["dup_bill"]["supplier"]
            self.attempt("duplicate bill", self.dup_bill, d, s, "21500.00", "HL-20431")
            due = d + timedelta(days=2)
            if due in self.plans:
                self.plans[due].follow.append(("bill2", {"supplier": s, "amount": "21500.00"}))
        if "count" in dp.special:
            self.attempt("stock count", self.stock_count, dp)
        if "open_requests" in dp.special:
            for b in range(min(2, len(self.branches))):
                skus = [s for s in self.products if self.products[s].price > 500][b::3][:3]
                if not skus:
                    continue
                who = f"mgr.{self.branch_codes[b]}"
                req = self.api.post(who, "/purchasing/requests", {
                    "company_id": self.company, "branch_id": str(self.branch_ids[b]),
                    "needed_by": (self.today + timedelta(days=7)).isoformat(),
                    "lines": [{"product_id": str(self.products[s].id), "quantity": "20", "note": "Customers keep asking"} for s in skus]})
                self.api.post(who, f"/purchasing/requests/{req['id']}/submit")
                self.stats["purchase_requests"] += 1

    def place_order(self, d: date, po: dict[str, Any]) -> None:
        b = po["branch"]
        who = f"mgr.{self.branch_codes[b]}"
        sup = po["supplier"]
        costs = po.get("cost", {})
        lines = [{"product_id": str(self.products[sku].id), "quantity": str(q),
                  "unit_cost": str(costs.get(sku, self.products[sku].cost))} for sku, q in po["lines"]]
        expected = self.today + (po["recv_day"] - po["order_day"])
        body: dict[str, Any] = {
            "company_id": self.company, "supplier_id": self.suppliers[sup]["id"], "branch_id": str(self.branch_ids[b]),
            "deliver_to_location_id": self.locations[b], "expected_date": expected.isoformat(), "lines": lines}
        if self.stats["orders"] % 4 == 1:                    # every fourth order started as a request from the shop
            asker = "store" if b == 0 and "store" in self.users else who
            req = self.api.raw(asker, "POST", "/purchasing/requests", json={
                "company_id": self.company, "branch_id": str(self.branch_ids[b]), "needed_by": expected.isoformat(),
                "lines": [{"product_id": x["product_id"], "quantity": x["quantity"], "note": "Running low"} for x in lines]})
            if req.status_code in (200, 201):
                sub = self.api.raw(asker, "POST", f"/purchasing/requests/{req.json()['id']}/submit")
                if sub.status_code in (200, 201) and sub.json().get("status") == "approved":
                    body["request_id"] = req.json()["id"]
                    self.stats["purchase_requests"] += 1
        order = self.api.post(who, "/purchasing/orders", body)
        submitted = self.api.post(who, f"/purchasing/orders/{order['id']}/submit")
        by_product = {x["product_id"]: x["id"] for x in order["lines"]}
        line_qty = [(by_product[str(self.products[sku].id)], q) for sku, q in po["lines"]]
        self.refs[po["ref"]] = {"id": order["id"], "branch": b, "supplier": sup, "line_qty": line_qty, "status": "approved"
                                if submitted.get("status") == "approved" else "pending"}
        if submitted.get("status") == "approved":
            self.send_order(po["ref"])
        else:
            self.pending_send.append((po["ref"], who))
        self.stats["orders"] += 1

    def send_order(self, ref: str) -> None:
        po = self.refs[ref]
        who = f"mgr.{self.branch_codes[po['branch']]}"
        self.api.post(who, f"/purchasing/orders/{po['id']}/send")
        po["status"] = "sent"

    def expense(self, d: date, b: int, code: str, amount: int, paid_from: str, desc: str, vat: Decimal) -> None:
        who = f"mgr.{self.branch_codes[b]}"
        gross = Decimal(amount)
        tax = money(gross * vat / (1 + vat)) if vat else Decimal(0)
        e = self.api.post(who, "/finance/expenses", {
            "company_id": self.company, "branch_id": str(self.branch_ids[b]), "expense_date": self.today.isoformat(),
            "description": desc, "account_id": self.ledger[code]["id"], "amount": str(gross), "tax_amount": str(tax),
            "paid_from": paid_from, "payee": None})
        self.api.post(who, f"/finance/expenses/{e['id']}/submit")
        self.stats["expenses"] += 1

    def adjustment(self, adj: dict[str, Any]) -> None:
        b = adj["branch"]
        who = "store" if b == 0 and "store" in self.users else f"mgr.{self.branch_codes[b]}"
        a = self.api.post(who, "/inventory/adjustments", {
            "company_id": self.company, "location_id": self.locations[b],
            "reason_code_id": self.reason("stock_adjustment", adj["reason"]), "note": adj.get("note"),
            "lines": [{"product_id": str(self.products[adj["sku"]].id), "qty_change": str(adj["qty"])}]})
        self.api.post(who, f"/inventory/adjustments/{a['id']}/submit")
        self.stats["adjustments"] += 1

    def write_off(self, spec: dict[str, Any]) -> None:
        """Story 7: late at night, the storekeeper writes off stock worth just over the limit Intelligence watches."""
        sku = spec["sku"]
        avg = Decimal(self.one("select average_cost from inventory.product_cost where product_id = :p",
                               p=str(self.products[sku].id)) or self.products[sku].cost)
        qty = math.ceil(Decimal("1060") / avg)
        a = self.api.post("store", "/inventory/adjustments", {
            "company_id": self.company, "location_id": self.locations[spec["branch"]],
            "reason_code_id": self.reason("stock_adjustment", "DAMAGED"), "note": "Stock damaged when the shelf gave way",
            "lines": [{"product_id": str(self.products[sku].id), "qty_change": str(-qty)}]})
        self.api.post("store", f"/inventory/adjustments/{a['id']}/submit")
        self.story_data["writeoff"] = {"sku": sku, "qty": qty, "value": str(qty * avg)}
        self.stats["adjustments"] += 1

    def stock_count(self, dp: DayPlan) -> None:
        b = 0
        who = "store"
        count = self.api.post(who, "/inventory/counts", {"company_id": self.company, "location_id": self.locations[b]})
        lines = {x["product_id"]: x for x in count.get("lines", [])}
        entries = []
        total_value = Decimal(0)
        picks = [s for s in self.products if self.products[s].cost >= 100][:40]
        for sku in self.rng.sample(picks, min(8, len(picks))):
            pid = str(self.products[sku].id)
            line = lines.get(pid)
            if line is None:
                continue
            system = Decimal(str(line.get("system_qty") or line.get("expected_qty") or 0))
            delta = Decimal(self.rng.choice([-3, -2, -1, 1, 2, -4]))
            if system + delta < 0 or total_value > 2800:
                delta = Decimal(0)
            total_value += abs(delta) * self.products[sku].cost
            entries.append({"product_id": pid, "counted_qty": str(system + delta),
                            "reason_code_id": self.reason("count_variance", "COUNT_ERROR") if delta else None})
        # the rest of the shelf is counted as it is
        for pid, line in lines.items():
            if pid not in {e["product_id"] for e in entries}:
                system = Decimal(str(line.get("system_qty") or line.get("expected_qty") or 0))
                entries.append({"product_id": pid, "counted_qty": str(system)})
        self.api.post(who, f"/inventory/counts/{count['id']}/entries", {"entries": entries})
        self.api.post(who, f"/inventory/counts/{count['id']}/finish", {"uncounted_as_zero": False})
        self.api.post(who, f"/inventory/counts/{count['id']}/submit", {})
        self.stats["counts"] += 1

    def settle(self) -> None:
        """Approvals the finance manager works through the same day; the ones the demo keeps waiting are left."""
        for req in self.api.get("finance", "/approvals/pending"):
            if req.get("doc_type") == "credit_limit_change" or str(req.get("doc_id")) in self.keep_pending:
                continue
            self.api.raw("finance", "POST", f"/approvals/{req['id']}/decision", json={"approve": True, "note": "Reviewed"})
        for ref, who in self.pending_send:
            po = self.refs.get(ref)
            if po and po["status"] == "pending":
                self.api.raw(who, "GET", f"/purchasing/orders/{po['id']}")
                r = self.api.raw(who, "POST", f"/purchasing/orders/{po['id']}/send")
                po["status"] = "sent" if r.status_code in (200, 201) else "pending"
        self.pending_send = [(r, w) for r, w in self.pending_send if self.refs.get(r, {}).get("status") == "pending"]

    def settlement_days(self) -> set[date]:
        """Mobile money is settled to the bank on Mondays, and the last time on the day after (today - 3): a settlement
        covers every day before it, so the last one covers exactly what Intelligence compares with the bank."""
        last = self.today - timedelta(days=2)
        days = {d for d in self.days if d.weekday() == 0 and d <= last}
        if last in self.plans:
            days.add(last)
        return days

    def bank_the_week(self, d: date) -> None:
        """Cash goes to the bank and mobile money is settled to it, as a branch would do each week."""
        for b in range(len(self.branches)):
            if d.weekday() == 0:
                since = self.cash_banked_to.get(b, self.start - timedelta(days=1))
                taken = sum((v for (bb, day), v in self.cash_day.items() if bb == b and since < day <= d), Decimal(0))
                cash = (taken * Decimal("0.85") / 100).to_integral_value() * 100
                if cash >= 1000:
                    self.api.post(f"mgr.{self.branch_codes[b]}", "/payments/cash-deposits", {
                        "company_id": self.company, "branch_id": str(self.branch_ids[b]), "bank_account_id": self.bank_account,
                        "amount": str(cash), "reference": f"DEP{d:%m%d}{self.branch_codes[b]}"})
                    self.stats["cash_deposits"] += 1
                self.cash_banked_to[b] = d
            if d in self.settlement_days():
                since = self.settled_to.get(b, self.start - timedelta(days=1))
                mm = money(sum((v for (bb, day), v in self.mm_day.items() if bb == b and since < day < d), Decimal(0)))
                if mm >= 1000:
                    fee = money(mm * Decimal("0.01"))
                    self.api.post("finance", "/payments/settlements", {
                        "from_account_id": self.pay_accounts[b]["mobile_money"], "to_account_id": self.bank_account,
                        "amount": str(mm - fee), "fee": str(fee), "reference": f"SETTLE{d:%m%d}{self.branch_codes[b]}"})
                    self.stats["settlements"] += 1
                self.settled_to[b] = d - timedelta(days=1)

    def run_today(self) -> None:
        """Today so far: the tills are open with a few sales on them. Whatever the clock says, they are placed between
        08:00 and (at most) 17:30 today, so the demo never has sales at night."""
        rng = self.rng
        now_local = datetime.now(UTC).astimezone(self.zone)
        if now_local.hour < 9:
            log("it is before 09:00 where the business is: today's tills are not opened")
            return
        end = min(now_local - timedelta(minutes=3), now_local.replace(hour=17, minute=30)).time()
        with self.phase(self.today, start=dtime(8, 0), end=end, shift=False):
            for b in range(len(self.branches)):
                who = self.cashier_for(self.today, b)
                till = self.open_till(self.today, b, "D1", who)
                for _ in range(rng.randint(2, 5)):
                    s = self.plan_one_sale(self.today, b, 0.3, [])
                    if s is not None and s.device == "D1":
                        s.method = "cash" if s.method in ("credit", "split") else s.method
                        self.ring_up(s, till)
            self.settle()
        self.stats["open_tills"] = len(self.tills_open)

    # ================================================================ putting every day where it belongs
    NOT_MOVED = {("finance", "period"), ("kernel", "document_series"), ("kernel", "user_session"), ("kernel", "tenant"),
                 ("kernel", "unit"), ("kernel", "schema_migration"), ("kernel", "tenant_unit"), ("kernel", "idempotency_key"),
                 ("kernel", "periodic_run"), ("kernel", "api_key")}

    def move_phases(self) -> None:
        """Move what each phase made to its day (see the module note). One pass; triggers are off for its length only."""
        phases = self.phases[self.moved:]
        if not phases:
            return
        self.moved = len(self.phases)
        started = time.time()
        with self.db() as s:
            s.execute(text("create temp table _phase (t0 timestamptz, t1 timestamptz, shift int, a timestamptz, "
                           "ratio float8) on commit drop"))
            for ph in phases:
                span = (ph.t1 - ph.t0).total_seconds()
                s.execute(text("insert into _phase values (:t0, :t1, :sh, :a, :r)"), {
                    "t0": ph.t0, "t1": ph.t1, "sh": ph.shift_days, "a": ph.a,
                    "r": max((ph.b - ph.a).total_seconds(), 1.0) / max(span, 0.001)})
            s.execute(text("create index on _phase (t0)"))
            s.execute(text(
                "create or replace function pg_temp.remap(ts timestamptz) returns timestamptz language sql stable as $$ "
                "select coalesce((select p.a + make_interval(secs => extract(epoch from (ts - p.t0)) * p.ratio) "
                " from _phase p where ts >= p.t0 and ts <= p.t1 limit 1), ts) $$"))
            cols = s.execute(text(
                "select c.table_schema, c.table_name, c.column_name, c.data_type from information_schema.columns c "
                "join information_schema.tables t on t.table_schema = c.table_schema and t.table_name = c.table_name "
                "where t.table_type = 'BASE TABLE' and c.table_schema not in ('pg_catalog', 'information_schema') "
                "and c.data_type in ('timestamp with time zone', 'date') and c.is_generated = 'NEVER' "
                "order by 1, 2, c.ordinal_position")).all()
            tables: dict[tuple[str, str], dict[str, list[str]]] = {}
            for schema, table, column, kind in cols:
                if (schema, table) in self.NOT_MOVED:
                    continue
                tables.setdefault((schema, table), {"ts": [], "date": []})["ts" if kind.startswith("timestamp") else "date"].append(column)
            moved_rows = 0
            todo = []
            for (schema, table), c in tables.items():
                key = "created_at" if "created_at" in c["ts"] else (c["ts"][0] if c["ts"] else None)
                if key is None:
                    continue
                hit = s.execute(text(f'select 1 from "{schema}"."{table}" t, _phase p where t."{key}" between p.t0 and p.t1 limit 1')).first()
                if hit:
                    todo.append((schema, table, key, c))
            try:
                for schema, table, _key, _c in todo:
                    s.execute(text(f'alter table "{schema}"."{table}" disable trigger user'))
                for schema, table, key, c in todo:
                    sets = [f'"{col}" = pg_temp.remap("{col}")' for col in c["ts"]]
                    sets += [f'"{col}" = "{col}" - p.shift' for col in c["date"]]
                    r = s.execute(text(f'update "{schema}"."{table}" t set {", ".join(sets)} from _phase p '
                                       f'where t."{key}" between p.t0 and p.t1'))
                    moved_rows += r.rowcount
                # rows made outside a phase and changed inside one (a customer, a product): only their timestamps
                for schema, table, key, c in todo:
                    if "updated_at" in c["ts"] and key == "created_at":
                        s.execute(text(f'update "{schema}"."{table}" t set updated_at = pg_temp.remap(updated_at) '
                                       f'where updated_at is not null and not exists (select 1 from _phase p where t.created_at between p.t0 and p.t1)'))
                self.fix_derived(s)
            finally:
                for schema, table, _key, _c in todo:
                    s.execute(text(f'alter table "{schema}"."{table}" enable trigger user'))
        log(f"{len(phases)} phases moved to their days ({moved_rows} rows in {len(todo)} tables)", started)

    def fix_derived(self, s: Any) -> None:
        """What depends on a moved date: the books' periods, the stored till reports, delivered events."""
        s.execute(text(
            "update finance.journal_entry e set period_id = p.id from finance.period p where p.company_id = e.company_id "
            "and e.entry_date between p.start_date and p.end_date and e.period_id <> p.id"))
        s.execute(text(
            "update pos.till_session set report = jsonb_set(report, '{business_date}', to_jsonb(business_date::text)) "
            "where report ? 'business_date'"))
        s.execute(text("update kernel.event_outbox set published_at = created_at + interval '2 seconds' "
                       "where published_at is null and created_at < :now"), {"now": self.seed_end})

    def ensure_periods(self) -> None:
        d = self.start - timedelta(days=60)
        seen: set[tuple[int, int]] = set()
        while d <= self.today:
            if (d.year, d.month) not in seen:
                seen.add((d.year, d.month))
                self.api.raw("finance", "POST", "/finance/periods", json={"company_id": self.company, "day": d.isoformat()})
            d += timedelta(days=20)
        self.api.raw("finance", "POST", "/finance/periods", json={"company_id": self.company, "day": self.today.isoformat()})

    # ================================================================ people: employees, leave, attendance, payroll
    STAFF: list[tuple[str, str, int | None, str | None, int, str]] = [
        # name, job, branch index, login key, basic pay, hired
        ("Grace Njeri", "Branch manager", 0, "mgr.THK", 48000, "2021-03-01"),
        ("Lucy Chebet", "Cashier", 0, "cash.THK", 19000, "2023-02-06"),
        ("Joseph Karanja", "Storekeeper", 0, "store", 23000, "2022-06-01"),
        ("Dennis Maina", "Sales assistant", 0, None, 17000, "2024-01-15"),
        ("Daniel Omondi", "Branch manager", 1, "mgr.JUJ", 45000, "2022-09-01"),
        ("Esther Wafula", "Cashier", 1, "cash.JUJ", 18000, "2023-08-14"),
        ("Brian Mwangi", "Cashier", 1, "cash2.JUJ", 18000, "2025-05-05"),
        ("Kevin Otieno", "Loader", 1, None, 14500, "2024-04-01"),
        ("Moses Mutua", "Branch manager", 2, "mgr.RUI", 42000, "2023-01-09"),
        ("Ruth Kiptoo", "Cashier", 2, "cash.RUI", 17500, "2024-07-01"),
        ("Peter Njoroge", "Sales assistant", 2, None, 16000, "2025-01-13"),
        ("Faith Wambui", "Finance manager", 0, "finance", 70000, "2021-01-04"),
        ("Hannah Achieng", "HR officer", 0, "hr", 42000, "2022-02-01"),
        ("Peter Kariuki", "Accountant", 0, "accountant", 52000, "2023-05-02"),
    ]

    def month_ends(self, count: int) -> list[tuple[date, date]]:
        """The last `count` finished months, oldest first."""
        out = []
        y, m = self.today.year, self.today.month
        for _ in range(count):
            m -= 1
            if m == 0:
                y, m = y - 1, 12
            first = date(y, m, 1)
            last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
            out.append((first, last))
        return list(reversed(out))

    def at(self, day: date, moment: dtime) -> str:
        """A time of day in the company's zone, as the API writes it."""
        return datetime.combine(day, moment, tzinfo=self.zone).isoformat()

    def day_window(self, day: date, start: dtime, end: dtime) -> "contextlib.AbstractContextManager[None]":
        return self.phase(day, start=start, end=end, shift=False)

    def people(self) -> None:
        started = time.time()
        cfg, co = self.cfg, self.company
        runs = self.month_ends(cfg["payroll_runs"])
        anchor = min(self.start, runs[0][0]) - timedelta(days=45)
        staff = [s for s in self.STAFF if s[3] is None or s[3] in self.users][: cfg["employees"]]
        hr, finance = "hr", "finance"
        self.employees: dict[str, dict[str, Any]] = {}
        with self.day_window(anchor, dtime(9, 0), dtime(12, 0)):
            self.api.post(hr, "/people/departments", {"company_id": co, "name": "Retail"}, expect=(200, 201, 409))
            comps: dict[str, str] = {}
            for code, name, taxable in (("HOUSE", "House allowance", True), ("TRANSPORT", "Transport allowance", False)):
                comps[code] = self.api.post(hr, "/people/pay-components", {
                    "company_id": co, "code": code, "name": name, "kind": "earning", "is_taxable": taxable})["id"]
            defs = (
                ("RETIRE", "Retirement fund", {"name": "Retirement fund", "kind": "contribution", "order": 10, "base": "gross",
                                                "reduces_taxable": True, "employee": {"method": "rate", "rate": "0.05", "base_maximum": "100000"},
                                                "employer": {"method": "rate", "rate": "0.05", "base_maximum": "100000"}},
                 self.ledger["2410"]["id"]),
                ("HEALTH", "Health insurance levy", {"name": "Health insurance levy", "kind": "contribution", "order": 20, "base": "gross",
                                                     "employee": {"method": "rate", "rate": "0.0275", "base_maximum": None}},
                 self.ledger["2420"]["id"]),
                ("INCOME_TAX", "Income tax", {"name": "Income tax", "kind": "tax", "order": 30, "base": "taxable",
                                              "applies_to": "resident", "employee": {"method": "bands", "credit": "2000", "bands": [
                                                  {"up_to": "24000", "rate": "0.10"}, {"up_to": "40000", "rate": "0.20"},
                                                  {"up_to": "80000", "rate": "0.25"}, {"up_to": "300000", "rate": "0.30"},
                                                  {"up_to": None, "rate": "0.35"}]}}, self.ledger["2400"]["id"]),
            )
            for code, label, definition, account in defs:
                rule = self.api.post(finance, "/people/rules", {
                    "company_id": co, "code": code, "effective_from": f"{anchor.year - 1}-01-01", "definition": definition,
                    "source_reference": f"{label}: rates set by the owner's accountant (demo figures)", "payable_account_id": account})
                self.api.post("accountant", f"/people/rules/{rule['id']}/verify", {})
            for name, job, bi, key, basic, hired in staff:
                user_id = self.users[key]["id"] if key else None
                e = self.api.post(hr, "/people/employees", {
                    "company_id": co, "full_name": name, "hire_date": hired, "branch_id": str(self.branch_ids[bi or 0]),
                    "user_id": user_id, "national_id": f"{20000000 + len(self.employees) * 7919}", "tax_id": f"A00{len(self.employees) + 1}7{len(name)}Z",
                    "phone": f"+2547{30000000 + len(self.employees) * 4421:08d}"[:13], "email": f"{name.split()[0].lower()}@{self.domain}"})
                approver = "owner" if key == "finance" else finance
                terms = self.api.post(hr, f"/people/employees/{e['id']}/terms", {"basic_pay": str(basic), "valid_from": hired, "note": f"{job}: agreed on appointment"})
                self.api.post(approver, f"/people/terms/{terms['id']}/approve")
                self.api.post(hr, f"/people/employees/{e['id']}/pay-items", {
                    "component_id": comps["HOUSE"], "amount": str(round(basic * 0.12, -2)), "valid_from": hired})
                if job in ("Loader", "Sales assistant", "Storekeeper"):
                    self.api.post(hr, f"/people/employees/{e['id']}/pay-items", {
                        "component_id": comps["TRANSPORT"], "amount": "3000", "valid_from": hired})
                bank = self.api.post(hr, f"/people/employees/{e['id']}/bank-accounts", {
                    "method": "mobile_money" if len(self.employees) % 3 == 0 else "bank",
                    "account_no": f"+254712{len(self.employees):06d}" if len(self.employees) % 3 == 0 else f"01{80000000 + len(self.employees) * 3331}",
                    "bank_name": None if len(self.employees) % 3 == 0 else "Commerce Bank"})
                self.api.post(approver, f"/people/bank-accounts/{bank['id']}/approve")
                self.employees[name] = {"id": e["id"], "job": job, "branch": bi or 0, "key": key, "basic": basic, "hired": hired}
        self.leave_and_attendance(runs)
        # story 8: someone is added, and the payment details they gave are changed, three days before the last run
        last_start, last_end = runs[-1]
        if 8 in cfg["stories"]:
            g = last_end - timedelta(days=3)
            with self.day_window(g, dtime(10, 0), dtime(10, 30)):
                e = self.api.post(hr, "/people/employees", {
                    "company_id": co, "full_name": "Collins Barasa", "hire_date": g.isoformat(),
                    "branch_id": str(self.branch_ids[min(1, len(self.branch_ids) - 1)]), "national_id": "29981543",
                    "tax_id": "A009341K", "phone": "+254733000111", "email": f"collins.barasa@{self.domain}"})
                terms = self.api.post(hr, f"/people/employees/{e['id']}/terms", {"basic_pay": "30000", "valid_from": g.isoformat(), "note": "Sales assistant"})
                self.api.post(finance, f"/people/terms/{terms['id']}/approve")
                first = self.api.post(hr, f"/people/employees/{e['id']}/bank-accounts", {
                    "method": "bank", "account_no": "0179044521", "bank_name": "Commerce Bank"})
                self.api.post(finance, f"/people/bank-accounts/{first['id']}/approve")
            with self.day_window(g, dtime(15, 0), dtime(15, 30)):
                second = self.api.post(hr, f"/people/employees/{e['id']}/bank-accounts", {
                    "method": "mobile_money", "account_no": "+254733000111"})
                self.api.post(finance, f"/people/bank-accounts/{second['id']}/approve")
            self.story_data["ghost"] = {"employee": "Collins Barasa", "added": str(g)}
        # payroll: every finished month in the history is run, approved by someone else, posted and paid
        for first, last in runs:
            with self.day_window(last, dtime(15, 0), dtime(18, 0)):
                body = {"company_id": co, "period_start": first.isoformat(), "period_end": last.isoformat(), "pay_date": last.isoformat()}
                run = self.api.post(finance, "/people/payroll-runs", body)
                self.api.post(finance, f"/people/payroll-runs/{run['id']}/calculate")
                self.api.post(finance, f"/people/payroll-runs/{run['id']}/submit")
                self.api.post("owner", f"/people/payroll-runs/{run['id']}/approve")
                self.api.post(finance, f"/people/payroll-runs/{run['id']}/pay", {"paid_on": last.isoformat()})
                self.stats["payroll_runs"] += 1
        # and the month under way is being prepared (not yet sent for approval)
        month_first = self.today.replace(day=1)
        month_last = date(self.today.year + (self.today.month == 12), self.today.month % 12 + 1, 1) - timedelta(days=1)
        r = self.api.raw(finance, "POST", "/people/payroll-runs", json={
            "company_id": co, "period_start": month_first.isoformat(), "period_end": month_last.isoformat(),
            "pay_date": month_last.isoformat()})
        if r.status_code in (200, 201):
            self.api.raw(finance, "POST", f"/people/payroll-runs/{r.json()['id']}/calculate")
            self.stats["payroll_runs_in_draft"] += 1
        log(f"{len(self.employees)} employees, 3 statutory rules, {self.stats['payroll_runs']} payroll runs paid, "
            f"{self.stats['payroll_runs_in_draft']} being prepared", started)

    def leave_and_attendance(self, runs: list[tuple[date, date]]) -> None:
        co = self.company
        hr = "hr"
        types: dict[str, str] = {}
        with self.day_window(self.start - timedelta(days=1), dtime(10, 0), dtime(11, 0)):
            for name, days, paid in (("Annual leave", "21", True), ("Sick leave", "14", True), ("Unpaid leave", None, False)):
                types[name] = self.api.post(hr, "/people/leave-types", {
                    "company_id": co, "name": name, "days_per_year": days, "is_paid": paid})["id"]
        t = self.today
        wanted = [("Lucy Chebet", "Annual leave", 20, 5, "approved"), ("Dennis Maina", "Sick leave", 12, 2, "approved"),
                  ("Esther Wafula", "Annual leave", 35, 3, "approved"), ("Kevin Otieno", "Unpaid leave", 17, 2, "approved"),
                  ("Peter Njoroge", "Sick leave", 9, 1, "rejected"), ("Ruth Kiptoo", "Annual leave", 2, 5, "pending"),
                  ("Joseph Karanja", "Annual leave", 1, 4, "pending")]
        on_leave: dict[str, set[date]] = defaultdict(set)
        for name, kind, back, length, outcome in wanted:
            if name not in self.employees or self.cfg["days"] < 30:
                continue
            first = t - timedelta(days=back)
            while first.weekday() >= 5:
                first += timedelta(days=1)
            last = first
            away = [first]
            while len(away) < length:
                last += timedelta(days=1)
                if last.weekday() < 5:
                    away.append(last)
            when = t - timedelta(days=back + 4) if outcome != "pending" else t - timedelta(days=6 if name == "Ruth Kiptoo" else 5)
            e = self.employees[name]
            with self.day_window(when, dtime(9, 0), dtime(9, 30)):
                req = self.api.post(hr, "/people/leave-requests", {
                    "employee_id": e["id"], "leave_type_id": types[kind], "start_date": away[0].isoformat(),
                    "end_date": away[-1].isoformat(), "days": str(len(away)), "reason": "Planned time off" if kind != "Sick leave" else "Unwell"})
            if outcome != "pending":
                approver = f"mgr.{self.branch_codes[e['branch']]}" if e["key"] and e["branch"] < len(self.branch_codes) else "owner"
                with self.day_window(when + timedelta(days=1), dtime(10, 0), dtime(10, 30)):
                    self.api.post(approver, f"/people/leave-requests/{req['id']}/{'approve' if outcome == 'approved' else 'reject'}",
                                  {"note": "Covered by the team" if outcome == "approved" else "Short staffed that day"})
            if outcome == "approved":
                on_leave[name].update(away)
        # attendance: the last weeks in full, and one record each for the older payroll months
        span = min(self.cfg["days"], 14)
        recorded = 0
        with self.day_window(t - timedelta(days=1), dtime(18, 0), dtime(19, 30)):
            for name, e in self.employees.items():
                day = t - timedelta(days=span)
                while day < t:
                    if day.weekday() < 5 and day not in on_leave[name]:
                        late = self.rng.random() < 0.06
                        overtime = Decimal(self.rng.choice([0, 0, 0, 1, 2])) if e["job"] in ("Cashier", "Loader", "Sales assistant") else Decimal(0)
                        self.api.post("hr", "/people/attendance", {
                            "employee_id": e["id"], "work_date": day.isoformat(),
                            "clock_in": self.at(day, dtime(8, 25) if not late else dtime(8, 55)),
                            "clock_out": self.at(day, dtime(17, 35)), "hours": "8.00", "overtime_hours": str(overtime)})
                        recorded += 1
                    day += timedelta(days=1)
                for first, last in runs:
                    if last < t - timedelta(days=span):
                        mid = first + timedelta(days=10)
                        while mid.weekday() >= 5:
                            mid += timedelta(days=1)
                        self.api.post("hr", "/people/attendance", {
                            "employee_id": e["id"], "work_date": mid.isoformat(), "clock_in": self.at(mid, dtime(8, 30)),
                            "clock_out": self.at(mid, dtime(17, 30)), "hours": "8.00"})
                        recorded += 1
        self.stats["attendance_records"] = recorded

    # ================================================================ sales leads, a bank reconciliation, an import
    def crm_pipeline(self) -> None:
        started = time.time()
        co, rng = self.company, self.rng
        if self.cfg["days"] < 30:
            return
        sources = {}
        with self.day_window(self.start - timedelta(days=1), dtime(11, 0), dtime(11, 30)):
            for name in ("Walk-in enquiry", "Referral from a customer", "Facebook page", "Signboard on the highway", "Site visit"):
                sources[name] = self.api.post("rep", "/crm/lead-sources", {"name": name})["id"]
        src_ids = list(sources.values())
        owners = ["rep"] + [f"mgr.{c}" for c in self.branch_codes]
        outcomes = ["new", "new", "contacted", "contacted", "contacted", "qualified", "qualified", "converted", "lost",
                    "contacted", "new", "qualified", "lost", "contacted", "new"]
        overdue_for_rep = 0
        for i, biz in enumerate(LEAD_NAMES):
            created = self.today - timedelta(days=rng.randint(4, min(80, self.cfg["days"])))
            owner = owners[0] if i % 2 == 0 else owners[i % len(owners)]
            with self.day_window(created, dtime(9, 0), dtime(9, 20)):
                lead = self.api.post(owner, "/crm/leads", {
                    "company_id": co, "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", "business_name": biz,
                    "phone": f"+2547{40000000 + i * 5113:08d}"[:13], "email": f"info@{self._slug(biz)}.test",
                    "source_id": rng.choice(src_ids), "owner_user_id": self.users[owner]["id"], "customer_kind": "business"})
            outcome = outcomes[i % len(outcomes)]
            moved = created + timedelta(days=rng.randint(1, 6))
            if outcome != "new":
                with self.day_window(min(moved, self.today - timedelta(days=1)), dtime(10, 0), dtime(10, 20)):
                    steps = {"contacted": ["contacted"], "qualified": ["contacted", "qualified"],
                             "converted": ["contacted", "qualified"], "lost": ["contacted"]}[outcome]
                    for st in steps:
                        self.api.post(owner, f"/crm/leads/{lead['id']}/status", {"status": st})
                    if outcome == "lost":
                        self.api.post(owner, f"/crm/leads/{lead['id']}/status", {
                            "status": "lost", "lost_reason": rng.choice(["Went with a cheaper supplier", "Project postponed"])})
                    if outcome == "converted":
                        self.api.post(owner, f"/crm/leads/{lead['id']}/convert", {"customer_group": None})
            if outcome in ("new", "contacted", "qualified"):
                due = created + timedelta(days=rng.randint(2, 20))
                if owner == "rep" and overdue_for_rep < 6:
                    due = self.today - timedelta(days=rng.randint(5, 25))
                    overdue_for_rep += 1
                with self.day_window(min(moved, self.today - timedelta(days=1)), dtime(10, 30), dtime(10, 40)):
                    act = self.api.post(owner, "/crm/activities", {
                        "related_type": "lead", "related_id": lead["id"], "kind": rng.choice(["call", "visit", "message"]),
                        "due_at": datetime.combine(due, dtime(10, 0), tzinfo=self.zone).isoformat(),
                        "owner_user_id": self.users[owner]["id"], "note": "Follow up on the quotation"})
                if due < self.today - timedelta(days=12) and owner != "rep":
                    with self.day_window(due, dtime(11, 0), dtime(11, 10)):
                        self.api.post(owner, f"/crm/activities/{act['id']}/done", {"note": "Spoke to them; sending prices"})
            self.stats["leads"] += 1
        log(f"{self.stats['leads']} leads with follow-ups", started)

    def after_move(self) -> None:
        """What needs the days to be where they belong first: the bank reconciliation, then the daily closes."""
        self.reconciliation()
        self.reconcile_payments()
        self.daily_closes()
        self.seed_end = self.db_now()
        self.move_phases()
        self.extras()

    def reconcile_payments(self) -> None:
        """The provider statements arrive (M-Pesa, the card terminal, the bank) and are matched to what was recorded."""
        from ziira.kernel import jobs

        started = time.time()
        rows = self.sql(
            "select p.payment_account_id, a.kind, p.direction, p.external_ref, p.amount, p.created_at, p.business_date "
            "from payments.payment p join payments.payment_account a on a.id = p.payment_account_id "
            "where p.status = 'posted' and p.external_ref is not null and a.kind in ('mobile_money', 'card', 'bank') "
            "and p.business_date <= :cut order by p.created_at", cut=self.today - timedelta(days=1))
        by_account: dict[Any, list[Any]] = defaultdict(list)
        kinds: dict[Any, str] = {}
        for acct, kind, direction, ref, amount, created, bdate in rows:
            by_account[acct].append((direction, ref, Decimal(amount), created.astimezone(self.zone), bdate))
            kinds[acct] = kind
        rng = self.rng
        leave_out = set()           # payments the statement never shows (story: no provider evidence)
        recent = [(a, r) for a, items in by_account.items() for r in items
                  if r[4] >= self.today - timedelta(days=4) and r[0] == "in" and r[2] >= 1000 and kinds[a] == "mobile_money"]
        for _a, r in rng.sample(recent, min(2, len(recent))):
            leave_out.add(r[1])
        self.story_data["no_evidence_refs"] = sorted(leave_out)
        sent = 0
        for acct, items in by_account.items():
            kind = kinds[acct]
            lines = []
            for direction, ref, amount, when, _bdate in items:
                if ref in leave_out:
                    continue
                lines.append((when, direction, ref, amount))
            if kind == "mobile_money" and acct == next(a for a in by_account if kinds[a] == "mobile_money"):
                # money that arrived on the till and was never rung up: appears on the statement only
                for k in range(2):
                    when = datetime.now(self.zone).replace(microsecond=0) - timedelta(days=rng.randint(2, 6), hours=rng.randint(1, 5))
                    lines.append((when, "in", f"UNK{rng.randint(10000, 99999)}{k}", Decimal(rng.choice([1500, 2300, 4200, 780]))))
            lines.sort(key=lambda x: x[0])
            if kind == "mobile_money":
                body = "Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn\n" + "".join(
                    f"{ref},{when:%Y-%m-%d %H:%M:%S},{'Customer payment' if d == 'in' else 'Transfer to bank'},Completed,"
                    f"{amount if d == 'in' else ''},{amount if d == 'out' else ''}\n" for when, d, ref, amount in lines)
                fmt = "mpesa"
            else:
                body = "Date,Description,Reference,Debit,Credit\n" + "".join(
                    f"{when:%Y-%m-%d %H:%M:%S},{'Card settlement' if kind == 'card' else 'Deposit or transfer'},{ref},"
                    f"{amount if d == 'out' else ''},{amount if d == 'in' else ''}\n" for when, d, ref, amount in lines)
                fmt = "bank"
            self.api.post("accountant", f"/payments/accounts/{acct}/statements", {"format": fmt, "content": body, "options": {}})
            sent += 1
        for _ in range(40):
            if jobs.run_due(self.tenant_id) == 0:
                break
        matched = self.one("select count(*) from payments.match where status = 'applied'")
        log(f"{sent} provider statements loaded and matched ({matched} matches)", started)

    def daily_closes(self) -> None:
        """Each branch closes its day (except settlement days, when the managers are at the bank)."""
        started = time.time()
        done = 0
        monday_open = {d for d in self.days if d.weekday() == 0}
        for d in self.days:
            if d in monday_open and self.cfg["days"] > 20 and d in self.settlement_days():
                continue
            with self.day_window(d, dtime(20, 30), dtime(20, 50)):
                for b in range(len(self.branches)):
                    totals = self.sql(
                        "select direction, method, sum(amount) from payments.payment where branch_id = :b and "
                        "business_date = :d and status = 'posted' group by 1, 2", b=str(self.branch_ids[b]), d=d)
                    cash = Decimal(0)
                    for direction, method, amount in totals:
                        if method == "cash":
                            cash += Decimal(amount) if direction == "in" else -Decimal(amount)
                    if not totals:
                        continue
                    shortage = self.one("select coalesce(sum(variance), 0) from pos.till_session where branch_id = :b and "
                                        "business_date = :d and variance <= -2500", b=str(self.branch_ids[b]), d=d) or Decimal(0)
                    banked = money(max(cash + Decimal(shortage), Decimal(0)))
                    body = {"company_id": self.company, "branch_id": str(self.branch_ids[b]), "business_date": d.isoformat(),
                            "cash_banked": str(banked),
                            "explanation": "Till short at closing; counted twice with the cashier" if shortage else None}
                    r = self.api.raw(f"mgr.{self.branch_codes[b]}", "POST", "/payments/closes", json=body)
                    if r.status_code == 422 and "variance" in r.text:       # a payment not yet on the provider's statement
                        body["explanation"] = "A mobile money payment is not on the provider's statement yet"
                        r = self.api.raw(f"mgr.{self.branch_codes[b]}", "POST", "/payments/closes", json=body)
                    if r.status_code in (200, 201):
                        done += 1
                    else:
                        self.skipped["daily close"] += 1
                        self.first_error.setdefault("daily close", r.text[:250])
        self.stats["daily_closes"] = done
        log(f"{done} daily closes submitted", started)

    def extras(self) -> None:
        """An import from the owner's old spreadsheet of customers (one row refused, one already known), so the Imports
        screen has a history. Not essential: a failure here is reported, not fatal."""
        from ziira.kernel import jobs

        try:
            known = self.one("select code from crm.customer order by created_at limit 1") or "CUS000001"
            rows = ["name,code,kind,phone,email,tax_id,group,payment_terms_days",
                    "Mugo Steel Fabricators,,business,0722100200,accounts@mugosteel.test,P051900123K,,30",
                    "Waweru Painters,,business,0733455566,waweru@painters.test,,,14",
                    "Sunrise Nursery School,,business,0711223344,office@sunrise-nursery.test,,,45",
                    f"Old duplicate row,{known},business,0700000000,dup@example.test,,,30",
                    ",,business,0799887766,missing-name@example.test,,,30",
                    "Kariuki Transporters Sacco,,business,0722333444,sacco@kariuki.test,P051900456M,Wholesale,30"]
            day = self.today - timedelta(days=min(20, self.cfg["days"] // 2))
            with self.day_window(day, dtime(10, 0), dtime(10, 30)):
                r = self.api.client.post(
                    "/api/v1/imports/batches", params={"kind": "customers", "company_id": self.company,
                                                       "filename": "customers-from-old-spreadsheet.csv"},
                    content="\n".join(rows).encode(), headers={**self.api.headers("owner"),
                                                              "Content-Type": "application/octet-stream"})
                body = r.json()
                batch_id = body.get("id") or body["batch"]["id"]
                mapping = body.get("mapping") or body["batch"]["mapping"]
                self.api.call("owner", "PUT", f"/imports/batches/{batch_id}/mapping", json={"columns": mapping})
                self.api.post("owner", f"/imports/batches/{batch_id}/validate")
                self.api.post("owner", f"/imports/batches/{batch_id}/commit", expect=(200, 201, 202))
                for _ in range(10):
                    if jobs.run_due(self.tenant_id) == 0:
                        break
            self.stats["imports"] += 1
        except Exception as error:  # noqa: BLE001 - an import is a nicety
            log(f"the sample import could not be made: {str(error)[:200]}")
        self.seed_end = self.db_now()
        self.move_phases()

    def reconciliation(self) -> None:
        """A bank reconciliation that has been started but not finished."""
        day = self.today - timedelta(days=9)
        if self.cfg["days"] < 20 or "1020" not in self.ledger:
            return
        book = self.one("select coalesce(sum(l.debit - l.credit), 0) from finance.journal_line l "
                        "join finance.account a on a.id = l.account_id where a.code = '1020' and l.entry_date <= :d", d=day) or Decimal(0)
        with self.day_window(day, dtime(14, 0), dtime(14, 20)):
            r = self.api.raw("accountant", "POST", "/finance/bank-reconciliations", json={
                "company_id": self.company, "account_id": self.ledger["1020"]["id"], "statement_date": day.isoformat(),
                "statement_balance": str(money(Decimal(book) - Decimal("12840")))})
            if r.status_code in (200, 201):
                self.stats["bank_reconciliations"] += 1
            else:
                self.first_error["reconciliation"] = r.text[:200]

    # ================================================================ proof: verify, Intelligence, the stories
    def verify_data(self) -> bool:
        from ziira.kernel import cli

        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = cli.main(["verify", self.code])
        for line in out.getvalue().strip().splitlines():
            log(f"verify: {line.split(None, 1)[1] if ' ' in line else line}")
        if status != 0:
            log("ziira verify REPORTED PROBLEMS")
            print(err.getvalue()[-1500:])
        ok = status == 0
        tb = self.api.get("finance", "/finance/reports/trial-balance", company_id=self.company, as_of=self.today.isoformat())
        debit, credit = self._tb_totals(tb)
        balanced = debit == credit and debit > 0
        log(f"trial balance: debits {debit:,.2f}, credits {credit:,.2f}: {'balanced' if balanced else 'DOES NOT BALANCE'}")
        return ok and balanced

    @staticmethod
    def _tb_totals(tb: Any) -> tuple[Decimal, Decimal]:
        if isinstance(tb, dict):
            for key_d, key_c in (("total_debit", "total_credit"), ("debit_total", "credit_total"), ("debits", "credits")):
                if key_d in tb:
                    return Decimal(str(tb[key_d])), Decimal(str(tb[key_c]))
            rows = tb.get("lines") or tb.get("rows") or tb.get("accounts") or []
        else:
            rows = tb
        d = sum((Decimal(str(r.get("debit", 0))) for r in rows), Decimal(0))
        c = sum((Decimal(str(r.get("credit", 0))) for r in rows), Decimal(0))
        return d, c

    def tidy_exceptions(self) -> None:
        """The exceptions inbox a working business keeps: payments that were waiting for the provider's record are cleared
        once the statement matched them, and the small till differences older than a week were looked at by the branch
        manager. Recent ones, big ones and the unexplained stay open."""
        started = time.time()
        finance_id = self.users["finance"]["id"]
        self.sql(
            "update kernel.exception_item e set status = 'resolved', resolved_by = :u, "
            "resolved_at = e.created_at + interval '1 day', resolution_note = 'Matched to the provider statement' "
            "where e.kind = 'payment_without_transaction' and e.status = 'open' and exists "
            "(select 1 from payments.match m where m.payment_id = e.ref_id and m.status = 'applied')", u=str(finance_id))
        for b, code in enumerate(self.branch_codes):
            self.sql(
                "update kernel.exception_item e set status = 'resolved', resolved_by = :u, "
                "resolved_at = e.created_at + interval '1 day', resolution_note = 'Looked at with the cashier' "
                "where e.kind = 'till_variance' and e.status = 'open' and e.branch_id = :b "
                "and e.created_at < now() - interval '7 days' and abs(coalesce(e.amount, 0)) < 500",
                u=str(self.users[f"mgr.{code}"]["id"]), b=str(self.branch_ids[b]))
        left = self.one("select count(*) from kernel.exception_item where status = 'open'")
        log(f"exceptions inbox tidied: {left} still open", started)

    def run_intelligence(self) -> None:
        from ziira.kernel import jobs

        started = time.time()
        # A worker running on this machine also serves this business: it may have run the checks (and filled the
        # figures) while the history was half made and its dates were not yet right. Start those afresh.
        for table in ("intel.finding_event", "intel.finding", "intel.baseline", "command.brief", "command.pulse_figure"):
            self.sql(f"delete from {table}")
        for name in ("intel.refresh_baselines", "intel.run_checks", "command.refresh_pulse"):
            ran = jobs.run_periodic(self.tenant_id, only=name, force=True)
            if not ran:
                log(f"  {name} did not run")
        for who in ("owner", "finance", "mgr.THK"):
            self.api.raw(who, "PUT", "/command/schedules/mine/daily", json={"channel": "in_app", "send_time": "07:30", "is_active": True})
        self.api.raw("owner", "PUT", "/command/schedules/mine/weekly", json={
            "channel": "in_app", "send_time": "08:00", "weekday": 1, "is_active": True})
        jobs.run_periodic(self.tenant_id, only="command.send_briefs", force=True)
        log("baselines refreshed, checks run, figures refreshed, briefs made", started)

    def findings_by_check(self) -> list[tuple[str, str, int, str]]:
        rows = self.sql("select check_code, max(severity), count(*), max(summary) from intel.finding "
                        "where status not in ('resolved', 'dismissed') group by check_code order by check_code")
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def find(self, check: str, where: str = "true", **params: Any) -> list[Any]:
        return list(self.sql(f"select summary, severity, amount, branch_id, entity_id, period_end from intel.finding "
                             f"where check_code = :chk and ({where})", chk=check, **params))

    def assert_stories(self) -> list[tuple[int, str, bool, str]]:
        """Each planted story and the finding it should have produced."""
        results: list[tuple[int, str, bool, str]] = []
        stories: set[int] = self.cfg["stories"]

        def add(n: int, title: str, rows: list[Any], detail: str = "") -> None:
            ok = bool(rows)
            what = rows[0][0] if rows else detail
            results.append((n, title, ok, what))

        if 1 in stories:
            uid = self.users["cash2.JUJ"]["id"]
            add(1, "void rate of the Juja cashier", self.find("pos.cashier_void_rate", "entity_id = :u", u=str(uid)),
                "no pos.cashier_void_rate finding for the second Juja cashier")
        if 2 in stories:
            add(2, "till closed short", self.find("pos.till_cash_variance", "amount >= 5000"),
                "no pos.till_cash_variance finding of 5,000 or more")
        if 3 in stories and getattr(self, "cement_orders", 0) >= 4:
            add(3, "cement price rise", self.find("purchasing.supplier_price_rise", "summary ilike '%Cement 50kg%'"),
                f"no purchasing.supplier_price_rise finding for cement ({getattr(self, 'cement_orders', 0)} cement deliveries)")
        if 4 in stories:
            cid = self.customers["Otieno Construction Co"]["id"]
            add(4, "credit to an overdue customer", self.find("pos.credit_to_overdue_customer", "summary ilike '%Otieno%'"),
                "no pos.credit_to_overdue_customer finding for Otieno Construction Co")
            add(4, "the customer 70 days overdue", self.find("pos.customer_overdue", "entity_id = :c", c=str(cid)),
                "no pos.customer_overdue finding for Otieno Construction Co")
        if 5 in stories and self.story_product:
            add(5, "product out of stock at Ruiru", self.find("inventory.out_of_stock", "summary ilike '%White emulsion paint 4L%Ruiru%'"),
                "no inventory.out_of_stock finding for white emulsion paint at Ruiru")
        if 6 in stories:
            add(6, "duplicate supplier bill", self.find("purchasing.duplicate_supplier_bill"),
                "no purchasing.duplicate_supplier_bill finding")
        if 7 in stories:
            add(7, "write-off just above the limit", self.find("inventory.large_write_down"),
                "no inventory.large_write_down finding")
            add(7, "entered at 23:40", self.find("inventory.unusual_stock_moves", "summary ilike '%23:4%'"),
                "no inventory.unusual_stock_moves finding for the 23:40 adjustment")
        if 8 in stories:
            add(8, "new employee before payroll", self.find("people.changes_before_payroll", "summary ilike '%Collins Barasa%'"),
                "no people.changes_before_payroll finding for Collins Barasa")
        if 9 in stories:
            add(9, "branch sales collapse", self.find("pos.branch_sales_low", "branch_id = :b", b=str(self.branch_ids[0])),
                "no pos.branch_sales_low finding for Thika")
        if 10 in stories:
            add(10, "expense far above normal", self.find("finance.unusual_expense", "summary ilike '%Fuel%'"),
                "no finance.unusual_expense finding for fuel")
        return results

    def summary(self) -> None:
        counts = {
            "products": "select count(*) from products.product", "customers": "select count(*) from crm.customer",
            "suppliers": "select count(*) from purchasing.supplier", "users": "select count(*) from kernel.app_user",
            "employees": "select count(*) from people.employee", "POS sales": "select count(*) from pos.sale",
            "voided sales": "select count(*) from pos.sale where status = 'voided'",
            "returns": "select count(*) from pos.sales_return", "till sessions": "select count(*) from pos.till_session",
            "invoices": "select count(*) from pos.sales_invoice", "customer receipts": "select count(*) from pos.customer_receipt",
            "purchase orders": "select count(*) from purchasing.purchase_order",
            "goods receipts": "select count(*) from purchasing.goods_receipt",
            "supplier bills": "select count(*) from purchasing.supplier_bill",
            "supplier payments": "select count(*) from payments.payment where direction = 'out'",
            "stock movements": "select count(*) from inventory.stock_movement",
            "journal entries": "select count(*) from finance.journal_entry", "expenses": "select count(*) from finance.expense",
            "transfers": "select count(*) from inventory.transfer", "stock counts": "select count(*) from inventory.stock_count",
            "payroll runs": "select count(*) from people.payroll_run", "leads": "select count(*) from crm.lead",
            "audit entries": "select count(*) from kernel.audit_log",
        }
        self.created = {k: int(self.one(q) or 0) for k, q in counts.items()}
        log("created: " + ", ".join(f"{v} {k}" for k, v in self.created.items()))

    def finish(self) -> None:
        if self.skipped:
            log(f"NOT accepted by the services (skipped): {dict(self.skipped)}")
            for what, why in self.first_error.items():
                log(f"  first {what} refusal: {why}")
        self.tidy_exceptions()
        self.summary()
        ok = self.verify_data()
        # this business settles mobile money to the bank once a week, so it widens the limit of the settlement check
        self.api.raw("finance", "PATCH", "/intel/checks/payments.settlement_mismatch", json={"params": {"tolerance_percent": "25"}})
        self.run_intelligence()
        rows = self.findings_by_check()
        log(f"findings: {sum(r[2] for r in rows)} open in {len(rows)} checks")
        for check, severity, n, _summary in rows:
            print(f"        {n:4d}  {check:42s} (worst: {severity})", flush=True)
        pulse = self.sql("select metric, label, value from command.pulse_figure where branch_id is null "
                         "and day = (select max(day) from command.pulse_figure) order by metric")
        if pulse:
            log("Command Center figures (company, latest day):")
            for _metric, label, value in pulse:
                print(f"        {label}: {value}", flush=True)
        results = self.assert_stories()
        missing = [r for r in results if not r[2]]
        for n, title, good, what in results:
            print(f"        story {n:2d} {'OK     ' if good else 'MISSING'} {title}: {what}", flush=True)
        self.story_results = results
        self.ok = ok and not missing
        if missing:
            log("MISSING planted stories: " + ", ".join(f"{n} ({t})" for n, t, _g, _w in missing))


# ------------------------------------------------------------------------------------------------------ safety and main
def check_code(code: str, *, i_know: bool) -> None:
    if os.environ.get("ZIIRA_ENV", "development").lower() == "production":
        raise SystemExit("Refusing: ZIIRA_ENV=production. This script is for development data only.")
    if code.startswith("aluta"):
        raise SystemExit(f"Refusing: '{code}' is a real business (aluta-*). It is never filled with demo data.")
    if not code.startswith("demo") and not i_know:
        raise SystemExit(f"Refusing: the tenant code '{code}' does not start with 'demo'. Add --i-know if you really "
                         "mean to fill it with invented data.")


def reset_tenant(code: str, confirm: str | None) -> None:
    """Drop and recreate a demo business (only `demo-hardware` or demo-*), as the CLI does."""
    if not (code == "demo-hardware" or code.startswith("demo-")):
        raise SystemExit("--reset only works for demo-hardware or a business whose code starts with 'demo-'")
    if confirm != code:
        raise SystemExit(f"--reset needs --confirm {code}")
    from ziira.kernel import cli
    from ziira.kernel.tenants import list_tenants

    if any(t.code == code for t in list_tenants()):
        log(f"dropping {code}")
        if cli.main(["drop-tenant", code, "--confirm", code]) != 0:
            raise SystemExit("drop-tenant failed")
    log(f"creating {code}")
    os.environ["ZIIRA_OWNER_PASSWORD"] = PASSWORD
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = cli.main([
            "create-tenant", "Demo Hardware" if code == "demo-hardware" else code.replace("-", " ").title(),
            "--code", code, "--company", "Demo Hardware Ltd", "--branch-code", "THK", "--branch-name", "Thika",
            "--owner-name", "Demo Owner", "--owner-email", f"owner@{code}.test", "--currency", "KES",
            "--phone-country-code", "254", "--timezone", "Africa/Nairobi"])
    if status != 0:
        raise SystemExit("create-tenant failed")
    if code == "demo-hardware":                 # scripts/seed_demo.py remembers the demo business by its id
        made = next(t for t in list_tenants() if t.code == code)
        (ROOT / ".demo_tenant").write_text(str(made.id))


def seed(code: str, scale: str = "full", *, owner_email: str | None = None, owner_password: str = PASSWORD,
         stop_after: str | None = None) -> "Seeder":
    """Fill the existing business `code`. Returns the seeder (its `results` say what was created and found)."""
    s = Seeder(code, scale, owner_email=owner_email, owner_password=owner_password)
    s.connect()
    if s.already_filled():
        log(f"{code} already holds this demo data: nothing to do (use --reset to start over)")
        s.skipped_all = True
        return s
    s.skipped_all = False
    try:
        s.run(stop_after)
    finally:
        s.restore()
    return s


def main() -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    p.add_argument("--tenant", default="demo-hardware", help="business code (default demo-hardware)")
    p.add_argument("--scale", choices=["tiny", "small", "full"], default="full", help="tiny is for the test suite")
    p.add_argument("--i-know", action="store_true", help="allow a tenant whose code does not start with 'demo'")
    p.add_argument("--reset", action="store_true", help="drop and recreate the demo business first")
    p.add_argument("--confirm", help="the business code again, required with --reset")
    p.add_argument("--days", type=int, help="how many trading days of history (default: the scale's own: tiny 14, small 45, full 90); "
                   "sales are scaled to match")
    p.add_argument("--stop-after", help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.days:
        if not 7 <= a.days <= 120:
            raise SystemExit("--days must be between 7 and 120")
        base = SCALES[a.scale]
        SCALES[a.scale] = dict(base, days=a.days, sales=max(20, round(base["sales"] * a.days / base["days"])))
    for noisy in ("httpx", "ziira.access", "ziira"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    check_code(a.tenant, i_know=a.i_know)
    if a.reset:
        reset_tenant(a.tenant, a.confirm)
    started = time.time()
    s = seed(a.tenant, a.scale, stop_after=a.stop_after)
    if getattr(s, "skipped_all", False):
        return 0
    log(f"finished in {time.time() - started:.0f}s")
    print(f"\nSign in as owner@{a.tenant}.test with password {PASSWORD} (workspace {a.tenant}). "
          "The other logins are in docs/demo-data.md.", flush=True)
    return 0 if s.ok else 1


if __name__ == "__main__":
    sys.exit(main())

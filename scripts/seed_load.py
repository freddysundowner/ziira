# ruff: noqa: N806, E501
"""Seed a scratch business with realistic volume, to measure performance (development only).

    .venv/bin/python scripts/seed_load.py                       # small preset (CI-sized, about a minute)
    .venv/bin/python scripts/seed_load.py --preset full         # the sizes of docs/performance.md (about 30-60 minutes)
    .venv/bin/python scripts/seed_load.py --sales 50000 --products 2000 --code perf-mine

Creates a tenant whose code starts with `perf-` (random unless --code is given) and refuses any other code, so it can
never touch `demo-hardware` or a real business. Prints the workspace, the owner login and the password, and writes
them to `.perf_tenant` (gitignored) for `scripts/loadtest.py`. Drop it afterwards with
`.venv/bin/ziira drop-tenant <code> --confirm <code>` (or pass --drop to this script to drop an earlier one).

How the data is made (see docs/performance.md):
  * REAL, through the HTTP API (in process): the business, users, units of measure, tax code, price list, locations,
    payment accounts, devices, the chart of accounts, employees and their pay terms, every payroll run (calculated,
    submitted, approved and paid), and `--real-sales` sales on a real till.
  * BULK SQL, for the volume: products, customers, suppliers, tills, POS sales with their lines and payments, credit
    invoices and the receipts that settle them, goods receipts and supplier bills with their payments, and the stock
    movements and journal entries all of those produce. The bulk path writes the same tables and columns the
    services write, through the tenant's own login (row-level security on, immutability triggers on, the balance
    trigger on journal lines on), with timestamps set to the business date. It writes no audit-log or outbox rows.
    The derived data (stock balances, cost figures) are filled from the movements; afterwards the script runs
    `ziira verify` (stock ledger, books, customer ledger) to prove the bulk data is consistent.
The bulk path assumes the default chart of accounts (account codes 1010, 1030, 1040, 1100, 1200, 2000, 2100, 2200,
3100, 4000, 5000, 1300, 1020): these are the standard chart `finance` installs for a new company, not a country's.
"""

import argparse
import calendar
import json
import logging
import secrets
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, make_url, text

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".perf_tenant"
PASSWORD = "perf-pass-123"
VAT_RATE = 16                      # the fixture tax rate (tax-inclusive prices)

PRESETS: dict[str, dict[str, int]] = {
    "small": dict(products=300, customers=1000, suppliers=40, sales=3000, bills=300, employees=12, payroll_runs=3,
                  real_sales=30),
    "medium": dict(products=1500, customers=5000, suppliers=120, sales=30000, bills=1600, employees=40,
                   payroll_runs=6, real_sales=100),
    "full": dict(products=5000, customers=20000, suppliers=300, sales=150000, bills=8000, employees=100,
                 payroll_runs=12, real_sales=200),
}
BRANCHES = [("HQ", "Head office"), ("EST", "Eastlands"), ("WST", "Westlands")]
DEVICES_PER_BRANCH = 2
CREDIT_SHARE = 0.10                # share of customers with a credit account


def log(message: str, started: float | None = None) -> None:
    suffix = f"  ({time.time() - started:.1f}s)" if started else ""
    print(f"[seed] {message}{suffix}", flush=True)


def parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--preset", choices=sorted(PRESETS), default="small")
    for name in PRESETS["small"]:
        p.add_argument(f"--{name.replace('_', '-')}", type=int, default=None)
    p.add_argument("--code", help="tenant code; must start with 'perf-' (default: perf-<random>)")
    p.add_argument("--drop", metavar="CODE", help="drop an earlier perf- tenant and exit")
    return p.parse_args()


# --------------------------------------------------------------------------------------------------- helpers
class Seeder:
    def __init__(self, args: argparse.Namespace) -> None:
        self.sizes = {**PRESETS[args.preset], **{k: v for k, v in vars(args).items()
                                                 if k in PRESETS["small"] and v is not None}}
        self.code = args.code or f"perf-{secrets.token_hex(3)}"
        self.email = f"owner@{self.code}.test"
        self.ids: dict[str, Any] = {}

    # ---- API (in process)
    def api(self, method: str, path: str, who: dict[str, str] | None = None, expect: int | tuple[int, ...] = (200, 201),
            **kw: Any) -> Any:
        r = self.client.request(method, f"/api/v1{path}", headers=who or self.owner, **kw)
        ok = (expect,) if isinstance(expect, int) else expect
        if r.status_code not in ok:
            raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content and r.status_code != 204 else None

    def sign_in(self, login: str, password: str = PASSWORD) -> dict[str, str]:
        r = self.client.post("/api/v1/auth/sign-in", json={"workspace": self.code, "login": login,
                                                           "password": password, "device_id": "seed"})
        if r.status_code != 200:
            raise SystemExit(f"sign-in failed for {login}: {r.text[:200]}")
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def sql(self, statement: str, **params: Any) -> Any:
        return self.s.execute(text(statement), {"t": str(self.tenant_id), "c": str(self.company_id), **params})

    # ---- 1. the business, users and reference data (real, through the API)
    def create_business(self) -> None:
        from fastapi.testclient import TestClient

        from ziira.kernel.app import create_app
        from ziira.kernel.context import system_context
        from ziira.kernel.registry import Registry, load_event_handlers
        from ziira.kernel.tenants import create_tenant

        started = time.time()
        load_event_handlers()
        made = create_tenant(name=f"Perf {self.code}", code=self.code, company="Perf Trading Ltd",
                             branch_code=BRANCHES[0][0], branch_name=BRANCHES[0][1], owner_name="Perf Owner",
                             owner_email=self.email, owner_password=PASSWORD, currency="USD",
                             phone_country_code="44", vat_registered=True)
        self.tenant_id, self.company_id, self.branch_ids = made.tenant_id, made.company_id, [made.branch_id]
        self.db_name = made.database
        reg = Registry()
        for unit in ("pos", "crm", "finance", "purchasing", "people", "intel", "command", "mpesa"):
            reg.enable(self.tenant_id, unit)                    # pos also enables products, inventory and payments
        system_context(self.tenant_id)
        from ziira.kernel.db import tenant_session
        self.tenant_session = tenant_session
        with tenant_session(self.tenant_id) as s:
            for code, name in BRANCHES[1:]:
                bid = s.execute(text(
                    "insert into kernel.branch (tenant_id, company_id, code, name) values (:t, :c, :code, :n) "
                    "returning id"), {"t": str(self.tenant_id), "c": str(self.company_id), "code": code,
                                      "n": name}).scalar_one()
                self.branch_ids.append(bid)
        self.client = TestClient(create_app())
        self.owner = self.sign_in(self.email)
        roles = {r["name"]: r["id"] for r in self.api("GET", "/roles")}
        co = str(self.company_id)

        def user(name: str, role: str, branch: UUID | None) -> dict[str, str]:
            login = f"{name}@{self.code}.test"
            u = self.api("POST", "/users", json={"full_name": name, "email": login, "password": PASSWORD})
            self.api("POST", f"/users/{u['id']}/roles", json={
                "role_id": roles[role], "scope": "branch" if branch else "company", "company_id": co,
                "branch_id": str(branch) if branch else None})
            self.ids.setdefault("users", {})[name] = u["id"]
            return self.sign_in(login)

        self.hr = user("hr", "HR", None)
        self.finance = user("finance", "Finance Manager", None)
        self.finance2 = user("finance2", "Finance Manager", None)
        self.cashiers = [user(f"cashier{i + 1}", "Cashier", b) for i, b in enumerate(self.branch_ids)]
        self.api("PATCH", f"/companies/{co}/settings", json={"phone_country_code": "44"})

        uom = self.api("POST", "/products/uoms", json={"code": "PCS", "name": "Pieces"})["id"]
        tax = self.api("POST", "/products/tax-codes", json={
            "code": "VAT16", "name": "VAT", "vat_rate": str(VAT_RATE), "authority_code": "B"})["id"]
        price_list = self.api("POST", "/products/price-lists", json={
            "company_id": co, "name": "Retail", "is_default": True})["id"]
        self.api("POST", f"/finance/companies/{co}/books")
        self.ids.update(uom=uom, tax=tax, price_list=price_list)

        self.locations, self.devices = [], []
        for bi, branch_id in enumerate(self.branch_ids):
            code = BRANCHES[bi][0]
            loc = self.api("POST", "/inventory/locations", json={
                "company_id": co, "branch_id": str(branch_id), "code": f"{code}-STORE", "name": f"{code} store"})["id"]
            self.locations.append(loc)
            cash = self.api("POST", "/payments/accounts", json={
                "company_id": co, "branch_id": str(branch_id), "kind": "cash", "name": f"{code} till cash"})["id"]
            mm = self.api("POST", "/payments/accounts", json={
                "company_id": co, "branch_id": str(branch_id), "kind": "mobile_money", "name": f"{code} mobile money",
                "shortcode": f"60{bi}638", "provider": "fake", "provider_config": {"till_type": "till"}})["id"]
            card = self.api("POST", "/payments/accounts", json={
                "company_id": co, "branch_id": str(branch_id), "kind": "card", "name": f"{code} card terminal"})["id"]
            for d in range(DEVICES_PER_BRANCH):
                dev = self.api("POST", "/pos/devices", json={
                    "branch_id": str(branch_id), "code": f"D{d + 1}", "name": f"{code} counter {d + 1}",
                    "location_id": loc})
                self.devices.append(dict(id=dev["id"], code=f"D{d + 1}", bcode=code, branch_id=str(branch_id),
                                         location_id=loc, cashier=str(self.ids["users"][f"cashier{bi + 1}"]),
                                         cash=cash, mm=mm, card=card))
        self.api("POST", "/payments/accounts", json={"company_id": co, "kind": "bank", "name": "Main bank",
                                                      "bank_account_masked": "****4821"})
        self.bank_account = next(a["id"] for a in self.api("GET", "/payments/accounts") if a["kind"] == "bank")
        log("business, users, locations, accounts and devices created", started)

    # ---- 2. bulk catalogue
    def bulk_catalogue(self) -> None:
        started = time.time()
        n = self.sizes
        with self.tenant_session(self.tenant_id, admin=True) as s:
            self.s = s
            self.sql("insert into products.category (tenant_id, name) select :t, 'Category ' || g "
                     "from generate_series(1, 20) g")
            self.sql(
                "insert into products.product (tenant_id, company_id, sku, name, category_id, product_type, base_uom_id,"
                " tax_code_id, is_batch_tracked, reorder_level, is_active) "
                "select :t, :c, 'SKU-' || lpad(g::text, 6, '0'), "
                " (array['Cement','Paint','Nails','Pipe','Tile','Wire','Brush','Bolt','Roofing','Sand'])[1 + g % 10] "
                " || ' item ' || g, (select id from products.category order by name limit 1 offset g % 20), 'stock', "
                " :uom, :tax, false, 10, true from generate_series(1, :n) g",
                uom=self.ids["uom"], tax=self.ids["tax"], n=n["products"])
            self.sql("insert into products.barcode (tenant_id, product_id, code) "
                     "select :t, id, '6' || lpad(row_number() over (order by sku)::text, 12, '0') "
                     "from products.product")
            self.sql(
                "insert into products.price_list_item (tenant_id, price_list_id, product_id, uom_id, price, valid_from)"
                " select :t, :pl, id, :uom, 20 + floor(random() * 1980), current_date - 400 from products.product",
                pl=self.ids["price_list"], uom=self.ids["uom"])
            credit = max(1, int(n["customers"] * CREDIT_SHARE))
            self.sql(
                "insert into crm.customer (tenant_id, company_id, code, name, kind, phone, email, credit_limit,"
                " payment_terms_days, status) "
                "select :t, :c, 'C' || lpad(g::text, 6, '0'), "
                " (array['Amina','Brian','Cecilia','Daudi','Esther','Farid','Grace','Hassan','Irene','Joel'])[1 + g % 10]"
                " || ' ' || (array['Otieno','Kamau','Wanjiru','Mwangi','Njeri','Ochieng','Achieng','Kiptoo','Mutua',"
                "'Abdi'])[1 + (g / 10) % 10] || ' ' || g, case when g % 5 = 0 then 'business' else 'individual' end,"
                " '44' || (7000000000 + g)::text, 'cust' || g || '@example.test',"
                " case when g <= :credit then 100000 else 0 end, case when g <= :credit then 30 else 0 end, 'active' "
                "from generate_series(1, :n) g", credit=credit, n=n["customers"])
            self.sql(
                "insert into crm.customer_credit_version (tenant_id, customer_id, credit_limit, payment_terms_days, "
                " valid_from, reason, status) select :t, id, credit_limit, payment_terms_days, now() - interval '1 year',"
                " 'Seeded', 'active' from crm.customer where credit_limit > 0")
            self.sql(
                "insert into purchasing.supplier (tenant_id, company_id, code, name, phone, email, payment_terms_days, "
                " status) select :t, :c, 'S' || lpad(g::text, 4, '0'), 'Supplier ' || g, '44' || (7100000000 + g)::text,"
                " 'sup' || g || '@example.test', 30, 'active' from generate_series(1, :n) g", n=n["suppliers"])
        log(f"{n['products']} products, {n['customers']} customers, {n['suppliers']} suppliers", started)

    # ---- 3. bulk trading: sales, stock, purchases, receipts, journals
    def reserve(self, doc_type: str, prefix: str, branch_id: UUID | None) -> tuple[str, int, int]:
        """Create a numbering series (as the services do) and return (prefix, first number, padding); the series is
        reset to 1 so the bulk path can number from the start and move the counter on at the end."""
        from ziira.kernel.numbering import next_document_number
        next_document_number(self.s, company_id=self.company_id, branch_id=branch_id, doc_type=doc_type, prefix=prefix)
        self.sql("update kernel.document_series set next_number = 1 where company_id = :c and doc_type = :d "
                 "and branch_id is not distinct from :b", d=doc_type, b=str(branch_id) if branch_id else None)
        row = self.sql("select prefix, padding from kernel.document_series where company_id = :c and doc_type = :d "
                       "and branch_id is not distinct from :b", d=doc_type, b=str(branch_id) if branch_id else None).one()
        return row.prefix, 1, row.padding

    def finish_series(self, doc_type: str, branch_id: UUID | None, used: int) -> None:
        self.sql("update kernel.document_series set next_number = :n where company_id = :c and doc_type = :d "
                 "and branch_id is not distinct from :b", n=1 + used, d=doc_type, b=str(branch_id) if branch_id else None)

    def numbering_table(self, name: str, doc_type: str, prefix: str, per_branch: bool) -> None:
        """Temp table `name(branch_id, prefix, padding)` with the numbering series of a document type."""
        self.sql(f"create temp table {name} (branch_id uuid, prefix text, padding int, used int default 0)")
        for branch_id in (self.branch_ids if per_branch else [None]):
            pre, _, pad = self.reserve(doc_type, prefix, branch_id)
            self.sql(f"insert into {name} values (:b, :p, :pad)", b=str(branch_id) if branch_id else None, p=pre, pad=pad)

    def bulk_trading(self) -> None:
        started = time.time()
        n = self.sizes
        S, P = n["sales"], n["products"]
        with self.tenant_session(self.tenant_id, admin=True) as s:
            self.s = s
            sql = self.sql
            # ---- reference temp tables
            sql("create temp table acct as select code, id from finance.account")
            sql("create temp table s_prod as select row_number() over (order by sku) as idx, p.id, p.sku, pi.price,"
                " round(pi.price * 0.65, 2) as cost, p.tax_code_id, p.base_uom_id as uom_id "
                "from products.product p join products.price_list_item pi on pi.product_id = p.id")
            sql("create unique index on s_prod (idx)")
            sql("create temp table s_cust as select row_number() over (order by code) as idx, id, credit_limit > 0 as"
                " has_credit, payment_terms_days from crm.customer")
            sql("create unique index on s_cust (idx)")
            credit_n = sql("select count(*) from s_cust where has_credit").scalar_one()
            sql("create temp table s_sup as select row_number() over (order by code) as idx, id from "
                "purchasing.supplier")
            sql("create unique index on s_sup (idx)")
            sql("create temp table s_dev (k int, device_id uuid, code text, bcode text, branch_id uuid, location_id uuid,"
                " cashier_id uuid, cash_acct uuid, mm_acct uuid, card_acct uuid, lo float, hi float)")
            weights = [1.0 / len(self.devices)] * len(self.devices)
            low = 0.0
            for k, (d, w) in enumerate(zip(self.devices, weights, strict=True)):
                sql("insert into s_dev values (:k, :d, :code, :bc, :b, :l, :cash, :ca, :mm, :card, :lo, :hi)",
                    k=k, d=d["id"], code=d["code"], bc=d["bcode"], b=d["branch_id"], l=d["location_id"],
                    cash=d["cashier"], ca=d["cash"], mm=d["mm"], card=d["card"], lo=low, hi=low + w)
                low += w
            sql("update s_dev set hi = 1.01 where k = (select max(k) from s_dev)")
            sql("create temp table s_branch as select distinct branch_id, bcode, location_id as store from s_dev")
            sql("insert into finance.period (tenant_id, company_id, start_date, end_date, status) "
                "select :t, :c, m::date, (m + interval '1 month - 1 day')::date, 'open' "
                "from generate_series(date_trunc('month', current_date - 400), date_trunc('month', current_date), "
                " interval '1 month') m on conflict do nothing")
            log("reference tables ready", started)

            # ---- sales
            sql(f"""create temp table s_sale as
                with x as (select n, current_date - 1 - floor(365 * power(random(), 1.15))::int as day,
                      random() as r_dev, random() as r_pay, random() as r_lines, random() as r_time,
                      random() as r_cust, random() as r_cust2
                    from generate_series(1, {S}) n)
                select x.n, gen_random_uuid() as id, gen_random_uuid() as local_id, x.day,
                  d.device_id, d.code as dcode, d.bcode, d.branch_id, d.location_id, d.cashier_id, d.cash_acct,
                  d.mm_acct, d.card_acct,
                  case when x.r_lines < .35 then 1 when x.r_lines < .65 then 2 when x.r_lines < .85 then 3
                       when x.r_lines < .95 then 4 else 5 end as nlines,
                  case when x.r_pay < .55 then 'cash' when x.r_pay < .84 then 'mobile_money'
                       when x.r_pay < .92 then 'card' else 'credit' end as method,
                  x.day::timestamptz + interval '8 hours' + x.r_time * interval '12 hours' as sold_at,
                  case when x.r_pay >= .92 then 1 + floor(x.r_cust * {credit_n})::int
                       when x.r_cust < .25 then 1 + floor(x.r_cust2 * {n['customers']})::int end as cidx
                from x join s_dev d on x.r_dev >= d.lo and x.r_dev < d.hi""")
            sql("update s_sale set cidx = 1 where method = 'credit' and cidx is null")
            sql("alter table s_sale add column seq int, add column total numeric, add column tax numeric, "
                "add column cust uuid, add column till uuid, add column pay_id uuid, add column inv_id uuid")
            sql("update s_sale s set seq = r.seq from (select n, row_number() over (partition by device_id order by "
                "sold_at, n) as seq from s_sale) r where r.n = s.n")
            sql("update s_sale s set cust = c.id from s_cust c where c.idx = s.cidx")
            sql("create unique index on s_sale (n)")
            sql(f"""create temp table s_line as
                select gen_random_uuid() as id, s.id as sale_id, s.n, g as line_no, p.id as product_id, p.uom_id,
                  p.tax_code_id, p.price, p.cost, q.qty, q.qty * p.price as gross,
                  round(q.qty * p.price * {VAT_RATE} / {100 + VAT_RATE}, 2) as tax, q.qty * p.cost as cost_amount,
                  s.location_id, s.branch_id, s.day, s.sold_at
                from s_sale s cross join lateral generate_series(1, s.nlines) g
                cross join lateral (select 1 + floor({P} * power(random(), 2))::int as pidx,
                    case when random() < .7 then 1 else 1 + floor(random() * 6)::int end as qty offset 0) q
                join s_prod p on p.idx = q.pidx""")
            sql("create index on s_line (n)")
            sql("update s_sale s set total = l.total, tax = l.tax from (select n, sum(gross) as total, sum(tax) as tax "
                "from s_line group by n) l where l.n = s.n")
            # tills: one closed session per device and trading day
            sql("create temp table s_till as select gen_random_uuid() as id, device_id, day, bcode, branch_id, cashier_id,"
                " cash_acct from (select distinct device_id, day, bcode, branch_id, cashier_id, cash_acct from s_sale) x")
            sql("create unique index on s_till (device_id, day)")
            sql("update s_sale s set till = t.id from s_till t where t.device_id = s.device_id and t.day = s.day")
            sql("""insert into pos.till_session (id, tenant_id, branch_id, device_id, cash_account_id, cashier_id,
                    business_date, opened_at, opening_float, closed_at, expected_cash, counted_cash, variance, status,
                    closed_by)
                select t.id, :t, t.branch_id, t.device_id, t.cash_acct, t.cashier_id, t.day,
                  t.day::timestamptz + interval '7 hours 45 minutes', 1000, t.day::timestamptz + interval '20 hours 30 minutes',
                  1000 + coalesce(c.cash, 0), 1000 + coalesce(c.cash, 0), 0, 'closed', t.cashier_id
                from s_till t left join (select till, sum(total) as cash from s_sale where method = 'cash' group by till) c
                  on c.till = t.id""")
            log(f"{S} sales and {sql('select count(*) from s_line').scalar_one()} lines generated", started)

            # numbering tables
            self.numbering_table("n_pay", "payment", "PAY", True)
            self.numbering_table("n_inv", "sales_invoice", "INV", True)
            self.numbering_table("n_rct", "customer_receipt", "RCT", True)
            self.numbering_table("n_grn", "goods_receipt", "GRN", True)
            self.numbering_table("n_bill", "supplier_bill", "BILL", True)
            for j in ("SAL", "STK", "PUR", "CSH"):
                self.numbering_table(f"n_j{j.lower()}", f"journal_{j}", j, False)

            # ---- credit invoices and the receipts that settle most of them
            sql("update s_sale set inv_id = gen_random_uuid() where method = 'credit'")
            sql("update s_sale set pay_id = gen_random_uuid() where method <> 'credit'")
            sql("""create temp table s_inv as
                select s.inv_id as id, s.id as sale_id, s.branch_id, s.bcode, s.cust as customer_id, s.day, s.total, s.tax,
                  s.location_id, s.sold_at, s.n, c.payment_terms_days as terms,
                  (s.day < current_date - 45 and random() < .7) as paid, gen_random_uuid() as receipt_id,
                  gen_random_uuid() as receipt_pay_id
                from s_sale s join s_cust c on c.id = s.cust where s.method = 'credit'""")
            # ---- sales, lines, payments
            sql("""insert into pos.sale (id, tenant_id, created_at, created_by, company_id, branch_id, number, device_id,
                    local_id, till_session_id, customer_id, cashier_id, business_date, sold_at, subtotal, discount_total,
                    tax_total, total, paid_total, status, synced_offline, location_id)
                select id, :t, sold_at, cashier_id, :c, branch_id, 'POS-' || bcode || '-' || dcode || '-' ||
                    lpad(seq::text, 6, '0'), device_id, local_id, till, cust, cashier_id, day, sold_at, total, 0, tax,
                  total, case when method = 'credit' then 0 else total end, 'posted', false, location_id
                from s_sale order by sold_at, n""")
            sql("update pos.pos_device d set last_seq = c.m from (select device_id, max(seq) as m from s_sale group by "
                "device_id) c where c.device_id = d.id")
            sql("""insert into pos.sale_line (id, tenant_id, created_at, sale_id, line_no, product_id, uom_id, quantity,
                    list_price, unit_price, discount_amount, tax_code_id, tax_amount, line_total, cost_amount)
                select id, :t, sold_at, sale_id, line_no, product_id, uom_id, qty, price, price, 0, tax_code_id, tax, gross,
                  cost_amount from s_line order by sold_at, n, line_no""")
            sql("""insert into pos.sales_invoice (id, tenant_id, created_at, company_id, branch_id, number, customer_id,
                    sale_id, issue_date, due_date, subtotal, tax_total, total, amount_paid, status, kind, location_id,
                    credited)
                select i.id, :t, i.sold_at, :c, i.branch_id, b.prefix || lpad((row_number() over (partition by i.branch_id
                    order by i.day, i.n))::text, b.padding::int, '0'), i.customer_id, i.sale_id, i.day,
                  i.day + i.terms, i.total - i.tax, i.tax, i.total, case when i.paid then i.total else 0 end,
                  case when i.paid then 'paid' else 'issued' end, 'credit_sale', i.location_id, 0
                from s_inv i join n_inv b on b.branch_id = i.branch_id""")
            sql("update n_inv set used = (select count(*) from s_inv where s_inv.branch_id = n_inv.branch_id)")

            sql("""create temp table s_paid as
                select s.pay_id as id, s.id as sale_id, s.branch_id, s.bcode, s.method, s.total, s.day, s.sold_at, s.n,
                  s.till, s.cust, case s.method when 'cash' then s.cash_acct when 'mobile_money' then s.mm_acct
                  else s.card_acct end as acct,
                  case s.method when 'mobile_money' then 'MM' || upper(substr(md5(s.id::text), 1, 10))
                    when 'card' then 'CARD' || upper(substr(md5(s.id::text), 1, 8)) end as ref
                from s_sale s where s.method <> 'credit'""")
            # every payment of the business, with its number: customer sales, receipts and supplier payments
            sql("""create temp table p_all (id uuid, branch_id uuid, direction text, method text, acct uuid, amount numeric,
                    day date, ts timestamptz, party_type text, party_id uuid, ref text, till uuid, allocation_type text,
                    allocation_id uuid, ord bigint)""")
            sql("""insert into p_all select id, branch_id, 'in', method, acct, total, day, sold_at,
                    case when cust is not null then 'customer' end, cust, ref, till, 'sale', sale_id, n from s_paid""")
            # receipts (cash paid at the branch counter, 25 days after the invoice, if it is settled)
            sql("""insert into p_all select i.receipt_pay_id, i.branch_id, 'in', 'cash', d.cash_acct, i.total,
                    least(i.day + 25, current_date - 1), least(i.day + 25, current_date - 1)::timestamptz + interval '11 hours',
                    'customer', i.customer_id, null, null, 'invoice', i.id, 10000000 + i.n
                from s_inv i join (select distinct branch_id, cash_acct from s_dev) d on d.branch_id = i.branch_id
                where i.paid""")
            # ---- purchasing: goods receipts, bills, supplier payments
            B = n["bills"]
            sql(f"""create temp table b_bill as
                select g as n, gen_random_uuid() as id, gen_random_uuid() as receipt_id, gen_random_uuid() as pay_id,
                  br.branch_id, br.bcode, br.store as location_id,
                  s.id as supplier_id, current_date - 1 - floor(365 * random())::int as day,
                  1 + floor(random() * 4)::int as nlines, random() as r_paid
                from generate_series(1, {B}) g
                join (select row_number() over (order by branch_id) - 1 as k, branch_id, bcode, store from s_branch) br
                  on br.k = g % {len(self.branch_ids)}
                join s_sup s on s.idx = 1 + (g * 7919) % {n['suppliers']}""")
            sql("alter table b_bill add column subtotal numeric, add column tax numeric, add column paid boolean")
            sql(f"""create temp table b_line as
                select gen_random_uuid() as id, b.id as bill_id, b.receipt_id, b.n, g as line_no, p.id as product_id,
                  p.uom_id, p.tax_code_id, p.cost, q.qty, q.qty * p.cost as amount, b.day, b.branch_id, b.location_id
                from b_bill b cross join lateral generate_series(1, b.nlines) g
                cross join lateral (select 1 + floor({P} * random())::int as pidx, 10 + floor(random() * 120)::int as qty
                  offset 0) q join s_prod p on p.idx = q.pidx""")
            sql(f"update b_bill b set subtotal = l.amt, tax = round(l.amt * {VAT_RATE} / 100.0, 2) from "
                "(select bill_id, sum(amount) as amt from b_line group by bill_id) l where l.bill_id = b.id")
            sql("update b_bill set paid = r_paid < .85 and day < current_date - 31")
            sql("""insert into purchasing.goods_receipt (id, tenant_id, created_at, company_id, branch_id, number,
                    supplier_id, location_id, received_at, status)
                select b.id_r, :t, b.day::timestamptz + interval '10 hours', :c, b.branch_id,
                  n.prefix || lpad(row_number() over (partition by b.branch_id order by b.day, b.n)::text, n.padding::int,
                  '0'), b.supplier_id, b.location_id, b.day::timestamptz + interval '10 hours', 'posted'
                from (select *, receipt_id as id_r from b_bill) b join n_grn n on n.branch_id = b.branch_id""")
            sql("update n_grn set used = (select count(*) from b_bill where b_bill.branch_id = n_grn.branch_id)")
            sql("""insert into purchasing.goods_receipt_line (id, tenant_id, created_at, receipt_id, product_id, quantity,
                    unit_cost) select id, :t, day::timestamptz + interval '10 hours', receipt_id, product_id, qty, cost
                from b_line""")
            sql("""insert into purchasing.supplier_bill (id, tenant_id, created_at, company_id, branch_id, number, supplier_id,
                    supplier_invoice_no, bill_date, due_date, subtotal, tax_total, total, amount_paid, match_status, status,
                    posted_at, credited, refunded)
                select b.id, :t, b.day::timestamptz + interval '12 hours', :c, b.branch_id, n.prefix || lpad(row_number()
                    over (partition by b.branch_id order by b.day, b.n)::text, n.padding::int, '0'), b.supplier_id,
                  'INV-' || b.n, b.day, b.day + 30, b.subtotal, b.tax, b.subtotal + b.tax,
                  case when b.paid then b.subtotal + b.tax else 0 end, 'matched',
                  case when b.paid then 'paid' else 'posted' end, b.day::timestamptz + interval '12 hours', 0, 0
                from b_bill b join n_bill n on n.branch_id = b.branch_id""")
            sql("update n_bill set used = (select count(*) from b_bill where b_bill.branch_id = n_bill.branch_id)")
            sql("""insert into purchasing.supplier_bill_line (id, tenant_id, created_at, bill_id, receipt_line_id, product_id,
                    quantity, unit_cost, tax_code_id, tax_amount, line_total)
                select gen_random_uuid(), :t, day::timestamptz + interval '12 hours', bill_id, id, product_id, qty, cost,
                  tax_code_id, round(amount * 0.16, 2), amount from b_line""")
            sql("""insert into p_all select b.pay_id, b.branch_id, 'out', 'bank', :bank, b.subtotal + b.tax,
                    b.day + 30, (b.day + 30)::timestamptz + interval '15 hours', 'supplier', b.supplier_id, null, null,
                    'supplier_bill', b.id, 20000000 + b.n
                from b_bill b where b.paid and b.day + 30 < current_date""", bank=self.bank_account)
            # payments, numbered per branch in date order
            sql("""insert into payments.payment (id, tenant_id, created_at, company_id, branch_id, number, direction, method,
                    payment_account_id, amount, business_date, party_type, party_id, external_ref, status, till_session_id)
                select p.id, :t, p.ts, :c, p.branch_id, n.prefix || lpad(row_number() over (partition by p.branch_id
                    order by p.day, p.ord)::text, n.padding::int, '0'), p.direction, p.method, p.acct, p.amount, p.day,
                  p.party_type, p.party_id, p.ref, 'posted', p.till
                from p_all p join n_pay n on n.branch_id = p.branch_id""")
            sql("update n_pay set used = (select count(*) from p_all where p_all.branch_id = n_pay.branch_id)")
            sql("""insert into payments.payment_allocation (id, tenant_id, created_at, payment_id, doc_type, doc_id, amount)
                select gen_random_uuid(), :t, ts, id, allocation_type, allocation_id, amount from p_all""")
            sql("""insert into pos.customer_receipt (id, tenant_id, created_at, company_id, branch_id, number, customer_id,
                    payment_id, method, amount, received_on, status, unallocated, refunded)
                select i.receipt_id, :t, p.ts, :c, i.branch_id, b.prefix || lpad(row_number() over (partition by i.branch_id
                    order by p.day, i.n)::text, b.padding::int, '0'), i.customer_id, p.id, 'cash', i.total, p.day,
                  'posted', 0, 0
                from s_inv i join p_all p on p.id = i.receipt_pay_id join n_rct b on b.branch_id = i.branch_id""")
            sql("update n_rct set used = (select count(*) from s_inv where paid and s_inv.branch_id = n_rct.branch_id)")
            sql("""insert into pos.customer_receipt_allocation (id, tenant_id, created_at, receipt_id, invoice_id, amount)
                select gen_random_uuid(), :t, p.ts, i.receipt_id, i.id, i.total
                from s_inv i join p_all p on p.id = i.receipt_pay_id""")

            sql("""insert into pos.sale_payment (id, tenant_id, created_at, sale_id, method, payment_account_id, amount,
                    external_ref, payment_id)
                select gen_random_uuid(), :t, sold_at, sale_id, method, case when method = 'cash' then null else acct end,
                  total, ref, id from s_paid""")
            sql("""insert into pos.sale_payment (id, tenant_id, created_at, sale_id, method, amount)
                select gen_random_uuid(), :t, sold_at, id, 'credit', total from s_sale where method = 'credit'""")
            log("sales, payments, invoices and purchasing rows written", started)

            # ---- stock: opening, receipts, sales
            sql("create temp table m_open as select s.id as product_id, l.store as location_id, l.branch_id, p.cost, "
                " (greatest(0, ceil(coalesce(sold.q, 0) * 1.12)) + 20 + floor(random() * 80))::numeric as qty "
                "from products.product s join s_prod p on p.id = s.id cross join s_branch l "
                "left join (select product_id, location_id, sum(qty) as q from s_line group by 1, 2) sold "
                "  on sold.product_id = s.id and sold.location_id = l.store")
            sql("create temp table s_loc_open as select location_id, gen_random_uuid() as source_id from "
                "(select distinct location_id from m_open) x")
            sql("""create temp table s_mv as
                select gen_random_uuid() as id, o.location_id, o.branch_id, o.product_id, o.qty as quantity,
                  o.cost as unit_cost, round(o.qty * o.cost, 2) as value, 'opening' as movement_type,
                  'opening_stock' as source_type, lo.source_id, null::uuid as source_line_id,
                  current_date - 366 as day, (current_date - 366)::timestamptz as ts, 0 as rank, 0::bigint as ord
                from m_open o join s_loc_open lo on lo.location_id = o.location_id
                union all
                select gen_random_uuid(), l.location_id, l.branch_id, l.product_id, l.qty, l.cost, round(l.qty * l.cost, 2),
                  'receipt', 'goods_receipt', l.receipt_id, l.id, l.day, l.day::timestamptz + interval '10 hours', 1, l.n
                from b_line l
                union all
                select gen_random_uuid(), l.location_id, l.branch_id, l.product_id, -l.qty, l.cost,
                  -round(l.qty * l.cost, 2), 'sale', 'sale', l.sale_id, l.id, l.day, l.sold_at, 2, l.n
                from s_line l""")
            sql("""insert into inventory.stock_movement (id, tenant_id, created_at, company_id, branch_id, location_id,
                    product_id, quantity, unit_cost, value, movement_type, source_type, source_id, source_line_id,
                    business_date)
                select id, :t, ts, :c, branch_id, location_id, product_id, quantity, unit_cost, value, movement_type,
                  source_type, source_id, source_line_id, day from s_mv order by day, rank, ord, id""")
            sql("""insert into inventory.stock_balance (id, tenant_id, location_id, product_id, quantity)
                select gen_random_uuid(), :t, location_id, product_id, sum(quantity) from s_mv
                group by location_id, product_id""")
            sql("""insert into inventory.product_cost (id, tenant_id, company_id, product_id, quantity, value, average_cost)
                select gen_random_uuid(), :t, :c, product_id, sum(quantity), sum(value),
                  case when sum(quantity) > 0 then round(sum(value) / sum(quantity), 6) else 0 end
                from s_mv group by product_id""")
            log(f"{sql('select count(*) from s_mv').scalar_one()} stock movements written", started)

            # ---- the books: one journal entry per sale, per stock movement, per bill, per payment
            sql("""create temp table j_entry (id uuid, journal text, branch_id uuid, day date, ts timestamptz,
                    source_type text, source_id uuid, description text, ord bigint)""")
            sql("""create temp table j_line (entry_id uuid, branch_id uuid, account text, debit numeric, credit numeric,
                    party_type text, party_id uuid, description text)""")
            # sales: Dr cash / mobile money / card / receivable, Cr sales, Cr VAT output
            sql("""create temp table j_sale as select gen_random_uuid() as eid, s.*, 'Sale POS-' || bcode || '-' || dcode ||
                    '-' || lpad(seq::text, 6, '0') as descr from s_sale s""")
            sql("""insert into j_entry select eid, 'SAL', branch_id, day, sold_at, 'sale', id, descr, n from j_sale""")
            sql("""insert into j_line select eid, branch_id, case method when 'cash' then '1010' when 'mobile_money' then '1030'
                    when 'card' then '1040' else '1100' end, total, 0, case when method = 'credit' then 'customer' end,
                    case when method = 'credit' then cust end, descr from j_sale""")
            sql("insert into j_line select eid, branch_id, '4000', 0, total - tax, null, null, descr from j_sale")
            sql("insert into j_line select eid, branch_id, '2200', 0, tax, null, null, descr from j_sale where tax > 0")
            # stock movements: Dr/Cr inventory against cost of sales, goods received not invoiced, opening equity
            sql("""create temp table j_stock as select gen_random_uuid() as eid, m.id as mid, m.branch_id, m.day, m.ts,
                    m.movement_type, abs(m.value) as amount, m.quantity > 0 as gained,
                    row_number() over (order by m.day, m.rank, m.ord, m.id) as ord from s_mv m where m.value <> 0""")
            sql("""insert into j_entry select eid, 'STK', branch_id, day, ts, 'stock_movement', mid,
                    'Stock ' || movement_type, ord from j_stock""")
            sql("""insert into j_line select eid, branch_id, '1200', case when gained then amount else 0 end,
                    case when gained then 0 else amount end, null, null, 'Stock ' || movement_type from j_stock""")
            sql("""insert into j_line select eid, branch_id, case movement_type when 'sale' then '5000' when 'receipt' then
                    '2100' else '3100' end, case when gained then 0 else amount end, case when gained then amount else 0 end,
                    null, null, 'Stock ' || movement_type from j_stock""")
            # supplier bills: Dr goods received not invoiced, Dr VAT input, Cr payables
            sql("""create temp table j_bill as select gen_random_uuid() as eid, b.*, 'Supplier bill ' || b.n as descr
                    from b_bill b""")
            sql("insert into j_entry select eid, 'PUR', branch_id, day, day::timestamptz + interval '12 hours', "
                "'supplier_bill', id, descr, n from j_bill")
            sql("insert into j_line select eid, branch_id, '2100', subtotal, 0, null, null, descr from j_bill")
            sql("insert into j_line select eid, branch_id, '1300', tax, 0, null, null, descr from j_bill where tax > 0")
            sql("insert into j_line select eid, branch_id, '2000', 0, subtotal + tax, 'supplier', supplier_id, descr from j_bill")
            # supplier payments and customer receipts: Dr payables / Cr bank, Dr cash / Cr receivable
            sql("""create temp table j_cash as select gen_random_uuid() as eid, p.* from p_all p
                    where allocation_type in ('supplier_bill', 'invoice')""")
            sql("insert into j_entry select eid, 'CSH', branch_id, day, ts, case allocation_type when 'invoice' then "
                "'customer_payment' else 'supplier_payment' end, id, case allocation_type when 'invoice' then "
                "'Customer payment' else 'Payment of supplier bill' end, ord from j_cash")
            sql("insert into j_line select eid, branch_id, case allocation_type when 'invoice' then '1010' else '2000' end, "
                "amount, 0, case allocation_type when 'invoice' then null else party_type end, "
                "case allocation_type when 'invoice' then null else party_id end, null from j_cash")
            sql("insert into j_line select eid, branch_id, case allocation_type when 'invoice' then '1100' else '1020' end, "
                "0, amount, case allocation_type when 'invoice' then party_type else null end, "
                "case allocation_type when 'invoice' then party_id else null end, null from j_cash")
            # write them: entries numbered per journal, then their lines
            sql("""insert into finance.journal_entry (id, tenant_id, created_at, company_id, journal_id, period_id, number,
                    entry_date, source_type, source_id, description, is_manual, posted_at)
                select e.id, :t, e.ts, :c, j.id, p.id, nj.prefix || lpad(row_number() over (partition by e.journal
                    order by e.day, e.ord)::text, nj.padding::int, '0'), e.day, e.source_type, e.source_id, e.description,
                  false, e.ts
                from j_entry e join finance.journal j on j.company_id = :c and j.code = e.journal
                join finance.period p on p.company_id = :c and e.day between p.start_date and p.end_date
                join (select 'SAL' as j, * from n_jsal union all select 'STK', * from n_jstk union all
                      select 'PUR', * from n_jpur union all select 'CSH', * from n_jcsh) nj on nj.j = e.journal""")
            sql("""insert into finance.journal_line (id, tenant_id, created_at, entry_id, company_id, branch_id, account_id,
                    debit, credit, party_type, party_id, description)
                select gen_random_uuid(), :t, e.ts, l.entry_id, :c, l.branch_id, a.id, l.debit, l.credit, l.party_type,
                  l.party_id, l.description from j_line l join j_entry e on e.id = l.entry_id
                join acct a on a.code = l.account""")
            for j in ("SAL", "STK", "PUR", "CSH"):
                used = sql("select count(*) from j_entry where journal = :j", j=j).scalar_one()
                self.finish_series(f"journal_{j}", None, used)
            for table, doc_type in (("n_pay", "payment"), ("n_inv", "sales_invoice"), ("n_rct", "customer_receipt"),
                                    ("n_grn", "goods_receipt"), ("n_bill", "supplier_bill")):
                for row in sql(f"select branch_id, used from {table}").all():
                    self.finish_series(doc_type, row.branch_id, row.used)
            counts = {t: sql(f"select count(*) from {t}").scalar_one() for t in (
                "finance.journal_entry", "finance.journal_line", "inventory.stock_movement", "pos.sale")}
            log(f"books written: {counts}", started)

    # ---- 4. maintenance: statistics, like a database after a night of autovacuum
    def analyse(self) -> None:
        started = time.time()
        url = make_url(self.server_url()).set(database=self.db_name)
        engine = create_engine(url, isolation_level="AUTOCOMMIT")
        with engine.connect() as c:
            c.exec_driver_sql("vacuum (analyze)")
        engine.dispose()
        log("vacuum analyze done", started)

    def server_url(self) -> str:
        from ziira.kernel.config import get_settings
        return get_settings().tenant_server_url

    # ---- 5. payroll (real, through the API)
    def payroll(self) -> None:
        started = time.time()
        n = self.sizes
        if n["employees"] <= 0 or n["payroll_runs"] <= 0:
            return
        co = str(self.company_id)
        people = "/people"
        tax_account = self.api("POST", "/finance/accounts", json={
            "company_id": co, "code": "2400", "name": "Income tax payable", "type": "liability"})["id"]
        rules = []
        definitions = (
            ("PENSION", {"name": "Pension", "kind": "contribution", "order": 10, "base": "gross", "reduces_taxable": True,
                         "employee": {"method": "rate", "rate": "0.06", "base_maximum": "72000"},
                         "employer": {"method": "rate", "rate": "0.06", "base_maximum": "72000"}}, {}),
            ("INCOME_TAX", {"name": "Income tax", "kind": "tax", "order": 30, "base": "taxable",
                            "applies_to": "resident", "employee": {"method": "bands", "credit": "2400", "bands": [
                                {"up_to": "24000", "rate": "0.10"}, {"up_to": "32333", "rate": "0.25"},
                                {"up_to": "500000", "rate": "0.30"}, {"up_to": None, "rate": "0.35"}]}},
             {"payable_account_id": tax_account}))
        for code, definition, extra in definitions:
            rule = self.api("POST", f"{people}/rules", self.finance, json={
                "company_id": co, "code": code, "effective_from": "2024-01-01", "definition": definition,
                "source_reference": "Fixture rule for load testing", **extra})
            self.api("POST", f"{people}/rules/{rule['id']}/verify", self.finance2, json={})
            rules.append(rule["id"])
        self.api("POST", f"{people}/pay-components", self.hr, json={
            "company_id": co, "code": "HOUSE", "name": "House allowance", "kind": "earning"})
        house = next(c["id"] for c in self.api("GET", f"{people}/pay-components", self.finance) if c["code"] == "HOUSE")
        for i in range(n["employees"]):
            emp = self.api("POST", f"{people}/employees", self.hr, json={
                "company_id": co, "full_name": f"Employee {i + 1:03d}", "hire_date": "2024-01-08",
                "branch_id": str(self.branch_ids[i % len(self.branch_ids)])})
            terms = self.api("POST", f"{people}/employees/{emp['id']}/terms", self.hr, json={
                "basic_pay": str(30000 + (i % 20) * 2500), "valid_from": "2024-01-08"})
            self.api("POST", f"{people}/terms/{terms['id']}/approve", self.finance)
            self.api("POST", f"{people}/employees/{emp['id']}/pay-items", self.hr, json={
                "component_id": house, "amount": "5000", "valid_from": "2024-01-08"})
            bank = self.api("POST", f"{people}/employees/{emp['id']}/bank-accounts", self.hr, json={
                "method": "bank" if i % 2 else "mobile_money", "account_no": f"0{1000000000 + i}",
                "bank_name": "First Bank" if i % 2 else None})
            self.api("POST", f"{people}/bank-accounts/{bank['id']}/approve", self.finance)
        log(f"{n['employees']} employees set up", started)
        today = date.today()
        year, month = today.year, today.month
        periods = []
        for _ in range(n["payroll_runs"]):
            month -= 1
            if month == 0:
                month, year = 12, year - 1
            periods.append((year, month))
        for year, month in reversed(periods):
            start = date(year, month, 1)
            end = date(year, month, calendar.monthrange(year, month)[1])
            body = {"company_id": co, "period_start": start.isoformat(), "period_end": end.isoformat(),
                    "pay_date": end.isoformat()}
            run = self.api("POST", f"{people}/payroll-runs", self.finance, json=body)
            for action, who in (("calculate", self.finance), ("submit", self.finance), ("approve", self.owner),
                                ("pay", self.finance)):
                payload = {"paid_on": end.isoformat()} if action == "pay" else None
                self.api("POST", f"{people}/payroll-runs/{run['id']}/{action}", who, json=payload)
        log(f"{len(periods)} payroll runs calculated, approved and paid", started)

    # ---- 6. real sales through the API on a real till (proves the bulk shape against the real one)
    def real_sales(self) -> None:
        started = time.time()
        count = self.sizes["real_sales"]
        if count <= 0:
            return
        from uuid import uuid4
        headers = self.cashiers[0]
        device = next(d for d in self.devices if d["branch_id"] == str(self.branch_ids[0]))
        till = self.api("POST", "/pos/tills", headers, json={"device_id": device["id"], "opening_float": "1000.00"})
        products = [p for p in self.api("GET", "/products/products", params={"limit": 50})][:50]
        done = 0
        for i in range(count):
            prod = products[i % len(products)]
            body = {"till_session_id": till["id"], "local_id": str(uuid4()), "lines": [
                {"product_id": prod["id"], "quantity": "1"}], "payments": [{"method": "cash", "amount": "5000.00"}]}
            r = self.client.post("/api/v1/pos/sales", headers=headers, json=body)
            if r.status_code == 201:
                done += 1
        log(f"{done}/{count} real sales posted through the API", started)

    # ---- 7. prove the bulk data is consistent
    def verify(self) -> bool:
        started = time.time()
        out = subprocess.run([str(ROOT / ".venv/bin/ziira"), "verify", self.code], capture_output=True, text=True,
                             cwd=ROOT)
        print(out.stdout.strip()[-3000:] or "(no output)")
        if out.stderr.strip():
            print(out.stderr.strip()[-2000:])
        log(f"ziira verify exit code {out.returncode}", started)
        return out.returncode == 0

    def run(self) -> int:
        t0 = time.time()
        self.create_business()
        self.bulk_catalogue()
        self.bulk_trading()
        self.payroll()
        self.real_sales()
        self.analyse()
        ok = self.verify()
        STATE.write_text(json.dumps({"code": self.code, "login": self.email, "password": PASSWORD,
                                     "tenant_id": str(self.tenant_id), "company_id": str(self.company_id),
                                     "sizes": self.sizes}, indent=2))
        print(f"\nScratch business ready: workspace={self.code} login={self.email} password={PASSWORD}")
        print(f"Drop it with: .venv/bin/ziira drop-tenant {self.code} --confirm {self.code}")
        log(f"total {time.time() - t0:.0f}s, verify {'clean' if ok else 'REPORTED PROBLEMS'}")
        return 0 if ok else 1


def main() -> int:
    args = parse()
    for noisy in ("httpx", "ziira.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if args.drop:
        if not args.drop.startswith("perf-"):
            raise SystemExit("Only tenants whose code starts with 'perf-' can be dropped by this script")
        return subprocess.call([str(ROOT / ".venv/bin/ziira"), "drop-tenant", args.drop, "--confirm", args.drop])
    if args.code and (args.code == "demo-hardware" or not args.code.startswith("perf-")):
        raise SystemExit("Refusing: the tenant code must start with 'perf-' (never the demo or a real business)")
    return Seeder(args).run()


if __name__ == "__main__":
    sys.exit(main())

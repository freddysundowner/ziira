# ruff: noqa: E501
"""Load and latency harness: hits the hot paths of a seeded scratch business and reports p50/p95/p99 and errors.

    .venv/bin/python scripts/seed_load.py --preset full                 # once: makes the business, writes .perf_tenant
    .venv/bin/python scripts/loadtest.py --spawn                        # starts its own API on :8765, runs everything
    .venv/bin/python scripts/loadtest.py --spawn --workers 2 --tills 20 --only sale_post,product_search
    .venv/bin/python scripts/loadtest.py --base-url http://127.0.0.1:8765 --json out.json
    .venv/bin/python scripts/loadtest.py --checks-profile               # time every Intelligence check (in process)

Needs `httpx` (a dependency of the project). Signs in as the scratch business's owner (from `.perf_tenant`, or
--workspace/--login/--password). For the till scenario it creates `--tills` cashiers, devices and open tills named
`lt-*` in the scratch business (idempotent: re-running reuses them). Never point it at a real business: it posts
sales, creates users and runs payroll calculations. It refuses workspaces that do not start with `perf-`.

Scenarios (name: what it measures)
  sale_post          POST /pos/sales from N tills at once (one per cashier): the till's hot path
  sale_post_retry    the same sale sent again with the same local_id (idempotent replay: must return the first result)
  product_list, product_search, stock_balances, customer_search, receivables_ageing, trial_balance,
  profit_and_loss, balance_sheet, stock_movements, supplier_bills, sales_list, payroll_calculate, intel_run,
  command_overview, findings
A request counts as an error when it ends in HTTP 4xx/5xx (other than the statuses a scenario expects) or fails.
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".perf_tenant"
PASSWORD = "perf-pass-123"


@dataclass
class Stats:
    name: str
    concurrency: int
    latencies: list[float] = field(default_factory=list)
    errors: int = 0
    statuses: dict[int, int] = field(default_factory=dict)
    wall: float = 0.0
    sample_error: str = ""

    def pct(self, p: float) -> float:
        if not self.latencies:
            return float("nan")
        data = sorted(self.latencies)
        return data[min(len(data) - 1, int(round(p / 100 * (len(data) - 1))))]

    def row(self) -> dict[str, Any]:
        n = len(self.latencies)
        return {"scenario": self.name, "concurrency": self.concurrency, "requests": n, "errors": self.errors,
                "error_rate": round(self.errors / n, 4) if n else 0.0,
                "rps": round(n / self.wall, 1) if self.wall else 0.0,
                "p50_ms": round(self.pct(50) * 1000, 1), "p95_ms": round(self.pct(95) * 1000, 1),
                "p99_ms": round(self.pct(99) * 1000, 1), "max_ms": round(max(self.latencies, default=0) * 1000, 1),
                "mean_ms": round(statistics.fmean(self.latencies) * 1000, 1) if self.latencies else 0.0,
                "statuses": self.statuses, "sample_error": self.sample_error}


class Api:
    """A signed-in HTTP client that signs in again when its token expires."""

    def __init__(self, http: httpx.AsyncClient, workspace: str, login: str, password: str) -> None:
        self.http, self.workspace, self.login, self.password = http, workspace, login, password
        self.token = ""

    async def sign_in(self) -> None:
        for attempt in range(5):
            r = await self.http.post("/api/v1/auth/sign-in", json={
                "workspace": self.workspace, "login": self.login, "password": self.password, "device_id": "loadtest"})
            if r.status_code == 200:
                self.token = r.json()["access_token"]
                return
            if r.status_code == 429:
                await asyncio.sleep(2 + attempt * 2)
                continue
            raise SystemExit(f"sign-in failed for {self.login}: {r.status_code} {r.text[:200]}")
        raise SystemExit(f"sign-in rate limited for {self.login}")

    async def request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self.token}"}
            started = time.perf_counter()
            r = await self.http.request(method, f"/api/v1{path}", headers=headers, **kw)
            r.measured = time.perf_counter() - started          # type: ignore[attr-defined]
            if r.status_code != 401 or attempt:
                break
            await self.sign_in()
        return r


class World:
    """What the scenarios need to know about the scratch business."""

    api: Api
    company_id: str
    branch_ids: list[str]
    locations: list[str]
    product_pool: list[str]
    skus: list[str]
    customer_names: list[str]
    sale_tills: list[tuple[Api, str]]           # (cashier client, open till id)
    today: date


async def build_world(http: httpx.AsyncClient, workspace: str, login: str, password: str, tills: int) -> World:
    w = World()
    w.today = date.today()
    w.api = Api(http, workspace, login, password)
    await w.api.sign_in()
    w.company_id = (await w.api.request("GET", "/companies")).json()[0]["id"]
    locs = (await w.api.request("GET", "/inventory/locations", params={"company_id": w.company_id})).json()
    w.locations = [x["id"] for x in locs if x["kind"] == "store"]
    w.branch_ids = [x["branch_id"] for x in locs if x["kind"] == "store"]
    prods = (await w.api.request("GET", "/products/products", params={"limit": 200})).json()
    w.product_pool = [p["id"] for p in prods]
    w.skus = [p["sku"] for p in prods]
    custs = (await w.api.request("GET", "/crm/customers", params={"limit": 50})).json()
    w.customer_names = [c["name"].split()[0] for c in custs] or ["Amina"]
    w.sale_tills = await make_tills(w, http, workspace, tills)
    return w


async def make_tills(w: World, http: httpx.AsyncClient, workspace: str, count: int) -> list[tuple[Api, str]]:
    """`count` cashiers with their own device and open till, spread over the branches (created once, then reused)."""
    roles = {r["name"]: r["id"] for r in (await w.api.request("GET", "/roles")).json()}
    devices = (await w.api.request("GET", "/pos/devices")).json()
    by_code = {(d["branch_id"], d["code"]): d["id"] for d in devices}
    out: list[tuple[Api, str]] = []
    for i in range(count):
        bi = i % len(w.branch_ids)
        branch, location = w.branch_ids[bi], w.locations[bi]
        email = f"lt-cashier-{i}@{workspace}.test"
        created = await w.api.request("POST", "/users", json={"full_name": f"LT cashier {i}", "email": email,
                                                              "password": PASSWORD})
        if created.status_code == 201:
            r = await w.api.request("POST", f"/users/{created.json()['id']}/roles", json={
                "role_id": roles["Cashier"], "scope": "branch", "company_id": w.company_id, "branch_id": branch})
            assert r.status_code == 201, r.text
        cashier = Api(http, workspace, email, PASSWORD)
        await cashier.sign_in()
        code = f"LT{i}"
        device_id = by_code.get((branch, code))
        if device_id is None:
            r = await w.api.request("POST", "/pos/devices", json={
                "branch_id": branch, "code": code, "name": f"Load test till {i}", "location_id": location})
            assert r.status_code == 201, r.text
            device_id = r.json()["id"]
        opened = await cashier.request("POST", "/pos/tills", json={"device_id": device_id, "opening_float": "1000.00"})
        if opened.status_code == 201:
            till_id = opened.json()["id"]
        else:
            existing = (await cashier.request("GET", "/pos/tills", params={"status": "open", "limit": 5})).json()
            if not existing:
                raise SystemExit(f"cannot open a till for {email}: {opened.status_code} {opened.text[:200]}")
            till_id = existing[0]["id"]
        out.append((cashier, till_id))
    return out


# ---------------------------------------------------------------------------------------------------- runner
Call = Any      # async (World, worker index, iteration) -> httpx.Response | list[tuple[str, httpx.Response]]


async def run_scenario(name: str, call: Call, w: World, *, concurrency: int, requests: int,
                       expect: tuple[int, ...] = (200, 201), secondary: dict[str, Stats]) -> Stats:
    stats = Stats(name, concurrency)
    counter = {"n": 0}

    async def worker(idx: int) -> None:
        while True:
            counter["n"] += 1
            if counter["n"] > requests:
                return
            started = time.perf_counter()
            try:
                result = await call(w, idx, counter["n"])
                responses = result if isinstance(result, list) else [(name, result)]
            except Exception as error:      # network failure, timeout
                stats.latencies.append(time.perf_counter() - started)
                stats.errors += 1
                stats.sample_error = stats.sample_error or repr(error)[:200]
                continue
            for label, resp in responses:
                target = stats if label == name else secondary.setdefault(label, Stats(label, concurrency))
                target.latencies.append(getattr(resp, "measured", time.perf_counter() - started))
                target.statuses[resp.status_code] = target.statuses.get(resp.status_code, 0) + 1
                if resp.status_code not in expect:
                    target.errors += 1
                    target.sample_error = target.sample_error or f"{resp.status_code} {resp.text[:160]}"

    started = time.perf_counter()
    await asyncio.gather(*(worker(i) for i in range(concurrency)))
    stats.wall = time.perf_counter() - started
    for extra in secondary.values():
        extra.wall = stats.wall
    return stats


# ---------------------------------------------------------------------------------------------------- scenarios
def pick(items: list[Any]) -> Any:
    return items[min(len(items) - 1, int(len(items) * random.random() ** 2))]


THINK_MS = 0.0           # --think-ms: a cashier's pause between customers (0 = flat out, a stress test)


async def sale_post(w: World, idx: int, n: int) -> list[tuple[str, httpx.Response]]:
    cashier, till = w.sale_tills[idx % len(w.sale_tills)]
    if THINK_MS:
        await asyncio.sleep(random.uniform(0.5, 1.5) * THINK_MS / 1000)
    lines = [{"product_id": pick(w.product_pool), "quantity": str(random.choice([1, 1, 1, 2, 3]))}
             for _ in range(random.choice([1, 2, 2, 3]))]
    local_id = str(uuid4())
    body = {"till_session_id": till, "local_id": local_id, "lines": lines,
            "payments": [{"method": "cash", "amount": "100000.00"}]}
    first = await cashier.request("POST", "/pos/sales", json=body)
    out = [("sale_post", first)]
    if n % 10 == 0 and first.status_code in (200, 201):
        out.append(("sale_post_retry", await cashier.request("POST", "/pos/sales", json=body)))
    return out


async def product_list(w: World, idx: int, n: int) -> httpx.Response:
    return await w.api.request("GET", "/products/products", params={"limit": 50, "offset": random.choice([0, 50, 1000])})


async def product_search(w: World, idx: int, n: int) -> httpx.Response:
    term = random.choice(["Cement", "item 12", random.choice(w.skus), "Pipe item", "Roofing", "Nails item 4"])
    return await w.api.request("GET", "/products/products", params={"search": term, "limit": 20})


async def stock_balances(w: World, idx: int, n: int) -> httpx.Response:
    params: dict[str, Any] = {"location_id": random.choice(w.locations), "limit": 50}
    if n % 2:
        params["product_id"] = random.choice(w.product_pool)
    return await w.api.request("GET", "/inventory/balances", params=params)


async def customer_search(w: World, idx: int, n: int) -> httpx.Response:
    term = random.choice(w.customer_names + ["Otieno", "Kamau 1", "447000"])
    return await w.api.request("GET", "/crm/customers", params={"search": term, "limit": 20})


async def receivables_ageing(w: World, idx: int, n: int) -> httpx.Response:
    return await w.api.request("GET", "/pos/receivables/ageing")


def year_ago(w: World) -> str:
    return (w.today - timedelta(days=364)).isoformat()


async def trial_balance(w: World, idx: int, n: int) -> httpx.Response:
    return await w.api.request("GET", "/finance/reports/trial-balance", params={
        "company_id": w.company_id, "as_of": w.today.isoformat()})


async def profit_and_loss(w: World, idx: int, n: int) -> httpx.Response:
    return await w.api.request("GET", "/finance/reports/profit-and-loss", params={
        "company_id": w.company_id, "date_from": year_ago(w), "date_to": w.today.isoformat(),
        "by_branch": str(bool(n % 2)).lower()})


async def balance_sheet(w: World, idx: int, n: int) -> httpx.Response:
    return await w.api.request("GET", "/finance/reports/balance-sheet", params={
        "company_id": w.company_id, "as_of": w.today.isoformat()})


async def stock_movements(w: World, idx: int, n: int) -> httpx.Response:
    params: dict[str, Any] = {"limit": 50}
    if n % 3 == 0:
        params.update(location_id=random.choice(w.locations), product_id=random.choice(w.product_pool))
    elif n % 3 == 1:
        params.update(location_id=random.choice(w.locations))
    return await w.api.request("GET", "/inventory/movements", params=params)


async def supplier_bills(w: World, idx: int, n: int) -> httpx.Response:
    params: dict[str, Any] = {"limit": 50}
    if n % 2:
        params.update(status="posted", due_before=w.today.isoformat())
    return await w.api.request("GET", "/purchasing/bills", params=params)


async def sales_list(w: World, idx: int, n: int) -> httpx.Response:
    params: dict[str, Any] = {"limit": 50}
    if n % 2:
        params.update(branch_id=random.choice(w.branch_ids), business_date=(w.today - timedelta(days=3)).isoformat())
    return await w.api.request("GET", "/pos/sales", params=params)


async def command_overview(w: World, idx: int, n: int) -> httpx.Response:
    return await w.api.request("GET", "/command/overview", params={"company_id": w.company_id})


async def findings(w: World, idx: int, n: int) -> httpx.Response:
    path = "/intel/findings" if n % 2 else "/intel/findings/summary"
    return await w.api.request("GET", path, params={"limit": 50} if n % 2 else None)


async def intel_run(w: World, idx: int, n: int) -> httpx.Response:
    return await w.api.request("POST", "/intel/run", json={"company_id": w.company_id}, timeout=900)


PAYROLL: dict[str, str] = {}


async def payroll_calculate(w: World, idx: int, n: int) -> httpx.Response:
    if "run" not in PAYROLL:
        runs = (await w.api.request("GET", "/people/payroll-runs", params={"company_id": w.company_id, "limit": 50})).json()
        open_run = next((r for r in runs if r["status"] in ("draft", "calculated")), None)
        if open_run is None:
            first = w.today.replace(day=1)
            nxt = (first + timedelta(days=32)).replace(day=1)
            r = await w.api.request("POST", "/people/payroll-runs", json={
                "company_id": w.company_id, "period_start": first.isoformat(),
                "period_end": (nxt - timedelta(days=1)).isoformat(), "pay_date": (nxt - timedelta(days=1)).isoformat()})
            if r.status_code != 201:
                return r
            open_run = r.json()
        PAYROLL["run"] = open_run["id"]
    return await w.api.request("POST", f"/people/payroll-runs/{PAYROLL['run']}/calculate", timeout=600)


# name -> (call, default concurrency, default requests, expected statuses)
SCENARIOS: dict[str, tuple[Call, int, int, tuple[int, ...]]] = {
    "sale_post": (sale_post, 0, 400, (200, 201, 422)),          # concurrency 0: one worker per till
    "product_list": (product_list, 8, 200, (200,)),
    "product_search": (product_search, 8, 200, (200,)),
    "stock_balances": (stock_balances, 8, 200, (200,)),
    "customer_search": (customer_search, 8, 200, (200,)),
    "stock_movements": (stock_movements, 8, 150, (200,)),
    "supplier_bills": (supplier_bills, 8, 100, (200,)),
    "sales_list": (sales_list, 8, 100, (200,)),
    "receivables_ageing": (receivables_ageing, 4, 20, (200,)),
    "trial_balance": (trial_balance, 4, 20, (200,)),
    "profit_and_loss": (profit_and_loss, 4, 20, (200,)),
    "balance_sheet": (balance_sheet, 4, 20, (200,)),
    "command_overview": (command_overview, 4, 20, (200,)),
    "findings": (findings, 8, 100, (200,)),
    "payroll_calculate": (payroll_calculate, 1, 3, (200,)),
    "intel_run": (intel_run, 1, 1, (200,)),
}


# ---------------------------------------------------------------------------------------------------- reporting
def table(rows: list[dict[str, Any]]) -> str:
    head = f"{'scenario':<20}{'conc':>5}{'reqs':>7}{'err%':>7}{'rps':>8}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}"
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r['scenario']:<20}{r['concurrency']:>5}{r['requests']:>7}{r['error_rate'] * 100:>7.1f}"
                     f"{r['rps']:>8}{r['p50_ms']:>9}{r['p95_ms']:>9}{r['p99_ms']:>9}{r['max_ms']:>9}")
    return "\n".join(lines)


async def amain(args: argparse.Namespace) -> int:
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    workspace = args.workspace or state.get("code")
    login = args.login or state.get("login")
    password = args.password or state.get("password") or PASSWORD
    if not workspace or not login:
        raise SystemExit("No scratch business: run scripts/seed_load.py first (or pass --workspace and --login)")
    if not workspace.startswith("perf-"):
        raise SystemExit("Refusing: the workspace must start with 'perf-' (this tool posts sales and creates users)")
    global THINK_MS
    THINK_MS = args.think_ms
    server = None
    base = args.base_url
    if args.spawn:
        port = args.port
        env = {**os.environ}
        log_file = open(args.server_log, "w")                    # noqa: SIM115 - lives as long as the server
        server = subprocess.Popen(
            [str(ROOT / ".venv/bin/uvicorn"), "ziira.kernel.app:app", "--port", str(port), "--workers",
             str(args.workers), "--log-level", "warning"], cwd=ROOT, env=env, stdout=log_file, stderr=log_file)
        base = f"http://127.0.0.1:{port}"
    limits = httpx.Limits(max_connections=max(args.tills, 8) * 2 + 8, max_keepalive_connections=max(args.tills, 8) * 2)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(120.0), limits=limits) as http:
            for _ in range(60):
                try:
                    if (await http.get("/health")).status_code < 500:
                        break
                except httpx.HTTPError:
                    await asyncio.sleep(0.5)
            world = await build_world(http, workspace, login, password, args.tills)
            names = [n.strip() for n in args.only.split(",")] if args.only else list(SCENARIOS)
            rows: list[dict[str, Any]] = []
            for name in names:
                if name not in SCENARIOS:
                    raise SystemExit(f"Unknown scenario {name}; choose from {', '.join(SCENARIOS)}")
                call, conc, reqs, expect = SCENARIOS[name]
                concurrency = args.tills if name == "sale_post" else (args.concurrency or conc)
                requests = int(reqs * args.scale) or 1
                extra: dict[str, Stats] = {}
                print(f"running {name} ({requests} requests, concurrency {concurrency}) ...", flush=True)
                stats = await run_scenario(name, call, world, concurrency=concurrency, requests=requests,
                                           expect=expect, secondary=extra)
                for s in (stats, *extra.values()):
                    rows.append(s.row())
            print()
            print(table(rows))
            for r in rows:
                if r["errors"]:
                    print(f"  ! {r['scenario']}: {r['errors']} errors, statuses {r['statuses']}, e.g. {r['sample_error']}")
            if args.json:
                Path(args.json).write_text(json.dumps({"workspace": workspace, "base_url": base,
                                                       "workers": args.workers if args.spawn else None,
                                                       "tills": args.tills, "results": rows}, indent=2))
            return 1 if any(r["error_rate"] > 0.01 for r in rows) else 0
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=20)


def checks_profile(args: argparse.Namespace) -> int:
    """Time every Intelligence check against the scratch business, in process (what one `intel.run_checks` costs)."""
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    code = args.workspace or state.get("code")
    if not code or not code.startswith("perf-"):
        raise SystemExit("Needs the scratch business (.perf_tenant) or --workspace perf-...")
    from uuid import UUID

    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.kernel.registry import load_event_handlers
    from ziira.kernel.tenants import find_tenant
    from ziira.modules.intel.public import INTEL_CHECK, CheckContext
    from ziira.modules.intel.repository import findings_repo as repo
    from ziira.modules.intel.services import baselines as baseline_service
    from ziira.modules.intel.services import engine
    from ziira.sdk import company_setting, implementations

    load_event_handlers()
    tenant = find_tenant(code)
    system_context(tenant.id)
    timings: list[tuple[float, str, int]] = []
    with tenant_session(tenant.id, admin=True) as s:
        company_id = UUID(state["company_id"]) if state.get("company_id") else UUID(
            str(s.execute(__import__("sqlalchemy").text("select id from kernel.company limit 1")).scalar_one()))
        today = engine.local_today(s, company_id)
        tz = str(company_setting(s, company_id, "timezone"))
        baselines = baseline_service.load(s, company_id)
        settings = repo.check_settings(s)
        for check in implementations(s, INTEL_CHECK):
            enabled, overrides = settings.get(check.code, (True, {}))
            if not enabled:
                continue
            ctx = CheckContext(company_id=company_id, today=today, params=engine.effective_params(check, overrides),
                               baseline=baselines.get, timezone=tz)
            started = time.perf_counter()
            try:
                with s.begin_nested():
                    found = len(check.run(s, ctx))
            except Exception as error:
                found = -1
                print(f"  check {check.code} failed: {error}")
            timings.append((time.perf_counter() - started, check.code, found))
        s.rollback()
    total = sum(t for t, _, _ in timings)
    print(f"{len(timings)} checks, total {total:.2f}s (checks only: no findings written)")
    print(f"{'check':<44}{'seconds':>9}{'findings':>10}")
    for t, code_, found in sorted(timings, reverse=True)[:args.top]:
        print(f"{code_:<44}{t:>9.3f}{found:>10}")
    if args.json:
        Path(args.json).write_text(json.dumps({"total_s": total, "checks": [
            {"code": c, "seconds": round(t, 4), "findings": f} for t, c, f in sorted(timings, reverse=True)]}, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--base-url", default="http://127.0.0.1:8765")
    p.add_argument("--spawn", action="store_true", help="start an API server (uvicorn) on --port for the run")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--workers", type=int, default=1, help="uvicorn worker processes when --spawn")
    p.add_argument("--server-log", default="/tmp/ziira_loadtest_server.log", help="where --spawn writes the API's log")
    p.add_argument("--workspace")
    p.add_argument("--login")
    p.add_argument("--password")
    p.add_argument("--tills", type=int, default=20, help="concurrent tills for sale_post")
    p.add_argument("--think-ms", type=float, default=0.0, help="pause per till between sales (realistic: 3000+)")
    p.add_argument("--concurrency", type=int, default=0, help="override concurrency of the read scenarios")
    p.add_argument("--scale", type=float, default=1.0, help="multiply every scenario's request count")
    p.add_argument("--only", help="comma-separated scenario names")
    p.add_argument("--json", help="write the results to this file")
    p.add_argument("--checks-profile", action="store_true", help="time each Intelligence check (in process) and exit")
    p.add_argument("--top", type=int, default=25)
    args = p.parse_args()
    if args.checks_profile:
        return checks_profile(args)
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())

# ruff: noqa: E501
"""A believable month at a small gym ("Peak Gym", workspace demo-gym), so every membership screen shows a living business.

    .venv/bin/python scripts/seed_demo_gym.py                 # create demo-gym and fill it (about a minute)
    .venv/bin/python scripts/seed_demo_gym.py --reset --confirm demo-gym     # drop it and fill it again

Development only (refuses ZIIRA_ENV=production). Everything goes through the real API in this process, signed in as the owner;
only the dates of invoices and of the check-ins are moved back afterwards (the immutability triggers are switched off for
that one pass and on again), so the month looks lived in. What it plants, on purpose:

  * the fitness pack's plans (example prices), 38 members on monthly, contract, annual, off-peak and
    classes-only plans, a day-pass buyer, two people on a free trial
  * a household of three with one payer, a company account with two staff
  * 4 members whose payment is late (3 days, 9 days, 17 days, 40 days), one frozen for unpaid fees, one frozen for an injury
  * a member who cancelled (with a reason) and one cancelling at the end of the period
  * visit packs, class packs, a personal-training pack with a trainer rate and sessions, a gift voucher, lockers, a guest
  * a month of check-ins with morning and evening peaks, a few refused and one overridden
Login: owner@demo-gym.test / the demo password (ZIIRA_DEMO_PASSWORD, default demo-pass-123). Run `ziira apply-packs demo-gym` is done for you.
"""

import argparse
import os
import random
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
CODE = "demo-gym"
PASSWORD = os.environ.get("ZIIRA_DEMO_PASSWORD", "demo-pass-123")
M = "/memberships"
FIRST = ["Amina", "Brian", "Cynthia", "Daniel", "Esther", "Farouk", "Grace", "Hassan", "Irene", "James", "Kevin", "Lilian",
         "Mercy", "Nadia", "Omar", "Peter", "Queen", "Ruth", "Samuel", "Tabitha", "Umar", "Violet", "Wanjiru", "Yusuf", "Zainab"]
LAST = ["Mwangi", "Otieno", "Kamau", "Njoroge", "Achieng", "Wekesa", "Mutua", "Hussein", "Chebet", "Odhiambo", "Kariuki", "Ali"]


class Fail(Exception):
    pass


class Api:
    def __init__(self) -> None:
        from fastapi.testclient import TestClient

        from ziira.kernel.app import create_app

        self.client = TestClient(create_app())
        self.token: dict[str, str] = {}

    def headers(self) -> dict[str, str]:
        if not self.token:
            r = self.client.post("/api/v1/auth/sign-in", json={"workspace": CODE, "login": f"owner@{CODE}.test",
                                                               "password": PASSWORD, "device_id": "demo-gym-seed"})
            if r.status_code != 200:
                raise Fail(f"cannot sign in: {r.status_code} {r.text[:200]}")
            self.token = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return self.token

    def call(self, method: str, path: str, expect: tuple[int, ...] = (200, 201, 204), **kw: Any) -> Any:
        r = self.client.request(method, f"/api/v1{path}", headers=self.headers(), **kw)
        if r.status_code not in expect:
            raise Fail(f"{method} {path} -> {r.status_code}: {r.text[:300]} {kw.get('json')}")
        return r.json() if r.content and r.status_code != 204 else None

    def get(self, path: str, **params: Any) -> Any:
        return self.call("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, body: dict[str, Any] | None = None, **kw: Any) -> Any:
        return self.call("POST", path, json=body or {}, **kw)


def sh(*args: str, **env: str) -> None:
    done = subprocess.run(args, cwd=ROOT, env={**os.environ, **env}, capture_output=True, text=True)
    if done.returncode != 0:
        raise Fail(f"{' '.join(args)} failed: {done.stdout[-400:]} {done.stderr[-400:]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if os.environ.get("ZIIRA_ENV", "development") == "production":
        sys.exit("Refusing to fill a production system with demo data.")
    py = str(ROOT / ".venv" / "bin" / "ziira")
    tenants = subprocess.run([py, "tenants"], cwd=ROOT, capture_output=True, text=True).stdout
    exists = any(line.split()[:1] == [CODE] for line in tenants.splitlines())
    if args.reset:
        if args.confirm != CODE:
            sys.exit(f"--reset needs --confirm {CODE}")
        if exists:
            sh(py, "drop-tenant", CODE, "--confirm", CODE)
            exists = False
    if not exists:
        print("[gym] creating the business")
        sh(py, "install", "--all")
        sh(py, "create-tenant", "Peak Gym", "--code", CODE, "--company", "Peak Gym Ltd", "--branch-code", "MAIN",
           "--branch-name", "Main gym", "--owner-name", "Gym Owner", "--owner-email", f"owner@{CODE}.test",
           "--currency", "KES", "--phone-country-code", "254", "--timezone", "Africa/Nairobi", "--edition", "services",
           ZIIRA_OWNER_PASSWORD=PASSWORD)
    from ziira.kernel.registry import Registry

    api = Api()
    company = api.get("/companies")[0]
    co, branch = company["id"], company["branches"][0]["id"]
    listing = subprocess.run([py, "tenants"], cwd=ROOT, capture_output=True, text=True).stdout
    tenant_id = UUID(next(line.split()[-1] for line in listing.splitlines() if line.split()[:1] == [CODE]))
    reg = Registry()
    for unit in ("pos", "crm", "payments", "finance", "memberships", "bookings", "intel", "command", "pack_fitness"):
        reg.enable(tenant_id, unit)
    if api.get(f"{M}/members", limit=1):
        print("[gym] already filled; nothing to do (use --reset --confirm demo-gym to start again)")
        return
    seed(api, co, branch, tenant_id)


def seed(api: Api, co: str, branch: str, tenant_id: UUID) -> None:
    rng = random.Random(20261019)
    print("[gym] reference data")
    if not api.get("/products/uoms"):
        api.post("/products/uoms", {"code": "EA", "name": "Each"})
    if not api.get("/products/tax-codes"):
        api.post("/products/tax-codes", {"code": "VAT16", "name": "VAT 16%", "vat_rate": "16", "authority_code": "B"})
    sh(str(ROOT / ".venv" / "bin" / "ziira"), "apply-packs", CODE)
    plans = {p["code"]: p for p in api.get(f"{M}/plans", company_id=co)}
    packages = {p["code"]: p for p in api.get(f"{M}/packages", company_id=co)}
    # reasons
    reasons = {r["code"]: r["id"] for r in api.get("/settings/reason-codes") if r["category"] == "membership_cancel"}
    sale_return = next(r["id"] for r in api.get("/settings/reason-codes") if r["category"] == "sale_return")
    today = datetime.now(UTC).date()
    api.call("PATCH", f"{M}/settings", params={"company_id": co}, json={"repeat_window_minutes": 10})

    def customer(name: str, phone: str | None = None) -> dict[str, Any]:
        phone = phone or f"07{rng.randint(10, 99)}{rng.randint(100000, 999999)}"
        made = api.post("/crm/customers", {"company_id": co, "name": name, "phone": phone})
        api.post(f"/crm/customers/{made['id']}/credit", {"credit_limit": "100000", "payment_terms_days": 14, "reason": "Gym member"})
        return made

    def join(cust: dict[str, Any], plan: str, days_ago: int, **extra: Any) -> dict[str, Any]:
        return api.post(f"{M}/members", {"plan_id": plans[plan]["id"], "customer_id": cust["id"], "branch_id": branch,
                                         "start_date": (today - timedelta(days=days_ago)).isoformat(), **extra})

    print("[gym] members")
    names = [f"{first} {last}" for first in FIRST for last in LAST]
    rng.shuffle(names)
    people: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    mix = ["MONTHLY"] * 18 + ["CONTRACT12"] * 8 + ["ANNUAL"] * 3 + ["OFFPEAK"] * 5 + ["CLASSESONLY"] * 4
    for i, plan in enumerate(mix):
        c = customer(names[i])
        people.append(c)
        members.append(join(c, plan, rng.randint(2, 150)))
    print("[gym] a household, a company, trials, passes")
    parent = customer("Joyce Wambui")
    group = api.post(f"{M}/groups", {"company_id": co, "name": "The Wambui family", "kind": "household", "payer_customer_id": parent["id"]})
    for who in ("Tom Wambui", "Mary Wambui"):
        kid = customer(who)
        api.call("PUT", f"{M}/profiles/by-customer/{kid['id']}/group", json={"group_id": group["id"]})
        join(kid, "MONTHLY", 20)
    boss = customer("Savanna Logistics Ltd")
    corp = api.post(f"{M}/groups", {"company_id": co, "name": "Savanna Logistics staff", "kind": "corporate", "payer_customer_id": boss["id"]})
    for who in ("Hillary Kiprop", "Doreen Naliaka"):
        staff = customer(who)
        api.call("PUT", f"{M}/profiles/by-customer/{staff['id']}/group", json={"group_id": corp["id"]})
        join(staff, "MONTHLY", 35)
    for who in ("Trial Tina", "Trial Tony"):
        join(customer(who), "TRIAL", rng.randint(0, 2))
    join(customer("Pass Paul"), "DAYPASS", 0)
    print("[gym] terms and card numbers")
    for i, c in enumerate(people[:12]):
        api.call("PATCH", f"{M}/profiles/by-customer/{c['id']}", json={"card_number": f"WB-{1000 + i}", "emergency_name": "Next of kin", "emergency_phone": "0722000111", "emergency_relation": "Family"})
        api.post(f"{M}/customers/{c['id']}/waiver", {"accepted_name": c["name"], "method": "desk"})
    print("[gym] cancelled, cancelling, injured")
    api.post(f"{M}/members/{members[1]['id']}/cancel", {"reason_code_id": reasons["TOO_EXPENSIVE"], "at_period_end": False, "note": "Moved to a cheaper gym"})
    api.post(f"{M}/members/{members[2]['id']}/cancel", {"reason_code_id": reasons["MOVED"], "note": "Moving in two weeks"})
    api.post(f"{M}/members/{members[3]['id']}/pause", {"resume_on": (today + timedelta(days=12)).isoformat(), "note": "Knee injury"})
    print("[gym] visit packs, class packs, personal training, voucher, lockers, guest")
    for c in people[20:24]:
        api.post(f"{M}/sold-packages", {"package_id": packages["VISITS10"]["id"], "customer_id": c["id"], "branch_id": branch})
    for c in people[24:27]:
        api.post(f"{M}/sold-packages", {"package_id": packages["CLASSES10"]["id"], "customer_id": c["id"], "branch_id": branch})
    pt = api.post(f"{M}/sold-packages", {"package_id": packages["PT5"]["id"], "customer_id": people[4]["id"], "branch_id": branch})
    coach = str(uuid4())
    api.call("PUT", f"{M}/trainers/rates", json={"company_id": co, "trainer_ref": coach, "trainer_name": "Coach Kim", "basis": "percent", "amount": "40"})
    api.call("PATCH", f"{M}/settings", params={"company_id": co}, json={"voucher_product_id": packages["PT5"]["product_id"], "referral_reward": "500", "points_per_unit": "0.01", "point_value": "1"})
    api.post(f"{M}/vouchers", {"company_id": co, "branch_id": branch, "amount": "2000", "purchaser_customer_id": people[6]["id"], "note": "Birthday gift"})
    lockers = api.post(f"{M}/lockers", {"company_id": co, "branch_id": branch, "codes": [f"L{n}" for n in range(1, 13)], "fee": "500", "deposit": "1000", "product_id": plans["MONTHLY"]["service_product_id"]})
    api.post(f"{M}/lockers/{lockers[0]['id']}/assign", {"customer_id": people[5]["id"]})
    api.post(f"{M}/lockers/{lockers[1]['id']}/assign", {"customer_id": people[7]["id"]})
    api.post(f"{M}/members/{members[5]['id']}/guests", {"guest_name": "Visitor Vera", "guest_phone": "0733000999"})
    api.post(f"{M}/customers/{people[4]['id']}/measurements", {"metric": "weight", "value": "82.5", "unit": "kg"})
    api.post(f"{M}/customers/{people[4]['id']}/measurements", {"metric": "weight", "value": "80.9", "unit": "kg", "taken_on": (today - timedelta(days=28)).isoformat()})

    print("[gym] moving dates back so the month looks lived in")
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session

    system_context(tenant_id)
    with tenant_session(tenant_id, admin=True) as s:
        s.execute(text("alter table pos.sales_invoice disable trigger sales_invoice_protected"))
        # five members pay late: 3, 9, 17 and 40 days, and one is frozen for unpaid fees
        late = [(members[10], 3), (members[11], 9), (members[12], 17), (members[13], 40), (members[14], 33)]
        for m, days in late:
            run = s.execute(text("select invoice_number from memberships.invoice_run where owner_id = :m and status = 'issued' "
                                 "order by period_start limit 1"), {"m": m["id"]}).scalar()
            s.execute(text("update pos.sales_invoice set due_date = current_date - :d where number = :n"), {"d": days, "n": run})
            s.execute(text("update memberships.invoice_run set due_date = current_date - :d where invoice_number = :n"), {"d": days, "n": run})
        s.execute(text("alter table pos.sales_invoice enable trigger sales_invoice_protected"))
    api.post(f"{M}/dues/refresh", params={"company_id": co})
    api.post(f"{M}/members/{members[14]['id']}/pause", {"frozen": True, "note": "Fees unpaid for 33 days"})

    print("[gym] a month of check-ins")
    with tenant_session(tenant_id, admin=True) as s:
        s.execute(text("alter table memberships.checkin disable trigger checkin_immutable"))
        live = [m for m in members if m["id"] not in (members[1]["id"], members[3]["id"], members[14]["id"])]
        user = s.execute(text("select id from kernel.app_user order by created_at limit 1")).scalar()
        for offset in range(30, -1, -1):
            day = today - timedelta(days=offset)
            weekday = day.weekday()
            busy = {0: 0.55, 1: 0.5, 2: 0.5, 3: 0.5, 4: 0.45, 5: 0.35, 6: 0.15}[weekday]
            for m in live:
                started = date.fromisoformat(m["start_date"])
                if started > day or rng.random() > busy:
                    continue
                hour = rng.choices([6, 7, 8, 12, 13, 17, 18, 19, 20], weights=[8, 10, 6, 4, 4, 9, 12, 10, 4])[0]
                moment = datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), tzinfo=UTC) - timedelta(hours=3)
                s.execute(text(
                    "insert into memberships.checkin (tenant_id, created_by, company_id, branch_id, customer_id, member_id, "
                    "holder_type, holder_id, occurred_at, business_date, method, decision, counted) "
                    "values (:t, :u, :c, :b, :cu, :m, 'membership', :m, :at, :d, :meth, 'allow', true) on conflict do nothing"),
                    {"t": str(tenant_id), "u": user, "c": co, "b": branch, "cu": m["customer_id"], "m": m["id"], "at": moment,
                     "d": day, "meth": rng.choice(["scan", "scan", "card", "desk"])})
                s.execute(text("update memberships.profile set last_visit_on = greatest(coalesce(last_visit_on, :d), :d), "
                               "last_visit_at = :at where customer_id = :cu"), {"d": day, "at": moment, "cu": m["customer_id"]})
        s.execute(text("alter table memberships.checkin enable trigger checkin_immutable"))
    # three who stopped coming: their last visit was a month ago
    with tenant_session(tenant_id, admin=True) as s:
        for m in members[15:18]:
            s.execute(text("update memberships.profile set last_visit_on = current_date - 26 where customer_id = :c"), {"c": m["customer_id"]})
    print("[gym] today's desk: a refused entry and an override")
    desk = {"company_id": co, "branch_id": branch, "method": "scan"}
    api.post(f"{M}/checkin", {**desk, "customer_id": people[0]["id"]})
    refused = api.post(f"{M}/checkin", {**desk, "customer_id": members[3]["customer_id"]})
    api.post(f"{M}/checkin", {**desk, "customer_id": members[3]["customer_id"], "override_reason": "Came to see the trainer, not to train"})
    print("[gym] done. Sign in as", f"owner@{CODE}.test", "(workspace", CODE + ")")
    _ = (sale_return, pt, refused)


if __name__ == "__main__":
    try:
        main()
    except Fail as error:
        sys.exit(f"[gym] stopped: {error}")

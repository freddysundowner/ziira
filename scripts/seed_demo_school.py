# ruff: noqa: E501
"""A believable year in two terms at a small tutoring centre ("Bright Tutors", workspace demo-school).

    .venv/bin/python scripts/seed_demo_school.py [--scale tiny|small|full]      # create demo-school and fill it
    .venv/bin/python scripts/seed_demo_school.py --reset --confirm demo-school   # drop it and fill it again (this is how the sample goes away)

Development only (refuses ZIIRA_ENV=production). Everything goes through the real API as the owner; only the dates of the Term 2
timetable are moved back afterwards, and attendance and invoice dates set, so the term looks half done. What it plants, on purpose:

  * families with one or two children (a sibling fee plan for the second), parents as household payers, learner profile fields
  * Term 1 (finished) and Term 2 (half done): fees paid once, in instalments, or monthly; most paid
  * a weekly timetable with rosters; Maths full with a waitlist; English nearly empty (under-filled); Science with one learner often absent
  * a family whose fees are 12 days late, a short course ending in 10 days with fees unpaid
  * a report attached to two learners (one shared)
Login: owner@demo-school.test / ZIIRA_DEMO_PASSWORD (default demo-pass-123).

`seed(api, db, bill, ...)` is also called by tests/test_pack_education.py (tiny scale) against a test business.
"""

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
CODE = "demo-school"
PASSWORD = os.environ.get("ZIIRA_DEMO_PASSWORD", "demo-pass-123")
M, B = "/memberships", "/bookings"
FAMILIES = [("Wanjiru", ["Amina", "Brian"]), ("Otieno", ["Carol"]), ("Kamau", ["David", "Esther"]), ("Mutua", ["Faith"]),
            ("Achieng", ["George"]), ("Njoroge", ["Hannah", "Ian"]), ("Chebet", ["Joy"]), ("Hussein", ["Kamal"]),
            ("Odhiambo", ["Lucy", "Moses"]), ("Wekesa", ["Naomi"]), ("Kariuki", ["Oscar"]), ("Ali", ["Pendo", "Quentin"])]
ZONE = "Africa/Nairobi"        # the demo business is created in this zone (a fixture, not logic)
SCALES = {"tiny": 4, "small": 8, "full": 12}


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
                                                               "password": PASSWORD, "device_id": "demo-school-seed"})
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


def _report_pdf(title: str) -> bytes:
    import io

    from reportlab.pdfgen import canvas

    out = io.BytesIO()
    page = canvas.Canvas(out)
    page.drawString(72, 720, title)
    page.save()
    return out.getvalue()


def seed(api: Any, db: Callable[[], AbstractContextManager[Any]], bill: Callable[[date], Any], co: str, branch: str,
         today: date, scale: str = "small") -> dict[str, int]:
    """Fill a business that has the pack on. `db()` gives a system session; `bill(day)` runs the hourly billing for that day.
    Does nothing (returns {}) when the business already has members."""
    from ziira.sdk import files

    if api.get(f"{M}/members", limit=1):
        return {}
    plans = {p["code"]: p for p in api.get(f"{M}/plans", company_id=co)}
    offers = {o["name"]: o for o in api.get(f"{B}/offers", company_id=co)}
    t2_start = today - timedelta(days=35)
    t2_end = today + timedelta(days=49)
    t1_start = t2_start - timedelta(days=112)
    t1_end = t2_start - timedelta(days=21)
    families = FAMILIES[:SCALES[scale]]
    kids: list[dict[str, Any]] = []
    parents: dict[str, dict[str, Any]] = {}

    def person(name: str, phone: str) -> dict[str, Any]:
        made = api.post("/crm/customers", {"company_id": co, "name": name, "phone": phone})
        api.post(f"/crm/customers/{made['id']}/credit", {"credit_limit": "100000", "payment_terms_days": 14, "reason": "Parent"})
        return made

    def enrol(kid: dict[str, Any], plan: str, start: date, end: date) -> dict[str, Any]:
        return api.post(f"{M}/members", {"plan_id": plans[plan]["id"], "customer_id": kid["id"], "branch_id": branch,
                                         "start_date": start.isoformat(), "end_date": end.isoformat()})

    for n, (family, children) in enumerate(families):
        parent = person(f"Mr/Mrs {family}", f"07{20 + n:02d}000{100 + n}")
        group = api.post(f"{M}/groups", {"company_id": co, "name": f"The {family} family", "kind": "household", "payer_customer_id": parent["id"]})
        parents[family] = parent
        for order, child in enumerate(children):
            kid = person(f"{child} {family}", f"07{20 + n:02d}000{200 + n}")
            api.call("PUT", f"{M}/profiles/by-customer/{kid['id']}/group", json={"group_id": group["id"]})
            profile = api.call("PATCH", f"{M}/profiles/by-customer/{kid['id']}", json={
                "emergency_name": f"Mr/Mrs {family}", "emergency_phone": f"07{20 + n:02d}000{100 + n}", "emergency_relation": "Parent"})
            api.call("PUT", f"/custom-fields/values/memberships.profile/{profile['id']}", json={"values": {
                "grade": f"Grade {4 + (n + order) % 5}", "guardian_name": f"Mr/Mrs {family}", "guardian_phone": f"07{20 + n:02d}000{100 + n}",
                "guardian_relation": "Mother" if n % 2 else "Father"}})
            kid["order"], kid["family"], kid["n"] = order, family, n
            kids.append(kid)

    def term_plan(kid: dict[str, Any], term: int) -> str:
        sibling = kid["order"] > 0
        return {0: "TERM3-SIB" if sibling else "TERM3", 1: "TERM-SIB" if sibling else "TERM", 2: "MONTHLY"}[(kid["n"] + term) % 3]

    # Term 1: finished. Instalments are billed on their days; nearly everything is paid.
    members1 = [enrol(k, term_plan(k, 1) if term_plan(k, 1) != "MONTHLY" else "TERM3", t1_start, t1_end) for k in kids]
    for day in (t1_start + timedelta(days=31), t1_start + timedelta(days=62), t1_end + timedelta(days=1)):
        bill(day)                                              # the last run closes the finished term
    for m in members1[:-1]:
        _pay_all(api, co, m)
    # Term 2: half done
    members2 = []
    for k in kids:
        members2.append(enrol(k, term_plan(k, 2), t2_start, t2_end))
    bill(t2_start + timedelta(days=31))
    for m in members2[2:]:
        _pay_all(api, co, m, keep=0)
    # a family 12 days late, and a short course ending in 10 days with fees unpaid
    late = members2[0]
    short = enrol(kids[-1], "TERM2", today - timedelta(days=50), today + timedelta(days=10)) if len(kids) > 2 else None
    with db() as s:
        for m in [late, *( [short] if short else [])]:
            for run in s.execute(text("select invoice_number from memberships.invoice_run where owner_id = :m and status = 'issued'"), {"m": m["id"]}):
                s.execute(text("alter table pos.sales_invoice disable trigger sales_invoice_protected"))
                s.execute(text("update pos.sales_invoice set due_date = current_date - 12 where number = :n"), {"n": run.invoice_number})
                s.execute(text("alter table pos.sales_invoice enable trigger sales_invoice_protected"))
                s.execute(text("update memberships.invoice_run set due_date = current_date - 12 where invoice_number = :n"), {"n": run.invoice_number})
    api.post(f"{M}/dues/refresh", params={"company_id": co})

    # the weekly timetable (made ahead, then moved back so five weeks are over), with rosters
    classes = [("Mathematics class", 0, 16, 6), ("English class", 1, 16, 12), ("Science class", 2, 16, 12), ("Language class", 3, 16, 10)]
    made: list[tuple[dict[str, Any], str]] = []
    for name, weekday, hour, capacity in classes:
        first = today + timedelta(days=1)
        first += timedelta(days=(weekday - first.weekday()) % 7)
        start = datetime(first.year, first.month, first.day, hour, 0, tzinfo=ZoneInfo(ZONE))
        out = api.post(f"{B}/sessions", {"offer_id": offers[name]["id"], "starts_at": start.isoformat(), "weeks": 8, "capacity": capacity})
        for sess in out["created"]:
            made.append((sess, name))
            roster = kids if name == "Mathematics class" else (kids[:2] if name == "English class" else kids[: max(3, len(kids) // 2)])
            for k in roster:
                api.call("POST", f"{B}/sessions/{sess['id']}/book", expect=(200, 201), json={"customer_id": k["id"]})
    shift = timedelta(days=35)
    with db() as s:
        s.execute(text("update bookings.appointment set starts_at = starts_at - :d, ends_at = ends_at - :d where kind = 'class'"), {"d": shift})
        s.execute(text("update bookings.appointment_resource set blocked = tstzrange(lower(blocked) - :d, upper(blocked) - :d, '[)')"), {"d": shift})
        s.execute(text("update bookings.appointment set status = 'completed', completed_at = ends_at where kind = 'class' and ends_at < now() and status = 'confirmed'"))
        s.execute(text("update bookings.appointment_attendee t set status = 'attended' from bookings.appointment a "
                       "where a.id = t.appointment_id and a.status = 'completed' and t.status = 'booked'"))
        away = kids[0]["id"]
        s.execute(text("update bookings.appointment_attendee t set status = 'no_show' from bookings.appointment a, bookings.service_offer o "
                       "where a.id = t.appointment_id and o.id = a.offer_id and o.name = 'Science class' and a.status = 'completed' "
                       "and t.customer_id = :c"), {"c": away})
        profile_ids = [r.id for r in s.execute(text("select id from memberships.profile order by created_at limit 2"))]
        for i, pid in enumerate(profile_ids):
            info = files.attach(s, entity_type="memberships.profile", entity_id=pid, data=_report_pdf("Term 1 report"),
                                name="term-1-report.pdf", category="report", caption="Term 1 report")
            if i == 0:
                files.update_file(s, info.id, visibility="shareable")
    return {"families": len(families), "learners": len(kids), "sessions": len(made)}


def _pay_all(api: Any, co: str, member: dict[str, Any], keep: int = 0) -> None:
    owed = api.get(f"{M}/members/{member['id']}")
    amount = owed.get("arrears") or "0"
    if amount not in ("0", "0.00", None):
        api.post(f"{M}/members/{member['id']}/payments", {"amount": str(amount), "method": "mobile_money", "reference": "SAMPLE"}, expect=(200, 201, 400, 409))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--scale", choices=list(SCALES), default="small")
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
        print("[school] creating the business")
        sh(py, "install", "--all")
        sh(py, "create-tenant", "Bright Tutors", "--code", CODE, "--company", "Bright Tutors Ltd", "--branch-code", "MAIN",
           "--branch-name", "Main centre", "--owner-name", "Centre Owner", "--owner-email", f"owner@{CODE}.test",
           "--currency", "KES", "--phone-country-code", "254", "--timezone", "Africa/Nairobi", "--edition", "services",
           ZIIRA_OWNER_PASSWORD=PASSWORD)
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.kernel.registry import Registry

    api = Api()
    company = api.get("/companies")[0]
    co, branch = company["id"], company["branches"][0]["id"]
    listing = subprocess.run([py, "tenants"], cwd=ROOT, capture_output=True, text=True).stdout
    tenant_id = UUID(next(line.split()[-1] for line in listing.splitlines() if line.split()[:1] == [CODE]))
    reg = Registry()
    for unit in ("pos", "crm", "payments", "finance", "memberships", "bookings", "intel", "command", "pack_education"):
        reg.enable(tenant_id, unit)
    if not api.get("/products/uoms"):
        api.post("/products/uoms", {"code": "EA", "name": "Each"})
    if not api.get("/products/tax-codes"):
        api.post("/products/tax-codes", {"code": "VAT16", "name": "VAT 16%", "vat_rate": "16", "authority_code": "B"})
    sh(py, "apply-packs", CODE)
    system_context(tenant_id)

    def db() -> AbstractContextManager[Any]:
        return tenant_session(tenant_id, admin=True)

    def bill(day: date) -> Any:
        from ziira.modules.memberships import jobs

        with tenant_session(tenant_id) as s:
            return jobs.bill_company(s, UUID(co), day)

    done = seed(api, db, bill, co, branch, datetime.now(UTC).date(), args.scale)
    print("[school] already filled; nothing to do (use --reset --confirm demo-school)" if not done else f"[school] done: {done}. Sign in as owner@{CODE}.test")


if __name__ == "__main__":
    try:
        main()
    except Fail as error:
        sys.exit(f"[school] stopped: {error}")

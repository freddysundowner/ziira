"""Intelligence checks and Command Center figures over CRM: customers over their limit, credit raises waiting, overdue
follow-ups, customers entered twice. A real business, the real engine, today is 2026-10-14.

What customers owe comes from Point of Sale. The sales flow has its own tests, so here the balance is stubbed at the one
public function CRM reads it through (`pos.public.customer_balance`), with the figures chosen by the test.
"""

from datetime import date
from decimal import Decimal as Dec  # noqa: N817
from typing import Any

import pytest
from sqlalchemy import text

import ziira.modules.pos.public as pos_public
from tests.crm_helpers import CRM, make_crm_shop, new_customer
from tests.stock_helpers import system
from ziira.modules.command.services import pulse
from ziira.modules.crm import intel_checks
from ziira.modules.crm.intel_checks import (
    CreditIncreaseWaiting,
    DuplicateCustomers,
    OverCreditLimit,
    OverdueFollowUps,
)
from ziira.modules.intel.public import CheckContext, IntelCheck
from ziira.modules.intel.services import engine

TODAY = date(2026, 10, 14)
INTEL = "/api/v1/intel"
OWED: dict[str, Dec] = {}


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    s = make_crm_shop(client, registry, "Crm Intel Co")
    # these tests are written in UTC hours: say so (test tenants are otherwise created in LOCALE["timezone"])
    client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"], json={"timezone": "UTC"})
    for unit in ("pos", "intel", "command"):
        registry.enable(s["tenant_id"], unit)
    co = str(s["company_id"])
    assert client.patch(f"/api/v1/companies/{co}/settings", headers=s["owner"],
                        json={"phone_country_code": "254"}).status_code == 200
    s["currency"] = sql(s, "select base_currency from kernel.company")[0][0]
    users = {u["email"].split("@")[0]: u["id"] for u in client.get("/api/v1/users", headers=s["owner"]).json()}
    s["users"] = users
    return s


@pytest.fixture(autouse=True)
def balances(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(pos_public, "customer_balance", lambda session, customer_id: OWED.get(str(customer_id), Dec(0)))
    monkeypatch.setattr(pos_public, "customer_balances", lambda session, ids: {i: OWED.get(str(i), Dec(0)) for i in ids})


def sql(shop, stmt: str, **params: Any) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        result = s.execute(text(stmt), params)
        return list(result.all()) if result.returns_rows else []


def run_check(shop, code: str):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=TODAY, only={code})


def findings(client, shop, code: str, *statuses: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    params: dict[str, Any] = {"check_code": code, "limit": 100}
    if statuses:
        params["status"] = list(statuses)
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


def detail(client, shop, finding: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return client.get(f"{INTEL}/findings/{finding['id']}", headers=shop["owner"]).json()


def direct(shop, check: IntelCheck, **params: Any):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        ctx = CheckContext(company_id=shop["company_id"], today=TODAY, params={**check.params, **params},
                           baseline=lambda metric, key: None)
        return check.run(s, ctx)


def with_credit(client, shop, name: str, limit: str, **kw):  # type: ignore[no-untyped-def]
    c = new_customer(client, shop, name=name, **kw)
    r = client.post(f"{CRM}/customers/{c['id']}/credit", headers=shop["fm"], json={
        "credit_limit": limit, "payment_terms_days": 30, "reason": "Agreed with the owner"})
    assert r.status_code == 201, r.text
    return c


def named(items: list[dict[str, Any]], who: str) -> dict[str, Any]:
    return next(f for f in items if f["summary"].startswith(who))


# --------------------------------------------------------------------------- over the credit limit
def test_customers_over_their_credit_limit(client, shop) -> None:  # type: ignore[no-untyped-def]
    a = with_credit(client, shop, "Wanjiku Hardware", "100000")
    b = with_credit(client, shop, "Kamau Stores", "50000")
    d = with_credit(client, shop, "Within Limits Ltd", "20000")
    c = new_customer(client, shop, name="Cash Only Shop")                          # no limit: nothing to be over
    shop["a"], shop["b"] = a, b
    OWED.update({a["id"]: Dec(130000), b["id"]: Dec(90000), d["id"]: Dec(15000), c["id"]: Dec(5000)})
    result = run_check(shop, "crm.over_credit_limit")
    assert result.created == 2 and not result.failed
    items = findings(client, shop, "crm.over_credit_limit")
    cur = shop["currency"]
    fa, fb = named(items, "Wanjiku"), named(items, "Kamau")
    assert fa["summary"] == (f"Wanjiku Hardware owes {cur} 130,000.00, which is {cur} 30,000.00 over their credit "
                             f"limit of {cur} 100,000.00.")
    assert fa["severity"] == "medium" and Dec(fa["amount"]) == 30000                  # 30% over
    assert Dec(fa["value"]) == 130000 and Dec(fa["expected_value"]) == 100000 and fa["branch_id"] is None
    assert fb["severity"] == "high" and Dec(fb["amount"]) == 40000                   # 80% over
    assert [r["id"] for r in detail(client, shop, fa)["records"]] == [a["id"]]
    assert not any(f["summary"].startswith(("Within", "Cash")) for f in items)
    # tuned: only more than 100% over counts as serious
    levels = {c_.entity_id: c_.severity for c_ in direct(shop, OverCreditLimit(), high_over_pct="100.0")}
    assert set(levels.values()) == {"medium"}


def test_an_over_limit_finding_closes_when_the_customer_pays_and_reopens_if_it_returns(client, shop) -> None:  # type: ignore[no-untyped-def]
    OWED[shop["a"]["id"]] = Dec(95000)
    closed = run_check(shop, "crm.over_credit_limit")
    assert closed.resolved == 1
    assert [f["summary"].split(" owes")[0] for f in findings(client, shop, "crm.over_credit_limit")] == ["Kamau Stores"]
    OWED[shop["a"]["id"]] = Dec(120000)
    back = run_check(shop, "crm.over_credit_limit")
    assert back.reopened == 1
    items = findings(client, shop, "crm.over_credit_limit")
    assert Dec(named(items, "Wanjiku")["amount"]) == 20000


def test_without_point_of_sale_there_are_no_balances_to_check(shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(intel_checks, "pos_is_on", lambda session: False)
    assert direct(shop, OverCreditLimit()) == []


# --------------------------------------------------------------------------- credit raises waiting
def test_a_credit_increase_waiting_for_approval(client, shop) -> None:  # type: ignore[no-untyped-def]
    rule = client.post("/api/v1/approvals/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "doc_type": "credit_limit_change",
        "approver_role_id": shop["roles"]["Finance Manager"], "min_amount": "0"})
    assert rule.status_code == 201, rule.text
    waiting = new_customer(client, shop, name="Big Contract Ltd")
    recent = new_customer(client, shop, name="Fresh Request Ltd")
    for c in (waiting, recent):
        r = client.post(f"{CRM}/customers/{c['id']}/credit", headers=shop["rep"], json={
            "credit_limit": "75000", "payment_terms_days": 30, "reason": "Big contract"})
        assert r.status_code == 201 and r.json()["status"] == "pending_approval", r.text
        shop[c["name"]] = r.json()["id"]
    sql(shop, "update crm.customer_credit_version set created_at = '2026-10-08 09:00+00' where id = :i",
        i=shop["Big Contract Ltd"])                                                  # 6 days ago
    sql(shop, "update crm.customer_credit_version set created_at = '2026-10-12 09:00+00' where id = :i",
        i=shop["Fresh Request Ltd"])                                                 # 2 days ago
    assert run_check(shop, "crm.credit_increase_waiting").created == 1
    [f] = findings(client, shop, "crm.credit_increase_waiting")
    cur = shop["currency"]
    assert f["summary"] == (f"The credit limit of Big Contract Ltd was asked to go from {cur} 0.00 to {cur} 75,000.00 "
                            "6 days ago and has not been decided.")
    assert f["severity"] == "low" and Dec(f["amount"]) == 75000 and Dec(f["value"]) == 6
    assert {r["type"] for r in detail(client, shop, f)["records"]} == {"crm.customer", "crm.customer_credit_version"}
    assert len(direct(shop, CreditIncreaseWaiting(), days=1)) == 2                   # tuned
    assert direct(shop, CreditIncreaseWaiting(), days=10) == []
    pending = client.get("/api/v1/approvals/pending", headers=shop["fm"]).json()
    request = next(x for x in pending if x["doc_id"] == shop["Big Contract Ltd"])
    assert client.post(f"/api/v1/approvals/{request['id']}/decision", headers=shop["fm"],
                       json={"approve": True}).status_code == 200
    assert run_check(shop, "crm.credit_increase_waiting").resolved == 1
    assert findings(client, shop, "crm.credit_increase_waiting") == []


# --------------------------------------------------------------------------- follow-ups
def new_lead(client, shop, name: str, who: str = "rep") -> str:  # type: ignore[no-untyped-def]
    r = client.post(f"{CRM}/leads", headers=shop[who], json={
        "company_id": str(shop["company_id"]), "name": name, "phone": "0700000001"})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def follow_up(client, shop, lead_id: str, due: str, *, who: str = "rep", related: str = "lead") -> str:  # type: ignore[no-untyped-def]
    r = client.post(f"{CRM}/activities", headers=shop[who], json={
        "related_type": related, "related_id": lead_id, "kind": "call", "due_at": f"{due}T09:00:00+00:00"})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_overdue_follow_ups_one_finding_per_owner(client, shop) -> None:  # type: ignore[no-untyped-def]
    l1, l2, l3, lost = (new_lead(client, shop, n) for n in ("Lead One", "Lead Two", "Lead Three", "Lead Lost"))
    sql(shop, "update crm.lead set status = 'lost', lost_reason = 'No budget' where id = :i", i=lost)
    shop["leads"] = (l1, l2, l3, lost)
    shop["rep_open"] = [follow_up(client, shop, l1, "2026-10-05"), follow_up(client, shop, l2, "2026-10-08"),
                        follow_up(client, shop, l3, "2026-10-09")]               # 9, 6 and 5 days overdue
    follow_up(client, shop, l1, "2026-10-12")                                     # 2 days: not yet overdue enough
    follow_up(client, shop, lost, "2026-10-02")                                   # the lead is lost: nobody needs to call
    done = follow_up(client, shop, l2, "2026-10-01")
    assert client.post(f"{CRM}/activities/{done}/done", headers=shop["rep"], json={}).status_code == 200
    fm_activity = follow_up(client, shop, l2, "2026-10-06", who="fm")            # the finance manager: 8 days overdue
    result = run_check(shop, "crm.followups_overdue")
    assert result.created == 2
    items = findings(client, shop, "crm.followups_overdue")
    rep, fm = named(items, "rep"), named(items, "fm")
    assert rep["summary"] == ("rep has 3 follow-ups on open leads more than 3 days overdue; the oldest was due on "
                              "2026-10-05.")
    assert rep["severity"] == "low" and Dec(rep["value"]) == 3 and rep["period_start"] == "2026-10-05"
    assert fm["summary"].startswith("fm has 1 follow-up on open leads") and Dec(fm["value"]) == 1
    records = detail(client, shop, rep)["records"]
    assert sorted(r["id"] for r in records) == sorted(shop["rep_open"])
    assert any("Lead One" in r["label"] and "due 2026-10-05" in r["label"] for r in records)
    # tuned: three of them is "many" for a small team; and a 7 day grace leaves the 9 and the 8 day old ones
    assert {c.severity for c in direct(shop, OverdueFollowUps(), many=3)} == {"medium", "low"}
    assert sorted(int(c.value or 0) for c in direct(shop, OverdueFollowUps(), days=7)) == [1, 1]
    # doing the calls closes that person's finding only
    for aid in shop["rep_open"]:
        assert client.post(f"{CRM}/activities/{aid}/done", headers=shop["rep"], json={}).status_code == 200
    assert run_check(shop, "crm.followups_overdue").resolved == 1
    assert [f["summary"].split(" has")[0] for f in findings(client, shop, "crm.followups_overdue")] == ["fm"]
    assert fm_activity


# --------------------------------------------------------------------------- the same customer twice
def test_customers_entered_twice(client, shop) -> None:  # type: ignore[no-untyped-def]
    old = new_customer(client, shop, name="Mama Mboga", phone="0722 111 222")
    again = new_customer(client, shop, name="Mama Mboga Two", phone="+254 722 111 222")     # the same number
    taxed = new_customer(client, shop, name="Mwangi Ltd", tax_id="P051234567X")
    taxed2 = new_customer(client, shop, name="Mwangi Limited", tax_id=" p051234567x ")
    lone = new_customer(client, shop, name="Only One", phone="0733 999 888", tax_id="P000000001Z")
    old1 = new_customer(client, shop, name="Old Twin A", phone="0744 555 666")
    old2 = new_customer(client, shop, name="Old Twin B", phone="0744 555 666")             # both long ago: not new
    clock = {old["id"]: "2026-01-05", again["id"]: "2026-10-10", taxed["id"]: "2026-02-01",
             taxed2["id"]: "2026-10-13", lone["id"]: "2026-10-12", old1["id"]: "2026-03-01", old2["id"]: "2026-03-02"}
    for customer_id, day in clock.items():
        sql(shop, "update crm.customer set created_at = cast(:d as timestamptz) where id = :i", d=day, i=customer_id)
    result = run_check(shop, "crm.duplicate_customers")
    assert result.created == 2
    items = findings(client, shop, "crm.duplicate_customers")
    phone = next(f for f in items if "phone number" in f["summary"])
    tax = next(f for f in items if "tax number" in f["summary"])
    assert phone["summary"] == ("2 customers share the same phone number (254722111222): Mama Mboga, "
                                "Mama Mboga Two.")
    assert phone["severity"] == "low" and tax["severity"] == "medium" and Dec(phone["value"]) == 2
    assert "Mwangi Ltd, Mwangi Limited" in tax["summary"]
    assert sorted(r["id"] for r in detail(client, shop, phone)["records"]) == sorted([old["id"], again["id"]])
    assert not any("Only One" in f["summary"] or "Old Twin" in f["summary"] for f in items)
    # tuned look-back: in the last 3 days only the tax number pair is new (13 Oct); nothing is new today
    assert [c.severity for c in direct(shop, DuplicateCustomers(), days=3)] == ["medium"]
    assert direct(shop, DuplicateCustomers(), days=0) == []
    assert len(direct(shop, DuplicateCustomers(), days=5)) == 2                       # 10 Oct is within 5 days
    # it is an event: seen again it is the same finding, and nothing new is made
    later = run_check(shop, "crm.duplicate_customers")
    assert (later.created, later.updated) == (0, 2)


# --------------------------------------------------------------------------- Command Center figures
def test_crm_figures_for_the_command_center(client, shop) -> None:  # type: ignore[no-untyped-def]
    sql(shop, "update crm.customer set created_at = '2026-10-01'")                    # earlier tests made customers "now"
    # two customers arrive on the day (08:00 UTC), one just before midnight the day before
    arrivals = [new_customer(client, shop, name=n) for n in ("Today One", "Today Two", "Yesterday Late")]
    for c, moment in zip(arrivals, ("2026-10-14 08:00+00", "2026-10-14 13:00+00", "2026-10-13 23:30+00"), strict=True):
        sql(shop, "update crm.customer set created_at = cast(:d as timestamptz) where id = :i", d=moment, i=c["id"])
    follow_up(client, shop, arrivals[0]["id"], "2026-10-13", related="customer")      # open, due yesterday: overdue
    follow_up(client, shop, arrivals[1]["id"], "2026-10-14", related="customer")      # due today: not overdue yet
    with system(shop) as s:
        assert pulse.refresh_company(s, shop["company_id"], TODAY) >= 4
    rows = sql(shop, "select metric, branch_id, value from command.pulse_figure where day = :d and metric like 'crm.%'",
               d=TODAY)
    got = {r.metric: Dec(r.value) for r in rows}
    assert all(r.branch_id is None for r in rows)                                    # customers belong to the company
    # arrivals today: Today One and Today Two
    assert got["crm.new_customers"] == 2
    # overdue follow-ups, open and due before today: Lead One's 12 Oct call (rep), the finance manager's 6 Oct call,
    # and the 13 Oct call on a customer = 3. The lost lead's call, the done calls and today's call do not count.
    assert got["crm.followups_overdue"] == 3
    assert got["crm.leads_open"] == 3                                                # Lead One, Two, Three (one lost)
    assert got["crm.credit_increases_waiting"] == 1                                  # Fresh Request Ltd (the other was approved)
    for metric in ("crm.new_customers", "crm.followups_overdue", "crm.leads_open", "crm.credit_increases_waiting"):
        assert metric in got

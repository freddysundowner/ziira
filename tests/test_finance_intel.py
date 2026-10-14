"""Finance's Intelligence checks and Command Center figures, run through the real engine on hand-made books.

Books are written straight into the tables where a test needs a date or a time that the API would not allow (an entry
posted last week, a journal written at night); the rest goes through the API.
"""

import calendar
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as Dec  # noqa: N817
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.finance_helpers import FIN, make_books_shop
from tests.stock_helpers import system
from ziira.modules.finance.pulse import FinancePulse
from ziira.modules.intel.services import baselines, engine

INTEL = "/api/v1/intel"
NOW = datetime.now(UTC)
TODAY = NOW.date()                       # companies are in UTC unless set otherwise


# --------------------------------------------------------------------------- setup helpers
def make_shop(client, registry, name: str):  # type: ignore[no-untyped-def]
    s = make_books_shop(client, registry, name)
    # these tests are written in UTC hours: say so (test tenants are otherwise created in LOCALE["timezone"])
    client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"], json={"timezone": "UTC"})
    registry.enable(s["tenant_id"], "intel")
    registry.enable(s["tenant_id"], "command")
    s["company"] = str(s["company_id"])
    books = client.post(f"{FIN}/companies/{s['company']}/books", headers=s["owner"]).json()
    s["acc"] = {a["code"]: a["id"] for a in books}
    with system(s) as db:
        s["gen"] = db.execute(text("select id from finance.journal where code = 'GEN'")).scalar_one()
        s["owner_id"] = db.execute(text("select id from kernel.app_user where email = :e"),
                                   {"e": f"owner@{s['code']}.test"}).scalar_one()
        s["manager_id"] = db.execute(text("select id from kernel.app_user where email = :e"),
                                     {"e": f"manager@{s['code']}.test"}).scalar_one()
    s["seq"] = 0
    return s


def period_for(db, shop, day: date, status: str = "open", closed_at: datetime | None = None) -> UUID:  # type: ignore[no-untyped-def]
    start = day.replace(day=1)
    found = db.execute(text("select id from finance.period where company_id = :c and start_date = :s"),
                       {"c": shop["company"], "s": start}).scalar()
    if found:
        return found
    return db.execute(text(
        "insert into finance.period (tenant_id, company_id, start_date, end_date, status, closed_at) values "
        "(:t, :c, :s, :e, :st, :ca) returning id"),
        {"t": str(shop["tenant_id"]), "c": shop["company"], "s": start,
         "e": day.replace(day=calendar.monthrange(day.year, day.month)[1]), "st": status, "ca": closed_at}).scalar_one()


def add_entry(shop, day: date, lines: list[tuple[str, str, str, UUID | None]], *, posted_at: datetime | None = None,  # type: ignore[no-untyped-def]
              manual: bool = False, status: str = "open", closed_at: datetime | None = None) -> tuple[UUID, str, list[UUID]]:
    """A balanced entry: lines are (account code, debit, credit, branch). Returns its id, number and line ids."""
    shop["seq"] += 1
    number = f"T-{shop['seq']:04d}"
    entry_id = uuid4()
    line_ids = []
    with system(shop) as db:
        period = period_for(db, shop, day, status, closed_at)
        db.execute(text(
            "insert into finance.journal_entry (id, tenant_id, company_id, journal_id, period_id, number, entry_date, "
            "is_manual, posted_at) values (:i, :t, :c, :j, :p, :n, :d, :m, :pa)"),
            {"i": str(entry_id), "t": str(shop["tenant_id"]), "c": shop["company"], "j": str(shop["gen"]),
             "p": str(period), "n": number, "d": day, "m": manual, "pa": posted_at or NOW})
        for code, debit, credit, branch in lines:
            line_id = uuid4()
            line_ids.append(line_id)
            db.execute(text(
                "insert into finance.journal_line (id, tenant_id, entry_id, company_id, branch_id, account_id, debit, "
                "credit) values (:i, :t, :e, :c, :b, :a, :d, :cr, )".replace(", )", ")")),
                {"i": str(line_id), "t": str(shop["tenant_id"]), "e": str(entry_id), "c": shop["company"],
                 "b": str(branch) if branch else None, "a": shop["acc"][code], "d": debit, "cr": credit})
    return entry_id, number, line_ids


def pair(debit_code: str, credit_code: str, amount: str, branch: UUID | None = None):  # type: ignore[no-untyped-def]
    return [(debit_code, amount, "0", branch), (credit_code, "0", amount, branch)]


def add_manual(shop, total: str, status: str = "posted", *, created_at: datetime | None = None,  # type: ignore[no-untyped-def]
               created_by: UUID | None = None, approved_by: UUID | None = None, entry_id: UUID | None = None,
               description: str = "Adjustment") -> tuple[UUID, str]:
    shop["seq"] += 1
    number = f"MJ-T{shop['seq']:04d}"
    mid = uuid4()
    with system(shop) as db:
        db.execute(text(
            "insert into finance.manual_journal (id, tenant_id, created_at, created_by, company_id, journal_id, number, "
            "entry_date, description, status, total, entry_id, approved_by) values (:i, :t, :ca, :cb, :c, :j, :n, "
            ":d, :ds, :st, :tot, :e, :ab)"),
            {"i": str(mid), "t": str(shop["tenant_id"]), "ca": created_at or NOW, "cb": str(created_by or shop["owner_id"]),
             "c": shop["company"], "j": str(shop["gen"]), "n": number, "d": TODAY, "ds": description, "st": status,
             "tot": total, "e": str(entry_id) if entry_id else None, "ab": str(approved_by) if approved_by else None})
    return mid, number


def add_expense(shop, day: date, code: str, amount: str, *, branch: UUID | None = None, status: str = "posted",  # type: ignore[no-untyped-def]
                created_by: UUID | None = None, approved_by: UUID | None = None, payee: str = "Vendor") -> tuple[UUID, str]:
    shop["seq"] += 1
    number = f"EXP-T{shop['seq']:04d}"
    xid = uuid4()
    with system(shop) as db:
        db.execute(text(
            "insert into finance.expense (id, tenant_id, created_by, company_id, branch_id, number, expense_date, payee, "
            "account_id, amount, status, approved_by, description, paid_from) values (:i, :t, :cb, :c, :b, :n, :d, "
            ":p, :a, :am, :st, :ab, 'Test expense', 'cash')"),
            {"i": str(xid), "t": str(shop["tenant_id"]), "cb": str(created_by or shop["owner_id"]), "c": shop["company"],
             "b": str(branch) if branch else None, "n": number, "d": day, "p": payee, "a": shop["acc"][code],
             "am": amount, "st": status, "ab": str(approved_by) if approved_by else None})
    return xid, number


def run(shop, code: str, today: date = TODAY):  # type: ignore[no-untyped-def]
    with system(shop) as db:
        return engine.run_company(db, shop["company_id"], today=today, only={code})


def found(shop, code: str, status: str | None = None) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as db:
        rows = db.execute(text(
            "select severity, status, summary, amount, branch_id, evidence from intel.finding where check_code = :c "
            "and (cast(:s as text) is null or status = :s) order by summary"), {"c": code, "s": status}).all()
    return list(rows)


def tune(client, shop, code: str, **params: Any) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"{INTEL}/checks/{code}", headers=shop["owner"], json={"params": params})
    assert r.status_code == 200, r.text


def labels(row: Any) -> set[str]:
    evidence = row.evidence if isinstance(row.evidence, dict) else json.loads(row.evidence)
    return {x["label"] for x in evidence["records"]}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


# --------------------------------------------------------------------------- back-dated entries and closed periods
@pytest.fixture(scope="module")
def ctl(client, registry):  # type: ignore[no-untyped-def]
    return make_shop(client, registry, "Fin Controls Co")


def test_entries_posted_long_after_their_date(client, ctl) -> None:  # type: ignore[no-untyped-def]
    hq = ctl["branch_id"]
    e30, n30, _ = add_entry(ctl, TODAY - timedelta(days=30), pair("6000", "1010", "500.00", hq), manual=True)
    add_entry(ctl, TODAY - timedelta(days=10), pair("6000", "1010", "800.00", hq), manual=True)          # not late enough
    closed_day = TODAY - timedelta(days=120)
    e_closed, n_closed, _ = add_entry(ctl, closed_day, pair("6000", "1010", "900.00"), manual=True,
                                      status="soft_closed", closed_at=NOW - timedelta(days=2))
    add_entry(ctl, closed_day, pair("6000", "1010", "50.00"), posted_at=NOW - timedelta(days=5))         # not manual
    code = "finance.backdated_entries"
    run(ctl, code)
    rows = {r.summary: r for r in found(ctl, code)}
    assert len(rows) == 2
    old = next(r for k, r in rows.items() if n30 in k)
    assert old.severity == "medium" and old.amount == Dec("500.00") and str(old.branch_id) == str(hq)
    assert "dated " + str(TODAY - timedelta(days=30)) in old.summary and "30 days later" in old.summary
    assert labels(old) == {f"Entry {n30}"}
    closed = next(r for k, r in rows.items() if n_closed in k)
    assert closed.severity == "high" and closed.amount == Dec("900.00") and closed.branch_id is None
    assert "already soft closed" in closed.summary

    tune(client, ctl, code, late_days=40)                      # 30 days is now normal
    run(ctl, code)
    assert {r.status for r in found(ctl, code)} == {"new"}     # an event stays until a person deals with it
    tune(client, ctl, code, late_days=14, manual_only=0)       # entries made by the system count too
    run(ctl, code)
    assert len(found(ctl, code)) == 3
    tune(client, ctl, code, manual_only=1)


def test_entries_posted_into_a_month_after_it_was_closed(client, ctl) -> None:  # type: ignore[no-untyped-def]
    code = "finance.posted_after_close"
    run(ctl, code)
    rows = found(ctl, code)
    assert len(rows) == 1                                      # the system entry posted 5 days ago was before the close
    assert rows[0].severity == "high" and rows[0].amount == Dec("900.00")
    assert "had already been closed" in rows[0].summary


def test_a_reopened_period_is_flagged(client, ctl) -> None:  # type: ignore[no-untyped-def]
    code = "finance.period_reopened"
    ids = {}
    for key, offset in (("quiet", 200), ("busy", 230)):
        day = TODAY - timedelta(days=offset)
        p = client.post(f"{FIN}/periods", headers=ctl["owner"], json={"company_id": ctl["company"], "day": str(day)})
        assert p.status_code == 201, p.text
        ids[key] = p.json()["id"]
        for status in ("soft_closed", "open"):
            r = client.post(f"{FIN}/periods/{ids[key]}/status", headers=ctl["owner"], json={"status": status})
            assert r.status_code == 200, r.text
        ids[key + "_day"] = day
    add_entry(ctl, ids["busy_day"], pair("6000", "1010", "10.00"), posted_at=NOW + timedelta(minutes=5))   # after reopening
    still_closed = client.post(f"{FIN}/periods", headers=ctl["owner"], json={
        "company_id": ctl["company"], "day": str(TODAY - timedelta(days=260))}).json()["id"]
    client.post(f"{FIN}/periods/{still_closed}/status", headers=ctl["owner"], json={"status": "soft_closed"})   # closing is not reopening
    run(ctl, code)
    rows = found(ctl, code)
    assert len(rows) == 2
    quiet = next(r for r in rows if str(ids["quiet_day"].replace(day=1)) in r.summary)
    busy = next(r for r in rows if str(ids["busy_day"].replace(day=1)) in r.summary)
    assert quiet.severity == "medium" and "Since then" not in quiet.summary
    assert busy.severity == "high" and "Since then 1 entry has been posted into it" in busy.summary
    assert f"on {TODAY}" in busy.summary


# --------------------------------------------------------------------------- manual journals
@pytest.fixture(scope="module")
def journals(ctl):  # type: ignore[no-untyped-def]
    noon = at(TODAY, 12)
    j = {
        "j1": add_manual(ctl, "150000.00", created_at=noon),
        "j2": add_manual(ctl, "600000.00", "pending_approval", created_at=at(TODAY, 2)),
        "j3": add_manual(ctl, "50000.00", created_at=noon),
        "j4": add_manual(ctl, "900000.00", created_at=at(TODAY - timedelta(days=60), 12)),
        "j5": add_manual(ctl, "123456.78", created_at=noon),
        "j6": add_manual(ctl, "5000.00", created_at=noon),
        "draft": add_manual(ctl, "700000.00", "draft", created_at=noon),
    }
    entry, _, _ = add_entry(ctl, TODAY, pair("6000", "1010", "7000.50"), manual=True, posted_at=at(TODAY, 23, 30))
    j["j7"] = add_manual(ctl, "7000.50", created_at=noon, entry_id=entry)
    return j


def summaries(shop, code: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {r.summary: r for r in found(shop, code)}


def pick(rows: dict[str, Any], number: str) -> Any:
    return next(r for k, r in rows.items() if number in k)


def test_manual_journals_above_the_limit(client, ctl, journals) -> None:  # type: ignore[no-untyped-def]
    code = "finance.large_manual_journal"
    run(ctl, code)
    rows = summaries(ctl, code)
    assert len(rows) == 3                                       # 150000, 600000 and 123456.78: not the old one or a draft
    one, two, five = (pick(rows, journals[k][1]) for k in ("j1", "j2", "j5"))
    assert one.severity == "medium" and one.amount == Dec("150000.00") and "has been posted" in one.summary
    assert two.severity == "high" and "is waiting for approval" in two.summary         # 600000 is six times the limit
    assert five.severity == "medium" and "123,456.78" in five.summary and "limit for hand-made entries" in five.summary
    tune(client, ctl, code, limit="40000.00")
    run(ctl, code)
    assert len(found(ctl, code)) == 4                           # and 50000 now counts
    tune(client, ctl, code, limit="100000.00")


def test_manual_journals_for_round_sums(client, ctl, journals) -> None:  # type: ignore[no-untyped-def]
    code = "finance.round_manual_journal"
    run(ctl, code)
    rows = summaries(ctl, code)
    assert {k.split()[2] for k in rows} == {journals[k][1] for k in ("j1", "j2", "j3")}
    assert {r.severity for r in rows.values()} == {"low"}
    tune(client, ctl, code, min_amount="1000.00")               # 5000 is round too
    run(ctl, code)
    assert len(found(ctl, code)) == 4
    tune(client, ctl, code, min_amount="10000.00")


def test_manual_journals_at_unusual_hours(client, ctl, journals) -> None:  # type: ignore[no-untyped-def]
    code = "finance.odd_hours_manual_journal"
    run(ctl, code)
    rows = summaries(ctl, code)
    assert len(rows) == 2
    night = pick(rows, journals["j2"][1])                       # written at 02:00
    assert night.severity == "low" and "was written by" in night.summary and "at 02:00" in night.summary
    late = pick(rows, journals["j7"][1])                        # written at noon, posted at 23:30
    assert "was posted by" in late.summary and "at 23:30" in late.summary and late.amount == Dec("7000.50")
    tune(client, ctl, code, start_hour=1, end_hour=3)
    run(ctl, code)
    assert len(found(ctl, code)) == 2                           # the 23:30 one is still there: events stay
    assert sum(1 for r in found(ctl, code) if "23:30" in r.summary) == 1
    tune(client, ctl, code, start_hour=22, end_hour=5)


def test_the_same_person_preparing_and_approving(client, ctl) -> None:  # type: ignore[no-untyped-def]
    code = "finance.same_person_approval"
    me, other = ctl["owner_id"], ctl["manager_id"]
    _, self_made = add_manual(ctl, "2500.00", created_by=me, approved_by=me)
    add_manual(ctl, "2600.00", created_by=me, approved_by=other)
    add_manual(ctl, "2700.00", created_by=me)
    x_self, x_number = add_expense(ctl, TODAY, "6200", "250.00", branch=ctl["branch_id"], created_by=me, approved_by=me,
                                   payee="KPLC")
    add_expense(ctl, TODAY, "6200", "260.00", created_by=me, approved_by=other)
    add_expense(ctl, TODAY, "6200", "270.00", created_by=me, approved_by=me, status="rejected")
    run(ctl, code)
    rows = summaries(ctl, code)
    assert len(rows) == 2
    journal = pick(rows, self_made)
    assert journal.severity == "medium" and journal.amount == Dec("2500.00") and journal.branch_id is None
    assert "Fin Controls Co Owner both prepared and approved" in journal.summary
    expense = pick(rows, x_number)
    assert str(expense.branch_id) == str(ctl["branch_id"]) and "paid to KPLC" in expense.summary
    assert labels(expense) == {f"Expense {x_number}"}


# --------------------------------------------------------------------------- unusual expenses
@pytest.fixture(scope="module")
def exp(client, registry):  # type: ignore[no-untyped-def]
    return make_shop(client, registry, "Fin Expense Co")


def test_an_expense_far_above_the_normal_for_the_branch(client, exp) -> None:  # type: ignore[no-untyped-def]
    hq, juja = exp["branch_id"], exp["juja"]
    for i in range(20):                                         # 20 days of 900 and 1100, ten days ago and before
        add_expense(exp, TODAY - timedelta(days=10 + i), "6200", "900.00" if i % 2 else "1100.00", branch=hq)
    add_expense(exp, TODAY - timedelta(days=2), "6200", "1100.00", branch=hq)               # a normal day
    _, a = add_expense(exp, TODAY - timedelta(days=1), "6200", "3000.00", branch=hq)       # the spike, in two parts
    _, b = add_expense(exp, TODAY - timedelta(days=1), "6200", "2000.00", branch=hq)
    add_expense(exp, TODAY - timedelta(days=3), "6200", "9000.00", branch=hq, status="rejected")   # never counted
    add_expense(exp, TODAY - timedelta(days=1), "6200", "5000.00", branch=juja)             # no history at that branch
    with system(exp) as db:
        baselines.refresh_company(db, exp["company_id"], TODAY)
        stored = db.execute(text("select sample_size, mean from intel.baseline where metric = "
                                 "'finance.expense_per_account' order by sample_size desc")).first()
    assert stored is not None and stored.sample_size == 22          # 20 + the normal day + the spike day
    assert abs(stored.mean - Dec("26100") / 22) < Dec("0.001")

    code = "finance.unusual_expense"
    run(exp, code)
    rows = found(exp, code)
    assert len(rows) == 1
    f = rows[0]
    assert f.severity == "medium" and str(f.branch_id) == str(hq)
    assert f.amount.quantize(Dec("0.01")) == Dec("3813.64")        # 5000 - 1186.36
    assert "6200 Utilities" in f.summary and "5,000.00" in f.summary and "1,186.36" in f.summary
    assert labels(f) == {f"Expense {a}", f"Expense {b}"}

    tune(exp_client := client, exp, code, min_ratio="5.0")           # 5000 is 4.2 times the usual: not enough
    with system(exp) as db:
        db.execute(text("update intel.finding set status = 'dismissed' where check_code = :c"), {"c": code})
    run(exp, code)
    assert [r.status for r in found(exp, code)] == ["dismissed"] and exp_client is client


# --------------------------------------------------------------------------- bank reconciliation
@pytest.fixture(scope="module")
def rec(client, registry):  # type: ignore[no-untyped-def]
    return make_shop(client, registry, "Fin Recon Co")


def add_recon(shop, code: str, status: str, created_at: datetime) -> UUID:  # type: ignore[no-untyped-def]
    with system(shop) as db:
        return db.execute(text(
            "insert into finance.bank_reconciliation (tenant_id, created_at, company_id, account_id, statement_date, "
            "statement_balance, book_balance, difference, status) values (:t, :ca, :c, :a, :d, 0, 0, 0, :s) "
            "returning id"),
            {"t": str(rec_tenant(shop)), "ca": created_at, "c": shop["company"], "a": shop["acc"][code],
             "d": TODAY - timedelta(days=1), "s": status}).scalar_one()


def rec_tenant(shop) -> UUID:  # type: ignore[no-untyped-def]
    return shop["tenant_id"]


def test_reconciliations_left_open(client, rec) -> None:  # type: ignore[no-untyped-def]
    code = "finance.stale_reconciliation"
    r_bank = add_recon(rec, "1020", "in_progress", NOW - timedelta(days=40))
    add_recon(rec, "1030", "in_progress", NOW - timedelta(days=70))
    add_recon(rec, "1040", "in_progress", NOW - timedelta(days=10))
    run(rec, code)
    rows = {r.summary: r for r in found(rec, code)}
    assert len(rows) == 2
    bank = next(r for k, r in rows.items() if "1020 Bank" in k)
    assert bank.severity == "low" and "after 40 days" in bank.summary
    mobile = next(r for k, r in rows.items() if "1030" in k)
    assert mobile.severity == "medium" and "after 70 days" in mobile.summary
    tune(client, rec, code, days_open=5)
    result = run(rec, code)
    assert result.created == 1 and len(found(rec, code)) == 3
    tune(client, rec, code, days_open=30)
    with system(rec) as db:                                        # the bank one is finished
        db.execute(text("update finance.bank_reconciliation set status = 'completed' where id = :i"), {"i": str(r_bank)})
    run(rec, code)
    gone = [r for r in found(rec, code, "resolved")]
    assert len(gone) == 2 and all("1020" in r.summary or "1040" in r.summary for r in gone)


def test_old_bank_lines_never_reconciled(client, rec) -> None:  # type: ignore[no-untyped-def]
    code = "finance.unreconciled_bank_lines"
    done_bank = add_recon(rec, "1020", "completed", NOW - timedelta(days=100))
    done_card = add_recon(rec, "1040", "completed", NOW - timedelta(days=100))
    d60, d90 = TODAY - timedelta(days=60), TODAY - timedelta(days=90)
    _, _, l60 = add_entry(rec, d60, pair("1020", "3000", "1000.00"), manual=True)
    _, _, l90 = add_entry(rec, d90, pair("1020", "3000", "2500.00"), manual=True)
    _, _, l50 = add_entry(rec, TODAY - timedelta(days=50), pair("3000", "1020", "300.00"), manual=True)
    add_entry(rec, TODAY - timedelta(days=10), pair("1020", "3000", "700.00"), manual=True)      # too recent
    add_entry(rec, TODAY - timedelta(days=100), pair("1040", "3000", "400.00"), manual=True)
    add_entry(rec, TODAY - timedelta(days=100), pair("1030", "3000", "999.00"), manual=True)     # never reconciled account
    with system(rec) as db:                                      # the 2500 line cleared a statement
        db.execute(text("insert into finance.reconciliation_line (tenant_id, reconciliation_id, journal_line_id) "
                        "values (:t, :r, :l)"), {"t": str(rec["tenant_id"]), "r": str(done_bank), "l": str(l90[0])})
    run(rec, code)
    rows = {r.summary: r for r in found(rec, code)}
    assert len(rows) == 2
    bank = next(r for k, r in rows.items() if "1020 Bank" in k)
    assert bank.severity == "low" and bank.amount == Dec("700.00")             # 1000 in, 300 out
    assert "2 entries" in bank.summary and "net " in bank.summary and "700.00" in bank.summary
    assert f"from {d60}" in bank.summary
    card = next(r for k, r in rows.items() if "1040" in k)
    assert card.severity == "medium" and card.amount == Dec("400.00")          # 100 days old: twice the limit

    tune(client, rec, code, age_days=120)
    run(rec, code)
    assert len(found(rec, code, "resolved")) == 2 and not found(rec, code, "new")
    tune(client, rec, code, age_days=45)
    assert run(rec, code).reopened == 2
    with system(rec) as db:                                      # the rest is now cleared too
        for line in (l60[0], l50[1]):
            db.execute(text("insert into finance.reconciliation_line (tenant_id, reconciliation_id, journal_line_id) "
                            "values (:t, :r, :l)"), {"t": str(rec["tenant_id"]), "r": str(done_bank), "l": str(line)})
        db.execute(text("insert into finance.reconciliation_line (tenant_id, reconciliation_id, journal_line_id) "
                        "select :t, :r, l.id from finance.journal_line l where l.account_id = :a"),
                   {"t": str(rec["tenant_id"]), "r": str(done_card), "a": rec["acc"]["1040"]})
    run(rec, code)
    assert not found(rec, code, "new")


# --------------------------------------------------------------------------- gross margin
@pytest.fixture(scope="module")
def mar(client, registry):  # type: ignore[no-untyped-def]
    s = make_shop(client, registry, "Fin Margin Co")
    for month, income, cost in ((7, "10000.00", "6000.00"), (8, "20000.00", "12000.00"), (9, "10000.00", "6000.00"),
                                (10, "5000.00", "3800.00")):
        day = date(2026, month, 12 if month == 10 else 10)
        add_entry(s, day, pair("1010", "4000", income))
        add_entry(s, day, pair("5000", "1020", cost))
        add_entry(s, day, pair("6000", "1010", "999.00"))               # rent is not a cost of sales
    return s


def test_gross_margin_far_below_the_previous_months(client, mar) -> None:  # type: ignore[no-untyped-def]
    code = "finance.low_gross_margin"
    run(mar, code, date(2026, 10, 14))
    rows = found(mar, code)
    assert len(rows) == 1
    f = rows[0]
    # July to September: sales 40000, cost 24000 -> 40.0%. October so far: sales 5000, cost 3800 -> 24.0%.
    assert f.severity == "medium" and f.amount == Dec("800.00")                  # 5000 * 16 points
    assert "24.0%" in f.summary and "40.0%" in f.summary and "previous 3 months" in f.summary
    assert "5,000.00" in f.summary

    tune(client, mar, code, drop_points="5.0")                                   # 16 is more than twice 5
    run(mar, code, date(2026, 10, 14))
    assert found(mar, code)[0].severity == "high"
    tune(client, mar, code, drop_points="20.0")
    run(mar, code, date(2026, 10, 14))
    assert not found(mar, code, "new") and len(found(mar, code, "resolved")) == 1
    tune(client, mar, code, drop_points="10.0")
    assert run(mar, code, date(2026, 10, 14)).reopened == 1


def test_gross_margin_stays_quiet_when_there_is_nothing_to_compare(client, mar) -> None:  # type: ignore[no-untyped-def]
    code = "finance.low_gross_margin"
    with system(mar) as db:
        db.execute(text("update intel.finding set status = 'dismissed' where check_code = :c"), {"c": code})
    before = len(found(mar, code))
    assert run(mar, code, date(2026, 10, 3)).created == 0          # too early in the month
    assert run(mar, code, date(2026, 8, 14)).created == 0          # only July before it: too little history
    assert run(mar, code, date(2026, 9, 14)).created == 0          # September is 40.0% like the months before
    assert len(found(mar, code)) == before
    add_entry(mar, date(2026, 10, 13), pair("1010", "4000", "5000.00"))             # October improves: 10000 / 3800
    with system(mar) as db:
        db.execute(text("update intel.finding set status = 'new' where check_code = :c"), {"c": code})
    run(mar, code, date(2026, 10, 14))
    assert [r.status for r in found(mar, code)] == ["resolved"]


# --------------------------------------------------------------------------- pulse figures
@pytest.fixture(scope="module")
def pls(client, registry):  # type: ignore[no-untyped-def]
    s = make_shop(client, registry, "Fin Pulse Co")
    hq, juja = s["branch_id"], s["juja"]
    add_entry(s, date(2026, 9, 30), pair("1010", "4000", "3000.00", hq))
    add_entry(s, date(2026, 10, 5), pair("1010", "4000", "8000.00", hq))
    add_entry(s, date(2026, 10, 6), pair("1010", "4000", "4000.00", juja))
    add_entry(s, date(2026, 10, 6), pair("5000", "1020", "3000.00", hq))
    add_entry(s, date(2026, 10, 6), pair("5000", "1020", "2400.00", juja))
    add_entry(s, date(2026, 10, 7), pair("6000", "1010", "1000.00", hq))
    add_entry(s, date(2026, 10, 20), pair("1010", "4000", "999.00", hq))               # after the day
    day = date(2026, 10, 14)
    add_expense(s, day, "6200", "300.00", branch=hq)
    add_expense(s, day, "6300", "200.00", branch=hq, status="approved")
    add_expense(s, day, "6200", "150.00", branch=juja)
    add_expense(s, day, "6200", "999.00", branch=hq, status="rejected")
    add_expense(s, day - timedelta(days=1), "6200", "400.00", branch=hq)
    add_manual(s, "100.00", "pending_approval")
    add_manual(s, "200.00", "pending_approval")
    add_manual(s, "300.00", "posted")
    return s


def figures(shop, day: date) -> dict[tuple[str, str | None], Dec]:  # type: ignore[no-untyped-def]
    # The source is called directly: the Command Center's own store (pulse.refresh_company) fails on an ON CONFLICT
    # that does not match its index when any source supplies a branch figure (reported to the owner of that module).
    with system(shop) as db:
        made = FinancePulse().figures(db, shop["company_id"], day)
    return {(f.metric, str(f.branch_id) if f.branch_id else None): f.value for f in made}


def test_finance_pulse_figures(pls) -> None:  # type: ignore[no-untyped-def]
    f = figures(pls, date(2026, 10, 14))
    hq, juja = str(pls["branch_id"]), str(pls["juja"])
    # Cash 1010: 3000 + 8000 + 4000 - 1000 = 14000; bank 1020: -3000 - 2400 = -5400; the entry of the 20th is not yet.
    assert f[("finance.cash_and_bank", None)] == Dec("8600")
    # October: sales 12000, cost of sales 5400, all expenses 5400 + 1000 rent.
    assert f[("finance.net_profit_mtd", None)] == Dec("5600")
    assert f[("finance.gross_margin_mtd", None)] == Dec("55.0")                 # 6600 / 12000
    assert f[("finance.net_profit_mtd", hq)] == Dec("4000")                     # 8000 - 3000 - 1000
    assert f[("finance.net_profit_mtd", juja)] == Dec("1600")                   # 4000 - 2400
    assert f[("finance.gross_margin_mtd", hq)] == Dec("62.5")                   # 5000 / 8000
    assert f[("finance.gross_margin_mtd", juja)] == Dec("40.0")                 # 1600 / 4000
    assert f[("finance.expenses_day", None)] == Dec("650")                      # 300 + 200 + 150, not the rejected one
    assert f[("finance.expenses_day", hq)] == Dec("500") and f[("finance.expenses_day", juja)] == Dec("150")
    assert f[("finance.manual_journals_waiting", None)] == Dec("2")
    assert ("finance.cash_and_bank", hq) not in f                               # the bank has no branch


def test_pulse_on_a_quiet_day_has_no_margin_and_zero_expenses(pls) -> None:  # type: ignore[no-untyped-def]
    f = figures(pls, date(2026, 8, 15))                                         # nothing was sold yet that month
    assert f[("finance.cash_and_bank", None)] == Dec("0")
    assert f[("finance.net_profit_mtd", None)] == Dec("0")
    assert ("finance.gross_margin_mtd", None) not in f
    assert f[("finance.expenses_day", None)] == Dec("0")


def test_months_back_crosses_years() -> None:
    from ziira.modules.finance.intel_checks.books import _months_back

    assert _months_back(date(2026, 10, 1), 3) == date(2026, 7, 1)
    assert _months_back(date(2026, 2, 1), 3) == date(2025, 11, 1)
    assert _months_back(date(2026, 3, 1), 3) == date(2025, 12, 1)

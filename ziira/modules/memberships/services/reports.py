"""Reports an owner acts on: who is a member, what they bring in each month, who is leaving, when the gym is busy,
who owes.

Everything is read from this unit's own records (memberships, check-ins, invoice runs); figures are never invented.
Money
is per month for recurring plans (a quarter's fee counts a third, a year's a twelfth). Filtered to the branches the
person
may see."""

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.memberships.permissions import MANAGE, PLANS, REPORTS
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common
from ziira.sdk import Forbidden, Session, ValidationFailed, company_zone, current_context

MONTHLY = ("case m.billing_interval when 'month' then 1 when 'quarter' then 3 else 12 end")
ZERO = Decimal(0)


def _allowed(company_id: UUID) -> None:
    """The reports right (or manage/plans) at some level in the company: a branch manager sees their branch's figures
    (every query is filtered to the branches the person may see)."""
    ctx = current_context()
    for permission in (REPORTS, MANAGE, PLANS):
        companies = ctx.companies_with(permission)
        if companies is None or company_id in companies:
            return
    raise Forbidden("You need the reports right to see these figures")


def _months(start: date, end: date) -> list[date]:
    out: list[date] = []
    day = start.replace(day=1)
    while day <= end and len(out) < 36:
        out.append(day)
        day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _scope(alias: str = "m") -> tuple[str, repo.Row]:
    return repo.scope_sql(common.view_scopes(), alias)


def overview(session: Session, *, company_id: UUID, start: date | None = None, end: date | None = None,
             branch_id: UUID | None = None) -> dict[str, Any]:
    """All the owner's figures for a company between two dates (default: the last 6 months to today)."""
    _allowed(company_id)
    common.check_visible(company_id, branch_id, "Company")
    today = common.today(session, company_id)
    end = end or today
    start = start or (end.replace(day=1) - timedelta(days=150)).replace(day=1)
    if start > end:
        raise ValidationFailed("The start date is after the end date")
    clause, params = _scope("m")
    base = {"c": company_id, "b": branch_id, **params}
    where = f"{clause} and m.company_id = :c and (cast(:b as uuid) is null or m.branch_id = :b)"

    now = repo.one(
        session,
        f"select count(*) filter (where m.status = 'active') as active, "
        f"count(*) filter (where m.status = 'paused') as paused, count(*) filter (where m.status = 'frozen') as frozen, "  # noqa: E501
        f"count(*) filter (where m.status = 'active' and m.is_trial) as trials, "
        f"coalesce(sum(m.price / ({MONTHLY})) filter (where m.status = 'active'), 0) as mrr, "
        f"coalesce(sum(m.price / ({MONTHLY})) filter (where m.status = 'active' and (m.cancel_at is not null "
        f"  or m.past_due_since is not null)), 0) as at_risk_cancel_late, "
        f"coalesce(sum(m.price / ({MONTHLY})) filter (where m.status in ('paused', 'frozen')), 0) as at_risk_held, "
        f"count(*) filter (where m.status = 'active' and m.cancel_at is not null) as cancelling "
        f"from memberships.member m where {where} and m.status in ('active', 'paused', 'frozen')", **base) or {}
    by_plan = repo.many(
        session,
        f"select m.plan_name, count(*) as members, coalesce(sum(m.price / ({MONTHLY})), 0) as mrr "
        f"from memberships.member m where {where} and m.status = 'active' group by m.plan_name order by mrr desc",
        **base)

    # new and ended per month
    months = _months(start, end)
    started = {r["m"]: r["n"] for r in repo.many(
        session, f"select date_trunc('month', m.start_date)::date as m, count(*) as n from memberships.member m "
                 f"where {where} and m.start_date between :s and :e and not m.is_trial group by 1", s=start, e=end,
        **base)}
    ended = {r["m"]: r["n"] for r in repo.many(
        session, f"select date_trunc('month', m.cancelled_on)::date as m, count(*) as n from memberships.member m "
                 f"where {where} and m.cancelled_on between :s and :e and not m.is_trial group by 1", s=start, e=end,
        **base)}
    flow = [{"month": mo, "new": int(started.get(mo, 0)), "ended": int(ended.get(mo, 0)),
             "net": int(started.get(mo, 0)) - int(ended.get(mo, 0))} for mo in months]

    # retention: of the people who joined in a month, how many are still members k months later
    cohorts: list[dict[str, Any]] = []
    cohort_rows = repo.many(
        session, f"select m.start_date, m.cancelled_on from memberships.member m where {where} "
                 f"and m.start_date >= :from and not m.is_trial",
        **base, **{"from": (today.replace(day=1) - timedelta(days=366)).replace(day=1)})
    for mo in _months((today.replace(day=1) - timedelta(days=340)).replace(day=1), today):
        nxt = (mo.replace(day=28) + timedelta(days=4)).replace(day=1)
        people = [r for r in cohort_rows if mo <= r["start_date"] < nxt]
        if not people:
            continue
        points: list[int | None] = []
        for k in range(0, 12):
            at = mo
            for _ in range(k):
                at = (at.replace(day=28) + timedelta(days=4)).replace(day=1)
            cutoff = at.replace(day=calendar.monthrange(at.year, at.month)[1])
            if cutoff > today:
                points.append(None)
                continue
            alive = sum(1 for r in people if r["cancelled_on"] is None or r["cancelled_on"] > cutoff)
            points.append(round(alive * 100 / len(people)))
        cohorts.append({"month": mo, "joined": len(people), "still_member_percent": points})

    # attendance by weekday and hour (company's clock), from entries that let someone in
    zone = str(company_zone(session, company_id))
    clause_k, params_k = repo.scope_sql(common.view_scopes(), "k")
    heat = repo.many(
        session,
        "select extract(isodow from k.occurred_at at time zone :tz)::int - 1 as weekday, "
        "extract(hour from k.occurred_at at time zone :tz)::int as hour, count(*) as visits "
        f"from memberships.checkin k where {clause_k} and k.company_id = :c "
        "and (cast(:b as uuid) is null or k.branch_id = :b) and (k.decision <> 'deny' or k.overridden) "
        "and k.business_date between :s and :e group by 1, 2 order by 1, 2",
        tz=zone, c=company_id, b=branch_id, s=start, e=end, **params_k)
    visits = repo.one(
        session,
        f"select count(*) as visits, count(distinct k.customer_id) as people from memberships.checkin k where "
        f"{clause_k} and k.company_id = :c and (cast(:b as uuid) is null or k.branch_id = :b) "
        "and (k.decision <> 'deny' or k.overridden) and k.counted and k.business_date between :s and :e",
        c=company_id, b=branch_id, s=start, e=end, **params_k) or {}

    # money owed
    owed = repo.one(
        session,
        "select coalesce(sum(r.outstanding), 0) as owed, count(distinct r.customer_id) as people, "
        "coalesce(sum(r.outstanding) filter (where r.due_date >= :t - 7), 0) as d7, "
        "coalesce(sum(r.outstanding) filter (where r.due_date < :t - 7 and r.due_date >= :t - 30), 0) as d30, "
        "coalesce(sum(r.outstanding) filter (where r.due_date < :t - 30 and r.due_date >= :t - 60), 0) as d60, "
        "coalesce(sum(r.outstanding) filter (where r.due_date < :t - 60), 0) as d60plus "
        "from memberships.invoice_run r where " + repo.scope_sql(common.view_scopes(), "r")[0] +
        " and r.company_id = :c and r.status = 'issued' and r.settle_state = 'open' and r.invoice_id is not null "
        "and r.due_date < :t and r.outstanding > 0 and (cast(:b as uuid) is null or r.branch_id = :b)",
        c=company_id, t=today, b=branch_id, **repo.scope_sql(common.view_scopes(), "r")[1]) or {}

    # freezes in the period
    clause_f, params_f = repo.scope_sql(common.view_scopes(), "m")
    freezes = repo.one(
        session,
        "select count(*) as holds, coalesce(sum(coalesce(f.days, (:t - f.started_on))), 0) as days, "
        "coalesce(sum(f.fee), 0) as fees, count(*) filter (where f.ended_on is null) as running "
        "from memberships.freeze f join memberships.member m on m.id = f.member_id "
        f"where {clause_f} and f.company_id = :c and (cast(:b as uuid) is null or m.branch_id = :b) "
        "and f.started_on between :s and :e", c=company_id, b=branch_id, s=start, e=end, t=today, **params_f) or {}

    # trials and joining
    clause_p, params_p = repo.scope_sql(common.view_scopes(), "p")
    trials = repo.one(
        session,
        "select count(*) filter (where p.trial_started_on between :s and :e) as started, "
        "count(*) filter (where p.trial_started_on between :s and :e and exists (select 1 from memberships.member m "
        "  where m.customer_id = p.customer_id and not m.is_trial and m.start_date >= p.trial_started_on)) "
        "  as converted from memberships.profile p "
        f"where {clause_p} and p.company_id = :c and (cast(:b as uuid) is null or p.branch_id = :b)",
        c=company_id, b=branch_id, s=start, e=end, **params_p) or {}

    # why people leave
    reasons = repo.many(
        session,
        "select coalesce(rc.label, 'No reason given') as reason, count(*) as members "
        "from memberships.member m left join kernel.reason_code rc on rc.id = m.cancel_reason_code_id "
        f"where {where} and m.cancelled_on between :s and :e and not m.is_trial group by 1 order by 2 desc",
        s=start, e=end, **base)

    inactive = repo.scalar(
        session, f"select count(*) from memberships.member m join memberships.profile p on p.customer_id = m.customer_id "  # noqa: E501
                 f"where {where} and m.status = 'active' and coalesce(p.last_visit_on, m.start_date) < :cut",
        cut=today - timedelta(days=28), **base)

    trainer_rows = repo.many(
        session,
        "select trainer_name, count(*) filter (where status <> 'reversed') as sessions, "
        "coalesce(sum(amount) filter (where status <> 'reversed'), 0) as earned "
        "from memberships.trainer_earning where company_id = :c and earned_on between :s and :e "
        "group by trainer_name order by sessions desc", c=company_id, s=start, e=end)

    classes = _class_fill(session, company_id, branch_id, start, end)
    at_risk = Decimal(now.get("at_risk_cancel_late") or 0) + Decimal(now.get("at_risk_held") or 0)
    mrr = Decimal(now.get("mrr") or 0)
    return {
        "company_id": company_id, "start": start, "end": end, "branch_id": branch_id,
        "members": {"active": int(now.get("active") or 0), "paused": int(now.get("paused") or 0),
                    "frozen": int(now.get("frozen") or 0), "trials": int(now.get("trials") or 0),
                    "cancelling": int(now.get("cancelling") or 0), "inactive_4_weeks": int(inactive)},
        "mrr": mrr.quantize(Decimal("0.01")), "revenue_at_risk": at_risk.quantize(Decimal("0.01")),
        "revenue_at_risk_percent": int((at_risk * 100 / mrr).quantize(Decimal(1))) if mrr > 0 else 0,
        "by_plan": [{"plan": r["plan_name"], "members": int(r["members"]), "mrr": Decimal(r["mrr"]).quantize(
            Decimal("0.01"))} for r in by_plan],
        "flow": flow, "retention": cohorts,
        "attendance": [{"weekday": int(r["weekday"]), "hour": int(r["hour"]), "visits": int(r["visits"])} for r in heat],  # noqa: E501
        "visits": int(visits.get("visits") or 0), "visitors": int(visits.get("people") or 0),
        "arrears": {k: Decimal(owed.get(k) or 0) if k != "people" else int(owed.get("people") or 0)
                    for k in ("owed", "people", "d7", "d30", "d60", "d60plus")},
        "freezes": {"holds": int(freezes.get("holds") or 0), "days": int(freezes.get("days") or 0),
                    "fees": Decimal(freezes.get("fees") or 0), "running": int(freezes.get("running") or 0)},
        "trials": {"started": int(trials.get("started") or 0), "converted": int(trials.get("converted") or 0)},
        "leaving": [{"reason": r["reason"], "members": int(r["members"])} for r in reasons],
        "class_fill": classes,
        "trainers": [{"trainer": r["trainer_name"], "sessions": int(r["sessions"]), "earned": r["earned"]}
                     for r in trainer_rows],
    }


def _class_fill(session: Session, company_id: UUID, branch_id: UUID | None, start: date,
                end: date) -> list[dict[str, Any]]:
    """How full the classes were, per class (from Bookings' group sessions, when Bookings is on)."""
    if not common.unit_enabled(session, "bookings"):
        return []
    from datetime import datetime, time

    zone = company_zone(session, company_id)
    try:
        with session.begin_nested():
            from ziira.modules.bookings.public import list_sessions

            found = list_sessions(session, branch_id=branch_id, start=datetime.combine(start, time.min, tzinfo=zone),
                                  end=datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone))
    except Exception:  # noqa: BLE001 - the report still works without it
        return []
    per: dict[str, list[int]] = {}
    for view in found:
        if view.company_id != company_id or view.capacity <= 0:
            continue
        row = per.setdefault(view.name, [0, 0, 0])
        row[0] += 1
        row[1] += view.booked
        row[2] += view.capacity
    return sorted(({"class": name, "sessions": n, "booked": b, "places": c, "fill_percent": round(b * 100 / c)}
                   for name, (n, b, c) in per.items()), key=lambda r: -r["fill_percent"])


def member_rows(session: Session, company_id: UUID, status: str | None = None) -> list[list[object]]:
    """The members list as rows for a spreadsheet."""
    _allowed(company_id)
    clause, params = _scope("m")
    rows = repo.many(
        session,
        f"select m.number, m.customer_id, m.plan_name, m.status, m.start_date, m.next_renewal_date, m.price, "
        f"m.billing_interval, m.arrears, m.past_due_since, p.number as member_number, p.card_number, p.last_visit_on "
        f"from memberships.member m left join memberships.profile p on p.customer_id = m.customer_id "
        f"where {clause} and m.company_id = :c and (cast(:s as text) is null or m.status = :s) "
        f"order by m.number limit 20000", c=company_id, s=status, **params)
    names = common.customer_names(session, {r["customer_id"] for r in rows})
    out: list[list[object]] = []
    for r in rows:
        who = names.get(r["customer_id"])
        out.append([r["member_number"], r["number"], who.name if who else "", who.phone if who else "", r["plan_name"],
                    r["status"], r["start_date"], r["next_renewal_date"], r["price"], r["billing_interval"],
                    r["arrears"], r["past_due_since"], r["card_number"], r["last_visit_on"]])
    return out


MEMBER_HEADER = ["Member number", "Membership", "Name", "Phone", "Plan", "Status", "Started", "Next renewal", "Price",
                 "Billed every", "Owed", "Late since", "Card", "Last visit"]

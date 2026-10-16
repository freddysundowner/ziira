"""What the Super Admin's frame and landing page need: search, alerts, set-up checklist, trends, feeds, audit trail.

Everything here is a read. Money is never added across currencies (series are per currency). Which alerts, search hits
and checklist links an operator sees is decided by the permissions of their role; the server of each area still
re-checks every action. Nothing country- or provider-specific is named (rule 15): providers come from the plugins' data.
"""

import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ziira.kernel import csvutil
from ziira.kernel import operator_console as console
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.platform import ai, behaviour, mail

MIN_QUERY = 2
MAX_QUERY = 80
FACTS_SECONDS = 60
TRIAL_DAYS_AHEAD = 7
LICENCE_DAYS_AHEAD = 30
BACKUP_OLD_HOURS = 26
METRICS = ("revenue", "signups", "churn")
RANGES = ("12m", "12w")
EXPORT_LIMIT = 5000
SEVERITY_ORDER = {"bad": 0, "warn": 1, "info": 2}


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- search
def _like(needle: str) -> str:
    """A LIKE pattern that finds the text as typed (the wildcards the person typed are plain characters)."""
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(q: str, permissions: frozenset[str], *, per_kind: int = 5) -> list[dict[str, str]]:
    """Subscribers, invoices, plans, licences and (for those who may see them) operators matching the text.

    Returns `{kind, id, title, subtitle, to}` rows; `to` is a path inside the console. Fewer than two characters finds
    nothing, so a stray keystroke never reads the whole database."""
    needle = q.strip()[:MAX_QUERY]
    if len(needle) < MIN_QUERY:
        return []
    like = _like(needle)
    found: list[dict[str, str]] = []
    with master_session() as m:
        for r in m.execute(text(
                "select t.code, t.name, coalesce(s.status, 'unmanaged') as status from master.tenant t "
                "left join master.subscription s on s.tenant_id = t.id "
                "where t.name ilike :q escape '\\' or t.code ilike :q escape '\\' or exists ("
                "  select 1 from master.registration r where r.tenant_id = t.id and r.email ilike :q escape '\\') "
                "order by t.created_at desc limit :n"), {"q": like, "n": per_kind}):
            found.append({"kind": "subscriber", "id": r.code, "title": r.name, "subtitle": f"{r.code} · {r.status}",
                          "to": f"/operator/subscribers/{r.code}"})
        for r in m.execute(text(
                "select i.id, i.number, i.status, i.currency, i.total, t.name as tenant_name from "
                "master.billing_invoice i left join master.tenant t on t.id = i.tenant_id "
                "where i.number ilike :q escape '\\' or t.name ilike :q escape '\\' or t.code ilike :q escape '\\' "
                "order by i.created_at desc limit :n"), {"q": like, "n": per_kind}):
            found.append({"kind": "invoice", "id": str(r.id), "title": r.number or "Draft",
                          "subtitle": " · ".join(
                              x for x in (r.tenant_name, r.status, f"{r.total} {r.currency.strip()}") if x),
                          "to": f"/operator/billing/invoices?open={r.id}"})
        for r in m.execute(text(
                "select code, name, status from master.plan where code ilike :q escape '\\' "
                "or name ilike :q escape '\\' order by sort_order, code limit :n"), {"q": like, "n": per_kind}):
            found.append({"kind": "plan", "id": r.code, "title": r.name, "subtitle": f"{r.code} · {r.status}",
                          "to": f"/operator/plans/edit/{r.code}"})
        for r in m.execute(text(
                "select licence_no, customer, status from master.licence where licence_no ilike :q escape '\\' "
                "or customer ilike :q escape '\\' or contact_email ilike :q escape '\\' "
                "order by issued_at desc limit :n"), {"q": like, "n": per_kind}):
            found.append({"kind": "licence", "id": r.licence_no, "title": r.customer,
                          "subtitle": f"{r.licence_no} · {r.status}", "to": "/operator/licences"})
        if "platform.operators" in permissions:
            for r in m.execute(text(
                    "select id, name, email, role from master.operator where name ilike :q escape '\\' "
                    "or email ilike :q escape '\\' order by name limit :n"), {"q": like, "n": per_kind}):
                found.append({"kind": "operator", "id": str(r.id), "title": r.name, "subtitle": f"{r.email} · {r.role}",
                              "to": "/operator/operators"})
    return found


# --------------------------------------------------------------------------- facts, alerts and system tiles
_lock = threading.Lock()
_cached: tuple[float, dict[str, Any]] | None = None


def clear_cache() -> None:
    """Forget the platform facts read a moment ago (tests, and after a change that should show at once)."""
    global _cached
    with _lock:
        _cached = None


def _count(m: Any, sql: str, **params: Any) -> int:
    return int(m.execute(text(sql), params).scalar_one() or 0)


def collect_facts(now: datetime | None = None) -> dict[str, Any]:
    """The platform's state in plain numbers (input to `build_alerts` and `system_view`), read at most once a minute."""
    global _cached
    moment = now or _now()
    with _lock:
        if now is None and _cached is not None and time.monotonic() - _cached[0] < FACTS_SECONDS:
            return _cached[1]
    health = console.platform_health()
    queues = health["queues"]
    snap = ai.snapshot()
    mail_status = mail.status()
    with master_session() as m:
        facts: dict[str, Any] = {
            "payments_attention": _count(
                m, "select count(*) from master.payment_attempt where status = 'mismatch' "
                   "or (status = 'failed' and created_at > :since)", since=moment - timedelta(days=7)),
            "past_due": _count(m, "select count(*) from master.subscription where status in ('past_due', 'grace')"),
            "suspended": _count(m, "select count(*) from master.subscription where status = 'suspended'"),
            "trials_ending": _count(
                m, "select count(*) from master.subscription where status = 'trialing' and trial_end is not null "
                   "and trial_end <= :until", until=moment + timedelta(days=TRIAL_DAYS_AHEAD)),
            "licences_expiring": _count(
                m, "select count(*) from master.licence where status = 'active' and valid_until is not null "
                   "and valid_until between :a and :b", a=moment, b=moment + timedelta(days=LICENCE_DAYS_AHEAD)),
            "pending_requests": _count(m, "select count(*) from master.plan_request where status = 'pending'"),
        }
    facts.update({
        "failed_jobs": int(queues["jobs_failed"]) if queues else 0,
        "jobs_due": int(queues["jobs_due"]) if queues else 0,
        "jobs_oldest_due_seconds": int(queues["jobs_oldest_due_seconds"]) if queues else 0,
        "outbox_pending": int(queues["outbox_pending"]) if queues else 0,
        "outbox_stuck": int(queues["outbox_stuck"]) if queues else 0,
        "queues_known": queues is not None,
        "businesses_behind": len(health["businesses_behind"]),
        "businesses_unreadable": len(health["businesses_unreadable"]),
        "plugins_refused": len(health["plugins"]["refused"]),
        "ready": bool(health["ready"]),
        "problems": len(health["problems"]),
        "backup_reported": bool(health["backups"]["reported"]),
        "backup_age_hours": health["backups"]["master_age_hours"],
        "mail_configured": bool(mail_status["configured"]),
        "mail_working": bool(mail_status["working"]),
        "ai_has_provider": snap.default is not None or bool(get_settings().ai_provider),
        "ai_cap_usd": str(snap.cap_usd) if snap.cap_usd is not None else None,
        "ai_spend_usd": str(snap.spend_usd.quantize(Decimal("0.01"))),
        "ai_cap_reached": snap.cap_usd is not None and snap.spend_usd >= snap.cap_usd,
    })
    if now is None:
        with _lock:
            _cached = (time.monotonic(), facts)
    return facts


# (key, how it is raised, severity, the permission that can act on it, where to go). The count is the facts' number.
_ALERTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("payments_attention", "payments_attention", "bad", "platform.billing", "/operator/payment-attempts"),
    ("suspended", "suspended", "bad", "platform.subscribers", "/operator/subscribers?status=suspended"),
    ("past_due", "past_due", "warn", "platform.subscribers", "/operator/subscribers?flag=past_due"),
    ("pending_requests", "pending_requests", "warn", "platform.billing", "/operator/billing/requests"),
    ("trials_ending", "trials_ending", "info", "platform.subscribers", "/operator/subscribers?flag=trial_ending"),
    ("failed_jobs", "failed_jobs", "bad", "platform.units", "/operator/health"),
    ("businesses_behind", "businesses_behind", "warn", "platform.units", "/operator/backups"),
    ("businesses_unreadable", "businesses_unreadable", "bad", "platform.units", "/operator/health"),
    ("plugins_refused", "plugins_refused", "warn", "platform.units", "/operator/health"),
    ("licences_expiring", "licences_expiring", "warn", "platform.licences", "/operator/licences"),
)


def build_alerts(facts: dict[str, Any], permissions: frozenset[str]) -> list[dict[str, Any]]:
    """The things that need an operator, worst first, limited to the areas their role can act in.

    Each is `{key, severity, count, to, needs}`; `count` is how many (1 for a yes/no condition)."""
    out: list[dict[str, Any]] = []
    for key, fact, severity, needs, to in _ALERTS:
        if facts.get(fact, 0) > 0 and needs in permissions:
            out.append({"key": key, "severity": severity, "count": int(facts[fact]), "to": to, "needs": needs})
    if facts.get("backup_reported") is True:
        age = facts.get("backup_age_hours")
        if (age is None or age > BACKUP_OLD_HOURS) and "platform.units" in permissions:
            out.append({"key": "backup_old", "severity": "bad", "count": 1, "to": "/operator/backups",
                        "needs": "platform.units"})
    if not facts.get("ready", True) and "platform.units" in permissions:
        out.append({"key": "not_ready", "severity": "bad", "count": int(facts.get("problems", 1)) or 1,
                    "to": "/operator/health", "needs": "platform.units"})
    if not facts.get("mail_working", True) and "platform.settings" in permissions:
        out.append({"key": "mail_not_working", "severity": "warn", "count": 1, "to": "/operator/email",
                    "needs": "platform.settings"})
    if facts.get("ai_cap_reached") and "platform.ai" in permissions:
        out.append({"key": "ai_cap_reached", "severity": "warn", "count": 1, "to": "/operator/ai",
                    "needs": "platform.ai"})
    out.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], a["key"]))
    return out


def alerts(permissions: frozenset[str]) -> dict[str, Any]:
    items = build_alerts(collect_facts(), permissions)
    return {"total": len(items), "worst": items[0]["severity"] if items else None, "items": items}


def system_view(facts: dict[str, Any]) -> dict[str, Any]:
    """The dashboard's health tiles from the facts (no secrets: counts, ages and money amounts)."""
    return {
        "ready": facts["ready"], "problems": facts["problems"],
        "queues_known": facts["queues_known"], "failed_jobs": facts["failed_jobs"], "jobs_due": facts["jobs_due"],
        "jobs_oldest_due_seconds": facts["jobs_oldest_due_seconds"], "outbox_pending": facts["outbox_pending"],
        "outbox_stuck": facts["outbox_stuck"],
        "backup_reported": facts["backup_reported"], "backup_age_hours": facts["backup_age_hours"],
        "businesses_behind": facts["businesses_behind"], "businesses_unreadable": facts["businesses_unreadable"],
        "mail_configured": facts["mail_configured"], "mail_working": facts["mail_working"],
        "ai_has_provider": facts["ai_has_provider"], "ai_cap_usd": facts["ai_cap_usd"],
        "ai_spend_usd": facts["ai_spend_usd"], "ai_cap_reached": facts["ai_cap_reached"],
    }


def system() -> dict[str, Any]:
    return system_view(collect_facts())


# --------------------------------------------------------------------------- the setup checklist and risky settings
def _item(key: str, done: bool, to: str, needs: str, *, optional: bool = False, detail: str | None = None,
          feature: str | None = None) -> dict[str, Any]:
    return {"key": key, "done": done, "to": to, "needs": needs, "optional": optional, "detail": detail,
            "feature": feature}


def build_risks(*, environment: str, mfa_off: bool, mail_working: bool, registration_mode: str, ai_has_provider: bool,
                permissions: frozenset[str]) -> list[dict[str, str]]:
    """Settings that put the platform at risk, for the banner under the top bar (worst first)."""
    risks: list[dict[str, str]] = []
    if mfa_off:
        risks.append({"key": "mfa_off", "severity": "bad", "to": "/operator/account", "needs": "platform.view"})
    if registration_mode != "closed" and not mail_working:
        risks.append({"key": "registration_without_email", "severity": "bad", "to": "/operator/settings",
                      "needs": "platform.settings"})
    elif not mail_working:
        risks.append({"key": "mail_not_configured", "severity": "warn", "to": "/operator/email",
                      "needs": "platform.settings"})
    if not ai_has_provider:
        risks.append({"key": "no_ai_provider", "severity": "info", "to": "/operator/ai", "needs": "platform.ai"})
    return [r for r in risks if r["needs"] in permissions]


def setup(permissions: frozenset[str]) -> dict[str, Any]:
    """Where the platform owner stands on first-time set-up (from real state), and the risky settings that are on."""
    cfg = get_settings()
    mail_status = mail.status()
    snap = ai.snapshot()
    saved_mode = str(behaviour.get("registration.mode") or "")
    mode = behaviour.registration_mode_set()
    with master_session() as m:
        gateways = _count(m, "select count(*) from master.payment_gateway where enabled")
        public_plans = _count(m, "select count(*) from master.plan where is_public and status = 'active'")
        published = _count(m, "select count(*) from master.site_publish")
        licences = _count(m, "select count(*) from master.licence")
    items = [
        _item("email", bool(mail_status["working"]), "/operator/email", "platform.settings"),
        _item("registration", saved_mode != "", "/operator/settings", "platform.settings", detail=mode),
        _item("ai", snap.default is not None or bool(cfg.ai_provider), "/operator/ai", "platform.ai"),
        _item("payments", gateways > 0, "/operator/payment-methods", "platform.billing"),
        _item("plans", public_plans > 0, "/operator/plans", "platform.plans"),
        _item("website", published > 0, "/operator/website", "platform.content", feature="website"),
        _item("licence", licences > 0, "/operator/licences", "platform.licences", optional=True),
    ]
    risks = build_risks(environment=cfg.env, mfa_off=cfg.env == "production" and cfg.operator_password_only(),
                        mail_working=bool(mail_status["working"]), registration_mode=mode,
                        ai_has_provider=snap.default is not None or bool(cfg.ai_provider), permissions=permissions)
    return {"environment": cfg.env, "mode": cfg.deployment_mode, "items": items, "risks": risks}


# --------------------------------------------------------------------------- trends
def bucket_starts(range_: str, today: date) -> list[date]:
    """Twelve bucket start dates ending with the current one: calendar months ("12m") or Monday weeks ("12w")."""
    if range_ == "12m":
        year, month = today.year, today.month
        starts = []
        for back in range(11, -1, -1):
            index = year * 12 + (month - 1) - back
            starts.append(date(index // 12, index % 12 + 1, 1))
        return starts
    if range_ == "12w":
        monday = today - timedelta(days=today.weekday())
        return [monday - timedelta(weeks=back) for back in range(11, -1, -1)]
    raise ValidationFailed("Range is one of: " + ", ".join(RANGES))


def fill_series(starts: list[date], found: dict[tuple[str | None, date], Decimal]) -> list[dict[str, Any]]:
    """One series per currency (or one for a count), a value for every bucket, zero where nothing happened."""
    names = sorted({k[0] for k in found}, key=lambda c: (c is None, c or ""))
    return [{"currency": name, "points": [str(found.get((name, s), Decimal(0))) for s in starts]} for name in names]


def series(metric: str, range_: str, *, today: date | None = None) -> dict[str, Any]:
    """Money collected, new businesses or businesses lost per month or week; money is per currency, never summed."""
    if metric not in METRICS:
        raise ValidationFailed("Metric is one of: " + ", ".join(METRICS))
    starts = bucket_starts(range_, today or _now().date())
    unit = "month" if range_ == "12m" else "week"
    found: dict[tuple[str | None, date], Decimal] = {}
    with master_session() as m:
        if metric == "revenue":
            rows = m.execute(text(
                f"select date_trunc('{unit}', paid_on)::date as b, currency, sum(amount) as v from "
                "master.billing_payment where reversed_at is null and paid_on >= :s group by 1, 2"), {"s": starts[0]})
            found = {(r.currency.strip(), r.b): Decimal(r.v) for r in rows}
        elif metric == "signups":
            rows = m.execute(text(
                f"select date_trunc('{unit}', created_at at time zone 'UTC')::date as b, count(*) as v "
                "from master.tenant where created_at >= :s group by 1"), {"s": starts[0]})
            found = {(None, r.b): Decimal(r.v) for r in rows}
        else:
            rows = m.execute(text(
                f"select date_trunc('{unit}', occurred_at at time zone 'UTC')::date as b, "
                "count(distinct tenant_id) as v from master.subscription_event "
                "where kind in ('status.cancelled', 'status.expired') and occurred_at >= :s group by 1"),
                {"s": starts[0]})
            found = {(None, r.b): Decimal(r.v) for r in rows}
    if not found:
        found = {(None, starts[0]): Decimal(0)} if metric != "revenue" else {}
    return {"metric": metric, "range": range_, "buckets": starts, "series": fill_series(starts, found)}


# --------------------------------------------------------------------------- feeds
def feed(limit: int = 8) -> dict[str, Any]:
    """The newest payments and sign-ups."""
    with master_session() as m:
        payments = [dict(r._mapping) for r in m.execute(text(
            "select p.id, p.paid_on, p.amount, p.currency, p.method, p.reversed_at is not null as reversed, "
            "i.number as invoice_number, t.code as tenant_code, t.name as tenant_name from master.billing_payment p "
            "join master.billing_invoice i on i.id = p.invoice_id left join master.tenant t on t.id = i.tenant_id "
            "order by p.created_at desc limit :n"), {"n": limit})]
        signups = [dict(r._mapping) for r in m.execute(text(
            "select t.code, t.name, t.created_at, s.status, s.plan_name from master.tenant t "
            "left join master.subscription s on s.tenant_id = t.id order by t.created_at desc limit :n"), {"n": limit})]
    for p in payments:
        p["currency"] = p["currency"].strip()
    return {"payments": payments, "signups": signups}


# --------------------------------------------------------------------------- audit trail
def _audit_where(operator: str | None, action: str | None, target: str | None, outcome: str | None,
                 date_from: date | None, date_to: date | None) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = ["true"]
    params: dict[str, Any] = {}
    for column, value, key in (("operator_name", operator, "f_op"), ("action", action, "f_act"),
                               ("target", target, "f_tgt")):
        if value and value.strip():
            clauses.append(f"{column} ilike :{key} escape '\\'")
            params[key] = _like(value.strip())
    if outcome:
        if outcome not in ("ok", "refused", "failed"):
            raise ValidationFailed("Outcome is ok, refused or failed")
        clauses.append("outcome = :f_out")
        params["f_out"] = outcome
    if date_from:
        clauses.append("occurred_at >= :f_from")
        params["f_from"] = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
    if date_to:
        clauses.append("occurred_at < :f_until")
        params["f_until"] = datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(days=1)
    if date_from and date_to and date_to < date_from:
        raise ValidationFailed("The end date is before the start date")
    return " and ".join(clauses), params


def audit_trail(*, operator: str | None = None, action: str | None = None, target: str | None = None,
                outcome: str | None = None, date_from: date | None = None, date_to: date | None = None,
                limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """The operator action trail, newest first, with filters; `total` is how many lines matched."""
    where, params = _audit_where(operator, action, target, outcome, date_from, date_to)
    with master_session() as m:
        total = int(m.execute(text(f"select count(*) from master.operator_action_log where {where}"),
                              params).scalar_one())
        rows = [dict(r._mapping) for r in m.execute(text(
            "select id, occurred_at, operator_name, action, target, outcome, reason, detail from "
            f"master.operator_action_log where {where} order by id desc limit :l offset :o"),
            {**params, "l": limit, "o": offset})]
    return {"total": total, "items": rows}


def audit_csv(**filters: Any) -> tuple[str, int]:
    """The same lines as spreadsheet text (newest first, at most EXPORT_LIMIT), and how many were written."""
    page = audit_trail(limit=EXPORT_LIMIT, offset=0, **filters)
    rows = [[r["occurred_at"].isoformat(), r["operator_name"], r["action"], r["target"], r["outcome"], r["reason"]]
            for r in page["items"]]
    return csvutil.to_csv(["When (UTC)", "Operator", "Action", "Target", "Outcome", "Reason"], rows), len(rows)

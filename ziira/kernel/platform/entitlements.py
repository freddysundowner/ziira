"""What a business may do under its plan (SaaS) or the instance's licence (self-hosted).

One question, asked in a few places by the kernel: *which units, which limits, and may it write right now?*

- `enforce_access(ctx, request)` runs on every authenticated request (see `ziira.sdk.request_context`): a suspended
  business can reach billing, sign-in and the data export, and its tills can still upload sales that already happened;
  a cancelled, expired or unlicensed one is read-only. Nothing is ever deleted by this.
- `check_unit(...)` refuses switching on a unit the plan does not include ("not in your plan: upgrade").
- `check_limit(session, kind)` refuses adding a user, branch or company beyond the plan's limit, with a clear message.

A business without a subscription row is *unmanaged* (businesses made from the command line before plans existed):
no limits and no billing. `ZIIRA_DEPLOYMENT_MODE=selfhosted` ignores subscription rows and reads the installed licence.
Decisions are cached for a few seconds per process; every change made through this package clears the cache.
"""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.config import get_settings
from ziira.kernel.context import RequestContext
from ziira.kernel.db import master_session
from ziira.kernel.errors import NotInPlan, PlanLimitReached, SubscriptionEnded, SubscriptionInactive
from ziira.kernel.registry import discover

CACHE_SECONDS = 10
FULL, WARNING, BILLING_ONLY, READ_ONLY = "full", "warning", "billing_only", "read_only"
STATUS_ACCESS = {
    "trialing": FULL,
    "active": FULL,
    "past_due": WARNING,
    "grace": WARNING,
    "suspended": BILLING_ONLY,
    "cancelled": READ_ONLY,
    "expired": READ_ONLY,
}
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Always reachable, even when suspended: sign-in and sessions, the business's own billing page, the shell's start-up
# reads, privacy (data) requests, and the till uploading sales that already happened (CLAUDE.md: a business event that
# already happened is accepted).
ALWAYS = ("/api/v1/auth/", "/api/v1/billing/", "/api/v1/privacy/", "/api/v1/pos/sync/upload")
ALWAYS_READ = ("/api/v1/units", "/api/v1/organisation", "/api/v1/editions")
LIMIT_KINDS = {"users": "max_users", "branches": "max_branches", "companies": "max_companies"}


@dataclass(frozen=True)
class Entitlements:
    """What applies to one business now."""

    source: str  # none | subscription | licence
    status: str  # subscription status, licence status, or "unmanaged"
    access: str  # full | warning | billing_only | read_only
    units: frozenset[str] | None  # None = every unit
    max_users: int | None = None
    max_branches: int | None = None
    max_companies: int | None = None
    plan_code: str | None = None
    plan_name: str | None = None
    message: str = ""
    period_end: datetime | None = None
    extra: dict[str, Any] | None = None

    @property
    def managed(self) -> bool:
        return self.source != "none"

    def limit(self, kind: str) -> int | None:
        return {"users": self.max_users, "branches": self.max_branches, "companies": self.max_companies}[kind]


UNMANAGED = Entitlements("none", "unmanaged", FULL, None)
_cache: dict[str, tuple[float, Entitlements]] = {}


def invalidate(tenant_id: UUID | None = None) -> None:
    """Forget cached decisions (one business, or all)."""
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(str(tenant_id), None)


def mode() -> str:
    return get_settings().deployment_mode


def allowed_units(names: list[str]) -> frozenset[str]:
    """The units a plan allows: its own plus what they require (an allowed unit must be able to work)."""
    known = discover()
    out: set[str] = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in out or name not in known:
            continue
        out.add(name)
        pending.extend(known[name].requires)
    return frozenset(out)


def _message(status: str, period_end: datetime | None) -> str:
    when = f" on {period_end:%Y-%m-%d}" if period_end else ""
    return {
        "trialing": f"Your free trial ends{when}." if period_end else "You are on a free trial.",
        "past_due": "Your latest invoice is overdue. Please pay it to avoid interruption.",
        "grace": "Your invoice is well overdue and your account will be suspended soon. Please pay it now.",
        "suspended": "Your account is suspended for non-payment. Pay your invoice to restore it. "
        "Your data is safe and the till can still upload sales.",
        "cancelled": "Your subscription has ended. Your data is kept and can be viewed and exported; "
        "choose a plan to continue working.",
        "expired": "Your subscription has expired. Your data is kept and can be viewed and exported; "
        "choose a plan to continue working.",
    }.get(status, "")


def _from_subscription(row: Any) -> Entitlements:
    e = row.entitlements or {}
    units = e.get("units")
    end = row.trial_end if row.status == "trialing" and row.trial_end else row.period_end
    return Entitlements(
        "subscription",
        row.status,
        STATUS_ACCESS.get(row.status, FULL),
        allowed_units(list(units)) if units is not None else None,
        e.get("max_users"),
        e.get("max_branches"),
        e.get("max_companies"),
        row.plan_code,
        row.plan_name,
        _message(row.status, end),
        end,
        {k: v for k, v in e.items() if k.startswith("limit_")},
    )


def _from_licence(now: datetime) -> Entitlements:
    from ziira.kernel.platform import licences

    info = licences.describe(now=now)
    if not info["installed"]:
        if info["required"]:
            return Entitlements(
                "licence",
                "unlicensed",
                READ_ONLY,
                frozenset(),
                message="No licence is installed. The system is read-only: install your licence file.",
            )
        return UNMANAGED
    if not info["valid_signature"]:
        return Entitlements("licence", info["status"], READ_ONLY, frozenset(), message=info["message"])
    ent = info["entitlements"]
    until = licences._when(info["valid_until"])
    return Entitlements(
        "licence",
        info["status"],
        info["access"],
        allowed_units(list(ent["units"])),
        ent.get("max_users"),
        ent.get("max_branches"),
        ent.get("max_companies"),
        ent.get("plan_code"),
        info["customer"],
        info["message"],
        until,
    )


def for_tenant(tenant_id: UUID, *, now: datetime | None = None, use_cache: bool = True) -> Entitlements:
    """The entitlements of a business now."""
    key = str(tenant_id)
    if use_cache and now is None:
        hit = _cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    moment = now or datetime.now(UTC)
    if mode() == "selfhosted":
        result = _from_licence(moment)
    else:
        with master_session() as m:
            row = m.execute(text("select * from master.subscription where tenant_id = :t"), {"t": key}).first()
        result = _from_subscription(row) if row is not None else UNMANAGED
    if now is None:
        _cache[key] = (time.monotonic(), result)
    return result


# --------------------------------------------------------------------------- access (every request)
def _always_allowed(method: str, path: str) -> bool:
    if any(path.startswith(p) for p in ALWAYS):
        return True
    return method.upper() in SAFE_METHODS and any(path == p or path.startswith(p + "/") for p in ALWAYS_READ)


def check_access(access: str, status: str, message: str, method: str, path: str, query: dict[str, str]) -> None:
    """Pure: raise the right 402 unless this request is allowed at this access level."""
    if access in (FULL, WARNING) or _always_allowed(method, path):
        return
    csv_export = method.upper() in SAFE_METHODS and query.get("format") == "csv"
    if access == READ_ONLY:
        if method.upper() in SAFE_METHODS:
            return
        raise SubscriptionEnded(message or "This account is read-only.", {"subscription_status": status})
    if csv_export:
        return
    raise SubscriptionInactive(message or "This account is suspended.", {"subscription_status": status})


def enforce_access(ctx: RequestContext, request: Request) -> None:
    """Refuse a request the business's subscription (or licence) does not allow. Platform staff in a support session are
    not stopped (they are helping; everything they do is logged)."""
    if ctx.support_session_id is not None:
        return
    ent = for_tenant(ctx.tenant_id)
    if ent.access in (FULL, WARNING):
        return
    check_access(ent.access, ent.status, ent.message, request.method, request.url.path, dict(request.query_params))


# --------------------------------------------------------------------------- units and limits
def unit_allowed(tenant_id: UUID, unit: str) -> bool:
    ent = for_tenant(tenant_id)
    return ent.units is None or unit in ent.units


def check_unit(tenant_id: UUID, unit: str, title: str | None = None) -> None:
    """Raise NotInPlan unless the plan (or licence) includes the unit."""
    ent = for_tenant(tenant_id)
    if ent.units is None or unit in ent.units:
        return
    which = f" ({ent.plan_name})" if ent.plan_name else ""
    raise NotInPlan(
        f"{title or unit} is not in your plan{which}. Upgrade your plan to use it.",
        {"unit": unit, "plan": ent.plan_code},
    )


def usage(session: Session) -> dict[str, int]:
    """What the business has now, counted in its own database."""
    row = session.execute(
        text(
            "select (select count(*) from kernel.app_user where status in ('active', 'invited')) as users, "
            "(select count(*) from kernel.branch where is_active) as branches, "
            "(select count(*) from kernel.company) as companies"
        )
    ).one()
    return {"users": int(row.users), "branches": int(row.branches), "companies": int(row.companies)}


def check_limit(session: Session, tenant_id: UUID, kind: str, adding: int = 1) -> None:
    """Raise PlanLimitReached when adding `adding` more `users`/`branches`/`companies` would pass the plan's limit.
    Existing records are never touched: a business over its limit (after a downgrade) simply cannot add more."""
    ent = for_tenant(tenant_id)
    limit = ent.limit(kind)
    if limit is None:
        return
    have = usage(session)[kind]
    if have + adding > limit:
        which = f" ({ent.plan_name})" if ent.plan_name else ""
        raise PlanLimitReached(
            f"Your plan{which} allows {limit} {kind} and you have {have}. Upgrade your plan to add more.",
            {"limit": limit, "kind": kind, "used": have},
        )


def snapshot(
    plan: dict[str, Any], units: list[str], extra_users: int = 0, extra_branches: int = 0, extra_companies: int = 0
) -> dict[str, Any]:
    """The entitlements copied into a subscription when it is sold (add-on quantities included)."""

    def plus(base: int | None, more: int) -> int | None:
        return None if base is None else base + more

    return {
        "edition": plan.get("edition"),
        "units": sorted(units),
        "max_users": plus(plan["max_users"], extra_users),
        "max_branches": plus(plan["max_branches"], extra_branches),
        "max_companies": plus(plan["max_companies"], extra_companies),
        **{f"limit_{k}": v for k, v in (plan.get("limits") or {}).items()},
    }


def dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, default=str)

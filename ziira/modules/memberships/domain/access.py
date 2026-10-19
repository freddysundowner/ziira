"""May this person come in now? Pure rules (no database, no clock): the same answer for the desk, the kiosk and a door
controller.

The service gathers the facts (the person's profile, memberships and packages, the plan's time windows and branch
list, arrears) and this module decides `allow`, `warn` (let in, but tell the staff why) or `deny`, with every reason in
plain words. A staff override is not decided here: the service records it with its reason."""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

ALLOW, WARN, DENY = "allow", "warn", "deny"
ZERO = Decimal(0)

# reason codes (stable: the access API and the web app switch on them)
BLOCKED = "blocked"
NO_MEMBERSHIP = "no_membership"
NOT_STARTED = "not_started"
ENDED = "ended"
ON_HOLD = "on_hold"
FROZEN = "frozen"
CLASSES_ONLY = "classes_only"
WRONG_BRANCH = "wrong_branch"
OUTSIDE_HOURS = "outside_hours"
PAYMENT_LATE = "payment_late"
PAYMENT_OVERDUE = "payment_overdue"
WAIVER_MISSING = "waiver_missing"
EXPIRING = "expiring"
NO_CREDITS = "no_credits"
ALREADY_IN = "already_in"
TRIAL = "trial"
CANCELLING = "cancelling"
BIRTHDAY = "birthday"
NOT_FOUND = "not_found"


@dataclass(frozen=True)
class Reason:
    code: str
    message: str
    level: str = "info"                    # deny | warn | info

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "level": self.level}


@dataclass(frozen=True)
class MembershipFact:
    """A membership as the door sees it (the plan's access settings are the plan's current ones)."""

    id: str
    number: str
    plan_name: str
    status: str                             # active | paused | frozen | cancelled | expired
    start_date: date
    end_date: date | None
    cancel_at: date | None
    past_due_since: date | None
    arrears: Decimal = ZERO
    hold_kind: str | None = None
    plan_kind: str = "recurring"
    is_trial: bool = False
    gym_access: bool = True
    access_rules: tuple[dict[str, Any], ...] = ()
    branch_ids: tuple[str, ...] = ()
    balance: Decimal = ZERO


@dataclass(frozen=True)
class PackageFact:
    """A bought package that could pay for one visit."""

    id: str
    name: str
    balance: Decimal
    expires_on: date | None
    pays_for_entry: bool = True


@dataclass(frozen=True)
class Facts:
    today: date
    local_time: time
    weekday: int                            # Monday is 0
    branch_id: str
    blocked: bool = False
    block_reason: str | None = None
    waiver_required: bool = False
    waiver_accepted: bool = True
    memberships: tuple[MembershipFact, ...] = ()
    packages: tuple[PackageFact, ...] = ()
    grace_days: int = 0
    expiry_warning_days: int = 7
    counted_today: bool = False             # a visit is already counted for today (no second credit is taken)
    birthday: bool = False


@dataclass(frozen=True)
class Entitlement:
    """What lets the person in: `holder_type` membership or package; `consumes` is the credit taken (0 for a
    membership)."""

    holder_type: str
    holder_id: str
    label: str
    consumes: Decimal = ZERO


@dataclass(frozen=True)
class Decision:
    outcome: str
    reasons: tuple[Reason, ...] = ()
    entitlement: Entitlement | None = None
    member_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.outcome in (ALLOW, WARN)

    @property
    def headline(self) -> str:
        """The one sentence for a screen or a door display: the most serious reason."""
        order = {DENY: 0, WARN: 1, "info": 2}
        ranked = sorted(self.reasons, key=lambda r: order.get(r.level, 3))
        return ranked[0].message if ranked else "Welcome"

    @property
    def code(self) -> str:
        """The code of the most serious reason ('ok' when there is none)."""
        order = {DENY: 0, WARN: 1, "info": 2}
        ranked = sorted(self.reasons, key=lambda r: order.get(r.level, 3))
        return ranked[0].code if ranked else "ok"


# --------------------------------------------------------------------------- time windows
def _minutes(value: str) -> int:
    hours, _, minutes = value.partition(":")
    return int(hours) * 60 + int(minutes or 0)


def window_allows(rules: tuple[dict[str, Any], ...] | list[dict[str, Any]], weekday: int, at: time) -> bool:
    """True when `rules` (the plan's time windows) allow entry on this weekday at this time. No windows: always. A
    window
    that ends before it starts runs past midnight (22:00 to 06:00)."""
    if not rules:
        return True
    now = at.hour * 60 + at.minute
    for rule in rules:
        days = rule.get("days") or list(range(7))
        start, end = _minutes(str(rule.get("from", "00:00"))), _minutes(str(rule.get("to", "24:00")))
        if start <= end:
            if weekday in days and start <= now < end:
                return True
        elif (weekday in days and now >= start) or ((weekday - 1) % 7 in days and now < end):
            return True
    return False


def describe_windows(rules: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    parts = []
    for rule in rules:
        days = rule.get("days") or list(range(7))
        label = "every day" if len(days) == 7 else ", ".join(names[d] for d in sorted(days))
        parts.append(f"{label} {rule.get('from', '00:00')} to {rule.get('to', '24:00')}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- the decision
def _membership_verdict(m: MembershipFact, f: Facts) -> tuple[list[Reason], bool]:
    """(reasons, usable) for one membership: usable means it can let the person in, perhaps with a warning."""
    label = f"{m.plan_name} ({m.number})"
    if m.status in ("cancelled", "expired"):
        return [Reason(ENDED, f"{label} has ended", DENY)], False
    if m.status == "paused":
        return [Reason(ON_HOLD, f"{label} is on hold", DENY)], False
    if m.status == "frozen":
        why = " for unpaid fees" if m.hold_kind == "arrears" else ""
        return [Reason(FROZEN, f"{label} is frozen{why}", DENY)], False
    if m.start_date > f.today:
        return [Reason(NOT_STARTED, f"{label} starts on {m.start_date}", DENY)], False
    if (m.end_date is not None and m.end_date <= f.today) or (m.cancel_at is not None and m.cancel_at <= f.today):
        return [Reason(ENDED, f"{label} has ended", DENY)], False
    if not m.gym_access:
        return [Reason(CLASSES_ONLY, f"{label} is for booked classes only", DENY)], False
    if m.branch_ids and f.branch_id not in m.branch_ids:
        return [Reason(WRONG_BRANCH, f"{label} is not valid at this branch", DENY)], False
    if not window_allows(m.access_rules, f.weekday, f.local_time):
        return [Reason(OUTSIDE_HOURS, f"{label} is valid {describe_windows(m.access_rules)}", DENY)], False
    reasons: list[Reason] = []
    if m.past_due_since is not None and m.arrears > 0:
        late = (f.today - m.past_due_since).days
        if late > f.grace_days:
            return [Reason(PAYMENT_OVERDUE, f"Payment is {late} days late ({m.arrears:,.2f} owed)", DENY)], False
        if late > 0:
            reasons.append(Reason(PAYMENT_LATE, f"Payment is {late} days late ({m.arrears:,.2f} owed)", WARN))
    if m.end_date is not None:
        left = (m.end_date - f.today).days
        if left <= f.expiry_warning_days:
            reasons.append(Reason(EXPIRING, f"{label} ends in {left} days", WARN))
    if m.cancel_at is not None:
        left = (m.cancel_at - f.today).days
        reasons.append(Reason(CANCELLING, f"{label} ends in {left} days (cancelled)", "info"))
    if m.is_trial:
        reasons.append(Reason(TRIAL, "Trial visit", "info"))
    return reasons, True


def decide(f: Facts) -> Decision:
    """The decision for one person at one branch at one moment."""
    if f.blocked:
        why = f": {f.block_reason}" if f.block_reason else ""
        return Decision(DENY, (Reason(BLOCKED, f"Entry is stopped for this member{why}", DENY),))
    reasons: list[Reason] = []
    if f.waiver_required and not f.waiver_accepted:
        reasons.append(Reason(WAIVER_MISSING, "The current terms have not been accepted", DENY))
    best: tuple[MembershipFact, list[Reason]] | None = None
    failed: list[Reason] = []
    for m in f.memberships:
        verdict, usable = _membership_verdict(m, f)
        if usable:
            if best is None or sum(r.level == WARN for r in verdict) < sum(r.level == WARN for r in best[1]):
                best = (m, verdict)
        else:
            failed += verdict
    entitlement: Entitlement | None = None
    member_id: str | None = None
    if best is not None:
        reasons += best[1]
        entitlement = Entitlement("membership", best[0].id, f"{best[0].plan_name} ({best[0].number})")
        member_id = best[0].id
    else:
        pack = next((p for p in sorted(f.packages, key=lambda p: (p.expires_on or date.max, p.id))
                     if p.pays_for_entry and p.balance > 0 and (p.expires_on is None or p.expires_on >= f.today)),
                    None)
        if pack is not None:
            take = ZERO if f.counted_today else Decimal(1)
            entitlement = Entitlement("package", pack.id, pack.name, take)
            left = pack.balance - take
            if left <= 1:
                reasons.append(Reason(NO_CREDITS, f"{left:g} visit{'s' if left != 1 else ''} left on {pack.name}",
                                      WARN))
            if pack.expires_on is not None and (pack.expires_on - f.today).days <= f.expiry_warning_days:
                reasons.append(Reason(EXPIRING, f"{pack.name} expires on {pack.expires_on}", WARN))
        elif failed:
            reasons += failed
        elif f.packages:
            reasons.append(Reason(NO_CREDITS, "No visits left on the packages", DENY))
        else:
            reasons.append(Reason(NO_MEMBERSHIP, "No active membership or visits left", DENY))
    if f.birthday:
        reasons.append(Reason(BIRTHDAY, "It is their birthday", "info"))
    if entitlement is None or any(r.level == DENY for r in reasons):
        outcome = DENY
    else:
        outcome = WARN if any(r.level == WARN for r in reasons) else ALLOW
    return Decision(outcome, tuple(reasons), entitlement, member_id)


def when(moment: datetime) -> tuple[date, time, int]:
    """The date, time of day and weekday (Monday 0) of a local moment."""
    return moment.date(), moment.time().replace(second=0, microsecond=0), moment.weekday()

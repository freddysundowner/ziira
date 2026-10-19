"""Check-in: who is at the door, may they enter, and the record of it.

One decision for every way in: the front desk (by name, phone, member number), a scanner or camera (the number in a QR
code or barcode), a card, tag or wristband number kept on the member, the self-service kiosk, and the access-decision
API a
door or turnstile controller calls. The decision is the pure rule in `domain/access.py`; this module gathers the facts
quickly (a handful of indexed queries), serialises two desks checking in the same person, takes a visit from a package
when that is what lets the person in, records the attempt, and publishes `checkin.recorded`.

A staff override of a refusal needs 'memberships.override' and a reason and is recorded and audited. A check-in is never
edited. Offline desks queue their check-ins with a client id and the moment they happened; `sync` records them later and
flags anything the server would have refused (a business event that already happened is accepted, not refused)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from ziira.modules.crm.public import search_customers
from ziira.modules.memberships.domain import access
from ziira.modules.memberships.permissions import CHECKIN, MANAGE, OVERRIDE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, credits, profiles, waivers
from ziira.sdk import (
    Event,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_zone,
    current_context,
    flag_for_review,
    publish,
)

ENTRY_SERVICE = "gym"
METHODS = ("desk", "scan", "card", "kiosk", "api", "class")
QR_PREFIX = "ZM:"


@dataclass
class Result:
    """The answer to 'may this person come in?' and what was recorded."""

    decision: access.Decision
    profile: repo.Row | None
    checkin: repo.Row | None
    duplicate: bool = False
    overridden: bool = False
    owed: Decimal = Decimal(0)
    credits_left: Decimal | None = None
    message: str = ""


# --------------------------------------------------------------------------- finding the person
def clean_identifier(raw: str) -> str:
    """What a scanner or a typist gave: a member number, the text of a QR code (`ZM:` and the number), or a card
    number."""
    text = raw.strip()
    if text.upper().startswith(QR_PREFIX):
        text = text[len(QR_PREFIX):]
    return text.strip()


def resolve(session: Session, company_id: UUID, identifier: str) -> repo.Row | None:
    """The profile for a member number, card/tag/wristband number or QR text; None when nobody has it. Exact match only
    (a name or phone is searched with `search`)."""
    text = clean_identifier(identifier)
    if not text or len(text) > 60:
        return None
    return repo.one(session, "select * from memberships.profile where company_id = :c and "
                             "(upper(number) = upper(:t) or card_number = upper(:t)) limit 1", c=company_id, t=text)


def search(session: Session, company_id: UUID, query: str, limit: int = 12) -> list[repo.Row]:
    """People matching what the desk typed: member number or card (exact), or part of a name, or a phone number. Each
    comes with
    a one-line standing so the desk can pick the right one."""
    typed = clean_identifier(query)
    if not typed:
        return []
    found: dict[UUID, repo.Row] = {}
    exact = resolve(session, company_id, typed)
    if exact is not None:
        found[exact["customer_id"]] = exact
    for customer in search_customers(session, company_id, typed, limit):
        profile = profiles.by_customer(session, customer.id)
        if profile is not None and customer.id not in found:
            found[customer.id] = profile
    rows = profiles.with_customer(session, list(found.values())[:limit])
    standing = standings(session, [r["customer_id"] for r in rows])
    return [{**r, **standing.get(r["customer_id"], {})} for r in rows]


def standings(session: Session, customer_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    """For each customer: the plan they are on, its status and any arrears (one line for a search result)."""
    if not customer_ids:
        return {}
    out: dict[UUID, dict[str, Any]] = {}
    for r in repo.many(
            session,
            "select distinct on (customer_id) customer_id, plan_name, status, arrears, next_renewal_date "
            "from memberships.member where customer_id = any(cast(:ids as uuid[])) "
            "order by customer_id, (status = 'active') desc, start_date desc", ids=[str(i) for i in customer_ids]):
        out[r["customer_id"]] = {"plan_name": r["plan_name"], "membership_status": r["status"],
                                 "arrears": r["arrears"], "next_renewal_date": r["next_renewal_date"]}
    return out


# --------------------------------------------------------------------------- facts
def _membership_facts(rows: list[repo.Row]) -> tuple[access.MembershipFact, ...]:
    return tuple(access.MembershipFact(
        id=str(r["id"]), number=r["number"], plan_name=r["plan_name"], status=r["status"], start_date=r["start_date"],
        end_date=r["end_date"], cancel_at=r["cancel_at"], past_due_since=r["past_due_since"],
        arrears=Decimal(r["arrears"]), hold_kind=r["hold_kind"], plan_kind=r["plan_kind"], is_trial=r["is_trial"],
        gym_access=r["gym_access"], access_rules=tuple(r["access_rules"] or ()),
        branch_ids=tuple(r["branch_ids"] or ())) for r in rows)


MEMBERSHIP_SQL = (
    "select m.id, m.number, m.customer_id, m.plan_name, m.status, m.start_date, m.end_date, m.cancel_at, "
    "  m.past_due_since, m.arrears, m.hold_kind, m.is_trial, p.kind as plan_kind, p.gym_access, p.access_rules, "
    "  p.branch_ids from memberships.member m join memberships.plan p on p.id = m.plan_id ")
PACKAGE_SQL = (
    "select s.id, s.customer_id, s.name, s.expires_on, s.covered_services, "
    "  coalesce((select sum(e.quantity) from memberships.credit_entry e where e.holder_id = s.id), 0) as balance "
    "from memberships.sold_package s ")


def _package_facts(rows: list[repo.Row]) -> tuple[access.PackageFact, ...]:
    return tuple(access.PackageFact(
        id=str(r["id"]), name=r["name"], balance=Decimal(r["balance"]), expires_on=r["expires_on"],
        pays_for_entry=(not r["covered_services"] or ENTRY_SERVICE in r["covered_services"])) for r in rows)


def _facts(session: Session, profile: repo.Row, branch_id: UUID, moment: datetime, settings: repo.Row) -> access.Facts:
    zone = company_zone(session, profile["company_id"])
    local = moment.astimezone(zone)
    customer_id = profile["customer_id"]
    members = repo.many(session, MEMBERSHIP_SQL + "where m.customer_id = :c order by (m.status = 'active') desc, "
                                                  "m.start_date desc limit 6", c=customer_id)
    packs = repo.many(session, PACKAGE_SQL + "where s.customer_id = :c and s.status = 'active'", c=customer_id)
    counted = repo.one(session, "select 1 as x from memberships.checkin where customer_id = :c and business_date = :d "
                                "and counted", c=customer_id, d=local.date()) is not None
    needs_waiver = bool(settings["waiver_required"])
    dob = profile["date_of_birth"]
    return access.Facts(
        today=local.date(), local_time=local.time().replace(second=0, microsecond=0), weekday=local.weekday(),
        branch_id=str(branch_id), blocked=bool(profile["access_blocked"]), block_reason=profile["block_reason"],
        waiver_required=needs_waiver,
        waiver_accepted=(not needs_waiver) or waivers.accepted_current(session, profile["company_id"], customer_id),
        memberships=_membership_facts(members), packages=_package_facts(packs),
        grace_days=int(settings["grace_days"]), expiry_warning_days=int(settings["expiry_warning_days"]),
        counted_today=counted, birthday=bool(dob and (dob.month, dob.day) == (local.month, local.day)))


def decide_for(session: Session, profile: repo.Row, branch_id: UUID, moment: datetime | None = None) -> access.Decision:
    """The decision for a member at a branch now, without recording anything."""
    settings = repo.get_settings(session, profile["company_id"])
    return access.decide(_facts(session, profile, branch_id, moment or datetime.now(UTC), settings))


# --------------------------------------------------------------------------- recording
def _owed(session: Session, customer_id: UUID) -> Decimal:
    return Decimal(repo.scalar(
        session, "select coalesce(sum(outstanding), 0) from memberships.invoice_run where status = 'issued' "
                 "and settle_state = 'open' and invoice_id is not null and customer_id = :c", c=customer_id))


def _payload(profile: repo.Row | None, decision: access.Decision, **extra: Any) -> dict[str, Any]:
    return {"outcome": decision.outcome, "allowed": decision.allowed, "code": decision.code,
            "message": decision.headline, "reasons": [r.as_dict() for r in decision.reasons],
            "member_number": profile["number"] if profile else None, **extra}


def _take_visit(session: Session, holder_id: UUID, customer_id: UUID, checkin_id: UUID, company_id: UUID,
                day: date) -> UUID | None:
    """Take one visit from a package, once, safe against two desks at the same moment (the package row is locked and
    the balance read again). Returns the ledger entry, or None when the package no longer has a visit."""
    sold = repo.get(session, "sold_package", holder_id, lock=True)
    if sold is None or sold["status"] != "active" or (sold["expires_on"] is not None and sold["expires_on"] < day):
        return None
    if repo.holder_balance(session, holder_id) < 1:
        return None
    entry = credits.add_unchecked(session, sold, credits.PACKAGE, "use", Decimal(-1), source_type="checkin",
                                  source_id=checkin_id, day=day, note="Visit")
    audit_record(session, "visit", "memberships.sold_package", holder_id, {"checkin": str(checkin_id)})
    made: UUID = entry["id"]
    return made


def check_in(session: Session, *, company_id: UUID, branch_id: UUID, identifier: str | None = None,
             customer_id: UUID | None = None, method: str = "desk", device: str | None = None,
             local_id: str | None = None, override_reason: str | None = None, record: bool = True,
             occurred_at: datetime | None = None, offline: bool = False) -> Result:
    """Decide and record an entry. Give the `identifier` (member number, card, QR text) or the `customer_id` the desk
    picked. `record=False` only asks (a door controller that logs elsewhere). With `override_reason` a refused person is
    let in by someone holding 'memberships.override'. A repeated `local_id` returns the first result. Needs
    'memberships.checkin' at the branch."""
    ctx = current_context()
    ctx.require(CHECKIN, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    if method not in METHODS:
        raise ValidationFailed("Method must be one of: " + ", ".join(METHODS))
    key = (local_id or "").strip()[:80] or None
    if key:
        old = repo.one(session, "select * from memberships.checkin where company_id = :c and local_id = :l",
                       c=company_id, l=key)
        if old is not None:
            return _replay(session, old)
    profile: repo.Row | None = None
    if customer_id is not None:
        found = common.customer_of_any(session, customer_id)
        if found.company_id != company_id:
            raise ValidationFailed("That customer belongs to another company")
        profile = profiles.ensure_profile(session, company_id, customer_id, branch_id=branch_id)
    elif identifier:
        profile = resolve(session, company_id, identifier)
    if profile is None:
        miss = access.Decision(access.DENY, (access.Reason(access.NOT_FOUND, "Nobody has this number or card",
                                                           access.DENY),))
        return Result(miss, None, None, message=miss.headline)
    moment = occurred_at or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if moment > datetime.now(UTC) + timedelta(minutes=10):
        raise ValidationFailed("A check-in cannot be in the future")
    repo.scalar(session, "select cast(pg_advisory_xact_lock(hashtextextended(:k, 0)) as text)",
                k=f"checkin:{profile['customer_id']}")
    settings = repo.get_settings(session, company_id)
    window = int(settings["repeat_window_minutes"])
    if record and window > 0 and not offline:
        again = repo.one(
            session, "select * from memberships.checkin where customer_id = :c and branch_id = :b and decision <> 'deny' "  # noqa: E501
                     "and occurred_at >= :since order by occurred_at desc limit 1",
            c=profile["customer_id"], b=branch_id, since=moment - timedelta(minutes=window))
        if again is not None:
            return _replay(session, again, duplicate=True)
    facts = _facts(session, profile, branch_id, moment, settings)
    decision = access.decide(facts)
    overridden = False
    if override_reason is not None and override_reason.strip() and decision.outcome == access.DENY:
        ctx.require(OVERRIDE, company_id=company_id, branch_id=branch_id)
        overridden = True
    elif override_reason is not None and not override_reason.strip():
        raise ValidationFailed("Say why the person is let in")
    allowed = decision.allowed or overridden or offline
    owed = _owed(session, profile["customer_id"])
    if not record:
        return Result(decision, profile, None, owed=owed, message=decision.headline)
    day = facts.today
    counted = allowed and not facts.counted_today
    new_id = uuid4()
    holder_type, holder_id = "none", None
    if allowed and decision.entitlement is not None:
        holder_type, holder_id = decision.entitlement.holder_type, UUID(decision.entitlement.holder_id)
    if counted and holder_type == "package" and holder_id is not None and decision.entitlement is not None \
            and decision.entitlement.consumes > 0 \
            and _take_visit(session, holder_id, profile["customer_id"], new_id, company_id, day) is None:
        decision = access.Decision(access.DENY, (access.Reason(access.NO_CREDITS, "The last visit was just used",
                                                               access.DENY),))
        allowed = overridden or offline
        counted = allowed
        holder_type, holder_id = "none", None
    row = repo.insert(session, "checkin", {
        "id": new_id, "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id,
        "branch_id": branch_id, "customer_id": profile["customer_id"],
        "member_id": UUID(decision.member_id) if decision.member_id else None, "holder_type": holder_type,
        "holder_id": holder_id, "local_id": key, "occurred_at": moment, "business_date": day, "method": method,
        "identifier": (clean_identifier(identifier)[:60] if identifier else None), "device": (device or "")[:80] or None,  # noqa: E501
        "decision": decision.outcome, "reasons": [r.as_dict() for r in decision.reasons], "overridden": overridden,
        "override_reason": override_reason.strip()[:300] if overridden and override_reason else None,
        "counted": counted, "offline": offline})
    if allowed:
        repo.update(session, "profile", profile["id"], {"last_visit_on": day, "last_visit_at": moment,
                                                        "inactive_notice_for": None})
    if overridden:
        audit_record(session, "override", "memberships.checkin", new_id,
                     {"customer": str(profile["customer_id"]), "reason": override_reason,
                      "was": [r.code for r in decision.reasons]})
    if offline and not (decision.allowed):
        flag_for_review(session, unit="memberships", kind="offline_checkin_refused", severity="low",
                        company_id=company_id, branch_id=branch_id, ref_type="memberships.checkin", ref_id=new_id,
                        message=f"{profile['number']} was let in while the desk was offline, but the server would have "
                                f"refused: {decision.headline}", dedupe_key=f"memberships-offline:{new_id}")
    publish(session, Event("checkin.recorded", "memberships.checkin", new_id, {
        "company_id": company_id, "branch_id": branch_id, "customer_id": profile["customer_id"],
        "member_number": profile["number"], "decision": decision.outcome, "code": decision.code, "method": method,
        "device": device, "overridden": overridden, "offline": offline, "counted": counted}))
    left = repo.holder_balance(session, holder_id) if holder_type == "package" and holder_id else None
    return Result(decision, profile, row, overridden=overridden, owed=owed, credits_left=left,
                  message=decision.headline)


def _replay(session: Session, old: repo.Row, duplicate: bool = False) -> Result:
    """The answer already given for this person/visit."""
    profile = repo.one(session, "select * from memberships.profile where customer_id = :c", c=old["customer_id"])
    reasons = tuple(access.Reason(r["code"], r["message"], r.get("level", "info")) for r in (old["reasons"] or []))
    if duplicate and not any(r.code == access.ALREADY_IN for r in reasons):
        reasons += (access.Reason(access.ALREADY_IN, "Already checked in a moment ago", "info"),)
    decision = access.Decision(old["decision"], reasons)
    left = repo.holder_balance(session, old["holder_id"]) if old["holder_type"] == "package" and old["holder_id"] else None  # noqa: E501
    return Result(decision, profile, old, duplicate=duplicate, overridden=bool(old["overridden"]),
                  owed=_owed(session, old["customer_id"]), credits_left=left, message=decision.headline)


def give_back_visit(session: Session, checkin_id: UUID, reason: str) -> Decimal:
    """A visit was taken by mistake: put it back on the package (once). Needs 'memberships.manage'."""
    row = common.get_row(session, "checkin", checkin_id, "Check-in")
    common.require(MANAGE, row["company_id"], row["branch_id"])
    if not reason.strip():
        raise ValidationFailed("Say why the visit is given back")
    back = credits.release(session, source_type="checkin", source_id=checkin_id)
    audit_record(session, "give_back", "memberships.checkin", checkin_id, {"reason": reason, "visits": str(back)})
    return back


# --------------------------------------------------------------------------- lists
def recent(session: Session, *, company_id: UUID, branch_id: UUID | None = None, customer_id: UUID | None = None,
           decision: str | None = None, limit: int = 50, offset: int = 0) -> list[repo.Row]:
    clause, params = repo.scope_sql(common.view_scopes(), "k")
    rows = repo.many(
        session,
        f"select k.* from memberships.checkin k where {clause} and k.company_id = :c "
        "and (cast(:b as uuid) is null or k.branch_id = :b) and (cast(:cu as uuid) is null or k.customer_id = :cu) "
        "and (cast(:d as text) is null or k.decision = :d) order by k.occurred_at desc limit :l offset :o",
        c=company_id, b=branch_id, cu=customer_id, d=decision, l=min(limit, 200), o=offset, **params)
    names = common.customer_names(session, {r["customer_id"] for r in rows})
    numbers = {p["customer_id"]: p["number"] for p in repo.many(
        session, "select customer_id, number from memberships.profile where customer_id = any(cast(:ids as uuid[]))",
        ids=[str(r["customer_id"]) for r in rows])}
    return [{**r, "customer_name": names[r["customer_id"]].name if r["customer_id"] in names else None,
             "member_number": numbers.get(r["customer_id"])} for r in rows]


def today_counts(session: Session, company_id: UUID, branch_id: UUID | None, day: date) -> dict[str, int]:
    row = repo.one(session, "select count(*) filter (where counted) as visits, "
                            "count(*) filter (where decision = 'deny' and not overridden) as refused, "
                            "count(*) filter (where overridden) as overridden from memberships.checkin "
                            "where company_id = :c and business_date = :d and (cast(:b as uuid) is null "
                            "or branch_id = :b)", c=company_id, d=day, b=branch_id)
    return {k: int(v) for k, v in (row or {}).items()}


# --------------------------------------------------------------------------- roster (offline desks, door controllers)
def roster(session: Session, *, company_id: UUID, branch_id: UUID, with_names: bool = True,
           moment: datetime | None = None) -> list[dict[str, Any]]:
    """Everyone who has a way in or had one recently, with today's decision for this branch: for a desk that must keep
    working without the network, or a controller that keeps its own list. Worked out in bulk (a few queries, however
    many
    members). The decision is for the day it is fetched and `valid_until` says how long the desk may trust it."""
    ctx = current_context()
    ctx.require(CHECKIN, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    now = moment or datetime.now(UTC)
    zone = company_zone(session, company_id)
    local = now.astimezone(zone)
    settings = repo.get_settings(session, company_id)
    needs_waiver = bool(settings["waiver_required"])
    people = repo.many(
        session,
        "select p.* from memberships.profile p where p.company_id = :c and (exists (select 1 from memberships.member m "
        "where m.customer_id = p.customer_id and m.status in ('active', 'paused', 'frozen')) or exists (select 1 from "
        "memberships.sold_package s where s.customer_id = p.customer_id and s.status = 'active') "
        "or p.access_blocked or p.lifecycle = 'former' and p.last_visit_on >= :recent) order by p.number",
        c=company_id, recent=local.date() - timedelta(days=60))
    ids = [str(p["customer_id"]) for p in people]
    by_member: dict[UUID, list[repo.Row]] = {}
    for r in repo.many(session, MEMBERSHIP_SQL + "where m.customer_id = any(cast(:ids as uuid[])) "
                                                  "order by (m.status = 'active') desc, m.start_date desc", ids=ids):
        by_member.setdefault(r["customer_id"], []).append(r)
    by_pack: dict[UUID, list[repo.Row]] = {}
    for r in repo.many(session, PACKAGE_SQL + "where s.customer_id = any(cast(:ids as uuid[])) and s.status = 'active'",
                       ids=ids):
        by_pack.setdefault(r["customer_id"], []).append(r)
    counted = {r["customer_id"] for r in repo.many(
        session, "select customer_id from memberships.checkin where company_id = :c and business_date = :d and counted",
        c=company_id, d=local.date())}
    current = repo.one(session, "select id from memberships.waiver_version where company_id = :c "
                                "order by version desc limit 1", c=company_id)
    signed = {r["customer_id"] for r in repo.many(
        session, "select customer_id from memberships.waiver_acceptance where version_id = :v",
        v=current["id"] if current else None)} if (needs_waiver and current) else None
    names = common.customer_names(session, {p["customer_id"] for p in people}) if with_names else {}
    out: list[dict[str, Any]] = []
    for p in people:
        dob = p["date_of_birth"]
        facts = access.Facts(
            today=local.date(), local_time=local.time().replace(second=0, microsecond=0), weekday=local.weekday(),
            branch_id=str(branch_id), blocked=bool(p["access_blocked"]), block_reason=p["block_reason"],
            waiver_required=needs_waiver and current is not None,
            waiver_accepted=signed is None or p["customer_id"] in signed,
            memberships=_membership_facts(by_member.get(p["customer_id"], [])[:6]),
            packages=_package_facts(by_pack.get(p["customer_id"], [])),
            grace_days=int(settings["grace_days"]), expiry_warning_days=int(settings["expiry_warning_days"]),
            counted_today=p["customer_id"] in counted,
            birthday=bool(dob and (dob.month, dob.day) == (local.month, local.day)))
        d = access.decide(facts)
        entry = {"number": p["number"], "card_number": p["card_number"], "outcome": d.outcome, "code": d.code,
                 "message": d.headline, "plan": d.entitlement.label if d.entitlement else None}
        if with_names:
            c = names.get(p["customer_id"])
            entry.update({"customer_id": str(p["customer_id"]), "name": c.name if c else None,
                          "phone": c.phone if c else None, "photo_file_id": str(p["photo_file_id"])
                          if p["photo_file_id"] else None})
        out.append(entry)
    return out

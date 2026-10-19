"""HTTP endpoints for members' profiles, households, waivers, price changes, plan changes, dues, check-in and the access
decision API. Routes only convert HTTP to service calls."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from ziira.modules.memberships.api import schemas as sc
from ziira.modules.memberships.api import schemas_gym as gs
from ziira.modules.memberships.api.deps import (
    ADJUST,
    CATALOGUE,
    DESK,
    SEE,
    SERVE,
    one_named,
)
from ziira.modules.memberships.permissions import MANAGE, OVERRIDE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import (
    changes,
    checkin,
    common,
    dues,
    holds,
    plans,
    profiles,
    settings,
    waivers,
)
from ziira.sdk import DB_SESSION, Session, ValidationFailed, current_context, files, page_limit, page_offset

router = APIRouter()
CREATED = status.HTTP_201_CREATED


# --------------------------------------------------------------------------- profiles
@router.get("/profiles", response_model=list[gs.MemberProfileOut], dependencies=SEE)
def get_profiles(company_id: UUID, search: str | None = Query(default=None, max_length=80),
                 lifecycle: str | None = None, group_id: UUID | None = None, limit: int = page_limit(50),
                 offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return profiles.list_profiles(session, company_id=company_id, search=search, lifecycle=lifecycle,
                                  group_id=group_id, limit=limit, offset=offset)


@router.get("/profiles/by-customer/{customer_id}", response_model=gs.MemberProfileOut, dependencies=SEE)
def get_profile(customer_id: UUID, session: Session = DB_SESSION) -> object:
    return profiles.with_customer(session, [profiles.profile_of_customer(session, customer_id)])[0]


@router.patch("/profiles/by-customer/{customer_id}", response_model=gs.MemberProfileOut, dependencies=SERVE)
def patch_profile(customer_id: UUID, body: gs.MemberProfileUpdate, session: Session = DB_SESSION) -> object:
    saved = profiles.update_profile(session, customer_id, **body.model_dump(exclude_unset=True))
    return profiles.with_customer(session, [saved])[0]


@router.post("/profiles/by-customer/{customer_id}/block", response_model=gs.MemberProfileOut, dependencies=SERVE)
def post_block(customer_id: UUID, body: gs.MemberProfileBlockIn, session: Session = DB_SESSION) -> object:
    saved = profiles.set_block(session, customer_id, blocked=body.blocked, reason=body.reason)
    return profiles.with_customer(session, [saved])[0]


@router.put("/profiles/by-customer/{customer_id}/group", response_model=gs.MemberProfileOut, dependencies=SERVE)
def put_profile_group(customer_id: UUID, body: gs.MemberGroupSetIn, session: Session = DB_SESSION) -> object:
    return profiles.with_customer(session, [profiles.set_group(session, customer_id, body.group_id)])[0]


@router.get("/groups", response_model=list[gs.MemberGroupOut], dependencies=SEE)
def get_groups(company_id: UUID, limit: int = page_limit(100), offset: int = page_offset(),
               session: Session = DB_SESSION) -> object:
    return profiles.list_groups(session, company_id, limit, offset)


@router.post("/groups", response_model=gs.MemberGroupOut, status_code=CREATED, dependencies=SERVE)
def post_group(body: gs.MemberGroupIn, session: Session = DB_SESSION) -> object:
    return profiles.get_group(session, profiles.create_group(session, **body.model_dump())["id"])


@router.get("/groups/{group_id}", response_model=gs.MemberGroupOut, dependencies=SEE)
def get_group(group_id: UUID, session: Session = DB_SESSION) -> object:
    return profiles.get_group(session, group_id)


@router.patch("/groups/{group_id}", response_model=gs.MemberGroupOut, dependencies=SERVE)
def patch_group(group_id: UUID, body: gs.MemberGroupUpdate, session: Session = DB_SESSION) -> object:
    profiles.update_group(session, group_id, **body.model_dump(exclude_unset=True))
    return profiles.get_group(session, group_id)


# --------------------------------------------------------------------------- waiver
@router.get("/waiver/versions", response_model=list[gs.WaiverVersionOut], dependencies=SEE)
def get_waiver_versions(company_id: UUID, session: Session = DB_SESSION) -> object:
    return waivers.list_versions(session, company_id)


@router.post("/waiver/versions", response_model=gs.WaiverVersionOut, status_code=CREATED, dependencies=CATALOGUE)
def post_waiver_version(body: gs.WaiverVersionIn, session: Session = DB_SESSION) -> object:
    return waivers.publish_version(session, **body.model_dump())


@router.get("/customers/{customer_id}/waiver", response_model=gs.WaiverStatusOut, dependencies=SEE)
def get_customer_waiver(customer_id: UUID, session: Session = DB_SESSION) -> object:
    return waivers.status_of(session, customer_id)


@router.post("/customers/{customer_id}/waiver", response_model=gs.WaiverAcceptanceOut, status_code=CREATED,
             dependencies=SERVE)
def post_customer_waiver(customer_id: UUID, body: gs.WaiverAcceptIn, session: Session = DB_SESSION) -> object:
    made = waivers.accept(session, customer_id, **body.model_dump())
    return {**made, "recorded_by_name": None}


# --------------------------------------------------------------------------- price changes, plan changes, holds
@router.get("/plans/{plan_id}/price-changes", response_model=list[sc.MembershipPriceChangeOut], dependencies=SEE)
def get_price_changes(plan_id: UUID, session: Session = DB_SESSION) -> object:
    return plans.list_price_changes(session, plan_id)


@router.post("/plans/{plan_id}/price-changes", response_model=sc.MembershipPriceChangeOut, status_code=CREATED,
             dependencies=CATALOGUE)
def post_price_change(plan_id: UUID, body: sc.MembershipPriceChangeIn, session: Session = DB_SESSION) -> object:
    return plans.schedule_price_change(session, plan_id, **body.model_dump())


@router.post("/price-changes/{change_id}/cancel", response_model=sc.MembershipPriceChangeOut, dependencies=CATALOGUE)
def post_cancel_price_change(change_id: UUID, session: Session = DB_SESSION) -> object:
    return plans.cancel_price_change(session, change_id)


@router.get("/members/{member_id}/change-quote", response_model=sc.MembershipPlanChangeQuoteOut, dependencies=SEE)
def get_change_quote(member_id: UUID, plan_id: UUID, session: Session = DB_SESSION) -> object:
    return changes.quote(session, member_id, plan_id)


@router.post("/members/{member_id}/change-plan", response_model=sc.MembershipOut, dependencies=SERVE)
def post_change_plan(member_id: UUID, body: sc.MembershipPlanChangeIn, session: Session = DB_SESSION) -> object:
    return one_named(session, changes.change_plan(session, member_id, body.plan_id, when=body.when, note=body.note))


@router.post("/members/{member_id}/undo-plan-change", response_model=sc.MembershipOut, dependencies=SERVE)
def post_undo_plan_change(member_id: UUID, session: Session = DB_SESSION) -> object:
    return one_named(session, changes.undo_pending(session, member_id))


@router.get("/members/{member_id}/freezes", response_model=list[sc.MembershipFreezeOut], dependencies=SEE)
def get_freezes(member_id: UUID, session: Session = DB_SESSION) -> object:
    return holds.history(session, member_id)


@router.get("/members/{member_id}/freeze-allowance", response_model=sc.MembershipAllowanceOut, dependencies=SEE)
def get_freeze_allowance(member_id: UUID, session: Session = DB_SESSION) -> object:
    member = common.get_row(session, "member", member_id, "Membership")
    return holds.allowance(session, member, common.today(session, member["company_id"]))


# --------------------------------------------------------------------------- dues
@router.get("/members/{member_id}/dues", response_model=list[gs.MemberDueOut], dependencies=SEE)
def get_member_dues(member_id: UUID, session: Session = DB_SESSION) -> object:
    return dues.member_dues(session, member_id)


@router.post("/members/{member_id}/payments", response_model=gs.MemberPaymentOut, status_code=CREATED,
             dependencies=SERVE)
def post_member_payment(member_id: UUID, body: gs.MemberPaymentIn, session: Session = DB_SESSION) -> object:
    return dues.take_payment(session, member_id, **body.model_dump())


@router.get("/arrears", response_model=list[gs.ArrearsOut], dependencies=SEE)
def get_arrears(company_id: UUID, min_days: int = Query(default=1, ge=0, le=3650), limit: int = page_limit(100),
                offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return dues.arrears(session, company_id=company_id, min_days=min_days, limit=limit, offset=offset)


@router.post("/invoice-runs/{run_id}/credit", response_model=gs.InvoiceCreditOut, dependencies=ADJUST)
def post_run_credit(run_id: UUID, body: gs.InvoiceCreditIn, session: Session = DB_SESSION) -> object:
    """Write off an invoice (credit note) or refund it (cash or mobile money once paid), in whole or in part."""
    return dues.credit_run(session, run_id, **body.model_dump())


@router.post("/invoice-runs/{run_id}/dunning", response_model=sc.InvoiceRunOut, dependencies=SERVE)
def post_run_dunning(run_id: UUID, body: gs.DunningPauseIn, session: Session = DB_SESSION) -> object:
    return one_named(session, dues.set_dunning_paused(session, run_id, body.paused))


@router.post("/dues/refresh", response_model=gs.DuesRefreshOut, dependencies=SERVE)
def post_dues_refresh(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Read the company's open invoices again now (the hourly task does this too)."""
    common.require(MANAGE, company_id)
    today = common.today(session, company_id)
    changed = dues.refresh_runs(session, company_id, today=today)
    frozen = dues.apply_arrears_holds(session, company_id, today)
    resumed = dues.release_arrears_holds(session, company_id)
    return {"changed": changed, "frozen": frozen, "resumed": resumed, "reminders_queued": 0}


# --------------------------------------------------------------------------- check-in
def _person(session: Session, res: checkin.Result) -> dict[str, Any] | None:
    if res.profile is None:
        return None
    p = res.profile
    names = common.customer_names(session, {p["customer_id"]})
    c = names.get(p["customer_id"])
    stand = checkin.standings(session, [p["customer_id"]]).get(p["customer_id"], {})
    photo = None
    if p["photo_file_id"]:
        try:
            photo = files.signed_link(session, p["photo_file_id"], "thumb", seconds=600).path
        except Exception:  # noqa: BLE001 - a missing picture must not stop a check-in
            photo = None
    return {"customer_id": p["customer_id"], "profile_id": p["id"], "number": p["number"], "photo_link": photo,
            "name": c.name if c else None, "phone": c.phone if c else None, "photo_file_id": p["photo_file_id"],
            "lifecycle": p["lifecycle"], "plan_name": stand.get("plan_name"),
            "membership_status": stand.get("membership_status"), "next_renewal_date": stand.get("next_renewal_date"),
            "owed": res.owed}


def result_out(session: Session, res: checkin.Result) -> dict[str, Any]:
    ctx = current_context()
    company_id = res.profile["company_id"] if res.profile else None
    can_override = (res.decision.outcome == "deny" and res.profile is not None and not res.overridden
                    and ctx.can(OVERRIDE, company_id=company_id))
    classes: list[dict[str, Any]] = []
    return {"outcome": res.decision.outcome, "allowed": res.decision.allowed or res.overridden,
            "code": res.decision.code, "message": res.message,
            "reasons": [r.as_dict() for r in res.decision.reasons], "duplicate": res.duplicate,
            "overridden": res.overridden, "can_override": can_override,
            "checkin_id": res.checkin["id"] if res.checkin else None,
            "occurred_at": res.checkin["occurred_at"] if res.checkin else None,
            "entitlement": res.decision.entitlement.label if res.decision.entitlement else None,
            "credits_left": res.credits_left, "person": _person(session, res), "classes_today": classes}


@router.get("/checkin/search", response_model=list[gs.CheckinSearchOut], dependencies=DESK)
def get_checkin_search(company_id: UUID, q: str = Query(min_length=1, max_length=80),
                       session: Session = DB_SESSION) -> object:
    common.require_in_company("memberships.checkin", company_id)
    return [{"customer_id": r["customer_id"], "number": r["number"], "name": r.get("customer_name"),
             "phone": r.get("phone"), "photo_file_id": r["photo_file_id"], "plan_name": r.get("plan_name"),
             "membership_status": r.get("membership_status"), "arrears": r.get("arrears"),
             "next_renewal_date": r.get("next_renewal_date")} for r in checkin.search(session, company_id, q)]


@router.post("/checkin", response_model=gs.CheckinResultOut, dependencies=DESK)
def post_checkin(body: gs.CheckinIn, session: Session = DB_SESSION) -> object:
    """Decide whether the person may come in and record it. The answer is `allow`, `warn` (in, but see the reasons) or
    `deny`; a refused person is let in only with `override_reason` by someone holding the override right."""
    res = checkin.check_in(session, company_id=body.company_id, branch_id=body.branch_id, identifier=body.identifier,
                           customer_id=body.customer_id, method=body.method, device=body.device,
                           local_id=body.local_id, override_reason=body.override_reason, record=body.record)
    return result_out(session, res)


@router.post("/checkin/sync", response_model=gs.CheckinSyncOut, dependencies=DESK)
def post_checkin_sync(body: gs.CheckinSyncIn, session: Session = DB_SESSION) -> object:
    """Record check-ins a desk made while it was offline. Each carries the client's own id (a repeat records nothing
    new) and the moment it happened. Anyone the server would have refused is recorded and put in the exceptions
    inbox."""
    out: list[dict[str, Any]] = []
    for item in body.items:
        try:
            with session.begin_nested():
                res = checkin.check_in(
                    session, company_id=body.company_id, branch_id=body.branch_id, identifier=item.identifier,
                    customer_id=item.customer_id, method=item.method, device=item.device, local_id=item.local_id,
                    occurred_at=item.occurred_at, offline=True)
            out.append({"local_id": item.local_id, "outcome": res.decision.outcome, "code": res.decision.code,
                        "message": res.message, "recorded": res.checkin is not None})
        except ValidationFailed as error:
            out.append({"local_id": item.local_id, "outcome": "deny", "code": "invalid", "message": str(error),
                        "recorded": False})
    return {"results": out}


@router.get("/checkin/recent", response_model=list[gs.CheckinRowOut], dependencies=SEE)
def get_checkin_recent(company_id: UUID, branch_id: UUID | None = None, customer_id: UUID | None = None,
                       decision: str | None = Query(default=None, pattern="^(allow|warn|deny)$"),
                       limit: int = page_limit(50), offset: int = page_offset(),
                       session: Session = DB_SESSION) -> object:
    return checkin.recent(session, company_id=company_id, branch_id=branch_id, customer_id=customer_id,
                          decision=decision, limit=limit, offset=offset)


@router.get("/checkin/today", response_model=gs.CheckinCountsOut, dependencies=SEE)
def get_checkin_today(company_id: UUID, branch_id: UUID | None = None, session: Session = DB_SESSION) -> object:
    common.check_visible(company_id, branch_id, "Company")
    return checkin.today_counts(session, company_id, branch_id, common.today(session, company_id))


@router.get("/checkin/roster", response_model=gs.RosterOut, dependencies=DESK)
def get_roster(company_id: UUID, branch_id: UUID, session: Session = DB_SESSION) -> object:
    """Everyone who may have a way in, with today's decision, for a desk to keep working offline."""
    entries = checkin.roster(session, company_id=company_id, branch_id=branch_id, with_names=True)
    hours = int(settings.get_settings(session, company_id)["offline_valid_hours"])
    return {"generated_at": datetime.now(UTC), "valid_hours": hours, "branch_id": branch_id, "entries": entries}


@router.post("/checkins/{checkin_id}/give-back", response_model=gs.CheckinGiveBackOut, dependencies=SERVE)
def post_give_back(checkin_id: UUID, body: gs.CheckinGiveBackIn, session: Session = DB_SESSION) -> object:
    return {"visits_given_back": checkin.give_back_visit(session, checkin_id, body.reason)}


# --------------------------------------------------------------------------- access decision API (public API, API key)
@router.post("/access/decision", response_model=gs.AccessDecisionOut, dependencies=DESK)
def post_access_decision(body: gs.AccessDecisionIn, session: Session = DB_SESSION) -> object:
    """May the member with this number, card or QR text enter this branch now? For a door or turnstile controller: it
    sends what it read and opens on `allowed`. Every answer is recorded (use `record: false` for a dry run) and
    published
    as `checkin.recorded`, so a business can follow entries with a webhook. Only the member number and first name
    leave."""
    branch = repo.one(session, "select company_id from kernel.branch where id = :b", b=body.branch_id)
    if branch is None:
        raise ValidationFailed("Branch not found")
    res = checkin.check_in(session, company_id=branch["company_id"], branch_id=body.branch_id, identifier=body.identifier,  # noqa: E501
                           method="api", device=body.device, local_id=body.local_id, record=body.record)
    first = None
    if res.profile is not None:
        names = common.customer_names(session, {res.profile["customer_id"]})
        c = names.get(res.profile["customer_id"])
        first = c.name.split()[0] if c and c.name.split() else None
    return {"allowed": res.decision.allowed, "decision": res.decision.outcome, "code": res.decision.code,
            "message": res.message, "member_number": res.profile["number"] if res.profile else None,
            "first_name": first, "checkin_id": res.checkin["id"] if res.checkin else None,
            "reasons": [r.as_dict() for r in res.decision.reasons]}


@router.get("/access/allowed", response_model=gs.AccessAllowedOut, dependencies=DESK)
def get_access_allowed(branch_id: UUID, session: Session = DB_SESSION) -> object:
    """The numbers and cards that may enter this branch right now, for a controller that keeps its own list. No
    names."""
    row = repo.one(session, "select company_id from kernel.branch where id = :b", b=branch_id)
    if row is None:
        raise ValidationFailed("Branch not found")
    entries = checkin.roster(session, company_id=row["company_id"], branch_id=branch_id, with_names=False)
    return {"generated_at": datetime.now(UTC), "branch_id": branch_id,
            "members": [e for e in entries if e["outcome"] in ("allow", "warn")]}


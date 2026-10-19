"""HTTP endpoints of the Memberships module. Routes only convert HTTP to service calls."""

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from ziira.modules.memberships.api import schemas as sc
from ziira.modules.memberships.api.deps import (
    ADJUST,
    CATALOGUE,
    RECUR,
    REVIEW,
    SEE,
    SERVE,
    named,
    one_named,
)
from ziira.modules.memberships.api.routes_extras import router as extras_router  # noqa: E402
from ziira.modules.memberships.api.routes_gym import router as gym_router  # noqa: E402
from ziira.modules.memberships.permissions import MANAGE
from ziira.modules.memberships.services import (
    billing,
    common,
    credits,
    holds,
    invoicing,
    members,
    overview,
    packages,
    plans,
    schedules,
    settings,
)
from ziira.sdk import DB_SESSION, Session, page_limit, page_offset

router = APIRouter()
router.include_router(gym_router)
router.include_router(extras_router)
CREATED = status.HTTP_201_CREATED


# --------------------------------------------------------------------------- overview and settings
@router.get("/summary", response_model=sc.MembershipSummaryOut, dependencies=SEE)
def get_summary(company_id: UUID | None = None, session: Session = DB_SESSION) -> object:
    return overview.summary(session, company_id)


@router.get("/setup-steps", response_model=list[sc.MembershipSetupStepOut], dependencies=SEE)
def get_setup_steps(company_id: UUID, session: Session = DB_SESSION) -> object:
    """The first-run checklist: which steps are done (plans priced, service items linked, terms, policies, a member,
    a check-in)."""
    return overview.setup_steps(session, company_id)


@router.get("/invoicing", response_model=sc.InvoicingAvailableOut, dependencies=SEE)
def get_invoicing(session: Session = DB_SESSION) -> object:
    """Whether invoices can be issued from here (Point of Sale and Invoices are on)."""
    return {"available": invoicing.available(session)}


@router.get("/settings", response_model=sc.MembershipSettingsOut, dependencies=SEE)
def get_settings(company_id: UUID, session: Session = DB_SESSION) -> object:
    return settings.get_settings(session, company_id)


@router.patch("/settings", response_model=sc.MembershipSettingsOut, dependencies=CATALOGUE)
def patch_settings(company_id: UUID, body: sc.MembershipSettingsUpdate, session: Session = DB_SESSION) -> object:
    return settings.update_settings(session, company_id, **body.model_dump(exclude_unset=True))


# --------------------------------------------------------------------------- plans and packages
@router.get("/plans", response_model=list[sc.MembershipPlanOut], dependencies=SEE)
def get_plans(company_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
              limit: int = page_limit(100), offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return plans.list_plans(session, company_id=company_id, status=status_, limit=limit, offset=offset)


@router.post("/plans", response_model=sc.MembershipPlanOut, status_code=CREATED, dependencies=CATALOGUE)
def post_plan(body: sc.MembershipPlanIn, session: Session = DB_SESSION) -> object:
    return plans.create_plan(session, **body.model_dump())


@router.get("/plans/{plan_id}", response_model=sc.MembershipPlanOut, dependencies=SEE)
def get_plan(plan_id: UUID, session: Session = DB_SESSION) -> object:
    return plans.get_plan(session, plan_id)


@router.patch("/plans/{plan_id}", response_model=sc.MembershipPlanOut, dependencies=CATALOGUE)
def patch_plan(plan_id: UUID, body: sc.MembershipPlanUpdate, session: Session = DB_SESSION) -> object:
    return plans.update_plan(session, plan_id, **body.model_dump(exclude_unset=True))


@router.get("/packages", response_model=list[sc.SessionPackageOut], dependencies=SEE)
def get_packages(company_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                 limit: int = page_limit(100), offset: int = page_offset(),
                 session: Session = DB_SESSION) -> object:
    return plans.list_packages(session, company_id=company_id, status=status_, limit=limit, offset=offset)


@router.post("/packages", response_model=sc.SessionPackageOut, status_code=CREATED, dependencies=CATALOGUE)
def post_package(body: sc.SessionPackageIn, session: Session = DB_SESSION) -> object:
    return plans.create_package(session, **body.model_dump())


@router.get("/packages/{package_id}", response_model=sc.SessionPackageOut, dependencies=SEE)
def get_package(package_id: UUID, session: Session = DB_SESSION) -> object:
    return plans.get_package(session, package_id)


@router.patch("/packages/{package_id}", response_model=sc.SessionPackageOut, dependencies=CATALOGUE)
def patch_package(package_id: UUID, body: sc.SessionPackageUpdate, session: Session = DB_SESSION) -> object:
    return plans.update_package(session, package_id, **body.model_dump(exclude_unset=True))


# --------------------------------------------------------------------------- members
@router.get("/members", response_model=list[sc.MembershipOut], dependencies=SEE)
def get_members(company_id: UUID | None = None, branch_id: UUID | None = None,
                status_: str | None = Query(default=None, alias="status"), plan_id: UUID | None = None,
                customer_id: UUID | None = None, renewing_from: date | None = None, renewing_to: date | None = None,
                past_due: bool | None = None, limit: int = page_limit(50), offset: int = page_offset(), session: Session = DB_SESSION) -> object:  # noqa: E501
    rows = members.list_members(session, company_id=company_id, branch_id=branch_id, status=status_, plan_id=plan_id,
                                customer_id=customer_id, renewing_from=renewing_from, renewing_to=renewing_to,
                                past_due=past_due, limit=limit, offset=offset)
    return named(session, rows)


@router.post("/members", response_model=sc.MembershipOut, status_code=CREATED, dependencies=SERVE)
def post_member(body: sc.MembershipSignUpIn, session: Session = DB_SESSION) -> object:
    return one_named(session, members.with_balance(session, [members.sign_up(session, **body.model_dump())])[0])


@router.get("/members/{member_id}", response_model=sc.MembershipOut, dependencies=SEE)
def get_member(member_id: UUID, session: Session = DB_SESSION) -> object:
    return one_named(session, members.get_member(session, member_id))


@router.patch("/members/{member_id}", response_model=sc.MembershipOut, dependencies=SERVE)
def patch_member(member_id: UUID, body: sc.MembershipUpdate, session: Session = DB_SESSION) -> object:
    return one_named(session, members.update_member(session, member_id, **body.model_dump(exclude_unset=True)))


@router.get("/members/{member_id}/history", response_model=list[sc.MembershipHistoryOut], dependencies=SEE)
def get_member_history(member_id: UUID, session: Session = DB_SESSION) -> object:
    return members.history(session, member_id)


@router.get("/members/{member_id}/credits", response_model=list[sc.CreditEntryOut], dependencies=SEE)
def get_member_credits(member_id: UUID, limit: int = page_limit(100), offset: int = page_offset(),
                       session: Session = DB_SESSION) -> object:
    members.get_member(session, member_id)
    return credits.ledger(session, member_id, limit=limit, offset=offset)


@router.post("/members/{member_id}/pause", response_model=sc.MembershipOut, dependencies=SERVE)
def post_pause(member_id: UUID, body: sc.MembershipHoldIn, session: Session = DB_SESSION) -> object:
    return one_named(session, members.with_balance(session, [holds.pause(session, member_id, **body.model_dump())])[0])


@router.post("/members/{member_id}/resume", response_model=sc.MembershipOut, dependencies=SERVE)
def post_resume(member_id: UUID, body: sc.MembershipResumeIn, session: Session = DB_SESSION) -> object:
    return one_named(session, members.with_balance(session, [holds.resume(session, member_id, note=body.note)])[0])


@router.post("/members/{member_id}/cancel", response_model=sc.MembershipOut, dependencies=SERVE)
def post_cancel(member_id: UUID, body: sc.MembershipCancelIn, session: Session = DB_SESSION) -> object:
    return one_named(session, members.cancel(session, member_id, **body.model_dump()))


@router.post("/members/{member_id}/undo-cancel", response_model=sc.MembershipOut, dependencies=SERVE)
def post_undo_cancel(member_id: UUID, session: Session = DB_SESSION) -> object:
    return one_named(session, members.undo_cancel(session, member_id))


# --------------------------------------------------------------------------- packages sold
@router.get("/sold-packages", response_model=list[sc.SoldPackageOut], dependencies=SEE)
def get_sold_packages(company_id: UUID | None = None, customer_id: UUID | None = None,
                      status_: str | None = Query(default=None, alias="status"), expiring_before: date | None = None,
                      limit: int = page_limit(50), offset: int = page_offset(),
                      session: Session = DB_SESSION) -> object:
    rows = packages.list_sold(session, company_id=company_id, customer_id=customer_id, status=status_,
                              expiring_before=expiring_before, limit=limit, offset=offset)
    return named(session, rows)


@router.post("/sold-packages", response_model=sc.SoldPackageOut, status_code=CREATED, dependencies=SERVE)
def post_sold_package(body: sc.SellPackageIn, session: Session = DB_SESSION) -> object:
    return one_named(session, packages.sell(session, **body.model_dump()))


@router.get("/sold-packages/{sold_id}", response_model=sc.SoldPackageOut, dependencies=SEE)
def get_sold_package(sold_id: UUID, session: Session = DB_SESSION) -> object:
    return one_named(session, packages.get_sold(session, sold_id))


@router.get("/sold-packages/{sold_id}/credits", response_model=list[sc.CreditEntryOut], dependencies=SEE)
def get_sold_package_credits(sold_id: UUID, limit: int = page_limit(100), offset: int = page_offset(),
                             session: Session = DB_SESSION) -> object:
    packages.get_sold(session, sold_id)
    return credits.ledger(session, sold_id, limit=limit, offset=offset)


@router.post("/sold-packages/{sold_id}/refund", response_model=sc.SoldPackageOut, dependencies=ADJUST)
def post_refund(sold_id: UUID, body: sc.PackageRefundIn, session: Session = DB_SESSION) -> object:
    return one_named(session, packages.refund(session, sold_id, body.note))


# --------------------------------------------------------------------------- credits
@router.get("/customers/{customer_id}/credits", response_model=sc.CustomerCreditsOut, dependencies=SEE)
def get_customer_credits(customer_id: UUID, session: Session = DB_SESSION) -> object:
    found: dict[str, Any] = credits.customer_summary(session, customer_id)
    return {**found, "memberships": named(session, found["memberships"]), "packages": named(session, found["packages"])}


@router.post("/credits/adjust", response_model=sc.CreditEntryOut, status_code=CREATED, dependencies=ADJUST)
def post_adjust(body: sc.CreditAdjustIn, session: Session = DB_SESSION) -> object:
    return credits.adjust(session, **body.model_dump())


@router.post("/credits/consume", response_model=sc.CreditConsumeOut, dependencies=SERVE)
def post_consume(body: sc.CreditConsumeIn, session: Session = DB_SESSION) -> object:
    """Spend credits for a service by hand. The same `source_id` spends them once, however often it is sent."""
    customer = common.customer_of_any(session, body.customer_id)
    common.require(MANAGE, customer.company_id)
    used = credits.consume(session, **body.model_dump())
    return {"covered": used.covered, "remaining": used.remaining, "discount_percent": used.discount_percent,
            "replayed": used.replayed,
            "covered_by": [{"holder_type": t, "holder_id": h, "quantity": q} for t, h, q in used.covered_by]}


@router.post("/credits/release", response_model=sc.CreditReleaseOut, dependencies=SERVE)
def post_release(body: sc.CreditReleaseIn, session: Session = DB_SESSION) -> object:
    return {"released": credits.release(session, **body.model_dump())}


# --------------------------------------------------------------------------- recurring invoices
@router.get("/recurring-invoices", response_model=list[sc.RecurringInvoiceOut], dependencies=SEE)
def get_schedules(company_id: UUID | None = None, customer_id: UUID | None = None,
                  status_: str | None = Query(default=None, alias="status"), limit: int = page_limit(50),
                  offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    rows = schedules.list_schedules(session, company_id=company_id, customer_id=customer_id, status=status_,
                                    limit=limit, offset=offset)
    return named(session, rows)


@router.post("/recurring-invoices", response_model=sc.RecurringInvoiceOut, status_code=CREATED, dependencies=RECUR)
def post_schedule(body: sc.RecurringInvoiceIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    return one_named(session, schedules.create_schedule(session, **data))


@router.get("/recurring-invoices/{schedule_id}", response_model=sc.RecurringInvoiceOut, dependencies=SEE)
def get_schedule(schedule_id: UUID, session: Session = DB_SESSION) -> object:
    return one_named(session, schedules.get_schedule(session, schedule_id))


@router.patch("/recurring-invoices/{schedule_id}", response_model=sc.RecurringInvoiceOut, dependencies=RECUR)
def patch_schedule(schedule_id: UUID, body: sc.RecurringInvoiceUpdate, session: Session = DB_SESSION) -> object:
    return one_named(session, schedules.update_schedule(session, schedule_id, **body.model_dump(exclude_unset=True)))


@router.post("/recurring-invoices/{schedule_id}/pause", response_model=sc.RecurringInvoiceOut, dependencies=RECUR)
def post_schedule_pause(schedule_id: UUID, body: sc.RecurringPauseIn, session: Session = DB_SESSION) -> object:
    return one_named(session, schedules.pause(session, schedule_id, body.resume_on))


@router.post("/recurring-invoices/{schedule_id}/resume", response_model=sc.RecurringInvoiceOut, dependencies=RECUR)
def post_schedule_resume(schedule_id: UUID, session: Session = DB_SESSION) -> object:
    return one_named(session, schedules.resume(session, schedule_id))


@router.post("/recurring-invoices/{schedule_id}/end", response_model=sc.RecurringInvoiceOut, dependencies=RECUR)
def post_schedule_end(schedule_id: UUID, session: Session = DB_SESSION) -> object:
    return one_named(session, schedules.end(session, schedule_id))


@router.post("/recurring-invoices/{schedule_id}/run", response_model=sc.RecurringInvoiceOut, dependencies=RECUR)
def post_schedule_run(schedule_id: UUID, session: Session = DB_SESSION) -> object:
    """Invoice the periods that are due now, instead of waiting for the next hourly run."""
    return one_named(session, schedules.run_now(session, schedule_id))


@router.get("/invoice-runs", response_model=list[sc.InvoiceRunOut], dependencies=SEE)
def get_runs(company_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
             owner_id: UUID | None = None, customer_id: UUID | None = None, limit: int = page_limit(50),
             offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    rows = billing.list_runs(session, company_id=company_id, status=status_, owner_id=owner_id,
                             customer_id=customer_id, limit=limit, offset=offset)
    return named(session, rows)


@router.get("/invoice-runs/{run_id}", response_model=sc.InvoiceRunOut, dependencies=SEE)
def get_run(run_id: UUID, session: Session = DB_SESSION) -> object:
    return one_named(session, billing.get_run(session, run_id))


@router.post("/invoice-runs/{run_id}/issue", response_model=sc.InvoiceRunOut, dependencies=REVIEW)
def post_run_issue(run_id: UUID, session: Session = DB_SESSION) -> object:
    """Issue the invoice of a draft, or try a failed one again."""
    return one_named(session, billing.issue_run(session, run_id))


@router.post("/invoice-runs/{run_id}/discard", response_model=sc.InvoiceRunOut, dependencies=REVIEW)
def post_run_discard(run_id: UUID, body: sc.InvoiceRunDiscardIn, session: Session = DB_SESSION) -> object:
    return one_named(session, billing.discard_run(session, run_id, body.note))

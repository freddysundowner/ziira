"""The Super Admin's platform endpoints (docs/platform-admin.md): dashboard, subscribers, plans and prices, add-ons,
coupons,
subscriptions, invoices and payments, plan requests, licences, platform settings and operators.

Same rules as the rest of the operator console: an operator token, a permission per route (`require(...)`, checked by
`tests/test_platform_roles.py`), a fresh second-factor code for every change, and a line in the operator trail."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from ziira.kernel import operators
from ziira.kernel.api import platform_schemas as sc
from ziira.kernel.api.operator_routes import require
from ziira.kernel.auth import client_ip
from ziira.kernel.platform import (
    admin,
    billing,
    dashboard,
    licences,
    permissions,
    plans,
    providers,
    settings,
    subscribers,
)
from ziira.kernel.platform import entitlements as ent

router = APIRouter(prefix="/api/v1/operator", tags=["Super Admin"])
Op = operators.Operator


def _ip(request: Request) -> str | None:
    return client_ip(request)


# --------------------------------------------------------------------------- dashboard, roles, settings
@router.get("/dashboard", response_model=sc.DashboardOut)
def get_dashboard(_: Op = Depends(require("platform.view"))) -> object:
    """Recurring revenue (per currency), trials, churn, money overdue and what needs attention."""
    return dashboard.overview()


@router.get("/roles", response_model=sc.RolesOut)
def roles(_: Op = Depends(require("platform.view"))) -> object:
    """The operator roles and what each may do."""
    return {
        "roles": [{"role": r, "permissions": sorted(p)} for r, p in permissions.ROLES.items()],
        "permissions": permissions.PERMISSIONS,
    }


@router.get("/platform-settings", response_model=sc.SettingsOut)
def platform_settings(_: Op = Depends(require("platform.view"))) -> object:
    """Vendor details, tax lines, payment instructions, dunning, proration, retention and the default plan."""
    return {"values": settings.get_all(), "providers": providers.names(), "mode": ent.mode()}


@router.put("/platform-settings/{key}")
def put_setting(
    key: str, body: sc.SettingIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    return {"key": key, "value": admin.set_setting(operator, key, body.value, _ip(request))}


# --------------------------------------------------------------------------- plans
@router.get("/plans", response_model=list[sc.PlatformPlanOut])
def list_plans(_: Op = Depends(require("platform.view"))) -> object:
    return plans.list_plans()


@router.post("/plans", response_model=sc.PlanDetail, status_code=201)
def create_plan(body: sc.PlanIn, request: Request, operator: Op = Depends(require("platform.plans"))) -> object:
    return admin.create_plan(operator, body.model_dump(), _ip(request))


@router.get("/plans/{code}", response_model=sc.PlanDetail)
def get_plan(code: str, _: Op = Depends(require("platform.view"))) -> object:
    return admin.plan_detail(code)


@router.patch("/plans/{code}", response_model=sc.PlanDetail)
def patch_plan(
    code: str, body: sc.PlanPatch, request: Request, operator: Op = Depends(require("platform.plans"))
) -> object:
    """Change a plan. Subscribers keep the units and limits they were sold; sync one from its page to move it over."""
    return admin.update_plan(operator, code, body.model_dump(exclude_unset=True), _ip(request))


@router.post("/plans/{code}/prices", response_model=sc.PlanDetail, status_code=201)
def add_plan_price(
    code: str, body: sc.PlatformPriceIn, request: Request, operator: Op = Depends(require("platform.plans"))
) -> object:
    """Add a price from a date (now by default). Earlier prices are kept for the record and never change."""
    return admin.set_plan_price(operator, code, body.model_dump(), _ip(request))


@router.delete("/plans/{code}/prices/{price_id}", response_model=sc.PlanDetail)
def remove_plan_price(
    code: str, price_id: UUID, request: Request, operator: Op = Depends(require("platform.plans"))
) -> object:
    """Take back a price that has not started yet."""
    return admin.remove_plan_price(operator, code, price_id, _ip(request))


# --------------------------------------------------------------------------- add-ons
@router.get("/addons", response_model=list[sc.AddonOut])
def list_addons(_: Op = Depends(require("platform.view"))) -> object:
    return [admin.addon_detail(a["code"]) for a in plans.list_addons()]


@router.post("/addons", response_model=sc.AddonOut, status_code=201)
def create_addon(body: sc.AddonIn, request: Request, operator: Op = Depends(require("platform.plans"))) -> object:
    return admin.create_addon(operator, body.model_dump(), _ip(request))


@router.patch("/addons/{code}", response_model=sc.AddonOut)
def patch_addon(
    code: str, body: sc.AddonPatch, request: Request, operator: Op = Depends(require("platform.plans"))
) -> object:
    return admin.update_addon(operator, code, body.model_dump(exclude_unset=True), _ip(request))


@router.post("/addons/{code}/prices", response_model=sc.AddonOut, status_code=201)
def add_addon_price(
    code: str, body: sc.PlatformPriceIn, request: Request, operator: Op = Depends(require("platform.plans"))
) -> object:
    return admin.set_addon_price(operator, code, body.model_dump(), _ip(request))


@router.delete("/addons/{code}/prices/{price_id}", response_model=sc.AddonOut)
def remove_addon_price(
    code: str, price_id: UUID, request: Request, operator: Op = Depends(require("platform.plans"))
) -> object:
    return admin.remove_addon_price(operator, code, price_id, _ip(request))


# --------------------------------------------------------------------------- coupons
@router.get("/coupons", response_model=list[sc.CouponOut])
def list_coupons(_: Op = Depends(require("platform.view"))) -> object:
    return plans.list_coupons()


@router.post("/coupons", response_model=sc.CouponOut, status_code=201)
def create_coupon(body: sc.CouponIn, request: Request, operator: Op = Depends(require("platform.plans"))) -> object:
    data = body.model_dump()
    return admin.create_coupon(operator, data, _ip(request))


@router.post("/coupons/{code}/status", response_model=sc.CouponOut)
def coupon_status(
    code: str, body: sc.StatusIn, request: Request, operator: Op = Depends(require("platform.plans"))
) -> object:
    return admin.set_coupon_status(operator, code, body.status, _ip(request))


# --------------------------------------------------------------------------- subscribers
@router.get("/subscribers", response_model=sc.SubscriberList)
def list_subscribers(
    search: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=20),
    plan: str | None = Query(default=None, max_length=40),
    edition: str | None = Query(default=None, max_length=40),
    country: str | None = Query(default=None, max_length=2),
    flag: str | None = Query(default=None, max_length=20, description="trial_ending, past_due, churned or unmanaged"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Op = Depends(require("platform.view")),
) -> object:
    """Every business with its plan, usage and money; search and filter."""
    return subscribers.list_subscribers(
        search=search, status=status, plan=plan, edition=edition, country=country, flag=flag, limit=limit, offset=offset
    )


@router.get("/subscribers/{code}", response_model=sc.SubscriberDetail)
def subscriber(code: str, operator: Op = Depends(require("platform.view"))) -> object:
    return subscribers.detail(operator, code)


@router.post("/subscribers/{code}/subscription", response_model=sc.SubscriberDetail)
def start_subscription(
    code: str, body: sc.StartSubscriptionIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    """Give a business without a subscription one (a trial, a paid period, or free)."""
    return admin.start_subscription(operator, code, body.model_dump(), _ip(request))


@router.post("/subscribers/{code}/plan", response_model=sc.SubscriberDetail)
def change_plan(
    code: str, body: sc.ChangePlanIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    """Move to another plan. An upgrade applies now with the pro rata difference invoiced; a downgrade starts at the end
    of the period unless the platform setting says otherwise."""
    return admin.change_plan(operator, code, body.model_dump(), _ip(request))


@router.post("/subscribers/{code}/trial", response_model=sc.SubscriberDetail)
def extend_trial(
    code: str, body: sc.ExtendTrialIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    return admin.extend_trial(operator, code, body.days, _ip(request))


@router.post("/subscribers/{code}/comp", response_model=sc.SubscriberDetail)
def comp(code: str, body: sc.CompIn, request: Request, operator: Op = Depends(require("platform.billing"))) -> object:
    return admin.comp(operator, code, body.model_dump(), _ip(request))


@router.post("/subscribers/{code}/coupon", response_model=sc.SubscriberDetail)
def apply_coupon(
    code: str, body: sc.CouponApplyIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    return admin.apply_coupon(operator, code, body.code, _ip(request))


@router.post("/subscribers/{code}/sync-plan", response_model=sc.SubscriberDetail)
def sync_plan(code: str, request: Request, operator: Op = Depends(require("platform.billing"))) -> object:
    """Copy the plan's current units and limits into this subscription (not the price)."""
    return admin.sync_plan(operator, code, _ip(request))


@router.post("/subscribers/{code}/suspend", response_model=sc.SubscriberDetail)
def suspend(
    code: str, body: sc.PlatformReasonIn, request: Request, operator: Op = Depends(require("platform.subscribers"))
) -> object:
    return admin.suspend(operator, code, body.reason, _ip(request))


@router.post("/subscribers/{code}/reactivate", response_model=sc.SubscriberDetail)
def reactivate(
    code: str, body: sc.OptionalReasonIn, request: Request, operator: Op = Depends(require("platform.subscribers"))
) -> object:
    return admin.reactivate(operator, code, body.reason, _ip(request))


@router.post("/subscribers/{code}/cancel", response_model=sc.SubscriberDetail)
def cancel(
    code: str, body: sc.PlatformCancelIn, request: Request, operator: Op = Depends(require("platform.subscribers"))
) -> object:
    return admin.cancel(operator, code, body.at_period_end, body.reason, _ip(request))


@router.post("/subscribers/{code}/uncancel", response_model=sc.SubscriberDetail)
def uncancel(code: str, request: Request, operator: Op = Depends(require("platform.subscribers"))) -> object:
    return admin.uncancel(operator, code, _ip(request))


@router.patch("/subscribers/{code}/notes", response_model=sc.SubscriberDetail)
def notes(
    code: str, body: sc.NotesIn, request: Request, operator: Op = Depends(require("platform.subscribers"))
) -> object:
    return admin.set_notes(operator, code, body.notes, body.tags, _ip(request))


@router.get("/subscribers/{code}/export")
def export_subscriber(code: str, _: Op = Depends(require("platform.subscribers"))) -> object:
    """What the platform holds about this subscriber (subscription, invoices, payments, contacts). The business's own
    data
    is exported by the business, or with `ziira backup --tenant CODE`."""
    return subscribers.export_records(code)


@router.post("/subscribers/{code}/delete", response_model=sc.SubscriberDetail)
def request_delete(
    code: str, body: sc.DeleteIn, request: Request, operator: Op = Depends(require("platform.subscribers"))
) -> object:
    """Schedule the business's deletion after the cooling-off period. Refused while its subscription is live."""
    return admin.request_deletion(operator, code, body.confirm, body.reason, body.early, _ip(request))


@router.delete("/subscribers/{code}/delete", response_model=sc.SubscriberDetail)
def cancel_delete(code: str, request: Request, operator: Op = Depends(require("platform.subscribers"))) -> object:
    return admin.cancel_deletion(operator, code, _ip(request))


@router.post("/privacy/contact", response_model=sc.ContactFound)
def find_contact(body: sc.EmailIn, _: Op = Depends(require("platform.subscribers"))) -> object:
    """Where a person's email appears in the platform's own records (for a data subject request)."""
    return subscribers.find_contact(body.email)


@router.post("/privacy/contact/erase", response_model=sc.ErasedOut)
def erase_contact(
    body: sc.EmailIn, request: Request, operator: Op = Depends(require("platform.subscribers"))
) -> object:
    return admin.erase_contact(operator, body.email, _ip(request))


# --------------------------------------------------------------------------- invoices and payments
@router.get("/invoices", response_model=list[sc.PlatformInvoiceOut])
def list_invoices(
    status: str | None = Query(default=None, max_length=10),
    tenant_code: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Op = Depends(require("platform.view")),
) -> object:
    tenant = subscribers.tenant_by_code(tenant_code)["id"] if tenant_code else None
    return billing.list_invoices(tenant_id=tenant, status=status, limit=limit, offset=offset)


@router.post("/invoices", response_model=sc.PlatformInvoiceOut, status_code=201)
def create_invoice(
    body: sc.PlatformInvoiceIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    """A draft (or issued) invoice for a subscriber or a licence customer. Tax lines come from the platform settings."""
    data = body.model_dump()
    return admin.create_invoice(operator, data, _ip(request))


def _invoice_detail(invoice_id: UUID) -> dict[str, Any]:
    return {**billing.get_invoice(invoice_id), "payments": billing.list_payments(invoice_id)}


@router.get("/invoices/{invoice_id}", response_model=sc.InvoiceDetail)
def get_invoice(invoice_id: UUID, _: Op = Depends(require("platform.view"))) -> object:
    return _invoice_detail(invoice_id)


@router.get("/invoices/{invoice_id}/html", response_class=HTMLResponse)
def invoice_page(invoice_id: UUID, _: Op = Depends(require("platform.view"))) -> HTMLResponse:
    """The printable invoice."""
    return HTMLResponse(billing.invoice_html(billing.get_invoice(invoice_id)))


@router.patch("/invoices/{invoice_id}", response_model=sc.InvoiceDetail)
def patch_invoice(
    invoice_id: UUID, body: sc.InvoicePatch, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    admin.update_draft(operator, invoice_id, body.model_dump(exclude_unset=True), _ip(request))
    return _invoice_detail(invoice_id)


@router.post("/invoices/{invoice_id}/issue", response_model=sc.InvoiceDetail)
def issue_invoice(invoice_id: UUID, request: Request, operator: Op = Depends(require("platform.billing"))) -> object:
    admin.issue_invoice(operator, invoice_id, _ip(request))
    return _invoice_detail(invoice_id)


@router.post("/invoices/{invoice_id}/void", response_model=sc.InvoiceDetail)
def void_invoice(
    invoice_id: UUID, body: sc.PlatformReasonIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    admin.void_invoice(operator, invoice_id, body.reason, _ip(request))
    return _invoice_detail(invoice_id)


@router.post("/invoices/{invoice_id}/payments", response_model=sc.InvoiceDetail, status_code=201)
def record_payment(
    invoice_id: UUID, body: sc.PlatformPaymentIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    """Record money received (bank transfer, cash, mobile money ...). Paid in full: the subscription moves on."""
    admin.record_payment(operator, invoice_id, body.model_dump(), _ip(request))
    return _invoice_detail(invoice_id)


@router.post("/payments/{payment_id}/reverse", response_model=sc.InvoiceDetail)
def reverse_payment(
    payment_id: UUID, body: sc.PlatformReasonIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    invoice = admin.reverse_payment(operator, payment_id, body.reason, _ip(request))
    return _invoice_detail(invoice["id"])


@router.get("/plan-requests", response_model=list[sc.PlatformRequestOut])
def plan_requests(
    status: str | None = Query(default="pending", max_length=10), _: Op = Depends(require("platform.view"))
) -> object:
    return billing.list_requests(status=status)


@router.post("/plan-requests/{request_id}/decide", response_model=sc.DecideOut)
def decide_request(
    request_id: UUID, body: sc.DecideIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    """Approve a business's plan request (its invoice is issued, or the change applied) or decline it."""
    return admin.decide_request(operator, request_id, body.approve, _ip(request))


@router.post("/billing/run", response_model=sc.BillingRunOut)
def run_billing(request: Request, operator: Op = Depends(require("platform.billing"))) -> object:
    """Run the recurring billing pass now (renewal invoices, reminders, dunning). The worker does this hourly."""
    return admin.run_billing(operator, _ip(request))


# --------------------------------------------------------------------------- licences
@router.get("/licences", response_model=list[sc.LicenceOut])
def list_licences(_: Op = Depends(require("platform.view"))) -> object:
    return licences.list_licences()


@router.post("/licences", response_model=sc.LicenceIssued, status_code=201)
def issue_licence(
    body: sc.LicenceIssueIn, request: Request, operator: Op = Depends(require("platform.licences"))
) -> object:
    """Make and sign a licence with this deployment's signing key (vendor side only)."""
    return admin.issue_licence(operator, body.model_dump(), _ip(request))


@router.get("/licences/{licence_id}/file", response_model=sc.FileOut)
def licence_file(licence_id: UUID, _: Op = Depends(require("platform.licences"))) -> object:
    row = licences.get_licence(licence_id)
    return {"filename": f"{row['licence_no']}.ziira-licence", "content": row["token"]}


@router.post("/licences/{licence_id}/revoke", response_model=sc.LicenceOut)
def revoke_licence(
    licence_id: UUID, body: sc.PlatformReasonIn, request: Request, operator: Op = Depends(require("platform.licences"))
) -> object:
    return admin.revoke_licence(operator, licence_id, body.reason, _ip(request))


@router.get("/licence-revocations", response_model=sc.FileOut)
def revocation_file(_: Op = Depends(require("platform.licences"))) -> object:
    """A signed list of revoked licences, to install on self-hosted copies (`ziira licence install FILE`)."""
    return {"filename": "revocations.ziira-licence", "content": licences.revocation_list()}


# --------------------------------------------------------------------------- operators
@router.post("/operators", response_model=sc.OperatorCreatedOut, status_code=201)
def create_operator(
    body: sc.OperatorCreateIn, request: Request, operator: Op = Depends(require("platform.operators"))
) -> object:
    """Add a member of staff. They choose their own password at the first sign-in; a temporary password (or, with a
    second factor, the secret for their authenticator) is shown once: give it to them."""
    return admin.create_operator(operator, body.model_dump(), _ip(request))


@router.patch("/operators/{operator_id}", response_model=sc.OperatorBrief)
def patch_operator(
    operator_id: UUID, body: sc.OperatorPatch, request: Request, operator: Op = Depends(require("platform.operators"))
) -> object:
    """Change a role or disable/enable an operator (never yourself, never the last superadmin)."""
    return admin.update_operator(operator, operator_id, body.model_dump(exclude_unset=True), _ip(request))


@router.post("/operators/{operator_id}/reset-password", response_model=sc.TemporaryPasswordOut)
def reset_operator_password(
    operator_id: UUID, request: Request, operator: Op = Depends(require("platform.operators"))
) -> object:
    """A random temporary password for someone who forgot theirs (their sign-ins end; they must change it at the next
    one). Shown once."""
    return admin.reset_operator_password(operator, operator_id, _ip(request))


@router.post("/operators/{operator_id}/reset-mfa", response_model=sc.OperatorSecretOut)
def reset_operator_mfa(
    operator_id: UUID, request: Request, operator: Op = Depends(require("platform.operators"))
) -> object:
    """A new second-factor secret for someone who lost their device (their sign-ins end). Shown once."""
    return admin.reset_operator_mfa(operator, operator_id, _ip(request))

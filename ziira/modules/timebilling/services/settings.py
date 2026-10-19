"""Use cases: time settings, staff profiles and client billing settings."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from ziira.modules.timebilling.domain.timesheet import ROUND_MODES, STEPS
from ziira.modules.timebilling.permissions import PROJECTS_MANAGE, TIME_SETTINGS
from ziira.modules.timebilling.repository.models import ClientTerms, Setting, Staff
from ziira.modules.timebilling.services import access, common
from ziira.sdk import Forbidden, NotFound, Session, ValidationFailed, audit_record, check_company, current_context

SETTING_FIELDS = (
    "minute_step", "timer_round_minutes", "timer_round_mode", "week_starts_on", "capacity_minutes_week",
    "approval_required", "rates_include_tax", "service_product_id", "expense_product_id", "invoice_round_minutes",
    "default_group_by", "budget_alert_percent", "unsubmitted_after_days", "unbilled_after_days",
    "notes_retention_days", "partner_review", "partner_review_above", "default_markup_percent",
    "receipt_required_above", "nudge_minutes", "nudge_hour", "work_days", "approval_reminder_days",
    "approval_escalate_days")


def get_settings(session: Session, company_id: UUID) -> Setting:
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    return common.settings(session, company_id)


def update_settings(session: Session, company_id: UUID, **changes: Any) -> Setting:
    """Change the company's time settings. Needs 'time.settings'."""
    current_context().require(TIME_SETTINGS, company_id=company_id)
    check_company(session, company_id)
    row = common.settings(session, company_id)
    if "minute_step" in changes and changes["minute_step"] not in STEPS:
        raise ValidationFailed(f"Time is entered in steps of {', '.join(map(str, STEPS))} minutes")
    if "timer_round_mode" in changes and changes["timer_round_mode"] not in ROUND_MODES:
        raise ValidationFailed("Round timers up, down or to the nearest step")
    if changes.get("work_days") is not None:
        days = sorted(set(changes["work_days"]))
        if not days or any(d < 1 or d > 7 for d in days):
            raise ValidationFailed("Working days are numbers from 1 (Monday) to 7 (Sunday), at least one")
        changes["work_days"] = days
    for key in ("service_product_id", "expense_product_id"):
        if changes.get(key) is not None:
            _check_service_item(session, company_id, changes[key])
    done: dict[str, object] = {}
    for key, value in changes.items():
        if key in SETTING_FIELDS and getattr(row, key) != value:
            done[key] = value
            setattr(row, key, value)
    row.updated_by = current_context().user_id
    session.flush()
    if done:
        audit_record(session, "update", "timebilling.setting", row.id, done)
    return row


def _check_service_item(session: Session, company_id: UUID, product_id: UUID) -> None:
    from ziira.modules.products.public import find_product

    product = find_product(session, product_id)
    if product is None or product.company_id != company_id or not product.is_active:
        raise ValidationFailed("The service item was not found in this company")
    if product.product_type == "stock":
        raise ValidationFailed("Choose a service item (one that is not kept in stock)")


# --------------------------------------------------------------------------- staff
@dataclass
class StaffRow:
    user_id: UUID
    name: str
    email: str | None
    title: str | None
    weekly_capacity_minutes: int | None
    active: bool
    approver_id: UUID | None = None
    away_until: date | None = None
    nudges: bool = True


def list_staff(session: Session, company_id: UUID) -> list[StaffRow]:
    """Everyone who may log time in the company, with their title and capacity (if set)."""
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    profiles = {s.user_id: s for s in session.scalars(select(Staff).where(Staff.company_id == company_id))}
    users = session.execute(text(
        "select distinct u.id, u.full_name, u.email from kernel.app_user u "
        "join kernel.user_role ur on ur.user_id = u.id "
        "where u.status = 'active' and (ur.company_id is null or ur.company_id = :c) order by u.full_name"),
        {"c": str(company_id)}).all()
    out = []
    for u in users:
        p = profiles.get(u.id)
        out.append(StaffRow(u.id, str(u.full_name), u.email, p.title if p else None,
                            p.weekly_capacity_minutes if p else None, p.active if p else True,
                            p.approver_id if p else None, p.away_until if p else None, p.nudges if p else True))
    return out


def set_staff(session: Session, company_id: UUID, user_id: UUID, *, title: str | None,
              weekly_capacity_minutes: int | None, active: bool, approver_id: UUID | None = None,
              away_until: date | None = None, nudges: bool = True) -> Staff:
    """Set a person's title (rates can be set by title), weekly capacity, who approves their weeks first, when they
    are away (reminders to approve go to others meanwhile) and whether they get missed-time reminders. Needs
    'projects.manage' or 'time.settings'."""
    ctx = current_context()
    if not (ctx.can(PROJECTS_MANAGE, company_id=company_id) or ctx.can(TIME_SETTINGS, company_id=company_id)):
        raise Forbidden("You need permission to manage projects or time settings")
    check_company(session, company_id)
    if common.user_names(session, {user_id}).get(user_id) is None:
        raise ValidationFailed("Person not found")
    row = session.scalar(select(Staff).where(Staff.company_id == company_id, Staff.user_id == user_id))
    if row is None:
        row = Staff(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, user_id=user_id)
        session.add(row)
    row.title = (title or "").strip()[:80] or None
    if approver_id is not None:
        if approver_id == user_id:
            raise ValidationFailed("Somebody else has to approve a person's weeks")
        if common.user_names(session, {approver_id}).get(approver_id) is None:
            raise ValidationFailed("The approver was not found")
    row.weekly_capacity_minutes = weekly_capacity_minutes
    row.active = active
    row.approver_id, row.away_until, row.nudges = approver_id, away_until, nudges
    row.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "timebilling.staff", row.id, {"user_id": user_id, "title": row.title})
    return row


def staff_title(session: Session, company_id: UUID, user_id: UUID) -> str | None:
    row = session.scalar(select(Staff).where(Staff.company_id == company_id, Staff.user_id == user_id))
    return row.title if row else None


# --------------------------------------------------------------------------- client billing settings
def get_client_terms(session: Session, company_id: UUID, customer_id: UUID) -> ClientTerms | None:
    return session.scalar(select(ClientTerms).where(ClientTerms.company_id == company_id,
                                                    ClientTerms.customer_id == customer_id))


def set_client_terms(session: Session, company_id: UUID, customer_id: UUID, *, payment_terms_days: int | None,
                     invoice_group_by: str | None, billing_notes: str | None, active: bool,
                     expense_markup_percent: Decimal | None = None) -> ClientTerms:
    """Billing settings for a client (a CRM customer). Needs 'projects.manage'."""
    ctx = current_context()
    ctx.require(PROJECTS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    from ziira.modules.crm.public import find_customer

    customer = find_customer(session, customer_id)
    if customer is None or customer.company_id != company_id:
        raise ValidationFailed("Client not found in this company")
    row = get_client_terms(session, company_id, customer_id)
    if row is None:
        row = ClientTerms(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                          customer_id=customer_id)
        session.add(row)
    row.payment_terms_days, row.invoice_group_by = payment_terms_days, invoice_group_by
    row.expense_markup_percent = expense_markup_percent
    row.billing_notes = (billing_notes or "").strip()[:2000] or None
    row.active = active
    row.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "timebilling.client_terms", row.id, {"customer_id": customer_id})
    return row


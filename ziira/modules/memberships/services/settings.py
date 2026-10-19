"""A company's membership policies: overdraw, catch-up limit, proration, reminders and quiet hours."""

from uuid import UUID

from ziira.modules.memberships.permissions import PLANS
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common
from ziira.sdk import Session, ValidationFailed, audit_record, check_company, current_context

FIELDS = {"allow_overdraw", "catch_up_max_periods", "prorate_first_period", "reminders_enabled",
          "renewal_reminder_days", "expiry_reminder_days", "quiet_start", "quiet_end", "message_language", "grace_days",
          "dunning_days", "auto_freeze_days", "inactive_weeks", "birthday_messages", "waiver_required",
          "repeat_window_minutes", "expiry_warning_days", "late_cancel_hours", "late_cancel_consumes",
          "no_show_consumes", "points_per_unit", "point_value", "referral_reward", "auto_apply_credit",
          "voucher_product_id", "offline_valid_hours"}


def get_settings(session: Session, company_id: UUID) -> repo.Row:
    check_company(session, company_id)
    common.check_visible(company_id, None, "Company")
    return repo.get_settings(session, company_id)


def update_settings(session: Session, company_id: UUID, **changes: object) -> repo.Row:
    """Change the policies. Needs 'memberships.plans'."""
    check_company(session, company_id)
    common.require(PLANS, company_id)
    values = {k: v for k, v in changes.items() if k in FIELDS and v is not None}
    if "quiet_start" in values and values["quiet_start"] == values.get("quiet_end", repo.get_settings(
            session, company_id)["quiet_end"]):
        raise ValidationFailed("Quiet hours must start and end at different hours")
    if "dunning_days" in values:
        values["dunning_days"] = ",".join(p.strip() for p in str(values["dunning_days"]).split(",") if p.strip())
    if values.get("voucher_product_id"):
        common.check_product(session, company_id, values["voucher_product_id"])  # type: ignore[arg-type]
    ctx = current_context()
    saved = repo.save_settings(session, ctx.tenant_id, company_id, values, ctx.user_id)
    audit_record(session, "update", "memberships.setting", saved.get("id"), {k: str(v) for k, v in values.items()})
    return saved

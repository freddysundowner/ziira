"""Use cases: the booking settings of a company (online booking, notice, reminders, invoicing)."""

from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

from ziira.modules.bookings.permissions import BOOKINGS_SETUP
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import BookingSettings
from ziira.modules.bookings.services import access
from ziira.sdk import (
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    claim_booking_slug,
    current_context,
    release_booking_slug,
)

GRANULARITIES = (5, 10, 15, 20, 30, 60)
EDITABLE = ("online_enabled", "auto_confirm", "min_notice_minutes", "max_days_ahead", "cancel_window_hours",
            "reminders_enabled", "reminder_hours_before", "slot_granularity_minutes", "default_buffer_minutes",
            "show_resources_publicly", "invoice_on_completion", "invoice_due_days", "quiet_start", "quiet_end",
            "consent_text", "public_name", "public_note", "late_cancel_fee_percent", "no_show_fee_percent",
            "waitlist_confirm_minutes", "rebook_prompt_hours", "recalls_enabled", "deposit_note",
            "patch_test_valid_days", "commission_excludes_tax", "fee_product_id", "walkin_customer_id",
            "discount_limit_percent", "reminder_template", "recall_template", "rebook_template")
NULLABLE = ("invoice_due_days", "consent_text", "public_name", "public_note", "deposit_note", "patch_test_valid_days",
            "fee_product_id", "walkin_customer_id", "discount_limit_percent", "reminder_template", "recall_template",
            "rebook_template")
TEMPLATE_CHOICES = {
    "reminder_template": ("appointment_reminder", "appointment_reminder_clinic"),
    "recall_template": ("appointment_recall", "appointment_recall_clinic"),
    "rebook_template": ("appointment_rebook", "appointment_rebook_clinic")}
DEFAULT_CONSENT = ("I agree that the business keeps my name and contact details to manage my booking and to send me "
                   "messages about it.")


def get_settings(session: Session, company_id: UUID) -> BookingSettings:
    """The company's settings (made with the defaults on first use). Needs any bookings permission in the company."""
    if not access.can_see_company(company_id):
        raise ValidationFailed("Company not found")
    check_company(session, company_id)
    return repo.ensure_settings(session, company_id)


def update_settings(session: Session, company_id: UUID, *, slug: str | None = None, **changes: Any) -> BookingSettings:
    """Change the settings. `slug` is the public booking address ('' frees it). Needs 'bookings.setup'."""
    ctx = current_context()
    ctx.require(BOOKINGS_SETUP, company_id=company_id)
    check_company(session, company_id)
    row = repo.ensure_settings(session, company_id)
    done: dict[str, object] = {}
    for key, value in changes.items():
        if key not in EDITABLE or value is None and key not in NULLABLE:
            continue
        if key in ("quiet_start", "quiet_end") and isinstance(value, str):
            value = _time(value)
        if key == "slot_granularity_minutes" and value not in GRANULARITIES:
            raise ValidationFailed(f"Slots can be every {', '.join(map(str, GRANULARITIES))} minutes")
        if isinstance(value, str):
            value = value.strip() or None
        if key in TEMPLATE_CHOICES and value is not None and value not in TEMPLATE_CHOICES[key]:
            raise ValidationFailed(f"Choose one of: {', '.join(TEMPLATE_CHOICES[key])}")
        if key == "fee_product_id" and value is not None:
            from ziira.modules.products.public import find_product

            product = find_product(session, value)
            if product is None or product.company_id != company_id or product.product_type != "service":
                raise ValidationFailed("Pick a service item for fees")
        setattr(row, key, value)
        done[key] = str(value)
    if slug is not None:
        clean = slug.strip().lower()
        if clean:
            row.slug = claim_booking_slug(ctx.tenant_id, company_id, clean)
        else:
            release_booking_slug(ctx.tenant_id, company_id)
            row.slug = None
        done["slug"] = row.slug or ""
    if row.online_enabled and not row.slug:
        raise ValidationFailed("Choose a booking address before you switch online booking on")
    row.updated_by, row.updated_at = ctx.user_id, datetime.now(UTC)
    session.flush()
    audit_record(session, "update", "bookings.booking_settings", row.id, done)
    return row


def _time(value: str) -> time:
    from ziira.modules.bookings.domain.rules import parse_time

    return parse_time(value)

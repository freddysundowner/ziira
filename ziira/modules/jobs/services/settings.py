"""Use cases: job settings of a company and the intake checklist templates."""

from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.permissions import JOBS_SETTINGS
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import ChecklistTemplate, JobSetting
from ziira.modules.jobs.services import access
from ziira.modules.products.public import find_product
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, check_company, current_context

MAX_ITEMS = 60
MAX_TEMPLATES = 50


def get_settings(session: Session, company_id: UUID) -> JobSetting:
    """The company's job settings (created with defaults the first time)."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    found = repo.get_setting(session, company_id)
    if found is None:
        check_company(session, company_id)
        found = JobSetting(tenant_id=current_context().tenant_id, company_id=company_id)
        repo.add(session, found)
    return found


def _service_item(session: Session, company_id: UUID, product_id: UUID | None, what: str) -> None:
    if product_id is None:
        return
    product = find_product(session, product_id)
    if product is None or product.company_id != company_id or not product.is_active:
        raise ValidationFailed(f"The {what} item was not found in this company")
    if product.product_type == "stock":
        raise ValidationFailed(f"The {what} item must be a service or non-stock item, not one that holds stock")


def update_settings(session: Session, company_id: UUID, **changes: object) -> JobSetting:
    """Change job settings. Needs 'jobs.settings'."""
    current_context().require(JOBS_SETTINGS, company_id=company_id)
    row = get_settings(session, company_id)
    if "default_labour_rate" in changes:
        rate = changes["default_labour_rate"]
        if not isinstance(rate, Decimal) or rate < 0:
            raise ValidationFailed("The labour rate cannot be negative")
        row.default_labour_rate = rate
    for key, what in (("labour_product_id", "labour"), ("parts_product_id", "parts"), ("fees_product_id", "fees")):
        if key in changes:
            value = changes[key]
            _service_item(session, company_id, value if isinstance(value, UUID) else None, what)
            setattr(row, key, value)
    for key in ("estimate_valid_days", "default_warranty_days", "storage_grace_days", "service_reminder_days",
                "ready_reminder_days"):
        if key in changes and isinstance(changes[key], int):
            setattr(row, key, changes[key])
    for key in ("tell_customer_when_ready", "remind_service_due"):
        if key in changes and isinstance(changes[key], bool):
            setattr(row, key, changes[key])
    for key, allowed in (("odometer_unit", ("km", "mi")), ("unapproved_work", ("off", "warn", "block")),
                         ("release_unpaid", ("off", "warn", "block")), ("required_photos", ("off", "warn", "block"))):
        if key in changes:
            if changes[key] not in allowed:
                raise ValidationFailed(f"{key.replace('_', ' ').capitalize()} must be one of: {', '.join(allowed)}")
            setattr(row, key, changes[key])
    if "storage_fee_per_day" in changes:
        fee = changes["storage_fee_per_day"]
        if not isinstance(fee, Decimal) or fee < 0:
            raise ValidationFailed("The storage fee cannot be negative")
        row.storage_fee_per_day = fee
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "jobs.setting", row.id, {k: str(v) for k, v in changes.items()})
    return row


def clean_items(items: list[str]) -> list[str]:
    cleaned = [i.strip()[:120] for i in items if i and i.strip()]
    if len(cleaned) > MAX_ITEMS:
        raise ValidationFailed(f"A checklist has at most {MAX_ITEMS} items")
    return cleaned


def list_templates(session: Session, company_id: UUID, *, only_active: bool = False) -> list[ChecklistTemplate]:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    return repo.templates(session, company_id, only_active=only_active)


def create_template(session: Session, *, company_id: UUID, name: str, items: list[str],
                    asset_kind: str | None = None) -> ChecklistTemplate:
    """Add an intake checklist. Needs 'jobs.settings'."""
    ctx = current_context()
    ctx.require(JOBS_SETTINGS, company_id=company_id)
    check_company(session, company_id)
    if not name.strip():
        raise ValidationFailed("A checklist needs a name")
    if repo.template_by_name(session, company_id, name.strip()) is not None:
        raise Conflict("There is already a checklist with this name")
    if len(repo.templates(session, company_id)) >= MAX_TEMPLATES:
        raise ValidationFailed(f"At most {MAX_TEMPLATES} checklists")
    row = ChecklistTemplate(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                            name=name.strip()[:80], items=clean_items(items),
                            asset_kind=(asset_kind or "").strip()[:40] or None)
    repo.add(session, row)
    audit_record(session, "create", "jobs.checklist_template", row.id, {"name": row.name})
    return row


def update_template(session: Session, template_id: UUID, **changes: object) -> ChecklistTemplate:
    """Change a checklist. Needs 'jobs.settings'. Jobs already made keep the copy they took."""
    row = repo.get(session, ChecklistTemplate, template_id)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Checklist not found")
    current_context().require(JOBS_SETTINGS, company_id=row.company_id)
    if "name" in changes and isinstance(changes["name"], str) and changes["name"].strip():
        other = repo.template_by_name(session, row.company_id, changes["name"].strip())
        if other is not None and other.id != row.id:
            raise Conflict("There is already a checklist with this name")
        row.name = changes["name"].strip()[:80]
    if "items" in changes and isinstance(changes["items"], list):
        row.items = clean_items([str(i) for i in changes["items"]])
    if "asset_kind" in changes:
        row.asset_kind = str(changes["asset_kind"] or "").strip()[:40] or None
    if "is_active" in changes and isinstance(changes["is_active"], bool):
        row.is_active = changes["is_active"]
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "jobs.checklist_template", row.id, {})
    return row


def seed_template(session: Session, company_id: UUID, name: str, items: list[str],
                  asset_kind: str | None = None) -> bool:
    """Add a checklist unless the company has one with this name (for industry packs). True when added."""
    if repo.template_by_name(session, company_id, name.strip()) is not None:
        return False
    create_template(session, company_id=company_id, name=name, items=items, asset_kind=asset_kind)
    return True

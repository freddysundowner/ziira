"""Use cases: assets, the things customers bring (a vehicle, a phone, a garment, a property).

An asset carries free identifiers (plate, serial number, IMEI, size, address): the business decides what to write.
Many jobs can point at one asset; its history is every job it has had.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.permissions import JOBS_MANAGE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Asset, Job
from ziira.modules.jobs.services import access
from ziira.modules.jobs.services.common import clean, unit_enabled
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, check_company, current_context

MAX_IDENTIFIERS = 12


def clean_identifiers(identifiers: dict[str, str] | None) -> dict[str, str]:
    """Identifier names and values trimmed; empty ones dropped."""
    found: dict[str, str] = {}
    for key, value in (identifiers or {}).items():
        k, v = str(key).strip()[:40], str(value).strip()[:120]
        if k and v:
            found[k] = v
    if len(found) > MAX_IDENTIFIERS:
        raise ValidationFailed(f"An item has at most {MAX_IDENTIFIERS} identifiers")
    return found


def check_customer(session: Session, company_id: UUID, customer_id: UUID | None) -> None:
    """The customer must exist in this company (Customers must be switched on to name one)."""
    if customer_id is None:
        return
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Customers are not switched on for this business")
    from ziira.modules.crm.public import find_customer

    customer = find_customer(session, customer_id)
    if customer is None or customer.company_id != company_id:
        raise ValidationFailed("The customer was not found in this company")


def create_asset(session: Session, *, company_id: UUID, label: str, kind: str = "item",
                 customer_id: UUID | None = None, identifiers: dict[str, str] | None = None,
                 notes: str | None = None, odometer: Decimal | None = None) -> Asset:
    """Record an item. Needs 'jobs.manage'."""
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    check_customer(session, company_id, customer_id)
    if not label.strip():
        raise ValidationFailed("Describe the item, for example 'Toyota Corolla KAA 123B'")
    row = Asset(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, customer_id=customer_id,
                kind=(kind.strip() or "item")[:40], label=label.strip()[:160],
                identifiers=clean_identifiers(identifiers), notes=clean(notes, 1000),
                odometer=odometer, odometer_at=datetime.now(UTC) if odometer is not None else None)
    repo.add(session, row)
    audit_record(session, "create", "jobs.asset", row.id, {"label": row.label})
    return row


def load_asset(session: Session, asset_id: UUID) -> Asset:
    row = repo.get(session, Asset, asset_id)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Item not found")
    return row


def update_asset(session: Session, asset_id: UUID, **changes: object) -> Asset:
    """Change an item's description, owner, identifiers or notes. Needs 'jobs.manage'."""
    row = load_asset(session, asset_id)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=row.company_id)
    if "label" in changes:
        label = str(changes["label"] or "").strip()
        if not label:
            raise ValidationFailed("Describe the item")
        row.label = label[:160]
    if "kind" in changes and str(changes["kind"] or "").strip():
        row.kind = str(changes["kind"]).strip()[:40]
    if "customer_id" in changes:
        customer = changes["customer_id"] if isinstance(changes["customer_id"], UUID) else None
        check_customer(session, row.company_id, customer)
        row.customer_id = customer
    if "identifiers" in changes and isinstance(changes["identifiers"], dict):
        row.identifiers = clean_identifiers({str(k): str(v) for k, v in changes["identifiers"].items()})
    if "notes" in changes:
        row.notes = clean(str(changes["notes"] or ""), 1000)
    if isinstance(changes.get("is_active"), bool):
        row.is_active = bool(changes["is_active"])
    row.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "jobs.asset", row.id, {})
    return row


def list_assets(session: Session, *, search: str | None = None, customer_id: UUID | None = None,
                only_active: bool = True, limit: int = 50, offset: int = 0) -> list[Asset]:
    return repo.list_assets(session, access.view_companies(), search=search, customer_id=customer_id,
                            only_active=only_active, limit=min(limit, 200), offset=offset)


def record_odometer(session: Session, asset: Asset, reading: Decimal) -> str | None:
    """Keep the latest reading seen on the item. Returns a plain warning when it is lower than the last one (a clock
    that went back, or a typing slip) — the reading is still kept on the visit that gave it."""
    warning = None
    if asset.odometer is not None and reading < asset.odometer:
        warning = f"The reading {reading:g} is lower than the last one on record ({asset.odometer:g})"
    if asset.odometer is None or reading >= asset.odometer:
        asset.odometer, asset.odometer_at = reading, datetime.now(UTC)
        session.flush()
    return warning


def set_next_service(session: Session, asset: Asset, *, date_: date | None, odometer: Decimal | None,
                     note: str | None, job: Job | None = None) -> Asset:
    """When the item is next due for service: a date, an odometer reading, or both. A new date is a new reminder."""
    from ziira.modules.jobs.services.common import add_event

    current_context().require(JOBS_MANAGE, company_id=asset.company_id)
    if odometer is not None and (odometer < 0 or odometer > Decimal("99999999")):
        raise ValidationFailed("The odometer reading is not valid")
    if date_ != asset.next_service_date:
        asset.service_reminded_for = None
    asset.next_service_date, asset.next_service_odometer = date_, odometer
    asset.next_service_note = clean(note, 200)
    asset.updated_by = current_context().user_id
    session.flush()
    if job is not None:
        what = ", ".join(x for x in (date_.isoformat() if date_ else "", f"{odometer:g}" if odometer is not None
                                     else "") if x) or "cleared"
        add_event(session, job, "intake", f"Next service: {what}")
    audit_record(session, "next_service", "jobs.asset", asset.id, {})
    return asset


@dataclass(frozen=True)
class Visit:
    """One earlier visit of an item, for the intake screen: when, what, the reading and what was done."""

    job: Job
    work: list[str]
    total: Decimal


def visits(session: Session, asset_id: UUID, limit: int = 12) -> list[Visit]:
    """The item's earlier jobs with what was done on each (labour and parts), newest first."""
    from ziira.modules.jobs.services import totals

    out: list[Visit] = []
    for job in history(session, asset_id)[:limit]:
        work = [x.description for x in repo.labour(session, job.id, include_voided=False)]
        work += [p.description for p in repo.parts(session, job.id, include_voided=False)]
        out.append(Visit(job, work[:8], totals.job_totals(session, job).grand.total))
    return out


def history(session: Session, asset_id: UUID) -> list[Job]:
    """Every job the item has had that the user may see, newest first."""
    asset = load_asset(session, asset_id)
    return [j for j in repo.jobs_of_asset(session, asset.id) if access.can_view(j.company_id, j.branch_id)]

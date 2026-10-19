"""Use cases: resources (people, rooms, chairs, equipment), their working hours and their time off."""

from datetime import UTC, datetime
from uuid import UUID

from ziira.modules.bookings.domain import rules
from ziira.modules.bookings.domain.availability import Hours
from ziira.modules.bookings.permissions import BOOKINGS_SETUP
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import Resource, ResourceHours, ResourceTimeOff
from ziira.modules.bookings.services import access
from ziira.sdk import (
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_branch_open,
    check_company,
    current_context,
)


def _visible(session: Session, resource_id: UUID, *, lock: bool = False) -> Resource:
    resource = repo.get_resource(session, resource_id, lock=lock)
    if resource is None or not access.can_view(resource.company_id, resource.branch_id):
        raise NotFound("Resource not found")
    return resource


def get_resource(session: Session, resource_id: UUID) -> Resource:
    return _visible(session, resource_id)


def create_resource(session: Session, *, company_id: UUID, branch_id: UUID, name: str, kind: str = "staff",
                    user_id: UUID | None = None, colour: str | None = None, note: str | None = None,
                    show_publicly: bool = True, sort_order: int = 0, level: str | None = None,
                    hours: list[Hours] | None = None) -> Resource:
    """Add a resource. Working hours may be given now or set later. Needs 'bookings.setup' at the branch."""
    ctx = current_context()
    ctx.require(BOOKINGS_SETUP, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    check_branch_open(session, branch_id)
    if kind not in rules.RESOURCE_KINDS:
        raise ValidationFailed(f"Kind must be one of: {', '.join(rules.RESOURCE_KINDS)}")
    resource = Resource(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
                        name=rules.check_name(name), kind=kind, user_id=user_id, colour=rules.check_colour(colour),
                        note=(note or "").strip() or None, show_publicly=show_publicly, sort_order=sort_order,
                        level=(level or "").strip() or None)
    repo.add(session, resource)
    if hours:
        _write_hours(session, resource, hours)
    audit_record(session, "create", "bookings.resource", resource.id, {"name": resource.name, "kind": kind})
    return resource


def update_resource(session: Session, resource_id: UUID, **changes: object) -> Resource:
    """Change a resource's details. Needs 'bookings.setup' at its branch."""
    resource = _visible(session, resource_id, lock=True)
    ctx = current_context()
    ctx.require(BOOKINGS_SETUP, company_id=resource.company_id, branch_id=resource.branch_id)
    done: dict[str, object] = {}
    for key, value in changes.items():
        if value is None and key not in ("user_id", "colour", "note", "level"):
            continue
        if key == "name":
            value = rules.check_name(str(value))
        elif key == "colour":
            value = rules.check_colour(str(value) if value else None)
        elif key == "kind" and value not in rules.RESOURCE_KINDS:
            raise ValidationFailed(f"Kind must be one of: {', '.join(rules.RESOURCE_KINDS)}")
        elif key == "is_active" and value is False and resource.is_active:
            upcoming = repo.appointments_on_resource(session, resource.id, datetime.now(UTC),
                                                     datetime(9999, 1, 1, tzinfo=UTC))
            if upcoming:
                raise ValidationFailed(f"{resource.name} has {upcoming} upcoming appointment(s): move or cancel them "
                                       "first")
        elif key == "level":
            value = (str(value) if value else "").strip() or None
        elif key not in ("show_publicly", "sort_order", "user_id", "note", "is_active"):
            continue
        setattr(resource, key, value)
        done[key] = str(value)
    if done:
        resource.is_template = False            # the business made it its own
    resource.updated_by, resource.updated_at = ctx.user_id, datetime.now(UTC)
    session.flush()
    audit_record(session, "update", "bookings.resource", resource.id, done)
    return resource


def list_resources(session: Session, *, branch_id: UUID | None = None, active_only: bool = False) -> list[Resource]:
    return repo.list_resources(session, access.view_scopes(), branch_id=branch_id, active_only=active_only)


def _write_hours(session: Session, resource: Resource, hours: list[Hours]) -> list[ResourceHours]:
    checked = rules.check_hours(hours)
    session.query(ResourceHours).filter(ResourceHours.resource_id == resource.id).delete()
    session.flush()
    ctx = current_context()
    rows = [ResourceHours(tenant_id=ctx.tenant_id, created_by=ctx.user_id, resource_id=resource.id, weekday=h.weekday,
                          start_time=h.start, end_time=h.end) for h in checked]
    session.add_all(rows)
    session.flush()
    return rows


def set_hours(session: Session, resource_id: UUID, hours: list[Hours]) -> list[ResourceHours]:
    """Replace a resource's weekly working hours (an empty list means it cannot be booked). Needs 'bookings.setup'."""
    resource = _visible(session, resource_id, lock=True)
    current_context().require(BOOKINGS_SETUP, company_id=resource.company_id, branch_id=resource.branch_id)
    rows = _write_hours(session, resource, hours)
    audit_record(session, "set_hours", "bookings.resource", resource.id, {"windows": len(rows)})
    return rows


def hours_of(session: Session, resource_id: UUID) -> list[ResourceHours]:
    resource = _visible(session, resource_id)
    return repo.hours_of(session, {resource.id}).get(resource.id, [])


def add_time_off(session: Session, resource_id: UUID, *, starts_at: datetime, ends_at: datetime,
                 reason: str | None = None) -> tuple[ResourceTimeOff, int]:
    """Block a period (leave, repairs). Returns it and how many existing appointments fall inside it (they are not
    moved: the front desk decides). Needs 'bookings.setup'."""
    resource = _visible(session, resource_id, lock=True)
    ctx = current_context()
    ctx.require(BOOKINGS_SETUP, company_id=resource.company_id, branch_id=resource.branch_id)
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise ValidationFailed("Time off needs a start and an end with a time zone")
    if ends_at <= starts_at:
        raise ValidationFailed("Time off must end after it starts")
    row = ResourceTimeOff(tenant_id=ctx.tenant_id, created_by=ctx.user_id, resource_id=resource.id,
                          starts_at=starts_at, ends_at=ends_at, reason=(reason or "").strip() or None)
    repo.add(session, row)
    clashes = repo.appointments_on_resource(session, resource.id, starts_at, ends_at)
    audit_record(session, "time_off", "bookings.resource", resource.id,
                 {"from": starts_at.isoformat(), "to": ends_at.isoformat(), "affected": clashes})
    return row, clashes


def remove_time_off(session: Session, time_off_id: UUID) -> None:
    row = repo.get_time_off(session, time_off_id)
    if row is None:
        raise NotFound("Time off not found")
    resource = _visible(session, row.resource_id)
    current_context().require(BOOKINGS_SETUP, company_id=resource.company_id, branch_id=resource.branch_id)
    session.delete(row)
    session.flush()
    audit_record(session, "remove_time_off", "bookings.resource", resource.id, {})


def time_off(session: Session, resource_id: UUID, start: datetime | None = None,
             end: datetime | None = None) -> list[ResourceTimeOff]:
    resource = _visible(session, resource_id)
    return repo.time_off_of(session, {resource.id}, start, end).get(resource.id, [])


def as_domain_hours(rows: list[ResourceHours]) -> tuple[Hours, ...]:
    return tuple(Hours(r.weekday, r.start_time, r.end_time) for r in rows)

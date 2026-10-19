"""Use cases: service offers, what a business sells by appointment, and which resources can do each."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.bookings.domain import rules
from ziira.modules.bookings.permissions import BOOKINGS_SETUP
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import ServiceOffer, ServiceOfferResource
from ziira.modules.bookings.services import access
from ziira.modules.bookings.services.common import unit_enabled
from ziira.modules.products.public import find_product, selling_prices
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, check_company, current_context


def _visible(session: Session, offer_id: UUID, *, lock: bool = False) -> ServiceOffer:
    offer = repo.get_offer(session, offer_id, lock=lock)
    if offer is None or not access.can_see_company(offer.company_id):
        raise NotFound("Service not found")
    return offer


def get_offer(session: Session, offer_id: UUID) -> ServiceOffer:
    return _visible(session, offer_id)


def list_offers(session: Session, *, company_id: UUID | None = None, active_only: bool = False) -> list[ServiceOffer]:
    return repo.list_offers(session, access.view_companies(), company_id=company_id, active_only=active_only)


def resource_ids_of(session: Session, offer_id: UUID) -> list[UUID]:
    return repo.offer_resource_ids(session, {offer_id}).get(offer_id, [])


def _check_product(session: Session, company_id: UUID, product_id: UUID, offer_id: UUID | None) -> tuple[str, Decimal]:
    product = find_product(session, product_id)
    if product is None or product.company_id != company_id:
        raise ValidationFailed("The service item was not found in this company")
    if product.product_type != "service":
        raise ValidationFailed("Pick a service item (not a stocked product) from Products")
    if repo.offer_product_taken(session, company_id, product_id, offer_id):
        raise ValidationFailed("There is already a bookable service for that item")
    price = selling_prices(session, company_id, None, {product_id}).get(product_id, Decimal(0)) \
        if unit_enabled(session, "products") else Decimal(0)
    return product.name, price


def _set_resources(session: Session, offer: ServiceOffer, resource_ids: list[UUID]) -> None:
    ctx = current_context()
    wanted = list(dict.fromkeys(resource_ids))
    found = repo.resources_by_ids(session, set(wanted))
    for rid in wanted:
        r = found.get(rid)
        if r is None or r.company_id != offer.company_id:
            raise ValidationFailed("A resource was not found in this company")
    session.query(ServiceOfferResource).filter(ServiceOfferResource.offer_id == offer.id).delete()
    session.flush()
    session.add_all([ServiceOfferResource(tenant_id=ctx.tenant_id, created_by=ctx.user_id, offer_id=offer.id,
                                          resource_id=rid) for rid in wanted])
    session.flush()


def create_offer(session: Session, *, company_id: UUID, duration_minutes: int, name: str | None = None,
                 product_id: UUID | None = None, description: str | None = None, kind: str = "appointment",
                 buffer_before_minutes: int | None = None, buffer_after_minutes: int | None = None,
                 price: Decimal | None = None, resource_mode: str = "any", capacity: int = 1,
                 show_publicly: bool = True, resource_ids: list[UUID] | None = None,
                 processing_start_minutes: int = 0, processing_minutes: int = 0, deposit_amount: Decimal = Decimal(0),
                 deposit_percent: Decimal = Decimal(0), recall_days: int | None = None, needs_patch_test: bool = False,
                 group_late_cancel_hours: int | None = None) -> ServiceOffer:
    """Make a service bookable. Link it to a service item (so it can be invoiced), or give it a name of its own.
    Needs 'bookings.setup'."""
    ctx = current_context()
    ctx.require(BOOKINGS_SETUP, company_id=company_id)
    check_company(session, company_id)
    product_name, product_price = (None, Decimal(0))
    if product_id is not None:
        product_name, product_price = _check_product(session, company_id, product_id, None)
    label = rules.check_name(name or product_name or "", "The service name")
    _check_shape(kind, resource_mode, capacity)
    _check_processing(duration_minutes, processing_start_minutes, processing_minutes)
    default_buffer = repo.ensure_settings(session, company_id).default_buffer_minutes
    offer = ServiceOffer(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, product_id=product_id, name=label,
        description=(description or "").strip() or None, kind=kind, duration_minutes=duration_minutes,
        buffer_before_minutes=0 if buffer_before_minutes is None else buffer_before_minutes,
        buffer_after_minutes=default_buffer if buffer_after_minutes is None else buffer_after_minutes,
        price=product_price if price is None else price, resource_mode=resource_mode,
        capacity=capacity if kind == "class" else 1, show_publicly=show_publicly,
        processing_start_minutes=processing_start_minutes, processing_minutes=processing_minutes,
        deposit_amount=deposit_amount, deposit_percent=deposit_percent, recall_days=recall_days,
        needs_patch_test=needs_patch_test, group_late_cancel_hours=group_late_cancel_hours)
    repo.add(session, offer)
    _set_resources(session, offer, resource_ids or [])
    audit_record(session, "create", "bookings.service_offer", offer.id, {"name": label})
    return offer


def _check_shape(kind: str, resource_mode: str, capacity: int) -> None:
    if kind not in rules.OFFER_KINDS:
        raise ValidationFailed(f"Kind must be one of: {', '.join(rules.OFFER_KINDS)}")
    if resource_mode not in rules.RESOURCE_MODES:
        raise ValidationFailed("A service needs 'any' or 'all' of its resources")
    if kind == "class" and capacity < 1:
        raise ValidationFailed("A class has room for at least one person")


def _check_processing(duration: int, start: int, minutes: int) -> None:
    if start < 0 or minutes < 0 or start + minutes > duration:
        raise ValidationFailed("The free minutes (while colour sets, for example) must fit inside the service")


def update_offer(session: Session, offer_id: UUID, *, resource_ids: list[UUID] | None = None,
                 **changes: object) -> ServiceOffer:
    """Change a bookable service. Appointments already made keep the price and duration they were booked with.
    Needs 'bookings.setup'."""
    offer = _visible(session, offer_id, lock=True)
    ctx = current_context()
    ctx.require(BOOKINGS_SETUP, company_id=offer.company_id)
    done: dict[str, object] = {}
    allowed = ("description", "duration_minutes", "buffer_before_minutes", "buffer_after_minutes", "price",
               "resource_mode", "capacity", "show_publicly", "is_active", "name", "product_id",
               "processing_start_minutes", "processing_minutes", "deposit_amount", "deposit_percent", "recall_days",
               "needs_patch_test", "group_late_cancel_hours")
    nullable = ("description", "recall_days", "group_late_cancel_hours")
    for key, value in changes.items():
        if key not in allowed or (value is None and key not in nullable):
            continue
        if key == "name":
            value = rules.check_name(str(value), "The service name")
        elif key == "product_id":
            _check_product(session, offer.company_id, UUID(str(value)), offer.id)
        elif key == "resource_mode" and value not in rules.RESOURCE_MODES:
            raise ValidationFailed("A service needs 'any' or 'all' of its resources")
        elif key == "description":
            value = (str(value) if value else "").strip() or None
        setattr(offer, key, value)
        done[key] = str(value)
        if key == "price":
            offer.price_is_example = False          # the business set its own price
    _check_processing(offer.duration_minutes, offer.processing_start_minutes, offer.processing_minutes)
    if resource_ids is not None:
        _set_resources(session, offer, resource_ids)
        done["resources"] = str(len(resource_ids))
    offer.updated_by, offer.updated_at = ctx.user_id, datetime.now(UTC)
    session.flush()
    audit_record(session, "update", "bookings.service_offer", offer.id, done)
    return offer

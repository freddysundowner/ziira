"""What a service costs for a given person: the offer's price, or a variant for that person's level (a senior stylist
charges more) or for something about the client (long hair). Variants are data the business enters."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.bookings.domain import rules
from ziira.modules.bookings.permissions import BOOKINGS_SETUP
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import Resource, ServiceOffer
from ziira.modules.bookings.services import access
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, current_context


def variants_of(session: Session, offer_id: UUID, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    return raw.many(session, "select * from bookings.price_variant where offer_id = :o "
                             f"{'' if include_inactive else 'and is_active '}order by sort_order, label", o=offer_id)


def price_for(session: Session, offer: ServiceOffer, resources: list[Resource],
              variant: str | None = None) -> tuple[Decimal, str | None]:
    """(price, variant label). A named variant wins; else the variant for the serving person's level; else the offer's
    price. Matching of levels and labels ignores case."""
    found = variants_of(session, offer.id)
    if variant:
        for v in found:
            if v["label"].casefold() == variant.casefold():
                return v["price"], v["label"]
        raise ValidationFailed(f"{offer.name} has no price called '{variant}'")
    levels = {(r.level or "").casefold() for r in resources if r.level}
    for v in found:
        if v["level"] and v["level"].casefold() in levels:
            return v["price"], v["label"]
    return offer.price, None


def set_variants(session: Session, offer_id: UUID, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace a service's price variants. Each has a label and a price, and optionally the staff level it applies to
    (everyone of that level is priced so automatically). Needs 'bookings.setup'."""
    offer = repo.get_offer(session, offer_id, lock=True)
    if offer is None or not access.can_see_company(offer.company_id):
        raise NotFound("Service not found")
    current_context().require(BOOKINGS_SETUP, company_id=offer.company_id)
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        label = rules.check_name(item.get("label", ""), "The price name")
        price = Decimal(item.get("price", 0))
        if price < 0:
            raise ValidationFailed("A price cannot be negative")
        if label.casefold() in seen:
            raise ValidationFailed(f"'{label}' is listed twice")
        seen.add(label.casefold())
        clean.append({"offer_id": offer.id, "label": label, "level": (item.get("level") or "").strip() or None,
                      "price": price, "sort_order": i, "is_active": bool(item.get("is_active", True))})
    raw.run(session, "delete from bookings.price_variant where offer_id = :o", o=offer.id)
    out = [raw.insert(session, "price_variant", c, user_id=current_context().user_id) for c in clean]
    audit_record(session, "variants", "bookings.service_offer", offer.id, {"count": len(out)})
    return out

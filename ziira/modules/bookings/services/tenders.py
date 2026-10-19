"""Paying a checkout with a voucher, points or any other credit a unit offers through `bookings.checkout_tender`."""

from decimal import Decimal
from uuid import UUID

from ziira.modules.bookings.tender import CHECKOUT_TENDER, CheckoutTender, TenderBalance, TenderUse
from ziira.sdk import Session, ValidationFailed, implementations

SOURCE = "bookings.checkout"


def providers(session: Session) -> dict[str, CheckoutTender]:
    """The ways of paying that units on for this business offer, by kind."""
    return {p.kind: p for p in implementations(session, CHECKOUT_TENDER) if getattr(p, "kind", "")}


def available(session: Session) -> list[dict[str, object]]:
    """What the desk can offer: [{kind, label, needs_code}]."""
    return [{"kind": p.kind, "label": p.label or p.kind, "needs_code": p.needs_code}
            for p in providers(session).values()]


def balance(session: Session, kind: str, *, customer_id: UUID | None, code: str | None) -> TenderBalance | None:
    provider = providers(session).get(kind)
    if provider is None:
        raise ValidationFailed("That way of paying is not available")
    return provider.balance(session, customer_id=customer_id, code=(code or "").strip() or None)


def redeem(session: Session, *, kind: str, code: str | None, amount: Decimal, customer_id: UUID, invoice_id: UUID,
           checkout_id: UUID) -> TenderUse:
    """Take `amount` from the credit and settle that much of the invoice."""
    provider = providers(session).get(kind)
    if provider is None:
        raise ValidationFailed("That way of paying is not available")
    if amount <= 0:
        raise ValidationFailed("Pay with more than nothing")
    done = provider.redeem(session, customer_id=customer_id, code=(code or "").strip() or None, amount=amount,
                           invoice_id=invoice_id, source_type=SOURCE, source_id=checkout_id)
    if done.applied <= 0 or done.applied > amount:
        raise ValidationFailed(f"{provider.label or kind} could not be used for that amount")
    if done.applied != amount:
        raise ValidationFailed(f"{provider.label or kind} covers only {done.applied}: change the amount")
    return done

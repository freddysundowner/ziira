"""The contract for paying a checkout with something that is not cash or a card: a gift voucher, loyalty points, a gym
credit. The unit that owns that credit (Memberships, a gym pack) implements `CheckoutTender` and plugs it into the
extension point `bookings.checkout_tender`; Bookings lists the kinds it finds, asks each for a balance, and redeems it
as part of completing a checkout. See docs/memberships.md ("Paying at the front desk")."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.sdk import Session

CHECKOUT_TENDER = "bookings.checkout_tender"


@dataclass(frozen=True)
class TenderBalance:
    """What a code (or a client) can still pay with, in money, and a short plain description for the screen."""

    available: Decimal
    description: str = ""


@dataclass(frozen=True)
class TenderUse:
    """What was really taken: the amount (never more than asked) and a reference for the receipt."""

    applied: Decimal
    reference: str = ""


class CheckoutTender(ABC):
    """One way of paying that the business holds the credit for.

    `kind` is a short stable word ("voucher", "loyalty"); `label` is what the desk sees ("Gift voucher", "Points").
    A provider must be safe to call twice for the same `(source_type, source_id)`: the second call takes nothing
    more."""

    kind: str = ""
    label: str = ""
    needs_code: bool = True            # a voucher is found by its code; points belong to the client

    @abstractmethod
    def balance(self, session: Session, *, customer_id: UUID | None, code: str | None) -> TenderBalance | None:
        """What the code (or the client's account) can pay now, or None when the code is unknown or used up."""

    @abstractmethod
    def redeem(self, session: Session, *, customer_id: UUID, code: str | None, amount: Decimal, invoice_id: UUID,
               source_type: str, source_id: UUID) -> TenderUse:
        """Take up to `amount` from the credit and **settle that much of the invoice**: call
        `pos.public.settle_invoice_non_cash(session, invoice_id, applied, kind=..., reference=...)` after you have moved
        your own liability. Bookings checks that the invoice came down by the amount you report. Raise
        `ValidationFailed` with a plain sentence when it cannot be used."""

    def release(self, session: Session, *, source_type: str, source_id: UUID) -> None:  # noqa: B027
        """Give back what `redeem` took for that source (a checkout reversed). Optional."""

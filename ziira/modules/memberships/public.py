"""Public interface of the Memberships module: what other units (bookings, jobs, time billing, industry packs) call.

Stable signatures, all taking the caller's session (the caller has checked its own permissions):

* `member_credit_balance(session, customer_id, service_ref=None)`: credits the customer can spend now.
* `consume_credit(session, *, customer_id, service_ref, quantity, source_type, source_id)`: pay a service with credits,
  once per source. Returns `CreditUse(covered, remaining, discount_percent, ...)`: `covered` was paid with credits;
  `remaining` is still to be charged, and the member's `discount_percent` applies to it.
* `release_credit(session, *, source_type, source_id)`: give the credits of that source back (appointment cancelled).
* `active_membership(session, customer_id)`: the customer's active membership, or None.
* `member_discount_percent(session, customer_id)`: their discount on services (0 if none).

Events published: membership.activated, .renewed, .paused, .resumed, .cancelled, .expired; package.sold, .used,
.expiring, .expired. See docs/memberships.md.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.memberships.domain.credits import ZERO
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, credits
from ziira.modules.memberships.services.credits import CreditUse
from ziira.sdk import Session

__all__ = ["CreditUse", "MembershipView", "active_membership", "consume_credit", "member_credit_balance",
           "member_discount_percent", "release_credit"]


@dataclass(frozen=True)
class MembershipView:
    """What other units need to know about a membership."""

    id: UUID
    company_id: UUID
    customer_id: UUID
    number: str
    plan_id: UUID
    plan_name: str
    status: str
    next_renewal_date: date
    discount_percent: Decimal
    credits_balance: Decimal


def member_credit_balance(session: Session, customer_id: UUID, service_ref: str | None = None) -> Decimal:
    """The credits the customer can spend today on a service (all services when `service_ref` is None): membership
    credits and unexpired packages that cover it."""
    customer = common.customer_of_any(session, customer_id)
    day = common.today(session, customer.company_id)
    return sum((h.balance for h in credits.holders(session, customer_id, day)
                if h.balance > ZERO and (service_ref is None or h.pays_for(service_ref))), ZERO)


def consume_credit(session: Session, *, customer_id: UUID, service_ref: str | None, quantity: Decimal,
                   source_type: str, source_id: UUID) -> CreditUse:
    """Pay `quantity` of a service with the customer's credits. Idempotent by (source_type, source_id)."""
    return credits.consume(session, customer_id=customer_id, service_ref=service_ref, quantity=quantity,
                           source_type=source_type, source_id=source_id)


def release_credit(session: Session, *, source_type: str, source_id: UUID) -> Decimal:
    """Give back the credits spent for a source. Returns how much came back (0 if nothing was spent or already given
    back)."""
    return credits.release(session, source_type=source_type, source_id=source_id)


def active_membership(session: Session, customer_id: UUID) -> MembershipView | None:
    """The customer's active membership (the one that renews first when they have several), or None."""
    row = repo.one(session, "select * from memberships.member where customer_id = :c and status = 'active' "
                            "order by next_renewal_date, number limit 1", c=customer_id)
    if row is None:
        return None
    return MembershipView(row["id"], row["company_id"], row["customer_id"], row["number"], row["plan_id"],
                          row["plan_name"], row["status"], row["next_renewal_date"], row["discount_percent"],
                          repo.holder_balance(session, row["id"]))


def member_discount_percent(session: Session, customer_id: UUID) -> Decimal:
    """The customer's discount on services from their active membership(s)."""
    return credits.member_discount(session, customer_id)

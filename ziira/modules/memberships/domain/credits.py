"""Which credits pay for a service: pure rules, no database.

A person may hold credits from their membership (they expire at the end of the period unless the plan rolls them over)
and from packages they bought. A visit is paid from the membership first, then from the package that expires soonest.
Balances never go below zero unless the business allows overdraw."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

MEMBERSHIP = "membership"
PACKAGE = "package"
ZERO = Decimal(0)


@dataclass(frozen=True)
class Holder:
    """Something that holds credits for a customer: a membership or a package they bought."""

    id: str
    kind: str                       # "membership" or "package"
    balance: Decimal
    covers: tuple[str, ...] = ()    # services it pays for; empty means every service
    expires_on: date | None = None

    def pays_for(self, service_ref: str | None) -> bool:
        return not self.covers or (service_ref is not None and service_ref in self.covers)


@dataclass(frozen=True)
class Take:
    holder_id: str
    quantity: Decimal               # positive: how much to take from the holder


def _order(holder: Holder) -> tuple[int, date, str]:
    return (0 if holder.kind == MEMBERSHIP else 1, holder.expires_on or date.max, holder.id)


def allocate(holders: list[Holder], quantity: Decimal, service_ref: str | None, *,
             overdraw: bool = False) -> tuple[list[Take], Decimal]:
    """Take `quantity` credits from the holders that cover the service, in order. Returns the takes and what is left
    to pay another way. With `overdraw` the first holder that covers the service goes below zero for the rest."""
    left = quantity
    takes: list[Take] = []
    eligible = sorted((h for h in holders if h.pays_for(service_ref)), key=_order)
    for holder in eligible:
        if left <= ZERO:
            break
        if holder.balance <= ZERO:
            continue
        got = min(holder.balance, left)
        takes.append(Take(holder.id, got))
        left -= got
    if left > ZERO and overdraw and eligible:
        merged = {t.holder_id: t.quantity for t in takes}
        merged[eligible[0].id] = merged.get(eligible[0].id, ZERO) + left
        takes = [Take(holder, qty) for holder, qty in merged.items()]
        left = ZERO
    return takes, left

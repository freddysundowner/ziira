"""Choosing batches: first expiry, first out. Pure Python: no database, no HTTP."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class BatchStock:
    """How much of one batch a location holds."""

    batch_id: UUID
    quantity: Decimal
    expiry_date: date | None


@dataclass(frozen=True)
class Pick:
    """Take `quantity` from a batch."""

    batch_id: UUID
    quantity: Decimal


def pick_first_expiry_first_out(available: list[BatchStock], needed: Decimal) -> tuple[list[Pick], Decimal]:
    """Choose batches to cover `needed`, earliest expiry first (no expiry date last).

    Returns the picks and the shortage (how much could not be covered, zero if all was).
    Batches with nothing on hand are skipped; ties keep a stable order by batch id.
    """
    if needed <= 0:
        raise ValueError("Pick a positive quantity")
    ordered = sorted((b for b in available if b.quantity > 0),
                     key=lambda b: (b.expiry_date is None, b.expiry_date or date.max, str(b.batch_id)))
    picks: list[Pick] = []
    remaining = needed
    for batch in ordered:
        if remaining == 0:
            break
        take = min(batch.quantity, remaining)
        picks.append(Pick(batch.batch_id, take))
        remaining -= take
    return picks, remaining

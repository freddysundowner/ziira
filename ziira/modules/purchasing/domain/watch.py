"""Pure rules behind the Intelligence checks and figures of Purchasing: price movements and look-alike documents."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

HUNDRED = Decimal(100)


def price_rise(costs: list[Decimal], min_earlier: int) -> tuple[Decimal, Decimal, Decimal] | None:
    """(latest, average of the earlier ones, percent the latest is above that average) for costs oldest first.

    None when there are fewer than `min_earlier` earlier costs (too little history to say what is usual) or the
    average is not above zero.
    """
    if len(costs) < min_earlier + 1 or min_earlier < 1:
        return None
    earlier = costs[:-1]
    average = sum(earlier, Decimal(0)) / len(earlier)
    if average <= 0:
        return None
    latest = costs[-1]
    return latest, average, (latest - average) / average * HUNDRED


def normalise_reference(value: str | None) -> str:
    """A supplier's invoice or credit number without spaces, dashes or case, so "INV-001" and "inv 001" match."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


@dataclass(frozen=True)
class BillStub:
    """What is needed of a bill to see whether it looks like another one."""

    id: UUID
    supplier_id: UUID
    invoice_no: str
    bill_date: date
    total: Decimal


def duplicate_bills(bills: list[BillStub], within_days: int) -> list[tuple[BillStub, BillStub, str]]:
    """Pairs (earlier, later, reason) of one supplier's bills that look like the same bill entered twice: the same
    amount within `within_days` days of each other, or the same invoice number written differently."""
    found: list[tuple[BillStub, BillStub, str]] = []
    ordered = sorted(bills, key=lambda b: (str(b.supplier_id), b.bill_date, str(b.id)))
    for i, first in enumerate(ordered):
        for second in ordered[i + 1:]:
            if second.supplier_id != first.supplier_id:
                break
            same_number = normalise_reference(first.invoice_no) != "" \
                and normalise_reference(first.invoice_no) == normalise_reference(second.invoice_no)
            same_amount = first.total == second.total and abs((second.bill_date - first.bill_date).days) <= within_days
            if same_number:
                found.append((first, second, "the same supplier invoice number"))
            elif same_amount:
                found.append((first, second, "the same amount within days of each other"))
    return found


@dataclass(frozen=True)
class PaymentStub:
    """What is needed of a payment to a supplier to see whether it looks like another one."""

    payment_id: UUID
    bill_id: UUID
    supplier_id: UUID
    number: str
    day: date
    amount: Decimal
    reference: str | None


def duplicate_payments(payments: list[PaymentStub], within_days: int) -> list[tuple[PaymentStub, PaymentStub, str]]:
    """Pairs (earlier, later, reason) of different payments to one supplier for the same amount within `within_days`
    days, or carrying the same payment reference."""
    found: list[tuple[PaymentStub, PaymentStub, str]] = []
    ordered = sorted(payments, key=lambda p: (str(p.supplier_id), p.day, p.number))
    for i, first in enumerate(ordered):
        for second in ordered[i + 1:]:
            if second.supplier_id != first.supplier_id:
                break
            if second.payment_id == first.payment_id:
                continue
            ref = normalise_reference(first.reference)
            if ref and ref == normalise_reference(second.reference):
                found.append((first, second, "the same payment reference"))
            elif first.amount == second.amount and abs((second.day - first.day).days) <= within_days:
                found.append((first, second, "the same amount within days of each other"))
    return found

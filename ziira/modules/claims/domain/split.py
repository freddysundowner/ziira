"""Who is invoiced what. Pure Python.

The payer is invoiced for what it pays less the customer's excess (spread over the payer's lines as discounts, so no
invoice line is negative). The customer is invoiced for the excess, for rejected lines they agreed to pay, and for the
difference of counter-offers they agreed to carry. Every cent is somewhere: payer net + excess = payer gross.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.domain.money import ZERO, allocate


@dataclass(frozen=True)
class BillableLine:
    line_id: UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    facts: rules.LineFacts


@dataclass(frozen=True)
class PayerPart:
    line_id: UUID
    description: str
    gross: Decimal
    discount: Decimal              # this line's share of the excess

    @property
    def net(self) -> Decimal:
        return self.gross - self.discount


@dataclass(frozen=True)
class CustomerPart:
    kind: str                      # excess | rejected_line | shortfall
    description: str
    amount: Decimal
    line_id: UUID | None = None


@dataclass
class Split:
    payer_parts: list[PayerPart] = field(default_factory=list)
    customer_parts: list[CustomerPart] = field(default_factory=list)
    excess_applied: Decimal = ZERO
    absorbed: Decimal = ZERO       # what the business gives up on accepted counter-offers

    @property
    def payer_gross(self) -> Decimal:
        return sum((p.gross for p in self.payer_parts), ZERO)

    @property
    def payer_net(self) -> Decimal:
        return sum((p.net for p in self.payer_parts), ZERO)

    @property
    def customer_total(self) -> Decimal:
        return sum((p.amount for p in self.customer_parts), ZERO)


def compute_split(lines: list[BillableLine], *, excess: Decimal, embedded_before: Decimal = ZERO,
                  charged_before: Decimal = ZERO, gross_before: Decimal = ZERO) -> Split:
    """Split the lines that are ready to be invoiced.

    `excess` is the claim's excess. Earlier invoices of the claim (leaving out lines since credited) already carry
    `embedded_before` of it as discounts on the payer's lines, on payer lines worth `gross_before`, and the customer was
    already charged `charged_before`. Normally the last two figures are equal; they differ after the payer reduced an
    invoiced line (its discount was credited with it but the customer's excess charge stands)."""
    split = Split()
    gross: list[Decimal] = []
    for line in lines:
        pays = rules.payer_pays(line.facts)
        if pays > 0:
            gross.append(pays)
    target = min(excess, gross_before + sum(gross, ZERO))
    in_this_run = min(max(target - embedded_before, ZERO), sum(gross, ZERO))
    split.excess_applied = max(target - charged_before, ZERO)
    shares = allocate(in_this_run, gross) if gross else []
    index = 0
    for line in lines:
        pays = rules.payer_pays(line.facts)
        if pays > 0:
            split.payer_parts.append(PayerPart(line.line_id, line.description, pays, shares[index]))
            index += 1
    if split.excess_applied > 0:
        split.customer_parts.append(CustomerPart("excess", "Excess (your share of the claim)", split.excess_applied))
    for line in lines:
        owed = rules.customer_owes(line.facts)
        if owed > 0:
            kind = "rejected_line" if line.facts.payer_state == "rejected" else "shortfall"
            label = line.description if kind == "rejected_line" else f"{line.description} (not covered)"
            split.customer_parts.append(CustomerPart(kind, label, owed, line.line_id))
        split.absorbed += rules.business_absorbs(line.facts)
    return split

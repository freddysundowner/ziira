"""What a payer's answer to a line means for the money. Pure Python.

A line is asked for (`asked_total`). The payer answers: approved (the whole asked amount), countered (they offer a lower
amount), rejected (with a reason) or needs information. After a counter the business accepts it (the line is worth the
offer) or declines it (the line is argued again in the next version). A rejected line waits for the customer: they agree
to pay it, or decline the work. When a counter is accepted the business says who carries the difference: the customer
(betterment, a part the policy does not cover in full) or the business (it absorbs it).
"""

from dataclasses import dataclass
from decimal import Decimal

from ziira.modules.claims.domain.money import ZERO

PAYER_STATES = ("pending", "approved", "countered", "rejected", "needs_information")
ANSWERS = ("approved", "countered", "rejected", "needs_information")
RESPONSES = ("accepted", "partly_accepted", "countered", "rejected", "needs_information", "withdrawn")
KINDS = ("labour", "parts", "paint", "sundries", "other")
PART_CLASSES = ("genuine", "aftermarket", "used")


@dataclass(frozen=True)
class LineFacts:
    """The parts of a line that decide who pays."""

    asked_total: Decimal
    payer_state: str
    payer_amount: Decimal | None = None
    our_decision: str | None = None           # accepted | declined (about a counter-offer)
    customer_decision: str | None = None      # pays | declined (about a rejected line)
    shortfall_to: str | None = None           # customer | business (who carries a countered line's difference)


def payer_pays(line: LineFacts) -> Decimal:
    """What the payer will pay for this line."""
    if line.payer_state == "approved":
        return line.asked_total
    if line.payer_state == "countered" and line.our_decision == "accepted":
        return line.payer_amount if line.payer_amount is not None else ZERO
    return ZERO


def customer_owes(line: LineFacts) -> Decimal:
    """What the customer will pay for this line: a rejected line they agreed to pay, or the difference of an accepted
    counter-offer that they agreed to carry."""
    if line.payer_state == "rejected" and line.customer_decision == "pays":
        return line.asked_total
    if line.payer_state == "countered" and line.our_decision == "accepted" and line.shortfall_to == "customer":
        return line.asked_total - payer_pays(line)
    return ZERO


def business_absorbs(line: LineFacts) -> Decimal:
    """What the business gives up on this line (an accepted counter-offer whose difference it carries)."""
    if line.payer_state == "countered" and line.our_decision == "accepted" and line.shortfall_to != "customer":
        return line.asked_total - payer_pays(line)
    return ZERO


def is_open(line: LineFacts) -> bool:
    """True while the line still waits for someone: the payer's answer, the business's answer to a counter, or the
    customer's answer about a rejected line."""
    if line.payer_state in ("pending", "needs_information"):
        return True
    if line.payer_state == "countered":
        return line.our_decision is None
    if line.payer_state == "rejected":
        return line.customer_decision is None
    return False


def is_payable(line: LineFacts) -> bool:
    return payer_pays(line) > 0


def is_authorised_work(line: LineFacts) -> bool:
    """May the workshop do this line? Approved, an accepted counter-offer, or a rejected line the customer will pay."""
    return payer_pays(line) > 0 or customer_owes(line) > 0


def check_answer(state: str, asked_total: Decimal, amount: Decimal | None, reason: str | None) -> Decimal | None:
    """Check one answer and return the amount to keep. Raises ValueError with a message for the person."""
    if state not in ANSWERS:
        raise ValueError("An answer is approved, countered, rejected or needs information")
    if state == "approved":
        if amount is not None and amount != asked_total:
            raise ValueError("Approving a line approves the whole amount asked: counter with a lower amount instead")
        return asked_total
    if state == "countered":
        if amount is None:
            raise ValueError("A counter-offer needs the amount the payer offers")
        if amount < 0 or amount >= asked_total:
            raise ValueError("A counter-offer is below the amount asked")
        return amount
    if state == "rejected" and not (reason or "").strip():
        raise ValueError("A rejected line needs the payer's reason")
    return None


def overall_response(states: list[str]) -> str | None:
    """The whole-estimate answer from the states of its lines, or None while any line is still waiting for the first
    answer."""
    if not states or any(s == "pending" for s in states):
        return None
    kinds = set(states)
    if kinds == {"approved"}:
        return "accepted"
    if kinds == {"needs_information"}:
        return "needs_information"
    if kinds == {"rejected"}:
        return "rejected"
    if "countered" in kinds:
        return "countered"
    if "needs_information" in kinds:
        return "needs_information"
    return "partly_accepted"

"""Prepaid retainers: drawing time down from a balance. Pure rules.

An hours retainer holds a balance of prepaid minutes. Approved billable time on its project first uses the balance; what
the balance cannot cover is billed in the usual way (the overage). A monthly-fee retainer covers all of the project's
time with a fixed fee that is billed once per month.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Drawdown:
    covered: int            # minutes taken from the retainer
    overage: int            # minutes it could not cover (to be billed)
    balance_after: int


def draw_down(balance: int, minutes: int) -> Drawdown:
    """Take `minutes` from a balance (never below zero)."""
    if balance < 0 or minutes < 0:
        raise ValueError("Balance and minutes cannot be negative")
    covered = min(balance, minutes)
    return Drawdown(covered, minutes - covered, balance - covered)


def is_expired(expires_on: date | None, day: date) -> bool:
    """A retainer is usable through its expiry date and not after."""
    return expires_on is not None and day > expires_on


def share_used(total_topped_up: int, balance: int) -> int:
    """Percent of everything paid in that has been used (0 when nothing was paid in)."""
    if total_topped_up <= 0:
        return 0
    return max(0, min(100, round((total_topped_up - balance) * 100 / total_topped_up)))

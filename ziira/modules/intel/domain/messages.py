"""The words of an alert: short, plain, with what to do. Figures come from the finding, never from a guess."""

from decimal import Decimal


def alert_text(severity: str, summary: str, action: str | None, amount: Decimal | None = None,
               currency: str = "") -> str:
    """A one-message alert that fits an SMS reasonably: severity, what happened, what to do."""
    head = f"[{severity.upper()}] {summary}"
    if amount and amount > 0:
        head += f" ({currency} {amount:,.2f})".replace("( ", "(")
    return (head + (f" Next: {action}" if action else ""))[:900]


def alert_subject(severity: str, summary: str) -> str:
    clipped = summary if len(summary) <= 80 else summary[:77] + "..."
    return f"[{severity}] {clipped}"

"""The words of a brief: what happened, what needs attention. Pure: it formats what it is given."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ziira.sdk import format_day


@dataclass(frozen=True)
class PulseLine:
    """A figure ready to show: its label, the number (money in the company currency), and how it moved."""

    label: str
    kind: str
    value: Decimal
    previous: Decimal | None = None
    branch_name: str | None = None


@dataclass(frozen=True)
class FindingLine:
    severity: str
    summary: str
    action: str | None


@dataclass(frozen=True)
class Brief:
    subject: str
    body: str
    short: str


def fmt(value: Decimal, kind: str, currency: str) -> str:
    if kind == "money":
        return f"{currency} {value:,.2f}".strip()
    if kind == "percent":
        return f"{value:,.1f}%"
    return f"{value:,.0f}"


def change(value: Decimal, previous: Decimal | None) -> str:
    """How a figure moved against the day before, as a short phrase ('up 12%'), or nothing when there is no basis."""
    if previous is None or previous == 0:
        return ""
    pct = (value - previous) / abs(previous) * 100
    if abs(pct) < Decimal("0.5"):
        return " (flat)"
    return f" ({'up' if pct > 0 else 'down'} {abs(pct):,.0f}%)"


def compose(*, business: str, day: date, kind: str, currency: str, pulse: list[PulseLine],
            findings: list[FindingLine], more_findings: int = 0) -> Brief:
    """A brief in plain words. `short` is the SMS form (top items only); `body` is the full text (email, app)."""
    period = "Yesterday" if kind == "daily" else "Last 7 days"
    title = f"{business}: {'daily' if kind == 'daily' else 'weekly'} brief, {format_day(day)}"
    lines = [title, ""]
    if pulse:
        lines.append(f"{period}")
        for p in pulse:
            where = f" [{p.branch_name}]" if p.branch_name else ""
            lines.append(f"- {p.label}{where}: {fmt(p.value, p.kind, currency)}{change(p.value, p.previous)}")
        lines.append("")
    if findings:
        lines.append("Needs your attention")
        for i, f in enumerate(findings, 1):
            lines.append(f"{i}. [{f.severity}] {f.summary}" + (f" Next: {f.action}" if f.action else ""))
        if more_findings > 0:
            lines.append(f"...and {more_findings} more in the Command Center.")
    elif pulse:
        lines.append("Nothing needs your attention.")
    body = "\n".join(lines).strip()
    top = [f"{business} {period.lower()}:"]
    top += [f"{p.label} {fmt(p.value, p.kind, currency)}" for p in pulse[:3] if not p.branch_name]
    short = " ".join(top)
    if findings:
        short += f" Attention: {findings[0].summary}" + (f" (+{len(findings) - 1 + max(more_findings, 0)} more)"
                                                          if len(findings) > 1 or more_findings > 0 else "")
    else:
        short += " Nothing needs attention."
    return Brief(subject=title, body=body, short=short[:900])

"""What a payslip looks like on paper or screen: text for a plain printer, HTML for A4. Pure Python.

Everything that came from a user is escaped. No country's layout is assumed: the lines are the business's own pay
items and statutory rules.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from html import escape

WIDTHS = (32, 40, 48, 80)


@dataclass
class PayslipDocument:
    header: list[str]                                     # the company: name, tax number
    title: str                                            # "Payslip"
    period: str                                           # "2026-09-01 to 2026-09-30"
    employee: list[tuple[str, str]]                       # label, value: name, number, tax number, branch ...
    earnings: list[tuple[str, Decimal]] = field(default_factory=list)
    benefits: list[tuple[str, Decimal]] = field(default_factory=list)
    deductions: list[tuple[str, Decimal]] = field(default_factory=list)
    totals: list[tuple[str, Decimal]] = field(default_factory=list)    # gross, deductions, net (last is the headline)
    notes: list[str] = field(default_factory=list)
    copy: bool = False


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _wrap(text: str, width: int) -> list[str]:
    words, rows, row = text.split(), [], ""
    for word in words:
        while len(word) > width:
            if row:
                rows.append(row)
                row = ""
            rows.append(word[:width])
            word = word[width:]
        if len(row) + len(word) + (1 if row else 0) > width:
            rows.append(row)
            row = word
        else:
            row = f"{row} {word}".strip()
    if row:
        rows.append(row)
    return rows or [""]


def _two(left: str, right: str, width: int) -> list[str]:
    room = max(width - len(right) - 1, 8)
    parts = _wrap(left, room)
    parts[-1] = parts[-1] + " " * max(width - len(parts[-1]) - len(right), 1) + right
    return parts


def render_text(doc: PayslipDocument, width: int = 40) -> str:
    """The payslip as plain text, `width` characters across."""
    if width not in WIDTHS:
        raise ValueError(f"width must be one of {WIDTHS}")
    rule = "-" * width
    out: list[str] = []
    for row in doc.header:
        out += [r.center(width).rstrip() for r in _wrap(row, width)]
    out += [rule, doc.title.upper().center(width).rstrip(), doc.period.center(width).rstrip()]
    if doc.copy:
        out.append("*** COPY ***".center(width).rstrip())
    out.append(rule)
    for label, value in doc.employee:
        out += _wrap(f"{label}: {value}", width)
    for heading, items in (("Earnings", doc.earnings), ("Benefits (not paid in cash)", doc.benefits),
                           ("Deductions", doc.deductions)):
        if items:
            out += [rule, heading]
            for label, amount in items:
                out += _two(f"  {label}", money(amount), width)
    out.append(rule)
    for label, amount in doc.totals:
        out += _two(label, money(amount), width)
    for note in doc.notes:
        out += _wrap(note, width)
    return "\n".join(out) + "\n"


def render_html(doc: PayslipDocument) -> str:
    """The payslip as a self-contained HTML page. All text is escaped."""
    e = escape

    def table(items: list[tuple[str, Decimal]], heading: str) -> str:
        if not items:
            return ""
        rows = "".join(f"<tr><td>{e(a)}</td><td class=n>{e(money(b))}</td></tr>" for a, b in items)
        return f"<h3>{e(heading)}</h3><table>{rows}</table>"

    head = "".join(f"<div>{e(h)}</div>" for h in doc.header)
    who = "".join(f"<div><b>{e(a)}:</b> {e(b)}</div>" for a, b in doc.employee)
    totals = "".join(f"<tr><td><b>{e(a)}</b></td><td class=n><b>{e(money(b))}</b></td></tr>" for a, b in doc.totals)
    notes = "".join(f"<p>{e(n)}</p>" for n in doc.notes)
    copy = "<div class=copy>COPY</div>" if doc.copy else ""
    return (
        "<!doctype html><html><head><meta charset=utf-8>"
        f"<title>{e(doc.title)} {e(doc.period)}</title><style>"
        "body{font:14px sans-serif;max-width:640px;margin:2em auto;color:#111}"
        "table{width:100%;border-collapse:collapse}td{padding:4px 6px;border-bottom:1px solid #ddd}"
        ".n{text-align:right}.copy{font-weight:bold;letter-spacing:.3em}"
        "</style></head><body>"
        f"<div>{head}</div><h1>{e(doc.title)}</h1><div>{e(doc.period)}</div>{copy}<div>{who}</div>"
        f"{table(doc.earnings, 'Earnings')}{table(doc.benefits, 'Benefits (not paid in cash)')}"
        f"{table(doc.deductions, 'Deductions')}<h3>Totals</h3><table>{totals}</table>{notes}</body></html>")

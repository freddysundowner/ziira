"""What a printed receipt or invoice looks like: plain rules, no database. Text is for thermal printers (a fixed
number of characters per line); HTML is for A4 and the screen. Everything that came from a user is escaped."""

from dataclasses import dataclass, field
from decimal import Decimal
from html import escape

WIDTHS = (32, 40, 48)


@dataclass(frozen=True)
class PrintLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class VatRow:
    rate: Decimal
    net: Decimal
    tax: Decimal


@dataclass
class PrintDocument:
    title: str                                   # "Receipt", "Tax invoice", "Payment receipt"
    number: str
    header: list[str]                            # company, branch, address, phone, PIN
    meta: list[tuple[str, str]]                  # label, value: date, cashier, customer, due date ...
    lines: list[PrintLine] = field(default_factory=list)
    vat: list[VatRow] = field(default_factory=list)
    totals: list[tuple[str, Decimal]] = field(default_factory=list)      # label, amount; the last one is the headline
    payments: list[tuple[str, Decimal]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    footer: list[str] = field(default_factory=list)
    copy: bool = False                           # reprint: marked "COPY"


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def quantity(value: Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _wrap(text: str, width: int) -> list[str]:
    words, rows, row = text.split(), [], ""
    for word in words:
        while len(word) > width:                  # a word longer than the paper
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


def _two(left: str, right: str, width: int) -> str:
    gap = max(width - len(left) - len(right), 1)
    return f"{left}{' ' * gap}{right}"[:max(width, len(left) + len(right) + 1)]


def render_text(doc: PrintDocument, width: int = 40) -> str:
    """The document as plain text, `width` characters across."""
    if width not in WIDTHS:
        raise ValueError(f"width must be one of {WIDTHS}")
    rule = "-" * width
    out: list[str] = []
    for row in doc.header:
        out += [r.center(width).rstrip() for r in _wrap(row, width)]
    out += [rule, _two(doc.title.upper(), doc.number, width)]
    if doc.copy:
        out.append("*** COPY ***".center(width).rstrip())
    for label, value in doc.meta:
        out += _wrap(f"{label}: {value}", width)
    if doc.lines:
        out.append(rule)
        for line in doc.lines:
            out += _wrap(line.description, width)
            out.append(_two(f"  {quantity(line.quantity)} x {money(line.unit_price)}", money(line.amount), width))
    out.append(rule)
    for label, amount in doc.totals:
        out.append(_two(label, money(amount), width))
    if doc.vat:
        out += [rule, "VAT".ljust(width)]
        out += [_two(f"  {quantity(v.rate)}% on {money(v.net)}", money(v.tax), width) for v in doc.vat]
    if doc.payments:
        out.append(rule)
        out += [_two(label, money(amount), width) for label, amount in doc.payments]
    for note in doc.notes:
        out += _wrap(note, width)
    if doc.footer:
        out.append(rule)
        for row in doc.footer:
            out += [r.center(width).rstrip() for r in _wrap(row, width)]
    return "\n".join(out) + "\n"


def render_html(doc: PrintDocument) -> str:
    """The document as a self-contained HTML page (A4 or screen). All text is escaped."""
    e = escape
    rows = "".join(
        f"<tr><td>{e(line.description)}</td><td class=n>{e(quantity(line.quantity))}</td>"
        f"<td class=n>{e(money(line.unit_price))}</td><td class=n>{e(money(line.amount))}</td></tr>"
        for line in doc.lines)
    table = (f"<table><thead><tr><th>Item</th><th class=n>Qty</th><th class=n>Price</th><th class=n>Amount</th></tr>"
             f"</thead><tbody>{rows}</tbody></table>") if doc.lines else ""

    def pairs(items: list[tuple[str, Decimal]], cls: str) -> str:
        body = "".join(f"<tr><td>{e(a)}</td><td class=n>{e(money(b))}</td></tr>" for a, b in items)
        return f"<table class={cls}>{body}</table>" if items else ""

    vat = ""
    if doc.vat:
        vat_rows = "".join(
            f"<tr><td>{e(quantity(v.rate))}% on {e(money(v.net))}</td><td class=n>{e(money(v.tax))}</td></tr>"
            for v in doc.vat)
        vat = f"<h3>VAT</h3><table class=sum>{vat_rows}</table>"
    meta = "".join(f"<div><b>{e(a)}:</b> {e(b)}</div>" for a, b in doc.meta)
    head = "".join(f"<div>{e(h)}</div>" for h in doc.header)
    notes = "".join(f"<p>{e(n)}</p>" for n in doc.notes)
    foot = "".join(f"<div>{e(f)}</div>" for f in doc.footer)
    copy = "<div class=copy>COPY</div>" if doc.copy else ""
    return (
        "<!doctype html><html><head><meta charset=utf-8>"
        f"<title>{e(doc.title)} {e(doc.number)}</title><style>"
        "body{font:14px sans-serif;max-width:720px;margin:2em auto;color:#111}"
        "table{width:100%;border-collapse:collapse}"
        "th,td{padding:4px 6px;border-bottom:1px solid #ddd;text-align:left}.n{text-align:right}"
        ".sum{width:50%;margin-left:auto}.copy{font-weight:bold;letter-spacing:.3em}h1{margin:.5em 0 0}"
        ".foot{margin-top:2em;text-align:center;color:#555}</style></head><body>"
        f"<div class=head>{head}</div><h1>{e(doc.title)} {e(doc.number)}</h1>{copy}{meta}{table}"
        f"{pairs(doc.totals, 'sum')}{vat}{pairs(doc.payments, 'sum')}{notes}<div class=foot>{foot}</div>"
        "</body></html>")

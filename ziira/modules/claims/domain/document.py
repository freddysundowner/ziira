"""The printable estimate: plain data turned into a self-contained HTML page (the browser prints it or saves it as a
PDF)
and a plain-text version for email. Everything typed by a person is escaped."""

from dataclasses import dataclass
from decimal import Decimal
from html import escape


@dataclass(frozen=True)
class DocLine:
    position: int
    kind: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    state: str = ""
    answer: str = ""


@dataclass(frozen=True)
class DocEstimate:
    business: str
    currency: str
    label: str
    claim_number: str
    payer: str
    policy_number: str
    insurer_claim_number: str
    subject: str
    loss_date: str
    notes: str
    valid_until: str
    lines: list[DocLine]
    total: Decimal
    link: str = ""


def money(value: Decimal, currency: str) -> str:
    return f"{currency} {value:,.2f}"


def render_text(doc: DocEstimate) -> str:
    rows = [f"{doc.business}", f"{doc.label}", f"To: {doc.payer}"]
    for caption, value in (("Our claim", doc.claim_number), ("Your claim number", doc.insurer_claim_number),
                           ("Policy", doc.policy_number), ("Item", doc.subject), ("Date of loss", doc.loss_date),
                           ("Valid until", doc.valid_until)):
        if value:
            rows.append(f"{caption}: {value}")
    rows.append("")
    for line in doc.lines:
        rows.append(f"{line.position}. {line.description}  {line.quantity:g} x {line.unit_price:,.2f} = "
                    f"{line.total:,.2f}")
    rows += ["", f"Total (tax included where it applies): {money(doc.total, doc.currency)}"]
    if doc.notes:
        rows += ["", doc.notes]
    if doc.link:
        rows += ["", f"Answer each line here: {doc.link}"]
    return "\n".join(rows)


def render_html(doc: DocEstimate) -> str:
    e = escape
    head = "".join(f"<tr><th>{e(c)}</th><td>{e(v)}</td></tr>" for c, v in (
        ("Our claim", doc.claim_number), ("Your claim number", doc.insurer_claim_number), ("Policy", doc.policy_number),
        ("Item", doc.subject), ("Date of loss", doc.loss_date), ("Valid until", doc.valid_until)) if v)
    body = "".join(
        f"<tr><td>{line.position}</td><td>{e(line.description)}<br><small>{e(line.kind)}</small></td>"
        f"<td class=n>{line.quantity:g}</td><td class=n>{line.unit_price:,.2f}</td><td class=n>{line.total:,.2f}</td>"
        f"<td>{e(line.answer)}</td></tr>" for line in doc.lines)
    notes = f"<p>{e(doc.notes)}</p>" if doc.notes else ""
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8><title>"
        f"{e(doc.label)}</title><style>body{{font:14px/1.4 system-ui,sans-serif;margin:2rem;color:#111}}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border-bottom:1px solid #ccc;padding:.4rem;"
        "text-align:left;vertical-align:top}.n{text-align:right}.meta th{width:12rem}small{color:#555}"
        "@media print{body{margin:0}}</style></head><body>"
        f"<h1>{e(doc.business)}</h1><h2>{e(doc.label)} for {e(doc.payer)}</h2>"
        f"<table class=meta>{head}</table>"
        "<table><thead><tr><th>#</th><th>Item</th><th class=n>Qty</th><th class=n>Price</th><th class=n>Total</th>"
        f"<th>Answer</th></tr></thead><tbody>{body}</tbody>"
        f"<tfoot><tr><th colspan=4 class=n>Total (tax included where it applies)</th>"
        f"<th class=n>{e(money(doc.total, doc.currency))}</th><th></th></tr></tfoot></table>{notes}</body></html>")

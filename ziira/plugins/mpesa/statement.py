"""Safaricom's M-Pesa business statement (CSV): Receipt No., Completion Time, Details, Status, Paid In, Withdrawn."""

import re

from ziira.modules.payments.public import (
    GENERIC_HEADER_WORDS,
    ParsedStatement,
    StatementReader,
    StatementRow,
    csv_rows,
    statement_amount,
    statement_time,
)
from ziira.plugins.mpesa.formats import EAT
from ziira.sdk import ValidationFailed

HEADER_WORDS = frozenset({"receiptno", "completiontime", "paidin", "withdrawn"}) | GENERIC_HEADER_WORDS
PHONE_IN_DETAILS = re.compile(r"(2547\*{4}\d{3}|254[17]\d{8}|07\d{8})")


def parse_mpesa_statement(text: str) -> ParsedStatement:
    """Read the statement text. Failed or reversed items did not move money and are left out."""
    header, data = csv_rows(text, HEADER_WORDS)
    if "receiptno" not in header:
        raise ValidationFailed("This does not look like an M-Pesa statement (no 'Receipt No.' column)")
    rows: list[StatementRow] = []
    skipped: list[str] = []
    for line, row in data:
        try:
            status = (row.get("transactionstatus") or "Completed").strip().lower()
            if status not in ("completed", "complete", "success", "successful"):
                continue
            paid_in, withdrawn = statement_amount(row.get("paidin")), statement_amount(row.get("withdrawn"))
            if (paid_in > 0) == (withdrawn > 0):
                raise ValueError("exactly one of Paid In and Withdrawn is expected")
            details = (row.get("details") or "").strip()
            phone = PHONE_IN_DETAILS.search(details)
            name = re.search(r"-\s*(.+)$", details)
            rows.append(StatementRow(
                ref=(row.get("receiptno") or "").strip().upper(),
                time=statement_time(row.get("completiontime") or "", EAT),
                amount=paid_in or withdrawn, direction="in" if paid_in > 0 else "out", description=details,
                payer_name=name.group(1).strip() if name and paid_in > 0 else None,
                payer_phone=phone.group(1) if phone else None))
            if not rows[-1].ref:
                raise ValueError("no receipt number")
        except ValueError as exc:
            skipped.append(f"line {line}: {exc}")
            rows = [r for r in rows if r.ref]
    return ParsedStatement(rows, skipped)


class MpesaStatement(StatementReader):
    """The statement format a business downloads from its M-Pesa portal."""

    name = "mpesa"
    label = "M-Pesa business statement (CSV)"
    source = "mpesa_statement"

    def parse(self, text: str) -> ParsedStatement:
        return parse_mpesa_statement(text)

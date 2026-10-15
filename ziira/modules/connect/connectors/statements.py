"""Statements as evidence: a bank's or a mobile-money provider's statement, uploaded as a CSV file.

The rows become `Payment` records (money in or out, with its transaction code, time, counterparty and the account it
moved through). Intelligence uses them to see whether sales were really paid and whether deposits match cash sales.
Direction comes from separate money-in / money-out columns, or from one signed amount column (with an optional
credit/debit column). Statements overlap (this month's file ends where the next begins, or you upload a whole year
again): each line's reference is made from (account, transaction code, amount, direction, time), so a line is
stored once.
"""

from decimal import Decimal

from ziira.modules.connect.connectors.files import (
    FileConnector,
    FileField,
    ParsedRow,
    RowReader,
    stable_ref,
)
from ziira.modules.connect.domain import reconcile, values
from ziira.modules.connect.public import Payment, Record

ZERO = Decimal(0)
DONE_WORDS = ("complete", "success", "paid", "posted", "ok", "settled", "processed", "cleared", "confirmed")
OUT_WORDS = ("debit", "dr", "out", "withdraw", "paid out", "payment", "sent", "charge")
IN_WORDS = ("credit", "cr", "in", "deposit", "received", "paid in", "receive")
DEFAULT_DEPOSIT_WORDS = "cash deposit,deposit"

STATEMENT_FIELDS = (
    FileField("date", "Date (and time)", True, ("completion time", "transaction date", "value date", "posting date",
                                                 "timestamp", "date time", "datetime", "trans date", "booking date",
                                                 "time")),
    FileField("time", "Time (if separate)", False, ("transaction time",)),
    FileField("reference", "Transaction code or reference", False,
              ("receipt no", "receipt no.", "receipt", "transaction id", "transaction code", "trans id", "txn id",
               "ref", "ref no", "reference no", "cheque no", "confirmation code", "transaction reference")),
    FileField("description", "Details or narration", False, ("details", "narration", "particulars", "description",
                                                              "remarks", "transaction details", "memo")),
    FileField("counterparty", "Who paid or was paid", False, ("name", "party", "payer", "payee", "beneficiary",
                                                               "other party", "customer")),
    FileField("money_in", "Money in", False, ("paid in", "credit", "credits", "deposit", "deposits", "cr",
                                               "amount received", "received", "money in", "inflow", "credit amount")),
    FileField("money_out", "Money out", False, ("withdrawn", "withdrawal", "withdrawals", "debit", "debits", "dr",
                                                 "amount paid", "paid out", "money out", "outflow", "debit amount")),
    FileField("amount", "Amount (one column, + in, - out)", False, ("transaction amount", "amount", "value")),
    FileField("direction", "Credit or debit (if there is one amount column)", False,
              ("type", "dr/cr", "cr/dr", "transaction type", "credit/debit", "debit/credit")),
    FileField("balance", "Balance", False, ("running balance", "closing balance", "balance")),
    FileField("status", "Status", False, ("transaction status", "state", "result")),
    FileField("account", "Account (if the file mixes accounts)", False, ("account no", "account number", "till number",
                                                                          "paybill", "shortcode", "wallet")),
)


# Lines of a statement that are not transactions (data: add words for other languages here)
SKIP_PHRASES = ("opening balance", "closing balance", "balance brought forward", "balance carried forward",
                "brought forward", "carried forward", "balance b/f", "balance c/f", "total paid in", "total withdrawn",
                "total money in", "total money out", "total debits", "total credits", "grand total", "end of statement",
                "statement summary", "this is a system generated", "page ")


class _Statement(FileConnector):
    method = "bank"
    fields = STATEMENT_FIELDS
    entities = ("payments",)
    family = "statement"
    lenient = True
    simple_fields = ("date", "description", "money_in", "money_out", "amount", "balance")
    skip_phrases = SKIP_PHRASES
    needs_any = (("money_in", "money_out", "amount"),)
    needs_any_label = "Money in and money out (or one amount column)"
    options_help = {"deposit_words": "Words in the details that mark a cash deposit (comma separated)"}

    def records(self, rows: list[ParsedRow], reader: RowReader, account: str) -> dict[str, list[Record]]:
        deposit_words = [w.strip().lower() for w in
                         str(reader.settings.options.get("deposit_words",
                             DEFAULT_DEPOSIT_WORDS)).split(",") if w.strip()]
        payments: list[Record] = []
        seen: dict[str, str] = {}
        doubtful = self._doubtful(rows, reader) if reader.settings.options.get("ocr") else {}
        for row in rows:
            if row.number in doubtful:
                reader.issue(row, doubtful[row.number])
                continue
            status = row.text("status").lower()
            if status and not any(w in status for w in DONE_WORDS):
                reader.issue(row, f"Transaction was not completed ({row.text('status')}): skipped")
                continue
            when = reader.moment(row, "date", "time", required=True)
            found = self._amount(row, reader)
            if when is None or found is None:
                continue
            direction, amount = found
            reference = row.text("reference") or None
            details = row.text("description")
            where = row.text("account") or account
            key = stable_ref(where, reference, format(amount.normalize(), "f"), direction, when.isoformat(),
                             "" if reference else f"{details}|{row.text('balance')}")
            if not reference:
                key = reader.unique(key)
            if key in seen:
                continue                                  # the same line twice in one file: stored once
            seen[key] = key
            low = details.lower()
            method = ("cash" if self.method == "bank" and direction == "in" and any(w in low for w in deposit_words)
                      else self.method)
            payments.append(Payment(
                ref=key, occurred_at=when, direction=direction, amount=amount, method=method,  # type: ignore[arg-type]
                reference=reference, party_name=(row.text("counterparty") or details or None), account=where))
        return {"payments": payments}

    def _doubtful(self, rows: list[ParsedRow], reader: RowReader) -> dict[int, str]:
        """Lines read from a picture that cannot be trusted: the running balance does not follow from the line
        before (a digit was probably misread), or a word was read with doubt and the balance cannot vouch for it."""
        entries: list[tuple[int, Decimal, Decimal]] = []
        scratch = RowReader(reader.settings)
        for row in rows:
            found = self._amount(row, scratch)
            balance = row.text("balance")
            if found is None or not balance:
                continue
            try:
                after = values.parse_decimal(balance, reader.settings.decimal_separator)
            except ValueError:
                continue
            entries.append((row.number, found[1] if found[0] == "in" else -found[1], after))
        bad = set(reconcile.suspects(entries)) if len(entries) >= 3 else set()
        verified = {n for n, _, _ in entries} - bad if len(entries) >= 3 else set()
        out = {n: "The balance does not add up after this line: check the amount and the balance" for n in bad}
        for row in rows:
            if row.low_confidence and row.number not in verified and row.number not in out:
                out[row.number] = "Some of this line was hard to read from the picture: check it"
        return out

    @staticmethod
    def _amount(row: ParsedRow, reader: RowReader) -> tuple[str, Decimal] | None:
        m_in, m_out = reader.number(row, "money_in"), reader.number(row, "money_out")
        if m_in is not None or m_out is not None:
            if m_in is not None and m_in != 0:
                return "in", abs(m_in)
            if m_out is not None and m_out != 0:
                return "out", abs(m_out)
            return None                                   # a line that moved nothing (an opening balance)
        value = reader.number(row, "amount")
        if value is None:
            if not reader.issues or reader.issues[-1].row != row.number:
                reader.issue(row, "amount: an amount (or money in and money out columns) is needed")
            return None
        word = row.text("direction").lower()
        if word:
            if any(word == w or word.startswith(w) for w in OUT_WORDS):
                return "out", abs(value)
            if any(word == w or word.startswith(w) for w in IN_WORDS):
                return "in", abs(value)
        if value == 0:
            return None
        return ("in", value) if value > 0 else ("out", -value)


class BankStatement(_Statement):
    kind = "bank_statement"
    title = "Bank statement"
    description = ("Your bank's statement: what was paid into and out of the account, to check sales, deposits and "
                   "bills against.")
    method = "bank"
    how_to = ("Download the statement from your bank's online banking, as PDF, Excel or CSV, for the period you want, "
              "or take a clear photo of a paper one. Drop it here. Upload a newer one whenever you like: lines already "
              "read are not counted twice.")


class MobileMoneyStatement(_Statement):
    kind = "mobile_money_statement"
    title = "Mobile-money statement"
    description = ("The statement of your mobile-money till or business account: every payment received or sent, "
                   "with its code.")
    method = "mobile_money"
    how_to = ("Download the transaction statement from your mobile-money provider (PDF, Excel or CSV; a PDF may have a "
              "password, which they send you) for the period you want. Drop it here. Upload a newer one whenever you "
              "like: lines already read are not counted twice.")

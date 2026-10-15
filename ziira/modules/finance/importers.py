"""Importing from a file, Finance's `imports.importer`s: the chart of accounts (rows go through `create_account`) and
the opening trial balance (all rows together make the company's one opening balance entry)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.crm.public import find_customer_by_code
from ziira.modules.finance.domain import opening
from ziira.modules.finance.domain.entries import ACCOUNT_TYPES
from ziira.modules.finance.permissions import ACCOUNTS_MANAGE, JOURNAL_APPROVE
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.services import opening_balances
from ziira.modules.finance.services.accounts import CODE_PATTERN, create_account
from ziira.modules.imports.public import FileCheck, ImportColumn, Importer, ImportRow
from ziira.modules.purchasing.public import find_supplier_by_code
from ziira.sdk import Session, ValidationFailed


class AccountImporter(Importer):
    kind = "accounts"
    title = "Chart of accounts"
    description = ("Your list of accounts: code, name and type. Open Finance once first so the company's books are "
                   "set up; accounts already there are skipped.")
    permission = ACCOUNTS_MANAGE
    columns = (
        ImportColumn("code", True, "The account number or code.", "5100", aliases=("account code", "account number",
                                                                                 "number", "account no")),
        ImportColumn("name", True, "The account's name.", "Rent", aliases=("account name", "account")),
        ImportColumn("type", True, "asset, liability, equity, income or expense.", "expense",
                     aliases=("account type", "class")),
        ImportColumn("subtype", False, "A finer grouping, if you use one.", "premises"),
    )
    reversal_note = "Accounts cannot be deleted. Switch unwanted ones off in Finance > Accounts."

    def key(self, row: ImportRow) -> str | None:
        return row.text("code").upper() or None

    def _problems(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        if not CODE_PATTERN.match(row.text("code").upper()):
            errors.append("code: 1-20 letters, digits, '.', '_' or '-'")
        name = row.text("name")
        if not name or len(name) > 200:
            errors.append("name: a name of up to 200 characters is needed")
        if row.text("type").lower() not in ACCOUNT_TYPES:
            errors.append(f"type: write one of {', '.join(ACCOUNT_TYPES)}")
        if session.execute(text("select 1 from finance.account where company_id = :c limit 1"),
                           {"c": str(company_id)}).first() is None:
            errors.append("The company's books are not set up yet. Open Finance first, then import again.")
        return errors

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        return self._problems(session, company_id, row)

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        code = row.text("code").upper()
        found = session.execute(text("select 1 from finance.account where company_id = :c and code = :k"),
                                {"c": str(company_id), "k": code}).first()
        return f"Account {code} already exists" if found else None

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        errors = self._problems(session, company_id, row)
        if errors:
            raise ValidationFailed("; ".join(errors))
        return create_account(session, company_id=company_id, code=row.text("code"), name=row.text("name"),
                              type=row.text("type").lower(), subtype=row.text("subtype") or None).id


def _unit_enabled(session: Session, unit: str) -> bool:
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


@dataclass(frozen=True)
class _Read:
    """A trial balance row after checking: the line it makes, and the code of the customer or supplier on it."""

    line: opening_balances.FileLine
    label: str | None


class OpeningTrialBalanceImporter(Importer):
    kind = "opening_trial_balance"
    title = "Opening trial balance"
    description = ("Your accountant's trial balance at the go-live date: one row per account with its debit or credit. "
                   "Balance sheet accounts only. Customers, suppliers and stock are brought in by their own imports "
                   "first; their lines here (one per customer or supplier, with its code) must agree with them. "
                   "All rows are posted together as one entry or not at all.")
    permission = JOURNAL_APPROVE
    columns = (
        ImportColumn("account_code", True, "The account's code in your chart of accounts.", "1020",
                     aliases=("account", "account no", "account number", "code", "gl code")),
        ImportColumn("debit", False, "The debit balance (leave empty for a credit balance).", "125000.00",
                     aliases=("dr", "debit balance"), total="debits"),
        ImportColumn("credit", False, "The credit balance (leave empty for a debit balance).", "",
                     aliases=("cr", "credit balance"), total="credits"),
        ImportColumn("party_code", False, "Receivable and payable accounts: the customer's or supplier's code.", "",
                     aliases=("customer code", "supplier code", "customer", "supplier", "party")),
        ImportColumn("branch", False, "Code of the branch the balance belongs to, if you keep accounts by branch.",
                     "", aliases=("branch code",)),
    )
    money_totals = ("debits", "credits")
    needs_go_live = True
    whole_file = True
    reversible = True
    reversal_note = ("The opening balance entry is reversed; customers, suppliers and stock are reversed by their "
                     "own imports.")

    def key(self, row: ImportRow) -> str | None:
        return f"{row.text('account_code').upper()}|{row.text('party_code').upper()}|{row.text('branch').upper()}"

    def _read(self, session: Session, company_id: UUID, row: ImportRow, errors: list[str]) -> _Read | None:
        debit = row.number("debit", errors, minimum=Decimal(0)) or Decimal(0)
        credit = row.number("credit", errors, minimum=Decimal(0)) or Decimal(0)
        if debit and credit:
            errors.append("Give either a debit or a credit, not both")
        for name, value in (("debit", debit), ("credit", credit)):
            if value != value.quantize(Decimal("0.01")):
                errors.append(f"{name}: at most 2 decimal places")
        code = row.text("account_code").upper()
        account = finance_repo.account_by_code(session, company_id, code) if code else None
        if account is None:
            errors.append(f"account_code: no account {code or '(empty)'} in this company. Import the chart of "
                          "accounts first (or open Finance once to set up the default chart)")
            return None
        if not account.is_active:
            errors.append(f"account_code: {code} is switched off")
        try:
            kind = opening.classify(account.type, account.subtype, account.is_control)
        except ValidationFailed as error:
            errors.append(f"account_code: {code}: {error.message}")
            return None
        party_id, label = self._party(session, company_id, kind, row, errors)
        branch_id = None
        if row.text("branch"):
            found = session.execute(text("select id from kernel.branch where company_id = :c and code = :b"),
                                    {"c": str(company_id), "b": row.text("branch").upper()}).first()
            branch_id = found.id if found else None
            if found is None:
                errors.append(f"branch: no branch with code {row.text('branch').upper()}")
        if errors:
            return None
        return _Read(opening_balances.FileLine(account.id, debit, credit, branch_id, party_id, label), label)

    def _party(self, session: Session, company_id: UUID, kind: str, row: ImportRow,
               errors: list[str]) -> tuple[UUID | None, str | None]:
        code = row.text("party_code").upper()
        if kind == opening.PLAIN or kind == opening.INVENTORY:
            if code:
                errors.append("party_code: only receivable and payable accounts take a customer or supplier code")
            return None, None
        who = opening.PARTY_OF[kind] or "party"
        if not code:
            errors.append(f"party_code: a line on the {who}s' control account needs the {who}'s code, one row per "
                          f"{who} (the total alone cannot be checked)")
            return None, None
        unit = "crm" if kind == opening.RECEIVABLE else "purchasing"
        if not _unit_enabled(session, unit):
            errors.append(f"party_code: {'Customers' if unit == 'crm' else 'Purchasing'} is not switched on")
            return None, None
        found = (find_customer_by_code(session, company_id, code) if kind == opening.RECEIVABLE
                 else find_supplier_by_code(session, company_id, code))
        if found is None:
            errors.append(f"party_code: no {who} with code {code}. Import the {who}s first")
            return None, None
        return found.id, code

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        self._read(session, company_id, row, errors)
        return errors

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        raise ValidationFailed("The rows of a trial balance are imported together, not one by one")

    def _lines(self, session: Session, company_id: UUID, rows: Sequence[ImportRow]) -> tuple[
            list[opening_balances.FileLine], dict[UUID, str]]:
        lines: list[opening_balances.FileLine] = []
        labels: dict[UUID, str] = {}
        for row in rows:
            read = self._read(session, company_id, row, [])
            if read is None:
                raise ValidationFailed("A row cannot be read any more; check the file again")
            if read.line.debit or read.line.credit:               # an account at zero adds nothing
                lines.append(read.line)
            if read.line.party_id and read.label:
                labels[read.line.party_id] = read.label
        return lines, labels

    def check_file(self, session: Session, company_id: UUID, rows: Sequence[ImportRow]) -> FileCheck:
        first = rows[0] if rows else None
        if first is None:
            return FileCheck(problems=["The file has no rows"])
        lines, labels = self._lines(session, company_id, rows)
        found = opening_balances.check_opening_file(
            session, company_id=company_id, go_live_date=self._go_live(first), lines=lines,
            tolerance=first.options.tolerance, labels=labels)
        return FileCheck(found.problems, found.needs_confirmation, found.notes)

    @staticmethod
    def _go_live(row: ImportRow) -> date:
        if row.options.as_of is None:
            raise ValidationFailed("Say the go-live date when uploading the file")
        return row.options.as_of

    def import_file(self, session: Session, company_id: UUID, rows: Sequence[ImportRow], *, confirmed: bool) -> UUID:
        lines, labels = self._lines(session, company_id, rows)
        document = opening_balances.post_opening_balances(
            session, company_id=company_id, go_live_date=self._go_live(rows[0]), lines=lines,
            tolerance=rows[0].options.tolerance, accept_difference=confirmed, labels=labels)
        return document.id

    def totals(self, rows: Sequence[ImportRow]) -> dict[str, Decimal]:
        """The file's debit and credit balances account by account (an account listed on several rows, one per customer
        for example, is added up first)."""
        net: dict[str, Decimal] = {}
        for row in rows:
            code = row.text("account_code").upper()
            net[code] = (net.get(code, Decimal(0)) + (row.number("debit", []) or Decimal(0))
                         - (row.number("credit", []) or Decimal(0)))
        return {"debits": sum((v for v in net.values() if v > 0), Decimal(0)),
                "credits": sum((-v for v in net.values() if v < 0), Decimal(0))}

    def read_back(self, session: Session, company_id: UUID, rows: Sequence[ImportRow],
                  record_ids: list[UUID]) -> dict[str, Decimal]:
        """The same figures from the books: each account of the file at the go-live date (control accounts included, as
        their own records brought them in)."""
        day = rows[0].options.as_of if rows else None
        if day is None:
            return {}
        codes = {row.text("account_code").upper() for row in rows}
        net = []
        for code in codes:
            account = finance_repo.account_by_code(session, company_id, code)
            if account is not None:
                net.append(finance_repo.account_net_until(session, company_id, account.id, day))
        return {"debits": sum((v for v in net if v > 0), Decimal(0)),
                "credits": sum((-v for v in net if v < 0), Decimal(0))}

    def reverse(self, session: Session, company_id: UUID, record_ids: list[UUID], reason: str) -> int:
        for opening_id in record_ids:
            opening_balances.reverse_opening_balance(session, opening_id, reason=reason)
        return len(record_ids)

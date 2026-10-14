"""Importing the chart of accounts from a file: Finance's `imports.importer`. Rows go through `create_account`.

Opening balances (a trial balance) are not imported yet: see docs/data-import.md for why and what to do instead."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.finance.domain.entries import ACCOUNT_TYPES
from ziira.modules.finance.permissions import ACCOUNTS_MANAGE
from ziira.modules.finance.services.accounts import CODE_PATTERN, create_account
from ziira.modules.imports.public import ImportColumn, Importer, ImportRow
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

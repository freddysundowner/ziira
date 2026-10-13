"""Use cases: reports that read the journal lines (reproducible for any past date, since entries never change)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.finance.domain.entries import natural_balance
from ziira.modules.finance.permissions import REPORTS_VIEW
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.finance_repo import LedgerLine
from ziira.sdk import NotFound, Session, ValidationFailed, check_company, current_context


@dataclass(frozen=True)
class TrialBalanceLine:
    account_id: UUID
    code: str
    name: str
    type: str
    debit: Decimal
    credit: Decimal
    balance: Decimal          # as the account normally shows it (see domain/entries.natural_balance)


@dataclass(frozen=True)
class TrialBalance:
    company_id: UUID
    as_of: date
    branch_id: UUID | None
    lines: list[TrialBalanceLine]
    total_debit: Decimal
    total_credit: Decimal

    @property
    def balanced(self) -> bool:
        return self.total_debit == self.total_credit


def _scopes(company_id: UUID) -> list[tuple[UUID | None, UUID | None]] | None:
    """Where the user may read this company's books; refuses when they may not read it at all."""
    scopes = current_context().scopes_with(REPORTS_VIEW)
    if scopes is not None and not any(c == company_id for c, _ in scopes):
        raise NotFound("Company not found")
    return scopes


def trial_balance(session: Session, company_id: UUID, as_of: date, *, branch_id: UUID | None = None,
                  include_zero: bool = False) -> TrialBalance:
    """Debit and credit totals per account up to a date. For a branch grant only that branch's lines are included,
    so the report covers the branches the user may see. Needs 'reports.view'."""
    check_company(session, company_id, branch_id)
    scopes = _scopes(company_id)
    rows = finance_repo.trial_balance(session, scopes, company_id, as_of, branch_id, include_zero)
    lines = [TrialBalanceLine(r.account_id, r.code, r.name, r.type, r.debit, r.credit,
                              natural_balance(r.type, r.debit, r.credit)) for r in rows]
    return TrialBalance(company_id, as_of, branch_id, lines, sum((x.debit for x in lines), Decimal(0)),
                        sum((x.credit for x in lines), Decimal(0)))


@dataclass(frozen=True)
class GeneralLedger:
    account_id: UUID
    code: str
    name: str
    date_from: date
    date_to: date
    opening: Decimal                    # balance before date_from, as the account normally shows it
    lines: list[tuple[LedgerLine, Decimal]]       # each line with the running balance after it
    closing: Decimal


def general_ledger(session: Session, company_id: UUID, account_id: UUID, date_from: date, date_to: date, *,
                   branch_id: UUID | None = None, limit: int = 1000, offset: int = 0) -> GeneralLedger:
    """The lines posted to one account between two dates with a running balance. Needs 'reports.view'."""
    if date_to < date_from:
        raise ValidationFailed("The end date is before the start date")
    check_company(session, company_id, branch_id)
    scopes = _scopes(company_id)
    account = finance_repo.get_account(session, account_id)
    if account is None or account.company_id != company_id:
        raise NotFound("Account not found")
    before_debit, before_credit = finance_repo.ledger_before(session, scopes, company_id, account_id, date_from,
                                                             branch_id)
    opening = natural_balance(account.type, before_debit, before_credit)
    running = opening
    out = []
    for line in finance_repo.ledger_lines(session, scopes, company_id, account_id, date_from, date_to, branch_id,
                                          min(limit, 5000), offset):
        running += natural_balance(account.type, line.debit, line.credit)
        out.append((line, running))
    return GeneralLedger(account.id, account.code, account.name, date_from, date_to, opening, out, running)

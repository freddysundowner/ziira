"""Use cases: the opening balance entry. A business that moves onto Ziira starts its books on a go-live date with
balances in its balance-sheet accounts. That is one entry per company, dated the go-live date, posted by the posting
engine like any other entry (`post_entry`), immutable, audited, and corrected only by reversing it (which frees the
company to post a new one).

The customers', suppliers' and stock balances inside control accounts are not posted here: their own records bring them
in (see `domain/opening.py`), and this entry only *checks* the file's control lines against them. So the file may be the
accountant's whole trial balance while every sub-ledger still equals its control account.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from ziira.modules.finance.domain import opening, rules
from ziira.modules.finance.domain.entries import Line, check_amount
from ziira.modules.finance.permissions import JOURNAL_APPROVE, JOURNAL_POST_MANUAL
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import Account, OpeningBalance
from ziira.modules.finance.services.access import visible_companies
from ziira.modules.finance.services.books import ensure_books
from ziira.modules.finance.services.posting import EntryRequest, post_entry, reverse_entry
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    next_document_number,
)

SOURCE_TYPE = "opening_balance"
SHOWN = 5          # how many mismatches a message names before saying "and N more"


@dataclass(frozen=True)
class FileLine:
    """One line of an opening trial balance. Control-account lines name the customer or supplier (`party_id`); `label`
    is how the file calls it (its code), for messages."""

    account_id: UUID
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    branch_id: UUID | None = None
    party_id: UUID | None = None
    label: str | None = None

    @property
    def net(self) -> Decimal:
        return self.debit - self.credit


@dataclass(frozen=True)
class OpeningCheck:
    """What is wrong with a file (`problems` stop it), whether the user must accept a difference first
    (`needs_confirmation`, the plain-language warning) and other things worth knowing (`notes`)."""

    problems: list[str] = field(default_factory=list)
    needs_confirmation: str | None = None
    notes: list[str] = field(default_factory=list)
    difference: Decimal = Decimal(0)


def _kind(account: Account) -> str:
    return opening.classify(account.type, account.subtype, account.is_control)


def live_opening(session: Session, company_id: UUID) -> OpeningBalance | None:
    """The company's opening balance entry, if it has one that has not been reversed."""
    return finance_repo.live_opening_balance(session, company_id)


def _equity_account(session: Session, company_id: UUID) -> UUID:
    posting_rules = [rules.PostingRule(r.doc_type, r.line_role, r.account_id, dict(r.conditions or {}), r.priority)
                     for r in finance_repo.list_rules(session, company_id)]
    return rules.resolve_account(posting_rules, SOURCE_TYPE, "opening_equity", {})


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _named(mismatches: Sequence[tuple[UUID | None, Decimal, Decimal]], labels: Mapping[UUID, str], who: str,
           account: Account) -> str:
    shown = []
    for key, in_file, in_books in mismatches[:SHOWN]:
        name = labels.get(key, f"another {who}") if key is not None else "no one"
        shown.append(f"{name}: file {_money(in_file)}, Ziira {_money(in_books)}")
    more = f" and {len(mismatches) - SHOWN} more" if len(mismatches) > SHOWN else ""
    return (f"{account.code} {account.name} does not agree with the {who}s' own records ({'; '.join(shown)}{more}). "
            f"Import the {who} balances first (with the same go-live date), or correct the file")


def check_opening_file(session: Session, *, company_id: UUID, go_live_date: date, lines: Sequence[FileLine],
                       tolerance: Decimal = Decimal(0), labels: Mapping[UUID, str] | None = None) -> OpeningCheck:
    """Check an opening trial balance without posting it: no earlier opening entry, an open period, every control
    account equal to the records behind it (customers, suppliers, stock), and whether the file balances."""
    labels = labels or {}
    problems: list[str] = []
    existing = live_opening(session, company_id)
    if existing is not None:
        problems.append(f"The company already has an opening balance entry ({existing.number}, dated "
                        f"{existing.go_live_date}). Reverse it first if the balances must be posted again")
    period = finance_repo.period_for(session, company_id, go_live_date)
    if period is not None and period.status != "open":
        problems.append(f"The accounting period containing {go_live_date} is {period.status.replace('_', ' ')}: "
                        "choose a go-live date in an open period")
    accounts = finance_repo.accounts_by_ids(session, {x.account_id for x in lines})
    plain = controlled = Decimal(0)
    in_file: dict[tuple[UUID, str], dict[UUID | None, Decimal]] = {}
    for line in lines:
        account = accounts.get(line.account_id)
        if account is None or account.company_id != company_id:
            problems.append("A line names an account that is not in this company")
            continue
        try:
            kind = _kind(account)
        except ValidationFailed as error:
            problems.append(f"{account.code} {account.name}: {error.message}")
            continue
        if kind == opening.PLAIN:
            plain += line.net
            continue
        controlled += line.net
        if kind in (opening.RECEIVABLE, opening.PAYABLE) and line.party_id is None:
            problems.append(f"{account.code} {account.name}: every line needs the customer or supplier it is for")
        key = None if kind == opening.INVENTORY else line.party_id
        per = in_file.setdefault((account.id, kind), {})
        per[key] = per.get(key, Decimal(0)) + line.net
    problems += _control_problems(session, company_id, go_live_date, in_file, accounts, labels)
    pos = opening.position(plain, controlled)
    notes: list[str] = []
    needs: str | None = None
    if pos.difference != 0:
        side = "debits are more than credits" if pos.difference > 0 else "credits are more than debits"
        message = (f"The opening balances do not balance: {side} by {_money(abs(pos.difference))}. The difference "
                   "can be posted to opening balance equity")
        if abs(pos.difference) <= tolerance:
            notes.append(f"{message}; it is within the tolerance of {_money(tolerance)}, so it will be")
        else:
            needs = f"{message}, but only if you confirm it"
    return OpeningCheck(problems, needs, notes, pos.difference)


def _control_problems(session: Session, company_id: UUID, go_live_date: date,
                      in_file: dict[tuple[UUID, str], dict[UUID | None, Decimal]], accounts: dict[UUID, Account],
                      labels: Mapping[UUID, str]) -> list[str]:
    """Every receivable, payable and inventory account of the company: the file's balance must equal the books'."""
    problems: list[str] = []
    for account in finance_repo.list_accounts(session, None, company_id, include_inactive=True):
        if not account.is_control or account.subtype not in (opening.RECEIVABLE, opening.PAYABLE, opening.INVENTORY):
            continue
        kind = str(account.subtype)
        file_net = in_file.get((account.id, kind), {})
        if kind == opening.INVENTORY:
            stock = finance_repo.account_net_until(session, company_id, account.id, go_live_date)
            books: dict[UUID | None, Decimal] = {None: stock} if stock != 0 else {}
        else:
            books = finance_repo.party_net_until(session, company_id, account.id, go_live_date)
        file_net = {k: v for k, v in file_net.items() if v != 0}
        wrong = opening.mismatches(file_net, books)
        if not wrong:
            continue
        if kind == opening.INVENTORY:
            problems.append(f"{account.code} {account.name}: the file says {_money(file_net.get(None, Decimal(0)))} "
                            f"but opening stock in Ziira is worth {_money(books.get(None, Decimal(0)))}. Import "
                            "opening stock first, or correct the file")
        else:
            problems.append(_named(wrong, labels, opening.PARTY_OF[kind] or "party", account))
    return problems


def post_opening_balances(session: Session, *, company_id: UUID, go_live_date: date, lines: Sequence[FileLine],
                          tolerance: Decimal = Decimal(0), accept_difference: bool = False,
                          labels: Mapping[UUID, str] | None = None, note: str | None = None) -> OpeningBalance:
    """Post the company's opening balance entry. Everything is checked again here, so a file that was valid when it was
    checked but is not any more (balances changed in between) is refused. Needs 'journal.post_manual' and
    'journal.approve' (the approver's permission: opening balances are never waiting in an approval queue, so
    whoever posts them is the one who approves them)."""
    ctx = current_context()
    check_company(session, company_id)
    ctx.require(JOURNAL_POST_MANUAL, company_id=company_id)
    ctx.require(JOURNAL_APPROVE, company_id=company_id)
    ensure_books(session, company_id)
    for line in lines:
        check_amount(line.debit, "Debit")
        check_amount(line.credit, "Credit")
        if line.debit < 0 or line.credit < 0 or (line.debit > 0) == (line.credit > 0):
            raise ValidationFailed("Each opening balance line is either a debit or a credit of an amount above zero")
        if line.branch_id:
            check_company(session, company_id, line.branch_id)
    finance_repo.lock_books(session, company_id)
    result = check_opening_file(session, company_id=company_id, go_live_date=go_live_date, lines=lines,
                                tolerance=tolerance, labels=labels)
    if result.problems:
        raise ValidationFailed("; ".join(result.problems))
    if result.needs_confirmation and not accept_difference:
        raise Conflict(result.needs_confirmation)
    accounts = finance_repo.accounts_by_ids(session, {x.account_id for x in lines})
    entry_lines = [Line(x.account_id, x.debit, x.credit, x.branch_id)
                   for x in lines if _kind(accounts[x.account_id]) == opening.PLAIN]
    if not entry_lines:
        raise ValidationFailed("The file has no account balances to post besides customers, suppliers and stock, "
                               "which are posted by their own imports")
    controlled = sum((x.net for x in lines if _kind(accounts[x.account_id]) != opening.PLAIN), Decimal(0))
    plain = sum((x.net for x in lines if _kind(accounts[x.account_id]) == opening.PLAIN), Decimal(0))
    equity = _equity_account(session, company_id)
    for side, amount, why in opening.equity_lines(opening.position(plain, controlled)):
        entry_lines.append(Line(equity, amount if side == "debit" else Decimal(0),
                                amount if side == "credit" else Decimal(0), description=why))
    number = next_document_number(session, company_id=company_id, branch_id=None, doc_type="opening_balance",
                                  prefix="OB")
    opening_id = uuid4()
    entry = post_entry(session, EntryRequest(
        company_id=company_id, entry_date=go_live_date, journal_code="GEN", lines=entry_lines,
        description=f"{number}: opening balances at {go_live_date}", source_type=SOURCE_TYPE, source_id=opening_id,
        is_manual=True, approved_by=ctx.user_id, exact_date=True))
    document = OpeningBalance(
        id=opening_id, tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, number=number,
        go_live_date=go_live_date, entry_id=entry.id, line_count=len(lines),
        difference=result.difference if result.difference != 0 else Decimal(0), note=(note or "").strip()[:500] or None)
    finance_repo.add(session, document)
    audit_record(session, "post", "finance.opening_balance", document.id, {
        "number": number, "go_live_date": go_live_date, "lines": len(lines), "entry": entry.number,
        "difference": document.difference})
    return document


def reverse_opening_balance(session: Session, opening_id: UUID, *, reason: str,
                            entry_date: date | None = None) -> OpeningBalance:
    """Cancel the opening balance entry with a mirror entry (dated the go-live date unless another date is given). The
    customers', suppliers' and stock balances are not touched: they are taken out by reversing their own imports.
    Needs 'journal.approve'; a reason is required."""
    document = finance_repo.get_opening_balance(session, opening_id, lock=True)
    companies = visible_companies()
    if document is None or (companies is not None and document.company_id not in companies):
        raise NotFound("Opening balance entry not found")
    current_context().require(JOURNAL_APPROVE, company_id=document.company_id)
    if document.status != "posted":
        raise Conflict("This opening balance entry has already been reversed")
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    reversal = reverse_entry(session, document.entry_id, entry_date=entry_date or document.go_live_date,
                             reason=reason.strip(), _opening_ok=True)
    document.status, document.reversal_entry_id = "reversed", reversal.id
    document.reversed_at, document.reversed_by = reversal.posted_at, current_context().user_id
    document.reverse_reason = reason.strip()
    session.flush()
    audit_record(session, "reverse", "finance.opening_balance", document.id,
                 {"number": document.number, "reason": reason.strip(), "entry": reversal.number})
    return document


def list_opening_balances(session: Session) -> list[OpeningBalance]:
    """The opening balance entries of the companies the user may see, newest first."""
    return finance_repo.list_opening_balances(session, visible_companies())

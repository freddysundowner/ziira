"""Setting up a company's books: chart of accounts, journals, default posting rules, and its periods.

Books are created the first time a company needs them (its first posting, or when someone opens the chart), from the
template in domain/chart.py. Doing it twice changes nothing.
"""

from datetime import date
from uuid import UUID

from ziira.modules.finance.domain import chart, periods
from ziira.modules.finance.public import CHART_TEMPLATE
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import Account, Journal, Period, PostingRule
from ziira.sdk import Session, audit_record, check_company, current_context, pack_providers


def template_for(session: Session, company_id: UUID) -> chart.ChartSet:
    """The chart the company's books are made from: the general one, refined by its country pack (if one is on)."""
    accounts: list[chart.TemplateAccount] = []
    journals: list[tuple[str, str]] = []
    rules: list[tuple[str, str, str, str]] = []
    for provider in pack_providers(session, CHART_TEMPLATE, company_id):
        accounts += [chart.TemplateAccount(a.code, a.name, a.type, a.subtype, a.is_control)
                     for a in provider.accounts()]
        journals += provider.journals()
        rules += [(r.doc_type, r.role, r.account_code, r.side) for r in provider.rules()]
    return chart.merged(tuple(accounts), tuple(journals), tuple(rules)) if accounts or journals or rules \
        else chart.GENERAL


def _books_complete(session: Session, company_id: UUID) -> bool:
    """True when the company has every template account and posting rules for every document type, so
    `ensure_books` has nothing to do. Two cheap reads instead of one query per template account."""
    codes = finance_repo.account_codes(session, company_id)
    if not all(template.code in codes for template in chart.CHART):
        return False
    known_types = finance_repo.rule_doc_types(session, company_id)
    return all(rule[0] in known_types for rule in chart.DEFAULT_RULES)


def ensure_books(session: Session, company_id: UUID) -> None:
    """Create the company's chart of accounts, journals and default posting rules if it has none yet."""
    check_company(session, company_id)
    done: set[UUID] = session.info.setdefault("books_complete", set())
    if company_id in done:
        return
    if _books_complete(session, company_id):
        done.add(company_id)
        return                       # the usual case: nothing to add, so no lock (it would serialise every posting)
    finance_repo.lock_books(session, company_id)                    # two postings at once: one sets up, one waits
    if finance_repo.has_accounts(session, company_id):
        add_missing_accounts(session, company_id)
        add_missing_default_rules(session, company_id)
        return
    ctx = current_context()
    template_set = template_for(session, company_id)
    by_code: dict[str, Account] = {}
    for template in template_set.accounts:
        account = Account(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=template.code,
                          name=template.name, type=template.type, subtype=template.subtype,
                          is_control=template.is_control)
        finance_repo.add(session, account)
        by_code[template.code] = account
    for code, name in template_set.journals:
        finance_repo.add(session, Journal(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                                          code=code, name=name))
    for doc_type, role, account_code, side in template_set.rules:
        finance_repo.add(session, PostingRule(
            tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, doc_type=doc_type,
            line_role=role, account_id=by_code[account_code].id, side=side, conditions={}, priority=100))
    audit_record(session, "setup", "finance.books", company_id,
                 {"accounts": len(template_set.accounts), "journals": len(template_set.journals),
                  "rules": len(template_set.rules)})


def get_or_create_period(session: Session, company_id: UUID, day: date) -> Period:
    """The monthly period containing `day`, created (open) if it does not exist yet."""
    found = finance_repo.period_for(session, company_id, day)
    if found is not None:
        return found
    finance_repo.lock_books(session, company_id)
    found = finance_repo.period_for(session, company_id, day)        # someone may have made it while we waited
    if found is not None:
        return found
    start, end = periods.month_bounds(day)
    ctx = current_context()
    period = Period(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, start_date=start,
                    end_date=end)
    finance_repo.add(session, period)
    return period


def add_missing_accounts(session: Session, company_id: UUID) -> int:
    """Give a company the template accounts added since its books were set up (a missing code is created; an account the
    company already has under that code is left alone). Returns how many were added."""
    ctx = current_context()
    added = 0
    for template in template_for(session, company_id).accounts:
        if finance_repo.account_by_code(session, company_id, template.code) is None:
            finance_repo.add(session, Account(
                tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=template.code,
                name=template.name, type=template.type, subtype=template.subtype, is_control=template.is_control))
            added += 1
    if added:
        audit_record(session, "add_default_accounts", "finance.books", company_id, {"accounts": added})
    return added


def add_missing_default_rules(session: Session, company_id: UUID) -> int:
    """Give a company the default posting rules for kinds of document added since its books were set up. A document
    type the company already has rules for is left alone, so a rule it removed or changed stays that way. Returns how
    many were added."""
    known_types = {r.doc_type for r in finance_repo.list_rules(session, company_id)}
    missing = [r for r in template_for(session, company_id).rules if r[0] not in known_types]
    if not missing:
        return 0
    ctx = current_context()
    added = 0
    for doc_type, role, account_code, side in missing:
        account = finance_repo.account_by_code(session, company_id, account_code)
        if account is None:                                  # the company removed that account: they must choose one
            continue
        finance_repo.add(session, PostingRule(
            tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, doc_type=doc_type, line_role=role,
            account_id=account.id, side=side, conditions={}, priority=100))
        added += 1
    if added:
        audit_record(session, "add_default_rules", "finance.books", company_id, {"rules": added})
    return added


def add_missing_journals(session: Session, company_id: UUID) -> int:
    """Give a company the template journals it lacks (a journal it has under that code is left alone)."""
    ctx = current_context()
    have = {j.code for j in finance_repo.list_journals(session, company_id)}
    added = 0
    for code, name in template_for(session, company_id).journals:
        if code not in have:
            finance_repo.add(session, Journal(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                                              code=code, name=name))
            added += 1
    return added


def seed_from_pack(session: Session, company_id: UUID) -> int:
    """A country pack came on (or a company was added): bring an existing chart up to the pack's template, adding only
    what is missing. A company with no books yet is left alone: its books are made from the template on first use."""
    if not finance_repo.has_accounts(session, company_id):
        return 0
    finance_repo.lock_books(session, company_id)
    return (add_missing_accounts(session, company_id) + add_missing_journals(session, company_id)
            + add_missing_default_rules(session, company_id))

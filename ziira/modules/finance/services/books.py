"""Setting up a company's books: chart of accounts, journals, default posting rules, and its periods.

Books are created the first time a company needs them (its first posting, or when someone opens the chart), from the
template in domain/chart.py. Doing it twice changes nothing.
"""

from datetime import date
from uuid import UUID

from ziira.modules.finance.domain import chart, periods
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import Account, Journal, Period, PostingRule
from ziira.sdk import Session, audit_record, check_company, current_context


def ensure_books(session: Session, company_id: UUID) -> None:
    """Create the company's chart of accounts, journals and default posting rules if it has none yet."""
    check_company(session, company_id)
    finance_repo.lock_books(session, company_id)                    # two postings at once: one sets up, one waits
    if finance_repo.has_accounts(session, company_id):
        add_missing_default_rules(session, company_id)
        return
    ctx = current_context()
    by_code: dict[str, Account] = {}
    for template in chart.CHART:
        account = Account(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=template.code,
                          name=template.name, type=template.type, subtype=template.subtype,
                          is_control=template.is_control)
        finance_repo.add(session, account)
        by_code[template.code] = account
    for code, name in chart.JOURNALS:
        finance_repo.add(session, Journal(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                                          code=code, name=name))
    for doc_type, role, account_code, side in chart.DEFAULT_RULES:
        finance_repo.add(session, PostingRule(
            tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, doc_type=doc_type,
            line_role=role, account_id=by_code[account_code].id, side=side, conditions={}, priority=100))
    audit_record(session, "setup", "finance.books", company_id,
                 {"accounts": len(chart.CHART), "journals": len(chart.JOURNALS), "rules": len(chart.DEFAULT_RULES)})


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


def add_missing_default_rules(session: Session, company_id: UUID) -> int:
    """Give a company the default posting rules for kinds of document added since its books were set up. A document
    type the company already has rules for is left alone, so a rule it removed or changed stays that way. Returns how
    many were added."""
    known_types = {r.doc_type for r in finance_repo.list_rules(session, company_id)}
    missing = [r for r in chart.DEFAULT_RULES if r[0] not in known_types]
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

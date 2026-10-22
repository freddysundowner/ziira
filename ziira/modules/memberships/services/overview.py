"""Counts for the Memberships overview."""

import calendar
from datetime import timedelta
from uuid import UUID

from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common
from ziira.sdk import Session


def summary(session: Session, company_id: UUID | None = None) -> dict[str, int]:
    """Headline numbers of the companies the person may see (or of one company)."""
    clause, params = repo.scope_sql(common.view_scopes())
    anchor = company_id
    if anchor is None:
        first = repo.one(session, "select id from kernel.company order by id limit 1")
        if first is None:
            return {}
        anchor = first["id"]
    today = common.today(session, anchor)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    where = f"{clause} and (cast(:c as uuid) is null or company_id = :c)"
    renewing = "status = 'active' and cancel_at is null and next_renewal_date between :t and"
    row = repo.one(
        session,
        "select "
        f"(select count(*) from memberships.member where {where} and status = 'active') as active_members, "
        f"(select count(*) from memberships.member where {where} and status in ('paused', 'frozen')) "
        "   as paused_members, "
        f"(select count(*) from memberships.member where {where} and {renewing} :me) as renewals_this_month, "
        f"(select count(*) from memberships.member where {where} and {renewing} :w) as renewals_next_7_days, "
        f"(select count(*) from memberships.sold_package where {where} and status = 'active' "
        "   and expires_on between :t and :m30) as packages_expiring_30_days, "
        f"(select count(*) from memberships.member where {where} and status in ('active', 'paused', 'frozen') "
        "   and coalesce(cancel_at, end_date) between :t and :m30) as ending_30_days, "
        f"(select count(*) from memberships.invoice_run where {where} and status = 'failed') as failed_runs, "
        f"(select count(*) from memberships.invoice_run where {where} and status = 'pending_review') as drafts_waiting",
        c=company_id, t=today, me=month_end, w=today + timedelta(days=7), m30=today + timedelta(days=30), **params)
    return {k: int(v) for k, v in (row or {}).items()}


def setup_steps(session: Session, company_id: UUID) -> list[dict[str, object]]:
    """The first-run checklist, worked out from what exists: each step is done or not. The screen shows only the ones
    still to do."""
    common.check_visible(company_id, None, "Company")

    def has(sql: str) -> bool:
        return repo.one(session, sql, c=company_id) is not None

    return [
        {"id": "plans", "done": has("select 1 as x from memberships.plan where company_id = :c and status = 'active' "
                                    "limit 1") and not has("select 1 as x from memberships.plan where company_id = :c "
                                                           "and status = 'active' and is_example limit 1")},
        {"id": "services", "done": not has("select 1 as x from memberships.plan where company_id = :c and status = "
                                           "'active' and service_product_id is null and fee > 0 limit 1")
         and has("select 1 as x from memberships.plan where company_id = :c limit 1")},
        {"id": "terms", "done": has("select 1 as x from memberships.waiver_version where company_id = :c limit 1")},
        {"id": "policies", "done": has("select 1 as x from memberships.setting where company_id = :c")},
        {"id": "members", "done": has("select 1 as x from memberships.member where company_id = :c limit 1")},
        {"id": "checkin", "done": has("select 1 as x from memberships.checkin where company_id = :c limit 1")},
    ]

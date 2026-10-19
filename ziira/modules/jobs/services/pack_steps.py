"""The first-run checklist an industry pack gives a business: 5 to 7 plain steps that tick themselves when the work is
done (rates set, service items chosen, a first job taken ...). Steps with no automatic check are ticked by hand. The
owner can hide the list."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.jobs.permissions import JOBS_MANAGE, JOBS_SETTINGS
from ziira.modules.jobs.services import access
from ziira.sdk import NotFound, Session, current_context

NOT_SAMPLE = "not exists (select 1 from jobs.sample_item s where s.item_type = 'job' and s.item_id = {alias}.id)"

CHECKS = {
    "items_chosen": ("select coalesce((select labour_product_id is not null and parts_product_id is not null "
                     "from jobs.setting where company_id = :c), false)"),
    "rates_set": ("select coalesce((select default_labour_rate > 0 from jobs.setting where company_id = :c), false)"),
    "tasks_reviewed": ("select exists (select 1 from jobs.labour_task where company_id = :c) and not exists "
                       "(select 1 from jobs.labour_task where company_id = :c and is_active and is_example)"),
    "first_job": f"select exists (select 1 from jobs.job j where j.company_id = :c and {NOT_SAMPLE.format(alias='j')})",
    "first_estimate": ("select exists (select 1 from jobs.estimate e join jobs.job j on j.id = e.job_id "
                       f"where e.company_id = :c and e.status <> 'draft' and {NOT_SAMPLE.format(alias='j')})"),
    "bays": "select exists (select 1 from jobs.bay where company_id = :c and is_active)",
    "reminders": ("select coalesce((select remind_service_due from jobs.setting where company_id = :c), false)"),
    "first_invoice": ("select exists (select 1 from jobs.job j where j.company_id = :c and j.invoiced_at is not null "
                      f"and {NOT_SAMPLE.format(alias='j')})"),
}


def steps_for(session: Session, company_id: UUID) -> list[dict[str, Any]]:
    """The pack's steps for the company, each with `done` (worked out now). Empty when no pack gave any."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    rows = [dict(r._mapping) for r in session.execute(text(
        "select * from jobs.pack_step where company_id = :c order by sort_order, created_at"), {"c": str(company_id)})]
    for r in rows:
        sql = CHECKS.get(r["check_key"] or "")
        done = bool(r["done_at"])
        if not done and sql:
            done = bool(session.execute(text(sql), {"c": str(company_id)}).scalar())
            if done:
                session.execute(text("update jobs.pack_step set done_at = now() where id = :i"), {"i": str(r["id"])})
        r["done"] = done
    return rows


def hide(session: Session, company_id: UUID, hidden: bool) -> None:
    """Hide or show the checklist (needs 'jobs.settings')."""
    current_context().require(JOBS_SETTINGS, company_id=company_id)
    session.execute(text("update jobs.pack_step set hidden = :h where company_id = :c"),
                    {"h": hidden, "c": str(company_id)})


def mark_done(session: Session, step_id: UUID, done: bool = True) -> None:
    """Tick (or untick) a step that has no automatic check (needs 'jobs.manage')."""
    row = session.execute(text("select company_id, check_key from jobs.pack_step where id = :i"),
                          {"i": str(step_id)}).first()
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Step not found")
    current_context().require(JOBS_MANAGE, company_id=row.company_id)
    session.execute(text("update jobs.pack_step set done_at = case when :d then now() else null end where id = :i"),
                    {"d": done, "i": str(step_id)})

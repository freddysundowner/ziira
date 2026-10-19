"""Use case: a believable week of sample data for an industry pack, loaded on request and removable.

The recipe is data the pack shipped (`[sample]` in its `data/timebilling.toml`, saved when the pack was seeded): a few
clients, projects of different fee types with their rates, a retainer, milestones, repeating work, a week of the
signed-in person's time, two expenses and a dated task. Loading is refused when sample data is already there; every
row it makes is remembered in `sample_item`, so removing it takes away exactly that.

What is never removed: time that has been submitted, approved or invoiced (it is the business's record, even if it
began as a sample), and the sample clients, which are ordinary customers (named "Sample: ...") that the business can
archive in Customers. Sample clients get an address that cannot receive mail.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from ziira.modules.timebilling.domain.timesheet import round_to_step
from ziira.modules.timebilling.permissions import PROJECTS_MANAGE, TIME_LOG
from ziira.modules.timebilling.repository.models import EngagementTask
from ziira.modules.timebilling.services import (
    access,
    common,
    engagements,
    entries,
    expenses,
    projects,
    rate_cards,
    retainers,
)
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    custom_fields,
)

NO_MAIL = "example.invalid"


def _remember(session: Session, company_id: UUID, pack: str, item_type: str, item_id: UUID, label: str) -> None:
    session.execute(text(
        "insert into timebilling.sample_item (tenant_id, company_id, pack, item_type, item_id, label) "
        "values (kernel.current_tenant(), :c, :p, :t, :i, :l) on conflict do nothing"),
        {"c": str(company_id), "p": pack, "t": item_type, "i": str(item_id), "l": label[:200]})


def status(session: Session, company_id: UUID) -> dict[str, Any]:
    """Whether a recipe is available for the company and whether sample data is loaded now."""
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    recipe = session.execute(text(
        "select pack, recipe->>'note' as note from timebilling.sample_recipe where company_id = :c order by created_at "
        "limit 1"), {"c": str(company_id)}).first()
    loaded = session.execute(text(
        "select count(*) from timebilling.sample_item where company_id = :c and item_type = 'project'"),
        {"c": str(company_id)}).scalar_one()
    return {"available": recipe is not None, "note": recipe.note if recipe else None, "loaded": int(loaded) > 0}


def load(session: Session, company_id: UUID) -> dict[str, int]:
    """Make the sample data. Needs 'projects.manage' and 'time.log'. The time is the signed-in person's own."""
    ctx = current_context()
    ctx.require(PROJECTS_MANAGE, company_id=company_id)
    ctx.require(TIME_LOG, company_id=company_id)
    check_company(session, company_id)
    row = session.execute(text(
        "select pack, recipe from timebilling.sample_recipe where company_id = :c order by created_at limit 1"),
        {"c": str(company_id)}).first()
    if row is None:
        raise NotFound("There is no sample data for this business: switch on an industry pack first")
    if status(session, company_id)["loaded"]:
        raise Conflict("Sample data is already loaded: remove it first")
    pack, recipe = row.pack, row.recipe
    today = common.today(session, company_id)
    setting = common.settings(session, company_id)
    start = today.replace(month=1, day=1)
    made = {"clients": 0, "projects": 0, "entries": 0, "expenses": 0, "tasks": 0}
    clients: dict[str, UUID] = {}
    from ziira.modules.crm.public import change_credit_limit, match_or_create_customer

    for spec in recipe.get("client", []):
        found, _ = match_or_create_customer(
            session, company_id, name=spec["name"], email=f"{spec['key']}@sample.{NO_MAIL}")
        clients[spec["key"]] = found.id
        try:                                        # invoices to a client are credit invoices: they need a limit
            with session.begin_nested():
                change_credit_limit(session, found.id, Decimal("1000000"), "Sample practice")
        except Exception:  # noqa: BLE001 - the sample still loads; the limit can be set in Customers
            pass
        _remember(session, company_id, pack, "client", found.id, spec["name"])
        made["clients"] += 1
    by_key: dict[str, UUID] = {}
    for spec in recipe.get("project", []):
        minutes = int(Decimal(str(spec["budget_hours"])) * 60) if spec.get("budget_hours") else None
        project = projects.create_project(
            session, company_id=company_id, client_id=clients[spec["client"]], code=spec["code"], name=spec["name"],
            billing_mode=spec.get("billing_mode", "time_and_materials"), budget_minutes=minutes,
            fixed_fee=Decimal(str(spec["fixed_fee"])) if spec.get("fixed_fee") else None,
            fee_cap=Decimal(str(spec["fee_cap"])) if spec.get("fee_cap") else None, manager_id=ctx.user_id)
        by_key[spec["key"]] = project.id
        _remember(session, company_id, pack, "project", project.id, project.code)
        made["projects"] += 1
        if spec.get("rate"):
            rate = rate_cards.create_rate(session, company_id=company_id, kind="bill", rate=Decimal(str(spec["rate"])),
                                          effective_from=start, project_id=project.id,
                                          note="Sample rate")
            _remember(session, company_id, pack, "rate", rate.id, f"{project.code} rate")
        if spec.get("monthly_fee"):
            kept = retainers.create_retainer(session, project.id, kind="monthly_fee",
                                             monthly_fee=Decimal(str(spec["monthly_fee"])), auto_draft=False)
            _remember(session, company_id, pack, "retainer", kept.id, project.code)
        for i, m in enumerate(spec.get("milestones", [])):
            milestone = projects.add_milestone(session, project.id, name=m["name"],
                                               amount=Decimal(str(m["amount"])), sort_order=i)
            if m.get("ready"):
                projects.update_milestone(session, milestone.id, status="ready")
            _remember(session, company_id, pack, "milestone", milestone.id, m["name"])
        if spec.get("repeat"):
            again = spec["repeat"]
            rec = engagements.create_recurrence(
                session, project.id, name=spec["name"], frequency=again["frequency"], due_day=again["due_day"],
                due_month=again.get("due_month"), lead_days=again.get("lead_days", 14),
                starts_on=today - timedelta(days=int(again.get("started_days_ago", 0))),
                checklist=list(spec.get("checklist", [])))
            _remember(session, company_id, pack, "recurrence", rec.id, spec["name"])
            for task in session.scalars(select(EngagementTask).where(EngagementTask.recurrence_id == rec.id)):
                _remember(session, company_id, pack, "task", task.id, task.name)
        if spec.get("fields"):
            try:
                defs = custom_fields.definitions_for(session, "timebilling.project", company_id)
                values = custom_fields.validate_values(defs, dict(spec["fields"]), check_required=False)
                custom_fields.write_values(session, "timebilling.project", project.id, values, company_id=company_id)
            except ValidationFailed:
                pass                       # the fields are not set up: the sample is still useful
    for spec in recipe.get("entry", []):
        minutes = round_to_step(int(Decimal(str(spec["hours"])) * 60), setting.minute_step, "nearest")
        try:
            with session.begin_nested():
                entry = entries.create_entry(
                    session, project_id=by_key[spec["project"]], work_date=today - timedelta(days=spec["days_ago"]),
                    minutes=minutes, task=spec.get("task"), note=spec.get("note"),
                    billable=bool(spec.get("billable", True)))
                _remember(session, company_id, pack, "entry", entry.id, spec.get("task") or "time")
                made["entries"] += 1
        except Conflict:
            continue                       # that week was already sent in: leave it alone
    for spec in recipe.get("expense", []):
        try:
            with session.begin_nested():
                spent = expenses.create_expense(
                    session, project_id=by_key[spec["project"]], expense_date=today - timedelta(days=spec["days_ago"]),
                    description=spec["description"], amount=Decimal(str(spec["amount"])),
                    markup_percent=Decimal(str(spec["markup_percent"])) if "markup_percent" in spec else None,
                    category=spec.get("category"))
                _remember(session, company_id, pack, "expense", spent.id, spec["description"])
                made["expenses"] += 1
        except Conflict:
            continue
    for spec in recipe.get("task", []):
        task = engagements.add_task(session, by_key[spec["project"]], name=spec["name"],
                                    due_on=today + timedelta(days=spec["due_in_days"]),
                                    assignee_id=ctx.user_id, checklist=list(spec.get("checklist", [])))
        _remember(session, company_id, pack, "task", task.id, spec["name"])
        made["tasks"] += 1
    audit_record(session, "load_sample", "timebilling.sample", None, {"pack": pack, **made})
    return made


def remove(session: Session, company_id: UUID) -> dict[str, int]:
    """Take away what loading made, except time that was submitted, approved or invoiced (it stays, with its project)
    and the sample clients (ordinary customers: archive them in Customers). Needs 'projects.manage'."""
    current_context().require(PROJECTS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    ids: dict[str, list[str]] = {}
    for r in session.execute(text("select item_type, item_id from timebilling.sample_item where company_id = :c"),
                             {"c": str(company_id)}):
        ids.setdefault(r.item_type, []).append(str(r.item_id))
    gone = {"entries": 0, "expenses": 0, "projects": 0}
    kept = {"entries": 0, "projects": 0}

    def run(sql: str, key: str) -> Any:
        return session.execute(text(sql), {"i": ids.get(key, [])})

    run("delete from timebilling.engagement_task where id = any(cast(:i as uuid[]))", "task")
    # a task made from a recurrence that has since been made by the worker belongs to the sample as well
    session.execute(text(
        "delete from timebilling.engagement_task where recurrence_id = any(cast(:i as uuid[]))"),
        {"i": ids.get("recurrence", [])})
    run("delete from timebilling.recurrence where id = any(cast(:i as uuid[]))", "recurrence")
    gone["entries"] = run("delete from timebilling.entry where id = any(cast(:i as uuid[])) and status = 'draft' "
                          "and batch_id is null and invoice_id is null", "entry").rowcount or 0
    kept["entries"] = len(ids.get("entry", [])) - gone["entries"]
    gone["expenses"] = run("delete from timebilling.expense where id = any(cast(:i as uuid[])) and status = 'draft' "
                           "and batch_id is null and invoice_id is null", "expense").rowcount or 0
    run("delete from timebilling.milestone where id = any(cast(:i as uuid[])) and status <> 'invoiced' "
        "and batch_id is null", "milestone")
    run("delete from timebilling.retainer where id = any(cast(:i as uuid[])) and not exists "
        "(select 1 from timebilling.retainer_txn t where t.retainer_id = retainer.id)", "retainer")
    free = [p for p in ids.get("project", []) if session.execute(text(
        "select not exists (select 1 from timebilling.entry where project_id = :p) "
        "and not exists (select 1 from timebilling.expense where project_id = :p) "
        "and not exists (select 1 from timebilling.invoice_batch_line where project_id = :p) "
        "and not exists (select 1 from timebilling.retainer where project_id = :p) "
        "and not exists (select 1 from timebilling.milestone where project_id = :p)"), {"p": p}).scalar()]
    session.execute(text("delete from timebilling.rate where project_id = any(cast(:i as uuid[])) "
                         "and note = 'Sample rate'"), {"i": free})
    for pid in free:
        saved = custom_fields.read_values(session, "timebilling.project", UUID(pid))
        if saved:
            custom_fields.write_values(session, "timebilling.project", UUID(pid), {k: "" for k in saved},
                                       company_id=company_id)
    session.execute(text("delete from timebilling.project where id = any(cast(:i as uuid[]))"), {"i": free})
    gone["projects"] = len(free)
    kept["projects"] = len(ids.get("project", [])) - gone["projects"]
    session.execute(text("delete from timebilling.sample_item where company_id = :c"), {"c": str(company_id)})
    audit_record(session, "remove_sample", "timebilling.sample", None, {**gone, "kept_entries": kept["entries"]})
    return {**gone, "kept_entries": kept["entries"], "kept_projects": kept["projects"]}

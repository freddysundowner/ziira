"""Industry packs for Jobs: what a garage, body shop, repair shop or tailor starts with, copied from the pack's
`data/jobs.toml`.

A pack may supply the stages and moves a business works with, intake checklists, suggested settings, work types
(mechanical, body, paint, electrical), a task library with standard times (marked as examples: standard times differ by
make and workshop), part categories with a markup, kinds of photo, job types (with the photos each must have), bays, the
first-run checklist, Intelligence limits and a believable sample week. Everything is data the business can edit; nothing
is overwritten once the business has changed it; and prices in a pack are never invented.

`data/jobs.toml` shape:

    [settings]                         # applied once, while no pack has set this business's job settings
    default_warranty_days = 30
    release_unpaid = "warn"
    labour_sku = "GAR-LABOUR"          # the Products service items labour, parts and fees are invoiced under
    [[status]] [[move]] [[checklist]]  # as in docs/jobs.md
    [[work_type]]                      # code, name, rate (optional)
    [[task]]                           # code, name, hours, work_type, flat_price (optional), asset_kind
    [[part_category]]                  # code, name, markup, class
    [[photo_category]]                 # code, name
    [[job_type]]                       # code, name, checklist (name), warranty_days, photos = [{category, min, before}]
    [[bay]]                            # name
    [[step]]                           # id, title, hint, to, check
    [intel."jobs.stuck_in_stage"]      # limits for an Intelligence check
    [sample]                           # the sample week (see sample_data.py)
"""

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.jobs.domain.workflow import Definition, StatusDef
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.services import catalog, photos, statuses
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import unit_enabled
from ziira.sdk import (
    INDUSTRY_SEEDER,
    PackData,
    SeededItem,
    SeedReport,
    Session,
    ValidationFailed,
    implementations,
)

SETTING_KEYS = ("default_labour_rate", "default_warranty_days", "estimate_valid_days", "tell_customer_when_ready",
                "odometer_unit", "unapproved_work", "release_unpaid", "required_photos", "storage_fee_per_day",
                "storage_grace_days", "remind_service_due", "service_reminder_days", "ready_reminder_days")
SKU_KEYS = {"labour_sku": "labour_product_id", "parts_sku": "parts_product_id", "fees_sku": "fees_product_id"}


def seed(session: Session, pack: PackData, company_id: UUID) -> SeedReport:
    """Copy the pack's job data for the company. Idempotent: running it again adds what is missing only."""
    report = SeedReport()
    data = pack.unit_data("jobs")
    if not data:
        return report
    _products_first(session, pack, company_id, report)
    _stages(session, company_id, data, report)
    _checklists(session, company_id, data, report)
    _settings(session, pack, company_id, data.get("settings", {}), report)
    _work_types(session, company_id, data.get("work_type", []), report)
    _tasks(session, company_id, data.get("task", []), report)
    _part_categories(session, company_id, data.get("part_category", []), report)
    _photo_categories(session, company_id, data.get("photo_category", []), report)
    _job_types(session, company_id, data.get("job_type", []), report)
    _bays(session, company_id, data.get("bay", []), report)
    _steps(session, pack, company_id, data.get("step", []), report)
    if data.get("sample"):
        session.execute(text(
            "insert into jobs.sample_recipe (tenant_id, company_id, pack, recipe) values "
            "(kernel.current_tenant(), :c, :p, cast(:r as jsonb)) on conflict (company_id, pack) do nothing"),
            {"c": str(company_id), "p": pack.name, "r": json.dumps(data["sample"], default=str)})
    if data.get("intel") and unit_enabled(session, "intel"):
        from ziira.modules.intel.public import apply_check_defaults

        done = apply_check_defaults(session, {code: dict(p) for code, p in data["intel"].items()})
        if done:
            report.notes.append(f"Intelligence limits suggested for: {', '.join(done)}")
    return report


# --------------------------------------------------------------------------- pieces
def _products_first(session: Session, pack: PackData, company_id: UUID, report: SeedReport) -> None:
    """The service items of the pack come from Products' own seeder. Which seeder runs first is not promised, so run it
    now (it only adds what is missing) and report what it added as ours; the kernel's later call finds nothing to do."""
    if not unit_enabled(session, "products"):
        return
    for seeder in implementations(session, INDUSTRY_SEEDER):
        if getattr(seeder, "unit", "") == "products":
            made = seeder.seed(session, pack, company_id)
            report.added.extend(made.added)
            report.notes.extend(made.notes)


def _stages(session: Session, company_id: UUID, data: dict[str, Any], report: SeedReport) -> None:
    given = data.get("status", [])
    if not given and not data.get("move"):
        return
    statuses.ensure_seeded(session, company_id)
    before = {s.code for s in repo.statuses(session, company_id)}
    definition = Definition(
        [StatusDef(str(s["code"]), str(s["name"]), str(s["kind"]), s.get("role")) for s in given],
        [(str(m["from"]), str(m["to"])) for m in data.get("move", [])])
    if definition.statuses or definition.moves:
        if definition.statuses:
            statuses.seed_statuses(session, company_id, definition)
        else:
            statuses.seed_statuses(session, company_id, Definition(
                [StatusDef("received", "Received", "open", "initial")], definition.moves))
    wanted = {s.code for s in definition.statuses}
    for row in repo.statuses(session, company_id):
        if row.code not in before and row.code in wanted:
            report.added.append(SeededItem("job_status", row.id, row.name))
    report.skipped += len(before & wanted)


def _checklists(session: Session, company_id: UUID, data: dict[str, Any], report: SeedReport) -> None:
    for item in data.get("checklist", []):
        items = [str(i) for i in item.get("items", [])]
        if job_settings.seed_template(session, company_id, str(item["name"]), items, item.get("asset_kind")):
            made = repo.template_by_name(session, company_id, str(item["name"]).strip())
            if made is not None:
                report.added.append(SeededItem("checklist_template", made.id, made.name))
        else:
            report.skipped += 1


def _settings(session: Session, pack: PackData, company_id: UUID, given: dict[str, Any], report: SeedReport) -> None:
    if not given:
        return
    row = job_settings.get_settings(session, company_id)
    changes: dict[str, Any] = {}
    first = row.pack_name is None
    if first:
        for key in SETTING_KEYS:
            if key in given:
                value = given[key]
                changes[key] = Decimal(str(value)) if key in ("default_labour_rate", "storage_fee_per_day") else value
        if row.default_labour_rate != 0:
            changes.pop("default_labour_rate", None)           # a rate the business already set is theirs
    else:
        report.skipped += 1
    # The service items come from Products' seeder, which needs a unit of measure and a tax code: when they were not
    # there yet the link is made on a later run, whenever the business has not chosen one itself.
    from ziira.modules.products.public import find_product_by_sku

    for key, field in SKU_KEYS.items():
        if key in given and getattr(row, field) is None:
            found = find_product_by_sku(session, company_id, str(given[key]))
            if found is not None and found.product_type != "stock":
                changes[field] = found.id
            elif first:
                report.notes.append(f"{given[key]} is not in Products yet: choose the {key[:-4]} item in job settings")
    if changes:
        try:
            job_settings.update_settings(session, company_id, **changes)
        except ValidationFailed as exc:
            report.notes.append(f"Some job settings were not applied: {exc}")
    if first:
        row.pack_name = pack.name
        report.notes.append("Job settings set to the pack's suggestions")
    session.flush()


def _work_types(session: Session, company_id: UUID, specs: list[dict[str, Any]], report: SeedReport) -> None:
    for position, spec in enumerate(specs, start=1):
        code = catalog.make_code(str(spec.get("code") or spec["name"]))
        if repo.work_type_by_code(session, company_id, code) is not None:
            report.skipped += 1
            continue
        rate = Decimal(str(spec["rate"])) if spec.get("rate") is not None else None
        made = catalog.create_work_type(session, company_id=company_id, name=str(spec["name"]), code=code,
                                        hourly_rate=rate, position=position)
        report.added.append(SeededItem("work_type", made.id, made.name))


def _tasks(session: Session, company_id: UUID, specs: list[dict[str, Any]], report: SeedReport) -> None:
    for spec in specs:
        code = catalog.make_code(str(spec.get("code") or spec["name"]))
        if repo.labour_task_by_code(session, company_id, code) is not None:
            report.skipped += 1
            continue
        work_type = str(spec["work_type"]) if spec.get("work_type") else None
        if work_type and repo.work_type_by_code(session, company_id, work_type) is None:
            work_type = None
        flat = Decimal(str(spec["flat_price"])) if spec.get("flat_price") is not None else None
        made = catalog.create_task(session, company_id=company_id, name=str(spec["name"]), code=code,
                                   standard_hours=Decimal(str(spec["hours"])), work_type_code=work_type,
                                   flat_price=flat, asset_kind=spec.get("asset_kind"), is_example=True)
        report.added.append(SeededItem("labour_task", made.id, made.name))


def _part_categories(session: Session, company_id: UUID, specs: list[dict[str, Any]], report: SeedReport) -> None:
    for position, spec in enumerate(specs, start=1):
        code = catalog.make_code(str(spec.get("code") or spec["name"]))
        if repo.part_category_by_code(session, company_id, code) is not None:
            report.skipped += 1
            continue
        made = catalog.create_part_category(
            session, company_id=company_id, name=str(spec["name"]), code=code,
            markup_percent=Decimal(str(spec.get("markup", 0))), default_class=spec.get("class"), position=position)
        report.added.append(SeededItem("part_category", made.id, made.name))


def _photo_categories(session: Session, company_id: UUID, specs: list[dict[str, Any]], report: SeedReport) -> None:
    have = {c.code for c in photos.list_categories(session, company_id)}
    for position, spec in enumerate(specs, start=1):
        code = catalog.make_code(str(spec.get("code") or spec["name"]))
        if code in have:
            report.skipped += 1
            continue
        made = photos.create_category(session, company_id=company_id, name=str(spec["name"]), code=code,
                                      position=position)
        report.added.append(SeededItem("photo_category", made.id, made.name))


def _job_types(session: Session, company_id: UUID, specs: list[dict[str, Any]], report: SeedReport) -> None:
    for position, spec in enumerate(specs, start=1):
        code = catalog.make_code(str(spec.get("code") or spec["name"]))
        if repo.job_type_by_code(session, company_id, code) is not None:
            report.skipped += 1
            continue
        template = repo.template_by_name(session, company_id, str(spec["checklist"])) if spec.get("checklist") else None
        made = catalog.create_job_type(
            session, company_id=company_id, name=str(spec["name"]), code=code,
            checklist_template_id=template.id if template else None,
            default_warranty_days=spec.get("warranty_days"), position=position,
            required_photos=[dict(p) for p in spec.get("photos", [])])
        report.added.append(SeededItem("job_type", made.id, made.name))


def _bays(session: Session, company_id: UUID, specs: list[dict[str, Any]], report: SeedReport) -> None:
    if not specs:
        return
    branch = session.execute(text(
        "select id from kernel.branch where company_id = :c order by created_at, name limit 1"),
        {"c": str(company_id)}).first()
    if branch is None:
        return
    from ziira.modules.jobs.services import bays

    have = {b.name.lower() for b in bays.list_bays(session, company_id, branch.id)}
    for position, spec in enumerate(specs, start=1):
        if str(spec["name"]).lower() in have:
            report.skipped += 1
            continue
        made = bays.create_bay(session, company_id=company_id, branch_id=branch.id, name=str(spec["name"]),
                               position=position)
        report.added.append(SeededItem("bay", made.id, made.name))


def _steps(session: Session, pack: PackData, company_id: UUID, specs: list[dict[str, Any]], report: SeedReport) -> None:
    for order, spec in enumerate(specs):
        made = session.execute(text(
            "insert into jobs.pack_step (tenant_id, company_id, pack, step_id, title, hint, to_path, check_key, "
            "sort_order) values (kernel.current_tenant(), :c, :p, :s, :t, :h, :to, :k, :o) "
            "on conflict (company_id, pack, step_id) do nothing returning id"),
            {"c": str(company_id), "p": pack.name, "s": spec["id"], "t": spec["title"], "h": spec.get("hint"),
             "to": spec.get("to"), "k": spec.get("check"), "o": order}).first()
        if made is None:
            report.skipped += 1
        else:
            report.added.append(SeededItem("pack_step", made.id, spec["title"]))


# --------------------------------------------------------------------------- switching a pack off
def untouched(session: Session, item_type: str, item_id: UUID) -> bool:
    """A row the pack added that nobody changed or used."""
    if item_type == "job_status":
        return session.execute(text(
            "select not exists (select 1 from jobs.job where status_id = :i) "
            "and not exists (select 1 from jobs.job_event where from_status_id = :i or to_status_id = :i) "
            "and (select updated_at is null from jobs.job_status where id = :i)"),
            {"i": str(item_id)}).scalar() is True
    if item_type == "checklist_template":
        return session.execute(text("select updated_at is null from jobs.checklist_template where id = :i"),
                               {"i": str(item_id)}).scalar() is True
    if item_type == "labour_task":
        return session.execute(text(
            "select is_example and not exists (select 1 from jobs.job_labour l, jobs.labour_task t "
            "where t.id = :i and l.task_code = t.code) from jobs.labour_task where id = :i"),
            {"i": str(item_id)}).scalar() is True
    if item_type == "work_type":
        return session.execute(text(
            "select updated_at is null and not exists "
            "(select 1 from jobs.job_labour l where l.work_type_code = w.code) "
            "from jobs.work_type w where w.id = :i"), {"i": str(item_id)}).scalar() is True
    if item_type == "part_category":
        return session.execute(text(
            "select updated_at is null and not exists (select 1 from jobs.job_part p where p.category_code = c.code) "
            "from jobs.part_category c where c.id = :i"), {"i": str(item_id)}).scalar() is True
    if item_type == "job_type":
        return session.execute(text(
            "select updated_at is null and not exists (select 1 from jobs.job j where j.job_type_code = t.code) "
            "from jobs.job_type t where t.id = :i"), {"i": str(item_id)}).scalar() is True
    if item_type == "photo_category":
        return session.execute(text("select updated_at is null from jobs.photo_category where id = :i"),
                               {"i": str(item_id)}).scalar() is True
    if item_type == "bay":
        return session.execute(text(
            "select updated_at is null and not exists (select 1 from jobs.bay_booking b where b.bay_id = y.id) "
            "from jobs.bay y where y.id = :i"), {"i": str(item_id)}).scalar() is True
    if item_type == "product":
        return any(s.untouched(session, item_type, item_id) for s in implementations(session, INDUSTRY_SEEDER)
                   if getattr(s, "unit", "") == "products")
    return item_type == "pack_step"


def remove(session: Session, item_type: str, item_id: UUID) -> None:
    if item_type == "job_status":
        session.execute(text("delete from jobs.job_status_move where from_status_id = :i or to_status_id = :i"),
                        {"i": str(item_id)})
        session.execute(text("delete from jobs.job_status where id = :i"), {"i": str(item_id)})
        return
    if item_type == "product":
        for s in implementations(session, INDUSTRY_SEEDER):
            if getattr(s, "unit", "") == "products":
                s.remove(session, item_type, item_id)
        return
    table = {"checklist_template": "checklist_template", "labour_task": "labour_task", "work_type": "work_type",
             "part_category": "part_category", "job_type": "job_type", "photo_category": "photo_category",
             "bay": "bay", "pack_step": "pack_step"}[item_type]
    session.execute(text(f"delete from jobs.{table} where id = :i"), {"i": str(item_id)})

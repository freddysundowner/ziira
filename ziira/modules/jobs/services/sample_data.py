"""Use case: a believable week of sample jobs for an industry pack, loaded on request and removable.

The recipe is data the pack shipped (`[sample]` in its `data/jobs.toml`, saved when the pack was seeded): a few
customers and their vehicles or garments, and jobs in different stages with parts and labour, estimates asked and
answered, a part on order, a finished job nobody collected, and (when the Claims unit is on) an insurer job with its
claim. Loading is refused when sample data is already there; every row it makes is remembered in `sample_item`,
so removing it takes away exactly that.

What is never removed: a sample job that was invoiced (it is the business's record), and the sample customers, which are
ordinary customers (named "Sample: ...") the business can archive in Customers. Sample customers get an address that
cannot receive mail.
"""

import json
from collections import deque
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.jobs.permissions import JOBS_SETTINGS
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, JobStatus
from ziira.modules.jobs.services import access, assets, claims_link, estimates, jobs, parts, statuses
from ziira.modules.jobs.services.common import unit_enabled
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_today,
    current_context,
)

NO_MAIL = "example.invalid"


def _remember(session: Session, company_id: UUID, pack: str, item_type: str, item_id: UUID, label: str) -> None:
    session.execute(text(
        "insert into jobs.sample_item (tenant_id, company_id, pack, item_type, item_id, label) "
        "values (kernel.current_tenant(), :c, :p, :t, :i, :l) on conflict do nothing"),
        {"c": str(company_id), "p": pack, "t": item_type, "i": str(item_id), "l": label[:200]})


def status(session: Session, company_id: UUID) -> dict[str, Any]:
    """Whether a recipe is available for the company and whether sample data is loaded now."""
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    recipe = session.execute(text(
        "select pack, recipe->>'note' as note from jobs.sample_recipe where company_id = :c order by created_at "
        "limit 1"), {"c": str(company_id)}).first()
    loaded = session.execute(text("select count(*) from jobs.sample_item where company_id = :c and item_type = 'job'"),
                             {"c": str(company_id)}).scalar_one()
    return {"available": recipe is not None, "loaded": int(loaded) > 0, "pack": recipe.pack if recipe else None,
            "note": recipe.note if recipe else None}


def _main_branch(session: Session, company_id: UUID) -> UUID:
    row = session.execute(text("select id from kernel.branch where company_id = :c order by created_at, name limit 1"),
                          {"c": str(company_id)}).first()
    if row is None:
        raise ValidationFailed("This business has no branch yet")
    return row.id  # type: ignore[no-any-return]


def _route(session: Session, company_id: UUID, start: str, goal: str) -> list[str]:
    """The stage codes to walk from `start` to `goal` through the moves the workflow allows (shortest way)."""
    by_id = {s.id: s.code for s in repo.statuses(session, company_id)}
    graph: dict[str, list[str]] = {}
    for m in repo.moves(session, company_id):
        graph.setdefault(by_id[m.from_status_id], []).append(by_id[m.to_status_id])
    queue: deque[list[str]] = deque([[start]])
    seen = {start}
    while queue:
        path = queue.popleft()
        if path[-1] == goal:
            return path[1:]
        for nxt in graph.get(path[-1], []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append([*path, nxt])
    return []


def _walk_to(session: Session, job: Job, goal: str) -> bool:
    """Move a job through the stages to `goal`. False when there is no way or a rule (photos, payment) stopped it."""
    current = repo.get(session, JobStatus, job.status_id)
    assert current is not None
    for code in _route(session, job.company_id, current.code, goal):
        target = repo.status_by_code(session, job.company_id, code)
        if target is None:
            return False
        try:
            jobs.change_status(session, job.id, target.id, "Sample", collected_by_name="Sample customer",
                               acknowledge_unpaid=True)
        except (ValidationFailed, Conflict):
            return False
    return True


def _customer(session: Session, company_id: UUID, pack: str, spec: dict[str, Any], made: dict[str, UUID]) -> UUID:
    name = str(spec["customer"])
    if name in made:
        return made[name]
    from ziira.modules.crm.public import match_or_create_customer

    slug = "".join(c for c in name.lower() if c.isalnum())[:24] or "customer"
    found, created = match_or_create_customer(session, company_id, name=name, email=f"{slug}@{NO_MAIL}")
    if created:
        _remember(session, company_id, pack, "customer", found.id, name)
    made[name] = found.id
    return found.id


def load(session: Session, company_id: UUID) -> dict[str, int]:
    """Fill the business with the sample week its industry pack ships. Needs 'jobs.settings'. Returns what was made."""
    ctx = current_context()
    ctx.require(JOBS_SETTINGS, company_id=company_id)
    info = status(session, company_id)
    if not info["available"]:
        raise ValidationFailed("No industry pack with sample data is switched on for this business")
    if info["loaded"]:
        raise Conflict("Sample data is already there. Take it away first")
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Sample jobs need Customers to be switched on")
    row = session.execute(text("select pack, recipe from jobs.sample_recipe where company_id = :c limit 1"),
                          {"c": str(company_id)}).one()
    pack, recipe = row.pack, row.recipe if isinstance(row.recipe, dict) else json.loads(row.recipe)
    statuses.ensure_seeded(session, company_id)
    branch_id = _main_branch(session, company_id)
    today = company_today(session, company_id)
    counts = {"customers": 0, "items": 0, "jobs": 0, "claims": 0}
    customers: dict[str, UUID] = {}
    payer_id: UUID | None = None
    for spec in recipe.get("job", []):
        customer_id = _customer(session, company_id, pack, spec, customers)
        item = spec.get("item", {})
        new_asset = jobs.NewAsset(label=str(item["label"]), kind=str(item.get("kind", "item")),
                                  identifiers={k: str(v) for k, v in item.get("identifiers", {}).items()},
                                  notes="Sample") if item else None
        job = jobs.receive_job(
            session, company_id=company_id, branch_id=branch_id, title=str(spec["title"]), customer_id=customer_id,
            new_asset=new_asset, job_type_code=spec.get("type"), odometer_in=Decimal(str(item["odometer"]))
            if item.get("odometer") is not None else None, fuel_level=spec.get("fuel"), key_tag=spec.get("key_tag"),
            description=spec.get("description"), condition_notes=spec.get("condition"),
            promised_at=today + timedelta(days=int(spec["promised_in_days"])) if "promised_in_days" in spec else None,
            acknowledged_by_name=spec.get("acknowledged_by"))
        counts["jobs"] += 1
        _remember(session, company_id, pack, "job", job.id, job.number)
        if job.asset_id is not None:
            counts["items"] += 1
            _remember(session, company_id, pack, "asset", job.asset_id, str(item.get("label", "")))
        _fill(session, job, spec, today)
        if spec.get("claim") and unit_enabled(session, "claims"):
            payer_id = _claim(session, company_id, pack, job, spec["claim"], payer_id)
            counts["claims"] += 1
        goal = spec.get("stage")
        if goal and goal != "received":
            _walk_to(session, job, str(goal))
        _backdate(session, job, spec, today)
    audit_record(session, "sample_data", "jobs.job", None, {"company_id": str(company_id), **counts})
    counts["customers"] = len(customers)
    return counts


def _fill(session: Session, job: Job, spec: dict[str, Any], today: date) -> None:
    for work in spec.get("labour", []):
        parts.add_labour(session, job.id, hours=Decimal(str(work["hours"])) if work.get("hours") else None,
                         description=work.get("description"), task_code=work.get("task"),
                         work_type_code=work.get("work_type"),
                         booked_hours=Decimal(str(work["booked"])) if work.get("booked") is not None else None)
    for part in spec.get("parts", []):
        parts.add_part(
            session, job.id, quantity=Decimal(str(part.get("qty", 1))), description=part["description"],
            unit_price=Decimal(str(part["price"])) if part.get("price") is not None else None,
            part_class=part.get("class"), customer_supplied=bool(part.get("customer_supplied")),
            order_for_job=bool(part.get("order")), supplier_name=part.get("supplier"),
            expected_on=today + timedelta(days=int(part["expected_in_days"])) if "expected_in_days" in part else None)
    kind = spec.get("estimate")
    if kind in ("sent", "approved"):
        made = estimates.create_estimate(session, job.id, from_job=True)
        sent, _ = estimates.send_estimate(session, made.id)
        if kind == "approved":
            estimates.decide(session, sent.id, approved=True, customer_name="Sample customer")
    if job.asset_id is not None and (spec.get("next_service_in_days") or spec.get("next_service_odometer")):
        asset = assets.load_asset(session, job.asset_id)
        assets.set_next_service(
            session, asset, date_=today + timedelta(days=int(spec["next_service_in_days"]))
            if spec.get("next_service_in_days") is not None else None,
            odometer=Decimal(str(spec["next_service_odometer"])) if spec.get("next_service_odometer") else None,
            note=spec.get("next_service_note"), job=job)


def _claim(session: Session, company_id: UUID, pack: str, job: Job, spec: dict[str, Any],
           payer_id: UUID | None) -> UUID:
    from ziira.modules.claims.public import ensure_payer

    if payer_id is None:
        payer_id = ensure_payer(
            session, company_id, str(spec.get("payer", "Sample: Insurer")), labour_rates={
                k: str(v) for k, v in spec.get("labour_rates", {}).items()},
            parts_discount_pct=Decimal(str(spec.get("parts_discount_pct", 0))),
            required_documents=list(spec.get("documents", [])),
            new_customer={"name": str(spec.get("payer", "Sample: Insurer")),
                          "email": f"claims@{NO_MAIL}"})
        _remember(session, company_id, pack, "payer", payer_id, str(spec.get("payer", "Sample: Insurer")))
    fresh = session.get(Job, job.id)
    assert fresh is not None
    created = claims_link.open_claim(
        session, fresh, payer_id=payer_id, policy_number=spec.get("policy"), claim_number=spec.get("claim_number"),
        excess_amount=Decimal(str(spec.get("excess", 0))))
    _remember(session, company_id, pack, "claim", created.id, created.number)
    if spec.get("draft_estimate", True):
        claims_link.draft_estimate(session, fresh)
    return payer_id


def _backdate(session: Session, job: Job, spec: dict[str, Any], today: date) -> None:
    """Make the job look as if it had been going for a few days."""
    days = int(spec.get("days_ago", 0))
    in_stage = int(spec.get("days_in_stage", min(days, 1)))
    session.execute(text(
        "update jobs.job set received_at = now() - make_interval(days => :d), "
        "status_changed_at = now() - make_interval(days => :s), "
        "ready_at = case when ready_at is not null then now() - make_interval(days => :s) end, "
        "collected_at = case when collected_at is not null then now() - make_interval(days => :s) end, "
        "estimate_sent_at = case when estimate_sent_at is not null then now() - make_interval(days => :d) end "
        "where id = :j"), {"d": days, "s": in_stage, "j": str(job.id)})
    session.flush()
    session.expire(job)


def remove(session: Session, company_id: UUID) -> dict[str, int]:
    """Take the sample jobs away again: their parts, labour, estimates, claims and items. A sample job that was invoiced
    stays (and so do the sample customers). Needs 'jobs.settings'."""
    current_context().require(JOBS_SETTINGS, company_id=company_id)
    check_company(session, company_id)
    removed = {"jobs": 0, "kept": 0, "items": 0, "claims": 0}
    items = session.execute(text(
        "select item_type, item_id from jobs.sample_item where company_id = :c order by created_at desc"),
        {"c": str(company_id)}).all()
    kept_jobs: set[UUID] = set()
    for row in items:
        if row.item_type == "job":
            job = session.get(Job, row.item_id)
            if job is None:
                continue
            if job.invoiced_at is not None:
                kept_jobs.add(job.id)
                removed["kept"] += 1
                continue
            if job.claim_id is not None and unit_enabled(session, "claims"):
                from ziira.modules.claims.public import close_claim_for_source

                if close_claim_for_source(session, "job", job.id, reason="cancelled", note="Sample data removed"):
                    removed["claims"] += 1
            _delete_job(session, job)
            removed["jobs"] += 1
    for row in items:
        if row.item_type == "asset":
            still = session.execute(text("select 1 from jobs.job where asset_id = :a limit 1"),
                                    {"a": str(row.item_id)}).first()
            if still is None:
                session.execute(text("delete from jobs.asset where id = :a"), {"a": str(row.item_id)})
                removed["items"] += 1
        elif row.item_type == "payer" and unit_enabled(session, "claims"):
            from ziira.modules.claims.public import retire_payer

            retire_payer(session, row.item_id)
    session.execute(text("delete from jobs.sample_item where company_id = :c "
                         "and item_type in ('job', 'asset', 'claim') "
                         "and not (item_type = 'job' and item_id = any(cast(:k as uuid[])))"),
                    {"c": str(company_id), "k": [str(k) for k in kept_jobs]})
    audit_record(session, "sample_data_removed", "jobs.job", None, {"company_id": str(company_id), **removed})
    return removed


def _delete_job(session: Session, job: Job) -> None:
    """Remove a sample job and everything that hangs off it (stock parts go back on the shelf first)."""
    for part in repo.parts(session, job.id, include_voided=False):
        if part.is_stock:
            parts.remove_part(session, job.id, part.id, "Sample data removed")
    for table in ("job_checklist_item", "job_event", "job_task", "job_part", "job_labour", "job_charge", "loan",
                  "bay_booking"):
        session.execute(text(f"delete from jobs.{table} where job_id = :j"), {"j": str(job.id)})
    session.execute(text("delete from jobs.estimate_line where estimate_id in "
                         "(select id from jobs.estimate where job_id = :j)"), {"j": str(job.id)})
    session.execute(text("delete from jobs.estimate where job_id = :j"), {"j": str(job.id)})
    session.execute(text("update jobs.job set rework_of_id = null where rework_of_id = :j"), {"j": str(job.id)})
    session.execute(text("delete from jobs.job where id = :j"), {"j": str(job.id)})

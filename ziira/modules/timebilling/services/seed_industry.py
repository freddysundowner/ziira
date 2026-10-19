"""Use case: copy what an industry pack ships in `data/timebilling.toml` into a company's time and billing data.

    [settings]               key = value for the company's time settings, applied only while nobody has saved them
    [[template]]             engagement templates: name, description, billing_mode, budget_hours, frequency, due_day,
                             due_month, lead_days, checklist = [...], and [[template.milestone]] name, percent
    [[rate]]                 EXAMPLE rates by job title (role_title, rate, note): they price nothing until the business
                             confirms each one on the rate card
    [[activity]]             the names people pick for what they did (name, group, billable)
    [[snippet]]              standard invoice wording (kind, name, language, body)
    [intel."<check code>"]   limits for Intelligence checks, applied only to checks the business has never tuned

Idempotent and non-destructive: a name the business already has is left alone, and anything a person deleted on purpose
(the pack's seed log remembers what it added) is never brought back.
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from ziira.modules.timebilling.repository.models import Activity, EngagementTemplate, Rate, Snippet
from ziira.modules.timebilling.services import access, common, engagements
from ziira.modules.timebilling.services.settings import SETTING_FIELDS
from ziira.sdk import PackData, SeededItem, SeedReport, Session, current_context

SEEDER = "timebilling"


def _was_seeded(session: Session, pack: str, company_id: UUID, item_type: str, label: str) -> bool:
    """True when the pack added this before (so a missing row was removed on purpose)."""
    return session.execute(text(
        "select 1 from kernel.pack_seed_log where pack = :p and company_id = :c and seeder = :s and item_type = :t "
        "and item_label = :l limit 1"), {"p": pack, "c": str(company_id), "s": SEEDER, "t": item_type,
                                         "l": label}).first() is not None


def seed(session: Session, pack: PackData, company_id: UUID) -> SeedReport:
    report = SeedReport()
    data = pack.unit_data(SEEDER)
    if not data:
        return report
    ctx = current_context()
    _settings(session, data.get("settings", {}), company_id, report)
    for spec in data.get("template", []):
        name = str(spec["name"]).strip()
        exists = session.scalar(select(EngagementTemplate.id).where(
            EngagementTemplate.company_id == company_id, EngagementTemplate.name == name))
        if exists is not None or _was_seeded(session, pack.name, company_id, "engagement_template", name):
            report.skipped += 1
            continue
        minutes = int(Decimal(str(spec["budget_hours"])) * 60) if spec.get("budget_hours") else None
        template = EngagementTemplate(
            tenant_id=ctx.tenant_id, company_id=company_id, name=name, description=spec.get("description"),
            billing_mode=spec.get("billing_mode", "time_and_materials"), budget_minutes=minutes,
            frequency=spec.get("frequency"), due_day=spec.get("due_day"), due_month=spec.get("due_month"),
            lead_days=int(spec.get("lead_days", 14)), checklist=engagements.clean_items(spec.get("checklist")),
            milestones=[{"name": m["name"], "percent": str(m.get("percent", 0))} for m in spec.get("milestone", [])],
            source=f"pack:{pack.name}")
        session.add(template)
        session.flush()
        report.added.append(SeededItem("engagement_template", template.id, name))
    today = common.today(session, company_id)
    for spec in data.get("rate", []):
        title = str(spec["role_title"]).strip()
        have = session.scalar(select(Rate.id).where(
            Rate.company_id == company_id, Rate.kind == "bill", Rate.project_id.is_(None), Rate.client_id.is_(None),
            Rate.user_id.is_(None), Rate.service_product_id.is_(None),
            text("lower(role_title) = :t").bindparams(t=title.casefold())))
        if have is not None or _was_seeded(session, pack.name, company_id, "example_rate", title):
            report.skipped += 1
            continue
        rate = Rate(tenant_id=ctx.tenant_id, company_id=company_id, kind="bill", role_title=title,
                   rate=Decimal(str(spec["rate"])), effective_from=_start(today), example=True,
                   note=str(spec.get("note") or f"Example from the {pack.title} pack: set your own rate")[:500])
        session.add(rate)
        session.flush()
        report.added.append(SeededItem("example_rate", rate.id, title))
    for i, spec in enumerate(data.get("activity", [])):
        name = str(spec["name"]).strip()
        exists = session.scalar(select(Activity.id).where(Activity.company_id == company_id, Activity.name == name))
        if exists is not None or _was_seeded(session, pack.name, company_id, "activity", name):
            report.skipped += 1
            continue
        activity = Activity(tenant_id=ctx.tenant_id, company_id=company_id, name=name, group_name=spec.get("group"),
                       billable=bool(spec.get("billable", True)), sort_order=int(spec.get("order", i)),
                       source=f"pack:{pack.name}")
        session.add(activity)
        session.flush()
        report.added.append(SeededItem("activity", activity.id, name))
    for spec in data.get("snippet", []):
        name, language = str(spec["name"]).strip(), str(spec.get("language", "en"))
        label = f"{name} ({language})"
        exists = session.scalar(select(Snippet.id).where(
            Snippet.company_id == company_id, Snippet.kind == spec.get("kind", "invoice_note"),
            Snippet.name == name, Snippet.language == language))
        if exists is not None or _was_seeded(session, pack.name, company_id, "snippet", label):
            report.skipped += 1
            continue
        snippet = Snippet(tenant_id=ctx.tenant_id, company_id=company_id, kind=spec.get("kind", "invoice_note"),
                      name=name, language=language, body=str(spec["body"]).strip()[:500],
                      source=f"pack:{pack.name}")
        session.add(snippet)
        session.flush()
        report.added.append(SeededItem("snippet", snippet.id, label))
    _intel(session, data.get("intel", {}), report)
    if data.get("sample"):
        session.execute(text(
            "insert into timebilling.sample_recipe (tenant_id, company_id, pack, recipe) "
            "values (kernel.current_tenant(), :c, :p, cast(:r as jsonb)) on conflict (company_id, pack) "
            "do update set recipe = excluded.recipe"),
            {"c": str(company_id), "p": pack.name, "r": json.dumps(data["sample"], default=str)})
    return report


def _start(today: date) -> date:
    """Example rates are in force from the start of the year, so they cover work already logged this year."""
    return date(today.year, 1, 1)


def _settings(session: Session, given: dict[str, Any], company_id: UUID, report: SeedReport) -> None:
    """Apply the pack's suggested settings while the business has not saved any of its own."""
    if not given:
        return
    row = common.settings(session, company_id)
    if row.updated_at is not None:
        report.skipped += 1
        return
    for key, value in given.items():
        if key in ("service_sku", "expense_sku"):
            _service_item(session, row, company_id, key, str(value), report)
            continue
        if key not in SETTING_FIELDS:
            report.notes.append(f"settings: '{key}' is not a time setting")
            continue
        setattr(row, key, Decimal(str(value)) if isinstance(value, float) else value)
    session.flush()
    report.notes.append("Time settings set to the pack's suggestions")


def _service_item(session: Session, row: Any, company_id: UUID, key: str, sku: str, report: SeedReport) -> None:
    """Point the settings at the pack's service item (found by SKU) when none is chosen. If the service items are not
    there yet (the products seeder runs after this one), the next `ziira apply-packs` finishes the job."""
    from ziira.modules.products.public import find_product_by_sku

    field = "service_product_id" if key == "service_sku" else "expense_product_id"
    if getattr(row, field) is not None:
        return
    found = find_product_by_sku(session, company_id, sku)
    if found is None:
        report.notes.append(f"settings: service item {sku} is not there yet")
        return
    setattr(row, field, found.id)


def _intel(session: Session, given: dict[str, Any], report: SeedReport) -> None:
    if not given or not access.unit_enabled(session, "intel"):
        return
    from ziira.modules.intel.public import apply_check_defaults

    done = apply_check_defaults(session, {code: dict(params) for code, params in given.items()})
    if done:
        report.notes.append(f"Intelligence limits suggested for: {', '.join(done)}")


def untouched(session: Session, item_type: str, item_id: UUID) -> bool:
    """A row the pack added that nobody changed (and nothing refers to): removing it loses nothing."""
    table = {"engagement_template": "engagement_template", "example_rate": "rate", "activity": "activity",
             "snippet": "snippet"}.get(item_type)
    if table is None:
        return False
    row = session.execute(text(f"select updated_at is null as fresh from timebilling.{table} where id = :i"),
                          {"i": str(item_id)}).first()
    if row is None or not row.fresh:
        return False
    if item_type == "example_rate":
        return session.execute(text("select example from timebilling.rate where id = :i"),
                               {"i": str(item_id)}).scalar() is True
    return True


def remove(session: Session, item_type: str, item_id: UUID) -> None:
    table = {"engagement_template": "engagement_template", "example_rate": "rate", "activity": "activity",
             "snippet": "snippet"}[item_type]
    session.execute(text(f"delete from timebilling.{table} where id = :i"), {"i": str(item_id)})

"""Use case: the plans, packages, policies, waiver and check limits an industry pack supplies (`data/memberships.toml`).

Everything is a starting point for the business to edit. Prices in a pack are **examples**: the plans carry
`is_example` until the owner changes the fee. Idempotent and non-destructive: a plan or package code the business
already
has is left alone (only a missing service item link is topped up), policies are written only when the company has
never saved any, and the waiver only when there is none."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import plans, settings, waivers
from ziira.sdk import (
    INDUSTRY_SEEDER,
    PackData,
    SeededItem,
    SeedReport,
    Session,
    audit_record,
    current_context,
    implementations,
)

PLAN_KEYS = ("kind", "valid_days", "is_trial", "term_periods", "notice_days", "early_exit_fee", "joining_fee",
             "freeze_max_days", "freeze_fee", "prorate", "access_rules", "gym_access", "classes_mode",
             "guest_passes_per_period", "description")


def _product_id(session: Session, company_id: UUID, sku: str | None) -> UUID | None:
    if not sku or not _unit_on(session, "products"):
        return None
    from ziira.modules.products.public import find_product_by_sku

    found = find_product_by_sku(session, company_id, sku.strip().upper())
    return found.id if found is not None else None


def _unit_on(session: Session, unit: str) -> bool:
    return session.execute(text("select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
                                "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


def seed(session: Session, pack: PackData, company_id: UUID) -> SeedReport:
    data = pack.unit_data("memberships")
    report = SeedReport()
    if not data:
        return report
    # The service items the plans are invoiced as come from the pack's products file; make sure they exist first
    # (seeders run in no fixed order). What that adds is reported here so switching the pack off can still remove it.
    for other in implementations(session, INDUSTRY_SEEDER):
        if other.unit == "products":
            report.added += other.seed(session, pack, company_id).added

    if data.get("settings") and repo.one(session, "select 1 as x from memberships.setting where company_id = :c",
                                         c=company_id) is None:
        wanted = {k: v for k, v in data["settings"].items() if k in settings.FIELDS}
        saved = settings.update_settings(session, company_id, **wanted)
        report.added.append(SeededItem("setting", saved["id"], "Membership policies"))
    waiver = data.get("waiver")
    if waiver and waivers.current_version(session, company_id) is None:
        made = waivers.publish_version(session, company_id=company_id, title=waiver["title"], body=waiver["body"])
        report.added.append(SeededItem("waiver_version", made["id"], waiver["title"]))

    for row in data.get("plan", []):
        code = str(row["code"]).strip().upper()
        found = repo.one(session, "select * from memberships.plan where company_id = :c and code = :k",
                         c=company_id, k=code)
        product = _product_id(session, company_id, row.get("service_sku"))
        joining = _product_id(session, company_id, row.get("joining_fee_sku"))
        if found is not None:
            top_up = {k: v for k, v in (("service_product_id", product), ("joining_fee_product_id", joining))
                      if v is not None and found[k] is None}
            if top_up:
                repo.update(session, "plan", found["id"], top_up)
            report.skipped += 1
            continue
        extra = {k: row[k] for k in PLAN_KEYS if k in row}
        made = plans.create_plan(
            session, company_id=company_id, code=code, name=row["name"], fee=Decimal(str(row["fee"])),
            billing_interval=row.get("billing_interval", "month"),
            credits_per_period=Decimal(str(row.get("credits_per_period", 0))),
            discount_percent=Decimal(str(row.get("discount_percent", 0))),
            covered_services=list(row.get("covered_services", [])), rollover=bool(row.get("rollover", False)),
            service_product_id=product, terms=row.get("terms"), joining_fee_product_id=joining, is_example=True,
            **extra)
        report.added.append(SeededItem("plan", made["id"], made["name"]))
        if row.get("service_sku") and product is None:
            report.notes.append(f"{code}: service item {row['service_sku']} not found yet; run apply-packs again")

    for row in data.get("package", []):
        code = str(row["code"]).strip().upper()
        found = repo.one(session, "select * from memberships.package where company_id = :c and code = :k",
                         c=company_id, k=code)
        product = _product_id(session, company_id, row.get("sku"))
        if found is not None:
            if product is not None and found["product_id"] is None:
                repo.update(session, "package", found["id"], {"product_id": product})
            report.skipped += 1
            continue
        made = plans.create_package(
            session, company_id=company_id, code=code, name=row["name"], credits=Decimal(str(row["credits"])),
            price=Decimal(str(row["price"])), expiry_days=row.get("expiry_days"),
            covered_services=list(row.get("covered_services", [])), product_id=product,
            description=row.get("description"), is_example=True)
        report.added.append(SeededItem("package", made["id"], made["name"]))

    limits = data.get("intel", {})
    if limits and _unit_on(session, "intel"):
        from ziira.modules.intel.public import apply_check_defaults

        done = apply_check_defaults(session, {code: dict(values) for code, values in limits.items()})
        if done:
            report.notes.append("check limits set: " + ", ".join(done))
    if report.added:
        audit_record(session, "seed", "memberships.plan", None, {"pack": pack.name,
                                                                  "items": [i.label for i in report.added][:20]})
    _ = current_context
    return report


def untouched(session: Session, item_type: str, item_id: UUID) -> bool:
    """Still as the pack made it and nothing refers to it."""
    if item_type == "plan":
        row = repo.get(session, "plan", item_id)
        return (row is not None and row["is_example"] and row["status"] == "active" and row["updated_at"] is None
                and repo.one(session, "select 1 as x from memberships.member where plan_id = :p limit 1",
                             p=item_id) is None)
    if item_type == "package":
        row = repo.get(session, "package", item_id)
        return (row is not None and row["is_example"] and row["status"] == "active" and row["updated_at"] is None
                and repo.one(session, "select 1 as x from memberships.sold_package where package_id = :p limit 1",
                             p=item_id) is None)
    if item_type == "product":
        for other in implementations(session, INDUSTRY_SEEDER):
            if other.unit == "products":
                return bool(other.untouched(session, item_type, item_id))
    return False


def remove(session: Session, item_type: str, item_id: UUID) -> None:
    if item_type in ("plan", "package"):
        repo.update(session, item_type, item_id, {"status": "retired"})
    elif item_type == "product":
        for other in implementations(session, INDUSTRY_SEEDER):
            if other.unit == "products":
                other.remove(session, item_type, item_id)

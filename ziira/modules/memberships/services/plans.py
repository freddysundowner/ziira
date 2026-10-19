"""Use cases: membership plans and session packages (the catalogue). Needs 'memberships.plans' to change."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.memberships.domain import rules
from ziira.modules.memberships.permissions import PLANS
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, check_company, current_context


def _catalogue(session: Session, table: str, company_id: UUID | None, status: str | None, limit: int,
               offset: int) -> list[repo.Row]:
    companies = common.visible_company_ids()
    return repo.many(
        session,
        f"select * from memberships.{table} where (cast(:c as uuid) is null or company_id = :c) "
        "and (cast(:cs as uuid[]) is null or company_id = any(cast(:cs as uuid[]))) "
        "and (cast(:s as text) is null or status = :s) order by status, name limit :l offset :o",
        c=company_id, cs=None if companies is None else [str(c) for c in companies], s=status, l=min(limit, 200),
        o=offset)


# --------------------------------------------------------------------------- plans
def list_plans(session: Session, *, company_id: UUID | None = None, status: str | None = None, limit: int = 100,
               offset: int = 0) -> list[repo.Row]:
    return with_prices(session, _catalogue(session, "plan", company_id, status, limit, offset))


def get_plan(session: Session, plan_id: UUID) -> repo.Row:
    return with_prices(session, [common.get_row(session, "plan", plan_id, "Plan")])[0]


EXTRA_FIELDS = ("kind", "valid_days", "is_trial", "term_periods", "notice_days", "early_exit_fee", "joining_fee",
                "joining_fee_product_id", "freeze_max_days", "freeze_fee", "prorate", "access_rules", "branch_ids",
                "gym_access", "classes_mode", "guest_passes_per_period", "description", "is_example")
CORE_FIELDS = ("name", "fee", "credits_per_period", "discount_percent", "covered_services", "rollover",
               "service_product_id", "terms", "status")
PLAN_FIELDS = CORE_FIELDS + EXTRA_FIELDS


def _clean_extra(session: Session, company_id: UUID, values: dict[str, object]) -> dict[str, object]:
    """Validate and tidy the gym/studio fields of a plan."""
    if "access_rules" in values:
        values["access_rules"] = rules.clean_access_rules(values["access_rules"])
    if "branch_ids" in values:
        ids = rules.clean_branch_ids(values["branch_ids"])
        for branch_id in ids:
            check_company(session, company_id, UUID(branch_id))
        values["branch_ids"] = ids
    if values.get("joining_fee_product_id"):
        common.check_product(session, company_id, values["joining_fee_product_id"])  # type: ignore[arg-type]
    if "description" in values:
        values["description"] = (str(values["description"] or "")).strip()[:1000] or None
    return values


def _check_kind(kind: str, valid_days: object, term_periods: object) -> None:
    if kind == "pass" and not valid_days:
        raise ValidationFailed("A pass says how many days it is valid")
    if kind == "fixed_term" and not term_periods:
        raise ValidationFailed("A fixed-term plan says how many periods the contract runs")


def create_plan(session: Session, *, company_id: UUID, code: str, name: str, fee: Decimal, billing_interval: str,
                credits_per_period: Decimal = Decimal(0), discount_percent: Decimal = Decimal(0),
                covered_services: list[str] | None = None, rollover: bool = False,
                service_product_id: UUID | None = None, terms: str | None = None, **extra: object) -> repo.Row:
    """Add a plan. `service_product_id` is the service item the fee is invoiced as. Needs 'memberships.plans'."""
    common.require(PLANS, company_id)
    check_company(session, company_id)
    cleaned = rules.clean_code(code)
    if repo.one(session, "select 1 as x from memberships.plan where company_id = :c and code = :k",
                c=company_id, k=cleaned) is not None:
        raise Conflict(f"There is already a plan with code {cleaned}")
    common.check_product(session, company_id, service_product_id)
    more = _clean_extra(session, company_id, {k: v for k, v in extra.items() if k in EXTRA_FIELDS and v is not None})
    _check_kind(str(more.get("kind", "recurring")), more.get("valid_days"), more.get("term_periods"))
    ctx = current_context()
    plan = repo.insert(session, "plan", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "code": cleaned,
        "name": rules.clean_name(name), "fee": fee, "billing_interval": billing_interval,
        "credits_per_period": credits_per_period, "discount_percent": discount_percent,
        "covered_services": rules.clean_services(covered_services), "rollover": rollover,
        "service_product_id": service_product_id, "terms": (terms or "").strip() or None, **more})
    audit_record(session, "create", "memberships.plan", plan["id"], {"code": cleaned, "fee": str(fee)})
    return with_prices(session, [plan])[0]


def update_plan(session: Session, plan_id: UUID, **changes: object) -> repo.Row:
    """Change a plan. Members already on it keep the price, credits and discount they started with (use a price change
    from a date to move them). Needs 'memberships.plans'."""
    plan = repo.get(session, "plan", plan_id, lock=True)
    if plan is None:
        raise NotFound("Plan not found")
    common.require(PLANS, plan["company_id"])
    values = {k: v for k, v in changes.items() if k in PLAN_FIELDS}
    if "name" in values:
        values["name"] = rules.clean_name(str(values["name"]))
    if "covered_services" in values:
        values["covered_services"] = rules.clean_services(values["covered_services"])  # type: ignore[arg-type]
    if "terms" in values:
        values["terms"] = (str(values["terms"] or "")).strip() or None
    if values.get("service_product_id"):
        common.check_product(session, plan["company_id"], values["service_product_id"])  # type: ignore[arg-type]
    values = _clean_extra(session, plan["company_id"], values)
    _check_kind(str(values.get("kind", plan["kind"])), values.get("valid_days", plan["valid_days"]),
                values.get("term_periods", plan["term_periods"]))
    if "fee" in values and values["fee"] != plan["fee"] and "is_example" not in values:
        values["is_example"] = False
    updated = repo.update(session, "plan", plan_id, {**values, "updated_by": current_context().user_id})
    audit_record(session, "update", "memberships.plan", plan_id, {k: str(v) for k, v in values.items()})
    return with_prices(session, [updated])[0]


# --------------------------------------------------------------------------- prices from a date
def fee_at(session: Session, plan: repo.Row, day: date) -> Decimal:
    """What a new member of the plan pays for a period starting on `day`: the latest scheduled price change on or before
    that day, else the plan's own fee."""
    found = repo.one(session, "select fee from memberships.plan_price_change where plan_id = :p "
                              "and status = 'scheduled' and effective_from <= :d order by effective_from desc limit 1",
                     p=plan["id"], d=day)
    return Decimal(found["fee"]) if found else Decimal(plan["fee"])


def with_prices(session: Session, plans: list[repo.Row]) -> list[repo.Row]:
    """Plans with the fee that applies today and the next price change that is scheduled."""
    out: list[repo.Row] = []
    for plan in plans:
        today = common.today(session, plan["company_id"])
        upcoming = repo.one(session, "select effective_from, fee, apply_to_existing from memberships.plan_price_change "
                                     "where plan_id = :p and status = 'scheduled' and effective_from > :d "
                                     "order by effective_from limit 1", p=plan["id"], d=today)
        out.append({**plan, "current_fee": fee_at(session, plan, today),
                    "next_fee": upcoming["fee"] if upcoming else None,
                    "next_fee_from": upcoming["effective_from"] if upcoming else None,
                    "next_fee_applies_to_existing": bool(upcoming["apply_to_existing"]) if upcoming else False})
    return out


def schedule_price_change(session: Session, plan_id: UUID, *, effective_from: date, fee: Decimal,
                          apply_to_existing: bool = False, note: str | None = None) -> repo.Row:
    """A new price from a date (today or later, never backwards). New members pay it from that date; existing members
    only
    when `apply_to_existing` is set, and at the first renewal on or after the date (members marked price-locked keep
    their price). Needs 'memberships.plans'."""
    plan = repo.get(session, "plan", plan_id, lock=True)
    if plan is None:
        raise NotFound("Plan not found")
    common.require(PLANS, plan["company_id"])
    today = common.today(session, plan["company_id"])
    if effective_from < today:
        raise ValidationFailed("A new price cannot start in the past: it never changes what was already invoiced")
    if fee < 0:
        raise ValidationFailed("The fee cannot be negative")
    ctx = current_context()
    existing = repo.one(session, "select id from memberships.plan_price_change where plan_id = :p "
                                 "and effective_from = :d", p=plan_id, d=effective_from)
    values = {"fee": fee, "apply_to_existing": apply_to_existing, "note": (note or "").strip()[:300] or None,
              "status": "scheduled"}
    if existing is not None:
        change = repo.update(session, "plan_price_change", existing["id"], values)
    else:
        change = repo.insert(session, "plan_price_change", {
            "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": plan["company_id"], "plan_id": plan_id,
            "effective_from": effective_from, **values})
    affected = repo.scalar(session, "select count(*) from memberships.member where plan_id = :p "
                                    "and status in ('active', 'paused', 'frozen') and not price_locked", p=plan_id)
    audit_record(session, "price_change", "memberships.plan", plan_id,
                 {"from": str(effective_from), "fee": str(fee), "existing": apply_to_existing})
    return {**change, "members_affected": int(affected) if apply_to_existing else 0}


def list_price_changes(session: Session, plan_id: UUID) -> list[repo.Row]:
    common.get_row(session, "plan", plan_id, "Plan")
    return repo.many(session, "select * from memberships.plan_price_change where plan_id = :p "
                              "order by effective_from desc", p=plan_id)


def cancel_price_change(session: Session, change_id: UUID) -> repo.Row:
    change = repo.get(session, "plan_price_change", change_id, lock=True)
    if change is None:
        raise NotFound("Price change not found")
    common.check_visible(change["company_id"], None, "Price change")
    common.require(PLANS, change["company_id"])
    if change["status"] != "scheduled":
        raise Conflict("This price change is already cancelled")
    if change["effective_from"] <= common.today(session, change["company_id"]):
        raise Conflict("This price change has already started; schedule a new one instead")
    saved = repo.update(session, "plan_price_change", change_id, {"status": "cancelled"})
    audit_record(session, "cancel", "memberships.plan_price_change", change_id, {})
    return saved


# --------------------------------------------------------------------------- packages
def list_packages(session: Session, *, company_id: UUID | None = None, status: str | None = None, limit: int = 100,
                  offset: int = 0) -> list[repo.Row]:
    return _catalogue(session, "package", company_id, status, limit, offset)


def get_package(session: Session, package_id: UUID) -> repo.Row:
    return common.get_row(session, "package", package_id, "Package")


def create_package(session: Session, *, company_id: UUID, code: str, name: str, credits: Decimal, price: Decimal,
                   expiry_days: int | None = None, covered_services: list[str] | None = None,
                   product_id: UUID | None = None, terms: str | None = None, description: str | None = None,
                   is_example: bool = False) -> repo.Row:
    """Add a package that can be sold ('10 massages', 'Term 1 lessons'). Needs 'memberships.plans'."""
    common.require(PLANS, company_id)
    check_company(session, company_id)
    cleaned = rules.clean_code(code)
    if repo.one(session, "select 1 as x from memberships.package where company_id = :c and code = :k",
                c=company_id, k=cleaned) is not None:
        raise Conflict(f"There is already a package with code {cleaned}")
    common.check_product(session, company_id, product_id)
    ctx = current_context()
    package = repo.insert(session, "package", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "code": cleaned,
        "name": rules.clean_name(name), "credits": credits, "price": price, "expiry_days": expiry_days,
        "covered_services": rules.clean_services(covered_services), "product_id": product_id,
        "terms": (terms or "").strip() or None, "description": (description or "").strip()[:1000] or None,
        "is_example": is_example})
    audit_record(session, "create", "memberships.package", package["id"], {"code": cleaned, "price": str(price)})
    return package


PACKAGE_FIELDS = ("name", "credits", "price", "expiry_days", "covered_services", "product_id", "terms", "status",
                  "description", "is_example")


def update_package(session: Session, package_id: UUID, **changes: object) -> repo.Row:
    """Change a package. Packages already sold keep what they were sold with. Needs 'memberships.plans'."""
    package = repo.get(session, "package", package_id, lock=True)
    if package is None:
        raise NotFound("Package not found")
    common.require(PLANS, package["company_id"])
    values = {k: v for k, v in changes.items() if k in PACKAGE_FIELDS}
    if "name" in values:
        values["name"] = rules.clean_name(str(values["name"]))
    if "covered_services" in values:
        values["covered_services"] = rules.clean_services(values["covered_services"])  # type: ignore[arg-type]
    if "terms" in values:
        values["terms"] = (str(values["terms"] or "")).strip() or None
    if values.get("product_id"):
        common.check_product(session, package["company_id"], values["product_id"])  # type: ignore[arg-type]
    if "description" in values:
        values["description"] = (str(values["description"] or "")).strip()[:1000] or None
    if "price" in values and values["price"] != package["price"] and "is_example" not in values:
        values["is_example"] = False
    updated = repo.update(session, "package", package_id, {**values, "updated_by": current_context().user_id})
    audit_record(session, "update", "memberships.package", package_id, {k: str(v) for k, v in values.items()})
    return updated

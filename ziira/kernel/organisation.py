"""The business's own structure after registration: companies and branches.

Adding a company, editing it, adding a branch, editing or closing one, and a list with what each branch holds.
Permission `organisation.manage` (the Owner holds it): tenant-wide to add a company, or for the company itself to edit
it and manage its branches.

Units tell the kernel what they hold at a branch through the "kernel.branch_usage" socket (`BranchUsageProvider`):
how many devices or locations a branch has, what stops it being closed (an open till, stock in transit, documents not
yet posted), and what stops a company's currency being changed (it already has postings). The kernel never reads
another unit's tables. A company's books and price lists are created the first time they are needed, so a new company
needs no set-up call into the units.
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, company_settings
from ziira.kernel.context import RequestContext, get_context
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.extensions import define_extension_point, implementations
from ziira.kernel.platform import entitlements

PERMISSION = "organisation.manage"
BRANCH_USAGE = "kernel.branch_usage"
BRANCH_CODE = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,9}")


class BranchUsageProvider(ABC):
    """Contract of the "kernel.branch_usage" extension point: what a unit holds at a branch or a company."""

    name = ""

    @abstractmethod
    def branch_blockers(self, session: Session, branch_id: UUID) -> list[str]:
        """Plain-language reasons the branch cannot be closed now (an open till, stock in transit...); none if free."""

    def branch_counts(self, session: Session, branch_ids: list[UUID]) -> dict[str, dict[UUID, int]]:
        """Counts to show beside each branch, for example {"devices": {branch_id: 2}}. Default: none."""
        return {}

    def currency_locks(self, session: Session, company_id: UUID) -> list[str]:
        """Plain-language reasons the company's currency can no longer change (it has postings). Default: none."""
        return []


define_extension_point(BRANCH_USAGE, BranchUsageProvider,
                       "What a unit holds at a branch: counts to show, reasons it cannot be closed, "
                       "and reasons a company's currency is fixed.")


def _providers(session: Session) -> list[BranchUsageProvider]:
    return list(implementations(session, BRANCH_USAGE))


def _clean(value: str | None, what: str, *, required: bool = False, limit: int = 200) -> str | None:
    text_ = (value or "").strip()
    if not text_:
        if required:
            raise ValidationFailed(f"{what} is required")
        return None
    if len(text_) > limit:
        raise ValidationFailed(f"{what} is too long (at most {limit} characters)")
    return text_


def _currency(value: str) -> str:
    code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValidationFailed("Currency is a three-letter code such as USD")
    return code


def _country(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", code):
        raise ValidationFailed("Country is a two-letter code such as GB")
    return code


def _branch_code(value: str) -> str:
    code = value.strip().upper()
    if not BRANCH_CODE.fullmatch(code):
        raise ValidationFailed("A branch code is 1 to 10 letters, digits, '-' or '_' (used in document numbers)")
    return code


def _user_id(ctx: RequestContext) -> str | None:
    return str(ctx.user_id) if ctx.user_id else None


# --------------------------------------------------------------------------- reading
def list_organisation(session: Session, ctx: RequestContext) -> list[dict[str, Any]]:
    """The companies the user manages, each with all its branches (closed ones too) and what each branch holds."""
    reach = ctx.companies_with(PERMISSION)
    companies = session.execute(text(
        "select id, name, tax_id, vat_registered, base_currency, country, settings from kernel.company "
        "order by name")).all()
    branches = session.execute(text(
        "select id, company_id, code, name, address, phone, is_active from kernel.branch order by code")).all()
    branch_ids = [b.id for b in branches]
    users = {r.branch_id: r.n for r in session.execute(text(
        "select branch_id, count(distinct user_id) as n from kernel.user_role where branch_id is not null "
        "group by branch_id"))}
    counts: dict[str, dict[UUID, int]] = {}
    for provider in _providers(session):
        for key, per_branch in provider.branch_counts(session, branch_ids).items():
            counts.setdefault(key, {}).update(per_branch)
    out = []
    for c in companies:
        if reach is not None and c.id not in reach:
            continue
        settings = company_settings.get_settings(session, c.id)
        mine = [b for b in branches if b.company_id == c.id]
        out.append({
            "id": c.id, "name": c.name, "tax_id": c.tax_id, "vat_registered": c.vat_registered,
            "currency": c.base_currency, "country": c.country, "timezone": settings["timezone"],
            "currency_locked": bool(_currency_locks(session, c.id)),
            "branches": [{
                "id": b.id, "code": b.code, "name": b.name, "address": b.address, "phone": b.phone,
                "is_active": b.is_active,
                "counts": {"users": users.get(b.id, 0),
                           **{key: per_branch.get(b.id, 0) for key, per_branch in sorted(counts.items())}},
            } for b in mine]})
    return out


def _currency_locks(session: Session, company_id: UUID) -> list[str]:
    return [reason for provider in _providers(session) for reason in provider.currency_locks(session, company_id)]


def _company_row(session: Session, company_id: UUID) -> Any:
    row = session.execute(text("select id, name, tax_id, vat_registered, base_currency, country from kernel.company "
                               "where id = :i"), {"i": str(company_id)}).first()
    if row is None:
        raise NotFound("Company not found")
    return row


def _branch_row(session: Session, branch_id: UUID) -> Any:
    row = session.execute(text("select id, company_id, code, name, address, phone, is_active from kernel.branch "
                               "where id = :i"), {"i": str(branch_id)}).first()
    if row is None:
        raise NotFound("Branch not found")
    return row


def one_company(session: Session, ctx: RequestContext, company_id: UUID) -> dict[str, Any]:
    for company in list_organisation(session, ctx):
        if company["id"] == company_id:
            return company
    raise NotFound("Company not found")


# --------------------------------------------------------------------------- companies
def create_company(session: Session, *, name: str, currency: str, country: str | None, tax_id: str | None,
                   timezone: str | None, vat_registered: bool, branch_code: str | None,
                   branch_name: str | None) -> UUID:
    """Add a company to the business, with a first branch if one is named. Tenant-wide permission."""
    get_context().require(PERMISSION)
    entitlements.check_limit(session, get_context().tenant_id, "companies")
    clean_name = _clean(name, "Company name", required=True)
    if (branch_code is None) != (branch_name is None):
        raise ValidationFailed("Give both the first branch's code and name, or neither")
    zone = str(company_settings.SETTINGS["timezone"].parse(timezone)) if timezone and timezone.strip() else None
    if session.execute(text("select 1 from kernel.company where lower(name) = lower(:n)"),
                       {"n": clean_name}).first():
        raise Conflict(f"There is already a company called '{clean_name}'")
    # The calling code is the business's habit: a new company starts with the same one (it can be changed in settings).
    calling = session.execute(text(
        "select settings ->> 'phone_country_code' from kernel.company where settings ? 'phone_country_code' "
        "order by created_at limit 1")).scalar()
    settings: dict[str, str] = {}
    if calling:
        settings["phone_country_code"] = calling
    if zone:
        settings["timezone"] = zone
    company_id = uuid4()
    session.execute(text(
        "insert into kernel.company (id, tenant_id, name, tax_id, vat_registered, base_currency, country, settings, "
        "created_by) values (:i, kernel.current_tenant(), :n, :t, :v, :c, :k, cast(:s as jsonb), :u)"),
        {"i": str(company_id), "n": clean_name, "t": _clean(tax_id, "Tax number", limit=60), "v": vat_registered,
         "c": _currency(currency), "k": _country(country), "s": json.dumps(settings),
         "u": _user_id(get_context())})
    audit.record(session, "create", "kernel.company", company_id,
                 {"name": clean_name, "currency": _currency(currency), "country": _country(country)})
    if branch_code is not None and branch_name is not None:
        create_branch(session, company_id, code=branch_code, name=branch_name, address=None, phone=None)
    return company_id


def update_company(session: Session, company_id: UUID, changes: dict[str, Any]) -> None:
    """Change a company's name, tax number, tax-registered flag, country, time zone or currency (not once it has
    postings). Only the fields given are changed."""
    get_context().require(PERMISSION, company_id=company_id)
    before = _company_row(session, company_id)
    sets: dict[str, Any] = {}
    changed: dict[str, Any] = {}
    if "name" in changes:
        new_name = _clean(changes["name"], "Company name", required=True)
        if new_name != before.name:
            if session.execute(text("select 1 from kernel.company where lower(name) = lower(:n) and id <> :i"),
                               {"n": new_name, "i": str(company_id)}).first():
                raise Conflict(f"There is already a company called '{new_name}'")
            sets["name"], changed["name"] = new_name, {"from": before.name, "to": new_name}
    if "tax_id" in changes:
        new_tax = _clean(changes["tax_id"], "Tax number", limit=60)
        if new_tax != before.tax_id:
            sets["tax_id"], changed["tax_id"] = new_tax, {"from": before.tax_id, "to": new_tax}
    if "vat_registered" in changes and changes["vat_registered"] != before.vat_registered:
        sets["vat_registered"] = bool(changes["vat_registered"])
        changed["vat_registered"] = {"from": before.vat_registered, "to": sets["vat_registered"]}
    if "country" in changes:
        new_country = _country(changes["country"])
        if new_country != before.country:
            sets["country"], changed["country"] = new_country, {"from": before.country, "to": new_country}
    if "currency" in changes:
        new_currency = _currency(changes["currency"])
        if new_currency != before.base_currency:
            reasons = _currency_locks(session, company_id)
            if reasons:
                raise Conflict("The currency cannot be changed because this company already has " + "; ".join(reasons)
                               + ". Its figures would no longer add up. Add a new company in the other currency "
                                 "instead.")
            sets["base_currency"] = new_currency
            changed["currency"] = {"from": before.base_currency, "to": new_currency}
    if sets:
        columns = ", ".join(f"{column} = :{column}" for column in sets)
        session.execute(text(f"update kernel.company set {columns}, updated_at = now(), updated_by = :u "  # noqa: S608
                             "where id = :i"), {**sets, "u": _user_id(get_context()), "i": str(company_id)})
    if "timezone" in changes and changes["timezone"] is not None:
        zone = company_settings.SETTINGS["timezone"].parse(changes["timezone"])
        if zone != company_settings.get_settings(session, company_id)["timezone"]:
            company_settings.update_settings(session, company_id, {"timezone": zone})
    if changed:
        audit.record(session, "update", "kernel.company", company_id, changed)


# --------------------------------------------------------------------------- branches
def create_branch(session: Session, company_id: UUID, *, code: str, name: str, address: str | None,
                  phone: str | None) -> UUID:
    """Add a branch to a company."""
    get_context().require(PERMISSION, company_id=company_id)
    entitlements.check_limit(session, get_context().tenant_id, "branches")
    _company_row(session, company_id)
    clean_code = _branch_code(code)
    clean_name = _clean(name, "Branch name", required=True)
    if session.execute(text("select 1 from kernel.branch where company_id = :c and code = :k"),
                       {"c": str(company_id), "k": clean_code}).first():
        raise Conflict(f"This company already has a branch with the code '{clean_code}'")
    branch_id = uuid4()
    session.execute(text(
        "insert into kernel.branch (id, tenant_id, company_id, code, name, address, phone, created_by) "
        "values (:i, kernel.current_tenant(), :c, :k, :n, :a, :p, :u)"),
        {"i": str(branch_id), "c": str(company_id), "k": clean_code, "n": clean_name,
         "a": _clean(address, "Address", limit=300), "p": _clean(phone, "Phone", limit=40),
         "u": _user_id(get_context())})
    audit.record(session, "create", "kernel.branch", branch_id,
                 {"company_id": str(company_id), "code": clean_code, "name": clean_name})
    return branch_id


def update_branch(session: Session, branch_id: UUID, changes: dict[str, Any]) -> None:
    """Change a branch's name, code, address or phone. A new code applies to documents numbered from now on."""
    before = _branch_row(session, branch_id)
    get_context().require(PERMISSION, company_id=before.company_id)
    sets: dict[str, Any] = {}
    changed: dict[str, Any] = {}
    if "code" in changes:
        new_code = _branch_code(changes["code"])
        if new_code != before.code:
            if session.execute(text("select 1 from kernel.branch where company_id = :c and code = :k"),
                               {"c": str(before.company_id), "k": new_code}).first():
                raise Conflict(f"This company already has a branch with the code '{new_code}'")
            sets["code"], changed["code"] = new_code, {"from": before.code, "to": new_code}
    if "name" in changes:
        new_name = _clean(changes["name"], "Branch name", required=True)
        if new_name != before.name:
            sets["name"], changed["name"] = new_name, {"from": before.name, "to": new_name}
    for field, label, limit in (("address", "Address", 300), ("phone", "Phone", 40)):
        if field in changes:
            value = _clean(changes[field], label, limit=limit)
            if value != getattr(before, field):
                sets[field], changed[field] = value, {"from": getattr(before, field), "to": value}
    if sets:
        columns = ", ".join(f"{column} = :{column}" for column in sets)
        session.execute(text(f"update kernel.branch set {columns}, updated_at = now(), updated_by = :u "  # noqa: S608
                             "where id = :i"), {**sets, "u": _user_id(get_context()), "i": str(branch_id)})
        audit.record(session, "update", "kernel.branch", branch_id, changed)


def deactivate_branch(session: Session, branch_id: UUID) -> None:
    """Close a branch: it no longer appears in pickers; its history stays. Refused, with the reasons, while it has an
    open till, stock in transit or documents not yet posted, and for a company's last open branch."""
    before = _branch_row(session, branch_id)
    get_context().require(PERMISSION, company_id=before.company_id)
    if not before.is_active:
        return
    others = session.execute(text(
        "select count(*) from kernel.branch where company_id = :c and is_active and id <> :i"),
        {"c": str(before.company_id), "i": str(branch_id)}).scalar_one()
    if not others:
        raise Conflict("This is the company's only open branch; a company needs at least one. Add another branch "
                       "first.")
    reasons = [reason for provider in _providers(session) for reason in provider.branch_blockers(session, branch_id)]
    if reasons:
        raise Conflict(f"Branch {before.code} cannot be closed yet: " + "; ".join(reasons) + ".")
    session.execute(text("update kernel.branch set is_active = false, updated_at = now(), updated_by = :u "
                         "where id = :i"), {"u": _user_id(get_context()), "i": str(branch_id)})
    audit.record(session, "deactivate", "kernel.branch", branch_id, {"code": before.code})


def reactivate_branch(session: Session, branch_id: UUID) -> None:
    """Open a closed branch again."""
    before = _branch_row(session, branch_id)
    get_context().require(PERMISSION, company_id=before.company_id)
    if before.is_active:
        return
    entitlements.check_limit(session, get_context().tenant_id, "branches")
    session.execute(text("update kernel.branch set is_active = true, updated_at = now(), updated_by = :u "
                         "where id = :i"), {"u": _user_id(get_context()), "i": str(branch_id)})
    audit.record(session, "reactivate", "kernel.branch", branch_id, {"code": before.code})

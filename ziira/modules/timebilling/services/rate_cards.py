"""Use cases: rate cards, and pricing an entry from them (the rules are in domain/rates.py)."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ziira.modules.timebilling.domain import rates as rules
from ziira.modules.timebilling.permissions import COST_VIEW, RATES_MANAGE
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Entry, Project, Rate, Staff
from ziira.modules.timebilling.services import access
from ziira.sdk import Forbidden, NotFound, Session, ValidationFailed, audit_record, check_company, current_context


def _row(r: Rate) -> rules.RateRow:
    return rules.RateRow(r.id, r.kind, r.rate, r.effective_from, r.effective_to, r.project_id, r.client_id, r.user_id,
                         r.service_product_id, r.role_title, r.seq)


def can_see_cost(company_id: UUID) -> bool:
    ctx = current_context()
    return ctx.can(COST_VIEW, company_id=company_id) or ctx.can(RATES_MANAGE, company_id=company_id)


def create_rate(session: Session, *, company_id: UUID, kind: str, rate: Decimal, effective_from: date,
                effective_to: date | None = None, project_id: UUID | None = None, client_id: UUID | None = None,
                user_id: UUID | None = None, service_product_id: UUID | None = None, role_title: str | None = None,
                note: str | None = None) -> Rate:
    """Add a row to the rate card. A row names the work it covers (any of project, client, person, service, role); one
    that names nothing covers everything. Needs 'rates.manage'."""
    ctx = current_context()
    ctx.require(RATES_MANAGE, company_id=company_id)
    check_company(session, company_id)
    if kind not in ("bill", "cost"):
        raise ValidationFailed("A rate is what you bill (bill) or what an hour costs you (cost)")
    if rate < 0:
        raise ValidationFailed("A rate cannot be negative")
    if effective_to is not None and effective_to < effective_from:
        raise ValidationFailed("A rate cannot end before it starts")
    if project_id is not None:
        project = repo.get(session, Project, project_id)
        if project is None or project.company_id != company_id:
            raise ValidationFailed("Project not found in this company")
    role = (role_title or "").strip() or None
    row = Rate(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, kind=kind, project_id=project_id,
               client_id=client_id, user_id=user_id, service_product_id=service_product_id, role_title=role,
               rate=rate, effective_from=effective_from, effective_to=effective_to,
               note=(note or "").strip()[:500] or None)
    repo.add(session, row)
    audit_record(session, "create", "timebilling.rate", row.id, {"kind": kind, "rate": rate})
    return row


def list_rates(session: Session, company_id: UUID, *, kind: str | None = None) -> list[Rate]:
    """The rate card. Cost rates are shown only to people who may see costs."""
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    q = select(Rate).where(Rate.company_id == company_id)
    if kind:
        q = q.where(Rate.kind == kind)
    if not can_see_cost(company_id):
        q = q.where(Rate.kind == "bill")
    return list(session.scalars(q.order_by(Rate.kind, Rate.effective_from.desc(), Rate.seq.desc())))


def update_rate(session: Session, rate_id: UUID, **changes: Any) -> Rate:
    """Change a row's rate, end date or note (what it covers is fixed: add a new row instead). Needs 'rates.manage'.
    Time already approved keeps the rate it was approved at. `example=False` confirms an example row from a pack, which
    prices nothing until then."""
    row = repo.get(session, Rate, rate_id, lock=True)
    if row is None:
        raise NotFound("Rate not found")
    current_context().require(RATES_MANAGE, company_id=row.company_id)
    done: dict[str, object] = {}
    if changes.get("example") is True:
        raise ValidationFailed("An example rate can be made real, not the other way round")
    for key in ("rate", "effective_to", "note", "example"):
        if key not in changes or (changes[key] is None and key not in ("effective_to", "note")):
            continue
        if getattr(row, key) != changes[key]:
            done[key] = changes[key]
            setattr(row, key, changes[key])
    if row.effective_to is not None and row.effective_to < row.effective_from:
        raise ValidationFailed("A rate cannot end before it starts")
    if row.rate < 0:
        raise ValidationFailed("A rate cannot be negative")
    row.updated_by = current_context().user_id
    session.flush()
    if done:
        audit_record(session, "update", "timebilling.rate", row.id, done)
    return row


def delete_rate(session: Session, rate_id: UUID) -> None:
    row = repo.get(session, Rate, rate_id, lock=True)
    if row is None:
        raise NotFound("Rate not found")
    current_context().require(RATES_MANAGE, company_id=row.company_id)
    session.delete(row)
    session.flush()
    audit_record(session, "delete", "timebilling.rate", rate_id, {"kind": row.kind, "rate": row.rate})


class Pricer:
    """Prices entries of one company from its rate card (loaded once; the cost rows only if asked for)."""

    def __init__(self, session: Session, company_id: UUID) -> None:
        self.company_id = company_id
        self.rows = [_row(r) for r in session.scalars(select(Rate).where(
            Rate.company_id == company_id, Rate.example.is_(False)))]
        self.titles = {s.user_id: s.title for s in session.scalars(select(Staff).where(Staff.company_id == company_id))}
        self.clients: dict[UUID, UUID] = {}
        self.session = session

    def _client(self, project_id: UUID) -> UUID | None:
        if project_id not in self.clients:
            project = self.session.get(Project, project_id)
            if project is None:
                return None
            self.clients[project_id] = project.client_id
        return self.clients[project_id]

    def work(self, entry: Entry) -> rules.WorkContext:
        return rules.WorkContext(entry.work_date, entry.project_id, self._client(entry.project_id), entry.user_id,
                                 entry.service_product_id, self.titles.get(entry.user_id))

    def bill_rate(self, entry: Entry) -> Decimal | None:
        """The hourly rate to bill for the entry: an override on the entry, else the rate card."""
        if entry.rate_override is not None:
            return entry.rate_override
        found = rules.resolve(self.rows, self.work(entry), "bill")
        return found.rate if found else None

    def cost_rate(self, entry: Entry) -> Decimal | None:
        found = rules.resolve(self.rows, self.work(entry), "cost")
        return found.rate if found else None


def explain(session: Session, *, company_id: UUID, day: date, project_id: UUID | None, user_id: UUID | None,
            service_product_id: UUID | None, kind: str = "bill") -> Rate | None:
    """Which row of the card would price this work (for the 'what rate will this get?' check on the rate card page)."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    if kind == "cost" and not can_see_cost(company_id):
        raise Forbidden("You may not see cost rates")
    pricer = Pricer(session, company_id)
    client = pricer._client(project_id) if project_id else None
    title = pricer.titles.get(user_id) if user_id else None
    found = rules.resolve(pricer.rows, rules.WorkContext(day, project_id, client, user_id, service_product_id, title),
                          kind)
    return session.get(Rate, found.id) if found else None

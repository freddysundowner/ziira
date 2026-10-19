"""Database access for the claims schema. Row-level security scopes every query to the tenant."""

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Text, and_, cast, false, func, or_, select, true
from sqlalchemy.orm import Session

from ziira.modules.claims.repository.models import (
    Claim,
    ClaimEvent,
    ClaimSetting,
    Estimate,
    EstimateLine,
    EstimateLink,
    EstimateResponse,
    InvoiceLine,
    InvoiceRun,
    LineResponse,
    LinkAccess,
    Payer,
    PayerReceipt,
    ReceiptAllocation,
    ShortPay,
    WorkDecision,
)
from ziira.sdk import like_pattern

Scopes = list[tuple[UUID | None, UUID | None]] | None


def in_scope(scopes: Scopes, company_col: Any, branch_col: Any) -> ColumnElement[bool]:
    """Rows of the companies and branches the user may see (None means everywhere)."""
    if scopes is None:
        return true()
    return or_(false(), *(and_(company_col == c, true() if b is None else branch_col == b) for c, b in scopes))


def add(session: Session, record: Any) -> None:
    session.add(record)
    session.flush()
    session.refresh(record)


def get[T](session: Session, model: type[T], record_id: UUID, *, lock: bool = False) -> T | None:
    if lock:
        return session.scalars(select(model).where(model.id == record_id)  # type: ignore[attr-defined]
                               .with_for_update().execution_options(populate_existing=True)).first()
    return session.get(model, record_id)


def get_setting(session: Session, company_id: UUID) -> ClaimSetting | None:
    return session.scalar(select(ClaimSetting).where(ClaimSetting.company_id == company_id))


# --------------------------------------------------------------------------- payers
def payers(session: Session, companies: set[UUID] | None, *, only_active: bool = False,
           company_id: UUID | None = None) -> list[Payer]:
    query = select(Payer)
    if company_id is not None:
        query = query.where(Payer.company_id == company_id)
    if companies is not None:
        query = query.where(Payer.company_id.in_(companies))
    if only_active:
        query = query.where(Payer.is_active)
    return list(session.scalars(query.order_by(Payer.name)))


def payer_by_name(session: Session, company_id: UUID, name: str) -> Payer | None:
    return session.scalar(select(Payer).where(Payer.company_id == company_id, func.lower(Payer.name) == name.lower()))


def payers_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, Payer]:
    if not ids:
        return {}
    return {p.id: p for p in session.scalars(select(Payer).where(Payer.id.in_(ids)))}


# --------------------------------------------------------------------------- claims
def list_claims(session: Session, scopes: Scopes, *, company_id: UUID | None, branch_id: UUID | None,
                payer_id: UUID | None, status: str | None, open_only: bool, source_type: str | None,
                source_id: UUID | None, customer_id: UUID | None, search: str | None, limit: int,
                offset: int) -> list[Claim]:
    query = select(Claim).where(in_scope(scopes, Claim.company_id, Claim.branch_id))
    if company_id:
        query = query.where(Claim.company_id == company_id)
    if branch_id:
        query = query.where(Claim.branch_id == branch_id)
    if payer_id:
        query = query.where(Claim.payer_id == payer_id)
    if status:
        query = query.where(Claim.status == status)
    if open_only:
        query = query.where(Claim.status.notin_(("settled", "closed")))
    if source_type and source_id:
        query = query.where(Claim.source_type == source_type, Claim.source_id == source_id)
    if customer_id:
        query = query.where(Claim.customer_id == customer_id)
    if search and search.strip():
        like = like_pattern(search.strip())
        query = query.where(or_(Claim.number.ilike(like), Claim.policy_number.ilike(like),
                                Claim.claim_number.ilike(like), Claim.insured_name.ilike(like),
                                Claim.subject.ilike(like), Claim.source_number.ilike(like),
                                cast(Claim.member_number, Text).ilike(like)))
    return list(session.scalars(query.order_by(Claim.created_at.desc()).limit(limit).offset(offset)))


def live_claim_for_source(session: Session, company_id: UUID, source_type: str, source_id: UUID) -> Claim | None:
    return session.scalar(select(Claim).where(Claim.company_id == company_id, Claim.source_type == source_type,
                                              Claim.source_id == source_id, Claim.status != "closed"))


def claims_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, Claim]:
    if not ids:
        return {}
    return {c.id: c for c in session.scalars(select(Claim).where(Claim.id.in_(ids)))}


# --------------------------------------------------------------------------- estimates
def estimates(session: Session, claim_id: UUID) -> list[Estimate]:
    return list(session.scalars(select(Estimate).where(Estimate.claim_id == claim_id).order_by(Estimate.seq)))


def estimate_lines(session: Session, estimate_id: UUID) -> list[EstimateLine]:
    return list(session.scalars(select(EstimateLine).where(EstimateLine.estimate_id == estimate_id)
                                .order_by(EstimateLine.position)))


def claim_lines(session: Session, claim_id: UUID) -> list[EstimateLine]:
    return list(session.scalars(select(EstimateLine).where(EstimateLine.claim_id == claim_id)
                                .order_by(EstimateLine.created_at, EstimateLine.position)))


def line_responses(session: Session, claim_id: UUID) -> list[LineResponse]:
    return list(session.scalars(select(LineResponse).where(LineResponse.claim_id == claim_id)
                                .order_by(LineResponse.created_at, LineResponse.round)))


def estimate_responses(session: Session, claim_id: UUID) -> list[EstimateResponse]:
    return list(session.scalars(select(EstimateResponse).where(EstimateResponse.claim_id == claim_id)
                                .order_by(EstimateResponse.created_at)))


def rounds_so_far(session: Session, estimate_id: UUID) -> int:
    return int(session.scalar(select(func.coalesce(func.max(EstimateResponse.round), 0))
                              .where(EstimateResponse.estimate_id == estimate_id)) or 0)


def events(session: Session, claim_id: UUID) -> list[ClaimEvent]:
    return list(session.scalars(select(ClaimEvent).where(ClaimEvent.claim_id == claim_id)
                                .order_by(ClaimEvent.created_at, ClaimEvent.id)))


# --------------------------------------------------------------------------- links
def link_by_hash(session: Session, token_hash: str) -> EstimateLink | None:
    return session.scalar(select(EstimateLink).where(EstimateLink.token_hash == token_hash))


def links_of_estimate(session: Session, estimate_id: UUID) -> list[EstimateLink]:
    return list(session.scalars(select(EstimateLink).where(EstimateLink.estimate_id == estimate_id)
                                .order_by(EstimateLink.created_at.desc())))


def link_accesses(session: Session, link_id: UUID, limit: int = 100) -> list[LinkAccess]:
    return list(session.scalars(select(LinkAccess).where(LinkAccess.link_id == link_id)
                                .order_by(LinkAccess.created_at.desc()).limit(limit)))


def work_decisions(session: Session, claim_id: UUID) -> list[WorkDecision]:
    return list(session.scalars(select(WorkDecision).where(WorkDecision.claim_id == claim_id)
                                .order_by(WorkDecision.created_at)))


# --------------------------------------------------------------------------- money
def runs(session: Session, claim_id: UUID) -> list[InvoiceRun]:
    return list(session.scalars(select(InvoiceRun).where(InvoiceRun.claim_id == claim_id).order_by(InvoiceRun.seq)))


def run_lines(session: Session, run_id: UUID) -> list[InvoiceLine]:
    return list(session.scalars(select(InvoiceLine).where(InvoiceLine.run_id == run_id)
                                .order_by(InvoiceLine.created_at, InvoiceLine.id)))


def claim_invoice_lines(session: Session, claim_id: UUID) -> list[InvoiceLine]:
    return list(session.scalars(select(InvoiceLine).where(InvoiceLine.claim_id == claim_id)))


def payer_runs(session: Session, payer_id: UUID) -> list[tuple[InvoiceRun, Claim]]:
    rows = session.execute(select(InvoiceRun, Claim).join(Claim, Claim.id == InvoiceRun.claim_id)
                           .where(Claim.payer_id == payer_id, InvoiceRun.payer_invoice_id.is_not(None))
                           .order_by(InvoiceRun.created_at)).all()
    return [(r, c) for r, c in rows]


def receipts_of_payer(session: Session, payer_id: UUID, limit: int = 50) -> list[PayerReceipt]:
    return list(session.scalars(select(PayerReceipt).where(PayerReceipt.payer_id == payer_id)
                                .order_by(PayerReceipt.created_at.desc()).limit(limit)))


def receipt_by_reference(session: Session, payer_id: UUID, reference: str) -> PayerReceipt | None:
    return session.scalar(select(PayerReceipt).where(PayerReceipt.payer_id == payer_id,
                                                     PayerReceipt.reference == reference))


def allocations_of_claim(session: Session, claim_id: UUID) -> list[ReceiptAllocation]:
    return list(session.scalars(select(ReceiptAllocation).where(ReceiptAllocation.claim_id == claim_id)
                                .order_by(ReceiptAllocation.created_at)))


def short_pays(session: Session, scopes_companies: set[UUID] | None, *, status: str | None = None,
               claim_id: UUID | None = None, payer_id: UUID | None = None) -> list[ShortPay]:
    query = select(ShortPay)
    if scopes_companies is not None:
        query = query.where(ShortPay.company_id.in_(scopes_companies))
    if status:
        query = query.where(ShortPay.status == status)
    if claim_id:
        query = query.where(ShortPay.claim_id == claim_id)
    if payer_id:
        query = query.where(ShortPay.payer_id == payer_id)
    return list(session.scalars(query.order_by(ShortPay.created_at.desc())))

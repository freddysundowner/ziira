"""Public interface of the Claims module (third-party payers: insurers, schemes, fleet owners, employers).

Jobs, Bookings and the clinic and garage packs use these; none of them reads Claims' tables. Nothing here checks who is
asking: the caller has already decided that the person may see the job or appointment. Money is `Decimal`.

* `claim_for_source` / `claims_for_sources`: the claim state of a job or appointment (or none).
* `approved_lines`: what the workshop may do, line by line, with what the payer and the customer will each pay.
* `payable_split`: who pays what of everything authorised so far (payer net, the customer's excess, customer extras).
* `work_gate`: may work start? (`warn` or `block` is a business setting; a recorded decision to go ahead lifts it.)
* `open_claim`: open a claim for a job or appointment (the caller needs 'claims.manage' at the branch).

Claims publishes `claim.created`, `claim.estimate_submitted`, `claim.response_recorded`, `claim.authorised`,
`claim.completed`, `claim.invoiced`, `claim.credited`, `claim.payment_recorded`, `claim.short_paid`, `claim.closed`;
every
payload carries `company_id`, `branch_id`, `number` and, when there is one, `source_type` and `source_id`.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.domain.money import ZERO
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Payer
from ziira.modules.claims.services import claims as claim_service
from ziira.modules.claims.services import gate, status
from ziira.sdk import Session

__all__ = ["ApprovedLine", "ClaimState", "PayableSplit", "WorkGateResult", "approved_lines", "claim_for_source",
           "claims_for_sources", "open_claim", "payable_split", "work_gate"]

WorkGateResult = gate.WorkGateResult


@dataclass(frozen=True)
class ClaimState:
    """Where a claim stands, for a job or appointment screen."""

    id: UUID
    number: str
    status: str                      # draft | open | authorised | completed | invoiced | settled | closed
    closed_reason: str | None
    payer_id: UUID
    payer_name: str
    waiting_on: str | None           # payer | us | customer | None
    policy_number: str | None
    claim_number: str | None
    excess: Decimal
    authorised_total: Decimal        # what may be worked on (payer's part plus the customer's part)
    payer_pays: Decimal
    customer_pays: Decimal
    open_total: Decimal              # asked and still undecided
    authority_ref: str | None
    completed: bool
    invoiced: bool


@dataclass(frozen=True)
class ApprovedLine:
    """One line of the estimates in play, with the payer's answer."""

    id: UUID
    estimate_id: UUID
    description: str
    kind: str
    quantity: Decimal
    unit_price: Decimal
    asked_total: Decimal
    state: str                       # pending | approved | countered | rejected | needs_information
    payer_pays: Decimal
    customer_pays: Decimal
    work_authorised: bool            # the workshop may do this line
    part_class: str | None
    reason: str | None
    waiting_on: str | None


@dataclass(frozen=True)
class PayableSplit:
    """Who will pay what of everything authorised so far."""

    payer_gross: Decimal
    excess: Decimal                  # the customer's excess applied
    payer_net: Decimal               # the payer's invoice
    customer_total: Decimal          # the customer's invoice: excess plus rejected or uncovered lines they accepted
    absorbed: Decimal                # given up by the business on accepted counter-offers


def _waiting_on(line_state: rules.LineFacts) -> str | None:
    if line_state.payer_state in ("pending", "needs_information"):
        return "payer"
    if line_state.payer_state == "countered" and line_state.our_decision is None:
        return "us"
    if line_state.payer_state == "rejected" and line_state.customer_decision is None:
        return "customer"
    return None


def _state(session: Session, claim: Claim) -> ClaimState:
    payer = repo.get(session, Payer, claim.payer_id)
    assert payer is not None
    totals = status.totals(session, claim.id)
    waits = {_waiting_on(status.facts(line)) for _, line in status.in_play(session, claim.id)} - {None}
    waiting = next((w for w in ("us", "customer", "payer") if w in waits), None)
    return ClaimState(
        id=claim.id, number=claim.number, status=claim.status, closed_reason=claim.closed_reason, payer_id=payer.id,
        payer_name=payer.name, waiting_on=waiting, policy_number=claim.policy_number, claim_number=claim.claim_number,
        excess=claim.excess_amount, authorised_total=totals["payer_pays"] + totals["customer_pays"],
        payer_pays=totals["payer_pays"], customer_pays=totals["customer_pays"], open_total=totals["open"],
        authority_ref=claim.authority_ref, completed=claim.completed_at is not None,
        invoiced=claim.invoiced_at is not None)


def claim_for_source(session: Session, source_type: str, source_id: UUID) -> ClaimState | None:
    """The claim of a job (`source_type="job"`) or appointment (`"appointment"`): the live one, else the latest
    closed."""
    claim = gate.claim_of(session, source_type, source_id)
    return _state(session, claim) if claim is not None else None


def claims_for_sources(session: Session, source_type: str, source_ids: set[UUID]) -> dict[UUID, ClaimState]:
    """`claim_for_source` for many jobs or appointments (for a board or list)."""
    found: dict[UUID, ClaimState] = {}
    for source_id in source_ids:
        state = claim_for_source(session, source_type, source_id)
        if state is not None:
            found[source_id] = state
    return found


def approved_lines(session: Session, source_type: str, source_id: UUID) -> list[ApprovedLine]:
    """The lines in play on the claim of a job or appointment, in order, with the payer's answer. Empty without a
    claim."""
    claim = gate.claim_of(session, source_type, source_id)
    if claim is None:
        return []
    out: list[ApprovedLine] = []
    for estimate, line in status.in_play(session, claim.id):
        f = status.facts(line)
        out.append(ApprovedLine(
            id=line.id, estimate_id=estimate.id, description=line.description, kind=line.kind,
            quantity=line.quantity, unit_price=line.unit_price, asked_total=line.asked_total, state=line.payer_state,
            payer_pays=rules.payer_pays(f), customer_pays=rules.customer_owes(f),
            work_authorised=rules.is_authorised_work(f), part_class=line.part_class, reason=line.payer_reason,
            waiting_on=_waiting_on(f)))
    return out


def payable_split(session: Session, source_type: str, source_id: UUID) -> PayableSplit | None:
    """Who pays what of everything authorised so far on the claim of a job or appointment, or none without a claim."""
    claim = gate.claim_of(session, source_type, source_id)
    if claim is None:
        return None
    split = gate.split_of(session, claim)
    return PayableSplit(split.payer_gross, split.excess_applied, split.payer_net, split.customer_total, split.absorbed)


def work_gate(session: Session, source_type: str, source_id: UUID) -> gate.WorkGateResult:
    """May work start on this job or appointment? Always `allowed` without a claim. With one, work that the payer has
    not
    approved is refused when the business chose `block`, and warned about when it chose `warn` (the default); a
    decision to go ahead recorded on the claim lifts both."""
    return gate.gate(session, gate.claim_of(session, source_type, source_id))


def open_claim(session: Session, *, company_id: UUID, payer_id: UUID, source_type: str, source_id: UUID,
               branch_id: UUID | None = None, customer_id: UUID | None = None, subject: str | None = None,
               policy_number: str | None = None, claim_number: str | None = None, excess_amount: Decimal = ZERO,
               loss_date: date | None = None) -> ClaimState:
    """Open a claim for a job or appointment. The caller needs 'claims.manage' at the branch."""
    claim = claim_service.create_claim(
        session, company_id=company_id, branch_id=branch_id, payer_id=payer_id, customer_id=customer_id,
        source_type=source_type, source_id=source_id, subject=subject, policy_number=policy_number,
        claim_number=claim_number, excess_amount=excess_amount, loss_date=loss_date)
    return _state(session, claim)


# --------------------------------------------------------------------------- added for Jobs (garage insurer jobs)
@dataclass(frozen=True)
class PayerTerms:
    """The payer's terms as data, for the job screen to suggest rates (the estimate keeps what is typed)."""

    payer_id: UUID
    payer_name: str
    labour_rates: dict[str, Decimal]         # work type -> hourly rate; the key `default` is the fallback
    paint_rate: Decimal | None
    parts_discount_pct: Decimal
    parts_markup_pct: Decimal
    required_documents: list[str]

    def labour_rate(self, work_type: str | None) -> Decimal | None:
        from ziira.modules.claims.domain import rates as claim_rates

        return claim_rates.labour_rate({k: str(v) for k, v in self.labour_rates.items()}, work_type)

    def parts_price(self, list_price: Decimal) -> Decimal:
        from ziira.modules.claims.domain import rates as claim_rates

        return claim_rates.parts_price(list_price, self.parts_discount_pct, self.parts_markup_pct)


def payer_terms(session: Session, source_type: str, source_id: UUID) -> PayerTerms | None:
    """The terms of the payer of the live claim of a job or appointment, or none without a claim."""
    claim = gate.claim_of(session, source_type, source_id)
    if claim is None or claim.status == "closed":
        return None
    payer = repo.get(session, Payer, claim.payer_id)
    if payer is None:
        return None
    return PayerTerms(payer.id, payer.name, {str(k): Decimal(str(v)) for k, v in (payer.labour_rates or {}).items()},
                      payer.paint_rate, payer.parts_discount_pct, payer.parts_markup_pct,
                      [str(d) for d in (payer.required_documents or [])])


@dataclass(frozen=True)
class EstimateLineSpec:
    """A line to put on a claim estimate. Kinds: labour, parts, paint, sundries, other. A blank price on labour or paint
    takes the payer's rate."""

    kind: str
    description: str
    quantity: Decimal
    unit_price: Decimal | None = None
    work_type: str | None = None
    part_class: str | None = None
    product_id: UUID | None = None


def draft_estimate(session: Session, source_type: str, source_id: UUID, lines: list[EstimateLineSpec], *,
                   kind: str = "original", notes: str | None = None) -> UUID:
    """Start a draft estimate for the live claim of a job or appointment from plain lines (the caller needs
    'claims.estimate' at the branch). `kind` is `original` or `supplementary`. Returns the estimate's id."""
    from ziira.modules.claims.services import estimates as estimate_service
    from ziira.sdk import NotFound

    claim = gate.claim_of(session, source_type, source_id)
    if claim is None:
        raise NotFound("There is no claim for this job")
    made = estimate_service.create_estimate(
        session, claim.id, kind=kind, notes=notes,
        lines=[estimate_service.LineIn(kind=x.kind, description=x.description, quantity=x.quantity,
                                       unit_price=x.unit_price, work_type=x.work_type, part_class=x.part_class,
                                       product_id=x.product_id) for x in lines])
    return made.id


@dataclass(frozen=True)
class ClaimBilling:
    """What a billing run of the claim made: the payer's invoice and the customer's invoice (either may be none)."""

    payer_invoice_id: UUID | None
    payer_invoice_number: str | None
    payer_amount: Decimal
    customer_invoice_id: UUID | None
    customer_invoice_number: str | None
    customer_amount: Decimal


def bill_claim(session: Session, source_type: str, source_id: UUID) -> ClaimBilling:
    """Bill what is authorised and not yet billed on the live claim of a job or appointment: the payer's invoice (less
    the customer's excess) and the customer's invoice. The caller needs 'claims.invoice' and POS's invoicing permission,
    and the work must be signed off."""
    from ziira.modules.claims.services import invoicing as claim_invoicing
    from ziira.sdk import NotFound

    claim = gate.claim_of(session, source_type, source_id)
    if claim is None:
        raise NotFound("There is no claim for this job")
    run = claim_invoicing.invoice_claim(session, claim.id)
    return ClaimBilling(run.payer_invoice_id, run.payer_invoice_number, run.payer_amount, run.customer_invoice_id,
                        run.customer_invoice_number, run.customer_amount)


def complete_claim_work(session: Session, source_type: str, source_id: UUID, *, signed_by: str,
                        note: str | None = None) -> None:
    """Record the completion sign-off (name and time) on the live claim of a job: the work is done, it may be billed."""
    from ziira.sdk import NotFound

    claim = gate.claim_of(session, source_type, source_id)
    if claim is None:
        raise NotFound("There is no claim for this job")
    claim_service.complete_claim(session, claim.id, signed_by=signed_by, note=note)


def ensure_payer(session: Session, company_id: UUID, name: str, *, kind: str = "insurer",
                 labour_rates: dict[str, str] | None = None, parts_discount_pct: Decimal = ZERO,
                 required_documents: list[str] | None = None, payment_days: int = 30,
                 new_customer: dict[str, str | None] | None = None) -> UUID:
    """The company's payer with this name (made when there is none, with its own customer account from `new_customer`).
    For industry packs and sample data. The caller needs 'claims.settings'. Returns the payer's id."""
    from ziira.modules.claims.services import settings as claim_settings

    existing = repo.payer_by_name(session, company_id, name.strip())
    if existing is not None:
        return existing.id
    made = claim_settings.create_payer(
        session, company_id=company_id, name=name, kind=kind, new_customer=new_customer,
        labour_rates=dict(labour_rates or {}), parts_discount_pct=parts_discount_pct, payment_days=payment_days,
        required_documents=required_documents)
    return made.id


def retire_payer(session: Session, payer_id: UUID) -> None:
    """Stop using a payer (it stays in the history). Needs 'claims.settings'."""
    from ziira.modules.claims.services import settings as claim_settings

    claim_settings.update_payer(session, payer_id, is_active=False)


def close_claim_for_source(session: Session, source_type: str, source_id: UUID, *, reason: str = "cancelled",
                           note: str | None = None) -> bool:
    """Close the live claim of a job or appointment (for example when sample data is taken away). False when there is
    none. Needs 'claims.manage'."""
    claim = gate.claim_of(session, source_type, source_id)
    if claim is None or claim.status == "closed":
        return False
    claim_service.close_claim(session, claim.id, reason=reason, note=note)
    return True

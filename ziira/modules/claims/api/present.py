"""Turn claims and their parts into API shapes. Reads only; the services decide who may see what."""

from decimal import Decimal
from uuid import UUID

from ziira.modules.claims.api import schemas as sc
from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Estimate, EstimateLine, EstimateLink, Payer
from ziira.modules.claims.services import gate, invoicing, links, status
from ziira.modules.claims.services.common import unit_enabled
from ziira.modules.claims.services.estimates import is_over_limit, label
from ziira.sdk import Session


def totals_out(t: dict[str, Decimal]) -> sc.ClaimsTotalsOut:
    return sc.ClaimsTotalsOut(asked=t["asked"], payer_pays=t["payer_pays"], customer_pays=t["customer_pays"],
                              open=t["open"], absorbed=t["absorbed"])


def summaries(session: Session, claims: list[Claim]) -> list[sc.ClaimsSummaryOut]:
    payers = repo.payers_by_ids(session, {c.payer_id for c in claims})
    played = status.bulk_in_play(session, {c.id for c in claims})
    out = []
    for c in claims:
        totals, waiting = status.summarise(played[c.id])
        out.append(sc.ClaimsSummaryOut(
            id=c.id, company_id=c.company_id, branch_id=c.branch_id, number=c.number, payer_id=c.payer_id,
            payer_name=payers[c.payer_id].name if c.payer_id in payers else "", customer_id=c.customer_id,
            insured_name=c.insured_name, subject=c.subject, source_type=c.source_type, source_id=c.source_id,
            source_number=c.source_number, policy_number=c.policy_number, claim_number=c.claim_number,
            status=c.status, closed_reason=c.closed_reason, waiting_on=waiting if c.status != "closed" else None,
            excess_amount=c.excess_amount, totals=totals_out(totals), created_at=c.created_at))
    return out


def payer_out(session: Session, payer: Payer) -> sc.ClaimsPayerOut:
    out = sc.ClaimsPayerOut.model_validate(payer)
    if payer.customer_id is not None and unit_enabled(session, "crm"):
        from ziira.modules.crm.public import find_customer

        found = find_customer(session, payer.customer_id)
        out.customer_name = found.name if found else None
    return out


def link_out(link: EstimateLink) -> sc.ClaimsLinkOut:
    return sc.ClaimsLinkOut(id=link.id, created_at=link.created_at, expires_at=link.expires_at,
                            state=links.state_of(link), sent_via=link.sent_via, sent_to=link.sent_to,
                            view_count=link.view_count, last_accessed_at=link.last_accessed_at,
                            signer_name=link.signer_name, signed_off_at=link.signed_off_at)


def line_out(line: EstimateLine, history: list[sc.ClaimsLineHistoryOut]) -> sc.ClaimsLineOut:
    f = status.facts(line)
    return sc.ClaimsLineOut(
        id=line.id, position=line.position, kind=line.kind, work_type=line.work_type, part_class=line.part_class,
        description=line.description, quantity=line.quantity, unit_price=line.unit_price,
        asked_total=line.asked_total, locked=line.locked, payer_state=line.payer_state,
        payer_amount=line.payer_amount, payer_reason=line.payer_reason, responded_at=line.responded_at,
        our_decision=line.our_decision, customer_decision=line.customer_decision,
        customer_decision_by=line.customer_decision_by, shortfall_to=line.shortfall_to,
        invoiced=line.invoiced_run_id is not None, payer_pays=rules.payer_pays(f),
        customer_pays=rules.customer_owes(f), waiting_on=status.waiting_on(f), history=history)


def estimate_out(session: Session, estimate: Estimate, *, payer: Payer | None = None,
                 with_links: bool = True) -> sc.ClaimsEstimateOut:
    claim = repo.get(session, Claim, estimate.claim_id)
    assert claim is not None
    payer = payer or repo.get(session, Payer, claim.payer_id)
    assert payer is not None
    rows = repo.estimate_lines(session, estimate.id)
    history: dict[UUID, list[sc.ClaimsLineHistoryOut]] = {}
    for h in repo.line_responses(session, claim.id):
        # every earlier version's answers on the same line family are shown with it (carried_from chain)
        history.setdefault(h.line_id, []).append(sc.ClaimsLineHistoryOut(
            round=h.round, state=h.state, amount=h.amount, reason=h.reason, by_name=h.by_name, channel=h.channel,
            via=h.via, answered_at=h.answered_at))
    chain = {r.id: _chain(r, {x.id: x for x in repo.claim_lines(session, claim.id)}) for r in rows}
    lines = [line_out(r, sorted([h for lid in chain[r.id] for h in history.get(lid, [])],
                                key=lambda h: h.answered_at)) for r in rows]
    answers = [sc.ClaimsResponseOut(round=x.round, response=x.response, by_name=x.by_name, channel=x.channel,
                                    via=x.via, occurred_at=x.occurred_at, note=x.note, authority_ref=x.authority_ref,
                                    authority_amount=x.authority_amount)
               for x in repo.estimate_responses(session, claim.id) if x.estimate_id == estimate.id]
    live = {e.id for e, _ in status.in_play(session, claim.id)}
    return sc.ClaimsEstimateOut(
        id=estimate.id, claim_id=claim.id, seq=estimate.seq, label=label(estimate), lineage_id=estimate.lineage_id,
        lineage_kind=estimate.lineage_kind, lineage_no=estimate.lineage_no, version=estimate.version,
        previous_id=estimate.previous_id, status=estimate.status, in_play=estimate.id in live,
        title=estimate.title, notes=estimate.notes, revision_note=estimate.revision_note,
        valid_until=estimate.valid_until, total=estimate.total, submitted_at=estimate.submitted_at,
        submitted_via=estimate.submitted_via, answered_at=estimate.answered_at, response=estimate.response,
        over_approval_limit=is_over_limit(payer, estimate), lines=lines, responses=answers,
        links=[link_out(link) for link in repo.links_of_estimate(session, estimate.id)] if with_links else [])


def _chain(line: EstimateLine, by_id: dict[UUID, EstimateLine]) -> list[UUID]:
    """The line and the lines of earlier versions it was carried from (so its whole history shows)."""
    ids = [line.id]
    seen = {line.id}
    current = line
    while current.carried_from_id and current.carried_from_id in by_id and current.carried_from_id not in seen:
        current = by_id[current.carried_from_id]
        ids.append(current.id)
        seen.add(current.id)
    return ids


def detail(session: Session, claim: Claim) -> sc.ClaimsClaimOut:
    payer = repo.get(session, Payer, claim.payer_id)
    assert payer is not None
    base = summaries(session, [claim])[0]
    estimates = [estimate_out(session, e, payer=payer) for e in repo.estimates(session, claim.id)]
    runs = repo.runs(session, claim.id)
    states: dict[UUID, object] = {}
    if runs and unit_enabled(session, "pos"):
        import ziira.modules.pos.public as pos

        ids = {i for r in runs for i in (r.payer_invoice_id, r.customer_invoice_id) if i}
        states = dict(pos.invoice_states(session, ids))

    def state_of(invoice_id: UUID | None) -> tuple[Decimal | None, str | None]:
        found = states.get(invoice_id) if invoice_id else None
        return (found.outstanding, found.status) if found is not None else (None, None)  # type: ignore[attr-defined]

    run_out = []
    for r in runs:
        po, ps = state_of(r.payer_invoice_id)
        co, cs = state_of(r.customer_invoice_id)
        run_out.append(sc.ClaimsInvoiceRunOut(
            id=r.id, seq=r.seq, created_at=r.created_at, payer_invoice_id=r.payer_invoice_id,
            payer_invoice_number=r.payer_invoice_number, payer_amount=r.payer_amount, payer_outstanding=po,
            payer_status=ps, excess_applied=r.excess_applied, customer_invoice_id=r.customer_invoice_id,
            customer_invoice_number=r.customer_invoice_number, customer_amount=r.customer_amount,
            customer_outstanding=co, customer_status=cs))
    plan = invoicing.preview(session, claim.id) if claim.status != "closed" else None
    result = gate.gate(session, claim)
    return sc.ClaimsClaimOut(
        **base.model_dump(), insured_phone=claim.insured_phone, member_number=claim.member_number,
        preauth_ref=claim.preauth_ref, loss_date=claim.loss_date, loss_description=claim.loss_description,
        assessor_name=claim.assessor_name, assessor_phone=claim.assessor_phone, closed_note=claim.closed_note,
        closed_amount=claim.closed_amount, closed_at=claim.closed_at, authority_ref=claim.authority_ref,
        authority_amount=claim.authority_amount, authority_by=claim.authority_by, authority_at=claim.authority_at,
        completed_at=claim.completed_at, completion_signed_by=claim.completion_signed_by,
        completion_signed_at=claim.completion_signed_at, completion_note=claim.completion_note,
        invoiced_at=claim.invoiced_at, required_documents=list(payer.required_documents), estimates=estimates,
        events=[sc.ClaimsEventOut(id=e.id, created_at=e.created_at, kind=e.kind, note=e.note,
                                  occurred_on=e.occurred_on, actor_name=e.actor_name, channel=e.channel,
                                  estimate_id=e.estimate_id) for e in repo.events(session, claim.id)],
        runs=run_out, short_pays=[sc.ClaimsShortPayOut.model_validate(s)
                                  for s in repo.short_pays(session, None, claim_id=claim.id)],
        gate=sc.ClaimsGateOut(has_claim=True, state=result.state, allowed=result.allowed, policy=result.policy,
                              authorised_total=result.authorised_total, unapproved_total=result.unapproved_total,
                              decision_recorded=result.decision_recorded, message=result.message),
        can_invoice=plan is not None and not plan.blockers, blockers=plan.blockers if plan else [])


def billing_out(plan: invoicing.Billing) -> sc.ClaimsBillingOut:
    split = plan.split
    return sc.ClaimsBillingOut(
        payer_parts=[sc.ClaimsBillingPartOut(description=p.description, amount=p.gross, discount=p.discount)
                     for p in split.payer_parts],
        customer_parts=[sc.ClaimsBillingPartOut(description=p.description, amount=p.amount, kind=p.kind)
                        for p in split.customer_parts],
        payer_gross=split.payer_gross, excess_applied=split.excess_applied, payer_net=split.payer_net,
        customer_total=split.customer_total, absorbed=split.absorbed, waiting_lines=len(plan.waiting),
        blockers=plan.blockers)

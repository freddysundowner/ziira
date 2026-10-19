"""HTTP endpoints of the Claims module. Routes only convert HTTP to service calls.

`public_router` holds the payer's response page (no sign-in): the link's secret is its credential.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, PlainTextResponse

from ziira.modules.claims.api import present
from ziira.modules.claims.api import schemas as sc
from ziira.modules.claims.domain import document as doc_render
from ziira.modules.claims.permissions import (
    ALL,
    CLAIMS_ESTIMATE,
    CLAIMS_INVOICE,
    CLAIMS_MANAGE,
    CLAIMS_PAYMENTS,
    CLAIMS_SETTINGS,
)
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.services import (
    access,
    claims,
    documents,
    estimates,
    gate,
    invoicing,
    links,
    public_response,
    receipts,
    responses,
)
from ziira.modules.claims.services import settings as claim_settings
from ziira.modules.claims.services.common import load_claim, load_estimate, unit_enabled
from ziira.sdk import (
    DB_SESSION,
    Forbidden,
    NotFound,
    RequestContext,
    Session,
    client_ip,
    idempotency_key_header,
    idempotent,
    page_limit,
    page_offset,
    request_context,
)

router = APIRouter()
public_router = APIRouter()
CREATED = status.HTTP_201_CREATED


def any_of(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


VIEW = [Depends(any_of(*ALL))]
MANAGE = [Depends(any_of(CLAIMS_MANAGE))]
ESTIMATE = [Depends(any_of(CLAIMS_ESTIMATE))]
INVOICE = [Depends(any_of(CLAIMS_INVOICE))]
PAYMENTS = [Depends(any_of(CLAIMS_PAYMENTS))]
SETTINGS = [Depends(any_of(CLAIMS_SETTINGS))]


def _claim(session: Session, claim_id: UUID) -> sc.ClaimsClaimOut:
    return present.detail(session, load_claim(session, claim_id))


def _estimate(session: Session, estimate_id: UUID) -> sc.ClaimsEstimateOut:
    estimate, _ = load_estimate(session, estimate_id)
    return present.estimate_out(session, estimate)


def _lines(body: list[sc.ClaimsLineIn]) -> list[estimates.LineIn]:
    return [estimates.LineIn(**x.model_dump()) for x in body]


# --------------------------------------------------------------------------- settings and payers
@router.get("/settings", response_model=sc.ClaimsSettingsOut, dependencies=VIEW)
def get_settings_(company_id: UUID, session: Session = DB_SESSION) -> object:
    row = claim_settings.get_settings(session, company_id)
    return _settings_out(session, row)


def _settings_out(session: Session, row) -> sc.ClaimsSettingsOut:  # type: ignore[no-untyped-def]
    out = sc.ClaimsSettingsOut.model_validate(row)
    if row.invoice_product_id is not None and unit_enabled(session, "products"):
        from ziira.modules.products.public import product_labels

        labels = product_labels(session, {row.invoice_product_id})
        if row.invoice_product_id in labels:
            out.invoice_product_name = labels[row.invoice_product_id][1]
    return out


@router.patch("/settings", response_model=sc.ClaimsSettingsOut, dependencies=SETTINGS)
def patch_settings(company_id: UUID, body: sc.ClaimsSettingsIn, session: Session = DB_SESSION) -> object:
    row = claim_settings.update_settings(session, company_id, **body.model_dump(exclude_unset=True))
    return _settings_out(session, row)


@router.get("/payers", response_model=list[sc.ClaimsPayerOut], dependencies=VIEW)
def get_payers(company_id: UUID | None = None, only_active: bool = False, session: Session = DB_SESSION) -> object:
    return [present.payer_out(session, p) for p in claim_settings.list_payers(session, company_id,
                                                                              only_active=only_active)]


@router.post("/payers", response_model=sc.ClaimsPayerOut, status_code=CREATED, dependencies=SETTINGS)
def post_payer(body: sc.ClaimsPayerIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump(exclude={"new_customer"})
    payer = claim_settings.create_payer(session, new_customer=body.new_customer.model_dump()
                                        if body.new_customer else None, **data)
    return present.payer_out(session, payer)


@router.get("/payers/{payer_id}", response_model=sc.ClaimsPayerOut, dependencies=VIEW)
def get_payer(payer_id: UUID, session: Session = DB_SESSION) -> object:
    return present.payer_out(session, claim_settings.load_payer(session, payer_id))


@router.patch("/payers/{payer_id}", response_model=sc.ClaimsPayerOut, dependencies=SETTINGS)
def patch_payer(payer_id: UUID, body: sc.ClaimsPayerUpdate, session: Session = DB_SESSION) -> object:
    payer = claim_settings.update_payer(session, payer_id, **body.model_dump(exclude_unset=True))
    return present.payer_out(session, payer)


# --------------------------------------------------------------------------- claims
@router.post("/claims", response_model=sc.ClaimsClaimOut, status_code=CREATED, dependencies=MANAGE)
def post_claim(body: sc.ClaimsClaimIn, key: str | None = Depends(idempotency_key_header),
               session: Session = DB_SESSION) -> object:
    """Open a claim for a job or appointment. Send an Idempotency-Key so a retry does not open a second one."""

    def create() -> object:
        made = claims.create_claim(session, **body.model_dump())
        return jsonable_encoder(present.detail(session, made))

    response, _ = idempotent(session, key, body.model_dump(mode="json"), create)
    return response


@router.get("/claims", response_model=list[sc.ClaimsSummaryOut], dependencies=VIEW)
def get_claims(company_id: UUID | None = None, branch_id: UUID | None = None, payer_id: UUID | None = None,
               status_: str | None = Query(default=None, alias="status"), open_only: bool = False,
               source_type: str | None = None, source_id: UUID | None = None, customer_id: UUID | None = None,
               search: str | None = Query(default=None, max_length=100), limit: int = page_limit(50),
               offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    found = claims.list_claims(session, company_id=company_id, branch_id=branch_id, payer_id=payer_id,
                               status_=status_, open_only=open_only, source_type=source_type, source_id=source_id,
                               customer_id=customer_id, search=search, limit=limit, offset=offset)
    return present.summaries(session, found)


@router.get("/claims/by-source", response_model=sc.ClaimsClaimOut, dependencies=VIEW)
def get_claim_by_source(source_type: str, source_id: UUID, session: Session = DB_SESSION) -> object:
    """The claim of a job or appointment (the live one, else the latest closed), for the embedded panel."""
    found = gate.claim_of(session, source_type, source_id)
    if found is None:
        raise NotFound("No claim for this")
    return present.detail(session, load_claim(session, found.id))


@router.get("/claims/{claim_id}", response_model=sc.ClaimsClaimOut, dependencies=VIEW)
def get_claim(claim_id: UUID, session: Session = DB_SESSION) -> object:
    return _claim(session, claim_id)


@router.patch("/claims/{claim_id}", response_model=sc.ClaimsClaimOut, dependencies=MANAGE)
def patch_claim(claim_id: UUID, body: sc.ClaimsClaimUpdate, session: Session = DB_SESSION) -> object:
    claims.update_claim(session, claim_id, **body.model_dump(exclude_unset=True))
    return _claim(session, claim_id)


@router.post("/claims/{claim_id}/notes", response_model=sc.ClaimsClaimOut, status_code=CREATED, dependencies=MANAGE)
def post_note(claim_id: UUID, body: sc.ClaimsNoteIn, session: Session = DB_SESSION) -> object:
    """A dated note: a plain note, an assessor's visit or a re-inspection."""
    claims.add_note(session, claim_id, kind=body.kind, note=body.note, occurred_on=body.occurred_on, actor=body.by)
    return _claim(session, claim_id)


@router.put("/claims/{claim_id}/authority", response_model=sc.ClaimsClaimOut, dependencies=MANAGE)
def put_authority(claim_id: UUID, body: sc.ClaimsAuthorityIn, session: Session = DB_SESSION) -> object:
    """The payer's authority to repair (approval or order number and amount), as told to us."""
    claims.record_authority(session, claim_id, reference=body.reference, amount=body.amount, by_name=body.by_name,
                            at=body.at)
    return _claim(session, claim_id)


@router.post("/claims/{claim_id}/completion", response_model=sc.ClaimsClaimOut, dependencies=MANAGE)
def post_completion(claim_id: UUID, body: sc.ClaimsCompletionIn, session: Session = DB_SESSION) -> object:
    """Sign the work off: the name and time of whoever accepted it."""
    claims.complete_claim(session, claim_id, signed_by=body.signed_by, note=body.note, signed_at=body.signed_at)
    return _claim(session, claim_id)


@router.post("/claims/{claim_id}/close", response_model=sc.ClaimsClaimOut, dependencies=MANAGE)
def post_close(claim_id: UUID, body: sc.ClaimsCloseIn, session: Session = DB_SESSION) -> object:
    """Close with an outcome: total loss, salvage, cash in lieu, rejected, withdrawn, cancelled or written off."""
    claims.close_claim(session, claim_id, reason=body.reason, note=body.note, amount=body.amount)
    return _claim(session, claim_id)


@router.post("/claims/{claim_id}/refresh", response_model=sc.ClaimsClaimOut, dependencies=MANAGE)
def post_refresh(claim_id: UUID, session: Session = DB_SESSION) -> object:
    """Look at the claim again: payments made straight in Point of Sale settle it too."""
    receipts.refresh_after_external_payment(session, load_claim(session, claim_id, lock=True))
    return _claim(session, claim_id)


@router.get("/claims/{claim_id}/work-gate", response_model=sc.ClaimsGateOut, dependencies=VIEW)
def get_gate(claim_id: UUID, session: Session = DB_SESSION) -> object:
    result = gate.gate(session, load_claim(session, claim_id))
    return sc.ClaimsGateOut(has_claim=True, state=result.state, allowed=result.allowed, policy=result.policy,
                            authorised_total=result.authorised_total, unapproved_total=result.unapproved_total,
                            decision_recorded=result.decision_recorded, message=result.message)


@router.post("/claims/{claim_id}/work-decisions", response_model=sc.ClaimsClaimOut, status_code=CREATED,
             dependencies=MANAGE)
def post_work_decision(claim_id: UUID, body: sc.ClaimsWorkDecisionIn, session: Session = DB_SESSION) -> object:
    """Go ahead with work the payer has not approved: who decided and why is recorded."""
    gate.record_work_decision(session, claim_id, body.note)
    return _claim(session, claim_id)


# --------------------------------------------------------------------------- estimates
@router.post("/claims/{claim_id}/estimates", response_model=sc.ClaimsEstimateOut, status_code=CREATED,
             dependencies=ESTIMATE)
def post_estimate(claim_id: UUID, body: sc.ClaimsEstimateIn, session: Session = DB_SESSION) -> object:
    """Start the next estimate as a draft: the first (`original`), extra damage (`supplementary`) or the next version
    after the payer's answer (`revision`, naming the estimate it follows)."""
    made = estimates.create_estimate(
        session, claim_id, kind=body.kind, lines=_lines(body.lines), from_estimate_id=body.from_estimate_id,
        notes=body.notes, valid_until=body.valid_until, title=body.title, revision_note=body.revision_note,
        apply_terms=body.apply_payer_terms)
    return present.estimate_out(session, made)


@router.get("/estimates/{estimate_id}", response_model=sc.ClaimsEstimateOut, dependencies=VIEW)
def get_estimate(estimate_id: UUID, session: Session = DB_SESSION) -> object:
    return _estimate(session, estimate_id)


@router.patch("/estimates/{estimate_id}", response_model=sc.ClaimsEstimateOut, dependencies=ESTIMATE)
def patch_estimate(estimate_id: UUID, body: sc.ClaimsEstimateUpdate, session: Session = DB_SESSION) -> object:
    given = body.model_fields_set
    changed = estimates.update_estimate(
        session, estimate_id, lines=_lines(body.lines) if body.lines is not None else None, notes=body.notes,
        change_notes="notes" in given, valid_until=body.valid_until, change_valid_until="valid_until" in given,
        revision_note=body.revision_note, change_revision_note="revision_note" in given, title=body.title,
        change_title="title" in given, apply_terms=body.apply_payer_terms)
    return present.estimate_out(session, changed)


@router.post("/estimates/{estimate_id}/submit", response_model=sc.ClaimsSubmitOut, dependencies=ESTIMATE)
def post_submit(estimate_id: UUID, body: sc.ClaimsSubmitIn, session: Session = DB_SESSION) -> object:
    """Send the draft to the payer. The reply holds the response link once (when one was made)."""
    sent, secret, queued = estimates.submit_estimate(session, estimate_id, channel=body.channel,
                                                     recipient=body.recipient, make_link=body.make_link,
                                                     link_days=body.link_days)
    return sc.ClaimsSubmitOut(estimate=present.estimate_out(session, sent),
                              link_path=f"/claim-response/{secret}" if secret else None, queued=queued)


@router.post("/estimates/{estimate_id}/withdraw", response_model=sc.ClaimsEstimateOut, dependencies=ESTIMATE)
def post_withdraw(estimate_id: UUID, body: sc.ClaimsWithdrawIn, session: Session = DB_SESSION) -> object:
    done = estimates.withdraw_estimate(session, estimate_id, note=body.note)
    return present.estimate_out(session, done)


@router.get("/estimates/{estimate_id}/document", dependencies=VIEW)
def get_document(estimate_id: UUID, format: str = Query(default="html", pattern="^(html|text)$"),
                 session: Session = DB_SESSION) -> Response:
    """The printable estimate: a page the browser prints or saves as PDF, or plain text."""
    built = documents.build(session, estimate_id)
    if format == "text":
        return PlainTextResponse(doc_render.render_text(built))
    return HTMLResponse(doc_render.render_html(built))


@router.post("/estimates/{estimate_id}/responses", response_model=sc.ClaimsEstimateOut, dependencies=ESTIMATE)
def post_response(estimate_id: UUID, body: sc.ClaimsResponseIn, key: str | None = Depends(idempotency_key_header),
                  session: Session = DB_SESSION) -> object:
    """Write down the payer's answer received by phone, email, a portal or in person: who, how and when."""

    def record() -> object:
        responses.record_response(
            session, estimate_id, [responses.AnswerIn(**a.model_dump()) for a in body.answers], by_name=body.by_name,
            via=body.via, occurred_at=body.occurred_at, note=body.note, authority_ref=body.authority_ref,
            authority_amount=body.authority_amount)
        return jsonable_encoder(_estimate(session, estimate_id))

    response, _ = idempotent(session, key, {"estimate": str(estimate_id), **body.model_dump(mode="json")}, record)
    return response


@router.get("/estimates/{estimate_id}/links", response_model=list[sc.ClaimsLinkOut], dependencies=VIEW)
def get_links(estimate_id: UUID, session: Session = DB_SESSION) -> object:
    return [present.link_out(x) for x in links.links_of(session, estimate_id)]


@router.post("/estimates/{estimate_id}/links", response_model=sc.ClaimsLinkMadeOut, status_code=CREATED,
             dependencies=ESTIMATE)
def post_link(estimate_id: UUID, session: Session = DB_SESSION) -> object:
    """Make another response link for a sent estimate. The link is shown only now."""
    link, secret = links.issue_link(session, estimate_id)
    return sc.ClaimsLinkMadeOut(link=present.link_out(link), link_path=f"/claim-response/{secret}")


@router.delete("/links/{link_id}", response_model=sc.ClaimsLinkOut, dependencies=ESTIMATE)
def delete_link(link_id: UUID, session: Session = DB_SESSION) -> object:
    """Revoke a response link: it stops working at once."""
    return present.link_out(links.revoke_link(session, link_id))


@router.get("/links/{link_id}/access", response_model=list[sc.ClaimsLinkAccessOut], dependencies=VIEW)
def get_link_access(link_id: UUID, session: Session = DB_SESSION) -> object:
    """Every time the link was opened, answered or refused."""
    return [sc.ClaimsLinkAccessOut(created_at=a.created_at, action=a.action, outcome=a.outcome,
                                   ip_address=a.ip_address, user_agent=a.user_agent)
            for a in links.accesses_of(session, link_id)]


@router.post("/lines/{line_id}/counter-decision", response_model=sc.ClaimsClaimOut, dependencies=ESTIMATE)
def post_counter_decision(line_id: UUID, body: sc.ClaimsCounterDecisionIn, session: Session = DB_SESSION) -> object:
    """Accept or decline a counter-offer on a line."""
    line = responses.decide_counter(session, line_id, accept=body.accept, shortfall_to=body.shortfall_to,
                                    customer_agreed_by=body.customer_agreed_by, note=body.note)
    return _claim(session, line.claim_id)


@router.post("/lines/{line_id}/customer-decision", response_model=sc.ClaimsClaimOut, dependencies=ESTIMATE)
def post_customer_decision(line_id: UUID, body: sc.ClaimsCustomerDecisionIn, session: Session = DB_SESSION) -> object:
    """Write down whether the customer pays for a line the payer rejected."""
    line = responses.decide_customer(session, line_id, pays=body.pays, by_name=body.by_name, note=body.note)
    return _claim(session, line.claim_id)


# --------------------------------------------------------------------------- billing and money
@router.get("/claims/{claim_id}/billing", response_model=sc.ClaimsBillingOut, dependencies=VIEW)
def get_billing(claim_id: UUID, session: Session = DB_SESSION) -> object:
    """What the next invoices would be, and what stops them."""
    return present.billing_out(invoicing.preview(session, claim_id))


@router.post("/claims/{claim_id}/invoice", response_model=sc.ClaimsClaimOut, dependencies=INVOICE)
def post_invoice(claim_id: UUID, session: Session = DB_SESSION) -> object:
    """Invoice what is authorised: the payer's invoice (less the excess) and the customer's invoice."""
    invoicing.invoice_claim(session, claim_id)
    return _claim(session, claim_id)


@router.post("/claims/{claim_id}/reductions", response_model=sc.ClaimsClaimOut, dependencies=INVOICE)
def post_reduction(claim_id: UUID, body: sc.ClaimsReductionIn, session: Session = DB_SESSION) -> object:
    """The payer now pays less for an invoiced line: credit note, new answer, billed again in the next run."""
    invoicing.reduce_line(session, claim_id, body.line_id, new_amount=body.new_amount, reason=body.reason,
                          by_name=body.by_name, shortfall_to=body.shortfall_to,
                          customer_agreed_by=body.customer_agreed_by)
    return _claim(session, claim_id)


@router.get("/payers/{payer_id}/statement", response_model=sc.ClaimsPayerStatementOut, dependencies=VIEW)
def get_payer_statement(payer_id: UUID, session: Session = DB_SESSION) -> object:
    data = receipts.payer_statement(session, payer_id)
    return sc.ClaimsPayerStatementOut(
        payer=present.payer_out(session, data["payer"]),
        owed=[sc.ClaimsOwedOut(**o.__dict__) for o in data["owed"]],
        receipts=[sc.ClaimsReceiptOut.model_validate(r) for r in data["receipts"]],
        short_pays=[sc.ClaimsShortPayOut.model_validate(s) for s in data["short_pays"]])


@router.post("/payers/{payer_id}/receipts", response_model=sc.ClaimsReceiptResultOut, status_code=CREATED,
             dependencies=PAYMENTS)
def post_receipt(payer_id: UUID, body: sc.ClaimsReceiptIn, response: Response,
                 session: Session = DB_SESSION) -> object:
    """Record money received from a payer against its invoices. A repeated reference returns the first receipt."""
    made, created = receipts.record_receipt(
        session, payer_id, amount=body.amount, method=body.method, reference=body.reference,
        received_on=body.received_on, branch_id=body.branch_id, note=body.note,
        allocations=[receipts.AllocationIn(**a.model_dump()) for a in body.allocations])
    if not created:
        response.status_code = status.HTTP_200_OK
    return sc.ClaimsReceiptResultOut(receipt=sc.ClaimsReceiptOut.model_validate(made), created=created)


@router.get("/ageing", response_model=list[sc.ClaimsAgeingRowOut], dependencies=VIEW)
def get_ageing(company_id: UUID | None = None, as_of: str | None = None, session: Session = DB_SESSION) -> object:
    """What each payer owes by how late it is."""
    from datetime import date

    day = date.fromisoformat(as_of) if as_of else None
    return receipts.ageing(session, company_id=company_id, as_of=day)


@router.get("/owed", response_model=list[sc.ClaimsOwedOut], dependencies=VIEW)
def get_owed(payer_id: UUID | None = None, company_id: UUID | None = None, session: Session = DB_SESSION) -> object:
    """The payers' unpaid invoices."""
    return [sc.ClaimsOwedOut(**o.__dict__) for o in receipts.owed_invoices(session, payer_id, company_id=company_id)]


@router.get("/short-pays", response_model=list[sc.ClaimsShortPayOut], dependencies=VIEW)
def get_short_pays(status_: str | None = Query(default=None, alias="status"), payer_id: UUID | None = None,
                   session: Session = DB_SESSION) -> object:
    return [sc.ClaimsShortPayOut.model_validate(s)
            for s in repo.short_pays(session, access.view_companies(), status=status_, payer_id=payer_id)]


@router.post("/short-pays/{short_pay_id}/resolve", response_model=sc.ClaimsShortPayOut, dependencies=PAYMENTS)
def post_resolve_short_pay(short_pay_id: UUID, body: sc.ClaimsShortPayResolveIn,
                           session: Session = DB_SESSION) -> object:
    row = receipts.resolve_short_pay(session, short_pay_id, resolution=body.resolution, note=body.note)
    return sc.ClaimsShortPayOut.model_validate(row)


# =========================================================================== the payer's page (no sign-in)
@public_router.get("/public/claim-response/{token}", response_model=sc.ClaimsPublicEstimateOut)
def get_public_estimate(token: str, request: Request) -> object:
    """The estimate behind a link: lines and totals only."""
    return public_response.view(token, client_ip(request), request.headers.get("user-agent"))


@public_router.post("/public/claim-response/{token}", response_model=sc.ClaimsPublicAnswerOut)
def post_public_answer(token: str, body: sc.ClaimsPublicAnswerIn, request: Request) -> object:
    """The payer answers every line and signs off. One sign-off per link."""
    return public_response.answer(
        token, client_ip(request), request.headers.get("user-agent"), name=body.name, role=body.role, note=body.note,
        lines=[public_response.LineAnswer(**x.model_dump()) for x in body.lines], authority_ref=body.authority_ref,
        authority_amount=body.authority_amount)


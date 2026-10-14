"""HTTP endpoints of the Payments module. Routes only convert HTTP to service calls.

`public_router` holds the endpoints Safaricom calls (no user login): each authenticates itself with a secret in its
address.
"""

import logging
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.encoders import jsonable_encoder

from ziira.modules.payments.api import schemas as sc
from ziira.modules.payments.permissions import (
    CLOSE_REOPEN,
    CLOSE_SUBMIT,
    PAYMENTS_COLLECT,
    PAYMENTS_MANAGE,
    PAYMENTS_RECORD,
    PAYMENTS_VIEW,
    RECON_MATCH,
)
from ziira.modules.payments.services import (
    accounts,
    closing,
    external,
    intents,
    matching,
    payments,
    settlements,
)
from ziira.sdk import (
    Amount,
    Forbidden,
    NotFound,
    RequestContext,
    Session,
    current_context,
    db_session,
    idempotency_key_header,
    idempotent,
    page_limit,
    page_offset,
    request_context,
    settings_public_base_url,
)

router = APIRouter()
NO_CONTENT = status.HTTP_204_NO_CONTENT
log = logging.getLogger("ziira.payments")


def any_of(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


VIEW = [Depends(any_of(PAYMENTS_VIEW))]
RECORD = [Depends(any_of(PAYMENTS_RECORD))]
MANAGE = [Depends(any_of(PAYMENTS_MANAGE))]
COLLECT = [Depends(any_of(PAYMENTS_COLLECT))]
MATCH = [Depends(any_of(RECON_MATCH))]


# --------------------------------------------------------------------------- accounts
@router.post("/accounts", response_model=sc.AccountOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_account(body: sc.AccountIn, session: Session = Depends(db_session)) -> object:
    return accounts.create_account(session, company_id=body.company_id, branch_id=body.branch_id, kind=body.kind,
                                   name=body.name, shortcode=body.shortcode,
                                   bank_account_masked=body.bank_account_masked,
                                   ledger_account_id=body.ledger_account_id, environment=body.environment,
                                   provider=body.provider, provider_config=body.provider_config)


@router.get("/accounts", response_model=list[sc.AccountOut], dependencies=VIEW)
def get_accounts(company_id: UUID | None = None, branch_id: UUID | None = None, kind: str | None = None,
                 include_inactive: bool = False, session: Session = Depends(db_session)) -> object:
    return accounts.list_accounts(session, company_id=company_id, branch_id=branch_id, kind=kind,
                                  include_inactive=include_inactive)


@router.get("/accounts/{account_id}", response_model=sc.AccountOut, dependencies=VIEW)
def get_account(account_id: UUID, session: Session = Depends(db_session)) -> object:
    return accounts.get_account(session, account_id)


@router.patch("/accounts/{account_id}", response_model=sc.AccountOut, dependencies=MANAGE)
def patch_account(account_id: UUID, body: sc.AccountUpdateIn, session: Session = Depends(db_session)) -> object:
    return accounts.update_account(session, account_id, name=body.name, is_active=body.is_active,
                                   ledger_account_id=body.ledger_account_id)


@router.put("/accounts/{account_id}/credentials", status_code=NO_CONTENT, dependencies=MANAGE)
def put_credentials(account_id: UUID, body: sc.CredentialsIn, session: Session = Depends(db_session)) -> Response:
    """Store the account's Daraja credentials, encrypted. They cannot be read back."""
    accounts.set_credentials(session, account_id, body.model_dump())
    return Response(status_code=NO_CONTENT)


@router.post("/accounts/{account_id}/callback-token", response_model=sc.CallbackTokenOut, dependencies=MANAGE)
def post_callback_token(account_id: UUID, session: Session = Depends(db_session)) -> object:
    """Make a new secret for the account's callback addresses; register the returned URLs with Safaricom. The old
    ones stop working."""
    token = accounts.rotate_callback_token(session, account_id)
    return sc.CallbackTokenOut(token=token, urls=accounts.callback_urls(token, settings_public_base_url()))


@router.post("/accounts/{account_id}/statements", response_model=sc.StatementResultOut, dependencies=RECORD)
def post_statement(account_id: UUID, body: sc.StatementIn, session: Session = Depends(db_session)) -> object:
    """Upload a statement (M-Pesa or bank CSV). Uploading it twice adds nothing."""
    result = external.import_statement(session, account_id, body.content, fmt=body.format,
                                       options=body.options or None)
    return sc.StatementResultOut(created=result.created, duplicates=result.duplicates, skipped=result.skipped[:200])


# --------------------------------------------------------------------------- payments
@router.post("/payments", response_model=sc.PaymentOut, status_code=status.HTTP_201_CREATED, dependencies=RECORD)
def post_payment(body: sc.PaymentIn, session: Session = Depends(db_session)) -> object:
    """Record money received or paid."""
    current_context().require(PAYMENTS_RECORD, company_id=body.company_id, branch_id=body.branch_id)
    return payments.record_payment(
        session, company_id=body.company_id, branch_id=body.branch_id, method=body.method, direction=body.direction,
        amount=body.amount, payment_account_id=body.payment_account_id, business_date=body.business_date,
        external_ref=body.external_ref, phone=body.phone, party_type=body.party_type, party_id=body.party_id)


@router.get("/payments", response_model=list[sc.PaymentOut], dependencies=VIEW)
def get_payments(branch_id: UUID | None = None, method: str | None = None, business_date: date | None = None,
                 external_ref: str | None = None, doc_id: UUID | None = None, limit: int = page_limit(),
                 offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return payments.list_payments(session, branch_id=branch_id, method=method, business_date=business_date,
                                  external_ref=external_ref, doc_id=doc_id, limit=limit, offset=offset)


@router.get("/payments/{payment_id}", response_model=sc.PaymentOut, dependencies=VIEW)
def get_payment(payment_id: UUID, session: Session = Depends(db_session)) -> object:
    return payments.get_payment(session, payment_id)


@router.post("/payments/{payment_id}/reverse", response_model=sc.PaymentOut, dependencies=RECORD)
def post_reverse(payment_id: UUID, body: sc.ReasonIn, session: Session = Depends(db_session)) -> object:
    return payments.reverse_payment(session, payment_id, body.reason)


# --------------------------------------------------------------------------- what the provider reported
@router.get("/transactions", response_model=list[sc.ExternalOut], dependencies=VIEW)
def get_transactions(payment_account_id: UUID | None = None, match_status: str | None = None,
                     date_from: datetime | None = None, date_to: datetime | None = None, limit: int = page_limit(),
                     offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return external.list_external(session, account_id=payment_account_id, match_status=match_status,
                                  date_from=date_from, date_to=date_to, limit=limit, offset=offset)


@router.get("/transactions/{txn_id}", response_model=sc.ExternalOut, dependencies=VIEW)
def get_transaction(txn_id: UUID, session: Session = Depends(db_session)) -> object:
    return external.get_external(session, txn_id)


@router.post("/transactions/{txn_id}/ignore", response_model=sc.ExternalOut, dependencies=MATCH)
def post_ignore(txn_id: UUID, body: sc.ReasonIn, session: Session = Depends(db_session)) -> object:
    return external.set_ignored(session, txn_id, True, body.reason)


@router.post("/transactions/{txn_id}/unignore", response_model=sc.ExternalOut, dependencies=MATCH)
def post_unignore(txn_id: UUID, body: sc.ReasonIn, session: Session = Depends(db_session)) -> object:
    return external.set_ignored(session, txn_id, False, body.reason)


# --------------------------------------------------------------------------- asking customers to pay
@router.post("/intents", response_model=sc.IntentOut, status_code=status.HTTP_201_CREATED, dependencies=COLLECT)
def post_intent(body: sc.IntentIn, key: str | None = Depends(idempotency_key_header),
                session: Session = Depends(db_session)) -> object:
    """Put an M-Pesa payment prompt on the customer's phone. Send an Idempotency-Key so a retry does not prompt
    twice."""

    def create() -> object:
        intent = intents.start_stk_push(session, account_id=body.payment_account_id, amount=body.amount,
                                        phone=body.phone, doc_type=body.doc_type, doc_id=body.doc_id,
                                        account_reference=body.account_reference)
        return jsonable_encoder(sc.IntentOut.model_validate(intent))

    response, _ = idempotent(session, key, body.model_dump(mode="json"), create)
    return response


@router.get("/intents", response_model=list[sc.IntentOut], dependencies=VIEW)
def get_intents(status_: str | None = Query(default=None, alias="status"), doc_id: UUID | None = None,
                limit: int = page_limit(), offset: int = page_offset(),
                session: Session = Depends(db_session)) -> object:
    return [_intent_out(session, i) for i in intents.list_intents(session, status=status_, doc_id=doc_id, limit=limit,
                                                                  offset=offset)]


@router.get("/intents/{intent_id}", response_model=sc.IntentOut, dependencies=VIEW)
def get_intent(intent_id: UUID, session: Session = Depends(db_session)) -> object:
    """The state of a prompt (poll this until it is 'succeeded', 'failed', 'cancelled' or 'timeout')."""
    return _intent_out(session, intents.get_intent(session, intent_id))


def _intent_out(session: Session, intent: object) -> sc.IntentOut:
    out = sc.IntentOut.model_validate(intent)
    out.receipt = intents.receipt_of(session, intent)  # type: ignore[arg-type]
    return out


# --------------------------------------------------------------------------- matching
@router.post("/matching/run", response_model=sc.MatchRunOut, dependencies=MATCH)
def post_run_matching(body: sc.MatchRunIn | None = None, session: Session = Depends(db_session)) -> object:
    """Match what is unmatched now (it also runs by itself shortly after money arrives)."""
    run = matching.run_matching(session, body.payment_account_id if body else None)
    return sc.MatchRunOut(applied=run.applied, proposed=run.proposed, flagged=run.flagged)


@router.get("/matches", response_model=list[sc.MatchOut], dependencies=VIEW)
def get_matches(external_transaction_id: UUID | None = None, payment_id: UUID | None = None,
                status_: str | None = Query(default=None, alias="status"),
                session: Session = Depends(db_session)) -> object:
    return matching.list_matches(session, txn_id=external_transaction_id, payment_id=payment_id, status=status_)


@router.post("/matches", response_model=sc.MatchOut, status_code=status.HTTP_201_CREATED, dependencies=MATCH)
def post_match(body: sc.ManualMatchIn, session: Session = Depends(db_session)) -> object:
    """Match a transaction to a payment by hand, or confirm what the engine proposed."""
    return matching.manual_match(session, body.external_transaction_id, body.payment_id, body.amount)


@router.post("/matches/{match_id}/undo", response_model=sc.MatchOut, dependencies=MATCH)
def post_undo_match(match_id: UUID, body: sc.ReasonIn, session: Session = Depends(db_session)) -> object:
    return matching.undo_match(session, match_id, body.reason)


# --------------------------------------------------------------------------- moving money between accounts
@router.post("/settlements", response_model=sc.IdOut, status_code=status.HTTP_201_CREATED, dependencies=RECORD)
def post_settlement(body: sc.SettlementIn, session: Session = Depends(db_session)) -> object:
    """M-Pesa paid its takings (less charges) into the bank."""
    return sc.IdOut(id=settlements.record_settlement(
        session, from_account_id=body.from_account_id, to_account_id=body.to_account_id, amount=body.amount,
        fee=body.fee, business_date=body.business_date, reference=body.reference))


@router.post("/cash-deposits", response_model=sc.IdOut, status_code=status.HTTP_201_CREATED, dependencies=RECORD)
def post_cash_deposit(body: sc.CashDepositIn, session: Session = Depends(db_session)) -> object:
    """A branch's cash was taken to the bank."""
    return sc.IdOut(id=settlements.record_cash_deposit(
        session, company_id=body.company_id, branch_id=body.branch_id, bank_account_id=body.bank_account_id,
        amount=body.amount, business_date=body.business_date, reference=body.reference))


# --------------------------------------------------------------------------- the daily close
CLOSER = [Depends(any_of(CLOSE_SUBMIT))]


@router.get("/closes", response_model=list[sc.CloseOut], dependencies=VIEW)
def get_closes(branch_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
               limit: int = page_limit(), offset: int = page_offset(),
               session: Session = Depends(db_session)) -> object:
    return closing.list_closes(session, branch_id=branch_id, status=status_, limit=limit, offset=offset)


@router.get("/closes/preview", response_model=sc.ClosePreviewOut, dependencies=CLOSER)
def get_close_preview(company_id: UUID, branch_id: UUID, business_date: date, cash_banked: Amount | None = None,
                      session: Session = Depends(db_session)) -> object:
    """Where a branch stands for a day: takings, what is unmatched, and what stops it closing."""
    s = closing.preview(session, company_id, branch_id, business_date, cash_banked)
    return sc.ClosePreviewOut(close=sc.CloseOut.model_validate(s.close), problems=s.problems, totals=s.totals)


@router.post("/closes", response_model=sc.ClosePreviewOut, dependencies=CLOSER)
def post_close(body: sc.CloseSubmitIn, session: Session = Depends(db_session)) -> object:
    """Submit the day's close and lock it."""
    s = closing.submit(session, body.company_id, body.branch_id, body.business_date, cash_banked=body.cash_banked,
                       explanation=body.explanation)
    return sc.ClosePreviewOut(close=sc.CloseOut.model_validate(s.close), problems=s.problems, totals=s.totals)


@router.post("/closes/{close_id}/reopen", response_model=sc.CloseOut, dependencies=[Depends(any_of(CLOSE_REOPEN))])
def post_reopen(close_id: UUID, body: sc.ReasonIn, session: Session = Depends(db_session)) -> object:
    """Ask to reopen a locked day (an approver may need to agree)."""
    return closing.request_reopen(session, close_id, body.reason)


# =========================================================================== public callbacks (Safaricom calls these)
public_router = APIRouter()
ACCEPTED = {"ResultCode": 0, "ResultDesc": "Accepted"}


def _tenant_of(hex_id: str) -> UUID:
    try:
        return UUID(hex=hex_id)
    except ValueError:
        raise NotFound("Not found") from None


@public_router.post("/callbacks/{token}/c2b/validation", include_in_schema=False)
def c2b_validation(token: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    """Safaricom asks whether we accept a payment before it is made. We accept every one; matching deals with it."""
    from ziira.modules.payments.api import callbacks

    callbacks.with_account(token, lambda session, account: None)
    return ACCEPTED


@public_router.post("/callbacks/{token}/c2b/confirmation", include_in_schema=False)
def c2b_confirmation(token: str, payload: dict[str, object]) -> dict[str, object]:
    """Safaricom tells us a customer paid one of our tills or paybills."""
    from ziira.modules.payments.api import callbacks

    callbacks.with_account(token, lambda session, account: external.process_c2b(session, account, dict(payload)))
    return ACCEPTED


@public_router.post("/callbacks/stk/{tenant_hex}/{intent_id}/{signature}", include_in_schema=False)
def stk_callback(tenant_hex: str, intent_id: UUID, signature: str, payload: dict[str, object]) -> dict[str, object]:
    """Safaricom tells us how a payment prompt ended."""
    from ziira.modules.payments.api import callbacks

    callbacks.with_intent(_tenant_of(tenant_hex), intent_id, signature,
                          lambda session: intents.handle_callback(session, intent_id, dict(payload)))
    return ACCEPTED

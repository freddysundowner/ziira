"""Use cases: a cashier's till session, from the opening float to the counted cash.

    open (float) --> sales and refunds through the session --> close (cash counted) --> Z report, variance

A cashier has one open till and a device has one open till. Cash is expected to be the float plus the cash taken (less
cash refunded); the difference with what was counted is the variance, which needs a reason, is posted to the books by
Finance and is put in front of a manager.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder

from ziira.modules.payments.public import cash_account_for_branch, cash_in_till_session, day_is_locked
from ziira.modules.pos.domain import sales as rules
from ziira.modules.pos.permissions import TILL_MANAGE
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import TillSession
from ziira.modules.pos.services import access, devices
from ziira.sdk import (
    Conflict,
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_reason,
    company_date_of,
    company_today,
    current_context,
    flag_for_review,
    publish,
)

MAX_FLOAT = Decimal("1000000")
TILL_VARIANCE = "till_variance"


def today(session: Session, company_id: UUID) -> date:
    """Today's trading date where the company is."""
    return company_today(session, company_id)


def business_day(session: Session, company_id: UUID, moment: datetime | None) -> date:
    """The company's calendar date of a moment (today when there is none)."""
    return company_date_of(session, company_id, moment) if moment is not None else company_today(session, company_id)


def company_of(session: Session, till: TillSession) -> UUID:
    company_id = pos_repo.branch_company(session, till.branch_id)
    if company_id is None:
        raise NotFound("Till not found")
    return company_id


def get_till(session: Session, till_id: UUID, *, lock: bool = False) -> TillSession:
    """A till session the user may see: their own, or any at a branch they review. Others read as not found."""
    till = pos_repo.get_till(session, till_id, lock=lock)
    if till is None:
        raise NotFound("Till not found")
    company_id = company_of(session, till)
    if till.cashier_id != current_context().user_id and not access.can_review(company_id, till.branch_id):
        raise NotFound("Till not found")
    return till


def list_tills(session: Session, *, branch_id: UUID | None = None, status: str | None = None,
               business_date: date | None = None, limit: int = 50, offset: int = 0) -> list[TillSession]:
    """Tills at the branches the user reviews, plus their own."""
    ctx = current_context()
    review = ctx.scopes_with("till.review")
    if review is None:
        return pos_repo.list_tills(session, None, branch_id=branch_id, status=status, business_date=business_date,
                                   cashier_id=None, limit=min(limit, 200), offset=offset)
    mine = pos_repo.list_tills(session, None, branch_id=branch_id, status=status, business_date=business_date,
                               cashier_id=ctx.user_id, limit=min(limit, 200), offset=offset)
    others = pos_repo.list_tills(session, review, branch_id=branch_id, status=status, business_date=business_date,
                                 cashier_id=None, limit=min(limit, 200), offset=offset) if review else []
    merged = {t.id: t for t in [*mine, *others]}
    return sorted(merged.values(), key=lambda t: t.opened_at, reverse=True)[:min(limit, 200)]


def open_till(session: Session, device_id: UUID, opening_float: Decimal, *, local_id: UUID | None = None,
              opened_at: datetime | None = None) -> tuple[TillSession, bool]:
    """Start the signed-in cashier's till session on a device. Returns (session, already_existed): a device that retries
    with the same `local_id` gets the session it opened the first time. Needs 'till.manage' at the branch."""
    ctx = current_context()
    device = devices.get_device(session, device_id, for_selling=True)
    company_id = pos_repo.branch_company(session, device.branch_id)
    if company_id is None:
        raise NotFound("Device not found")
    ctx.require(TILL_MANAGE, company_id=company_id, branch_id=device.branch_id)
    if ctx.user_id is None:
        raise Forbidden("A till is opened by a signed-in person")
    if local_id is not None:
        pos_repo.lock_key(session, f"pos.till:{local_id}")
        earlier = pos_repo.till_by_local_id(session, local_id)
        if earlier is not None:
            return earlier, True
    if device.status != "active":
        raise ValidationFailed("This device is blocked")
    if opening_float < 0 or opening_float > MAX_FLOAT or opening_float != opening_float.quantize(rules.CENT):
        raise ValidationFailed("The opening float is an amount of zero or more with at most 2 decimal places")
    day = business_day(session, company_id, opened_at)
    if day_is_locked(session, device.branch_id, day):
        day = today(session, company_id)
        if day_is_locked(session, device.branch_id, day):
            raise ValidationFailed(f"The day {day} is already closed for this branch")
    pos_repo.lock_key(session, f"pos.till.open:{ctx.user_id}")
    pos_repo.lock_key(session, f"pos.till.open:{device.id}")
    if pos_repo.open_till_of_device(session, device.id) is not None:
        raise Conflict("This device already has an open till: close it first")
    if pos_repo.open_till_of_user(session, ctx.user_id) is not None:
        raise Conflict("You already have an open till: close it first")
    till = TillSession(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, branch_id=device.branch_id, device_id=device.id,
        cash_account_id=cash_account_for_branch(session, company_id, device.branch_id), cashier_id=ctx.user_id,
        business_date=day, opened_at=opened_at or datetime.now(UTC), opening_float=opening_float, local_id=local_id)
    pos_repo.add(session, till)
    audit_record(session, "open", "pos.till_session", till.id, {"float": opening_float, "device": device.code})
    publish(session, Event("till.opened", "pos.till_session", till.id, {
        "company_id": company_id, "branch_id": device.branch_id, "business_date": day, "float": opening_float,
        "cashier_id": ctx.user_id}))
    return till, False


def report(session: Session, till: TillSession) -> dict[str, Any]:
    """The till's figures so far (the X report; when the till is closed, the Z report)."""
    figures = pos_repo.till_sale_figures(session, till.id)
    by_method = {m: Decimal(a) for m, a in figures["by_method"].items()}
    cash_sales = by_method.get("cash", Decimal(0))
    cash_net = cash_in_till_session(session, till.id)
    expected = rules.till_expected_cash(till.opening_float, cash_net)
    sales = figures["sales"]
    posted = sales.get("posted", {"count": 0, "total": Decimal(0), "tax": Decimal(0), "discount": Decimal(0)})
    voided = sales.get("voided", {"count": 0, "total": Decimal(0), "tax": Decimal(0), "discount": Decimal(0)})
    return {
        "till_session_id": till.id, "business_date": till.business_date, "status": till.status,
        "opening_float": till.opening_float, "sales_count": posted["count"], "sales_total": Decimal(posted["total"]),
        "tax_total": Decimal(posted["tax"]), "discount_total": Decimal(posted["discount"]),
        "voided_count": voided["count"], "voided_total": Decimal(voided["total"]),
        "takings_by_method": by_method, "cash_refunded": cash_sales - cash_net, "expected_cash": expected,
        "counted_cash": till.counted_cash, "variance": till.variance,
    }


def close_till(session: Session, till_id: UUID, counted_cash: Decimal, *, reason_code_id: UUID | None = None,
               note: str | None = None, closed_at: datetime | None = None, strict: bool = True) -> TillSession:
    """Count the drawer and close the session. Any difference from the expected cash needs a reason from the
    'till_variance' list (`strict=False`, for a device syncing offline, accepts the close and flags the missing reason
    instead). The cashier closes their own till; a reviewer may close any."""
    till = get_till(session, till_id, lock=True)
    company_id = company_of(session, till)
    ctx = current_context()
    if till.cashier_id != ctx.user_id and not access.can_review(company_id, till.branch_id):
        raise Forbidden("Only the cashier or a reviewer can close this till")
    if till.status != "open":
        raise Conflict("This till is already closed")
    if counted_cash < 0 or counted_cash > rules.MAX_PRICE or counted_cash != counted_cash.quantize(rules.CENT):
        raise ValidationFailed("The counted cash is an amount of zero or more with at most 2 decimal places")
    expected = rules.till_expected_cash(till.opening_float, cash_in_till_session(session, till.id))
    variance = counted_cash - expected
    missing_reason = False
    if variance != 0:
        if strict or reason_code_id is not None:
            check_reason(session, TILL_VARIANCE, reason_code_id, note)
        else:
            missing_reason = True
    till.status, till.closed_at = "closed", closed_at or datetime.now(UTC)
    till.expected_cash, till.counted_cash, till.variance = expected, counted_cash, variance
    till.variance_reason_code_id, till.closed_by = reason_code_id, ctx.user_id
    till.close_note = (note or "").strip() or None
    session.flush()
    till.report = jsonable_encoder(report(session, till))
    session.flush()
    audit_record(session, "close", "pos.till_session", till.id,
                 {"expected": expected, "counted": counted_cash, "variance": variance})
    publish(session, Event("till.closed", "pos.till_session", till.id, {
        "company_id": company_id, "branch_id": till.branch_id, "business_date": till.business_date,
        "variance": variance, "expected": expected, "counted": counted_cash, "cashier_id": till.cashier_id}))
    if variance != 0:
        what = "short" if variance < 0 else "over"
        flag_for_review(
            session, unit="pos", kind="till_variance", severity="medium", company_id=company_id,
            branch_id=till.branch_id, ref_type="till_session", ref_id=till.id, amount=variance,
            dedupe_key=f"till_variance:{till.id}",
            message=f"Till closed {abs(variance)} {what} (expected {expected}, counted {counted_cash})"
                    + (" - no reason was given" if missing_reason else ""))
    return till

"""HTTP endpoints for lockers, guest passes, vouchers and credit, points, measurements, trainers and the owner's
reports."""

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from ziira.modules.memberships.api import schemas_extras as xs
from ziira.modules.memberships.api.deps import ADJUST, CATALOGUE, REPORT, SEE, SERVE
from ziira.modules.memberships.services import common, dues, extras, reports, trainers, values
from ziira.sdk import DB_SESSION, Session, audit_record, page_limit, page_offset, to_csv

router = APIRouter()
CREATED = status.HTTP_201_CREATED


# --------------------------------------------------------------------------- lockers
@router.get("/lockers", response_model=list[xs.LockerOut], dependencies=SEE)
def get_lockers(company_id: UUID, branch_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),  # noqa: E501
                kind: str | None = None, session: Session = DB_SESSION) -> object:
    return extras.list_lockers(session, company_id=company_id, branch_id=branch_id, status=status_, kind=kind)


@router.post("/lockers", response_model=list[xs.LockerOut], status_code=CREATED, dependencies=SERVE)
def post_lockers(body: xs.LockersIn, session: Session = DB_SESSION) -> object:
    return extras.add_lockers(session, **body.model_dump())


@router.post("/lockers/{locker_id}/assign", response_model=xs.LockerOut, dependencies=SERVE)
def post_locker_assign(locker_id: UUID, body: xs.LockerAssignIn, session: Session = DB_SESSION) -> object:
    return extras.assign_locker(session, locker_id, **body.model_dump())


@router.post("/lockers/{locker_id}/release", response_model=xs.LockerOut, dependencies=SERVE)
def post_locker_release(locker_id: UUID, session: Session = DB_SESSION) -> object:
    return extras.release_locker(session, locker_id)


@router.post("/lockers/{locker_id}/out-of-service", response_model=xs.LockerOut, dependencies=SERVE)
def post_locker_out(locker_id: UUID, out: bool = True, session: Session = DB_SESSION) -> object:
    return extras.set_locker_out_of_service(session, locker_id, out)


# --------------------------------------------------------------------------- guests
@router.get("/members/{member_id}/guest-passes", response_model=xs.GuestPassesOut, dependencies=SEE)
def get_guest_passes(member_id: UUID, session: Session = DB_SESSION) -> object:
    return {"left": extras.guest_passes_left(session, common.get_row(session, "member", member_id, "Membership"))}


@router.get("/members/{member_id}/guests", response_model=list[xs.GuestOut], dependencies=SEE)
def get_guests(member_id: UUID, session: Session = DB_SESSION) -> object:
    return extras.guest_visits(session, member_id)


@router.post("/members/{member_id}/guests", response_model=xs.GuestOut, status_code=CREATED, dependencies=SERVE)
def post_guest(member_id: UUID, body: xs.GuestIn, session: Session = DB_SESSION) -> object:
    return extras.bring_guest(session, member_id, **body.model_dump())


# --------------------------------------------------------------------------- vouchers, credit, points
@router.get("/vouchers", response_model=list[xs.ValueAccountOut], dependencies=SEE)
def get_vouchers(company_id: UUID, kind: str | None = Query(default=None, pattern="^(gift|referral|promo|points)$"),
                 customer_id: UUID | None = None, active_only: bool = False, limit: int = page_limit(100),
                 offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return values.list_accounts(session, company_id=company_id, kind=kind, customer_id=customer_id,
                                active_only=active_only, limit=limit, offset=offset)


@router.post("/vouchers", response_model=xs.ValueAccountOut, status_code=CREATED, dependencies=SERVE)
def post_voucher(body: xs.VoucherSellIn, session: Session = DB_SESSION) -> object:
    return values.sell_voucher(session, **body.model_dump())


@router.get("/vouchers/lookup", response_model=xs.ValueAccountOut, dependencies=SEE)
def get_voucher_lookup(company_id: UUID, code: str = Query(min_length=3, max_length=30),
                       session: Session = DB_SESSION) -> object:
    common.check_visible(company_id, None, "Company")
    found = values.find_voucher(session, company_id, code)
    if found is None:
        from ziira.sdk import NotFound

        raise NotFound("That voucher code was not found")
    return values.get_account(session, found["id"])


@router.get("/vouchers/{account_id}", response_model=xs.ValueAccountOut, dependencies=SEE)
def get_voucher(account_id: UUID, session: Session = DB_SESSION) -> object:
    return values.get_account(session, account_id)


@router.get("/vouchers/{account_id}/ledger", response_model=list[xs.ValueEntryOut], dependencies=SEE)
def get_voucher_ledger(account_id: UUID, session: Session = DB_SESSION) -> object:
    return values.ledger(session, account_id)


@router.post("/vouchers/{account_id}/void", response_model=xs.ValueAccountOut, dependencies=ADJUST)
def post_voucher_void(account_id: UUID, body: xs.VoucherVoidIn, session: Session = DB_SESSION) -> object:
    return values.void_voucher(session, account_id, body.reason)


@router.post("/credits/give", response_model=xs.ValueAccountOut, status_code=CREATED, dependencies=ADJUST)
def post_credit_give(body: xs.CreditGiveIn, session: Session = DB_SESSION) -> object:
    """Give a customer credit by hand (a goodwill gesture, a promotion), applied to their next invoices."""
    return values.give_credit(session, **body.model_dump())


@router.get("/customers/{customer_id}/value", response_model=xs.CustomerValueOut, dependencies=SEE)
def get_customer_value(customer_id: UUID, session: Session = DB_SESSION) -> object:
    return values.summary(session, customer_id)


@router.post("/customers/{customer_id}/points/redeem", response_model=xs.ValueAccountOut, dependencies=SERVE)
def post_points_redeem(customer_id: UUID, body: xs.PointsRedeemIn, session: Session = DB_SESSION) -> object:
    return values.redeem_points(session, customer_id, body.points, note=body.note)


# --------------------------------------------------------------------------- measurements
@router.get("/customers/{customer_id}/measurements", response_model=list[xs.MeasurementOut], dependencies=SEE)
def get_measurements(customer_id: UUID, metric: str | None = Query(default=None, max_length=60),
                     session: Session = DB_SESSION) -> object:
    return extras.measurements(session, customer_id, metric)


@router.post("/customers/{customer_id}/measurements", response_model=xs.MeasurementOut, status_code=CREATED,
             dependencies=SERVE)
def post_measurement(customer_id: UUID, body: xs.MeasurementIn, session: Session = DB_SESSION) -> object:
    return extras.add_measurement(session, customer_id, **body.model_dump())


@router.delete("/measurements/{measurement_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=SERVE)
def delete_measurement(measurement_id: UUID, session: Session = DB_SESSION) -> Response:
    extras.delete_measurement(session, measurement_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- trainers
@router.get("/trainers/rates", response_model=list[xs.TrainerRateOut], dependencies=SEE)
def get_trainer_rates(company_id: UUID, session: Session = DB_SESSION) -> object:
    return trainers.list_rates(session, company_id)


@router.put("/trainers/rates", response_model=xs.TrainerRateOut, dependencies=CATALOGUE)
def put_trainer_rate(body: xs.TrainerRateIn, session: Session = DB_SESSION) -> object:
    return trainers.set_rate(session, **body.model_dump())


@router.get("/trainers/earnings", response_model=list[xs.TrainerEarningsOut], dependencies=REPORT)
def get_trainer_earnings(company_id: UUID, start: date | None = None, end: date | None = None,
                         session: Session = DB_SESSION) -> object:
    today = common.today(session, company_id)
    return trainers.earnings(session, company_id=company_id, start=start or today - timedelta(days=30),
                             end=end or today)


@router.get("/trainers/{trainer_ref}/earnings", response_model=list[xs.TrainerEarningRowOut], dependencies=REPORT)
def get_trainer_earning_rows(trainer_ref: UUID, company_id: UUID, start: date | None = None, end: date | None = None,
                             session: Session = DB_SESSION) -> object:
    today = common.today(session, company_id)
    return trainers.earning_rows(session, company_id=company_id, start=start or today - timedelta(days=30),
                                 end=end or today, trainer_ref=trainer_ref)


@router.post("/trainers/{trainer_ref}/mark-paid", response_model=xs.TrainerPaidOut, dependencies=CATALOGUE)
def post_trainer_paid(trainer_ref: UUID, company_id: UUID, body: xs.TrainerPaidIn,
                      session: Session = DB_SESSION) -> object:
    return {"rows": trainers.mark_paid(session, company_id=company_id, trainer_ref=trainer_ref, through=body.through)}


# --------------------------------------------------------------------------- reports and exports
@router.get("/reports/overview", response_model=xs.MembershipOwnerReportOut, dependencies=REPORT)
def get_report(company_id: UUID, start: xs.Day | None = None, end: xs.Day | None = None, branch_id: UUID | None = None,
               session: Session = DB_SESSION) -> object:
    """Active members, new and ended, monthly income, income at risk, retention, busy hours, money owed, holds,
    trials."""
    return reports.overview(session, company_id=company_id, start=start, end=end, branch_id=branch_id)


@router.get("/exports/{kind}", response_class=Response, responses={200: {"content": {"text/csv": {}}}},
            dependencies=REPORT)
def get_export(kind: str, company_id: UUID, session: Session = DB_SESSION) -> Response:
    """A spreadsheet (CSV) of the members or of who owes money. Every download is audited."""
    common.check_visible(company_id, None, "Company")
    if kind == "members":
        text = to_csv(reports.MEMBER_HEADER, reports.member_rows(session, company_id))
    elif kind == "arrears":
        rows = dues.arrears(session, company_id=company_id, min_days=0, limit=500)
        text = to_csv(["Customer", "Phone", "Email", "Owed", "Oldest due", "Days late", "Invoices"],
                      [[r["customer_name"], r["phone"], r["email"], r["owed"], r["oldest_due"], r["days_late"],
                        ", ".join(r["invoice_numbers"])] for r in rows])
    else:
        from ziira.sdk import NotFound

        raise NotFound("Export members or arrears")
    audit_record(session, "export", "memberships.report", None, {"kind": kind, "company": str(company_id)})
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{kind}-{common.today(session, company_id)}.csv"'})  # noqa: E501


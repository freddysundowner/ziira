"""The small things a gym sells and tracks besides the membership: lockers and towel rental (a recurring fee and a
deposit),
guest passes a member brings a friend with, and the measurements a member chooses to share with their trainer."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.memberships.permissions import MANAGE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import billing, common, invoicing, profiles, schedules
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
)

KINDS = ("locker", "towel", "other")


# --------------------------------------------------------------------------- lockers and rentals
def add_lockers(session: Session, *, company_id: UUID, branch_id: UUID, codes: list[str], kind: str = "locker",
                fee: Decimal = Decimal(0), deposit: Decimal = Decimal(0), billing_interval: str = "month",
                product_id: UUID | None = None) -> list[repo.Row]:
    """Add lockers (or towel sets) to a branch by their codes. The fee is the recurring rent; the deposit is charged
    once.
    Needs 'memberships.manage'."""
    common.require(MANAGE, company_id, branch_id)
    check_company(session, company_id, branch_id)
    if kind not in KINDS:
        raise ValidationFailed("A rental is a locker, a towel or something else")
    cleaned = []
    for code in codes:
        word = " ".join(code.split())[:30]
        if word and word not in cleaned:
            cleaned.append(word)
    if not cleaned or len(cleaned) > 500:
        raise ValidationFailed("Give between 1 and 500 codes")
    common.check_product(session, company_id, product_id)
    ctx = current_context()
    made: list[repo.Row] = []
    for code in cleaned:
        if repo.one(session, "select 1 as x from memberships.locker where branch_id = :b and code = :c",
                    b=branch_id, c=code) is not None:
            raise Conflict(f"There is already a {code} at this branch")
        made.append(repo.insert(session, "locker", {
            "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "branch_id": branch_id,
            "code": code, "kind": kind, "fee": fee, "deposit": deposit, "billing_interval": billing_interval,
            "product_id": product_id}))
    audit_record(session, "add", "memberships.locker", made[0]["id"], {"count": len(made), "kind": kind})
    return made


def list_lockers(session: Session, *, company_id: UUID, branch_id: UUID | None = None, status: str | None = None,
                 kind: str | None = None) -> list[repo.Row]:
    clause, params = repo.scope_sql(common.view_scopes(), "l")
    rows = repo.many(
        session,
        f"select l.* from memberships.locker l where {clause} and l.company_id = :c "
        "and (cast(:b as uuid) is null or l.branch_id = :b) and (cast(:s as text) is null or l.status = :s) "
        "and (cast(:k as text) is null or l.kind = :k) order by l.branch_id, l.kind, l.code limit 1000",
        c=company_id, b=branch_id, s=status, k=kind, **params)
    names = common.customer_names(session, {r["customer_id"] for r in rows if r["customer_id"]})
    return [{**r, "customer_name": names[r["customer_id"]].name if r["customer_id"] in names else None} for r in rows]


def assign_locker(session: Session, locker_id: UUID, *, customer_id: UUID, start_date: date | None = None) -> repo.Row:
    """Give a locker to a customer: the deposit is invoiced once and the fee on a recurring invoice from the start date.
    Needs 'memberships.manage'."""
    locker = common.get_row(session, "locker", locker_id, "Locker", lock=True)
    common.require(MANAGE, locker["company_id"], locker["branch_id"])
    if locker["status"] != "free":
        raise Conflict("This locker is not free")
    common.customer_of(session, locker["company_id"], customer_id)
    today = common.today(session, locker["company_id"])
    start = start_date or today
    schedule_id = None
    needs_bill = (locker["fee"] > 0 or locker["deposit"] > 0)
    if needs_bill and (locker["product_id"] is None or not invoicing.available(session)):
        raise ValidationFailed("The rent cannot be invoiced: the locker needs a service item to invoice it as, and "
                               "Point of Sale and Invoices must be on")
    payer = profiles.billing_customer_of(session, customer_id) or customer_id
    if locker["fee"] > 0:
        schedule = schedules.make_schedule(
            session, company_id=locker["company_id"], branch_id=locker["branch_id"], customer_id=payer,
            name=f"{locker['kind'].title()} {locker['code']}",
            lines=[{"product_id": locker["product_id"], "description": f"{locker['kind'].title()} {locker['code']}",
                    "quantity": "1", "unit_price": str(locker["fee"])}],
            billing_interval=locker["billing_interval"], start_date=start, for_customer_id=customer_id,
            for_label=f"{locker['kind']} {locker['code']}")
        schedule_id = schedule["id"]
    deposit_run = None
    if locker["deposit"] > 0:
        run = billing.bill_period(
            session, owner_type="rental", owner_id=locker_id, company_id=locker["company_id"],
            branch_id=locker["branch_id"], customer_id=payer, period_start=start, period_end=None,
            lines=[{"product_id": str(locker["product_id"]), "description": f"Deposit, {locker['kind']} "
                    f"{locker['code']}", "quantity": "1", "unit_price": str(locker["deposit"]), "discount": "0"}],
            due_days=None, memo=f"Deposit {locker['code']}", raise_on_error=True, credit_eligible=False,
            for_customer_id=customer_id, for_label=f"{locker['kind']} {locker['code']}")
        deposit_run = run["id"]
    saved = repo.update(session, "locker", locker_id, {
        "status": "assigned", "customer_id": customer_id, "assigned_on": start, "schedule_id": schedule_id,
        "deposit_run_id": deposit_run})
    audit_record(session, "assign", "memberships.locker", locker_id, {"customer": str(customer_id)})
    return saved


def release_locker(session: Session, locker_id: UUID) -> repo.Row:
    """Take a locker back: the recurring rent ends. The deposit is given back with a credit note or refund in Sales (see
    the invoice run). Needs 'memberships.manage'."""
    locker = common.get_row(session, "locker", locker_id, "Locker", lock=True)
    common.require(MANAGE, locker["company_id"], locker["branch_id"])
    if locker["status"] != "assigned":
        raise Conflict("This locker is not in use")
    if locker["schedule_id"] is not None:
        repo.update(session, "schedule", locker["schedule_id"], {"status": "ended", "resume_on": None})
    saved = repo.update(session, "locker", locker_id, {"status": "free", "customer_id": None, "assigned_on": None,
                                                       "schedule_id": None})
    audit_record(session, "release", "memberships.locker", locker_id, {"customer": str(locker["customer_id"])})
    return {**saved, "deposit_run_id": locker["deposit_run_id"]}


def set_locker_out_of_service(session: Session, locker_id: UUID, out: bool) -> repo.Row:
    locker = common.get_row(session, "locker", locker_id, "Locker", lock=True)
    common.require(MANAGE, locker["company_id"], locker["branch_id"])
    if locker["status"] == "assigned":
        raise Conflict("Take the locker back first")
    return repo.update(session, "locker", locker_id, {"status": "out_of_service" if out else "free"})


# --------------------------------------------------------------------------- guest passes
def guest_passes_left(session: Session, member: repo.Row) -> int:
    plan = repo.get(session, "plan", member["plan_id"]) or {}
    allowed = int(plan.get("guest_passes_per_period") or 0)
    used = int(repo.scalar(session, "select count(*) from memberships.guest_visit where host_member_id = :m "
                                    "and period_start = :p", m=member["id"], p=member["current_period_start"]))
    return max(allowed - used, 0)


def bring_guest(session: Session, member_id: UUID, *, guest_name: str, guest_phone: str | None = None,
                branch_id: UUID | None = None, note: str | None = None, capture_lead: bool = True) -> repo.Row:
    """A member brings a friend in with one of the guest passes their plan gives each period. The guest becomes an
    enquiry
    (a lead) when they leave a phone number. Needs 'memberships.manage'."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], branch_id or member["branch_id"])
    if member["status"] != "active":
        raise Conflict("Only an active membership can bring a guest")
    name = " ".join(guest_name.split())[:200]
    if not name:
        raise ValidationFailed("Give the guest's name")
    if guest_passes_left(session, member) <= 0:
        raise ValidationFailed("No guest passes are left this period")
    lead_id = None
    if capture_lead and guest_phone and guest_phone.strip():
        from ziira.modules.crm.public import capture_lead as crm_capture

        try:
            with session.begin_nested():
                lead_id = crm_capture(session, member["company_id"], name=name, phone=guest_phone,
                                      source_name="Guest of a member").id
        except Exception:  # noqa: BLE001 - a lead that cannot be saved must not stop the guest coming in
            lead_id = None
    where = branch_id or member["branch_id"]
    check_company(session, member["company_id"], where)
    ctx = current_context()
    visit = repo.insert(session, "guest_visit", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": member["company_id"],
        "branch_id": where, "host_member_id": member_id, "host_customer_id": member["customer_id"],
        "guest_name": name, "guest_phone": (guest_phone or "").strip()[:40] or None,
        "visited_on": common.today(session, member["company_id"]), "period_start": member["current_period_start"],
        "lead_id": lead_id, "note": (note or "").strip()[:300] or None})
    audit_record(session, "guest", "memberships.member", member_id, {"guest": name})
    return visit


def guest_visits(session: Session, member_id: UUID) -> list[repo.Row]:
    common.get_row(session, "member", member_id, "Membership")
    return repo.many(session, "select * from memberships.guest_visit where host_member_id = :m "
                              "order by visited_on desc, created_at desc limit 100", m=member_id)


# --------------------------------------------------------------------------- measurements the member shares
def add_measurement(session: Session, customer_id: UUID, *, metric: str, value: Decimal, taken_on: date | None = None,
                    unit: str | None = None, note: str | None = None) -> repo.Row:
    """Record a figure the member shared with their trainer (weight, waist, a lift). Not a medical record. Needs
    'memberships.manage'."""
    customer = common.customer_of_any(session, customer_id)
    common.require_in_company(MANAGE, customer.company_id)
    label = " ".join(metric.split()).lower()[:60]
    if not label:
        raise ValidationFailed("Say what was measured")
    ctx = current_context()
    row = repo.insert(session, "measurement", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": customer.company_id,
        "customer_id": customer_id, "taken_on": taken_on or common.today(session, customer.company_id),
        "metric": label, "value": value, "unit": (unit or "").strip()[:20] or None,
        "note": (note or "").strip()[:300] or None})
    audit_record(session, "measure", "memberships.measurement", row["id"], {"metric": label})
    return row


def measurements(session: Session, customer_id: UUID, metric: str | None = None) -> list[repo.Row]:
    customer = common.customer_of_any(session, customer_id)
    common.check_visible(customer.company_id, None, "Member")
    return repo.many(session, "select * from memberships.measurement where customer_id = :c "
                              "and (cast(:m as text) is null or metric = :m) order by taken_on desc, created_at desc "
                              "limit 500", c=customer_id, m=metric.lower() if metric else None)


def delete_measurement(session: Session, measurement_id: UUID) -> None:
    """A member may ask for a figure to be removed. Needs 'memberships.manage'."""
    row = repo.get(session, "measurement", measurement_id)
    if row is None:
        raise NotFound("Measurement not found")
    common.check_visible(row["company_id"], None, "Measurement")
    common.require_in_company(MANAGE, row["company_id"])
    repo.run(session, "delete from memberships.measurement where id = :i", i=measurement_id)
    audit_record(session, "delete", "memberships.measurement", measurement_id, {})

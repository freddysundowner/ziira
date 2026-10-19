"""Value a customer holds besides visits: gift vouchers (a code anyone can use), referral and promo credit, and loyalty
points. One immutable ledger (`value_entry`); a balance is the sum of its entries.

Value is spent on an invoice this unit makes (a membership period, a package, a voucher is not paid for with a voucher)
as a discount on its lines, and other units can spend it through `public.py`. Spending is idempotent by
(`source_type`, `source_id`); releasing the source gives it back with a reversal entry."""

import secrets
import uuid
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import UUID

from ziira.modules.memberships.permissions import CREDITS, MANAGE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, invoicing, profiles
from ziira.sdk import (
    Conflict,
    Event,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    publish,
)

ZERO = Decimal(0)
CENT = Decimal("0.01")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # no 0/O/1/I: read aloud and typed by hand
NAMESPACE = uuid.UUID("5f1c0a7e-0000-4000-8000-6d656d626572")


def _code() -> str:
    return "GV-" + "".join(secrets.choice(ALPHABET) for _ in range(10))


def balance_of(session: Session, account_id: UUID) -> Decimal:
    return Decimal(repo.scalar(session, "select coalesce(sum(quantity), 0) from memberships.value_entry "
                                        "where account_id = :a", a=account_id))


def _entry(session: Session, account: repo.Row, entry_type: str, quantity: Decimal, *, source_type: str | None = None,
           source_id: UUID | None = None, reverses_id: UUID | None = None, note: str | None = None,
           day: date | None = None) -> repo.Row:
    ctx = current_context()
    return repo.insert(session, "value_entry", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": account["company_id"],
        "account_id": account["id"], "entry_type": entry_type, "quantity": quantity, "source_type": source_type,
        "source_id": source_id, "reverses_id": reverses_id, "note": (note or "").strip()[:300] or None,
        "business_date": day or common.today(session, account["company_id"])})


def _with_balance(session: Session, rows: list[repo.Row]) -> list[repo.Row]:
    if not rows:
        return []
    found: dict[UUID, Decimal] = {r["id"]: ZERO for r in rows}
    for r in repo.many(session, "select account_id, sum(quantity) as b from memberships.value_entry "
                                "where account_id = any(cast(:ids as uuid[])) group by account_id",
                       ids=[str(r["id"]) for r in rows]):
        found[r["account_id"]] = Decimal(r["b"])
    names = common.customer_names(session, {r["customer_id"] for r in rows if r.get("customer_id")}
                                  | {r["purchaser_customer_id"] for r in rows if r.get("purchaser_customer_id")})
    return [{**r, "balance": found[r["id"]],
             "customer_name": names[r["customer_id"]].name if r.get("customer_id") in names else None,
             "purchaser_name": names[r["purchaser_customer_id"]].name
             if r.get("purchaser_customer_id") in names else None} for r in rows]


# --------------------------------------------------------------------------- accounts
def list_accounts(session: Session, *, company_id: UUID, kind: str | None = None, customer_id: UUID | None = None,
                  active_only: bool = False, limit: int = 100, offset: int = 0) -> list[repo.Row]:
    common.check_visible(company_id, None, "Company")
    rows = repo.many(
        session,
        "select * from memberships.value_account where company_id = :c and (cast(:k as text) is null or kind = :k) "
        "and (cast(:cu as uuid) is null or customer_id = :cu or purchaser_customer_id = :cu) "
        "and (not :a or status = 'active') order by created_at desc limit :l offset :o",
        c=company_id, k=kind, cu=customer_id, a=active_only, l=min(limit, 200), o=offset)
    return _with_balance(session, rows)


def get_account(session: Session, account_id: UUID) -> repo.Row:
    return _with_balance(session, [common.get_row(session, "value_account", account_id, "Voucher")])[0]


def ledger(session: Session, account_id: UUID, limit: int = 100) -> list[repo.Row]:
    common.get_row(session, "value_account", account_id, "Voucher")
    return repo.many(session, "select * from memberships.value_entry where account_id = :a order by seq desc limit :l",
                     a=account_id, l=min(limit, 500))


def find_voucher(session: Session, company_id: UUID, code: str) -> repo.Row | None:
    return repo.one(session, "select * from memberships.value_account where company_id = :c and code = :k",
                    c=company_id, k=code.strip().upper())


def sell_voucher(session: Session, *, company_id: UUID, branch_id: UUID, amount: Decimal,
                 purchaser_customer_id: UUID | None = None, recipient_customer_id: UUID | None = None,
                 expires_on: date | None = None, note: str | None = None, invoice: bool | None = None) -> repo.Row:
    """Sell a gift voucher worth `amount`: a code anyone can spend. The sale is invoiced to the purchaser when there is
    one and invoices are on (the company's voucher service item in Settings). Needs 'memberships.manage'."""
    common.require(MANAGE, company_id, branch_id)
    check_company(session, company_id, branch_id)
    if amount <= 0 or amount != amount.quantize(CENT):
        raise ValidationFailed("A voucher is worth more than zero, with at most 2 decimal places")
    today = common.today(session, company_id)
    if expires_on is not None and expires_on <= today:
        raise ValidationFailed("The expiry date must be in the future")
    if purchaser_customer_id is not None:
        common.customer_of(session, company_id, purchaser_customer_id)
    if recipient_customer_id is not None:
        common.customer_of(session, company_id, recipient_customer_id)
    settings = repo.get_settings(session, company_id)
    can_bill = purchaser_customer_id is not None and settings["voucher_product_id"] is not None \
        and invoicing.available(session)
    if invoice and not can_bill:
        raise ValidationFailed("The voucher cannot be invoiced: name the purchaser, set the voucher service item in "
                               "Settings, and switch on Point of Sale and Invoices")
    bill = can_bill if invoice is None else bool(invoice) and can_bill
    ctx = current_context()
    for _ in range(5):
        code = _code()
        if find_voucher(session, company_id, code) is None:
            break
    account = repo.insert(session, "value_account", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "kind": "gift",
        "customer_id": recipient_customer_id, "purchaser_customer_id": purchaser_customer_id, "code": code,
        "initial": amount, "expires_on": expires_on, "note": (note or "").strip()[:300] or None})
    _entry(session, account, "issue", amount, source_type="sale", source_id=account["id"], note="Voucher sold")
    if bill:
        from ziira.modules.memberships.services import billing

        billing.bill_period(
            session, owner_type="voucher", owner_id=account["id"], company_id=company_id, branch_id=branch_id,
            customer_id=purchaser_customer_id, period_start=today, period_end=None,  # type: ignore[arg-type]
            lines=[{"product_id": str(settings["voucher_product_id"]), "description": f"Gift voucher {code}",
                    "quantity": "1", "unit_price": str(amount), "discount": "0"}],
            due_days=None, memo=f"Gift voucher {code}", raise_on_error=True, credit_eligible=False)
    audit_record(session, "sell", "memberships.value_account", account["id"], {"amount": str(amount), "code": code})
    publish(session, Event("voucher.sold", "memberships.value_account", account["id"], {
        "company_id": company_id, "branch_id": branch_id, "amount": amount, "purchaser": purchaser_customer_id}))
    return _with_balance(session, [account])[0]


def void_voucher(session: Session, account_id: UUID, reason: str) -> repo.Row:
    """Cancel a voucher: what is left is removed. Money already received goes back through a credit note in Sales.
    Needs 'memberships.credits'."""
    account = repo.get(session, "value_account", account_id, lock=True)
    if account is None:
        raise ValidationFailed("Voucher not found")
    common.check_visible(account["company_id"], None, "Voucher")
    common.require_in_company(CREDITS, account["company_id"])
    if account["status"] != "active":
        raise Conflict("Only an active voucher can be cancelled")
    if not reason.strip():
        raise ValidationFailed("Say why the voucher is cancelled")
    left = balance_of(session, account_id)
    if left > 0:
        _entry(session, account, "adjustment", -left, note=reason)
    saved = repo.update(session, "value_account", account_id, {"status": "void"})
    audit_record(session, "void", "memberships.value_account", account_id, {"left": str(left), "reason": reason})
    return _with_balance(session, [saved])[0]


def grant_credit(session: Session, *, company_id: UUID, customer_id: UUID, amount: Decimal, kind: str, note: str,
                 source_type: str | None = None, source_id: UUID | None = None,
                 expires_on: date | None = None) -> repo.Row:
    """Give a customer credit (referral or promo): applied to their next invoices from here. The caller has checked
    permission. A repeat of the same (source_type, source_id) returns the first and changes nothing."""
    if kind not in ("referral", "promo"):
        raise ValidationFailed("Credit is referral or promo")
    if amount <= 0:
        raise ValidationFailed("Credit is more than zero")
    if source_type and source_id:
        found = repo.one(session, "select a.* from memberships.value_account a join memberships.value_entry e "
                                  "on e.account_id = a.id where e.source_type = :t and e.source_id = :s "
                                  "and e.entry_type = 'issue' and a.company_id = :c", t=source_type, s=source_id,
                         c=company_id)
        if found is not None:
            return found
    ctx = current_context()
    account = repo.insert(session, "value_account", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "kind": kind,
        "customer_id": customer_id, "initial": amount, "expires_on": expires_on, "note": note[:300]})
    _entry(session, account, "issue", amount, source_type=source_type, source_id=source_id, note=note)
    audit_record(session, "grant", "memberships.value_account", account["id"],
                 {"kind": kind, "amount": str(amount), "customer": str(customer_id)})
    return account


def give_credit(session: Session, *, customer_id: UUID, amount: Decimal, note: str, kind: str = "promo") -> repo.Row:
    """Staff give a customer credit by hand, with a note. Needs 'memberships.credits'."""
    customer = common.customer_of_any(session, customer_id)
    common.require_in_company(CREDITS, customer.company_id)
    if not note.strip():
        raise ValidationFailed("Say why the credit is given")
    return _with_balance(session, [grant_credit(session, company_id=customer.company_id, customer_id=customer_id,
                                                amount=amount, kind=kind, note=note.strip())])[0]


def reward_referrer(session: Session, profile: repo.Row) -> None:
    """When a referred person starts their first paid membership, the person who referred them gets the company's
    referral reward as credit (once per referred member)."""
    referrer = profile.get("referred_by_customer_id")
    if not referrer:
        return
    reward = Decimal(repo.get_settings(session, profile["company_id"])["referral_reward"])
    if reward <= 0:
        return
    grant_credit(session, company_id=profile["company_id"], customer_id=referrer, amount=reward, kind="referral",
                 note=f"Referral: member {profile['number']} joined", source_type="referral", source_id=profile["id"])


# --------------------------------------------------------------------------- spending
def usable_accounts(session: Session, company_id: UUID, customer_id: UUID, day: date) -> list[repo.Row]:
    """The customer's referral and promo credit and gift vouchers sent to them, soonest to expire first."""
    return repo.many(
        session,
        "select * from memberships.value_account where company_id = :c and customer_id = :cu "
        "and kind in ('referral', 'promo', 'gift') and status = 'active' and (expires_on is null or expires_on >= :d) "
        "order by expires_on nulls last, created_at, id", c=company_id, cu=customer_id, d=day)


def redeem(session: Session, account_id: UUID, amount: Decimal, *, source_type: str, source_id: UUID,
           note: str | None = None) -> Decimal:
    """Spend up to `amount` from one account. Idempotent by (source_type, source_id): asking again returns what the
    first
    request spent. Returns the amount spent (less than asked when the balance is lower). The caller has checked
    access."""
    account = repo.get(session, "value_account", account_id, lock=True)
    if account is None or account["status"] != "active":
        raise ValidationFailed("That voucher or credit cannot be used")
    standing = repo.one(session, "select coalesce(sum(-quantity), 0) as s from memberships.value_entry e "
                                "where e.account_id = :a and e.entry_type = 'redeem' and e.source_type = :t "
                                "and e.source_id = :s and not exists (select 1 from memberships.value_entry r "
                                "where r.reverses_id = e.id)", a=account_id, t=source_type, s=source_id)
    if standing and Decimal(standing["s"]) > 0:
        return Decimal(standing["s"])
    day = common.today(session, account["company_id"])
    if account["expires_on"] is not None and account["expires_on"] < day:
        raise ValidationFailed("That voucher or credit has expired")
    spend = min(amount, balance_of(session, account_id))
    if spend <= 0:
        return ZERO
    _entry(session, account, "redeem", -spend, source_type=source_type, source_id=source_id, note=note)
    if balance_of(session, account_id) <= 0:
        repo.update(session, "value_account", account_id, {"status": "used"})
    audit_record(session, "redeem", "memberships.value_account", account_id,
                 {"amount": str(spend), "source": source_type})
    return spend


def release(session: Session, *, source_type: str, source_id: UUID) -> Decimal:
    """Give back everything spent for a source (the invoice was thrown away, the order cancelled). Once only."""
    total = ZERO
    for entry in repo.many(
            session,
            "select e.*, exists(select 1 from memberships.value_entry r where r.reverses_id = e.id) as reversed "
            "from memberships.value_entry e where e.entry_type = 'redeem' and e.source_type = :t "
            "and e.source_id = :s order by e.seq", t=source_type, s=source_id):
        if entry["reversed"]:
            continue
        account = repo.get(session, "value_account", entry["account_id"], lock=True)
        assert account is not None
        _entry(session, account, "reversal", -entry["quantity"], source_type=source_type, source_id=source_id,
               reverses_id=entry["id"], note="Released")
        if account["status"] == "used":
            repo.update(session, "value_account", account["id"], {"status": "active"})
        total += -entry["quantity"]
    return total


def apply_credit_to_lines(session: Session, *, company_id: UUID, customer_id: UUID, lines: list[dict[str, str]],
                          source_id: UUID, period_start: date, voucher_code: str | None = None,
                          source_type: str = "memberships.run") -> list[dict[str, str]]:
    """Use a gift voucher the payer named, and (when the company allows) the credit the payer holds, to reduce the
    invoice lines: the discount is taken from the lines in order and recorded as spent against `source_id`. Returns the
    lines with their discounts."""
    day = common.today(session, company_id)
    wanted: list[repo.Row] = []
    if voucher_code:
        voucher = find_voucher(session, company_id, voucher_code)
        if voucher is None or voucher["status"] != "active":
            raise ValidationFailed("That gift voucher code is not valid")
        wanted.append(voucher)
    if repo.get_settings(session, company_id)["auto_apply_credit"]:
        wanted += [a for a in usable_accounts(session, company_id, customer_id, day)
                   if a["id"] not in {w["id"] for w in wanted}]
    if not wanted:
        return lines
    out = [dict(x) for x in lines]
    room = [(Decimal(x["quantity"]) * Decimal(x["unit_price"]) - Decimal(x.get("discount") or 0)).quantize(CENT)
            for x in out]
    for account in wanted:
        if sum(room) <= 0:
            break
        spent = redeem(session, account["id"], sum(room, ZERO), source_type=source_type, source_id=source_id,
                       note=f"Used on the invoice for the period starting {period_start}")
        for i, line in enumerate(out):
            if spent <= 0:
                break
            take = min(spent, room[i])
            if take > 0:
                line["discount"] = str(Decimal(line.get("discount") or 0) + take)
                room[i] -= take
                spent -= take
    return out


# --------------------------------------------------------------------------- loyalty points
def points_account(session: Session, company_id: UUID, customer_id: UUID, *, create: bool = False) -> repo.Row | None:
    found = repo.one(session, "select * from memberships.value_account where company_id = :c and customer_id = :cu "
                              "and kind = 'points'", c=company_id, cu=customer_id)
    if found is None and create:
        ctx = current_context()
        found = repo.insert(session, "value_account", {
            "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "kind": "points",
            "customer_id": customer_id, "initial": 0, "note": "Loyalty points"})
    return found


def points_balance(session: Session, customer_id: UUID) -> Decimal:
    customer = common.customer_of_any(session, customer_id)
    account = points_account(session, customer.company_id, customer_id)
    return balance_of(session, account["id"]) if account else ZERO


def earn_points(session: Session, *, company_id: UUID, customer_id: UUID, amount_paid: Decimal, source_type: str,
                source_id: UUID) -> Decimal:
    """Points for money a customer paid: the company's points per currency unit, rounded down. Once per source."""
    rate = Decimal(repo.get_settings(session, company_id)["points_per_unit"])
    points = (amount_paid * rate).quantize(Decimal(1), rounding=ROUND_DOWN)
    if rate <= 0 or points <= 0:
        return ZERO
    account = points_account(session, company_id, customer_id, create=True)
    assert account is not None
    if repo.one(session, "select 1 as x from memberships.value_entry where account_id = :a and entry_type = 'earn' "
                        "and source_type = :t and source_id = :s", a=account["id"], t=source_type, s=source_id):
        return ZERO
    _entry(session, account, "earn", points, source_type=source_type, source_id=source_id)
    return points


def redeem_points(session: Session, customer_id: UUID, points: Decimal, *, note: str | None = None) -> repo.Row:
    """Turn points into credit at the company's value per point; the credit is applied to the next invoices. Needs
    'memberships.manage'."""
    customer = common.customer_of_any(session, customer_id)
    common.require_in_company(MANAGE, customer.company_id)
    value = Decimal(repo.get_settings(session, customer.company_id)["point_value"])
    if value <= 0:
        raise ValidationFailed("Points have no value yet: set the value of a point in the policies")
    account = points_account(session, customer.company_id, customer_id)
    if account is None or points <= 0 or points != points.quantize(Decimal(1)):
        raise ValidationFailed("Redeem a whole number of points")
    locked = repo.get(session, "value_account", account["id"], lock=True)
    assert locked is not None
    if balance_of(session, account["id"]) < points:
        raise ValidationFailed("The member has fewer points than that")
    source = uuid.uuid4()
    _entry(session, locked, "redeem", -points, source_type="points_redeem", source_id=source, note=note)
    credit = grant_credit(session, company_id=customer.company_id, customer_id=customer_id,
                          amount=(points * value).quantize(CENT), kind="promo", note=f"{points:g} points redeemed",
                          source_type="points_redeem", source_id=source)
    return _with_balance(session, [credit])[0]


def expiring_vouchers(session: Session, company_id: UUID, today: date, days: int = 30) -> list[repo.Row]:
    return repo.many(session, "select * from memberships.value_account where company_id = :c and status = 'active' "
                              "and kind = 'gift' and expires_on between :t and :u order by expires_on",
                     c=company_id, t=today, u=today + timedelta(days=days))


def expire_due(session: Session, company_id: UUID, today: date) -> int:
    """Close vouchers and credit whose date has passed; what was left is written off with an 'expiry' entry."""
    due = repo.many(session, "select * from memberships.value_account where company_id = :c and status = 'active' "
                             "and expires_on is not null and expires_on < :d and kind <> 'points' for update",
                    c=company_id, d=today)
    for account in due:
        left = balance_of(session, account["id"])
        if left > 0:
            _entry(session, account, "expiry", -left, day=account["expires_on"], note="Expired")
        repo.update(session, "value_account", account["id"], {"status": "expired"})
    return len(due)


def summary(session: Session, customer_id: UUID) -> dict[str, Any]:
    """What a customer holds in credit, vouchers and points."""
    customer = common.customer_of_any(session, customer_id)
    common.check_visible(customer.company_id, None, "Customer")
    day = common.today(session, customer.company_id)
    accounts = _with_balance(session, usable_accounts(session, customer.company_id, customer_id, day))
    return {"customer_id": customer_id, "credit": sum((a["balance"] for a in accounts), ZERO), "accounts": accounts,
            "points": points_balance(session, customer_id)}


def for_profile(session: Session, customer_id: UUID) -> dict[str, Any]:
    profiles.profile_of_customer(session, customer_id)
    return summary(session, customer_id)

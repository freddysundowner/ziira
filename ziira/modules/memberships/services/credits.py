"""The credits ledger: spending, releasing and adjusting the credits of memberships and packages.

Every change is an immutable entry in `memberships.credit_entry`; a balance is the sum of its entries. Spending credits
for a source (an appointment, a job line) is idempotent: asking again for the same (source_type, source_id) while the
first use stands returns the first result and changes nothing. Releasing the source gives the credits back with reversal
entries; the same source may then spend again."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.memberships.domain import credits as rules
from ziira.modules.memberships.permissions import CREDITS
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common
from ziira.sdk import Event, Session, ValidationFailed, audit_record, current_context, publish

ZERO = Decimal(0)
MEMBERSHIP, PACKAGE = rules.MEMBERSHIP, rules.PACKAGE


@dataclass(frozen=True)
class CreditUse:
    """What spending credits for a service came to. `remaining` is still to be paid another way (at the member's
    `discount_percent` on services); `covered_by` lists (holder type, holder id, quantity) of each credit used."""

    covered: Decimal
    remaining: Decimal
    discount_percent: Decimal = ZERO
    covered_by: list[tuple[str, UUID, Decimal]] = field(default_factory=list)
    replayed: bool = False


def _lock_key(session: Session, source_type: str, source_id: UUID) -> None:
    repo.scalar(session, "select cast(pg_advisory_xact_lock(hashtextextended(:k, 0)) as text)",
                k=f"credit:{source_type}:{source_id}")


def holders(session: Session, customer_id: UUID, day: date, *, lock: bool = False) -> list[rules.Holder]:
    """The credit sources the customer can spend today: active memberships and unexpired active packages."""
    suffix = " for update" if lock else ""
    members = repo.many(session, "select id, covered_services from memberships.member where customer_id = :c "
                                 f"and status = 'active' order by id{suffix}", c=customer_id)
    packages = repo.many(session, "select id, covered_services, expires_on from memberships.sold_package "
                                  "where customer_id = :c and status = 'active' and (expires_on is null "
                                  f"or expires_on >= :d) order by id{suffix}", c=customer_id, d=day)
    balance = repo.balances(session, [r["id"] for r in members + packages])
    return ([rules.Holder(str(r["id"]), MEMBERSHIP, balance[r["id"]], tuple(r["covered_services"]), None)
             for r in members]
            + [rules.Holder(str(r["id"]), PACKAGE, balance[r["id"]], tuple(r["covered_services"]), r["expires_on"])
               for r in packages])


def member_discount(session: Session, customer_id: UUID) -> Decimal:
    """The highest discount on services among the customer's active memberships (0 if none)."""
    return Decimal(repo.scalar(session, "select coalesce(max(discount_percent), 0) from memberships.member "
                                        "where customer_id = :c and status = 'active'", c=customer_id))


def consume(session: Session, *, customer_id: UUID, service_ref: str | None, quantity: Decimal, source_type: str,
            source_id: UUID) -> CreditUse:
    """Pay `quantity` of a service with the customer's credits, once per source. The caller has already checked its own
    permission. Membership credits go first, then the package that expires soonest; what no credit covers is `remaining`
    (nothing is ever taken below zero unless the company allows overdraw)."""
    if quantity <= ZERO:
        raise ValidationFailed("The quantity must be above zero")
    if not source_type.strip():
        raise ValidationFailed("Say what the credits are spent on")
    customer = common.customer_of_any(session, customer_id)
    _lock_key(session, source_type, source_id)
    discount = member_discount(session, customer_id)
    standing = [e for e in repo.used_entries(session, source_type, source_id)
                if e["customer_id"] == customer_id and not e["reversed"]]
    if standing:
        covered = -sum((e["quantity"] for e in standing), ZERO)
        return CreditUse(covered, max(quantity - covered, ZERO), discount,
                         [(e["holder_type"], e["holder_id"], -e["quantity"]) for e in standing], replayed=True)
    day = common.today(session, customer.company_id)
    settings = repo.get_settings(session, customer.company_id)
    available = holders(session, customer_id, day, lock=True)
    kinds = {h.id: h.kind for h in available}
    takes, remaining = rules.allocate(available, quantity, service_ref, overdraw=bool(settings["allow_overdraw"]))
    ctx = current_context()
    used: list[tuple[str, UUID, Decimal]] = []
    for take in takes:
        kind = kinds[take.holder_id]
        repo.add_entry(session, ctx.tenant_id, ctx.user_id, {
            "company_id": customer.company_id, "customer_id": customer_id, "holder_type": kind,
            "holder_id": UUID(take.holder_id), "entry_type": "use", "quantity": -take.quantity,
            "service_ref": service_ref, "source_type": source_type, "source_id": source_id, "business_date": day})
        used.append((kind, UUID(take.holder_id), take.quantity))
        if kind == PACKAGE:
            publish(session, Event("package.used", "memberships.sold_package", UUID(take.holder_id), {
                "company_id": customer.company_id, "customer_id": customer_id, "quantity": take.quantity,
                "service_ref": service_ref, "source_type": source_type, "source_id": source_id,
                "balance": repo.holder_balance(session, UUID(take.holder_id))}))
    if used:
        audit_record(session, "consume", "memberships.credit", source_id,
                     {"customer_id": str(customer_id), "covered": str(quantity - remaining), "source": source_type})
    return CreditUse(quantity - remaining, remaining, discount, used)


def release(session: Session, *, source_type: str, source_id: UUID) -> Decimal:
    """Give back the credits spent for a source (an appointment cancelled after it was completed, a job line removed).
    Returns how much came back; nothing happens twice."""
    _lock_key(session, source_type, source_id)
    ctx = current_context()
    total = ZERO
    for entry in repo.used_entries(session, source_type, source_id):
        if entry["reversed"]:
            continue
        repo.add_entry(session, ctx.tenant_id, ctx.user_id, {
            "company_id": entry["company_id"], "customer_id": entry["customer_id"],
            "holder_type": entry["holder_type"], "holder_id": entry["holder_id"], "entry_type": "reversal",
            "quantity": -entry["quantity"], "service_ref": entry["service_ref"], "source_type": source_type,
            "source_id": source_id, "reverses_id": entry["id"],
            "business_date": common.today(session, entry["company_id"]), "note": "Released"})
        total += -entry["quantity"]
    if total:
        audit_record(session, "release", "memberships.credit", source_id, {"released": str(total)})
    return total


def _holder(session: Session, holder_type: str, holder_id: UUID) -> repo.Row:
    table = "member" if holder_type == MEMBERSHIP else "sold_package"
    row = repo.get(session, table, holder_id, lock=True)
    if row is None:
        raise ValidationFailed("That membership or package was not found")
    common.check_visible(row["company_id"], row["branch_id"], "Record")
    return row


def add_unchecked(session: Session, holder: repo.Row, holder_type: str, entry_type: str, quantity: Decimal, *,
                  note: str | None = None, period_start: date | None = None, day: date | None = None,
                  source_type: str | None = None, source_id: UUID | None = None) -> repo.Row:
    """Write one ledger entry for a holder (the caller has checked permission and rules)."""
    ctx = current_context()
    return repo.add_entry(session, ctx.tenant_id, ctx.user_id, {
        "company_id": holder["company_id"], "customer_id": holder["customer_id"], "holder_type": holder_type,
        "holder_id": holder["id"], "entry_type": entry_type, "quantity": quantity, "note": note,
        "period_start": period_start, "source_type": source_type, "source_id": source_id,
        "business_date": day or common.today(session, holder["company_id"])})


def adjust(session: Session, *, holder_type: str, holder_id: UUID, quantity: Decimal, note: str) -> repo.Row:
    """Add (or take away) credits by hand, with a note saying why. Needs 'memberships.credits'. A balance cannot go
    below zero unless the company allows overdraw."""
    if holder_type not in (MEMBERSHIP, PACKAGE):
        raise ValidationFailed("holder_type must be 'membership' or 'package'")
    if quantity == ZERO:
        raise ValidationFailed("The adjustment cannot be zero")
    if not note.strip():
        raise ValidationFailed("Say why the credits are being adjusted")
    holder = _holder(session, holder_type, holder_id)
    common.require(CREDITS, holder["company_id"], holder["branch_id"])
    if holder_type == PACKAGE and holder["status"] != "active":
        raise ValidationFailed("This package is no longer active")
    settings = repo.get_settings(session, holder["company_id"])
    if quantity < ZERO and not settings["allow_overdraw"] and repo.holder_balance(session, holder_id) + quantity < ZERO:
        raise ValidationFailed("That would take the balance below zero")
    entry = add_unchecked(session, holder, holder_type, "adjustment", quantity, note=note.strip()[:300])
    audit_record(session, "adjust", f"memberships.{holder_type}", holder_id, {"quantity": str(quantity)})
    return entry


def ledger(session: Session, holder_id: UUID, *, limit: int = 100, offset: int = 0) -> list[repo.Row]:
    """The entries of one membership or package, newest first."""
    found = repo.many(session, "select * from memberships.credit_entry where holder_id = :h "
                               "order by seq desc limit :l offset :o",
                      h=holder_id, l=min(limit, 500), o=offset)
    if found:
        common.check_visible(found[0]["company_id"], None, "Record")
    return found


def expire_leftover(session: Session, holder: repo.Row, holder_type: str, *, note: str,
                    day: date | None = None) -> Decimal:
    """Write off what is left of a holder's credits (an 'expiry' entry). Returns how much expired."""
    balance = repo.holder_balance(session, holder["id"])
    if balance > ZERO:
        add_unchecked(session, holder, holder_type, "expiry", -balance, note=note, day=day)
        return balance
    return ZERO


def customer_summary(session: Session, customer_id: UUID) -> dict[str, object]:
    """Everything a customer can spend or has: memberships and packages with balances."""
    customer = common.customer_of_any(session, customer_id)
    common.check_visible(customer.company_id, None, "Customer")
    members = repo.many(session, "select * from memberships.member where customer_id = :c "
                                 "order by status, start_date desc", c=customer_id)
    packages = repo.many(session, "select * from memberships.sold_package where customer_id = :c "
                                  "order by status, purchased_on desc", c=customer_id)
    balance = repo.balances(session, [r["id"] for r in members + packages])
    return {"customer_id": customer_id, "discount_percent": member_discount(session, customer_id),
            "memberships": [{**m, "balance": balance[m["id"]]} for m in members],
            "packages": [{**p, "balance": balance[p["id"]]} for p in packages]}

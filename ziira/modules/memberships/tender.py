"""Paying at the Bookings front desk with what this unit holds: a gift voucher (by code), the customer's credit
(referral, promo, a voucher sent to them) and loyalty points. Plugs into `bookings.checkout_tender`
(docs/memberships.md).

Each redeem takes from the value ledger and then settles that much of the invoice in Sales
(`pos.public.settle_invoice_non_cash`). Asking again for the same checkout takes nothing more."""

from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from ziira.modules.bookings.public import CHECKOUT_TENDER, CheckoutTender, TenderBalance, TenderUse
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, values
from ziira.sdk import Session, ValidationFailed, provides

ZERO = Decimal(0)


def _settle(session: Session, invoice_id: UUID, amount: Decimal, kind: str, reference: str) -> None:
    import ziira.modules.pos.public as sales

    sales.settle_invoice_non_cash(session, invoice_id, amount, kind=kind, reference=reference)


def _already(session: Session, account_id: UUID, source_type: str, source_id: UUID) -> Decimal:
    """What an earlier call for this checkout already took from the account (0 when nothing)."""
    found = repo.one(session, "select coalesce(sum(-e.quantity), 0) as s from memberships.value_entry e "
                              "where e.account_id = :a and e.entry_type = 'redeem' and e.source_type = :t "
                              "and e.source_id = :s and not exists (select 1 from memberships.value_entry r "
                              "where r.reverses_id = e.id)", a=account_id, t=source_type, s=source_id)
    return Decimal(found["s"]) if found else ZERO


@provides(CHECKOUT_TENDER)
class VoucherTender(CheckoutTender):
    kind = "voucher"
    label = "Gift voucher"
    needs_code = True

    def balance(self, session: Session, *, customer_id: UUID | None, code: str | None) -> TenderBalance | None:
        if not code:
            return None
        row = repo.one(session, "select * from memberships.value_account where code = :k and kind = 'gift' "
                                "and status = 'active' and (expires_on is null or expires_on >= current_date) limit 1",
                       k=code.strip().upper())
        if row is None:
            return None
        left = values.balance_of(session, row["id"])
        return TenderBalance(left, f"Voucher {row['code']}") if left > 0 else None

    def redeem(self, session: Session, *, customer_id: UUID, code: str | None, amount: Decimal, invoice_id: UUID,
               source_type: str, source_id: UUID) -> TenderUse:
        customer = common.customer_of_any(session, customer_id)
        row = values.find_voucher(session, customer.company_id, code or "")
        if row is None or row["status"] != "active":
            raise ValidationFailed("That gift voucher code is not valid")
        replay = _already(session, row["id"], source_type, source_id)
        if replay > 0:
            return TenderUse(replay, row["code"])
        applied = values.redeem(session, row["id"], amount, source_type=source_type, source_id=source_id,
                                note="Paid at the front desk")
        if applied > 0:
            _settle(session, invoice_id, applied, "voucher", row["code"])
        return TenderUse(applied, row["code"])

    def release(self, session: Session, *, source_type: str, source_id: UUID) -> None:
        values.release(session, source_type=source_type, source_id=source_id)


@provides(CHECKOUT_TENDER)
class CreditTender(CheckoutTender):
    kind = "credit"
    label = "Member credit"
    needs_code = False

    def balance(self, session: Session, *, customer_id: UUID | None, code: str | None) -> TenderBalance | None:
        if customer_id is None:
            return None
        found = values.summary(session, customer_id)
        return TenderBalance(found["credit"], "Referral and promo credit") if found["credit"] > 0 else None

    def redeem(self, session: Session, *, customer_id: UUID, code: str | None, amount: Decimal, invoice_id: UUID,
               source_type: str, source_id: UUID) -> TenderUse:
        customer = common.customer_of_any(session, customer_id)
        day = common.today(session, customer.company_id)
        taken, left = ZERO, amount
        replayed = False
        for account in values.usable_accounts(session, customer.company_id, customer_id, day):
            before = _already(session, account["id"], source_type, source_id)
            if before > 0:
                replayed, taken, left = True, taken + before, left - before
        if replayed:
            return TenderUse(taken, "credit")
        for account in values.usable_accounts(session, customer.company_id, customer_id, day):
            if left <= 0:
                break
            spent = values.redeem(session, account["id"], left, source_type=source_type, source_id=source_id,
                                  note="Paid at the front desk")
            taken, left = taken + spent, left - spent
        if taken > 0:
            _settle(session, invoice_id, taken, "credit", "member credit")
        return TenderUse(taken, "credit")

    def release(self, session: Session, *, source_type: str, source_id: UUID) -> None:
        values.release(session, source_type=source_type, source_id=source_id)


@provides(CHECKOUT_TENDER)
class LoyaltyTender(CheckoutTender):
    kind = "loyalty"
    label = "Loyalty points"
    needs_code = False

    @staticmethod
    def _value(session: Session, company_id: UUID) -> Decimal:
        return Decimal(repo.get_settings(session, company_id)["point_value"])

    def balance(self, session: Session, *, customer_id: UUID | None, code: str | None) -> TenderBalance | None:
        if customer_id is None:
            return None
        customer = common.customer_of_any(session, customer_id)
        value = self._value(session, customer.company_id)
        points = values.points_balance(session, customer_id)
        worth = (points * value).quantize(Decimal("0.01"))
        return TenderBalance(worth, f"{points:g} points") if worth > 0 else None

    def redeem(self, session: Session, *, customer_id: UUID, code: str | None, amount: Decimal, invoice_id: UUID,
               source_type: str, source_id: UUID) -> TenderUse:
        customer = common.customer_of_any(session, customer_id)
        value = self._value(session, customer.company_id)
        account = values.points_account(session, customer.company_id, customer_id)
        if value <= 0 or account is None:
            raise ValidationFailed("This customer has no points to pay with")
        replay = _already(session, account["id"], source_type, source_id)
        if replay > 0:
            return TenderUse(replay * value, "points")
        wanted = (amount / value).quantize(Decimal(1), rounding=ROUND_DOWN)
        points = values.redeem(session, account["id"], wanted, source_type=source_type, source_id=source_id,
                               note="Paid at the front desk")
        applied = (points * value).quantize(Decimal("0.01"))
        if applied > 0:
            _settle(session, invoice_id, applied, "loyalty", f"{points:g} points")
        return TenderUse(applied, f"{points:g} points")

    def release(self, session: Session, *, source_type: str, source_id: UUID) -> None:
        values.release(session, source_type=source_type, source_id=source_id)

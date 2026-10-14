"""Use cases: money moving between the business's own accounts: M-Pesa settled to the bank, cash banked.

Each is recorded as a pair of payments (out of one account, into the other) with the same reference, so a bank
statement line for it matches them like any other money; Finance posts the entry from the `payment.settled` /
`payment.banked` event.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.payments.domain import mpesa
from ziira.modules.payments.permissions import PAYMENTS_RECORD
from ziira.modules.payments.repository import payments_repo
from ziira.modules.payments.services import accounts, closing
from ziira.modules.payments.services.payments import record_payment
from ziira.sdk import (
    Event,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_today,
    current_context,
    publish,
)


def record_settlement(session: Session, *, from_account_id: UUID, to_account_id: UUID, amount: Decimal,
                      fee: Decimal = Decimal(0), business_date: date | None = None, reference: str) -> UUID:
    """M-Pesa paid its takings (less charges) into the bank. `amount` is what reached the bank; `fee` what Safaricom
    kept. Needs 'payments.record'. Returns the settlement's id."""
    source = accounts.check_active(payments_repo.get_account(session, from_account_id))
    target = accounts.check_active(payments_repo.get_account(session, to_account_id), source.company_id)
    ctx = current_context()
    ctx.require(PAYMENTS_RECORD, company_id=source.company_id, branch_id=source.branch_id)
    if source.kind != "mobile_money" or target.kind != "bank":
        raise ValidationFailed("A settlement goes from an M-Pesa account to a bank account")
    amount = mpesa.parse_amount(amount, "Settlement amount")
    if fee < 0 or fee != fee.quantize(Decimal("0.01")):
        raise ValidationFailed("The fee must be zero or a positive amount")
    if not reference.strip():
        raise ValidationFailed("A reference is required")
    day = business_date or company_today(session, source.company_id)
    paid_out = record_payment(session, company_id=source.company_id, branch_id=source.branch_id, method="mobile_money",
                              direction="out", amount=amount + fee, payment_account_id=source.id, business_date=day,
                              external_ref=reference, party_type="other",
                              allocations=[("settlement", target.id, amount + fee)])
    record_payment(session, company_id=source.company_id, branch_id=target.branch_id, method="bank", direction="in",
                   amount=amount, payment_account_id=target.id, business_date=day, external_ref=reference,
                   party_type="other", allocations=[("settlement", source.id, amount)])
    audit_record(session, "settle", "payments.payment", paid_out.id, {"amount": amount, "fee": fee})
    publish(session, Event("payment.settled", "payments.payment", paid_out.id, {
        "company_id": source.company_id, "branch_id": source.branch_id, "business_date": day, "amount": amount,
        "fee": fee, "from_account_id": source.id, "to_account_id": target.id, "reference": reference.strip()}))
    return paid_out.id


def record_cash_deposit(session: Session, *, company_id: UUID, branch_id: UUID, bank_account_id: UUID,
                        amount: Decimal, business_date: date | None = None, reference: str) -> UUID:
    """Cash from a branch's till was taken to the bank. Needs 'payments.record' for the branch. Returns the deposit's
    id (the cash payment out)."""
    check_company(session, company_id, branch_id)
    current_context().require(PAYMENTS_RECORD, company_id=company_id, branch_id=branch_id)
    bank = accounts.check_active(payments_repo.get_account(session, bank_account_id), company_id)
    if bank.kind != "bank":
        raise ValidationFailed("Cash is banked into a bank account")
    amount = mpesa.parse_amount(amount, "Deposit amount")
    if not reference.strip():
        raise ValidationFailed("A reference (the deposit slip number) is required")
    day = business_date or company_today(session, company_id)
    closing.check_day_open(session, branch_id, day)
    cash = accounts.cash_account_for_branch(session, company_id, branch_id)
    out = record_payment(session, company_id=company_id, branch_id=branch_id, method="cash", direction="out",
                         amount=amount, payment_account_id=cash.id, business_date=day, external_ref=None,
                         party_type="other", allocations=[("cash_deposit", bank.id, amount)])
    record_payment(session, company_id=company_id, branch_id=bank.branch_id, method="bank", direction="in",
                   amount=amount, payment_account_id=bank.id, business_date=day, external_ref=reference,
                   party_type="other", allocations=[("cash_deposit", cash.id, amount)])
    publish(session, Event("payment.banked", "payments.payment", out.id, {
        "company_id": company_id, "branch_id": branch_id, "business_date": day, "amount": amount,
        "bank_account_id": bank.id, "cash_account_id": cash.id, "reference": reference.strip()}))
    return out.id

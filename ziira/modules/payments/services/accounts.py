"""Use cases: payment accounts (a branch's till cash, an M-Pesa till or paybill, a bank account, a card terminal)."""

import re
from uuid import UUID

from sqlalchemy import text

from ziira.modules.payments.permissions import PAYMENTS_MANAGE
from ziira.modules.payments.repository import payments_repo
from ziira.modules.payments.repository.models import PaymentAccount
from ziira.modules.payments.services.access import can_view, view_scopes
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    hash_secret,
    is_production,
    new_secret,
    read_credential,
    store_credential,
)

KINDS = ("cash", "mpesa_till", "mpesa_paybill", "bank", "card")
SHORTCODE = re.compile(r"^\d{4,10}$")
ENVIRONMENTS = ("sandbox", "production")


def create_account(session: Session, *, company_id: UUID, kind: str, name: str, branch_id: UUID | None = None,
                   shortcode: str | None = None, bank_account_masked: str | None = None,
                   ledger_account_id: UUID | None = None, provider: str = "daraja",
                   environment: str = "sandbox") -> PaymentAccount:
    """Add a payment account. Needs 'payments.manage' for the company (and branch)."""
    ctx = current_context()
    check_company(session, company_id, branch_id)
    ctx.require(PAYMENTS_MANAGE, company_id=company_id, branch_id=branch_id)
    if kind not in KINDS:
        raise ValidationFailed(f"Kind must be one of: {', '.join(KINDS)}")
    name = name.strip()
    if not name or len(name) > 200:
        raise ValidationFailed("A name is required (at most 200 characters)")
    if kind in ("cash",) and branch_id is None:
        raise ValidationFailed("A till cash account belongs to a branch")
    if kind.startswith("mpesa"):
        if not shortcode or not SHORTCODE.match(shortcode.strip()):
            raise ValidationFailed("An M-Pesa account needs its till or paybill number (4-10 digits)")
        shortcode = shortcode.strip()
        if environment not in ENVIRONMENTS:
            raise ValidationFailed(f"Environment must be one of: {', '.join(ENVIRONMENTS)}")
    else:
        shortcode = None
    if provider not in ("daraja", "fake"):
        raise ValidationFailed("Provider must be 'daraja' (or 'fake', for development)")
    if provider == "fake" and is_production():
        raise ValidationFailed("The fake provider is for development only")
    if bank_account_masked is not None and len(bank_account_masked) > 40:
        raise ValidationFailed("The masked account number is too long")
    account = PaymentAccount(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id, kind=kind,
        name=name, shortcode=shortcode, bank_account_masked=bank_account_masked, ledger_account_id=ledger_account_id,
        provider=provider, config={"environment": environment} if kind.startswith("mpesa") else {})
    payments_repo.add(session, account)
    audit_record(session, "create", "payments.payment_account", account.id, {"kind": kind, "name": name})
    return account


def cash_account_for_branch(session: Session, company_id: UUID, branch_id: UUID) -> PaymentAccount:
    """The branch's till-cash account, created the first time it is needed (by the system, not a person)."""
    found = payments_repo.find_cash_account(session, company_id, branch_id)
    if found is not None:
        return found
    check_company(session, company_id, branch_id)
    ctx = current_context()
    branch_name = session.execute(text("select name from kernel.branch where id = :b"),
                                  {"b": str(branch_id)}).scalar_one()
    account = PaymentAccount(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                             branch_id=branch_id, kind="cash", name=f"Till cash - {branch_name}")
    payments_repo.add(session, account)
    audit_record(session, "create", "payments.payment_account", account.id, {"kind": "cash", "auto": True})
    return account


def get_account(session: Session, account_id: UUID) -> PaymentAccount:
    account = payments_repo.get_account(session, account_id)
    if account is None or not can_view(account.company_id, account.branch_id):
        raise NotFound("Payment account not found")
    return account


def list_accounts(session: Session, *, company_id: UUID | None = None, branch_id: UUID | None = None,
                  kind: str | None = None, include_inactive: bool = False) -> list[PaymentAccount]:
    """Payment accounts the user may see."""
    return payments_repo.list_accounts(session, view_scopes(), company_id=company_id, branch_id=branch_id, kind=kind,
                                       include_inactive=include_inactive)


def update_account(session: Session, account_id: UUID, *, name: str | None = None, is_active: bool | None = None,
                   ledger_account_id: UUID | None = None) -> PaymentAccount:
    """Rename an account, switch it on or off, or point it at a ledger account. Needs 'payments.manage'."""
    account = payments_repo.get_account(session, account_id)
    if account is None:
        raise NotFound("Payment account not found")
    current_context().require(PAYMENTS_MANAGE, company_id=account.company_id, branch_id=account.branch_id)
    changes: dict[str, object] = {}
    if name is not None:
        if not name.strip() or len(name.strip()) > 200:
            raise ValidationFailed("A name is required (at most 200 characters)")
        account.name = name.strip()
        changes["name"] = account.name
    if is_active is not None:
        account.is_active = is_active
        changes["is_active"] = is_active
    if ledger_account_id is not None:
        account.ledger_account_id = ledger_account_id
        changes["ledger_account_id"] = ledger_account_id
    session.flush()
    if changes:
        audit_record(session, "update", "payments.payment_account", account.id, changes)
    return account


def set_credentials(session: Session, account_id: UUID, secret: dict[str, str]) -> PaymentAccount:
    """Store the account's Daraja credentials (consumer key and secret, STK passkey), encrypted. They are never shown
    again. Needs 'payments.manage'."""
    account = payments_repo.get_account(session, account_id)
    if account is None:
        raise NotFound("Payment account not found")
    current_context().require(PAYMENTS_MANAGE, company_id=account.company_id, branch_id=account.branch_id)
    if not account.kind.startswith("mpesa"):
        raise ValidationFailed("Only M-Pesa accounts have Daraja credentials")
    missing = [k for k in ("consumer_key", "consumer_secret", "passkey") if not str(secret.get(k, "")).strip()]
    if missing:
        raise ValidationFailed(f"Missing: {', '.join(missing)}")
    account.credential_id = store_credential(
        session, company_id=account.company_id, branch_id=account.branch_id, provider="daraja",
        label=f"Daraja - {account.name}", secret={k: str(secret[k]).strip() for k in
                                                  ("consumer_key", "consumer_secret", "passkey")},
        config={"shortcode": account.shortcode}, replace=account.credential_id)
    session.flush()
    audit_record(session, "set_credentials", "payments.payment_account", account.id)
    return account


def credentials_of(session: Session, account: PaymentAccount) -> dict[str, str]:
    """The decrypted Daraja credentials, for the code about to call Safaricom."""
    if account.credential_id is None:
        raise ValidationFailed(f"{account.name} has no M-Pesa credentials yet")
    return {k: str(v) for k, v in read_credential(session, account.credential_id).items()}


def rotate_callback_token(session: Session, account_id: UUID) -> str:
    """Make a new secret for the account's callback URLs and return the full token, once. Register the URLs built
    from it with Safaricom; the previous token stops working. Needs 'payments.manage'."""
    account = payments_repo.get_account(session, account_id)
    if account is None:
        raise NotFound("Payment account not found")
    ctx = current_context()
    ctx.require(PAYMENTS_MANAGE, company_id=account.company_id, branch_id=account.branch_id)
    if not account.kind.startswith("mpesa"):
        raise ValidationFailed("Only M-Pesa accounts receive callbacks")
    token = f"{ctx.tenant_id.hex}.{new_secret()}"
    account.callback_token_hash = hash_secret(token)
    session.flush()
    audit_record(session, "rotate_callback_token", "payments.payment_account", account.id)
    return token


def callback_urls(token: str, base_url: str) -> dict[str, str]:
    """The C2B URLs to register with Safaricom for the account whose callback token this is. (The address for an STK
    push's outcome is made for each prompt: see services/intents.py.)"""
    root = f"{base_url.rstrip('/')}/api/v1/payments/callbacks/{token}"
    return {"c2b_validation": f"{root}/c2b/validation", "c2b_confirmation": f"{root}/c2b/confirmation"}


def check_active(account: PaymentAccount | None, company_id: UUID | None = None) -> PaymentAccount:
    """An active account (of the company, if given), or ValidationFailed."""
    if account is None or (company_id is not None and account.company_id != company_id):
        raise ValidationFailed("Payment account not found in this company")
    if not account.is_active:
        raise ValidationFailed(f"{account.name} is not active")
    return account


def ensure_unique_shortcode(session: Session, shortcode: str, company_id: UUID) -> None:
    for other in payments_repo.account_by_shortcode(session, shortcode):
        if other.company_id != company_id:
            raise Conflict("That shortcode is already used by another company")

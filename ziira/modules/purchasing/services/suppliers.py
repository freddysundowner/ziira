"""Use cases: suppliers and their bank details.

A supplier's bank details are the classic route for fraud ("we have changed our account"), so a change is never a
simple edit: one person proposes it, a *different* person confirms it with the supplier directly (a call back on a known
number, a visit, a signed letter), and then it goes through the approval matrix (document type `supplier_bank_change`).
Only then does it replace the active details, which are kept as history. The full account number is stored encrypted
and never shown again; people see the last four digits.
"""

from datetime import UTC, datetime
from uuid import UUID

from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import (
    SUPPLIER_BANK_CONFIRM,
    SUPPLIER_BANK_EDIT,
    SUPPLIERS_MANAGE,
)
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import Supplier, SupplierBankAccount
from ziira.modules.purchasing.services import access
from ziira.sdk import (
    Conflict,
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    encrypt_text,
    publish,
    submit_for_approval,
)

BANK_DOC_TYPE = "supplier_bank_change"
STATUSES = ("active", "on_hold", "inactive")


def create_supplier(session: Session, *, company_id: UUID, code: str, name: str, tax_id: str | None = None,
                    phone: str | None = None, email: str | None = None, payment_terms_days: int = 0) -> Supplier:
    """Add a supplier. Needs 'suppliers.manage' for the company."""
    ctx = current_context()
    ctx.require(SUPPLIERS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    code = rules.normalise_code(code)
    if repo.supplier_by_code(session, company_id, code) is not None:
        raise Conflict(f"There is already a supplier with code {code}")
    supplier = Supplier(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=code,
        name=rules.check_name(name), tax_id=rules.check_tax_id(tax_id), phone=(phone or "").strip() or None,
        email=(email or "").strip() or None, payment_terms_days=rules.check_terms(payment_terms_days))
    repo.add(session, supplier)
    audit_record(session, "create", "purchasing.supplier", supplier.id, {"code": code, "name": supplier.name})
    return supplier


def get_supplier(session: Session, supplier_id: UUID) -> Supplier:
    supplier = repo.get_supplier(session, supplier_id)
    if supplier is None or not access.can_see_company(supplier.company_id):
        raise NotFound("Supplier not found")
    return supplier


def list_suppliers(session: Session, *, search: str | None = None, status: str | None = None, limit: int = 50,
                   offset: int = 0) -> list[Supplier]:
    return repo.list_suppliers(session, access.view_companies(), search=search, status=status, limit=min(limit, 200),
                               offset=offset)


def update_supplier(session: Session, supplier_id: UUID, *, name: str | None = None, tax_id: str | None = None,
                    phone: str | None = None, email: str | None = None, payment_terms_days: int | None = None,
                    status: str | None = None) -> Supplier:
    """Change a supplier's details or put it on hold. Bank details are not changed here. Needs 'suppliers.manage'."""
    supplier = repo.get_supplier(session, supplier_id, lock=True)
    if supplier is None or not access.can_see_company(supplier.company_id):
        raise NotFound("Supplier not found")
    current_context().require(SUPPLIERS_MANAGE, company_id=supplier.company_id)
    changes: dict[str, object] = {}
    if name is not None:
        supplier.name = rules.check_name(name)
        changes["name"] = supplier.name
    if tax_id is not None:
        supplier.tax_id = rules.check_tax_id(tax_id)
        changes["tax_id"] = supplier.tax_id
    if phone is not None:
        supplier.phone = phone.strip() or None
    if email is not None:
        supplier.email = email.strip() or None
    if payment_terms_days is not None:
        supplier.payment_terms_days = rules.check_terms(payment_terms_days)
        changes["payment_terms_days"] = payment_terms_days
    if status is not None:
        if status not in STATUSES:
            raise ValidationFailed(f"Status must be one of: {', '.join(STATUSES)}")
        supplier.status = status
        changes["status"] = status
    supplier.updated_by = current_context().user_id
    supplier.updated_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "update", "purchasing.supplier", supplier.id, changes)
    return supplier


# --------------------------------------------------------------------------- bank details
def list_bank_accounts(session: Session, supplier_id: UUID) -> list[SupplierBankAccount]:
    """The supplier's bank details, newest first, as masked. Needs the right to see the supplier."""
    get_supplier(session, supplier_id)
    return repo.bank_accounts(session, supplier_id)


def propose_bank_account(session: Session, supplier_id: UUID, *, method: str, account_no: str,
                         bank_name: str | None = None, account_name: str | None = None) -> SupplierBankAccount:
    """Propose new bank or M-Pesa details. They change nothing until confirmed and approved. Needs
    'supplier.bank_edit'."""
    supplier = repo.get_supplier(session, supplier_id, lock=True)
    if supplier is None or not access.can_see_company(supplier.company_id):
        raise NotFound("Supplier not found")
    ctx = current_context()
    ctx.require(SUPPLIER_BANK_EDIT, company_id=supplier.company_id)
    if method not in ("bank", "mobile_money"):
        raise ValidationFailed("Method must be 'bank' or 'mpesa'")
    number = rules.check_account_number(method, account_no)
    if method == "bank" and not (bank_name and bank_name.strip()):
        raise ValidationFailed("A bank account needs the bank's name")
    if any(b.status in ("pending_confirmation", "pending_approval") for b in repo.bank_accounts(session, supplier_id)):
        raise Conflict("A change to this supplier's bank details is already waiting: finish or reject it first")
    account = SupplierBankAccount(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, supplier_id=supplier_id, method=method,
        bank_name=(bank_name or "").strip() or None, account_name=(account_name or "").strip() or None,
        account_no_ciphertext=encrypt_text(number).encode(), account_no_masked=rules.mask_account(number),
        valid_from=datetime.now(UTC))
    repo.add(session, account)
    audit_record(session, "propose_bank", "purchasing.supplier_bank_account", account.id,
                 {"supplier": supplier.code, "account": account.account_no_masked})
    return account


def confirm_bank_account(session: Session, bank_id: UUID, *, confirmation_method: str,
                         note: str | None = None) -> SupplierBankAccount:
    """Record that someone other than the proposer confirmed the details with the supplier directly, then send them
    for approval. Needs 'supplier.bank_confirm'."""
    account = repo.get_bank(session, bank_id, lock=True)
    supplier = repo.get_supplier(session, account.supplier_id) if account else None
    if account is None or supplier is None or not access.can_see_company(supplier.company_id):
        raise NotFound("Bank details not found")
    ctx = current_context()
    ctx.require(SUPPLIER_BANK_CONFIRM, company_id=supplier.company_id)
    if account.status != "pending_confirmation":
        raise Conflict(f"These details are {account.status.replace('_', ' ')}, not waiting for confirmation")
    if account.created_by == ctx.user_id:
        raise Forbidden("The person who proposed the change cannot be the one who confirms it")
    if confirmation_method not in rules.CONFIRMATION_METHODS:
        raise ValidationFailed(f"Confirmed by one of: {', '.join(rules.CONFIRMATION_METHODS)}")
    account.confirmed_by, account.confirmed_at = ctx.user_id, datetime.now(UTC)
    account.confirmation_method, account.status = confirmation_method, "pending_approval"
    session.flush()
    audit_record(session, "confirm_bank", "purchasing.supplier_bank_account", account.id,
                 {"method": confirmation_method, "note": (note or "").strip() or None})
    if submit_for_approval(session, company_id=supplier.company_id, doc_type=BANK_DOC_TYPE, doc_id=account.id) \
            == "approved":
        _activate(session, account, supplier, approved_by=None)
    return account


def apply_bank_decision(session: Session, bank_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Activate or reject bank details once their approval has been decided (from `approval.decided`)."""
    account = repo.get_bank(session, bank_id, lock=True)
    supplier = repo.get_supplier(session, account.supplier_id) if account else None
    if account is None or supplier is None or account.status != "pending_approval":
        return
    if approved:
        _activate(session, account, supplier, approved_by=decided_by)
    else:
        account.status = "rejected"
        session.flush()
        audit_record(session, "reject_bank", "purchasing.supplier_bank_account", account.id, None)


def reject_bank_account(session: Session, bank_id: UUID) -> SupplierBankAccount:
    """Withdraw proposed details that failed confirmation. Needs 'supplier.bank_confirm' (or 'supplier.bank_edit' for
    the proposer's own)."""
    account = repo.get_bank(session, bank_id, lock=True)
    supplier = repo.get_supplier(session, account.supplier_id) if account else None
    if account is None or supplier is None or not access.can_see_company(supplier.company_id):
        raise NotFound("Bank details not found")
    ctx = current_context()
    if not (ctx.can(SUPPLIER_BANK_CONFIRM, company_id=supplier.company_id)
            or (account.created_by == ctx.user_id and ctx.can(SUPPLIER_BANK_EDIT, company_id=supplier.company_id))):
        raise Forbidden("You cannot reject these details")
    if account.status != "pending_confirmation":
        raise Conflict("Only details still waiting for confirmation can be withdrawn here")
    account.status = "rejected"
    session.flush()
    audit_record(session, "reject_bank", "purchasing.supplier_bank_account", account.id, None)
    return account


def _activate(session: Session, account: SupplierBankAccount, supplier: Supplier, *, approved_by: UUID | None) -> None:
    now = datetime.now(UTC)
    current = repo.active_bank(session, supplier.id)
    if current is not None:
        current.status, current.valid_to = "superseded", now
        session.flush()
    account.status, account.valid_from, account.approved_by = "active", now, approved_by
    session.flush()
    audit_record(session, "activate_bank", "purchasing.supplier_bank_account", account.id,
                 {"supplier": supplier.code, "account": account.account_no_masked})
    publish(session, Event("supplier.bank_changed", "purchasing.supplier", supplier.id, {
        "company_id": supplier.company_id, "supplier": supplier.code, "method": account.method,
        "account": account.account_no_masked, "changed_by": account.created_by, "confirmed_by": account.confirmed_by}))

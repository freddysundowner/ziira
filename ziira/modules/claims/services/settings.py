"""Use cases: claim settings of a company, and payers with their terms."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.claims.permissions import CLAIMS_SETTINGS
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import ClaimSetting, Payer
from ziira.modules.claims.services import access
from ziira.modules.claims.services.common import clean, unit_enabled
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, check_company, current_context

KINDS = ("insurer", "scheme", "fleet", "employer", "other")


def get_settings(session: Session, company_id: UUID) -> ClaimSetting:
    """The company's settings, made with defaults the first time they are needed."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    found = repo.get_setting(session, company_id)
    if found is not None:
        return found
    check_company(session, company_id)
    row = ClaimSetting(tenant_id=current_context().tenant_id, company_id=company_id)
    repo.add(session, row)
    return row


def update_settings(session: Session, company_id: UUID, **changes: Any) -> ClaimSetting:
    """Change claim settings. Needs 'claims.settings' for the company."""
    ctx = current_context()
    ctx.require(CLAIMS_SETTINGS, company_id=company_id)
    row = get_settings(session, company_id)
    if "invoice_product_id" in changes and changes["invoice_product_id"] is not None:
        _check_service_item(session, company_id, changes["invoice_product_id"])
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "claims.setting", row.id, {k: str(v) for k, v in changes.items()})
    return row


def _check_service_item(session: Session, company_id: UUID, product_id: UUID) -> None:
    if not unit_enabled(session, "products"):
        raise ValidationFailed("Products must be switched on to choose the invoice item")
    from ziira.modules.products.public import find_product

    product = find_product(session, product_id)
    if product is None or product.company_id != company_id or not product.is_active:
        raise ValidationFailed("The invoice item was not found in this company")
    if product.product_type == "stock":
        raise ValidationFailed("Choose a service item (one that holds no stock) for claim invoices")


# --------------------------------------------------------------------------- payers
def _check_rates(rates: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (rates or {}).items():
        name = str(key).strip().lower()[:40]
        try:
            rate = Decimal(str(value))
        except Exception:
            raise ValidationFailed(f"The hourly rate for '{key}' is not a number") from None
        if not name or rate < 0 or rate > Decimal("100000000"):
            raise ValidationFailed("Hourly rates need a work type and an amount of zero or more")
        out[name] = str(rate)
    return out


def _check_contacts(contacts: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    out = []
    for item in contacts or []:
        row = {k: (clean(str(item.get(k) or ""), 160) or "") for k in ("name", "role", "phone", "email")}
        if row["name"]:
            out.append(row)
    return out[:30]


def _check_documents(documents: list[str] | None) -> list[str]:
    seen: list[str] = []
    for item in documents or []:
        label = clean(item, 120)
        if label and label not in seen:
            seen.append(label)
    return seen[:30]


def _check_customer(session: Session, company_id: UUID, customer_id: UUID | None) -> None:
    if customer_id is None:
        return
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Customers must be switched on to link a payer to a customer account")
    from ziira.modules.crm.public import find_customer

    customer = find_customer(session, customer_id)
    if customer is None or customer.company_id != company_id:
        raise ValidationFailed("The customer account was not found in this company")


def list_payers(session: Session, company_id: UUID | None, *, only_active: bool = False) -> list[Payer]:
    return repo.payers(session, access.view_companies(), only_active=only_active, company_id=company_id)


def load_payer(session: Session, payer_id: UUID) -> Payer:
    payer = repo.get(session, Payer, payer_id)
    if payer is None or not access.can_see_company(payer.company_id):
        raise NotFound("Payer not found")
    return payer


def create_payer(session: Session, *, company_id: UUID, name: str, kind: str = "insurer",
                 customer_id: UUID | None = None, new_customer: dict[str, str | None] | None = None,
                 labour_rates: dict[str, Any] | None = None, parts_discount_pct: Decimal = Decimal(0),
                 parts_markup_pct: Decimal = Decimal(0), paint_rate: Decimal | None = None,
                 approval_limit: Decimal | None = None, payment_days: int = 30,
                 required_documents: list[str] | None = None, contacts: list[dict[str, Any]] | None = None,
                 estimate_email: str | None = None, notes: str | None = None) -> Payer:
    """Set up a payer. Needs 'claims.settings' for the company. The payer is paid through a customer account: name an
    existing one, or give `new_customer` (name, phone, email) to make one."""
    ctx = current_context()
    ctx.require(CLAIMS_SETTINGS, company_id=company_id)
    check_company(session, company_id)
    label = clean(name, 160)
    if label is None:
        raise ValidationFailed("A payer needs a name")
    if kind not in KINDS:
        raise ValidationFailed(f"A payer is one of: {', '.join(KINDS)}")
    if repo.payer_by_name(session, company_id, label) is not None:
        raise Conflict(f"There is already a payer called {label}")
    if customer_id is None and new_customer is not None:
        if not unit_enabled(session, "crm"):
            raise ValidationFailed("Customers must be switched on to make a customer account for the payer")
        from ziira.modules.crm.public import match_or_create_customer

        made, _ = match_or_create_customer(session, company_id, name=clean(new_customer.get("name"), 160) or label,
                                           phone=new_customer.get("phone"), email=new_customer.get("email"))
        customer_id = made.id
    _check_customer(session, company_id, customer_id)
    payer = Payer(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, customer_id=customer_id,
                  name=label, kind=kind, labour_rates=_check_rates(labour_rates), parts_discount_pct=parts_discount_pct,
                  parts_markup_pct=parts_markup_pct, paint_rate=paint_rate, approval_limit=approval_limit,
                  payment_days=payment_days, required_documents=_check_documents(required_documents),
                  contacts=_check_contacts(contacts), estimate_email=clean(estimate_email, 200),
                  notes=clean(notes, 2000))
    repo.add(session, payer)
    audit_record(session, "create", "claims.payer", payer.id, {"name": label, "kind": kind})
    return payer


def update_payer(session: Session, payer_id: UUID, **changes: Any) -> Payer:
    """Change a payer's details or terms. Needs 'claims.settings' for the company. Terms apply to estimates made from
    now on; existing estimates keep their prices."""
    payer = load_payer(session, payer_id)
    ctx = current_context()
    ctx.require(CLAIMS_SETTINGS, company_id=payer.company_id)
    if "name" in changes:
        label = clean(changes["name"], 160)
        if label is None:
            raise ValidationFailed("A payer needs a name")
        other = repo.payer_by_name(session, payer.company_id, label)
        if other is not None and other.id != payer.id:
            raise Conflict(f"There is already a payer called {label}")
        changes["name"] = label
    if "kind" in changes and changes["kind"] not in KINDS:
        raise ValidationFailed(f"A payer is one of: {', '.join(KINDS)}")
    if "customer_id" in changes:
        _check_customer(session, payer.company_id, changes["customer_id"])
    if "labour_rates" in changes:
        changes["labour_rates"] = _check_rates(changes["labour_rates"])
    if "contacts" in changes:
        changes["contacts"] = _check_contacts(changes["contacts"])
    if "required_documents" in changes:
        changes["required_documents"] = _check_documents(changes["required_documents"])
    for key in ("estimate_email", "notes"):
        if key in changes:
            changes[key] = clean(changes[key], 2000 if key == "notes" else 200)
    for key, value in changes.items():
        setattr(payer, key, value)
    payer.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "claims.payer", payer.id, {k: str(v) for k, v in changes.items()})
    return payer

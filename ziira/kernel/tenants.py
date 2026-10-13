"""Creating a tenant: the business, its first company and branch, default roles and the owner."""

import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text

from ziira.kernel import audit
from ziira.kernel.context import system_context
from ziira.kernel.db import admin_session, tenant_session
from ziira.kernel.errors import Conflict, ValidationFailed
from ziira.kernel.registry import Registry, seed_unit_defaults
from ziira.kernel.security import hash_password

# Default roles from the specification (section 13). Owner always holds every permission;
# units add permissions to the others through the [roles] table of their manifest.
DEFAULT_ROLES = ("Owner", "Finance Manager", "Branch Manager", "Cashier", "Storekeeper", "Sales Rep", "HR",
                 "Accountant")
CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


@dataclass(frozen=True)
class NewTenant:
    """Identifiers of a newly created tenant."""

    tenant_id: UUID
    company_id: UUID
    branch_id: UUID
    owner_id: UUID


def create_tenant(*, name: str, code: str, company: str, branch_code: str, branch_name: str,
                  owner_name: str, owner_email: str, owner_password: str, kra_pin: str | None = None,
                  vat_registered: bool = False, registry: Registry | None = None) -> NewTenant:
    """Create a tenant ready to sign in to with the workspace code and the owner's email.

    The owner gets the Owner role for the whole tenant.
    """
    code = code.strip().lower()
    if not CODE_PATTERN.match(code):
        raise ValidationFailed("Workspace code must be 2-40 lowercase letters, digits or '-'")
    tenant_id, company_id, branch_id, owner_id = uuid4(), uuid4(), uuid4(), uuid4()
    with admin_session() as s:
        if s.execute(text("select 1 from kernel.tenant where code = :c"), {"c": code}).first():
            raise Conflict(f"Workspace code '{code}' is taken")
        s.execute(text("insert into kernel.tenant (id, name, code) values (:i, :n, :c)"),
                  {"i": str(tenant_id), "n": name, "c": code})

    system_context(tenant_id)
    password_hash = hash_password(owner_password)
    with tenant_session(tenant_id, admin=True) as s:
        s.execute(text("insert into kernel.company (id, tenant_id, name, kra_pin, vat_registered) "
                       "values (:i, :t, :n, :p, :v)"),
                  {"i": str(company_id), "t": str(tenant_id), "n": company, "p": kra_pin, "v": vat_registered})
        s.execute(text("insert into kernel.branch (id, tenant_id, company_id, code, name) "
                       "values (:i, :t, :c, :code, :n)"),
                  {"i": str(branch_id), "t": str(tenant_id), "c": str(company_id), "code": branch_code.upper(),
                   "n": branch_name})
        role_ids = {}
        for role in DEFAULT_ROLES:
            role_ids[role] = s.execute(text(
                "insert into kernel.role (tenant_id, name, is_system) values (:t, :n, true) returning id"),
                {"t": str(tenant_id), "n": role}).scalar_one()
        s.execute(text("insert into kernel.app_user (id, tenant_id, email, full_name, password_hash, status) "
                       "values (:i, :t, :e, :n, :h, 'active')"),
                  {"i": str(owner_id), "t": str(tenant_id), "e": owner_email.strip().lower(), "n": owner_name,
                   "h": password_hash})
        s.execute(text("insert into kernel.user_role (tenant_id, user_id, role_id, scope) "
                       "values (:t, :u, :r, 'tenant')"),
                  {"t": str(tenant_id), "u": str(owner_id), "r": str(role_ids["Owner"])})
        seed_unit_defaults(s, (registry or Registry()).get("kernel"))
        audit.record(s, "create", "kernel.tenant", tenant_id, {"name": name, "code": code, "owner": owner_email})
    return NewTenant(tenant_id=tenant_id, company_id=company_id, branch_id=branch_id, owner_id=owner_id)

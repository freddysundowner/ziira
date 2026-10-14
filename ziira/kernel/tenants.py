"""Tenants: each business gets its own database, recorded in the master database.

Creating a tenant:
1. Record it in the master database (status 'provisioning').
2. Create its own database login and copy the kernel-only template into a new database.
3. Store both connection strings (its login, and an owner login for migrations), encrypted.
4. Inside the new database: the business, its first company and branch, default roles and owner.
5. Mark it 'active'. If any step fails, the database, login and master record are removed.
"""

import json
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import make_url, text

from ziira.kernel import audit, directory
from ziira.kernel.config import get_settings
from ziira.kernel.context import system_context
from ziira.kernel.db import (
    forget_tenant,
    master_session,
    server_database_url,
    server_engine,
    tenant_engine,
    tenant_session,
)
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.phone import check_calling_code
from ziira.kernel.registry import Registry, ensure_master, grant_unit, seed_unit_defaults
from ziira.kernel.security import encrypt, hash_password, new_secret

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
    database: str


@dataclass(frozen=True)
class TenantRecord:
    """A tenant as the master database knows it."""

    id: UUID
    code: str
    name: str
    status: str
    db_name: str


def _names(code: str) -> tuple[str, str]:
    settings = get_settings()
    suffix = code.replace("-", "_")
    return f"{settings.tenant_db_prefix}{suffix}", f"{settings.tenant_role_prefix}{suffix}"


def list_tenants() -> list[TenantRecord]:
    """Every tenant in the master database."""
    with master_session() as s:
        rows = s.execute(text("select id, code, name, status, db_name from master.tenant order by code"))
        return [TenantRecord(**r._mapping) for r in rows]


def find_tenant(code_or_id: str) -> TenantRecord:
    """A tenant by workspace code or id."""
    for t in list_tenants():
        if code_or_id in (t.code, str(t.id)):
            return t
    raise NotFound(f"Tenant '{code_or_id}' not found")


def create_tenant(*, name: str, code: str, company: str, branch_code: str, branch_name: str,
                  owner_name: str, owner_email: str, currency: str, owner_password: str | None = None,
                  owner_password_hash: str | None = None, tax_id: str | None = None, phone_country_code: str = "",
                  country: str | None = None, vat_registered: bool = False,
                  registry: Registry | None = None) -> NewTenant:
    """Create a business with its own database, ready to sign in to with the workspace code.

    The owner gets the Owner role for the whole tenant. `currency` is the company's base currency (a three-letter code
    such as USD or KES); `phone_country_code` is its calling code (such as 44 or 254), used to read national phone
    numbers. Nothing about a country is assumed: both are chosen here. The owner's password is given as text or, when
    it was already hashed (self-service registration), as `owner_password_hash`.
    """
    currency = currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValidationFailed("Currency is a three-letter code such as USD")
    phone_country_code = check_calling_code(phone_country_code)
    country = country.strip().upper() if country and country.strip() else None
    if country is not None and not re.fullmatch(r"[A-Z]{2}", country):
        raise ValidationFailed("Country is a two-letter code such as GB")
    code = code.strip().lower()
    if not CODE_PATTERN.match(code):
        raise ValidationFailed("Workspace code must be 2-40 lowercase letters, digits or '-'")
    if (owner_password is None) == (owner_password_hash is None):
        raise ValidationFailed("Give the owner's password (or its hash)")
    password_hash = owner_password_hash or hash_password(str(owner_password))   # validate before creating anything
    reg = registry or Registry()
    ensure_master()
    reg.ensure_template()
    db_name, role = _names(code)
    tenant_id, company_id, branch_id, owner_id = uuid4(), uuid4(), uuid4(), uuid4()
    role_password = new_secret()
    app_url = make_url(get_settings().tenant_server_url).set(database=db_name, username=role,
                                                             password=role_password)
    with master_session() as s:
        if s.execute(text("select 1 from master.tenant where code = :c or db_name = :d"),
                     {"c": code, "d": db_name}).first():
            raise Conflict(f"Workspace code '{code}' is taken")
        s.execute(text(
            "insert into master.tenant (id, code, name, db_name, app_role, app_url_encrypted, admin_url_encrypted) "
            "values (:i, :c, :n, :d, :r, :app, :adm)"),
            {"i": str(tenant_id), "c": code, "n": name, "d": db_name, "r": role,
             "app": encrypt(app_url.render_as_string(hide_password=False)),
             "adm": encrypt(server_database_url(db_name))})
    try:
        with server_engine().connect() as conn:
            # role_password is URL-safe base64, so it needs no escaping inside the quotes.
            conn.exec_driver_sql(f"create role \"{role}\" login password '{role_password}'")
            conn.exec_driver_sql(f'create database "{db_name}" template "{get_settings().template_database}"')
            conn.exec_driver_sql(f'revoke all on database "{db_name}" from public')
            conn.exec_driver_sql(f'grant connect, temporary on database "{db_name}" to "{role}"')
        with tenant_engine(tenant_id, admin=True).begin() as conn:
            grant_unit(conn, reg.get("kernel"), role)
        _set_up_business(reg, tenant_id, company_id, branch_id, owner_id, name=name, code=code, company=company,
                         branch_code=branch_code, branch_name=branch_name, owner_name=owner_name,
                         owner_email=owner_email, password_hash=password_hash, tax_id=tax_id,
                         vat_registered=vat_registered, currency=currency, phone_country_code=phone_country_code,
                         country=country)
        with master_session() as s:
            s.execute(text("update master.tenant set status = 'active', updated_at = now() where id = :i"),
                      {"i": str(tenant_id)})
    except Exception:
        drop_tenant(tenant_id)
        raise
    return NewTenant(tenant_id=tenant_id, company_id=company_id, branch_id=branch_id, owner_id=owner_id,
                     database=db_name)


def _set_up_business(reg: Registry, tenant_id: UUID, company_id: UUID, branch_id: UUID, owner_id: UUID, *,
                     name: str, code: str, company: str, branch_code: str, branch_name: str, owner_name: str,
                     owner_email: str, password_hash: str, tax_id: str | None, vat_registered: bool, currency: str,
                     phone_country_code: str, country: str | None) -> None:
    system_context(tenant_id)
    with tenant_session(tenant_id, admin=True) as s:
        s.execute(text("insert into kernel.tenant (id, name, code, mfa_policy) values (:i, :n, :c, :m)"),
                  {"i": str(tenant_id), "n": name, "c": code, "m": get_settings().mfa_default_policy})
        settings = {"phone_country_code": phone_country_code} if phone_country_code else {}
        s.execute(text("insert into kernel.company (id, tenant_id, name, tax_id, vat_registered, base_currency, "
                       "country, settings) values (:i, :t, :n, :p, :v, :cur, :ctry, cast(:s as jsonb))"),
                  {"i": str(company_id), "t": str(tenant_id), "n": company, "p": tax_id, "v": vat_registered,
                   "cur": currency, "ctry": country, "s": json.dumps(settings)})
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
        seed_unit_defaults(s, reg.get("kernel"))
        audit.record(s, "create", "kernel.tenant", tenant_id, {"name": name, "code": code, "owner": owner_email})
    directory.register(tenant_id, owner_email)


def drop_tenant(tenant_id: UUID) -> None:
    """Delete a tenant completely: its database, its login and its master record. Cannot be undone."""
    with master_session() as s:
        row = s.execute(text("select db_name, app_role from master.tenant where id = :i"),
                        {"i": str(tenant_id)}).first()
    if row is None:
        raise NotFound("Tenant not found")
    forget_tenant(tenant_id)
    with server_engine().connect() as conn:
        conn.exec_driver_sql(f'drop database if exists "{row.db_name}" with (force)')
        conn.exec_driver_sql(f'drop role if exists "{row.app_role}"')
    with master_session() as s:
        s.execute(text("delete from master.tenant where id = :i"), {"i": str(tenant_id)})

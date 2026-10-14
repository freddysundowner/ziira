"""Users and roles: create users, grant roles with a scope, and manage custom roles.

Nobody can hand out more than they have: granting a role, or putting permissions in a role,
requires the actor to hold each of those permissions over the same scope. This stops a user
manager from making themselves Owner.
"""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, directory
from ziira.kernel.auth import sign_out_user
from ziira.kernel.context import get_context
from ziira.kernel.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ziira.kernel.security import hash_password

SCOPES = ("tenant", "company", "branch", "own")
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()-]{5,18}[0-9]$")


@dataclass(frozen=True)
class User:
    """A person who can sign in."""

    id: UUID
    full_name: str
    email: str | None
    phone: str | None
    status: str


@dataclass(frozen=True)
class Role:
    """A named set of permissions."""

    id: UUID
    name: str
    is_system: bool
    permissions: tuple[str, ...]


@dataclass(frozen=True)
class RoleGrant:
    """A role given to a user, with where it applies."""

    id: UUID
    user_id: UUID
    role_id: UUID
    role_name: str
    scope: str
    company_id: UUID | None
    branch_id: UUID | None


def _actor() -> str | None:
    user_id = get_context().user_id
    return str(user_id) if user_id else None


# --------------------------------------------------------------------------- users
def create_user(s: Session, *, full_name: str, email: str | None = None, phone: str | None = None,
                password: str | None = None) -> User:
    """Add a user. Without a password the user is 'invited' and cannot sign in yet."""
    if not full_name.strip():
        raise ValidationFailed("Full name is required")
    if not (email or phone):
        raise ValidationFailed("Give an email or a phone number")
    email = email.strip().lower() if email else None
    phone = phone.strip() if phone else None
    if email is not None and not EMAIL_PATTERN.match(email):
        raise ValidationFailed("Email address is not valid")
    if phone is not None and not PHONE_PATTERN.match(phone):
        raise ValidationFailed("Phone number is not valid (digits, optionally starting with +)")
    taken = s.execute(text("select 1 from kernel.app_user where lower(email) = :e or phone = :p"),
                      {"e": email, "p": phone}).first()
    if taken:
        raise Conflict("A user with this email or phone already exists")
    row = s.execute(text(
        "insert into kernel.app_user (tenant_id, created_by, email, phone, full_name, password_hash, status) "
        "values (kernel.current_tenant(), :by, :e, :p, :n, :h, :st) "
        "returning id, full_name, email, phone, status"),
        {"by": _actor(), "e": email, "p": phone, "n": full_name.strip(),
         "h": hash_password(password) if password else None, "st": "active" if password else "invited"}).one()
    user = User(**row._mapping)
    audit.record(s, "create", "kernel.app_user", user.id, {"email": email, "phone": phone, "name": user.full_name})
    directory.register(get_context().tenant_id, email, phone)             # so they can sign in without a workspace code
    return user


def list_users(s: Session) -> list[User]:
    """All users of the tenant."""
    rows = s.execute(text("select id, full_name, email, phone, status from kernel.app_user order by full_name"))
    return [User(**r._mapping) for r in rows]


def get_user(s: Session, user_id: UUID) -> User:
    """One user."""
    row = s.execute(text("select id, full_name, email, phone, status from kernel.app_user where id = :i"),
                    {"i": str(user_id)}).first()
    if row is None:
        raise NotFound("User not found")
    return User(**row._mapping)


def set_password(s: Session, user_id: UUID, password: str) -> None:
    """Set a user's password (activates an invited user) and sign them out everywhere."""
    user = get_user(s, user_id)
    if user.status == "disabled":
        raise ValidationFailed("The user is disabled")
    s.execute(text("update kernel.app_user set password_hash = :h, status = 'active', updated_at = now(), "
                   "updated_by = :by where id = :i"),
              {"h": hash_password(password), "by": _actor(), "i": str(user_id)})
    sign_out_user(s, user_id)
    audit.record(s, "set_password", "kernel.app_user", user_id)


def set_user_active(s: Session, user_id: UUID, active: bool) -> User:
    """Disable a user (signs them out everywhere) or enable them again."""
    user = get_user(s, user_id)
    if not active and user_id == get_context().user_id:
        raise ValidationFailed("You cannot disable yourself")
    status = "active" if active else "disabled"
    s.execute(text("update kernel.app_user set status = :st, updated_at = now(), updated_by = :by where id = :i"),
              {"st": status, "by": _actor(), "i": str(user_id)})
    if not active:
        sign_out_user(s, user_id)
    audit.record(s, "enable" if active else "disable", "kernel.app_user", user_id, {"status": [user.status, status]})
    return get_user(s, user_id)


# --------------------------------------------------------------------------- roles
def list_roles(s: Session) -> list[Role]:
    """Roles of the tenant with their permissions."""
    rows = s.execute(text(
        "select r.id, r.name, r.is_system, "
        "coalesce(array_agg(rp.permission_code order by rp.permission_code) "
        "         filter (where rp.permission_code is not null), '{}') as permissions "
        "from kernel.role r left join kernel.role_permission rp on rp.role_id = r.id "
        "group by r.id order by r.is_system desc, r.name"))
    return [Role(id=r.id, name=r.name, is_system=r.is_system, permissions=tuple(r.permissions)) for r in rows]


def get_role(s: Session, role_id: UUID) -> Role:
    """One role."""
    for role in list_roles(s):
        if role.id == role_id:
            return role
    raise NotFound("Role not found")


def check_can_give(permissions: list[str] | tuple[str, ...], company_id: UUID | None = None,
                   branch_id: UUID | None = None) -> None:
    """Raise Forbidden unless the actor holds every one of `permissions` over this scope."""
    ctx = get_context()
    missing = sorted(p for p in permissions if not ctx.can(p, company_id=company_id, branch_id=branch_id))
    if missing:
        raise Forbidden(f"You cannot give permissions you do not hold here: {', '.join(missing)}")


def check_permissions_exist(s: Session, permissions: list[str]) -> None:
    """Raise ValidationFailed if any permission code is not registered."""
    known = set(s.execute(text("select code from kernel.permission")).scalars())
    unknown = sorted(set(permissions) - known)
    if unknown:
        raise ValidationFailed(f"Unknown permissions: {', '.join(unknown)}")


def create_role(s: Session, name: str, permissions: list[str]) -> Role:
    """Create a custom role."""
    if not name.strip():
        raise ValidationFailed("Role name is required")
    check_permissions_exist(s, permissions)
    check_can_give(permissions)
    if s.execute(text("select 1 from kernel.role where lower(name) = lower(:n)"), {"n": name.strip()}).first():
        raise Conflict(f"Role '{name.strip()}' already exists")
    role_id: UUID = s.execute(text(
        "insert into kernel.role (tenant_id, created_by, name) values (kernel.current_tenant(), :by, :n) "
        "returning id"), {"by": _actor(), "n": name.strip()}).scalar_one()
    _write_permissions(s, role_id, permissions)
    audit.record(s, "create", "kernel.role", role_id, {"name": name.strip(), "permissions": sorted(permissions)})
    return get_role(s, role_id)


def set_role_permissions(s: Session, role_id: UUID, permissions: list[str]) -> Role:
    """Replace the permissions of a role. The Owner role cannot be changed."""
    role = get_role(s, role_id)
    if role.is_system and role.name == "Owner":
        raise ValidationFailed("The Owner role always has every permission")
    check_permissions_exist(s, permissions)
    changed = set(permissions) ^ set(role.permissions)
    check_can_give(sorted(changed))
    s.execute(text("delete from kernel.role_permission where role_id = :r"), {"r": str(role_id)})
    _write_permissions(s, role_id, permissions)
    audit.record(s, "set_permissions", "kernel.role", role_id,
                 {"before": list(role.permissions), "after": sorted(permissions)})
    return get_role(s, role_id)


def _write_permissions(s: Session, role_id: UUID, permissions: list[str]) -> None:
    for code in sorted(set(permissions)):
        s.execute(text("insert into kernel.role_permission (tenant_id, role_id, permission_code) "
                       "values (kernel.current_tenant(), :r, :c)"), {"r": str(role_id), "c": code})


# --------------------------------------------------------------------------- role grants
def _check_scope(s: Session, scope: str, company_id: UUID | None, branch_id: UUID | None) -> None:
    if scope not in SCOPES:
        raise ValidationFailed(f"Scope must be one of: {', '.join(SCOPES)}")
    if scope == "tenant" and (company_id or branch_id):
        raise ValidationFailed("A tenant-wide grant has no company or branch")
    if scope == "company" and (company_id is None or branch_id):
        raise ValidationFailed("A company grant needs a company and no branch")
    if scope == "branch" and (company_id is None or branch_id is None):
        raise ValidationFailed("A branch grant needs a company and a branch")
    if company_id and not s.execute(text("select 1 from kernel.company where id = :c"),
                                    {"c": str(company_id)}).first():
        raise ValidationFailed("Company not found")
    if branch_id and not s.execute(text("select 1 from kernel.branch where id = :b and company_id = :c"),
                                   {"b": str(branch_id), "c": str(company_id)}).first():
        raise ValidationFailed("Branch not found in that company")


def grant_role(s: Session, *, user_id: UUID, role_id: UUID, scope: str, company_id: UUID | None = None,
               branch_id: UUID | None = None) -> RoleGrant:
    """Give a user a role over the whole tenant, a company, a branch, or their own records."""
    get_user(s, user_id)
    role = get_role(s, role_id)
    _check_scope(s, scope, company_id, branch_id)
    check_can_give(role.permissions, company_id, branch_id)
    exists = s.execute(text(
        "select 1 from kernel.user_role where user_id = :u and role_id = :r "
        "and company_id is not distinct from :c and branch_id is not distinct from :b"),
        {"u": str(user_id), "r": str(role_id), "c": str(company_id) if company_id else None,
         "b": str(branch_id) if branch_id else None}).first()
    if exists:
        raise Conflict("The user already has this role here")
    grant_id: UUID = s.execute(text(
        "insert into kernel.user_role (tenant_id, created_by, user_id, role_id, company_id, branch_id, scope) "
        "values (kernel.current_tenant(), :by, :u, :r, :c, :b, :sc) returning id"),
        {"by": _actor(), "u": str(user_id), "r": str(role_id), "c": str(company_id) if company_id else None,
         "b": str(branch_id) if branch_id else None, "sc": scope}).scalar_one()
    audit.record(s, "grant_role", "kernel.app_user", user_id,
                 {"role": role.name, "scope": scope, "company_id": company_id, "branch_id": branch_id})
    return next(g for g in list_grants(s, user_id) if g.id == grant_id)


def list_grants(s: Session, user_id: UUID) -> list[RoleGrant]:
    """Roles a user holds."""
    rows = s.execute(text(
        "select ur.id, ur.user_id, ur.role_id, r.name as role_name, ur.scope, ur.company_id, ur.branch_id "
        "from kernel.user_role ur join kernel.role r on r.id = ur.role_id where ur.user_id = :u order by r.name"),
        {"u": str(user_id)})
    return [RoleGrant(**r._mapping) for r in rows]


def revoke_role(s: Session, grant_id: UUID) -> None:
    """Take a role away from a user. The last tenant-wide Owner cannot be removed."""
    row = s.execute(text(
        "select ur.user_id, ur.scope, r.name, r.is_system from kernel.user_role ur "
        "join kernel.role r on r.id = ur.role_id where ur.id = :i"), {"i": str(grant_id)}).first()
    if row is None:
        raise NotFound("Role grant not found")
    if row.is_system and row.name == "Owner" and row.scope == "tenant":
        owners = s.execute(text(
            "select count(*) from kernel.user_role ur join kernel.role r on r.id = ur.role_id "
            "join kernel.app_user u on u.id = ur.user_id "
            "where r.is_system and r.name = 'Owner' and ur.scope = 'tenant' and u.status = 'active' "
            "and ur.id <> :i"), {"i": str(grant_id)}).scalar_one()
        if owners < 1:
            raise ValidationFailed("The business must keep at least one owner")
    s.execute(text("delete from kernel.user_role where id = :i"), {"i": str(grant_id)})
    audit.record(s, "revoke_role", "kernel.app_user", row.user_id, {"role": row.name, "scope": row.scope})

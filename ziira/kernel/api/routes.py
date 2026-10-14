"""Kernel HTTP endpoints: sign-in, users, roles, API keys, numbering, reason codes, approvals.

Administration here is tenant-wide, so it needs the permission with a tenant-wide grant
(`admin(...)`); approval rules need it for the company they belong to.
"""

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import text

from ziira.kernel import (
    approvals,
    audit,
    auth,
    company_settings,
    exceptions_inbox,
    numbering,
    reasons,
    registration,
    users,
)
from ziira.kernel.api import schemas as sc
from ziira.kernel.context import RequestContext
from ziira.kernel.errors import Forbidden, NotFound, Unauthorized
from ziira.kernel.security import verify_password
from ziira.sdk import Session, db_session, page_limit, page_offset, request_context

router = APIRouter(prefix="/api/v1")
NO_CONTENT = status.HTTP_204_NO_CONTENT


def admin(permission: str) -> Callable[[RequestContext], RequestContext]:
    """Dependency: the actor must hold `permission` over the whole tenant."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        ctx.require(permission)
        return ctx

    return check


def signed_in_or_key(ctx: RequestContext = Depends(request_context)) -> RequestContext:
    """Dependency: any authenticated caller (user, API key, or the development header)."""
    return ctx


def signed_in_user(ctx: RequestContext = Depends(request_context)) -> RequestContext:
    """Dependency: a person signed in with a token (not an API key or the development header)."""
    if ctx.user_id is None or ctx.session_id is None:
        raise Unauthorized("Sign in as a user for this")
    return ctx


# --------------------------------------------------------------------------- auth
@router.post("/auth/sign-in", response_model=sc.TokensOut, tags=["Auth"])
def sign_in(body: sc.SignInIn, request: Request) -> object:
    """Sign in with an email or phone and the password. A workspace code is needed only when the same login works for
    more than one business (the reply then lists them and the client asks again with the chosen one)."""
    return auth.sign_in(body.workspace, body.login, body.password, device_id=body.device_id,
                        device_name=body.device_name, channel=body.channel, ip_address=auth.client_ip(request))


@router.post("/register", response_model=sc.RegisterOut, status_code=status.HTTP_202_ACCEPTED, tags=["Registration"])
def register(body: sc.RegisterIn, request: Request) -> object:
    """Ask for a business of your own. Nothing is created until the emailed link is used; the answer is the same
    whatever the address."""
    started = registration.register(
        business_name=body.business_name, owner_name=body.owner_name, email=body.email, password=body.password,
        currency=body.currency, phone_country_code=body.phone_country_code, country=body.country,
        tax_id=body.tax_id,
        invite_code=body.invite_code, ip_address=auth.client_ip(request))
    return sc.RegisterOut(message="Check your email for a link to finish creating your business.",
                          dev_token=started.dev_token)


@router.post("/register/verify", response_model=sc.RegisteredOut, tags=["Registration"])
def register_verify(body: sc.RegisterVerifyIn, request: Request) -> object:
    """Use the emailed link: the business and its own database are created and the owner is signed in."""
    done = registration.complete(body.token, device_id=body.device_id, device_name=body.device_name,
                                 ip_address=auth.client_ip(request))
    t = done.tokens
    return sc.RegisteredOut(access_token=t.access_token, refresh_token=t.refresh_token, expires_in=t.expires_in,
                            session_id=t.session_id, user_id=t.user_id, tenant_id=t.tenant_id,
                            workspace=done.workspace, business_name=done.business_name)


@router.post("/auth/refresh", response_model=sc.TokensOut, tags=["Auth"])
def refresh(body: sc.RefreshIn) -> object:
    """Swap a refresh token for new tokens (from the same device)."""
    return auth.refresh(body.refresh_token, body.device_id)


@router.post("/auth/sign-out", status_code=NO_CONTENT, tags=["Auth"])
def sign_out(ctx: RequestContext = Depends(signed_in_user), s: Session = Depends(db_session)) -> Response:
    """End this device's session."""
    assert ctx.session_id is not None
    auth.sign_out(s, ctx.session_id)
    audit.record(s, "logout", "kernel.app_user", ctx.user_id, {"session_id": ctx.session_id})
    return Response(status_code=NO_CONTENT)


@router.get("/auth/me", response_model=sc.MeOut, tags=["Auth"])
def me(ctx: RequestContext = Depends(request_context), s: Session = Depends(db_session)) -> object:
    """Who is signed in, with roles, scopes and permissions."""
    person = s.execute(text("select full_name, email from kernel.app_user where id = :u"),
                       {"u": str(ctx.user_id)}).first() if ctx.user_id else None
    return sc.MeOut(tenant_id=ctx.tenant_id, user_id=ctx.user_id, session_id=ctx.session_id, channel=ctx.channel,
                    full_name=person.full_name if person else None, email=person.email if person else None,
                    roles=[sc.AssignmentOut(role_id=a.role_id, role_name=a.role_name, scope=a.scope,
                                            company_id=a.company_id, branch_id=a.branch_id,
                                            permissions=sorted(a.permissions)) for a in ctx.assignments])


@router.get("/auth/sessions", response_model=list[sc.SessionOut], tags=["Auth"])
def my_sessions(ctx: RequestContext = Depends(signed_in_user), s: Session = Depends(db_session)) -> object:
    """Devices the current user is signed in on."""
    rows = s.execute(text(
        "select id, channel, device_id, device_name, created_at, last_used_at from kernel.user_session "
        "where user_id = :u and revoked_at is null and expires_at > now() order by last_used_at desc"),
        {"u": str(ctx.user_id)})
    return [sc.SessionOut(**r._mapping, current=r.id == ctx.session_id) for r in rows]


@router.delete("/auth/sessions/{session_id}", status_code=NO_CONTENT, tags=["Auth"])
def end_session(session_id: UUID, ctx: RequestContext = Depends(signed_in_user),
                s: Session = Depends(db_session)) -> Response:
    """Sign out one of your other devices (remote sign-out)."""
    owner = s.execute(text("select user_id from kernel.user_session where id = :i"), {"i": str(session_id)}).scalar()
    if owner != ctx.user_id:
        raise NotFound("Session not found")
    auth.sign_out(s, session_id)
    audit.record(s, "logout_remote", "kernel.app_user", ctx.user_id, {"session_id": session_id})
    return Response(status_code=NO_CONTENT)


@router.post("/auth/password", status_code=NO_CONTENT, tags=["Auth"])
def change_password(body: sc.ChangePasswordIn, ctx: RequestContext = Depends(signed_in_user),
                    s: Session = Depends(db_session)) -> Response:
    """Change your own password. Signs you out on every device."""
    stored = s.execute(text("select password_hash from kernel.app_user where id = :u"),
                       {"u": str(ctx.user_id)}).scalar()
    if not verify_password(body.current_password, stored):
        raise Unauthorized("Current password is wrong")
    assert ctx.user_id is not None
    users.set_password(s, ctx.user_id, body.new_password)
    return Response(status_code=NO_CONTENT)


# --------------------------------------------------------------------------- organisation
@router.get("/companies", response_model=list[sc.CompanyOut], tags=["Organisation"])
def list_companies(ctx: RequestContext = Depends(signed_in_or_key), s: Session = Depends(db_session)) -> object:
    """Companies and branches the user has any role in (all of them for a tenant-wide role)."""
    rows = s.execute(text(
        "select c.id, c.name, c.base_currency, c.country, b.id as branch_id, b.code, b.name as branch_name from kernel.company c "
        "left join kernel.branch b on b.company_id = c.id and b.is_active order by c.name, b.code")).all()
    reach = None if ctx.all_permissions or any(a.company_id is None and a.scope != "own" for a in ctx.assignments) \
        else {a.company_id for a in ctx.assignments}
    companies: dict[UUID, sc.CompanyOut] = {}
    for r in rows:
        if reach is not None and r.id not in reach:
            continue
        company = companies.setdefault(r.id, sc.CompanyOut(id=r.id, name=r.name, currency=r.base_currency, country=r.country, branches=[]))
        if r.branch_id:
            company.branches.append(sc.BranchOut(id=r.branch_id, code=r.code, name=r.branch_name))
    return list(companies.values())


@router.get("/companies/{company_id}/settings", response_model=sc.CompanySettingsOut, tags=["Organisation"])
def get_company_settings(company_id: UUID, ctx: RequestContext = Depends(request_context),
                         s: Session = Depends(db_session)) -> object:
    """Company policies such as negative stock. Needs 'settings.manage' for the company."""
    ctx.require("settings.manage", company_id=company_id)
    return company_settings.get_settings(s, company_id)


@router.patch("/companies/{company_id}/settings", response_model=sc.CompanySettingsOut, tags=["Organisation"])
def update_company_settings(company_id: UUID, body: sc.CompanySettingsIn,
                            ctx: RequestContext = Depends(request_context),
                            s: Session = Depends(db_session)) -> object:
    ctx.require("settings.manage", company_id=company_id)
    return company_settings.update_settings(s, company_id, body.model_dump(exclude_none=True))


# --------------------------------------------------------------------------- users
@router.get("/users", response_model=list[sc.UserOut], tags=["Users and roles"],
            dependencies=[Depends(admin("users.manage"))])
def list_users(s: Session = Depends(db_session)) -> object:
    return users.list_users(s)


@router.post("/users", response_model=sc.UserOut, status_code=201, tags=["Users and roles"],
             dependencies=[Depends(admin("users.manage"))])
def create_user(body: sc.UserIn, s: Session = Depends(db_session)) -> object:
    return users.create_user(s, full_name=body.full_name, email=body.email, phone=body.phone,
                             password=body.password)


@router.post("/users/{user_id}/status", response_model=sc.UserOut, tags=["Users and roles"],
             dependencies=[Depends(admin("users.manage"))])
def set_user_status(user_id: UUID, body: sc.UserStatusIn, s: Session = Depends(db_session)) -> object:
    """Disable a user (signs them out everywhere) or enable them again."""
    return users.set_user_active(s, user_id, body.active)


@router.post("/users/{user_id}/password", status_code=NO_CONTENT, tags=["Users and roles"],
             dependencies=[Depends(admin("users.manage"))])
def set_user_password(user_id: UUID, body: sc.PasswordIn, s: Session = Depends(db_session)) -> Response:
    users.set_password(s, user_id, body.password)
    return Response(status_code=NO_CONTENT)


@router.get("/users/{user_id}/roles", response_model=list[sc.GrantOut], tags=["Users and roles"],
            dependencies=[Depends(admin("users.manage"))])
def list_user_roles(user_id: UUID, s: Session = Depends(db_session)) -> object:
    return users.list_grants(s, user_id)


@router.post("/users/{user_id}/roles", response_model=sc.GrantOut, status_code=201, tags=["Users and roles"],
             dependencies=[Depends(admin("users.manage"))])
def grant_role(user_id: UUID, body: sc.GrantIn, s: Session = Depends(db_session)) -> object:
    """Give a user a role over the tenant, a company, a branch, or their own records."""
    return users.grant_role(s, user_id=user_id, role_id=body.role_id, scope=body.scope,
                            company_id=body.company_id, branch_id=body.branch_id)


@router.delete("/users/{user_id}/roles/{grant_id}", status_code=NO_CONTENT, tags=["Users and roles"],
               dependencies=[Depends(admin("users.manage"))])
def revoke_role(user_id: UUID, grant_id: UUID, s: Session = Depends(db_session)) -> Response:
    if grant_id not in {g.id for g in users.list_grants(s, user_id)}:
        raise NotFound("Role grant not found")
    users.revoke_role(s, grant_id)
    return Response(status_code=NO_CONTENT)


# --------------------------------------------------------------------------- roles and permissions
@router.get("/roles", response_model=list[sc.RoleOut], tags=["Users and roles"],
            dependencies=[Depends(admin("roles.manage"))])
def list_roles(s: Session = Depends(db_session)) -> object:
    return users.list_roles(s)


@router.post("/roles", response_model=sc.RoleOut, status_code=201, tags=["Users and roles"],
             dependencies=[Depends(admin("roles.manage"))])
def create_role(body: sc.RoleIn, s: Session = Depends(db_session)) -> object:
    return users.create_role(s, body.name, body.permissions)


@router.put("/roles/{role_id}/permissions", response_model=sc.RoleOut, tags=["Users and roles"],
            dependencies=[Depends(admin("roles.manage"))])
def set_role_permissions(role_id: UUID, body: sc.RolePermissionsIn, s: Session = Depends(db_session)) -> object:
    return users.set_role_permissions(s, role_id, body.permissions)


@router.get("/permissions", response_model=list[sc.PermissionOut], tags=["Users and roles"],
            dependencies=[Depends(admin("roles.manage"))])
def list_permissions(s: Session = Depends(db_session)) -> object:
    """Permissions of the kernel and of every installed unit."""
    return [sc.PermissionOut(**r._mapping) for r in s.execute(text(
        "select code, unit_name, description from kernel.permission order by unit_name, code"))]


# --------------------------------------------------------------------------- API keys
@router.get("/api-keys", response_model=list[sc.ApiKeyOut], tags=["Integrations"],
            dependencies=[Depends(admin("api_keys.manage"))])
def list_api_keys(s: Session = Depends(db_session)) -> object:
    return [sc.ApiKeyOut(**r._mapping) for r in s.execute(text(
        "select id, name, scopes, created_at, expires_at, revoked_at from kernel.api_key order by created_at"))]


@router.post("/api-keys", response_model=sc.ApiKeyCreatedOut, status_code=201, tags=["Integrations"],
             dependencies=[Depends(admin("api_keys.manage"))])
def create_api_key(body: sc.ApiKeyIn, ctx: RequestContext = Depends(request_context),
                   s: Session = Depends(db_session)) -> object:
    """Create a key for a server-to-server integration. The key is shown only in this response."""
    users.check_permissions_exist(s, body.scopes)
    users.check_can_give(body.scopes)
    key_id, key = auth.create_api_key(s, ctx.tenant_id, body.name, body.scopes, body.expires_at)
    audit.record(s, "create", "kernel.api_key", key_id, {"name": body.name, "scopes": body.scopes})
    return sc.ApiKeyCreatedOut(id=key_id, key=key)


@router.delete("/api-keys/{key_id}", status_code=NO_CONTENT, tags=["Integrations"],
               dependencies=[Depends(admin("api_keys.manage"))])
def revoke_api_key(key_id: UUID, s: Session = Depends(db_session)) -> Response:
    if s.execute(text("update kernel.api_key set revoked_at = now() where id = :i and revoked_at is null "
                      "returning id"), {"i": str(key_id)}).first() is None:
        raise NotFound("API key not found")
    audit.record(s, "revoke", "kernel.api_key", key_id)
    return Response(status_code=NO_CONTENT)


# --------------------------------------------------------------------------- numbering and reason codes
@router.get("/settings/document-series", response_model=list[sc.SeriesOut], tags=["Settings"],
            dependencies=[Depends(admin("settings.manage"))])
def list_series(s: Session = Depends(db_session)) -> object:
    return numbering.list_series(s)


@router.patch("/settings/document-series/{series_id}", response_model=sc.SeriesOut, tags=["Settings"],
              dependencies=[Depends(admin("settings.manage"))])
def update_series(series_id: UUID, body: sc.SeriesUpdateIn, s: Session = Depends(db_session)) -> object:
    series = numbering.update_series(s, series_id, prefix=body.prefix, padding=body.padding,
                                     next_number=body.next_number)
    audit.record(s, "update", "kernel.document_series", series_id, body.model_dump(exclude_none=True))
    return series


@router.get("/settings/reason-codes", response_model=list[sc.ReasonOut], tags=["Settings"])
def list_reason_codes(category: str | None = None, include_inactive: bool = False,
                      s: Session = Depends(db_session)) -> object:
    """Reason codes to choose from. Any signed-in user may read them."""
    return reasons.list_reasons(s, category, include_inactive)


@router.post("/settings/reason-codes", response_model=sc.ReasonOut, status_code=201, tags=["Settings"],
             dependencies=[Depends(admin("settings.manage"))])
def create_reason_code(body: sc.ReasonIn, s: Session = Depends(db_session)) -> object:
    reason = reasons.create_reason(s, body.category, body.code, body.label, body.requires_note)
    audit.record(s, "create", "kernel.reason_code", reason.id, body.model_dump())
    return reason


@router.post("/settings/reason-codes/{reason_id}/active", status_code=NO_CONTENT, tags=["Settings"],
             dependencies=[Depends(admin("settings.manage"))])
def set_reason_active(reason_id: UUID, body: sc.ActiveIn, s: Session = Depends(db_session)) -> Response:
    reasons.set_reason_active(s, reason_id, body.active)
    audit.record(s, "activate" if body.active else "deactivate", "kernel.reason_code", reason_id)
    return Response(status_code=NO_CONTENT)


# --------------------------------------------------------------------------- approvals
@router.get("/approvals/rules", response_model=list[sc.RuleOut], tags=["Approvals"])
def list_rules(company_id: UUID | None = None, ctx: RequestContext = Depends(request_context),
               s: Session = Depends(db_session)) -> object:
    ctx.require("approvals.manage", company_id=company_id)
    return approvals.list_rules(s, company_id)


@router.post("/approvals/rules", response_model=sc.RuleOut, status_code=201, tags=["Approvals"])
def create_rule(body: sc.RuleIn, ctx: RequestContext = Depends(request_context),
                s: Session = Depends(db_session)) -> object:
    """Add a row to a company's approval matrix."""
    ctx.require("approvals.manage", company_id=body.company_id)
    return approvals.create_rule(s, **body.model_dump())


@router.post("/approvals/rules/{rule_id}/active", status_code=NO_CONTENT, tags=["Approvals"])
def set_rule_active(rule_id: UUID, body: sc.ActiveIn, ctx: RequestContext = Depends(request_context),
                    s: Session = Depends(db_session)) -> Response:
    company_id = s.execute(text("select company_id from kernel.approval_rule where id = :i"),
                           {"i": str(rule_id)}).scalar()
    if company_id is None:
        raise NotFound("Approval rule not found")
    ctx.require("approvals.manage", company_id=company_id)
    approvals.set_rule_active(s, rule_id, body.active)
    return Response(status_code=NO_CONTENT)


@router.get("/approvals/pending", response_model=list[sc.RequestOut], tags=["Approvals"])
def pending_approvals(_: RequestContext = Depends(signed_in_user), s: Session = Depends(db_session)) -> object:
    """Requests waiting for a role you hold."""
    return approvals.pending_for_me(s)


@router.post("/approvals/{request_id}/decision", response_model=sc.RequestOut, tags=["Approvals"])
def decide(request_id: UUID, body: sc.DecisionIn, _: RequestContext = Depends(signed_in_user),
           s: Session = Depends(db_session)) -> object:
    """Approve or reject. You must hold the approver role; you cannot approve your own request."""
    return approvals.decide(s, request_id, approve=body.approve, note=body.note)


# --------------------------------------------------------------------------- exceptions inbox
def exceptions_manager(ctx: RequestContext = Depends(request_context)) -> RequestContext:
    """Dependency: the actor may work the exceptions inbox somewhere (the service limits it to their branches)."""
    if not ctx.has_anywhere("exceptions.manage"):
        raise Forbidden("You do not have permission 'exceptions.manage'")
    return ctx


MANAGE_EXCEPTIONS = [Depends(exceptions_manager)]


@router.get("/exceptions", response_model=list[sc.ExceptionItemOut], tags=["Exceptions"],
            dependencies=MANAGE_EXCEPTIONS)
def list_exceptions(status_: str | None = Query(default=None, alias="status"), unit: str | None = None,
                    kind: str | None = None, branch_id: UUID | None = None, limit: int = page_limit(),
                    offset: int = page_offset(), s: Session = Depends(db_session)) -> object:
    """Things that need a person's attention, newest first, for the branches the user manages."""
    return exceptions_inbox.list_items(s, status=status_, unit=unit, kind=kind, branch_id=branch_id, limit=limit,
                                       offset=offset)


@router.get("/exceptions/{item_id}", response_model=sc.ExceptionItemOut, tags=["Exceptions"],
            dependencies=MANAGE_EXCEPTIONS)
def get_exception(item_id: UUID, s: Session = Depends(db_session)) -> object:
    return exceptions_inbox.get_item(s, item_id)


@router.post("/exceptions/{item_id}/status", response_model=sc.ExceptionItemOut, tags=["Exceptions"],
             dependencies=MANAGE_EXCEPTIONS)
def set_exception_status(item_id: UUID, body: sc.ExceptionStatusIn, s: Session = Depends(db_session)) -> object:
    """Explain, resolve or dismiss an item (a note is required)."""
    return exceptions_inbox.change_status(s, item_id, body.status, body.note)


@router.post("/exceptions/{item_id}/assign", response_model=sc.ExceptionItemOut, tags=["Exceptions"],
             dependencies=MANAGE_EXCEPTIONS)
def assign_exception(item_id: UUID, body: sc.ExceptionAssignIn, s: Session = Depends(db_session)) -> object:
    return exceptions_inbox.assign(s, item_id, body.user_id)

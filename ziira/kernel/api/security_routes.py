"""Sign-in security endpoints: the second factor, forgotten passwords, and the business's security policy."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from ziira.kernel import auth, mfa, password_reset, passwords, throttle, users
from ziira.kernel.api import schemas as sc
from ziira.kernel.api.routes import NO_CONTENT, admin, signed_in_user
from ziira.kernel.context import RequestContext
from ziira.kernel.errors import Unauthorized, ValidationFailed
from ziira.kernel.security import verify_password
from ziira.sdk import DB_SESSION, Session

router = APIRouter(prefix="/api/v1")
USERS_ADMIN = Depends(admin("users.manage"))
SETTINGS_ADMIN = Depends(admin("settings.manage"))


class MfaVerifyIn(BaseModel):
    challenge: str
    code: str = Field(max_length=64)


class MfaStatusOut(BaseModel):
    enabled: bool
    backup_codes_left: int
    policy: str
    required: bool


class MfaSetupOut(BaseModel):
    secret: str = Field(description="The shared secret, for typing into an authenticator app")
    otpauth_uri: str = Field(description="The address to show as a QR code")


class MfaCodeIn(BaseModel):
    code: str = Field(max_length=64)


class MfaBackupCodesOut(BaseModel):
    backup_codes: list[str] = Field(description="Shown once: each works once, when the app is not at hand")


class MfaDisableIn(BaseModel):
    password: str = Field(max_length=1024)
    code: str = Field(max_length=64)


class SecuritySettingsOut(BaseModel):
    mfa_policy: str


class SecuritySettingsIn(BaseModel):
    mfa_policy: str = Field(description="off, privileged (people with powerful roles) or everyone")


class ForgotIn(BaseModel):
    login: str = Field(max_length=254, description="The email or phone you sign in with")


class PasswordCheckIn(BaseModel):
    password: str = Field(max_length=1024)
    login: str | None = Field(default=None, max_length=254, description="The email it will be used with")


class PasswordCheckOut(BaseModel):
    ok: bool
    message: str | None = Field(default=None, description="Why it is not acceptable, in plain words")


class ForgotOut(BaseModel):
    message: str
    dev_token: str | None = Field(default=None, description="Development only: the link's token (no email is read)")


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(max_length=1024)


# --------------------------------------------------------------------------- the second factor
@router.post("/auth/mfa/verify", response_model=sc.TokensOut, tags=["Auth"])
def mfa_verify(body: MfaVerifyIn, request: Request) -> object:
    """Second step of signing in when the person uses a second factor: the `challenge` from the password step, and a
    code from their authenticator app (or a backup code)."""
    return auth.complete_mfa(body.challenge, body.code, ip_address=auth.client_ip(request))


@router.get("/auth/mfa", response_model=MfaStatusOut, tags=["Auth"])
def mfa_status(ctx: RequestContext = Depends(signed_in_user), s: Session = DB_SESSION) -> object:
    assert ctx.user_id is not None
    return mfa.status(s, ctx.user_id)


def _account(s: Session, user_id: UUID) -> str:
    from sqlalchemy import text

    row = s.execute(text("select coalesce(email, phone, full_name) as a from kernel.app_user where id = :u"),
                    {"u": str(user_id)}).one()
    return str(row.a)


@router.post("/auth/mfa/setup", response_model=MfaSetupOut, tags=["Auth"])
def mfa_setup(ctx: RequestContext = Depends(signed_in_user), s: Session = DB_SESSION) -> object:
    """Start setting up the second factor: returns the secret and the address for a QR code. Switched on only when a
    code from the app is confirmed at /auth/mfa/enable."""
    assert ctx.user_id is not None
    secret, uri = mfa.setup(s, ctx.user_id, _account(s, ctx.user_id))
    return MfaSetupOut(secret=secret, otpauth_uri=uri)


@router.post("/auth/mfa/enable", response_model=MfaBackupCodesOut, tags=["Auth"])
def mfa_enable(body: MfaCodeIn, request: Request, ctx: RequestContext = Depends(signed_in_user),
               s: Session = DB_SESSION) -> object:
    """Confirm a code from the app: switches the second factor on and returns backup codes (shown once)."""
    assert ctx.user_id is not None
    counters = throttle.action_counters("mfa-enable", str(ctx.user_id), auth.client_ip(request), per_subject=10)
    throttle.guard(counters)
    try:
        codes = mfa.enable(s, ctx.user_id, body.code)
    except ValidationFailed:
        throttle.failed(counters)
        raise
    return MfaBackupCodesOut(backup_codes=codes)


def _confirm(s: Session, ctx: RequestContext, password: str, code: str) -> None:
    """Both the password and a current code, for the things that weaken or renew the second factor."""
    from sqlalchemy import text

    assert ctx.user_id is not None
    stored = s.execute(text("select password_hash from kernel.app_user where id = :u"),
                       {"u": str(ctx.user_id)}).scalar()
    counters = throttle.action_counters("mfa-confirm", str(ctx.user_id), ctx.ip_address, per_subject=5)
    throttle.guard(counters)
    if not verify_password(password, stored) or not mfa.verify(s, ctx.user_id, code):
        throttle.failed(counters)
        raise Unauthorized("The password or the code is wrong")


@router.post("/auth/mfa/disable", status_code=NO_CONTENT, tags=["Auth"])
def mfa_disable(body: MfaDisableIn, ctx: RequestContext = Depends(signed_in_user),
                s: Session = DB_SESSION) -> Response:
    """Switch the second factor off (needs your password and a code). Refused if your business requires it."""
    assert ctx.user_id is not None
    if mfa.required_for(s, ctx.user_id):
        raise ValidationFailed("Your business requires two-step verification for you: it cannot be switched off")
    _confirm(s, ctx, body.password, body.code)
    mfa.disable(s, ctx.user_id)
    return Response(status_code=NO_CONTENT)


@router.post("/auth/mfa/backup-codes", response_model=MfaBackupCodesOut, tags=["Auth"])
def mfa_new_backup_codes(body: MfaDisableIn, ctx: RequestContext = Depends(signed_in_user),
                         s: Session = DB_SESSION) -> object:
    """Replace your backup codes with new ones (needs your password and a code). The old ones stop working."""
    assert ctx.user_id is not None
    _confirm(s, ctx, body.password, body.code)
    return MfaBackupCodesOut(backup_codes=mfa.regenerate_backup_codes(s, ctx.user_id))


@router.post("/users/{user_id}/mfa/reset", status_code=NO_CONTENT, tags=["Users and roles"])
def mfa_reset(user_id: UUID, ctx: RequestContext = USERS_ADMIN,
              s: Session = DB_SESSION) -> Response:
    """Reset someone's second factor (they lost their phone): switches it off and signs them out everywhere. They set it
    up again at their next sign-in if the business requires it."""
    users.get_user(s, user_id)
    mfa.disable(s, user_id, by_admin=True)
    auth.sign_out_user(s, user_id)
    return Response(status_code=NO_CONTENT)


# --------------------------------------------------------------------------- the business's policy
@router.get("/settings/security", response_model=SecuritySettingsOut, tags=["Settings"])
def get_security(ctx: RequestContext = SETTINGS_ADMIN, s: Session = DB_SESSION) -> object:
    return SecuritySettingsOut(mfa_policy=mfa.policy(s))


@router.patch("/settings/security", response_model=SecuritySettingsOut, tags=["Settings"])
def patch_security(body: SecuritySettingsIn, ctx: RequestContext = SETTINGS_ADMIN,
                   s: Session = DB_SESSION) -> object:
    """Choose who must sign in with a second factor. People it applies to who have not set it up are asked to at their
    next sign-in (and cannot do anything else until they have)."""
    return SecuritySettingsOut(mfa_policy=mfa.set_policy(s, body.mfa_policy))


# --------------------------------------------------------------------------- forgotten passwords
@router.post("/auth/password/check", response_model=PasswordCheckOut, tags=["Auth"])
def check_password(body: PasswordCheckIn, request: Request) -> object:
    """Say whether a password would be accepted, so a sign-up form can tell the person at once (nothing is stored)."""
    counters = throttle.action_counters("pwcheck", "any", auth.client_ip(request), per_subject=100000, per_ip=120)
    throttle.guard(counters)
    throttle.failed(counters)
    try:
        passwords.check(body.password, login=body.login)
    except ValidationFailed as problem:
        return PasswordCheckOut(ok=False, message=str(problem))
    return PasswordCheckOut(ok=True)


@router.post("/auth/password/forgot", response_model=ForgotOut, status_code=status.HTTP_202_ACCEPTED, tags=["Auth"])
def forgot_password(body: ForgotIn, request: Request) -> object:
    """Ask for an email with a link to choose a new password. The answer is the same whether or not the login exists."""
    done = password_reset.request(body.login, ip_address=auth.client_ip(request))
    message = "If that login has an email address on file, a link to choose a new password is on its way."
    return ForgotOut(message=message, dev_token=done.dev_token)


@router.post("/auth/password/reset", status_code=NO_CONTENT, tags=["Auth"])
def reset_password(body: ResetIn, request: Request) -> Response:
    """Use the emailed link to choose a new password. Signs the person out everywhere."""
    password_reset.complete(body.token, body.new_password, ip_address=auth.client_ip(request))
    return Response(status_code=NO_CONTENT)


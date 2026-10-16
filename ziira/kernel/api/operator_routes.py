"""Platform staff endpoints: sign in (email and password; then a code from the authenticator app when
`ZIIRA_OPERATOR_MFA=totp`), change the password, and open a support session in a business that has given access.
These tokens are not business tokens: a business token is refused here and an operator token is refused everywhere
else."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import operators
from ziira.kernel.auth import client_ip
from ziira.kernel.config import get_settings
from ziira.kernel.errors import Forbidden, Unauthorized
from ziira.kernel.platform import permissions

router = APIRouter(prefix="/api/v1/operator", tags=["Operators"])


class PasswordChangeRequired(Forbidden):
    """A temporary password was used: the only things allowed are changing it and signing out."""

    code = "password_change_required"


# What an operator who must change their password may still call.
WHILE_PASSWORD_CHANGE_PENDING = frozenset({
    "/api/v1/operator/me", "/api/v1/operator/password", "/api/v1/operator/sign-out",
    "/api/v1/operator/sign-out-all"})


def current_operator(request: Request, authorization: str | None = Header(default=None)) -> operators.Operator:
    """Dependency: a signed-in member of platform staff."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Sign in first")
    operator = operators.operator_from_token(token.strip())
    if operator.must_change_password and request.url.path not in WHILE_PASSWORD_CHANGE_PENDING:
        raise PasswordChangeRequired("Choose a new password before you continue")
    return operator


def require(permission: str) -> Callable[[operators.Operator], operators.Operator]:
    """FastAPI dependency: `Depends(require("platform.plans"))` is a signed-in operator whose role holds the permission.
    Every operator route except sign-in and the operator's own session calls declares one;
    `tests/test_platform_roles.py`
    walks the routes and fails if one does not, then calls each with every role."""
    if permission not in permissions.PERMISSIONS:
        raise ValueError(f"Unknown platform permission {permission}")

    def check(operator: operators.Operator = Depends(current_operator)) -> operators.Operator:
        permissions.check(operator.role, permission)
        return operator

    check.platform_permission = permission          # type: ignore[attr-defined]  # read by the role matrix test
    return check


class OperatorSignInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class SignInOut(BaseModel):
    """Either `challenge` (send it back with the code from the authenticator app) or, when the platform signs staff in
    with a password alone, the finished session."""

    challenge: str | None = Field(default=None, description="Send this back with the code from the authenticator app")
    access_token: str | None = None
    expires_in: int | None = None
    must_change_password: bool = Field(default=False, description="A temporary password: change it first")


class OperatorMfaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge: str = Field(max_length=2000)
    code: str = Field(max_length=64)


class OperatorTokenOut(BaseModel):
    access_token: str
    expires_in: int


class PasswordChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=operators.MIN_PASSWORD_LENGTH, max_length=1024)


class BusinessOut(BaseModel):
    code: str
    name: str


class OpenSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant_id: UUID | None = Field(default=None, description="Which grant (default: the most permissive active one)")


class SupportSessionOut(BaseModel):
    access_token: str
    session_id: UUID
    tenant_id: UUID
    business: str
    level: str
    expires_at: datetime


class OperatorSessionOut(BaseModel):
    id: UUID
    business: str | None
    started_at: datetime
    expires_at: datetime | None
    ended_at: datetime | None
    level: str | None
    requests: int


@router.post("/sign-in", response_model=SignInOut, response_model_exclude_none=True)
def sign_in(body: OperatorSignInIn, request: Request, background: BackgroundTasks) -> object:
    """Email and password. With a second factor the answer is a challenge for `/mfa/verify`; with a password alone
    (the default) it is the signed-in session."""
    ip = client_ip(request)
    result = operators.sign_in(body.email, body.password, ip_address=ip)
    if result.new_address and get_settings().operator_signin_emails and result.access_token:
        background.add_task(operators.tell_new_address, body.email.strip().lower(), result.name, ip)
    return SignInOut(challenge=result.challenge, access_token=result.access_token, expires_in=result.expires_in,
                     must_change_password=result.must_change_password)


@router.post("/mfa/verify", response_model=OperatorTokenOut)
def verify(body: OperatorMfaIn, request: Request) -> object:
    """Step two, when a second factor is required: the code from the authenticator app."""
    token, seconds = operators.verify_mfa(body.challenge, body.code, ip_address=client_ip(request))
    return OperatorTokenOut(access_token=token, expires_in=seconds)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChangeIn, request: Request,
                    operator: operators.Operator = Depends(current_operator)) -> Response:
    """Change your own password (needs the current one). Your other sign-ins end."""
    operators.change_password(operator, body.current_password, body.new_password, ip_address=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(request: Request, operator: operators.Operator = Depends(current_operator)) -> Response:
    operators.sign_out(operator, ip_address=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sign-out-all", status_code=status.HTTP_204_NO_CONTENT)
def sign_out_all(request: Request, operator: operators.Operator = Depends(current_operator)) -> Response:
    """End every sign-in of yours, on every device, this one included."""
    operators.sign_out_everywhere(operator, ip_address=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/businesses", response_model=list[BusinessOut])
def businesses(_: operators.Operator = Depends(require("platform.subscribers"))) -> object:
    """Code and name of each business. Never any of their data."""
    return operators.list_businesses()


@router.post("/businesses/{code}/support-session", response_model=SupportSessionOut, status_code=201)
def open_session(code: str, request: Request, body: OpenSessionIn | None = None,
                 operator: operators.Operator = Depends(require("platform.subscribers"))) -> object:
    """Open the business under an active support grant. 403 when the business has not given access (or it ended)."""
    return operators.open_support_session(operator, code, grant_id=body.grant_id if body else None,
                                          ip_address=client_ip(request))


@router.get("/sessions", response_model=list[OperatorSessionOut])
def sessions(operator: operators.Operator = Depends(require("platform.subscribers"))) -> object:
    """Your own support sessions, newest first."""
    return operators.list_sessions(operator)


@router.post("/sessions/{session_id}/end", status_code=status.HTTP_204_NO_CONTENT)
def end_session(session_id: UUID, operator: operators.Operator = Depends(require("platform.subscribers"))) -> Response:
    """Close one of your support sessions."""
    operators.end_session(operator, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

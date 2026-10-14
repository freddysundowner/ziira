"""Platform staff endpoints: sign in (password, then a code from the authenticator app) and open a support session in a
business that has given access. These tokens are not business tokens: a business token is refused here and an
operator token is refused everywhere else."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import operators
from ziira.kernel.auth import client_ip
from ziira.kernel.errors import Unauthorized

router = APIRouter(prefix="/api/v1/operator", tags=["Operators"])


def current_operator(authorization: str | None = Header(default=None)) -> operators.Operator:
    """Dependency: a signed-in member of platform staff."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Sign in first")
    return operators.operator_from_token(token.strip())


class OperatorSignInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class ChallengeOut(BaseModel):
    challenge: str = Field(description="Send this back with the code from the authenticator app")


class OperatorMfaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge: str = Field(max_length=2000)
    code: str = Field(max_length=64)


class OperatorTokenOut(BaseModel):
    access_token: str
    expires_in: int


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


@router.post("/sign-in", response_model=ChallengeOut)
def sign_in(body: OperatorSignInIn, request: Request) -> object:
    """Step one: email and password. The answer is a challenge; there is no way in without the second factor."""
    return ChallengeOut(challenge=operators.sign_in(body.email, body.password, ip_address=client_ip(request)))


@router.post("/mfa/verify", response_model=OperatorTokenOut)
def verify(body: OperatorMfaIn, request: Request) -> object:
    """Step two: the code from the authenticator app."""
    token, seconds = operators.verify_mfa(body.challenge, body.code, ip_address=client_ip(request))
    return OperatorTokenOut(access_token=token, expires_in=seconds)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(operator: operators.Operator = Depends(current_operator)) -> Response:
    operators.sign_out(operator)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/businesses", response_model=list[BusinessOut])
def businesses(_: operators.Operator = Depends(current_operator)) -> object:
    """Code and name of each business. Never any of their data."""
    return operators.list_businesses()


@router.post("/businesses/{code}/support-session", response_model=SupportSessionOut, status_code=201)
def open_session(code: str, request: Request, body: OpenSessionIn | None = None,
                 operator: operators.Operator = Depends(current_operator)) -> object:
    """Open the business under an active support grant. 403 when the business has not given access (or it ended)."""
    return operators.open_support_session(operator, code, grant_id=body.grant_id if body else None,
                                          ip_address=client_ip(request))


@router.get("/sessions", response_model=list[OperatorSessionOut])
def sessions(operator: operators.Operator = Depends(current_operator)) -> object:
    """Your own support sessions, newest first."""
    return operators.list_sessions(operator)


@router.post("/sessions/{session_id}/end", status_code=status.HTTP_204_NO_CONTENT)
def end_session(session_id: UUID, operator: operators.Operator = Depends(current_operator)) -> Response:
    """Close one of your support sessions."""
    operators.end_session(operator, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

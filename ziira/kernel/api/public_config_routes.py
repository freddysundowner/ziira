"""The few non-secret platform values the web app needs before anyone signs in: sign-up state and links."""

from fastapi import APIRouter, Response
from pydantic import BaseModel

from ziira.kernel.platform import behaviour

router = APIRouter(prefix="/api/v1/public", tags=["Pricing"])


class PublicConfig(BaseModel):
    registration: str
    terms_url: str
    privacy_url: str
    help_url: str
    site_url: str
    support_email: str


@router.get("/config", response_model=PublicConfig)
def public_config(response: Response) -> object:
    """Whether sign-up is open, invitation only or closed, and the terms, privacy, help and website links."""
    response.headers["Cache-Control"] = "public, max-age=30"
    links = {k: str(behaviour.get(f"public.{k}")) for k in
             ("terms_url", "privacy_url", "help_url", "site_url", "support_email")}
    return {"registration": behaviour.registration_mode(), **links}

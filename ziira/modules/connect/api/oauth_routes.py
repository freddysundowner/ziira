"""OAuth endpoints for connectors that authorise through a browser redirect (Zoho Books, QuickBooks Online).

Flow
1. The business creates a connection of that kind (name, company, data centre or environment) in the usual way.
2. `POST /oauth/{kind}/start` {connection_id, client_id?, client_secret?} returns the vendor's authorisation address.
   The state in it is signed (`sign_value`), expires after 15 minutes and carries the tenant, connection, user and a
   one-time nonce. Nothing secret is placed in any address: the client secret the business typed, and the nonce, are
   kept encrypted with the connection's other secrets.
3. The vendor sends the browser to `GET /oauth/callback` (public: the signed state is the proof). We swap the one-time
   code for tokens (not inside a database transaction), store them encrypted on the connection, and redirect to the
   web app's connection page with `oauth=success` or `oauth=failed&reason=<code>`.

Platform-level app credentials (`ZIIRA_OAUTH_<KIND>_CLIENT_ID` / `_CLIENT_SECRET`, for example
`ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_ID`) are preferred when set; otherwise the business supplies its own.
"""

import base64
import json
import logging
import os
import secrets as token_source
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, SecretStr

from ziira.modules.connect.connectors import _http as h
from ziira.modules.connect.connectors.quickbooks import QuickBooksConnector
from ziira.modules.connect.connectors.zoho_books import ZohoBooksConnector
from ziira.modules.connect.permissions import CONNECT_MANAGE
from ziira.modules.connect.public import Connector, ConnectorError
from ziira.modules.connect.repository import connect_repo as repo
from ziira.modules.connect.services import connections, connectors
from ziira.sdk import (
    DB_SESSION,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    platform_settings,
    require_permission,
    settings_public_base_url,
    sign_value,
    system_session,
    verify_value,
)

log = logging.getLogger("ziira.connect.oauth")

router = APIRouter()
public_router = APIRouter()
MANAGE = [Depends(require_permission(CONNECT_MANAGE))]

STATE_MINUTES = 15
CALLBACK_PATH = "/api/v1/connect/oauth/callback"
WEB_PATH = "/connect/connections/{connection_id}"      # the web app's connection page
NONCE_KEY = "_oauth_nonce"
OAUTH_KINDS = {"zoho_books": ZohoBooksConnector, "quickbooks": QuickBooksConnector}


# --------------------------------------------------------------------------- the signed state
@dataclass(frozen=True)
class OAuthState:
    tenant_id: UUID
    connection_id: UUID
    user_id: UUID | None
    kind: str
    nonce: str
    expires_at: int


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_state(*, tenant_id: UUID, connection_id: UUID, user_id: UUID | None, kind: str, nonce: str,
               now: float | None = None) -> str:
    """`<payload>.<signature>`: tamper-proof (the signature covers the payload), expiring, bound to one connection."""
    body = {"t": str(tenant_id), "c": str(connection_id), "u": str(user_id) if user_id else None, "k": kind,
            "n": nonce, "e": int((time.time() if now is None else now) + STATE_MINUTES * 60)}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{sign_value('connect-oauth:' + payload)}"


def read_state(state: str, *, now: float | None = None) -> OAuthState:
    """The state's content, or ValidationFailed if it was altered, is malformed or has expired."""
    payload, _, signature = state.partition(".")
    # compare_digest refuses non-ASCII text, and a public address can be given anything
    if not payload or not signature or not signature.isascii() or not payload.isascii() or not verify_value(
            "connect-oauth:" + payload, signature):
        raise ValidationFailed("This approval link is not valid")
    try:
        body = json.loads(_unb64(payload))
        result = OAuthState(tenant_id=UUID(body["t"]), connection_id=UUID(body["c"]),
                            user_id=UUID(body["u"]) if body.get("u") else None, kind=str(body["k"]),
                            nonce=str(body["n"]), expires_at=int(body["e"]))
    except (ValueError, KeyError, TypeError):
        raise ValidationFailed("This approval link is not valid") from None
    if (time.time() if now is None else now) > result.expires_at:
        raise ValidationFailed("This approval link has expired. Start again.")
    return result


# --------------------------------------------------------------------------- app credentials and addresses
def platform_app(kind: str) -> tuple[str, str] | None:
    """The platform's own registered app for this vendor, if the operator has configured one (preferred)."""
    prefix = f"ZIIRA_OAUTH_{kind.upper()}_"
    client_id, client_secret = os.environ.get(prefix + "CLIENT_ID", ""), os.environ.get(prefix + "CLIENT_SECRET", "")
    return (client_id, client_secret) if client_id and client_secret else None


def redirect_uri() -> str:
    """The address the vendor sends the browser back to. It must be registered exactly like this with the vendor."""
    return settings_public_base_url().rstrip("/") + CALLBACK_PATH


def web_url(connection_id: UUID | None, **flags: str) -> str:
    base = platform_settings().public_web_url.rstrip("/")
    path = WEB_PATH.format(connection_id=connection_id) if connection_id else "/connect"
    return f"{base}{path}?{urlencode(flags)}"


# --------------------------------------------------------------------------- start
class OAuthStartIn(BaseModel):
    connection_id: UUID
    client_id: str | None = Field(default=None, max_length=200, description="Your own app's client id (optional)")
    client_secret: SecretStr | None = Field(default=None, max_length=400)


class OAuthStartOut(BaseModel):
    authorization_url: str
    redirect_uri: str
    expires_in_seconds: int


def _oauth_connector(session: Session, kind: str) -> Connector:
    if kind not in OAUTH_KINDS:
        raise NotFound("That system does not use an approval screen")
    connector = connectors.connector_for(session, kind)
    if not connector.needs_oauth:
        raise NotFound("That system does not use an approval screen")
    return connector


@router.post("/oauth/{kind}/start", response_model=OAuthStartOut, dependencies=MANAGE)
def start(kind: str, body: OAuthStartIn, session: Session = DB_SESSION) -> OAuthStartOut:
    """Begin approving Ziira in the other system: returns the address to send the person's browser to."""
    connector = _oauth_connector(session, kind)
    row = connections.get(session, body.connection_id, manage=True)
    if row.kind != kind:
        raise ValidationFailed("This connection is for a different system")
    if row.status == "disconnected":
        raise ValidationFailed("This connection is disconnected: create a new one")
    ctx = current_context()
    app = platform_app(kind)
    stored = connections.load_secrets(session, row)
    if app is not None:
        client_id, client_secret = app
    else:
        client_id = (body.client_id or str(stored.get("client_id") or "")).strip()
        client_secret = body.client_secret.get_secret_value().strip() if body.client_secret else str(
            stored.get("client_secret") or "")
        if not client_id or not client_secret:
            raise ValidationFailed("Enter the client id and client secret of your app (or ask your administrator to "
                                   "register Ziira's app with this vendor)")
    nonce = token_source.token_urlsafe(24)
    config = dict(connections.public_config(row))
    try:
        url = _authorization_url(connector, config, client_id, make_state(
            tenant_id=ctx.tenant_id, connection_id=row.id, user_id=ctx.user_id, kind=kind, nonce=nonce))
    except ConnectorError as error:
        raise ValidationFailed(str(error)) from None
    new_secrets = {"client_id": client_id, "client_secret": client_secret, NONCE_KEY: nonce}
    credential_id = connections.store_secrets(session, row, connector, new_secrets)
    names = sorted({*dict(row.config).get("_secrets", []), "client_id", "client_secret"})
    repo.update_connection(session, row.id, {"credential_id": credential_id, "config": {**dict(row.config),
                                                                                       "_secrets": names}})
    audit_record(session, "oauth_start", "connect.connection", row.id, {"kind": kind})
    return OAuthStartOut(authorization_url=url, redirect_uri=redirect_uri(), expires_in_seconds=STATE_MINUTES * 60)


def _authorization_url(connector: Connector, config: dict[str, Any], client_id: str, state: str) -> str:
    if isinstance(connector, ZohoBooksConnector):
        return connector.authorization_url(data_centre=str(config.get("data_centre") or "com"), client_id=client_id,
                                           redirect_uri=redirect_uri(), state=state)
    if isinstance(connector, QuickBooksConnector):
        return connector.authorization_url(client_id=client_id, redirect_uri=redirect_uri(), state=state)
    raise ConnectorError("That system does not use an approval screen", retryable=False)


# --------------------------------------------------------------------------- callback
@public_router.get("/oauth/callback", include_in_schema=False)
def callback(state: str = Query(default="", max_length=2000), code: str = Query(default="", max_length=2000),
             error: str = Query(default="", max_length=200), realmId: str = Query(default="", max_length=40),  # noqa: N803
             location: str = Query(default="", max_length=20)) -> RedirectResponse:
    """The vendor sends the person's browser here after they approve (or refuse). Public: the signed state proves it.
    Whatever happens, the person ends up back in the web app; the address carries only a short reason code."""
    try:
        parsed = read_state(state)
    except ValidationFailed:
        return _redirect(None, "failed", "invalid_state")
    if error:
        _forget_nonce(parsed)
        return _redirect(parsed.connection_id, "failed", "denied")
    if not code:
        return _redirect(parsed.connection_id, "failed", "no_code")
    try:
        reason = complete(parsed, code=code, realm_id=realmId, location=location)
    except Exception:  # noqa: BLE001 - the person must always land back in the app; details go to the log, not the URL
        log.exception("OAuth callback failed for %s", parsed.kind)
        reason = "error"
    return _redirect(parsed.connection_id, "failed" if reason else "success", reason)


def _redirect(connection_id: UUID | None, outcome: str, reason: str | None) -> RedirectResponse:
    flags = {"oauth": outcome}
    if reason:
        flags["reason"] = reason
    return RedirectResponse(web_url(connection_id, **flags), status_code=303)


def _forget_nonce(parsed: OAuthState) -> None:
    try:
        with system_session(parsed.tenant_id) as session:
            row = repo.get_connection(session, parsed.connection_id)
            if row is not None and row.credential_id is not None:
                stored = connections.load_secrets(session, row)
                if stored.get(NONCE_KEY) == parsed.nonce:
                    connections.store_secrets(session, row, connectors.connector_for(session, row.kind),
                                              {NONCE_KEY: ""})
    except Exception:  # noqa: BLE001 - best effort tidy-up
        log.warning("Could not clear a pending approval", exc_info=True)


def complete(parsed: OAuthState, *, code: str, realm_id: str = "", location: str = "") -> str | None:
    """Swap the code for tokens and store them. Returns None on success or a short reason code. The vendor is called
    between two short transactions, never inside one."""
    with system_session(parsed.tenant_id) as session:
        row = repo.get_connection(session, parsed.connection_id)
        if row is None or row.kind != parsed.kind or row.status == "disconnected":
            return "unknown_connection"
        connector = _oauth_connector(session, parsed.kind)
        stored = connections.load_secrets(session, row)
        if not stored.get(NONCE_KEY) or not token_source.compare_digest(str(stored[NONCE_KEY]), parsed.nonce):
            return "already_used"                                 # a replayed or superseded approval link
        config = dict(connections.public_config(row))
        client_id, client_secret = str(stored.get("client_id") or ""), str(stored.get("client_secret") or "")
    if not client_id or not client_secret:
        return "missing_app"
    try:
        result = _exchange(connector, config, client_id, client_secret, code, realm_id, location)
    except ConnectorError as error:
        log.warning("OAuth exchange refused for %s: %s", parsed.kind, error)
        return "exchange_failed" if not error.retryable else "vendor_unavailable"
    with system_session(parsed.tenant_id) as session:
        row = repo.get_connection(session, parsed.connection_id, lock=True)
        if row is None:
            return "unknown_connection"
        stored = connections.load_secrets(session, row)
        if not token_source.compare_digest(str(stored.get(NONCE_KEY) or ""), parsed.nonce):
            return "already_used"
        connector = _oauth_connector(session, parsed.kind)
        credential_id = connections.store_secrets(session, row, connector, {**result.secrets, NONCE_KEY: ""})
        names = sorted({*dict(row.config).get("_secrets", []), *result.secrets})
        new_config = {**dict(row.config), **result.config, "_secrets": names}
        repo.update_connection(session, row.id, {"credential_id": credential_id, "config": new_config,
                                                 "status": "active", "failures": 0, "last_error": None,
                                                 "next_sync_at": datetime.now(UTC)})       # read it soon
        audit_record(session, "oauth_complete", "connect.connection", row.id,
                     {"kind": parsed.kind, "approved_by": str(parsed.user_id) if parsed.user_id else None})
    return None


def _exchange(connector: Connector, config: dict[str, Any], client_id: str, client_secret: str, code: str,
              realm_id: str, location: str) -> h.OAuthResult:
    if isinstance(connector, ZohoBooksConnector):
        centre = location.strip().lower() or str(config.get("data_centre") or "com")   # Zoho says where the account is
        result = connector.exchange_code(data_centre=centre, client_id=client_id, client_secret=client_secret,
                                         code=code, redirect_uri=redirect_uri())
        return result
    if isinstance(connector, QuickBooksConnector):
        return connector.exchange_code(client_id=client_id, client_secret=client_secret, code=code,
                                       redirect_uri=redirect_uri(), realm_id=realm_id,
                                       environment=str(config.get("environment") or "production"))
    raise ConnectorError("That system does not use an approval screen", retryable=False)

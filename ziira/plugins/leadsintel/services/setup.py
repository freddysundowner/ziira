"""Connecting a business to Lead Intel: the platform key, a WhatsApp number (new, or one already on Lead Intel).

Everything here runs for a person holding `settings.manage` for the company. The platform key and the webhook secret are
kept in the credential store and are never returned, logged or put in an error.

States of the WhatsApp connection (`connection.status`):

    requested ──▶ awaiting_code ──▶ connected ──▶ active        a new number, set up by Lead Intel with Meta
    code_sent ──▶ (verify the SMS code) ──▶ connected ──▶ active   a number already on Lead Intel, claimed by SMS code
    failed | cancelled | disconnected                             end states; a new request starts again

Only an `active` connection sends. The credential carries `ready: false` until then, so the platform does not offer
WhatsApp as a way to reach people before it works.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from ziira.plugins.leadsintel import repository as repo
from ziira.plugins.leadsintel.client import LeadIntelClient, LeadIntelError
from ziira.sdk import (
    Conflict,
    Session,
    ValidationFailed,
    audit_record,
    check_calling_code,
    check_company,
    current_context,
    hash_secret,
    new_secret,
    read_credential,
    settings_public_base_url,
    store_credential,
)

log = logging.getLogger("ziira.leadsintel")
PROVIDER = "leadsintel"
# A number nobody has: used only to ask "is this key accepted?" (Lead Intel answers 404 for an unknown number and 401
# for
# a wrong key, as documented for the connection lookup).
PROBE_NUMBER = "+10000000000"


def _error(error: LeadIntelError) -> ValidationFailed:
    """A Lead Intel refusal as a message for the person setting up (no key, no response body)."""
    if error.status == 0:
        return ValidationFailed("Lead Intel could not be reached. Try again in a minute")
    if error.status in (401, 403):
        return ValidationFailed("Lead Intel does not accept that platform key")
    if error.status == 429:
        return ValidationFailed("Lead Intel asked us to slow down. Try again in a minute")
    if error.status >= 500:
        return ValidationFailed("Lead Intel had a problem. Try again in a minute")
    hints = {"phone_number_already_connected": "That number is already connected. If it is on Lead Intel under your "
                                               "account, use 'I already have this number on Lead Intel'",
             "number_not_connected": "That number is not on Lead Intel yet. Connect it as a new number",
             "invalid_code": "That code is not right" + (f" ({error.extra['attemptsLeft']} tries left)"
                                                         if "attemptsLeft" in error.extra else ""),
             "code_expired": "That code has expired. Start again to get a new one",
             "invalid_phone_number": "That phone number does not look right",
             "number_not_claimable": "That number cannot be claimed",
             "connection_id_in_use": "That connection is already in use. Start again",
             "sms_not_sent": "Lead Intel could not send the code by SMS. Try again shortly"}
    return ValidationFailed(hints.get(error.code) or f"Lead Intel refused this ({error.code or error.status})")


def _settings(session: Session, company_id: UUID) -> Any:
    ctx = current_context()
    ctx.require("settings.manage", company_id=company_id)
    check_company(session, company_id)
    return ctx


def _client(session: Session, company_id: UUID) -> LeadIntelClient:
    found = repo.credential(session, company_id, "whatsapp")
    if found is None:
        raise ValidationFailed("Enter your Lead Intel platform key first")
    return LeadIntelClient(str(read_credential(session, found.id)["platform_key"]))


def _tenant_ref() -> str:
    return str(current_context().tenant_id)


def webhook_url(token: str) -> str:
    base = settings_public_base_url().rstrip("/")
    if not base.startswith("https://"):
        raise ValidationFailed("Lead Intel needs a public https address for incoming messages: the platform's "
                               "public address (ZIIRA_PUBLIC_BASE_URL) is not https")
    return f"{base}/api/v1/plugins/leadsintel/webhook/{token}"


# --------------------------------------------------------------------------- the key
def save_platform_key(session: Session, company_id: UUID, platform_key: str) -> None:
    """Check the key with Lead Intel and keep it (encrypted) with a new secret for signing incoming messages."""
    _settings(session, company_id)
    key = platform_key.strip()
    if not key:
        raise ValidationFailed("Enter the platform key")
    try:
        LeadIntelClient(key).lookup_connection(PROBE_NUMBER)
    except LeadIntelError as error:
        if error.status not in (404,):                       # 404 connection_not_found: the key was accepted
            raise _error(error) from None
    previous = repo.credential(session, company_id, "whatsapp")
    old: dict[str, Any] = read_credential(session, previous.id) if previous is not None else {}
    config = dict(previous.config) if previous is not None else {
        "provider": PROVIDER, "tenant_ref": _tenant_ref(), "connection_id": "", "ready": False}
    store_credential(session, company_id=company_id, provider="whatsapp", label="WhatsApp (Lead Intel)",
                     secret={"platform_key": key, "webhook_secret": old.get("webhook_secret") or new_secret()},
                     config=config, replace=previous.id if previous is not None else None)
    audit_record(session, "leadsintel.key_saved", "kernel.integration_credential", None,
                 {"company_id": str(company_id)})


def check_credentials(session: Session, company_id: UUID) -> dict[str, Any]:
    """Ask Lead Intel whether the stored key is still accepted (the same harmless lookup as when it was saved). Never
    says more than yes or no: a key is not echoed, and an outage is not reported as a bad key."""
    _settings(session, company_id)
    client = _client(session, company_id)
    try:
        client.lookup_connection(PROBE_NUMBER)
    except LeadIntelError as error:
        if error.status == 404:
            return {"ok": True, "message": "Lead Intel accepts the platform key"}
        if error.retryable:
            return {"ok": False, "message": "Lead Intel could not be reached. Try again in a minute"}
        return {"ok": False, "message": str(_error(error).message)}
    return {"ok": True, "message": "Lead Intel accepts the platform key"}


def _activate(session: Session, company_id: UUID, connection_id: UUID, external_id: str,
              details: dict[str, Any]) -> None:
    """The connection is active: the credential now names it and WhatsApp may be used."""
    found = repo.credential(session, company_id, "whatsapp")
    assert found is not None
    secret = read_credential(session, found.id)
    config = {**found.config, "tenant_ref": _tenant_ref(), "connection_id": external_id, "ready": True}
    store_credential(session, company_id=company_id, provider="whatsapp", label="WhatsApp (Lead Intel)", secret=secret,
                     config=config, replace=found.id)
    repo.update_connection(session, connection_id, status="active", display_phone=details.get("displayPhoneNumber"),
                           phone_number_id=details.get("phoneNumberId"), error_code=None, error_message=None)
    audit_record(session, "leadsintel.whatsapp_active", "plg_leadsintel.connection", connection_id, None)


def _deactivate(session: Session, company_id: UUID) -> None:
    found = repo.credential(session, company_id, "whatsapp")
    if found is not None:
        secret = read_credential(session, found.id)
        store_credential(session, company_id=company_id, provider="whatsapp", label="WhatsApp (Lead Intel)",
                         secret=secret, config={**found.config, "connection_id": "", "ready": False},
                         replace=found.id)


# --------------------------------------------------------------------------- a new number
def request_number(session: Session, company_id: UUID, *, country_code: str, phone_number: str, business_name: str,
                   display_name: str,
                   profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ask Lead Intel to connect a number (Lead Intel sets it up with Meta; this can take a while: poll `refresh`)."""
    _settings(session, company_id)
    client = _client(session, company_id)
    current = repo.latest_connection(session, company_id)
    if current is not None and current.status in ("requested", "awaiting_code", "code_sent", "connected"):
        raise Conflict("A WhatsApp connection is already in progress. Cancel it first to start again")
    if current is not None and current.status == "active":
        raise Conflict("WhatsApp is already connected. Disconnect it first to use another number")
    country, national = _number(country_code, phone_number)
    external_id = uuid4().hex
    token = f"{_tenant_ref().replace('-', '')}.{new_secret()}"
    secret = read_credential(session, repo.credential(session, company_id, "whatsapp").id)  # type: ignore[union-attr]
    body: dict[str, Any] = {
        "externalPlatformTenantId": _tenant_ref(), "externalConnectionId": external_id,
        "externalUserId": str(current_context().user_id or ""), "countryCode": country, "phoneNumber": national,
        "businessName": business_name.strip()[:100], "displayName": display_name.strip()[:100],
        "inboundWebhookUrl": webhook_url(token), "inboundWebhookSecret": secret["webhook_secret"]}
    if not body["externalUserId"]:
        del body["externalUserId"]
    if profile:
        body["businessProfile"] = profile
    try:
        reply = client.create_assisted_request(body)
    except LeadIntelError as error:
        raise _error(error) from None
    connection = repo.insert_connection(session, company_id=company_id, kind="whatsapp", external_id=external_id,
                                        token_hash=hash_secret(token), status="requested",
                                        request_id=str(reply.get("requestId") or "") or None)
    audit_record(session, "leadsintel.number_requested", "plg_leadsintel.connection", connection, None)
    return {"status": "requested"}


def _number(country_code: str, phone_number: str) -> tuple[str, str]:
    """(calling code, national number) as digits. Lead Intel takes them separately, so the person gives them
    separately."""
    code = check_calling_code(country_code)
    national = "".join(ch for ch in phone_number if ch.isdigit()).lstrip("0")
    if not code:
        raise ValidationFailed("Enter the country calling code, for example 44")
    if not 5 <= len(national) <= 13 or len(code) + len(national) > 15:
        raise ValidationFailed("That phone number does not look right")
    return code, national


# --------------------------------------------------------------------------- progress
def refresh(session: Session, company_id: UUID) -> dict[str, Any]:
    """Ask Lead Intel how the connection is going and record it. Returns the new state (see `state`)."""
    _settings(session, company_id)
    current = repo.latest_connection(session, company_id)
    if current is None or current.status not in ("requested", "awaiting_code", "connected", "code_sent"):
        return state(session, company_id)
    client = _client(session, company_id)
    try:
        if current.status in ("requested", "awaiting_code") and current.request_id:
            reply = client.get_assisted_request(current.request_id)
            status = str(reply.get("status") or "")
            if status == "failed":
                repo.update_connection(session, current.id, status="failed", error_code=reply.get("errorCode"),
                                       error_message=str(reply.get("errorMessage") or "")[:300] or None)
            elif status == "cancelled":
                repo.update_connection(session, current.id, status="cancelled")
            elif status == "awaiting_code":
                repo.update_connection(session, current.id, status="awaiting_code")
            elif status == "connected":
                repo.update_connection(session, current.id, status="connected",
                                       display_phone=reply.get("displayPhoneNumber"))
                current = repo.latest_connection(session, company_id)
        if current is not None and current.status == "connected":
            details = client.get_connection(_tenant_ref(), current.external_connection_id)
            if str(details.get("status")) == "active":
                _activate(session, company_id, current.id, current.external_connection_id, details)
    except LeadIntelError as error:
        if error.retryable:
            return {**state(session, company_id),
                    "warning": "Lead Intel could not be reached; showing the last known state"}
        raise _error(error) from None
    return state(session, company_id)


def cancel(session: Session, company_id: UUID) -> dict[str, Any]:
    """Stop a connection that has not finished."""
    _settings(session, company_id)
    current = repo.latest_connection(session, company_id)
    if current is None or current.status not in ("requested", "awaiting_code", "code_sent"):
        raise ValidationFailed("There is no connection in progress")
    if current.request_id:
        try:
            _client(session, company_id).cancel_assisted_request(current.request_id)
        except LeadIntelError as error:
            if error.status not in (404, 409):
                raise _error(error) from None
    repo.update_connection(session, current.id, status="cancelled")
    return state(session, company_id)


def disconnect(session: Session, company_id: UUID) -> dict[str, Any]:
    """Remove the connected number from Lead Intel (and from Meta) and stop using WhatsApp."""
    _settings(session, company_id)
    current = repo.latest_connection(session, company_id)
    if current is None or current.status != "active":
        raise ValidationFailed("WhatsApp is not connected")
    try:
        _client(session, company_id).delete_connection(_tenant_ref(), current.external_connection_id)
    except LeadIntelError as error:
        if error.status != 404:
            raise _error(error) from None
    repo.update_connection(session, current.id, status="disconnected")
    _deactivate(session, company_id)
    audit_record(session, "leadsintel.whatsapp_disconnected", "plg_leadsintel.connection", current.id, None)
    return state(session, company_id)


# --------------------------------------------------------------------------- a number already on Lead Intel
def check_existing(session: Session, company_id: UUID, country_code: str, phone_number: str) -> dict[str, Any]:
    """Is this number on Lead Intel under the platform, and can it be claimed?"""
    _settings(session, company_id)
    code, national = _number(country_code, phone_number)
    try:
        reply = _client(session, company_id).lookup_existing_number(f"+{code}{national}")
    except LeadIntelError as error:
        if error.status == 404:
            return {"connected": False, "claimable": False, "reason": "number_not_connected"}
        raise _error(error) from None
    return {"connected": bool(reply.get("connected")), "claimable": bool(reply.get("claimable")),
            "reason": reply.get("reason")}


def start_claim(session: Session, company_id: UUID, country_code: str, phone_number: str) -> dict[str, Any]:
    """Lead Intel sends a code by SMS to the number; typing it back (`verify_claim`) connects the number."""
    _settings(session, company_id)
    client = _client(session, company_id)
    current = repo.latest_connection(session, company_id)
    if current is not None and current.status in ("requested", "awaiting_code", "code_sent", "connected", "active"):
        raise Conflict("A WhatsApp connection already exists or is in progress")
    external_id = uuid4().hex
    token = f"{_tenant_ref().replace('-', '')}.{new_secret()}"
    secret = read_credential(session, repo.credential(session, company_id, "whatsapp").id)  # type: ignore[union-attr]
    code, national = _number(country_code, phone_number)
    body = {"phoneNumber": f"+{code}{national}", "externalPlatformTenantId": _tenant_ref(),
            "externalConnectionId": external_id, "inboundWebhookUrl": webhook_url(token),
            "inboundWebhookSecret": secret["webhook_secret"]}
    try:
        reply = client.start_claim(body)
    except LeadIntelError as error:
        raise _error(error) from None
    repo.insert_connection(session, company_id=company_id, kind="whatsapp", external_id=external_id,
                           token_hash=hash_secret(token), status="code_sent",
                           claim_id=str(reply.get("claimId") or "") or None)
    return {**state(session, company_id), "sent_to": reply.get("sentTo"), "expires_at": reply.get("expiresAt")}


def verify_claim(session: Session, company_id: UUID, code: str) -> dict[str, Any]:
    _settings(session, company_id)
    current = repo.latest_connection(session, company_id)
    if current is None or current.status != "code_sent" or not current.claim_id:
        raise ValidationFailed("No code is waiting. Start again")
    try:
        reply = _client(session, company_id).verify_claim(current.claim_id, code.strip())
    except LeadIntelError as error:
        if error.status == 410:
            repo.update_connection(session, current.id, status="failed", error_code="code_expired")
        raise _error(error) from None
    repo.update_connection(session, current.id, status="connected", display_phone=reply.get("displayPhoneNumber"),
                           phone_number_id=reply.get("phoneNumberId"))
    return refresh(session, company_id)


# --------------------------------------------------------------------------- what the screen shows
def state(session: Session, company_id: UUID) -> dict[str, Any]:
    """Where setup stands, for the settings screen. Holds no secret."""
    _settings(session, company_id)
    key = repo.credential(session, company_id, "whatsapp")
    current = repo.latest_connection(session, company_id)
    return {
        "key_saved": key is not None,
        "whatsapp": None if current is None else {
            "status": current.status, "display_phone": current.display_phone, "error_code": current.error_code,
            "error_message": current.error_message},
    }

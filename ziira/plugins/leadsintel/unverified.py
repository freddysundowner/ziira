"""Request shapes that Lead Intel has NOT documented. Everything here is a guess, isolated in this one module so it can
be corrected in one place once Lead Intel's real API is known.

Documented at https://leadsintel.net/developers.html (2026-10-15): WhatsApp numbers, sending, inbound webhooks. Not
documented anywhere on the public site (developers, guide, features, support pages): creating or checking
WhatsApp message templates (the guide describes doing both in Lead Intel's own screens only). So:

* `# UNVERIFIED` marks every address, field name and reply shape below. They follow the pattern of the documented
  WhatsApp endpoints (same prefix, tenant and connection in the path) and Meta's own template format, which Lead Intel
  passes through for the messages it documents.
* Until Lead Intel confirms them, a business can still use WhatsApp with templates it creates in Lead Intel's screens
  (the template names are `ziira_<code>`; see docs/channels.md).
* Live testing is needed for all of it. Nothing here has been run against the real service.
"""

from typing import Any

from ziira.plugins.leadsintel.client import LeadIntelClient
from ziira.sdk import TemplateSpec, TemplateState

# --------------------------------------------------------------------------- WhatsApp templates
TEMPLATE_PATH = "/external-platform/whatsapp/connections/{tenant}/{connection}/templates"   # UNVERIFIED
# Meta's template statuses, mapped to ours. UNVERIFIED that Lead Intel reports them this way.
STATUS_MAP = {"APPROVED": "approved", "REJECTED": "rejected", "PENDING": "submitted", "IN_REVIEW": "submitted",
              "PAUSED": "rejected", "DISABLED": "rejected", "PENDING_DELETION": "rejected"}


def template_payload(spec: TemplateSpec) -> dict[str, Any]:
    """The body to create a template: Meta's own template format (name, language, category, components). UNVERIFIED."""
    components: list[dict[str, Any]] = [{
        "type": "BODY", "text": spec.body,
        "example": {"body_text": [list(spec.examples)]} if spec.examples else {}}]
    if spec.buttons:
        components.append({"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": t} for t in spec.buttons]})
    return {"name": spec.name, "language": spec.language, "category": spec.category.upper(),
            "components": components}                                                    # UNVERIFIED


def _state(reply: dict[str, Any]) -> TemplateState:
    raw = str(reply.get("status", "PENDING")).upper()                                    # UNVERIFIED
    return TemplateState(STATUS_MAP.get(raw, "submitted"), str(reply["id"]) if reply.get("id") else None,
                         str(reply.get("rejectedReason") or reply.get("reason") or "")[:300])


def submit_template(client: LeadIntelClient, tenant_ref: str, connection_id: str, spec: TemplateSpec) -> TemplateState:
    """Ask Lead Intel to submit a template to Meta. UNVERIFIED."""
    path = TEMPLATE_PATH.format(tenant=tenant_ref, connection=connection_id)
    return _state(client.call("POST", path, template_payload(spec)))


def template_state(client: LeadIntelClient, tenant_ref: str, connection_id: str, spec: TemplateSpec,
                   provider_template_id: str | None) -> TemplateState:
    """Ask where a submitted template stands, by name and language. UNVERIFIED (assumed `GET
    .../templates?name=&language=`
    returning one template object, or {"templates": [..]})."""
    path = (TEMPLATE_PATH.format(tenant=tenant_ref, connection=connection_id)
            + f"?name={spec.name}&language={spec.language}")
    reply = client.call("GET", path)
    items = reply.get("templates")
    if isinstance(items, list) and items:
        reply = items[0]
    return _state(reply)

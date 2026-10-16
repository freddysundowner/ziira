"""API keys, the public API description and outgoing webhooks (Settings > API keys, Settings > Webhooks)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from ziira.kernel import api_keys, public_api, webhooks
from ziira.kernel.api import integration_schemas as sc
from ziira.kernel.context import RequestContext
from ziira.sdk import DB_SESSION, Session, page_limit, page_offset, request_context

router = APIRouter(prefix="/api/v1")
NO_CONTENT = status.HTTP_204_NO_CONTENT


def admin(permission: str) -> Callable[[RequestContext], RequestContext]:
    """Dependency: the actor must hold `permission` over the whole business."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        ctx.require(permission)
        return ctx

    return check


manage_keys = admin("api_keys.manage")


# --------------------------------------------------------------------------- API keys
@router.get(
    "/api-keys",
    response_model=list[sc.ApiKeyOut],
    tags=["Integrations"],
    dependencies=[Depends(admin("api_keys.manage"))],
)
def list_api_keys(s: Session = DB_SESSION) -> object:
    """Keys with how they are limited and used (last used, how many requests, from which address)."""
    return [sc.ApiKeyOut.model_validate(r) for r in api_keys.list_keys(s)]


@router.post("/api-keys", response_model=sc.ApiKeyCreatedOut, status_code=201, tags=["Integrations"])
def create_api_key(body: sc.ApiKeyIn, ctx: RequestContext = Depends(manage_keys), s: Session = DB_SESSION) -> object:
    """Create a key for a server-to-server integration. The key is shown only in this response."""
    key_id, key = api_keys.create_key(
        s,
        ctx.tenant_id,
        name=body.name,
        scopes=body.scopes,
        expires_at=body.expires_at,
        read_only=body.read_only,
        company_id=body.company_id,
        branch_id=body.branch_id,
        rate_limit_per_minute=body.rate_limit_per_minute,
    )
    return sc.ApiKeyCreatedOut(id=key_id, key=key)


@router.post("/api-keys/{key_id}/rotate", response_model=sc.ApiKeyCreatedOut, status_code=201, tags=["Integrations"])
def rotate_api_key(
    key_id: UUID, body: sc.ApiKeyRotateIn, ctx: RequestContext = Depends(manage_keys), s: Session = DB_SESSION
) -> object:
    """Replace a key with a new one that has the same permissions and limits; the old one works for a while longer."""
    new_id, key = api_keys.rotate(s, ctx.tenant_id, key_id, body.grace_hours)
    return sc.ApiKeyCreatedOut(id=new_id, key=key)


@router.delete(
    "/api-keys/{key_id}",
    status_code=NO_CONTENT,
    tags=["Integrations"],
    dependencies=[Depends(admin("api_keys.manage"))],
)
def revoke_api_key(key_id: UUID, s: Session = DB_SESSION) -> Response:
    api_keys.revoke(s, key_id)
    return Response(status_code=NO_CONTENT)


@router.get("/public/openapi.json", tags=["Integrations"], include_in_schema=False)
def public_openapi(request: Request) -> dict[str, Any]:
    """The OpenAPI description of the public API only (no sign-in needed: it is documentation)."""
    return public_api.public_schema(request.app.openapi())


# --------------------------------------------------------------------------- webhooks
@router.get(
    "/webhooks/events",
    response_model=list[sc.WebhookEventOut],
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def webhook_events() -> object:
    """The events a webhook can subscribe to, and the payload fields each carries."""
    return webhooks.catalogue()


@router.get(
    "/webhooks/endpoints",
    response_model=list[sc.WebhookOut],
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def list_webhooks(s: Session = DB_SESSION) -> object:
    return [sc.WebhookOut.model_validate(r) for r in webhooks.list_endpoints(s)]


@router.post(
    "/webhooks/endpoints",
    response_model=sc.WebhookCreatedOut,
    status_code=201,
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def create_webhook(body: sc.WebhookIn, s: Session = DB_SESSION) -> object:
    """Register an endpoint. The signing secret is in this response only."""
    endpoint_id, secret = webhooks.create_endpoint(s, name=body.name, url=body.url, event_types=body.event_types)
    return sc.WebhookCreatedOut(
        endpoint=sc.WebhookOut.model_validate(webhooks.get_endpoint(s, endpoint_id)), secret=secret
    )


@router.get(
    "/webhooks/endpoints/{endpoint_id}",
    response_model=sc.WebhookOut,
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def get_webhook(endpoint_id: UUID, s: Session = DB_SESSION) -> object:
    return sc.WebhookOut.model_validate(webhooks.get_endpoint(s, endpoint_id))


@router.patch(
    "/webhooks/endpoints/{endpoint_id}",
    response_model=sc.WebhookOut,
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def update_webhook(endpoint_id: UUID, body: sc.WebhookPatch, s: Session = DB_SESSION) -> object:
    row = webhooks.update_endpoint(
        s, endpoint_id, name=body.name, url=body.url, event_types=body.event_types, status=body.status
    )
    return sc.WebhookOut.model_validate(row)


@router.delete(
    "/webhooks/endpoints/{endpoint_id}",
    status_code=NO_CONTENT,
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def delete_webhook(endpoint_id: UUID, s: Session = DB_SESSION) -> Response:
    webhooks.delete_endpoint(s, endpoint_id)
    return Response(status_code=NO_CONTENT)


@router.post(
    "/webhooks/endpoints/{endpoint_id}/secret",
    response_model=sc.WebhookSecretOut,
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def rotate_webhook_secret(endpoint_id: UUID, s: Session = DB_SESSION) -> object:
    """A new signing secret (shown once). The old one stops working at once."""
    return sc.WebhookSecretOut(secret=webhooks.rotate_secret(s, endpoint_id))


@router.post(
    "/webhooks/endpoints/{endpoint_id}/ping",
    response_model=sc.QueuedOut,
    status_code=202,
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def ping_webhook(endpoint_id: UUID, s: Session = DB_SESSION) -> object:
    """Queue a test delivery; its result appears in the delivery log within moments."""
    return sc.QueuedOut(delivery_id=webhooks.send_ping(s, endpoint_id))


@router.get(
    "/webhooks/endpoints/{endpoint_id}/deliveries",
    response_model=list[sc.DeliveryOut],
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def list_webhook_deliveries(
    endpoint_id: UUID,
    status: str | None = None,
    limit: int = page_limit(50),
    offset: int = page_offset(),
    s: Session = DB_SESSION,
) -> object:
    return [
        sc.DeliveryOut.model_validate(r)
        for r in webhooks.list_deliveries(s, endpoint_id, status=status, limit=limit, offset=offset)
    ]


@router.get(
    "/webhooks/deliveries/{delivery_id}",
    response_model=sc.DeliveryDetailOut,
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def get_webhook_delivery(delivery_id: UUID, s: Session = DB_SESSION) -> object:
    row, attempts = webhooks.get_delivery(s, delivery_id)
    return sc.DeliveryDetailOut(
        **sc.DeliveryOut.model_validate(row).model_dump(),
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        body_sha256=row.body_sha256,
        body_preview=row.body_preview,
        attempt_log=[sc.AttemptOut.model_validate(a) for a in attempts],
    )


@router.post(
    "/webhooks/deliveries/{delivery_id}/redeliver",
    status_code=202,
    response_model=sc.QueuedOut,
    tags=["Webhooks"],
    dependencies=[Depends(admin("webhooks.manage"))],
)
def redeliver_webhook(delivery_id: UUID, s: Session = DB_SESSION) -> object:
    """Send a delivery again, with the same event id."""
    webhooks.redeliver(s, delivery_id)
    return sc.QueuedOut(delivery_id=delivery_id)

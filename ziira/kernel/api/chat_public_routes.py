"""The chat bot's public inbound address (no sign-in: the provider's signature on the raw body is the credential).

`POST /api/v1/public/chat/inbound/{token}`. An unknown token, a bad or stale signature and an oversize body all get
the same
401, a repeat delivery gets 204, a delivery to be answered later gets 202 and an immediate reply is the 200 body.
Behaviour
and limits: docs/ai.md section 15, docs/security.md."""

from collections.abc import Mapping

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ziira.kernel.auth import client_ip
from ziira.kernel.config import get_settings
from ziira.kernel.platform import chat_inbound

router = APIRouter(prefix="/api/v1/public/chat", tags=["Chat bot (public)"])


class ChatInboundReply(BaseModel):
    type: str
    text: str | None = None
    body: str | None = None


NOT_ACCEPTED = {"error": "unauthorized", "message": "Not accepted"}


@router.post(
    "/inbound/{token}",
    responses={
        200: {"model": ChatInboundReply},
        202: {"description": "Answered later"},
        204: {"description": "Nothing to say"},
        401: {"description": "Not accepted"},
    },
)
async def chat_inbound_delivery(token: str, request: Request) -> Response:
    """A signed delivery from the chat provider. Never reveals why a delivery was refused."""
    limit = get_settings().chat_inbound_max_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return _json(401, NOT_ACCEPTED)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return _json(401, NOT_ACCEPTED)
        chunks.append(chunk)
    result = await run_in_threadpool(
        chat_inbound.handle, token, dict(request.headers), b"".join(chunks), client_ip(request)
    )
    if result.status == 200 and result.body is not None:
        return _json(200, result.body)
    if result.status == 401:
        return _json(401, NOT_ACCEPTED)
    return Response(status_code=result.status)


def _json(status: int, body: Mapping[str, object]) -> Response:
    import json

    return Response(content=json.dumps(body), status_code=status, media_type="application/json")

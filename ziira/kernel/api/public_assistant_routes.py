"""The website assistant for visitors of the marketing site (no sign-in): `GET /public/assistant/config` and
`POST /public/assistant/stream` (Server-Sent Events). Rules and behaviour: docs/ai.md, "Website assistant"."""

import asyncio
import contextvars
import json
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import site_assistant
from ziira.kernel.auth import client_ip
from ziira.kernel.platform import site_assistant as settings

router = APIRouter(prefix="/api/v1/public/assistant", tags=["Website assistant"])


class AssistantConfig(BaseModel):
    enabled: bool = Field(
        description="The assistant can answer right now (a provider is in use and no limit is reached); never a switch"
    )
    greeting: str
    suggestions: list[str]


class AssistantTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000, description="Only the first 800 characters are used")


class AssistantQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str = Field(max_length=4000, description="At most 500 characters; longer gets a `too_long` error event")
    history: list[AssistantTurn] = Field(default_factory=list, max_length=20, description="Only the last 6 are used")
    page: str | None = Field(default=None, max_length=300, description="The site path the visitor is on")
    lang: str = Field(default="en", max_length=8)


@router.get("/config", response_model=AssistantConfig)
def get_config(response: Response) -> object:
    """Whether the assistant can answer right now, its greeting and suggestions. Cached briefly; no secrets."""
    response.headers["Cache-Control"] = "public, max-age=30"
    return settings.public_config()


def _pump(
    events: Iterator[dict[str, Any]],
    loop: asyncio.AbstractEventLoop,
    queue: "asyncio.Queue[dict[str, Any] | None]",
    stop: threading.Event,
) -> None:
    """Runs in a worker thread: moves the events to the response and stops when the reader has gone."""
    try:
        for event in events:
            if stop.is_set():
                break
            loop.call_soon_threadsafe(queue.put_nowait, event)
    finally:
        close = getattr(events, "close", None)
        if close:
            close()
        loop.call_soon_threadsafe(queue.put_nowait, None)


def _sse(event: dict[str, Any]) -> bytes:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n".encode()


@router.post(
    "/stream",
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": (
                "Server-Sent Events: `status` {text}, `text` {text} (one sentence or list line each), "
                "`links` {items: [{title, href}]}, "
                "then `done` {}; or `error` {reason, message[, retry_after]} where reason is "
                "off (no AI provider in use), busy, budget, "
                "provider_failed or "
                "too_long."
            ),
        }
    },
)
async def post_stream(body: AssistantQuestion, request: Request) -> StreamingResponse:
    """Ask the website assistant about Ziira. It answers only from the site's own facts and the public prices."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    stop = threading.Event()
    events = site_assistant.stream(
        body.message, [(t.role, t.text) for t in body.history], body.page, body.lang, client_ip(request)
    )
    loop.run_in_executor(None, contextvars.copy_context().run, _pump, events, loop, queue, stop)

    async def body_iter() -> AsyncIterator[bytes]:
        try:
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            stop.set()

    return StreamingResponse(
        body_iter(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

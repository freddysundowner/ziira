"""Writes every request of a support session to the logs once the response has gone: the platform's support access
log and the business's own audit log (see support.py). A pure ASGI middleware like export_audit.py; the person acting
is the context `request_context` stored on the request. A failure to write is logged loudly, not shown to the caller."""

import logging
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ziira.kernel import support

log = logging.getLogger("ziira.support")


def route_template(scope: Scope) -> str:
    """The path with each id replaced by its parameter name (`/api/v1/users/{user_id}/password`): never real ids or
    anything typed into the address. A path that matched no route is logged as `unmatched`."""
    if scope.get("route") is None:
        return "unmatched"
    segments = str(scope["path"]).split("/")
    names = {str(v): k for k, v in (scope.get("path_params") or {}).items()}
    return "/".join("{" + names[s] + "}" if s in names else s for s in segments)


class SupportLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state: dict[str, Any] = {"status": 0}

        async def watch(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
            await send(message)

        await self.app(scope, receive, watch)
        ctx = scope.get("state", {}).get("ziira_ctx")
        if ctx is None or ctx.support_session_id is None:
            return
        route = route_template(scope)
        try:
            await run_in_threadpool(support.log_request, ctx, scope["method"], str(route), state["status"])
        except Exception:
            log.exception("A support request could not be written to the access log")

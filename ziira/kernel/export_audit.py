"""Every download of data (a CSV export) is written to the audit log: who, from where, which export, how big.

A pure ASGI middleware, so it sees the finished response without holding it in memory: it watches the response start for
a CSV content type or an attachment, counts the bytes that follow, and after the response has gone it records the entry
(the person is the one `request_context` stored on the request). A failure to write the entry is logged and never breaks
the download; the CSV reports are also the ones payroll and finance people use, so they are the ones to account for.
"""

import logging
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ziira.kernel import audit
from ziira.kernel.context import RequestContext, set_context
from ziira.kernel.db import tenant_session

log = logging.getLogger("ziira.export_audit")


def _is_export(headers: list[tuple[bytes, bytes]]) -> bool:
    values = {k.decode().lower(): v.decode().lower() for k, v in headers}
    disposition = values.get("content-disposition", "")
    return values.get("content-type", "").startswith("text/csv") or "attachment" in disposition


def _write(ctx: RequestContext, entry: dict[str, Any]) -> None:
    set_context(ctx)
    with tenant_session(ctx.tenant_id) as s:
        audit.record(s, "data_export", "kernel.export", None, entry)


class ExportAuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state: dict[str, Any] = {"status": 0, "export": False, "bytes": 0}

        async def watch(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["export"] = message["status"] == 200 and _is_export(message.get("headers", []))
            elif message["type"] == "http.response.body":
                state["bytes"] += len(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, watch)
        ctx = scope.get("state", {}).get("ziira_ctx")
        if not state["export"] or ctx is None:
            return
        entry = {"path": scope["path"], "query": scope.get("query_string", b"").decode()[:500],
                 "bytes": state["bytes"]}
        try:
            await run_in_threadpool(_write, ctx, entry)
        except Exception:
            log.exception("A data export could not be written to the audit log")

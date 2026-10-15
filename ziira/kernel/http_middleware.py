"""One ASGI middleware for what every response and request needs: request id, access log and metrics, security
headers, `Cache-Control: no-store` for API replies, and the request size limit.

It is written as plain ASGI (not Starlette's BaseHTTPMiddleware) so that the size limit also covers bodies sent
without a Content-Length, and so a crash still returns a JSON error that carries the request id.
"""

import json
import logging
import re
import time
from collections.abc import MutableMapping
from typing import Any
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ziira.kernel.config import get_settings
from ziira.kernel.observability import get_state, http_metrics, redact, request_state

access_log = logging.getLogger("ziira.access")
log = logging.getLogger("ziira")
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,128}")
# Pages that load their own scripts and styles (Swagger UI, ReDoc) cannot carry the strict API policy.
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
_QUIET_PATHS = ("/healthz", "/readyz", "/health", "/metrics")      # probes: logged at debug level only

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-site",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"



def _is_file_upload(method: str, path: str) -> bool:
    """Statement and export uploads (a file is the request body) may be larger than other requests."""
    return method == "POST" and path.startswith("/api/v1/connect/") and path.endswith(("/upload", "/files/detect"))


class RequestTooLarge(Exception):
    """The body is bigger than ZIIRA_MAX_BODY_BYTES."""


def _is_doc(path: str) -> bool:
    return path == "/" or any(path == p or path.startswith(p + "/") for p in _DOC_PATHS)


def error_body(code: str, message: str, **extra: Any) -> bytes:
    """The JSON error body our API uses, with the request id so a user can quote it to support."""
    body: dict[str, Any] = {"error": code, "message": message, **extra}
    rid = get_state().get("request_id")
    if rid:
        body["request_id"] = rid
    return json.dumps(body).encode()


class HttpMiddleware:
    """See the module text."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        supplied = headers.get("x-request-id", "")
        rid = supplied if _VALID_REQUEST_ID.fullmatch(supplied) else uuid4().hex
        state: dict[str, str | None] = {"request_id": rid, "tenant_id": None}
        token = request_state.set(state)
        path: str = scope["path"]
        method: str = scope["method"]
        started = time.perf_counter()
        status = 500
        response_started = False
        exceeded = False                    # the body went over the limit (the app may hide that, see send_wrapper)
        limit = settings.max_upload_bytes if _is_file_upload(method, path) else settings.max_body_bytes
        received = 0

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise RequestTooLarge
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if exceeded:
                # FastAPI turns any error while reading a body into "400 bad body"; the real answer is 413.
                if message["type"] == "http.response.start" and status != 413:
                    status = 413
                    await self._respond(decorate_and_send, 413, "too_large", "The request is too large")
                return
            await decorate_and_send(message)

        async def decorate_and_send(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                out: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                existing = {k.lower() for k, _ in out}
                extra = {"x-request-id": rid, **SECURITY_HEADERS}
                if not _is_doc(path):
                    extra["content-security-policy"] = API_CSP
                if settings.env == "production":
                    extra["strict-transport-security"] = f"max-age={settings.hsts_max_age}; includeSubDomains"
                if (path.startswith("/api/") or "authorization" in headers or "x-api-key" in headers) \
                        and not _is_doc(path):
                    extra["cache-control"] = "no-store"
                    extra["pragma"] = "no-cache"
                for k, v in extra.items():
                    if k.encode() not in existing:
                        out.append((k.encode(), v.encode()))
                message = {**message, "headers": out}
            await send(message)

        declared = headers.get("content-length", "")
        try:
            if declared.isdigit() and int(declared) > limit:
                raise RequestTooLarge
            await self.app(scope, limited_receive, send_wrapper)
        except RequestTooLarge:
            if not response_started:
                await self._respond(decorate_and_send, 413, "too_large", "The request is too large")
            status = 413
        except Exception:
            # Unhandled error: log it (redacted) and answer with the same JSON shape, never a stack trace.
            log.exception("Unhandled error on %s %s", method, self._route(scope))
            if not response_started:
                await self._respond(decorate_and_send, 500, "internal_error",
                                    "Something went wrong on our side. Quote the request id if you contact support")
            status = 500
        finally:
            seconds = time.perf_counter() - started
            route = self._route(scope)
            http_metrics.observe(method, route, status, seconds)
            access_log.log(
                logging.DEBUG if path in _QUIET_PATHS else logging.INFO, "%s %s %s %.0fms", method, route, status,
                seconds * 1000,
                extra={"route": route, "method": method, "status": status, "duration_ms": round(seconds * 1000, 1),
                       "client": (scope.get("client") or ("-",))[0], "tenant_id": state.get("tenant_id"),
                       "request_bytes": received})
            request_state.reset(token)

    @staticmethod
    def _route(scope: MutableMapping[str, Any]) -> str:
        """The route template (`/api/v1/products/{product_id}`), never the real path with ids in it."""
        route = scope.get("route")
        path = getattr(route, "path", None)
        return str(path) if path else "unmatched"

    @staticmethod
    async def _respond(send: Any, status: int, code: str, message: str) -> None:
        body = error_body(code, redact(message))
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

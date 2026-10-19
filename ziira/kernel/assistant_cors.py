"""Cross-origin access for the website assistant's two public routes, and nothing else.

The marketing site is a different host from the API. Only the origins of the platform setting `public.site_url` (and its
`www.` twin) may call `GET /api/v1/public/assistant/config` and `POST /api/v1/public/assistant/stream` from a browser.
No credentials are allowed, the preflight is answered here, and every other path is left exactly as it was.
"""

from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ziira.kernel.platform import behaviour

PATHS = ("/api/v1/public/assistant/config", "/api/v1/public/assistant/stream")
ALLOW_HEADERS = "Content-Type, Accept, Accept-Language"


def allowed_origins() -> set[str]:
    """The site's origin and its www twin (e.g. https://example.com and https://www.example.com); empty if unset."""
    try:
        url = str(behaviour.get("public.site_url") or "").strip()
    except Exception:  # noqa: BLE001 - a missing master database must not break unrelated requests
        return set()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return set()
    host = parts.hostname
    port = f":{parts.port}" if parts.port else ""
    twin = host[4:] if host.startswith("www.") else "www." + host
    if host.replace(".", "").isdigit() or host == "localhost":
        twin = host
    return {f"{parts.scheme}://{host}{port}", f"{parts.scheme}://{twin}{port}"}


class AssistantCors:
    """Plain ASGI middleware: adds the CORS headers on the two paths, for the allowed origins only."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in PATHS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        origin = headers.get("origin", "")
        allowed = bool(origin) and origin in allowed_origins()
        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            if not allowed:
                await send({"type": "http.response.start", "status": 403, "headers": [(b"content-length", b"0")]})
                await send({"type": "http.response.body", "body": b""})
                return
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": [
                        (b"access-control-allow-origin", origin.encode()),
                        (b"vary", b"Origin"),
                        (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                        (b"access-control-allow-headers", ALLOW_HEADERS.encode()),
                        (b"access-control-max-age", b"600"),
                        (b"content-length", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message["headers"] if not k.lower().startswith(b"access-control-")]
                kept.append((b"vary", b"Origin"))
                if allowed:
                    kept.append((b"access-control-allow-origin", origin.encode()))
                    kept.append((b"access-control-expose-headers", b"Retry-After"))
                message = {**message, "headers": kept}
            await send(message)

        await self.app(scope, receive, with_headers)

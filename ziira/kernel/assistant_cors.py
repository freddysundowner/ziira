"""Cross-origin access for the website assistant's two public routes, and nothing else.

The marketing site is a different host from the API. Only these origins may call `GET /api/v1/public/assistant/config`
and `POST /api/v1/public/assistant/stream` from a browser:

1. the origin of the platform setting `public.site_url` and its `www.` twin, when that setting is set; otherwise
2. (fallback, so the site keeps working while the setting is empty) the app host's registrable parent and its `www.`
   twin: with the app at `https://app.example.com` that is `https://example.com` and `https://www.example.com`. The
   app host is the platform's public web address (`public.web_url`, else `ZIIRA_PUBLIC_WEB_URL`). The API knows no other
   "published website address", so the host of `public.site_url` is the website host and it is rule 1. The parent is the
   app host without its first label, with the app address's scheme and port; none is derived when the app host has
   fewer than three labels, is an IP address or `localhost`, or the parent would be a public suffix such as `co.uk`.

No credentials are allowed, the preflight is answered here, and every other path is left exactly as it was.
"""

from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ziira.kernel.platform import behaviour

PATHS = ("/api/v1/public/assistant/config", "/api/v1/public/assistant/stream")
ALLOW_HEADERS = "Content-Type, Accept, Accept-Language"
# Short second-level labels under a country code that are public suffixes (co.uk, com.au, ...): never a site's parent.
_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "edu", "ac", "or", "ne", "go", "sch", "mil"})


def _twins(scheme: str, host: str, port: str) -> set[str]:
    twin = host[4:] if host.startswith("www.") else "www." + host
    if host.replace(".", "").isdigit() or host == "localhost" or ":" in host:
        twin = host
    return {f"{scheme}://{host}{port}", f"{scheme}://{twin}{port}"}


def _parts(url: str) -> tuple[str, str, str] | None:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts.scheme, parts.hostname.lower(), f":{parts.port}" if parts.port else ""


def parent_origins(app_url: str) -> set[str]:
    """The fallback: the registrable parent of the app host and its `www.` twin (empty when there is no safe parent)."""
    parsed = _parts(app_url)
    if parsed is None:
        return set()
    scheme, host, port = parsed
    labels = host.split(".")
    if len(labels) < 3 or host.replace(".", "").isdigit() or ":" in host:
        return set()
    parent = labels[1:]
    if len(parent) == 2 and len(parent[1]) == 2 and parent[0] in _SECOND_LEVEL:
        return set()
    return _twins(scheme, ".".join(parent), port)


def allowed_origins() -> set[str]:
    """The site's origin and its www twin when `public.site_url` is set, else the app host's parent (see above)."""
    try:
        parsed = _parts(str(behaviour.get("public.site_url") or ""))
        if parsed is not None:
            return _twins(*parsed)
        return parent_origins(behaviour.public_web_url())
    except Exception:  # noqa: BLE001 - a missing master database must not break unrelated requests
        return set()


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

"""Which host name may reach which part of the API (defence in depth behind the reverse proxy).

A production install serves the business web app on one host name (`ZIIRA_APP_HOST`, e.g. app.example.com) and the
Super Admin on another (`ZIIRA_OPERATOR_HOST`, e.g. admin.example.com). The reverse proxy already keeps staff routes
off the business host and business routes off the staff host; this middleware repeats the rule inside the API so one
proxy mistake does not expose the Super Admin on the wrong name.

* `ZIIRA_OPERATOR_HOST` set: `/api/v1/operator` answers only when the `Host` header equals it; anywhere else it is a
  plain 404 (the route is not revealed).
* `ZIIRA_APP_HOST` also set (and different): on the operator host only the operator, public and edition routes exist;
  the business API answers 404 there.
* Both empty (development, tests): no restriction. Only `/api/...` paths are ever refused, so `/healthz`, `/readyz` and
  `/metrics` keep working for probes. There is deliberately no loopback exception: a caller who can choose the Host
  header must not be able to pick `localhost` to reach staff routes (checks from the server itself send the real
  `Host` header, e.g. `curl -H 'Host: admin.example.com' http://127.0.0.1:8000/...`).
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from ziira.kernel.config import get_settings

OPERATOR_PREFIX = "/api/v1/operator"
# What the Super Admin host may serve besides its own routes: the public plans/site content and the edition list.
OPERATOR_HOST_SHARED = ("/api/v1/public", "/api/v1/editions")


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def host_name(raw: str) -> str:
    """Host header to bare name: lower case, no port, no trailing dot (`A.Example.com:443` is `a.example.com`)."""
    value = raw.strip().lower()
    if value.startswith("["):                       # [::1]:8000
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    return value.rstrip(".")


def decision(host: str, path: str, operator_host: str, app_host: str) -> bool:
    """True when the request may continue, False when it must be answered 404."""
    operator_host, app_host = host_name(operator_host), host_name(app_host)
    name = host_name(host)
    if operator_host and _under(path, OPERATOR_PREFIX) and name != operator_host:
        return False
    return not (operator_host and app_host and operator_host != app_host and name == operator_host
                and path.startswith("/api/") and not _under(path, OPERATOR_PREFIX)
                and not any(_under(path, p) for p in OPERATOR_HOST_SHARED))


class HostRoutingMiddleware:
    """Pure ASGI middleware: see the module text."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            settings = get_settings()
            if settings.operator_host.strip():
                headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
                if not decision(headers.get("host", ""), str(scope.get("path", "")), settings.operator_host,
                                settings.app_host):
                    body = b'{"error":"not_found","message":"Not found"}'
                    await send({"type": "http.response.start", "status": 404,
                                "headers": [(b"content-type", b"application/json"),
                                            (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return
        await self.app(scope, receive, send)

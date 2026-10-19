"""The public API: the documented, versioned subset of `/api/v1` that integrations (API keys) may use.

`PUBLIC_ENDPOINTS` is the list. Those operations are tagged `Public` in the OpenAPI description, published on their
own at `GET /api/v1/public/openapi.json`, and are the only ones an API key can call. They follow the policy in
`docs/public-api.md`: no breaking change inside `/api/v1`; an endpoint to be removed first gets `DEPRECATIONS` entry,
which adds the `Deprecation` and `Sunset` response headers.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import format_datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_VERSION = "1"
PUBLIC_TAG = "Public"

# (method, path as declared in the OpenAPI description). Every one must exist (tests/test_public_api.py checks it).
PUBLIC_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/products/products"),
        ("POST", "/api/v1/products/products"),
        ("GET", "/api/v1/products/products/{product_id}"),
        ("GET", "/api/v1/crm/customers"),
        ("POST", "/api/v1/crm/customers"),
        ("GET", "/api/v1/crm/customers/{customer_id}"),
        ("GET", "/api/v1/pos/sales"),
        ("GET", "/api/v1/pos/sales/{sale_id}"),
        ("GET", "/api/v1/pos/invoices"),
        ("GET", "/api/v1/pos/invoices/{invoice_id}"),
        ("GET", "/api/v1/inventory/balances"),
        ("GET", "/api/v1/inventory/products/{product_id}/stock"),
        ("GET", "/api/v1/payments/payments"),
        ("GET", "/api/v1/payments/payments/{payment_id}"),
        ("GET", "/api/v1/intel/findings"),
        ("GET", "/api/v1/intel/findings/{finding_id}"),
        ("POST", "/api/v1/memberships/access/decision"),
        ("GET", "/api/v1/memberships/access/allowed"),
    }
)


@dataclass(frozen=True)
class Deprecation:
    """An endpoint on its way out: when it was deprecated, when it stops, and where the replacement is described."""

    deprecated_on: date
    sunset_on: date
    link: str = ""


# (method, path) -> Deprecation. Empty in 1.0; see docs/public-api.md for the policy (at least 6 months' notice).
DEPRECATIONS: dict[tuple[str, str], Deprecation] = {}


def _pattern(template: str) -> re.Pattern[str]:
    """`/api/v1/pos/sales/{sale_id}` -> a pattern for the real path (the router only knows the path relative to its
    prefix, so requests are matched on the URL itself)."""
    return re.compile("^" + re.sub(r"\\\{[a-z_]+\\\}", "[^/]+", re.escape(template)) + "/?$")


_PUBLIC_PATTERNS = [(method, _pattern(path)) for method, path in PUBLIC_ENDPOINTS]


def is_public(method: str, path: str) -> bool:
    """True if this request (method and URL path) is one of the public API's operations."""
    verb = "GET" if method.upper() == "HEAD" else method.upper()
    return any(m == verb and p.match(path) for m, p in _PUBLIC_PATTERNS)


def deprecation_for(method: str, path: str) -> Deprecation | None:
    """The deprecation notice of the operation this request calls, if it has one."""
    for (m, template), notice in DEPRECATIONS.items():
        if m == method.upper() and _pattern(template).match(path):
            return notice
    return None


def tag_public(schema: dict[str, Any]) -> dict[str, Any]:
    """Add the `Public` tag to the public operations of a full OpenAPI description (in place)."""
    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if (method.upper(), path) in PUBLIC_ENDPOINTS:
                tags = operation.setdefault("tags", [])
                if PUBLIC_TAG not in tags:
                    tags.insert(0, PUBLIC_TAG)
    return schema


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and v.startswith("#/components/schemas/"):
                found.add(v.rsplit("/", 1)[1])
            else:
                found |= _refs(v)
    elif isinstance(node, list):
        for v in node:
            found |= _refs(v)
    return found


def public_schema(full: dict[str, Any]) -> dict[str, Any]:
    """The OpenAPI description of the public operations only, with just the schemas they use."""
    paths: dict[str, Any] = {}
    for path, operations in full.get("paths", {}).items():
        kept = {m: op for m, op in operations.items() if (m.upper(), path) in PUBLIC_ENDPOINTS}
        if kept:
            paths[path] = kept
    components = full.get("components", {}).get("schemas", {})
    needed: set[str] = set()
    todo = _refs(paths)
    while todo:
        name = todo.pop()
        if name in needed or name not in components:
            continue
        needed.add(name)
        todo |= _refs(components[name])
    return {
        "openapi": full["openapi"],
        "info": {
            "title": "Ziira Core public API",
            "version": f"v{API_VERSION}",
            "description": "The stable subset of /api/v1 for integrations. Authenticate with an API key in "
            "the X-API-Key header. Policy: docs/public-api.md.",
        },
        "tags": [{"name": PUBLIC_TAG}],
        "paths": paths,
        "components": {"schemas": {n: components[n] for n in sorted(needed)}},
    }


class PublicApiHeaders:
    """ASGI middleware: `Ziira-API-Version` on API replies; `Deprecation`, `Sunset`, `Link` on deprecated ones."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"ziira-api-version", API_VERSION.encode()))
                found = deprecation_for(scope["method"], scope["path"]) if DEPRECATIONS else None
                if found is not None:
                    headers.append((b"deprecation", f"@{_epoch(found.deprecated_on)}".encode()))
                    headers.append((b"sunset", format_datetime(_moment(found.sunset_on), usegmt=True).encode()))
                    if found.link:
                        headers.append((b"link", f'<{found.link}>; rel="deprecation"'.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, with_headers)


def _moment(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _epoch(day: date) -> int:
    return int(_moment(day).timestamp())

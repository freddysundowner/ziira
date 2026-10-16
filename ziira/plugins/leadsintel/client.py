"""The Lead Intel HTTP client: one place that knows the base address, the key header and how errors look.

Only the calls documented at https://leadsintel.net/developers.html (read 2026-10-15) are here. The pieces that are not
documented (message-template creation and approval) are in `unverified.py` and use this client too.

The platform key is a secret: it is sent only in the Authorization header, never put in a URL, a log line or an error.
The HTTP client comes from `client_factory`, which tests replace with one on a mock transport.
"""

import logging
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger("ziira.leadsintel")
BASE_URL = "https://app.leadsintel.net/api"
TIMEOUT_SECONDS = 15.0
RETRYABLE_STATUS = frozenset({408, 425, 429})


def client_factory() -> httpx.Client:
    """The HTTP client used for every call (replaced in tests)."""
    return httpx.Client(timeout=httpx.Timeout(TIMEOUT_SECONDS))


class LeadIntelError(Exception):
    """Lead Intel refused a call, or could not be reached (`status` 0)."""

    def __init__(self, status: int, code: str = "", detail: str = "", retry_after: int | None = None,
                 extra: dict[str, Any] | None = None) -> None:
        self.status, self.code, self.detail, self.retry_after = status, code, detail, retry_after
        self.extra = extra or {}
        super().__init__(f"Lead Intel replied {status} {code}".strip() + (f": {detail}" if detail else ""))

    @property
    def retryable(self) -> bool:
        """True for an outage or a rate limit: the same call may succeed later."""
        return self.status == 0 or self.status in RETRYABLE_STATUS or self.status >= 500


def _error_from(response: httpx.Response) -> LeadIntelError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    data = body if isinstance(body, dict) else {}
    code = str(data.get("error") or data.get("code") or "")[:80]
    detail = str(data.get("detail") or data.get("message") or "")[:300]
    retry = response.headers.get("Retry-After", "")
    return LeadIntelError(response.status_code, code, detail, int(retry) if retry.isdigit() else None,
                          {k: v for k, v in data.items() if k in ("attemptsLeft", "reason")})


class LeadIntelClient:
    """Calls to Lead Intel with one platform key."""

    def __init__(self, platform_key: str, base_url: str = BASE_URL,
                 factory: Callable[[], httpx.Client] | None = None) -> None:
        self._key = platform_key
        self._base = base_url.rstrip("/")
        self._factory = factory

    def call(self, method: str, path: str, body: dict[str, Any] | None = None,
             idempotency_key: str | None = None) -> dict[str, Any]:
        """One call. Returns the JSON reply ({} when there is none). Raises LeadIntelError."""
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with (self._factory or client_factory)() as http:
                response = http.request(method, f"{self._base}{path}", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise LeadIntelError(0, "unreachable", type(exc).__name__) from None
        if response.status_code >= 400:
            raise _error_from(response)
        if not response.content:
            return {}
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ----------------------------------------------------------------------- documented: connecting a number
    def create_assisted_request(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.call("POST", "/external-platform/whatsapp/assisted-requests", body)

    def get_assisted_request(self, request_id: str) -> dict[str, Any]:
        return self.call("GET", f"/external-platform/whatsapp/assisted-requests/{request_id}")

    def cancel_assisted_request(self, request_id: str) -> None:
        self.call("DELETE", f"/external-platform/whatsapp/assisted-requests/{request_id}")

    def lookup_connection(self, phone: str) -> dict[str, Any]:
        return self.call("POST", "/external-platform/whatsapp/connections/lookup", {"phoneNumber": phone})

    def lookup_existing_number(self, phone: str) -> dict[str, Any]:
        return self.call("POST", "/external-platform/whatsapp/existing-numbers/lookup", {"phoneNumber": phone})

    def start_claim(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.call("POST", "/external-platform/whatsapp/existing-numbers/claims", body)

    def verify_claim(self, claim_id: str, code: str) -> dict[str, Any]:
        return self.call("POST", f"/external-platform/whatsapp/existing-numbers/claims/{claim_id}/verify",
                         {"code": code})

    # ----------------------------------------------------------------------- documented: a connection
    def get_connection(self, tenant_ref: str, connection_id: str) -> dict[str, Any]:
        return self.call("GET", f"/external-platform/whatsapp/connections/{tenant_ref}/{connection_id}")

    def update_connection(self, tenant_ref: str, connection_id: str, changes: dict[str, Any]) -> None:
        self.call("PATCH", f"/external-platform/whatsapp/connections/{tenant_ref}/{connection_id}", changes)

    def delete_connection(self, tenant_ref: str, connection_id: str) -> None:
        self.call("DELETE", f"/external-platform/whatsapp/connections/{tenant_ref}/{connection_id}")

    def send_whatsapp(self, tenant_ref: str, connection_id: str, body: dict[str, Any],
                      idempotency_key: str) -> dict[str, Any]:
        """Send one message. 202 {messageId, status: "accepted"} means handed to the provider, not delivered."""
        return self.call("POST", f"/external-platform/whatsapp/connections/{tenant_ref}/{connection_id}/send", body,
                         idempotency_key=idempotency_key)

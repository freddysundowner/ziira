"""Optional address allow-list for the Super Admin (`ZIIRA_OPERATOR_ALLOWED_NETWORKS`, docs/security.md).

When the setting lists networks (comma separated CIDRs), every request under `/api/v1/operator`, sign-in included, is
refused with 403 `network_not_allowed` unless the caller's address is inside one of them. Business routes are not
affected. The address is the one the rest of the platform uses (`auth.client_ip`): the connection's own address, or
behind a proxy you control (`ZIIRA_TRUST_FORWARDED_FOR=true`) the last `X-Forwarded-For` entry, which the proxy added;
earlier entries can be forged by the caller and are never used. A caller whose address cannot be read is refused.
Terminate the same rule at the reverse proxy too: this is the second lock, not the only one.
"""

import ipaddress
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ziira.kernel.auth import client_ip
from ziira.kernel.config import get_settings

log = logging.getLogger("ziira.operator_network")

PREFIX = "/api/v1/operator"


def allowed(address: str | None) -> bool:
    """True when no list is configured, or the address is inside one of the listed networks."""
    networks = get_settings().operator_network_list()
    if not networks:
        return True
    if address is None:
        return False
    ip = ipaddress.ip_address(address)
    return any(ip in network for network in networks if network.version == ip.version)


class OperatorNetworkMiddleware:
    """Pure ASGI middleware: refuses operator routes from addresses outside the allow-list."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] == "http" and (path == PREFIX or path.startswith(PREFIX + "/")) \
                and get_settings().operator_allowed_networks.strip():
            address = client_ip(Request(scope))
            if not allowed(address):
                log.info("Operator route refused for an address outside ZIIRA_OPERATOR_ALLOWED_NETWORKS")
                response = JSONResponse(status_code=403, content={
                    "error": "network_not_allowed", "message": "The Super Admin cannot be reached from this address"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

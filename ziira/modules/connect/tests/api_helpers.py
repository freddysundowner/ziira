"""Helpers for the API connectors' tests: a recording mock of the other system, and fixture loading."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ziira.modules.connect.public import CanonicalBatch, Connector

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    """A recorded-style reply from `fixtures/<name>`."""
    return json.loads((FIXTURES / name).read_text())


Handler = Callable[[httpx.Request], httpx.Response]


class FakeSystem:
    """Stands in for the other system's server: records every request and answers with `handler`."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []
        self.handler = handler

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def factory(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def attach(self, connector: Connector) -> Connector:
        connector.client_factory = self.factory
        return connector

    def methods(self) -> set[str]:
        return {r.method for r in self.requests}

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def json_reply(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def drain(batches: Any) -> list[CanonicalBatch]:
    return list(batches)


def records(batches: list[CanonicalBatch]) -> list[Any]:
    return [r for b in batches for r in b.records]

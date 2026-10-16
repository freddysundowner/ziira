"""Host-based routing of the Super Admin (`ZIIRA_OPERATOR_HOST` / `ZIIRA_APP_HOST`): ziira/kernel/host_routing.py."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from ziira.kernel.config import get_settings
from ziira.kernel.host_routing import HostRoutingMiddleware, decision, host_name


@pytest.fixture
def hosts() -> Iterator[object]:
    """Set the two host settings on the live settings object and restore them."""
    s = get_settings()
    before = (s.operator_host, s.app_host)
    yield s
    s.operator_host, s.app_host = before


def make_client() -> TestClient:
    app = FastAPI()
    for path in ("/api/v1/operator/sign-in", "/api/v1/operator", "/api/v1/public/plans", "/api/v1/editions",
                 "/api/v1/pos/sales", "/healthz", "/operator"):
        app.add_api_route(path, lambda: {"ok": True}, methods=["GET", "POST"])
    app.add_middleware(HostRoutingMiddleware)
    return TestClient(app)


def status(client: TestClient, path: str, host: str) -> int:
    return client.get(path, headers={"host": host}).status_code


def test_host_name_strips_port_case_and_dot() -> None:
    assert host_name("Admin.Example.com:443") == "admin.example.com"
    assert host_name("admin.example.com.") == "admin.example.com"
    assert host_name("[::1]:8000") == "::1"
    assert host_name("") == ""


@given(st.from_regex(r"[a-z0-9]([a-z0-9-]{0,20}[a-z0-9])?(\.[a-z]{2,6}){1,2}", fullmatch=True), st.integers(1, 65535))
def test_host_name_ignores_port_for_any_name(name: str, port: int) -> None:
    assert host_name(f"{name}:{port}") == name == host_name(name.upper())


def test_no_restriction_when_hosts_are_empty(hosts) -> None:  # type: ignore[no-untyped-def]
    hosts.operator_host, hosts.app_host = "", ""
    c = make_client()
    assert status(c, "/api/v1/operator/sign-in", "anything.example") == 200
    assert status(c, "/api/v1/pos/sales", "anything.example") == 200


def test_operator_routes_answer_only_on_the_operator_host(hosts) -> None:  # type: ignore[no-untyped-def]
    hosts.operator_host, hosts.app_host = "admin.example.com", "app.example.com"
    c = make_client()
    assert status(c, "/api/v1/operator/sign-in", "admin.example.com") == 200
    assert status(c, "/api/v1/operator/sign-in", "ADMIN.example.com:443") == 200
    assert status(c, "/api/v1/operator", "admin.example.com") == 200
    for wrong in ("app.example.com", "example.com", "localhost", "127.0.0.1", "", "admin.example.com.evil.test",
                  "xadmin.example.com"):
        assert status(c, "/api/v1/operator/sign-in", wrong) == 404, wrong
        assert status(c, "/api/v1/operator", wrong) == 404, wrong
    r = c.post("/api/v1/operator/sign-in", headers={"host": "app.example.com"})
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_business_api_is_not_served_on_the_operator_host(hosts) -> None:  # type: ignore[no-untyped-def]
    hosts.operator_host, hosts.app_host = "admin.example.com", "app.example.com"
    c = make_client()
    assert status(c, "/api/v1/pos/sales", "app.example.com") == 200
    assert status(c, "/api/v1/pos/sales", "admin.example.com") == 404
    assert status(c, "/api/v1/public/plans", "admin.example.com") == 200
    assert status(c, "/api/v1/editions", "admin.example.com") == 200
    assert status(c, "/healthz", "admin.example.com") == 200          # probes and non-API paths are never touched
    assert status(c, "/operator", "app.example.com") == 200            # the proxy, not the API, hides the staff page


def test_with_only_the_operator_host_set_business_routes_stay_open(hosts) -> None:  # type: ignore[no-untyped-def]
    hosts.operator_host, hosts.app_host = "admin.example.com", ""
    c = make_client()
    assert status(c, "/api/v1/pos/sales", "admin.example.com") == 200
    assert status(c, "/api/v1/operator/sign-in", "other.example.com") == 404


@given(st.text(max_size=40))
def test_decision_never_raises_and_keeps_operator_paths_closed(host: str) -> None:
    allowed = decision(host, "/api/v1/operator/x", "admin.example.com", "app.example.com")
    assert allowed == (host_name(host) == "admin.example.com")

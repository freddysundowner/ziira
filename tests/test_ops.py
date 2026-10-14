"""Operations and application security plumbing: health, readiness, metrics, request ids, logging, headers, limits."""

import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from ziira.kernel import platform_metrics
from ziira.kernel.config import get_settings
from ziira.kernel.http_middleware import HttpMiddleware
from ziira.kernel.observability import JsonFormatter, TextFormatter, configure_logging, http_metrics, redact


@pytest.fixture
def settings():  # type: ignore[no-untyped-def]
    """The live settings object, restored after the test."""
    s = get_settings()
    before = s.model_copy()
    yield s
    for name in type(s).model_fields:
        setattr(s, name, getattr(before, name))
    platform_metrics.clear_cache()


@pytest.fixture(scope="module")
def ops(client, registry):  # type: ignore[no-untyped-def]
    make_tenant("Ops One")
    make_tenant("Ops Two")
    return {"one": sign_in(client, "ops-one", "owner@ops-one.test"), "two": sign_in(client, "ops-two", "owner@ops-two.test")}


# --------------------------------------------------------------------------- health and readiness
def test_liveness_needs_no_database(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ready_when_database_template_and_migrations_are_in_order(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/readyz")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ready"}


def test_not_ready_when_the_template_database_is_missing(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.template_database = "ziira_no_such_template"
    r = client.get("/readyz")
    assert r.status_code == 503
    assert any("ziira_no_such_template" in p for p in r.json()["problems"])


def test_not_ready_when_the_master_database_cannot_be_reached(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.api import ops_routes

    @contextmanager
    def broken() -> Iterator[None]:
        raise ConnectionError("password=hunter2 refused")
        yield

    monkeypatch.setattr(ops_routes, "master_session", broken)
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["problems"] == ["master database unreachable: ConnectionError"]       # no detail leaked


def test_not_ready_when_a_unit_in_the_code_is_newer_than_the_database(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import registry

    real = registry.discover()
    name = next(iter(n for n, m in real.items() if not m.core))

    class Newer:
        def __init__(self, m) -> None:  # type: ignore[no-untyped-def]
            self.version = m.version + ".9"

    monkeypatch.setattr(registry, "discover", lambda: {name: Newer(real[name])})
    r = client.get("/readyz")
    assert r.status_code == 503 and name in r.json()["problems"][0] and "ziira install --all" in r.json()["problems"][0]


# --------------------------------------------------------------------------- metrics
def test_metrics_need_the_token_when_one_is_set(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.metrics_token = "t" * 32
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer " + "t" * 31}).status_code == 401
    r = client.get("/metrics", headers={"Authorization": "Bearer " + "t" * 32})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")


def test_metrics_are_refused_in_production_without_a_token(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.env, settings.metrics_token = "production", ""
    r = client.get("/metrics")
    assert r.status_code == 403 and "ZIIRA_METRICS_TOKEN" in r.json()["message"]


def test_metrics_open_in_development_without_a_token(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.env, settings.metrics_token = "development", ""
    assert client.get("/metrics").status_code == 200


def test_metrics_count_requests_by_route_template_and_status_class(client, ops, settings) -> None:  # type: ignore[no-untyped-def]
    settings.env, settings.metrics_token = "development", ""
    http_metrics.reset()
    for _ in range(3):
        assert client.get(f"/api/v1/exceptions/{uuid4()}").status_code == 401        # route matched, no sign-in
    client.get("/healthz")
    body = client.get("/metrics").text
    assert 'ziira_http_requests_total{method="GET",route="/api/v1/exceptions/{item_id}",status="4xx"} 3' in body
    assert 'ziira_http_requests_total{method="GET",route="/healthz",status="2xx"} 1' in body
    assert re.search(r'ziira_http_request_duration_seconds_count\{method="GET",route="/healthz"\} 1\b', body)
    assert 'ziira_http_request_duration_seconds_bucket{method="GET",route="/healthz",le="+Inf"} 1' in body
    # buckets are cumulative
    counts = [int(m) for m in re.findall(r'route="/healthz",le="[^"]+"\} (\d+)', body)]
    assert counts == sorted(counts)
    assert "{item_id}" in body and "ziira_http_requests_total{" in body and str(uuid4())[:8] not in body


def _insert_everything(tenant_id, *, jobs_failed=0, jobs_queued=0, notifications=(), outbox=(), periodic=None,  # type: ignore[no-untyped-def]
                       intel_failures=0) -> None:
    from ziira.kernel import exceptions_inbox
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.kernel.jobs import enqueue

    system_context(tenant_id)
    with tenant_session(tenant_id) as s:
        for _ in range(jobs_queued):
            enqueue(s, "ops.test")
        for _ in range(jobs_failed):
            enqueue(s, "ops.test")
        if jobs_failed:
            s.execute(text("update kernel.job set status = 'failed' where id in (select id from kernel.job "
                           "where status = 'queued' and job_type = 'ops.test' order by id desc limit :n)"),
                      {"n": jobs_failed})
        for status in notifications:
            s.execute(text("insert into kernel.notification (tenant_id, channel, template, status) "
                           "values (kernel.current_tenant(), 'sms', 'ops.test', :s)"), {"s": status})
        for minutes_old, attempts in outbox:
            s.execute(text("insert into kernel.event_outbox (tenant_id, event_type, aggregate_type, aggregate_id, "
                           "payload, created_at, attempts) values (kernel.current_tenant(), 'ops.test', 'ops', "
                           "gen_random_uuid(), '{}', now() - make_interval(mins => :m), :a)"),
                      {"m": minutes_old, "a": attempts})
        if periodic:
            name, hours_ago, error = periodic
            s.execute(text("insert into kernel.periodic_run (tenant_id, name, last_run_at, last_error) values "
                           "(kernel.current_tenant(), :n, now() - make_interval(hours => :h), :e)"),
                      {"n": name, "h": hours_ago, "e": error})
        for _ in range(intel_failures):
            exceptions_inbox.flag(s, unit="intel", kind="check_failed", message="check broke",
                                  dedupe_key=f"ops-{uuid4()}")


def test_platform_gauges_add_up_across_businesses(ops, registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.tenants import find_tenant

    one, two = find_tenant("ops-one").id, find_tenant("ops-two").id
    before = platform_metrics.collect()
    _insert_everything(one, jobs_queued=2, jobs_failed=1, notifications=("queued", "failed", "failed"),
                       outbox=((10, 0), (1, 0), (5, 10)), periodic=("ops.task", 3, None), intel_failures=1)
    _insert_everything(two, jobs_queued=1, notifications=("queued",), outbox=((30, 0),),
                       periodic=("ops.task", 5, "boom"), intel_failures=2)
    after = platform_metrics.collect()

    def delta(key: str) -> float:
        return after.sums[key] - before.sums[key]

    assert delta("jobs_queued") == 2 + 1            # the failed one is no longer queued
    assert delta("jobs_due") == 3
    assert delta("jobs_failed") == 1
    assert delta("notifications_queued") == 2 and delta("notifications_failed") == 2
    assert delta("outbox_pending") == 3 + 3         # (10 min, 1 min, 30 min) + one exception.raised per flagged item
    assert delta("outbox_stuck") == 1
    assert delta("intel_check_failures") == 3
    assert after.maxes["outbox_lag_seconds"] >= 30 * 60 - 5            # the 30-minute-old event is the oldest
    assert after.periodic_age["ops.task"] >= 5 * 3600 - 5              # the least recently run business
    assert after.periodic_failures["ops.task"] == 1
    assert after.tenant_errors == 0
    assert after.tenants.get("active", 0) >= 2

    text_out = "\n".join(platform_metrics.render(after))
    assert "ziira_outbox_lag_seconds " in text_out
    assert 'ziira_periodic_last_run_age_seconds{task="ops.task"}' in text_out
    assert 'ziira_tenants{status="active"}' in text_out
    assert "ziira_jobs_failed " in text_out and "ziira_notifications_failed " in text_out
    assert "ziira_intel_check_failures " in text_out


def test_platform_gauges_are_cached(ops, settings) -> None:  # type: ignore[no-untyped-def]
    settings.metrics_cache_seconds = 60
    platform_metrics.clear_cache()
    first = platform_metrics.snapshot()
    assert platform_metrics.snapshot() is first
    settings.metrics_cache_seconds = 0
    assert platform_metrics.snapshot() is not first


def test_one_unreadable_business_does_not_break_the_scrape(ops, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real = platform_metrics.tenant_session
    broken = {"n": 0}

    @contextmanager
    def flaky(tenant_id):  # type: ignore[no-untyped-def]
        broken["n"] += 1
        if broken["n"] == 1:
            raise ConnectionError("down")
        with real(tenant_id) as s:
            yield s

    monkeypatch.setattr(platform_metrics, "tenant_session", flaky)
    snap = platform_metrics.collect()
    assert snap.tenant_errors == 1 and snap.tenants.get("active", 0) >= 2


def test_collecting_for_many_businesses_is_cheap(ops, registry) -> None:  # type: ignore[no-untyped-def]
    started = time.monotonic()
    snap = platform_metrics.collect()
    per_tenant = (time.monotonic() - started) / max(snap.tenants.get("active", 1), 1)
    assert per_tenant < 0.5, per_tenant


# --------------------------------------------------------------------------- request ids, error bodies, headers
def test_every_response_has_a_request_id_and_a_given_one_is_kept(client) -> None:  # type: ignore[no-untyped-def]
    a = client.get("/healthz")
    assert re.fullmatch(r"[0-9a-f]{32}", a.headers["x-request-id"])
    b = client.get("/healthz", headers={"X-Request-ID": "front-door-1234"})
    assert b.headers["x-request-id"] == "front-door-1234"
    for bad in ("short", "has space in it", "x" * 200, "new\tline12345"):
        assert client.get("/healthz", headers={"X-Request-ID": bad}).headers["x-request-id"] != bad


def test_error_bodies_carry_the_request_id(client, ops) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/auth/sign-in", json={"workspace": "ops-one", "login": "nobody@ops-one.test", "password": "wrong-pass-1", "device_id": "dev-1"},
                    headers={"X-Request-ID": "trace-me-0001"})
    assert r.status_code == 401
    assert r.json()["request_id"] == "trace-me-0001" == r.headers["x-request-id"]


def test_security_headers_on_api_responses(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.env = "development"
    r = client.get("/healthz")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "camera=()" in h["permissions-policy"] and "microphone=()" in h["permissions-policy"]
    assert "geolocation=()" in h["permissions-policy"]
    assert h["cross-origin-opener-policy"] == "same-origin"
    assert h["content-security-policy"].startswith("default-src 'none'") and "frame-ancestors 'none'" in h["content-security-policy"]
    assert "strict-transport-security" not in h              # production only


def test_hsts_only_in_production(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.env = "production"
    assert client.get("/healthz").headers["strict-transport-security"].startswith("max-age=")


def test_api_documentation_pages_are_not_given_the_strict_policy(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/docs")
    assert r.status_code == 200 and "content-security-policy" not in r.headers
    assert r.headers["x-content-type-options"] == "nosniff"              # the other headers still apply


def test_authenticated_api_responses_are_not_cached(client, ops) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/auth/me", headers=ops["one"].headers)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/auth/me").headers["cache-control"] == "no-store"          # errors too


# --------------------------------------------------------------------------- CORS
def test_cors_is_off_by_default_and_an_allowlist_when_set(settings) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.app import create_app

    ask = {"Origin": "https://app.example.test", "Access-Control-Request-Method": "GET",
           "Access-Control-Request-Headers": "authorization"}
    off = TestClient(create_app()).options("/api/v1/auth/me", headers=ask)
    assert "access-control-allow-origin" not in off.headers

    settings.cors_origins = "https://app.example.test, https://other.example.test"
    on = TestClient(create_app())
    ok = on.options("/api/v1/auth/me", headers=ask)
    assert ok.headers["access-control-allow-origin"] == "https://app.example.test"
    assert "access-control-allow-credentials" not in ok.headers
    assert "x-request-id" in ok.headers                        # headers also apply to preflight answers
    bad = on.options("/api/v1/auth/me", headers={**ask, "Origin": "https://evil.example.test"})
    assert "access-control-allow-origin" not in bad.headers


def test_production_refuses_a_wildcard_cors_origin(settings) -> None:  # type: ignore[no-untyped-def]
    settings.env, settings.cors_origins = "production", "*"
    settings.dev_tenant_header, settings.secret_key, settings.credentials_key = False, "s" * 40, "c" * 40
    settings.platform_email_provider = "smtp"
    with pytest.raises(RuntimeError, match="never"):
        settings.check_safe_for_production()


# --------------------------------------------------------------------------- request limits
def test_requests_over_the_limit_are_refused_even_without_a_content_length(client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.max_body_bytes = 1000

    def chunks() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * 500

    r = client.post("/api/v1/auth/sign-in", content=chunks())          # sent chunked: no declared size
    assert r.status_code == 413 and r.json()["error"] == "too_large" and r.json()["request_id"]
    r = client.post("/api/v1/auth/sign-in", content=b"x" * 1001)
    assert r.status_code == 413
    assert client.post("/api/v1/auth/sign-in", content=b"{}").status_code != 413


def _tiny_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(HttpMiddleware)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("database says password=hunter2 and zr_abcdef123456")

    @app.post("/echo/{item_id}")
    async def echo(item_id: str, request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    return app


def test_an_unhandled_error_gives_a_json_500_with_the_request_id_and_no_details(caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.INFO)
    r = TestClient(_tiny_app(), raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "internal_error" and body["request_id"] == r.headers["x-request-id"]
    assert "hunter2" not in r.text and "RuntimeError" not in r.text and "x-content-type-options" in r.headers


# --------------------------------------------------------------------------- logging
class _Capture(logging.Handler):
    """Formats each record with the JSON formatter at the moment it is emitted (inside the request)."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(JsonFormatter().format(record)))


@pytest.fixture
def access_lines() -> Iterator[_Capture]:
    handler = _Capture()
    log = logging.getLogger("ziira.access")
    old = log.level
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    yield handler
    log.removeHandler(handler)
    log.setLevel(old)


def test_one_access_line_per_request_with_route_template_tenant_and_request_id(client, ops, access_lines) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.tenants import find_tenant

    r = client.get(f"/api/v1/exceptions/{uuid4()}", headers={**ops["one"].headers, "X-Request-ID": "log-line-0001"})
    mine = [line for line in access_lines.lines if line.get("request_id") == "log-line-0001"]
    assert len(mine) == 1
    line = mine[0]
    assert line["route"] == "/api/v1/exceptions/{item_id}" and line["method"] == "GET"
    assert line["status"] == r.status_code and isinstance(line["duration_ms"], float)
    assert line["tenant_id"] == str(find_tenant("ops-one").id)
    assert ops["one"].headers["Authorization"].split()[1] not in json.dumps(line)


def test_json_log_lines_hide_secrets_in_messages_and_exceptions() -> None:
    log = logging.getLogger("ziira.test")
    try:
        raise ValueError("bad password=hunter2 for card 4111 1111 1111 1111")
    except ValueError:
        record = log.makeRecord("ziira.test", logging.ERROR, __file__, 1, "login failed Bearer abcdefgh12345678 zk_aa_bb11cc22dd",
                                (), __import__("sys").exc_info(), extra={"password": "p4ss", "note": "id 1234567890123"})
    out = JsonFormatter().format(record)
    for secret in ("hunter2", "4111 1111 1111 1111", "abcdefgh12345678", "zk_aa_bb11cc22dd", "p4ss", "1234567890123"):
        assert secret not in out, secret
    parsed = json.loads(out)
    assert parsed["level"] == "ERROR" and "exception" in parsed
    assert "hunter2" not in TextFormatter().format(record)


def test_log_format_setting_installs_the_chosen_formatter() -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("json", "INFO")
        ours = [h for h in root.handlers if getattr(h, "_ziira_handler", False)]
        assert len(ours) == 1 and isinstance(ours[0].formatter, JsonFormatter)
        configure_logging("text", "INFO")
        ours = [h for h in root.handlers if getattr(h, "_ziira_handler", False)]
        assert len(ours) == 1 and isinstance(ours[0].formatter, TextFormatter)
    finally:
        root.handlers[:] = before


# --------------------------------------------------------------------------- redaction (pure)
def luhn_number(prefix: str) -> str:
    digits = [int(c) for c in prefix]
    total = sum(d * 2 - 9 if d * 2 > 9 else d * 2 for d in digits[::-1][0::2]) + sum(digits[::-1][1::2])
    return prefix + str((10 - total % 10) % 10)


@pytest.mark.parametrize("raw, gone", [
    ("Authorization: Bearer abcdef0123456789", "abcdef0123456789"),
    ("refresh zr_0123456789abcdef_Sup3rSecret-token", "Sup3rSecret"),
    ("api key zk_0123456789abcdef_Sup3rSecret", "Sup3rSecret"),
    ("device zdk_ABCDEFGH12345678", "ABCDEFGH12345678"),
    ('{"password": "hunter2", "email": "a@b.test"}', "hunter2"),
    ("password=hunter2&next=/home", "hunter2"),
    ("new_password: 'hunter2'", "hunter2"),
    ("client_secret=abc123XYZ", "abc123XYZ"),
    ("cvv: 123", "123"),
])
def test_known_secret_shapes_are_removed(raw: str, gone: str) -> None:
    assert gone not in redact(raw)


def test_ordinary_text_survives_redaction() -> None:
    text_in = "GET /api/v1/users/3f2b8c1e-1234-4abc-9def-123456789012 200 12.5ms shipping: free total=1500 pin"
    assert redact(text_in) == text_in


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", min_size=8, max_size=40))
def test_property_our_token_formats_never_survive(secret: str) -> None:
    for prefix in ("zr_", "zk_", "zdk_"):
        assert secret not in redact(f"token was {prefix}{secret} ok")


@given(st.text(alphabet="0123456789", min_size=12, max_size=15))
def test_property_card_numbers_never_survive(prefix: str) -> None:
    card = luhn_number(prefix)
    assert card not in redact(f"paid with {card} today")
    grouped = " ".join(card[i:i + 4] for i in range(0, len(card), 4))
    assert grouped not in redact(f"paid with {grouped} today")


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^*()-_+.:", min_size=10,
               max_size=30))
def test_property_password_values_never_survive(value: str) -> None:
    secret = "Zq9" + value
    assert secret not in redact(f"password={secret}&x=1")
    assert secret not in redact(f'{{"password": "{secret}"}}')

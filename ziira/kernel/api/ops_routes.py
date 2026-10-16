"""Operations endpoints: liveness, readiness and Prometheus metrics. None of them returns business data.

- `GET /healthz`: the process is up. Touches nothing else, so a load balancer can use it without risk.
- `GET /readyz`: the process can serve: the master database answers, the tenant template exists and the platform's
  migrations and units are as current as this code. 503 with the reason otherwise.
- `GET /metrics`: Prometheus text; needs `Authorization: Bearer <ZIIRA_METRICS_TOKEN>`. Refused in production while no
  token is set.
"""

import hmac
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import text

from ziira.kernel import platform_metrics
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.observability import http_metrics

router = APIRouter(tags=["Operations"])
MASTER_MIGRATIONS = Path(__file__).resolve().parent.parent / "master_migrations"


@router.get("/healthz", summary="Liveness: the process is running")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def readiness_problems() -> list[str]:
    """Why this instance should not receive traffic (empty when it is ready)."""
    from ziira.kernel.registry import broken_units, discover

    problems: list[str] = []
    try:
        with master_session() as s:
            s.execute(text("select 1"))
            if s.execute(text("select to_regclass('master.schema_migration')")).scalar() is None:
                return ["master database has no schema yet: run `ziira install --all`"]
            applied = set(s.execute(text("select migration from master.schema_migration")).scalars())
            missing = sorted(f.name for f in MASTER_MIGRATIONS.glob("*.up.sql") if f.name not in applied)
            if missing:
                problems.append(f"master migrations not applied: {', '.join(missing)}")
            template = get_settings().template_database
            if s.execute(text("select 1 from pg_database where datname = :n"), {"n": template}).first() is None:
                problems.append(f"tenant template database '{template}' is missing")
            installed = {r.name: r.version for r in s.execute(text("select name, version from master.unit"))}
        outdated = [f"{name} ({installed[name]} installed, code is {m.version})"
                    for name, m in discover().items() if name in installed and installed[name] != m.version]
        if outdated:
            problems.append("units need `ziira install --all`: " + ", ".join(sorted(outdated)))
    except Exception as exc:  # noqa: BLE001 - any failure to ask means "not ready"
        return [f"master database unreachable: {type(exc).__name__}"]
    problems += [f"unit '{name}' could not be loaded and is skipped ({why})"
                 for name, why in sorted(broken_units.items())]
    return problems


@router.get("/readyz", summary="Readiness: the database and migrations are in order")
def readyz() -> Response:
    problems = readiness_problems()
    if problems:
        return JSONResponse(status_code=503, content={"status": "not_ready", "problems": problems})
    return JSONResponse(content={"status": "ready"})


@router.get("/metrics", summary="Prometheus metrics (bearer token)", include_in_schema=False)
def metrics(request: Request) -> Response:
    settings = get_settings()
    expected = settings.metrics_token
    if not expected:
        if settings.env == "production":
            return JSONResponse(status_code=403, content={
                "error": "forbidden", "message": "Metrics are switched off: set ZIIRA_METRICS_TOKEN"})
    else:
        header = request.headers.get("authorization", "")
        given = header[7:] if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(given.encode(), expected.encode()):
            return JSONResponse(status_code=401, content={"error": "unauthorized", "message": "Bearer token required"},
                                headers={"WWW-Authenticate": "Bearer"})
    lines = http_metrics.render()
    try:
        lines += platform_metrics.render(platform_metrics.snapshot())
    except Exception:  # noqa: BLE001 - HTTP metrics are still worth returning if the database is down
        lines += ["# platform metrics unavailable: master database not reachable", "ziira_metrics_up 0"]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

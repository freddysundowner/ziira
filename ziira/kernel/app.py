"""FastAPI application: mounts the API of every module and plugin.

Each unit's router is protected by `require_unit`, so its endpoints answer
only for tenants that have the unit enabled.
"""

import importlib
import logging
from collections.abc import Callable

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from ziira.kernel import notifications  # noqa: F401 - registers the send job and the channel socket
from ziira.kernel.api.notification_routes import router as notification_router
from ziira.kernel.api.operator_routes import router as operator_router
from ziira.kernel.api.ops_routes import router as ops_router
from ziira.kernel.api.organisation_routes import router as organisation_router
from ziira.kernel.api.privacy_routes import router as privacy_router
from ziira.kernel.api.routes import router as kernel_router
from ziira.kernel.api.security_routes import router as security_router
from ziira.kernel.api.support_routes import router as support_router
from ziira.kernel.api.unit_routes import router as unit_router
from ziira.kernel.config import get_settings
from ziira.kernel.errors import UnitNotEnabled, ZiiraError
from ziira.kernel.export_audit import ExportAuditMiddleware
from ziira.kernel.http_middleware import HttpMiddleware
from ziira.kernel.observability import configure_logging, current_request_id
from ziira.kernel.registry import discover, load_event_handlers
from ziira.kernel.support_log import SupportLogMiddleware
from ziira.sdk import DB_SESSION

log = logging.getLogger("ziira")


def require_unit(name: str) -> Callable[[Session], None]:
    """Dependency that rejects requests for units the tenant has not enabled."""

    def check(session: Session = DB_SESSION) -> None:
        enabled = session.execute(text(
            "select 1 from kernel.tenant_unit where unit_name = :n and status = 'enabled' "
            "and tenant_id = kernel.current_tenant()"), {"n": name}).first()
        if enabled is None:
            raise UnitNotEnabled(f"'{name}' is not enabled for this tenant")

    return check


def _with_request_id(body: dict[str, object]) -> dict[str, object]:
    """Add the request id to an error body so a user can quote it to support."""
    rid = current_request_id()
    return {**body, "request_id": rid} if rid else body


def create_app() -> FastAPI:
    """Build the application with all discovered units mounted."""
    get_settings().check_safe_for_production()
    configure_logging()
    app = FastAPI(title="Ziira Core", version="1.0.0.dev0")
    app.include_router(ops_router)
    app.include_router(kernel_router)
    app.include_router(security_router)
    app.include_router(notification_router)
    app.include_router(privacy_router)
    app.include_router(support_router)
    app.include_router(operator_router)
    app.include_router(organisation_router)
    app.include_router(unit_router)
    units = discover()
    load_event_handlers(units)

    for m in units.values():
        if m.core:
            continue
        if not m.api_prefix:
            continue
        try:
            routes = importlib.import_module(f"{m.package}.api.routes")
        except ModuleNotFoundError:
            log.info("Unit %s has no API yet", m.name)
            continue
        app.include_router(routes.router, prefix=m.api_prefix, tags=[m.title],
                           dependencies=[Depends(require_unit(m.name))])
        # Endpoints other systems call without a user login (payment callbacks): each authenticates itself.
        public = getattr(routes, "public_router", None)
        if public is not None:
            app.include_router(public, prefix=m.api_prefix, tags=[f"{m.title} (public callbacks)"])

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/docs")

    @app.get("/health", tags=["Kernel"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/units", tags=["Kernel"])
    def tenant_units(session: Session = DB_SESSION) -> list[dict[str, object]]:
        enabled = set(session.execute(text(
            "select unit_name from kernel.tenant_unit where status = 'enabled' "
            "and tenant_id = kernel.current_tenant()")).scalars())
        return [{"name": m.name, "title": m.title, "kind": m.kind, "version": m.version,
                 "requires": list(m.requires), "enabled": m.core or m.name in enabled}
                for m in units.values()]

    @app.exception_handler(ZiiraError)
    def ziira_error(_: Request, exc: ZiiraError) -> JSONResponse:
        body = {"error": exc.code, "message": exc.message, **(exc.details or {})}
        wait = (exc.details or {}).get("retry_after")
        return JSONResponse(status_code=exc.status, content=_with_request_id(body),
                            headers={"Retry-After": str(wait)} if wait else None)

    @app.exception_handler(IntegrityError)
    def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        # The database's own wording names tables and constraints; keep that in the log, not in the reply.
        log.info("Constraint violated: %s", str(exc.orig).splitlines()[0] if exc.orig else "")
        return JSONResponse(status_code=409, content=_with_request_id({
            "error": "conflict", "message": "This conflicts with something that already exists or changed meanwhile"}))

    @app.exception_handler(DataError)
    def data_error(_: Request, exc: DataError) -> JSONResponse:
        # A value the database cannot store (too large, wrong shape, NUL characters). The usual cases are caught
        # earlier by the request types; this keeps the rest from becoming a server error.
        log.warning("Rejected a value the database cannot store: %s", str(exc.orig).splitlines()[0] if exc.orig else "")
        return JSONResponse(status_code=422, content=_with_request_id({
            "error": "validation_failed", "message": "A value is too large, too long or contains characters "
                                                     "that are not allowed"}))

    origins = get_settings().cors_origin_list()
    if origins:
        # Bearer tokens travel in a header, not a cookie, so no credentials are allowed cross-origin.
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                           allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-API-Key",
                                          "X-Request-ID", "X-Device-ID", "Accept-Language"],
                           expose_headers=["X-Request-ID"], max_age=600)
    app.add_middleware(ExportAuditMiddleware)
    app.add_middleware(SupportLogMiddleware)
    app.add_middleware(HttpMiddleware)          # outermost: request id, access log, security headers, size limit

    return app


app = create_app()

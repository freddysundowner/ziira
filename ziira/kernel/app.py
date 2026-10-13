"""FastAPI application: mounts the API of every module and plugin.

Each unit's router is protected by `require_unit`, so its endpoints answer
only for tenants that have the unit enabled.
"""

import importlib
import logging
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from ziira.kernel.api.routes import router as kernel_router
from ziira.kernel.config import get_settings
from ziira.kernel.errors import UnitNotEnabled, ZiiraError
from ziira.kernel.registry import discover, load_event_handlers
from ziira.sdk import db_session

log = logging.getLogger("ziira")
MAX_BODY_BYTES = 2_000_000          # no request of ours needs more; bigger ones are refused before they are read


def require_unit(name: str) -> Callable[[Session], None]:
    """Dependency that rejects requests for units the tenant has not enabled."""

    def check(session: Session = Depends(db_session)) -> None:
        enabled = session.execute(text(
            "select 1 from kernel.tenant_unit where unit_name = :n and status = 'enabled' "
            "and tenant_id = kernel.current_tenant()"), {"n": name}).first()
        if enabled is None:
            raise UnitNotEnabled(f"'{name}' is not enabled for this tenant")

    return check


def create_app() -> FastAPI:
    """Build the application with all discovered units mounted."""
    get_settings().check_safe_for_production()
    app = FastAPI(title="Ziira Core", version="1.0.0.dev0")
    app.include_router(kernel_router)
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
    def tenant_units(session: Session = Depends(db_session)) -> list[dict[str, object]]:
        enabled = set(session.execute(text(
            "select unit_name from kernel.tenant_unit where status = 'enabled' "
            "and tenant_id = kernel.current_tenant()")).scalars())
        return [{"name": m.name, "title": m.title, "kind": m.kind, "version": m.version,
                 "requires": list(m.requires), "enabled": m.core or m.name in enabled}
                for m in units.values()]

    @app.exception_handler(ZiiraError)
    def ziira_error(_: Request, exc: ZiiraError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(IntegrityError)
    def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        # The database's own wording names tables and constraints; keep that in the log, not in the reply.
        log.info("Constraint violated: %s", str(exc.orig).splitlines()[0] if exc.orig else "")
        return JSONResponse(status_code=409, content={
            "error": "conflict", "message": "This conflicts with something that already exists or changed meanwhile"})

    @app.exception_handler(DataError)
    def data_error(_: Request, exc: DataError) -> JSONResponse:
        # A value the database cannot store (too large, wrong shape, NUL characters). The usual cases are caught
        # earlier by the request types; this keeps the rest from becoming a server error.
        log.warning("Rejected a value the database cannot store: %s", str(exc.orig).splitlines()[0] if exc.orig else "")
        return JSONResponse(status_code=422, content={
            "error": "validation_failed", "message": "A value is too large, too long or contains characters "
                                                     "that are not allowed"})

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        declared = request.headers.get("content-length", "0")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"error": "too_large", "message": "The request is too large"})
        return await call_next(request)

    return app


app = create_app()

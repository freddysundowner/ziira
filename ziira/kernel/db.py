"""Database engines and tenant-scoped sessions (one database per tenant).

- The master database lists tenants and how to reach each tenant's own database.
- Each tenant has its own database and its own login. Application work connects with that
  login, which does not own the tables, so row-level security still applies inside the
  tenant database as a second safety layer (`app.tenant_id` is set on every transaction).
- Admin work (migrations, provisioning) uses an owner login to the tenant database.
"""

import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from ziira.kernel.config import get_settings
from ziira.kernel.errors import NotFound
from ziira.kernel.security import decrypt


@lru_cache
def master_engine() -> Engine:
    """Engine for the master database (owner)."""
    settings = get_settings()
    return create_engine(settings.master_database_url, pool_pre_ping=True, pool_size=settings.master_pool_size,
                         max_overflow=settings.db_max_overflow, pool_timeout=settings.db_pool_timeout,
                         pool_recycle=settings.db_pool_recycle, **_driver_args())


def ensure_master_database() -> None:
    """Create the master database if it does not exist yet (same server and login as its URL)."""
    url = make_url(get_settings().master_database_url)
    engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            if conn.execute(text("select 1 from pg_database where datname = :d"), {"d": url.database}).first() is None:
                conn.exec_driver_sql(f'create database "{url.database}"')
    finally:
        engine.dispose()


@lru_cache
def server_engine() -> Engine:
    """Autocommit engine on the tenant server, for CREATE/DROP DATABASE and roles."""
    return create_engine(get_settings().tenant_server_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)


def server_database_url(database: str) -> str:
    """Owner URL for another database on the tenant server (e.g. the template)."""
    return make_url(get_settings().tenant_server_url).set(database=database).render_as_string(hide_password=False)


def _driver_args() -> dict[str, Any]:
    """Driver settings for connecting through a transaction-pooling PgBouncer (`ZIIRA_PGBOUNCER=true`).

    Such a pooler hands a different server connection to each transaction, so nothing may be remembered on the
    server connection between transactions. psycopg's automatic server-side prepared statements would be: switched off.
    Everything else we keep per transaction already (`set_config(..., true)`, `pg_advisory_xact_lock`).
    """
    return {"connect_args": {"prepare_threshold": None}} if get_settings().pgbouncer else {}


def _new_engine(url: str) -> Engine:
    # Small pools: there is one pool per tenant database (sizes: ZIIRA_DB_POOL_SIZE, _MAX_OVERFLOW, _POOL_TIMEOUT).
    settings = get_settings()
    return create_engine(url, pool_pre_ping=True, pool_size=settings.db_pool_size,
                         max_overflow=settings.db_max_overflow,
                         pool_timeout=settings.db_pool_timeout, pool_recycle=settings.db_pool_recycle,
                         **_driver_args())


# Least recently used last. Capped (config.max_cached_tenant_engines): every tenant has its own database and pool, and
# PostgreSQL allows only so many connections in total.
_engines: OrderedDict[tuple[UUID, bool], Engine] = OrderedDict()
_engines_lock = threading.Lock()


def tenant_engine(tenant_id: UUID, *, admin: bool = False) -> Engine:
    """Engine for one tenant's database: its own login, or the owner login when `admin`."""
    key = (tenant_id, admin)
    with _engines_lock:
        engine = _engines.get(key)
        if engine is not None:
            _engines.move_to_end(key)                  # used just now
            return engine
        with master_engine().connect() as conn:
            row = conn.execute(text(
                "select app_url_encrypted, admin_url_encrypted from master.tenant "
                "where id = :t and status in ('provisioning', 'active')"), {"t": str(tenant_id)}).first()
        if row is None:
            raise NotFound("Tenant not found or not active")
        engine = _engines[key] = _new_engine(decrypt(row.admin_url_encrypted if admin else row.app_url_encrypted))
        while len(_engines) > max(get_settings().max_cached_tenant_engines, 1):
            _, oldest = _engines.popitem(last=False)
            oldest.dispose()                           # in-use connections finish and are closed when returned
        return engine


def forget_tenant(tenant_id: UUID) -> None:
    """Close a tenant's connections (after it moves, is suspended or is dropped)."""
    with _engines_lock:
        for admin in (False, True):
            engine = _engines.pop((tenant_id, admin), None)
            if engine is not None:
                engine.dispose()


def forget_all() -> None:
    """Close every cached connection (tests and settings changes)."""
    with _engines_lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
    for cached in (master_engine, server_engine):
        if cached.cache_info().currsize:
            cached().dispose()
        cached.cache_clear()


def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def tenant_session(tenant_id: UUID, *, admin: bool = False) -> Iterator[Session]:
    """Open a transaction in the tenant's own database; commit on success, roll back on error."""
    session = _session_factory(tenant_engine(tenant_id, admin=admin))()
    try:
        # Both settings are transaction-local (third argument true), so they never leak to the next user of a pooled
        # connection, and a transaction-pooling PgBouncer keeps working.
        timeout = 0 if admin else max(get_settings().statement_timeout_ms, 0)
        session.execute(
            text("select set_config('app.tenant_id', :tenant, true), set_config('statement_timeout', :t, true)"),
            {"tenant": str(tenant_id), "t": str(timeout)}
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def master_session() -> Iterator[Session]:
    """Open a transaction in the master database (platform administration only)."""
    session = _session_factory(master_engine())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

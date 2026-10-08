"""Database engines and tenant-scoped sessions.

Every application session runs inside one transaction with the tenant set
through `app.tenant_id`, which PostgreSQL row-level security uses to hide
and protect other tenants' rows.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ziira.kernel.config import get_settings


@lru_cache
def app_engine() -> Engine:
    """Engine for application queries (non-owner role, row-level security applies)."""
    return create_engine(get_settings().app_database_url, pool_pre_ping=True)


@lru_cache
def admin_engine() -> Engine:
    """Engine for migrations and admin commands (table owner)."""
    return create_engine(get_settings().admin_database_url, pool_pre_ping=True)


def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def tenant_session(tenant_id: UUID, *, admin: bool = False) -> Iterator[Session]:
    """Open a transaction scoped to one tenant; commit on success, roll back on error."""
    engine = admin_engine() if admin else app_engine()
    session = _session_factory(engine)()
    try:
        session.execute(
            text("select set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def admin_session() -> Iterator[Session]:
    """Open an owner-level transaction with no tenant (platform administration only)."""
    session = _session_factory(admin_engine())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

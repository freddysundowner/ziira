"""Connection pools: sizes from settings, a capped cache of tenant engines, and nothing kept between transactions
(so the engines work behind PgBouncer in transaction pooling mode)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from tests.conftest import make_tenant
from ziira.kernel import db
from ziira.kernel.config import get_settings


@pytest.fixture
def settings():  # type: ignore[no-untyped-def]
    """The live settings, restored afterwards; engines are rebuilt so each test sees its own settings."""
    s = get_settings()
    before = s.model_copy()
    db.forget_all()
    yield s
    for name in type(s).model_fields:
        setattr(s, name, getattr(before, name))
    db.forget_all()


@pytest.fixture(scope="module")
def three(registry):  # type: ignore[no-untyped-def]
    return [make_tenant(f"Pool {n}")["tenant_id"] for n in "ABC"]


def test_pool_sizes_and_timeouts_come_from_settings(three, settings) -> None:  # type: ignore[no-untyped-def]
    settings.db_pool_size, settings.db_max_overflow, settings.db_pool_timeout = 3, 4, 7
    pool = db.tenant_engine(three[0]).pool
    assert pool.size() == 3 and pool._max_overflow == 4 and pool._timeout == 7      # type: ignore[attr-defined]


def test_the_number_of_cached_tenant_engines_is_capped_and_the_least_recently_used_is_closed(three, settings) -> None:  # type: ignore[no-untyped-def]
    a, b, c = three
    settings.max_cached_tenant_engines = 2
    engine_a, engine_b = db.tenant_engine(a), db.tenant_engine(b)
    with engine_b.connect():
        pass
    assert db.tenant_engine(a) is engine_a                    # a is now the most recently used
    engine_c = db.tenant_engine(c)                            # one too many: b (least recently used) is dropped
    cached = {key[0] for key in db._engines}
    assert cached == {a, c} and len(db._engines) == 2
    assert db.tenant_engine(c) is engine_c and db.tenant_engine(a) is engine_a
    assert engine_b.pool.checkedin() == 0                     # disposed: its idle connections were closed
    reopened = db.tenant_engine(b)                            # still usable: reopened on demand
    assert reopened is not engine_b
    with reopened.connect() as conn:
        assert conn.execute(text("select 1")).scalar_one() == 1
    assert len(db._engines) == 2


def test_a_cap_below_one_still_keeps_one_engine(three, settings) -> None:  # type: ignore[no-untyped-def]
    settings.max_cached_tenant_engines = 0
    db.tenant_engine(three[0])
    db.tenant_engine(three[1])
    assert len(db._engines) == 1


def test_an_evicted_engine_does_not_break_a_transaction_in_progress(three, settings) -> None:  # type: ignore[no-untyped-def]
    settings.max_cached_tenant_engines = 1
    with db.tenant_session(three[0]) as s:
        db.tenant_engine(three[1])                            # evicts and disposes the engine this session uses
        assert s.execute(text("select 1")).scalar_one() == 1
    with db.tenant_session(three[0]) as s:
        assert s.execute(text("select kernel.current_tenant()")).scalar_one() == three[0]


def test_nothing_is_left_on_the_connection_between_transactions(three, settings) -> None:  # type: ignore[no-untyped-def]
    """One physical connection serves two transactions: the tenant and the timeout of the first must be gone."""
    settings.db_pool_size, settings.db_max_overflow, settings.statement_timeout_ms = 1, 0, 45000
    with db.tenant_session(three[0]) as s:
        assert s.execute(text("select current_setting('app.tenant_id')")).scalar_one() == str(three[0])
        assert s.execute(text("show statement_timeout")).scalar_one() == "45s"
        pid = s.execute(text("select pg_backend_pid()")).scalar_one()
    with db.tenant_engine(three[0]).connect() as conn:
        assert conn.execute(text("select pg_backend_pid()")).scalar_one() == pid          # the same connection
        assert conn.execute(text("select coalesce(current_setting('app.tenant_id', true), '')")).scalar_one() == ""
        assert conn.execute(text("show statement_timeout")).scalar_one() == "0"


def test_pgbouncer_mode_turns_off_server_side_prepared_statements(three, settings) -> None:  # type: ignore[no-untyped-def]
    settings.pgbouncer = True
    with db.tenant_engine(three[0]).connect() as conn:
        assert conn.connection.dbapi_connection.prepare_threshold is None            # type: ignore[union-attr]
        for _ in range(12):                                   # past psycopg's default threshold of 5
            assert conn.execute(text("select :n + 1"), {"n": 1}).scalar_one() == 2
    with db.master_engine().connect() as conn:
        assert conn.connection.dbapi_connection.prepare_threshold is None            # type: ignore[union-attr]


def test_prepared_statements_stay_on_by_default(three, settings) -> None:  # type: ignore[no-untyped-def]
    with db.tenant_engine(three[0]).connect() as conn:
        assert conn.connection.dbapi_connection.prepare_threshold == 5               # type: ignore[union-attr]


def test_a_statement_over_the_timeout_is_cancelled_but_admin_work_is_not_limited(three, settings) -> None:  # type: ignore[no-untyped-def]
    settings.statement_timeout_ms = 200
    with pytest.raises(OperationalError, match="statement timeout"), db.tenant_session(three[0]) as s:
        s.execute(text("select pg_sleep(1)"))
    with db.tenant_session(three[0], admin=True) as s:
        s.execute(text("select pg_sleep(0.5)"))               # no limit for migrations and provisioning
    with db.tenant_session(three[0]) as s:                    # and the cancelled one left the pool healthy
        assert s.execute(text("select 1")).scalar_one() == 1


def test_a_timeout_of_zero_means_no_limit(three, settings) -> None:  # type: ignore[no-untyped-def]
    settings.statement_timeout_ms = 0
    with db.tenant_session(three[0]) as s:
        assert s.execute(text("show statement_timeout")).scalar_one() == "0"

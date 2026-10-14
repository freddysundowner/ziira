"""Create or drop the scratch databases the end-to-end tests use (never touches the dev or test databases).

  python e2e/scratch_db.py drop     drop the e2e master, template, every e2e business database and login
  python e2e/scratch_db.py create   drop, then create an empty e2e master database
"""
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ADMIN = make_url(os.environ.get("ZIIRA_TEST_ADMIN_URL", "postgresql+psycopg://ziira:ziira@localhost:5433/postgres"))
MASTER, TEMPLATE, DB_PREFIX, ROLE_PREFIX = "ziira_e2e_master", "ziira_e2e_template", "ziira_e2e_t_", "ze2e_"


def drop() -> None:
    engine = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        names = c.execute(text("select datname from pg_database where datname like :p or datname in (:m, :t)"),
                          {"p": DB_PREFIX + "%", "m": MASTER, "t": TEMPLATE}).scalars().all()
        for db in names:
            c.execute(text(f'drop database "{db}" with (force)'))
        for role in c.execute(text("select rolname from pg_roles where rolname like :p"),
                              {"p": ROLE_PREFIX + "%"}).scalars().all():
            c.execute(text(f'drop role "{role}"'))
    engine.dispose()


if __name__ == "__main__":
    drop()
    if sys.argv[1] == "create":
        engine = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
        with engine.connect() as c:
            c.execute(text(f"create database {MASTER}"))
        engine.dispose()

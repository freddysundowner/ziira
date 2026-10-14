"""The rich demo data script (scripts/seed_demo_rich.py) keeps working: it fills a tiny business through the real
services, `ziira verify` and the trial balance are clean afterwards, and the planted stories produce their findings.

The script is run at its smallest scale ("tiny": one branch, 20 counter sales, 14 days) on a scratch business named
`demo-seedtest`, so this takes about half a minute. The full 90-day run is checked by hand (docs/demo-data.md)."""

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import OWNER_PASSWORD, make_tenant

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_demo_rich.py"


def load_script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("seed_demo_rich", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo_rich"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seeded(registry):  # type: ignore[no-untyped-def]
    make_tenant("demo-seedtest")
    script = load_script()
    seeder = script.seed("demo-seedtest", "tiny", owner_password=OWNER_PASSWORD)
    yield seeder


def test_refuses_what_it_must_not_touch(registry):  # type: ignore[no-untyped-def]
    script = load_script()
    with pytest.raises(SystemExit):
        script.check_code("aluta-technology-ventures-limited", i_know=True)
    with pytest.raises(SystemExit):
        script.check_code("some-real-business", i_know=False)
    script.check_code("demo-anything", i_know=False)
    with pytest.raises(SystemExit):
        script.reset_tenant("some-real-business", "some-real-business")
    with pytest.raises(SystemExit):
        script.reset_tenant("demo-hardware", None)


def test_the_tiny_business_is_filled_and_consistent(seeded):  # type: ignore[no-untyped-def]
    assert seeded.ok, "ziira verify, the trial balance and the planted stories must all be fine"
    assert seeded.created["POS sales"] >= 15
    assert seeded.created["journal entries"] > 50
    assert seeded.created["payroll runs"] >= 1
    assert seeded.created["till sessions"] >= 10


def test_planted_stories_fire_in_the_tiny_business(seeded):  # type: ignore[no-untyped-def]
    fired = {n for n, _title, good, _what in seeded.story_results if good}
    assert {2, 6, 7} <= fired, seeded.story_results


def test_running_it_again_changes_nothing(seeded):  # type: ignore[no-untyped-def]
    script = load_script()
    before = seeded.one("select count(*) from pos.sale")
    again = script.seed("demo-seedtest", "tiny", owner_password=OWNER_PASSWORD)
    assert again.skipped_all is True
    assert seeded.one("select count(*) from pos.sale") == before


def test_immutability_triggers_are_back_on(seeded):  # type: ignore[no-untyped-def]
    """The time-shifting pass switches triggers off for its length only."""
    off = seeded.sql(
        "select c.relname from pg_trigger t join pg_class c on c.oid = t.tgrelid "
        "join pg_namespace n on n.oid = c.relnamespace where not t.tgisinternal and t.tgenabled = 'D' "
        "and n.nspname not in ('pg_catalog', 'information_schema')")
    assert off == []
    with pytest.raises(DBAPIError), seeded.db() as s:
        s.execute(text("update inventory.stock_movement set quantity = quantity + 1"))

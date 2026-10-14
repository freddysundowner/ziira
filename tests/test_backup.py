"""Backups: the retention rule (pure), and a real pg_dump / pg_restore round trip with the restore test."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from ziira.kernel import backup
from ziira.kernel.backup import keep_set

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def at(days_ago: float) -> datetime:
    return NOW - timedelta(days=days_ago)


# --------------------------------------------------------------------------- retention rule (pure)
def test_nothing_to_keep_when_there_are_no_backups() -> None:
    assert keep_set([], NOW) == set()


def test_the_newest_backup_of_each_recent_day_is_kept() -> None:
    morning, evening = at(20).replace(hour=3), at(20).replace(hour=22)
    kept = keep_set([at(25), morning, evening, at(0)], NOW)             # at(25) is the month's oldest, so it is kept
    assert evening in kept and morning not in kept          # two on the same day: the newest stays
    assert at(0) in kept


def test_daily_backups_are_kept_for_35_days_and_then_only_monthly_ones_stay() -> None:
    days = [at(d) for d in range(0, 120)]                  # one per day for ~4 months
    kept = keep_set(days, NOW)
    for d in range(0, 35):
        assert at(d) in kept, d                            # today and the 34 days before it
    assert at(35) not in kept and at(36) not in kept
    older = [t for t in kept if t < at(34)]
    months = {(t.year, t.month) for t in days if t < at(34)}
    assert len(older) == len(months)                       # exactly one per month outside the daily window ...
    for t in older:
        assert t == min(d for d in days if (d.year, d.month) == (t.year, t.month))      # ... the month's oldest


def test_monthly_backups_are_kept_for_12_months() -> None:
    firsts = [datetime(y, m, 1, 1, 0, tzinfo=UTC) for y in (2024, 2025, 2026) for m in range(1, 13)
              if (y, m) <= (2026, 10)]
    kept = keep_set(firsts, NOW)
    assert datetime(2025, 11, 1, 1, 0, tzinfo=UTC) in kept          # this month and the 11 before it: 12 months
    assert datetime(2026, 10, 1, 1, 0, tzinfo=UTC) in kept
    assert datetime(2025, 10, 1, 1, 0, tzinfo=UTC) not in kept      # 13 months back
    assert datetime(2024, 1, 1, tzinfo=UTC) not in kept
    assert len(kept) == 12


def test_the_newest_backup_is_kept_however_old() -> None:
    old = datetime(2020, 5, 17, 3, 0, tzinfo=UTC)
    assert keep_set([old], NOW) == {old}


def test_exact_edges_of_the_windows() -> None:
    edge_day = at(34)                                       # the 35th day counting today
    just_outside = at(35)
    anchor = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)        # the oldest of September, kept as the monthly one
    kept = keep_set([anchor, just_outside, edge_day, at(0)], NOW)
    assert edge_day in kept
    assert just_outside not in kept
    # months: this month plus the 11 before it are monthly-eligible
    eligible = datetime(2025, 11, 20, tzinfo=UTC)
    too_old = datetime(2025, 10, 20, tzinfo=UTC)
    kept = keep_set([too_old, eligible, at(0)], NOW)
    assert eligible in kept and too_old not in kept


times = st.lists(st.datetimes(min_value=datetime(2024, 1, 1), max_value=datetime(2026, 10, 14, 12, 0), timezones=st.just(UTC)),
                 max_size=80, unique=True)


@settings(max_examples=150, deadline=None)
@given(times, st.integers(1, 60), st.integers(1, 24))
def test_property_retention_invariants(taken: list[datetime], keep_daily: int, keep_monthly: int) -> None:
    kept = keep_set(taken, NOW, keep_daily=keep_daily, keep_monthly=keep_monthly)
    assert kept <= set(taken)
    if taken:
        assert max(taken) in kept                           # the newest is always kept
    assert len(kept) <= keep_daily + keep_monthly + 1       # bounded: one per day, one per month, the newest
    # idempotent: pruning what is already pruned changes nothing
    assert keep_set(sorted(kept), NOW, keep_daily=keep_daily, keep_monthly=keep_monthly) == kept
    # every backup newer than the daily window's start has its day's newest kept
    first_day = (NOW - timedelta(days=keep_daily - 1)).date()
    for t in taken:
        if first_day <= t.date() <= NOW.date():
            same_day = [u for u in taken if u.date() == t.date()]
            assert max(same_day) in kept


# --------------------------------------------------------------------------- prune on disk
def write_fake(directory: Path, target: str, when: datetime) -> Path:
    folder = directory / target
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{target}-{when.strftime('%Y%m%dT%H%M%SZ')}"
    (folder / f"{name}.dump").write_bytes(b"x")
    (folder / f"{name}.json").write_text(json.dumps({"file": f"{name}.dump", "taken_at": when.isoformat()}))
    return folder / f"{name}.dump"


def test_prune_removes_dump_and_manifest_of_dropped_backups(tmp_path: Path) -> None:
    keep = [write_fake(tmp_path, "acme", at(d)) for d in (0, 1, 34, 41)]        # 41 is September's oldest
    drop = [write_fake(tmp_path, "acme", at(d)) for d in (36, 40)]
    other = write_fake(tmp_path, "other", at(40))                    # another target is untouched
    removed = backup.prune(tmp_path, "acme", now=NOW)
    assert set(removed) == set(drop)
    assert all(p.exists() and p.with_suffix(".json").exists() for p in keep)
    assert not any(p.exists() or p.with_suffix(".json").exists() for p in drop)
    assert other.exists()


def test_a_damaged_manifest_is_skipped_not_fatal(tmp_path: Path) -> None:
    write_fake(tmp_path, "acme", at(1))
    (tmp_path / "acme" / "acme-broken.json").write_text("{not json")
    assert len(backup.list_backups(tmp_path, "acme")) == 1


# --------------------------------------------------------------------------- real dump and restore
@pytest.fixture(scope="module")
def pg_tools(registry):  # type: ignore[no-untyped-def]
    problem = backup.tools_available()
    if problem:
        pytest.skip(f"pg_dump/pg_restore not usable here: {problem} (set ZIIRA_PG_DUMP_COMMAND, see docs/operations.md)")


@pytest.fixture(scope="module")
def shop(registry, pg_tools):  # type: ignore[no-untyped-def]
    """A business with stock and finance data, so the restore test has real ledgers to check."""
    from fastapi.testclient import TestClient

    from tests.stock_helpers import make_stock_shop
    from ziira.kernel.app import create_app

    client = TestClient(create_app())
    shop = make_stock_shop(client, registry, "Backup Shop")
    r = client.post("/api/v1/inventory/opening-stock", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "location_id": shop["main"],
        "lines": [{"product_id": shop["cement"], "quantity": "100", "unit_cost": "100"}]})
    assert r.status_code == 201, r.text
    return shop


def table_count(tenant_id, table: str) -> int:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_engine

    with tenant_engine(tenant_id, admin=True).begin() as conn:
        conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        return int(conn.execute(text(f"select count(*) from {table}")).scalar_one())


def test_backup_writes_a_dump_a_manifest_and_prunes(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    code = "backup-shop"
    results = backup.run_backup(tmp_path, tenant=code, include_master=False, now=NOW - timedelta(days=40))
    assert [r.ok for r in results] == [True], results[0].error
    # a second one 40 days later: the first falls out of the daily window (and is the oldest of its month, so it stays)
    results = backup.run_backup(tmp_path, tenant=code, include_master=False, now=NOW, keep_monthly=1)
    assert results[0].ok and len(results[0].pruned) == 1
    found = backup.list_backups(tmp_path, code)
    assert len(found) == 1
    m = found[0].manifest
    dump = found[0].dump_path
    assert dump.stat().st_size == m["size_bytes"] > 1000
    assert backup.sha256_of(dump) == m["sha256"]
    assert m["tenant_id"] == str(shop["tenant_id"]) and m["database"].endswith("backup_shop")
    assert m["row_counts"]["kernel.company"] == 1 and m["row_counts"]["kernel.branch"] == 2
    assert m["row_counts"]["inventory.location"] == table_count(shop["tenant_id"], "inventory.location") == 2
    assert "inventory" in m["units"] and m["latest_migration"]["inventory"].endswith(".up.sql")
    assert "password" not in json.dumps(m).lower() or "password_hash" in json.dumps(m)   # table names only
    assert not list((tmp_path / code).glob("*.partial"))


def test_master_database_backup(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    results = backup.run_backup(tmp_path, tenant=None, include_master=True, now=NOW)
    assert all(r.ok for r in results), [r.error for r in results]
    assert "master" in {r.target for r in results} and "backup-shop" in {r.target for r in results}
    manifest = backup.list_backups(tmp_path, "master")[-1].manifest
    assert manifest["row_counts"]["master.tenant"] >= 1 and manifest["kind"] == "master"


def test_restore_test_passes_on_a_good_backup_and_leaves_no_scratch_database(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    assert backup.run_backup(tmp_path, tenant="backup-shop", include_master=False)[0].ok
    result = backup.restore_test(tmp_path, "backup-shop")
    assert result.ok, result.problems
    from ziira.kernel.db import server_engine

    with server_engine().connect() as conn:
        left = conn.execute(text("select datname from pg_database where datname like 'ziira_restore_%'")).all()
    assert left == []


def test_restore_test_catches_a_damaged_dump(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    backup.run_backup(tmp_path, tenant="backup-shop", include_master=False)
    newest = backup.list_backups(tmp_path, "backup-shop")[-1]
    data = bytearray(newest.dump_path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    newest.dump_path.write_bytes(bytes(data))
    result = backup.restore_test(tmp_path, "backup-shop")
    assert not result.ok and "checksum" in result.problems[0]


def test_restore_test_catches_data_that_does_not_match_the_manifest(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    backup.run_backup(tmp_path, tenant="backup-shop", include_master=False)
    newest = backup.list_backups(tmp_path, "backup-shop")[-1]
    manifest = json.loads(newest.manifest_path.read_text())
    manifest["row_counts"]["kernel.branch"] += 5
    newest.manifest_path.write_text(json.dumps(manifest))
    result = backup.restore_test(tmp_path, "backup-shop")
    assert not result.ok and any("kernel.branch" in p for p in result.problems)


def test_restore_test_catches_a_broken_ledger(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    """A balance that disagrees with its movements (a bug, a manual edit) is in the backup; the restore test finds it."""
    from ziira.kernel.db import tenant_session

    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("update inventory.stock_balance set quantity = quantity + 7"))
    try:
        assert backup.run_backup(tmp_path, tenant="backup-shop", include_master=False)[0].ok
        result = backup.restore_test(tmp_path, "backup-shop")
        assert not result.ok and any("integrity check inventory" in p and "107" in p for p in result.problems)
    finally:
        with tenant_session(shop["tenant_id"], admin=True) as s:
            s.execute(text("update inventory.stock_balance set quantity = quantity - 7"))


def test_restore_never_overwrites_an_existing_database(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.errors import ValidationFailed
    from ziira.kernel.tenants import find_tenant

    backup.run_backup(tmp_path, tenant="backup-shop", include_master=False)
    newest = backup.list_backups(tmp_path, "backup-shop")[-1]
    with pytest.raises(ValidationFailed, match="already exists"):
        backup.restore_into_new_database(newest, find_tenant("backup-shop").db_name)
    with pytest.raises(ValidationFailed):
        backup.restore_into_new_database(newest, 'x"; drop database y; --')
    url = backup.restore_into_new_database(newest, "ziira_restored_copy")
    try:
        assert url.database == "ziira_restored_copy"
    finally:
        backup._drop_database("ziira_restored_copy")


def test_cli_backup_and_restore_test_exit_codes(tmp_path: Path, shop, capsys) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    assert cli.main(["backup", "--tenant", "backup-shop", "--dir", str(tmp_path)]) == 0
    assert cli.main(["restore-test", "--tenant", "backup-shop", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "ok" in out and "backup-shop" in out
    assert cli.main(["restore-test", "--tenant", "backup-shop", "--dir", str(tmp_path / "empty")]) == 1
    assert "no backup" in capsys.readouterr().out


def test_a_failing_tool_is_reported_without_the_password(tmp_path: Path, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "pg_dump_command", "sh -c 'echo connect failed password=hunter2 >&2; exit 3' --")
    results = backup.run_backup(tmp_path, tenant="backup-shop", include_master=False)
    assert not results[0].ok and "exit 3" in results[0].error and "hunter2" not in results[0].error
    assert not list((tmp_path / "backup-shop").glob("*"))              # nothing half-written is left


def test_a_restore_that_keeps_ownership_gives_the_tenants_own_login_its_access(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from ziira.kernel.db import master_session
    from ziira.kernel.security import decrypt

    assert backup.run_backup(tmp_path, tenant="backup-shop", include_master=False)[0].ok
    newest = backup.list_backups(tmp_path, "backup-shop")[-1]
    with master_session() as s:
        app_url = decrypt(s.execute(text("select app_url_encrypted from master.tenant where code = 'backup-shop'"))
                          .scalar_one())
    names = {}
    for flag in (False, True):
        names[flag] = f"ziira_restored_{'owned' if flag else 'plain'}"
        backup.restore_into_new_database(newest, names[flag], keep_ownership=flag)
    try:
        for flag, expect_access in ((True, True), (False, False)):
            engine = create_engine(make_url(app_url).set(database=names[flag]))
            try:
                with engine.begin() as conn:
                    conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(shop["tenant_id"])})
                    if expect_access:
                        assert conn.execute(text("select count(*) from kernel.company")).scalar_one() == 1
                    else:
                        with pytest.raises(Exception, match="permission denied"):
                            conn.execute(text("select count(*) from kernel.company"))
            finally:
                engine.dispose()
    finally:
        for name in names.values():
            backup._drop_database(name)

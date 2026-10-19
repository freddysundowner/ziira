"""Backups and the restore test (`ziira backup`, `ziira restore-test`, `ziira restore`).

A backup is one `pg_dump` (custom format) of the master database and of each tenant's database, written as
`<dir>/<target>/<target>-<UTC time>.dump` with a `.json` manifest beside it: database, size, sha256, when, the
units and migrations in it and a row count per table, all taken from the same snapshot as the dump
(`pg_export_snapshot` + `pg_dump --snapshot`), so the counts match the dump exactly even on a busy database.

The restore test restores the newest dump of a target into a scratch database, compares every table's row count with
the manifest, runs the integrity checks (stock ledger, ...) and a journal-balance check, and drops the scratch database.
`restore_into_new_database` never touches a live database: a restore always goes to a new name.

Retention (`keep_set`): the newest backup of each of the last `keep_daily` days, and the oldest of each of the last
`keep_monthly` calendar months. The newest backup is always kept.

Passwords are given to the tools through the PGPASSWORD environment variable only and never logged.
Point-in-time recovery needs WAL archiving, which is the operator's to set up: docs/operations.md.
"""

import contextlib
import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.pool import NullPool

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_engine, master_session, server_engine, tenant_engine
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.observability import redact

log = logging.getLogger("ziira.backup")
MANIFEST_VERSION = 1
CHUNK = 1024 * 1024


class BackupError(Exception):
    """A backup or restore step failed (the message has no passwords in it)."""


# --------------------------------------------------------------------------- retention (pure)
def keep_set(taken: list[datetime], now: datetime, *, keep_daily: int = 35, keep_monthly: int = 12) -> set[datetime]:
    """Which of these backup times to keep.

    - the newest backup of each UTC day, for the `keep_daily` days up to and including today;
    - the oldest backup of each calendar month, for the `keep_monthly` months up to and including this one;
    - the newest backup overall, whatever its age.
    """
    if not taken:
        return set()
    keep: set[datetime] = {max(taken)}
    first_day = (now - timedelta(days=keep_daily - 1)).date() if keep_daily > 0 else None
    newest_per_day: dict[Any, datetime] = {}
    oldest_per_month: dict[tuple[int, int], datetime] = {}
    for t in taken:
        if first_day is not None and first_day <= t.date() <= now.date():
            newest_per_day[t.date()] = max(t, newest_per_day.get(t.date(), t))
        month = (t.year, t.month)
        oldest_per_month[month] = min(t, oldest_per_month.get(month, t))
    keep.update(newest_per_day.values())
    this_month = now.year * 12 + now.month
    keep.update(t for (y, m), t in oldest_per_month.items() if 0 <= this_month - (y * 12 + m) < keep_monthly)
    return keep


# --------------------------------------------------------------------------- files
@dataclass
class BackupFile:
    """A backup on disk, as its manifest describes it."""

    manifest_path: Path
    manifest: dict[str, Any]

    @property
    def dump_path(self) -> Path:
        return self.manifest_path.with_name(self.manifest["file"])

    @property
    def taken_at(self) -> datetime:
        return datetime.fromisoformat(self.manifest["taken_at"])

    @property
    def files_path(self) -> Path | None:
        """The archive of the business's photos and files taken with this dump, if there is one."""
        name = (self.manifest.get("files") or {}).get("archive")
        return self.manifest_path.with_name(name) if name else None


def list_backups(directory: Path, target: str) -> list[BackupFile]:
    """The backups of one target (`master` or a tenant code), oldest first. Unreadable manifests are skipped."""
    found = []
    for path in sorted((directory / target).glob("*.json")):
        try:
            manifest = json.loads(path.read_text())
            datetime.fromisoformat(manifest["taken_at"])
            manifest["file"]
        except (OSError, ValueError, KeyError):
            log.warning("Skipping unreadable backup manifest %s", path.name)
            continue
        found.append(BackupFile(path, manifest))
    return sorted(found, key=lambda b: b.taken_at)


def prune(directory: Path, target: str, *, now: datetime | None = None, keep_daily: int = 35,
          keep_monthly: int = 12) -> list[Path]:
    """Delete the backups of `target` the retention rule no longer keeps. Returns the dump files removed."""
    backups = list_backups(directory, target)
    keep = keep_set([b.taken_at for b in backups], now or datetime.now(UTC), keep_daily=keep_daily,
                    keep_monthly=keep_monthly)
    removed = []
    for b in backups:
        if b.taken_at not in keep:
            for path in (b.dump_path, b.manifest_path, b.files_path):
                if path is not None:
                    path.unlink(missing_ok=True)
            removed.append(b.dump_path)
    return removed


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- running pg_dump / pg_restore
def _tool_command(configured: str, default: str) -> list[str]:
    return shlex.split(configured) if configured.strip() else [default]


def _connection_args(url: URL, database: str | None = None) -> tuple[list[str], dict[str, str]]:
    """libpq arguments (no password) and the environment that carries the password."""
    settings = get_settings()
    host = settings.pg_tool_host or url.host or "localhost"
    port = settings.pg_tool_port or url.port or 5432
    args = ["--host", host, "--port", str(port), "--username", str(url.username),
            "--dbname", database or str(url.database)]
    env = {**os.environ, "PGCONNECT_TIMEOUT": "15"}
    if url.password:
        env["PGPASSWORD"] = url.password
    return args, env


def _run_tool(command: list[str], env: dict[str, str], *, stdin: Path | None = None,
              stdout: Path | None = None) -> None:
    """Run a command, streaming a file in and/or out. Raises BackupError (stderr, redacted) on a non-zero exit."""
    with tempfile.TemporaryFile() as err:
        src = stdin.open("rb") if stdin else None
        dst = stdout.open("wb") if stdout else None
        try:
            try:
                proc = subprocess.run(command, env=env, stdin=src, stdout=dst or subprocess.DEVNULL, stderr=err,
                                      check=False)
            except FileNotFoundError as exc:
                raise BackupError(f"Cannot run '{command[0]}': not installed. Install the PostgreSQL client tools or "
                                  "set ZIIRA_PG_DUMP_COMMAND / ZIIRA_PG_RESTORE_COMMAND (docs/operations.md)") from exc
        finally:
            if src:
                src.close()
            if dst:
                dst.close()
        if proc.returncode != 0:
            err.seek(0)
            message = redact(err.read().decode("utf-8", "replace").strip())[-1500:]
            raise BackupError(f"{command[0] if command[0] != 'docker' else 'docker exec'} failed "
                              f"(exit {proc.returncode}): {message}")


def tools_available() -> str | None:
    """None if pg_dump and pg_restore run and are not older than the server, else why not."""
    settings = get_settings()
    try:
        with server_engine().connect() as conn:
            server_major = int(conn.execute(text("show server_version_num")).scalar_one()) // 10000
    except Exception as exc:  # noqa: BLE001
        return f"database server not reachable: {type(exc).__name__}"
    for configured, default in ((settings.pg_dump_command, "pg_dump"), (settings.pg_restore_command, "pg_restore")):
        cmd = _tool_command(configured, default)
        try:
            out = subprocess.run([*cmd, "--version"], capture_output=True, text=True, check=False, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return f"{default} is not available (set ZIIRA_PG_DUMP_COMMAND / ZIIRA_PG_RESTORE_COMMAND)"
        found = re.search(r"(\d+)(?:\.\d+)*", out.stdout)
        if out.returncode != 0 or not found:
            return f"{default} does not run: {redact(out.stderr.strip())[:200]}"
        if int(found.group(1)) < server_major:
            return f"{default} is version {found.group(1)}, older than the server ({server_major})"
    return None


# --------------------------------------------------------------------------- backup
@dataclass
class BackupResult:
    target: str
    ok: bool
    file: Path | None = None
    size: int = 0
    error: str = ""
    pruned: list[Path] = field(default_factory=list)


def _table_counts(conn: Connection) -> dict[str, int]:
    tables = conn.execute(text(
        "select schemaname, tablename from pg_tables where schemaname !~ '^pg_' "
        "and schemaname <> 'information_schema' order by 1, 2")).all()
    return {f"{t.schemaname}.{t.tablename}": int(conn.execute(text(
        f'select count(*) from "{t.schemaname}"."{t.tablename}"')).scalar_one()) for t in tables}


def _versions(conn: Connection, schema: str) -> dict[str, Any]:
    units = {}
    for name, version in conn.execute(text(f"select name, version from {schema}.unit order by name")):
        units[name] = version
    migrations: dict[str, str] = {}
    if schema == "kernel":
        for unit, last in conn.execute(text(
                "select unit_name, max(migration) from kernel.schema_migration group by unit_name order by 1")):
            migrations[unit] = last
    else:
        migrations["master"] = str(conn.execute(text("select max(migration) from master.schema_migration"))
                                   .scalar_one())
    return {"units": units, "latest_migration": migrations}


def _file_keys(conn: Connection) -> list[str]:
    """The stored bytes the rows of this snapshot name (photos and files of live records), if the business has any."""
    if conn.execute(text("select to_regclass('kernel.attachment')")).scalar_one() is None:
        return []
    keys: list[str] = []
    for row in conn.execute(text("select storage_key, web_key, thumb_key from kernel.attachment "
                                 "where status = 'active'")):
        keys += [k for k in (row.storage_key, row.web_key, row.thumb_key) if k]
    return keys


def backup_database(url: URL, *, directory: Path, target: str, kind: str, tenant_id: UUID | None, engine: Any,
                    now: datetime | None = None) -> Path:
    """Dump one database and write its manifest. Returns the dump file."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    folder = directory / target
    folder.mkdir(parents=True, exist_ok=True)
    dump = folder / f"{target}-{stamp}.dump"
    partial = dump.with_suffix(".dump.partial")
    schema = "kernel" if kind == "tenant" else "master"
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            # One snapshot for both the counts and pg_dump: they describe the same moment.
            if tenant_id is not None:
                conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
            snapshot = conn.execute(text("select pg_export_snapshot()")).scalar_one()
            counts = _table_counts(conn)
            versions = _versions(conn, schema)
            file_keys = _file_keys(conn) if kind == "tenant" else []
            server_version = str(conn.execute(text("show server_version")).scalar_one())
            args, env = _connection_args(url)
            _run_tool([*_tool_command(settings.pg_dump_command, "pg_dump"), "--format=custom", "--compress=6",
                       f"--snapshot={snapshot}", *args], env, stdout=partial)
            conn.rollback()
        partial.replace(dump)
    finally:
        partial.unlink(missing_ok=True)
    files_info: dict[str, Any] | None = None
    if kind == "tenant":
        from ziira.kernel.files.archive import write_archive
        from ziira.kernel.files.store import get_store

        if file_keys:
            files_info = write_archive(get_store(), file_keys, folder / f"{target}-{stamp}.files.tar")
        else:
            files_info = {"archive": None, "count": 0, "bytes": 0, "sha256": None, "missing": []}
    manifest = {
        "manifest_version": MANIFEST_VERSION, "kind": kind, "target": target, "files": files_info,
        "tenant_id": str(tenant_id) if tenant_id else None, "database": url.database, "file": dump.name,
        "size_bytes": dump.stat().st_size, "sha256": sha256_of(dump), "taken_at": now.isoformat(),
        "server_version": server_version, "units": versions["units"], "latest_migration": versions["latest_migration"],
        "row_counts": counts}
    dump.with_suffix(".json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return dump


def run_backup(directory: Path, *, tenant: str | None = None, include_master: bool = True, keep_daily: int = 35,
               keep_monthly: int = 12, now: datetime | None = None) -> list[BackupResult]:
    """Back up the master database and the tenants (one by workspace code, or all not closed), then prune each target
    that succeeded. One target failing never stops the others."""
    if tenant is not None and not tenant.strip():
        raise ValidationFailed("Give a workspace code")
    with master_session() as s:
        rows = s.execute(text(
            "select id, code, db_name from master.tenant where status in ('active', 'suspended') "
            "and (cast(:c as text) is null or code = cast(:c as text)) order by code"), {"c": tenant}).all()
    if tenant is not None and not rows:
        raise ValidationFailed(f"No backup-able tenant with workspace code '{tenant}'")
    jobs: list[tuple[str, str, UUID | None, Any]] = []
    if include_master:
        jobs.append(("master", "master", None, master_engine()))
    jobs += [(r.code, "tenant", r.id, tenant_engine(r.id, admin=True)) for r in rows]
    results = []
    for target, kind, tid, engine in jobs:
        try:
            dump = backup_database(engine.url, directory=directory, target=target, kind=kind, tenant_id=tid,
                                   engine=engine, now=now)
            pruned = prune(directory, target, now=now, keep_daily=keep_daily, keep_monthly=keep_monthly)
            results.append(BackupResult(target, True, dump, dump.stat().st_size, pruned=pruned))
        except Exception as exc:  # noqa: BLE001 - reported, and the other targets still run
            log.error("Backup of %s failed: %s", target, redact(str(exc)))
            with contextlib.suppress(OSError):
                (directory / target).rmdir()                    # an empty folder is all a failed first backup leaves
            results.append(BackupResult(target, False, error=redact(str(exc))))
    return results


# --------------------------------------------------------------------------- restore
def _scratch_name() -> str:
    return f"ziira_restore_{uuid.uuid4().hex[:10]}"


def restore_into_new_database(backup: BackupFile, database: str, *, keep_ownership: bool = False) -> URL:
    """Create `database` (which must not exist) on the tenant server and restore the dump into it. By default without
    owners or grants (so it works on a server without the original logins); with `keep_ownership` the original owners
    and grants to the tenant's own login are restored too (they must exist on the server), which a restored database
    needs before it can replace a live one. Returns the URL of the new database."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}", database):
        raise ValidationFailed("Database name: lowercase letters, digits and _, starting with a letter")
    settings = get_settings()
    if sha256_of(backup.dump_path) != backup.manifest["sha256"]:
        raise BackupError(f"{backup.dump_path.name} does not match its manifest checksum: the file is damaged")
    with server_engine().connect() as conn:
        if conn.execute(text("select 1 from pg_database where datname = :d"), {"d": database}).first():
            raise ValidationFailed(f"Database '{database}' already exists; a restore never overwrites a database")
        conn.exec_driver_sql(f'create database "{database}"')
    server_url = make_url(settings.tenant_server_url)
    try:
        args, env = _connection_args(server_url, database)
        ownership = [] if keep_ownership else ["--no-owner", "--no-acl"]
        _run_tool([*_tool_command(settings.pg_restore_command, "pg_restore"), *ownership,
                   "--exit-on-error", *args], env, stdin=backup.dump_path)
    except Exception:
        _drop_database(database)
        raise
    return server_url.set(database=database)


def restore_files(backup: BackupFile, into: Path) -> int:
    """Unpack the backup's photos and files into a folder that does not exist yet (never over existing files).
    Returns how many were unpacked."""
    from ziira.kernel.files.archive import extract

    archive = backup.files_path
    if archive is None:
        return 0
    if not archive.exists():
        raise BackupError(f"{archive.name} (the photos and files of this backup) is missing")
    if sha256_of(archive) != backup.manifest["files"]["sha256"]:
        raise BackupError(f"{archive.name} does not match its manifest checksum: the file is damaged")
    try:
        return extract(archive, into)
    except (FileExistsError, ValueError) as exc:
        raise ValidationFailed(str(exc)) from exc


def _drop_database(database: str) -> None:
    with server_engine().connect() as conn:
        conn.exec_driver_sql(f'drop database if exists "{database}" with (force)')


@dataclass
class RestoreTestResult:
    target: str
    ok: bool
    backup: str = ""
    problems: list[str] = field(default_factory=list)


def check_restored(url: URL, manifest: dict[str, Any], files_archive: Path | None = None) -> list[str]:
    """Problems found in a restored copy: row counts different from the manifest, an unbalanced journal, and every
    integrity check of the units in it (stock ledger, ...)."""
    problems: list[str] = []
    engine = create_engine(url, poolclass=NullPool)
    tenant_id = UUID(manifest["tenant_id"]) if manifest.get("tenant_id") else None
    try:
        with engine.connect() as conn:
            if tenant_id:
                conn.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": str(tenant_id)})
            actual = _table_counts(conn)
            expected: dict[str, int] = manifest["row_counts"]
            for table in sorted(set(expected) | set(actual)):
                if table not in actual:
                    problems.append(f"table {table} is missing after restore")
                elif table not in expected:
                    problems.append(f"table {table} was not in the backup manifest")
                elif actual[table] != expected[table]:
                    problems.append(f"table {table}: {actual[table]} rows restored, backup had {expected[table]}")
            if "finance.journal_line" in actual:
                unbalanced = conn.execute(text(
                    "select count(*) from (select entry_id from finance.journal_line group by entry_id "
                    "having sum(debit) <> sum(credit)) x")).scalar_one()
                if unbalanced:
                    problems.append(f"{unbalanced} journal entries do not balance")
        if tenant_id and not problems:
            problems += _integrity_problems(engine, tenant_id, files_archive, manifest.get("files") or {})
    finally:
        engine.dispose()
    return problems


def _integrity_problems(engine: Any, tenant_id: UUID, files_archive: Path | None = None,
                        files_info: dict[str, Any] | None = None) -> list[str]:
    from sqlalchemy.orm import Session

    from ziira.kernel.checks import run_integrity_checks_in
    from ziira.kernel.context import system_context
    from ziira.kernel.registry import discover, load_event_handlers

    load_event_handlers(discover())
    system_context(tenant_id)
    problems = []
    with Session(engine) as session:
        session.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        # Photos and files are checked against the backup's own archive, not the live folder (which has moved on).
        from ziira.kernel.files.archive import ArchiveStore

        session.info["files_store"] = ArchiveStore(files_archive)
        gone = (files_info or {}).get("missing", [])
        session.info["files_missing_ok"] = {k.rsplit("/", 1)[-1].split(".")[0] for k in gone}
        for result in run_integrity_checks_in(session):
            problems += [f"integrity check {result.unit}: {result.check}: {line}" for line in result.problems]
        session.rollback()
    return problems


def restore_test(directory: Path, target: str) -> RestoreTestResult:
    """Restore the newest backup of `target` into a scratch database, check it, and drop the scratch database."""
    backups = list_backups(directory, target)
    if not backups:
        return RestoreTestResult(target, False, problems=[f"no backup of '{target}' found in {directory}"])
    newest = backups[-1]
    result = RestoreTestResult(target, True, backup=newest.dump_path.name)
    scratch = _scratch_name()
    try:
        url = restore_into_new_database(newest, scratch)
        archive = newest.files_path
        if archive is not None:
            expected = (newest.manifest.get("files") or {}).get("sha256")
            if not archive.exists():
                raise BackupError(f"{archive.name} (the photos and files of this backup) is missing")
            if expected and sha256_of(archive) != expected:
                raise BackupError(f"{archive.name} does not match its manifest checksum: the file is damaged")
        result.problems = check_restored(url, newest.manifest, archive)
    except Exception as exc:  # noqa: BLE001 - any failure to restore is a failed test
        result.problems = [redact(str(exc))]
    finally:
        _drop_database(scratch)
    result.ok = not result.problems
    return result

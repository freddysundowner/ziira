"""Photos and files in backups: the archive beside the database dump, the restore test that checks restored rows against
it, restoring files into a new folder, and pruning."""

import io
import json
import os
import tarfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from tests import files_helpers as fx
from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import backup
from ziira.kernel.files import archive
from ziira.kernel.files.store import LocalFileStore, forget_store

ET = "products.product"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def files_folder(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    from ziira.kernel.config import get_settings

    folder = tmp_path_factory.mktemp("backup-files")
    before = os.environ.get("ZIIRA_FILES_DIR")
    os.environ["ZIIRA_FILES_DIR"] = str(folder)
    get_settings.cache_clear()
    forget_store()
    yield folder
    if before is None:
        os.environ.pop("ZIIRA_FILES_DIR", None)
    else:
        os.environ["ZIIRA_FILES_DIR"] = before
    get_settings.cache_clear()
    forget_store()


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    if backup.tools_available():
        pytest.skip("pg_dump/pg_restore not usable here (set ZIIRA_PG_DUMP_COMMAND, see docs/operations.md)")
    return make_stock_shop(client, registry, "Files Backup")


def add(shop, colour: int, entity=None):  # type: ignore[no-untyped-def]
    from ziira.sdk import files

    with system(shop) as s:
        return files.attach(s, entity_type=ET, entity_id=UUID(entity or shop["cement"]), data=fx.jpeg(colour=(colour, 1, 1)),
                            name=f"p{colour}.jpg")


def test_a_backup_carries_the_files_its_rows_name_and_a_restore_test_checks_them(tmp_path: Path, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    one, two = add(shop, 10), add(shop, 20)
    pdf_row = None
    from ziira.sdk import files

    with system(shop) as s:
        pdf_row = files.attach(s, entity_type=ET, entity_id=UUID(shop["paint"]), data=fx.pdf(), name="spec.pdf")
    result = backup.run_backup(tmp_path, tenant="files-backup", include_master=False, now=NOW)[0]
    assert result.ok, result.error
    found = backup.list_backups(tmp_path, "files-backup")[-1]
    info = found.manifest["files"]
    assert info["count"] == 3 + 3 + 1 and info["missing"] == [] and found.files_path and found.files_path.exists()
    assert backup.sha256_of(found.files_path) == info["sha256"]
    with tarfile.open(found.files_path) as tar:
        names = {m.name.rsplit("/", 1)[-1] for m in tar.getmembers()}
    assert {f"{one.id}.original", f"{two.id}.thumb", f"{pdf_row.id}.original"} <= names
    assert not list((tmp_path / "files-backup").glob("*.partial"))
    ok = backup.restore_test(tmp_path, "files-backup")
    assert ok.ok, ok.problems


def test_the_restore_test_checks_the_archive_not_the_folder_that_has_moved_on(tmp_path: Path, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import files

    kept = add(shop, 30)
    assert backup.run_backup(tmp_path, tenant="files-backup", include_master=False, now=NOW)[0].ok
    later = add(shop, 40)                                           # uploaded after the backup: not a problem
    with system(shop) as s:
        files.delete_file(s, kept.id, "removed after the backup")  # bytes gone from the live folder: still in the archive
    result = backup.restore_test(tmp_path, "files-backup")
    assert result.ok, result.problems
    with system(shop) as s:
        files.delete_file(s, later.id, "cleanup")


def test_a_damaged_or_missing_archive_fails_the_restore_test(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    add(shop, 50)
    assert backup.run_backup(tmp_path, tenant="files-backup", include_master=False, now=NOW)[0].ok
    newest = backup.list_backups(tmp_path, "files-backup")[-1]
    blob = bytearray(newest.files_path.read_bytes())               # type: ignore[union-attr]
    blob[len(blob) // 2] ^= 0xFF
    newest.files_path.write_bytes(bytes(blob))                      # type: ignore[union-attr]
    damaged = backup.restore_test(tmp_path, "files-backup")
    assert not damaged.ok and "checksum" in damaged.problems[0]
    newest.files_path.unlink()                                      # type: ignore[union-attr]
    missing = backup.restore_test(tmp_path, "files-backup")
    assert not missing.ok and "is missing" in missing.problems[0]


def test_a_file_missing_from_the_archive_is_reported_by_id(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    made = add(shop, 60)
    assert backup.run_backup(tmp_path, tenant="files-backup", include_master=False, now=NOW)[0].ok
    newest = backup.list_backups(tmp_path, "files-backup")[-1]
    path = newest.files_path
    assert path is not None
    kept = io.BytesIO()
    with tarfile.open(path) as old, tarfile.open(fileobj=kept, mode="w") as new:        # rebuild without that file's web copy
        for member in old.getmembers():
            if member.name.endswith(f"{made.id}.web"):
                continue
            new.addfile(member, old.extractfile(member))
    path.write_bytes(kept.getvalue())
    manifest = json.loads(newest.manifest_path.read_text())
    manifest["files"]["sha256"] = backup.sha256_of(path)
    newest.manifest_path.write_text(json.dumps(manifest))
    result = backup.restore_test(tmp_path, "files-backup")
    assert not result.ok and any(f"file {made.id}: the web copy is missing" in p for p in result.problems)


def test_files_are_restored_into_a_new_folder_and_never_over_existing_ones(tmp_path: Path, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.errors import ValidationFailed

    made = add(shop, 70)
    assert backup.run_backup(tmp_path, tenant="files-backup", include_master=False, now=NOW)[0].ok
    newest = backup.list_backups(tmp_path, "files-backup")[-1]
    target = tmp_path / "restored-files"
    count = backup.restore_files(newest, target)
    assert count == newest.manifest["files"]["count"] > 0
    live = LocalFileStore(files_folder)
    copy = LocalFileStore(target)
    key = f"{shop['tenant_id']}/{str(made.id)[:2]}/{made.id}.original"
    assert copy.get(key) == live.get(key) and oct((target / key).stat().st_mode & 0o777) == "0o600"
    with pytest.raises(ValidationFailed, match="not empty"):
        backup.restore_files(newest, target)


def test_the_cli_restore_unpacks_files_on_request(tmp_path: Path, shop, capsys) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    add(shop, 80)
    assert cli.main(["backup", "--tenant", "files-backup", "--dir", str(tmp_path)]) == 0
    assert cli.main(["restore", "--tenant", "files-backup", "--dir", str(tmp_path), "--into", "ziira_files_copy",
                     "--files-into", str(tmp_path / "unpacked")]) == 0
    try:
        out = capsys.readouterr().out
        assert "Unpacked" in out and any((tmp_path / "unpacked").rglob("*.original"))
    finally:
        backup._drop_database("ziira_files_copy")


def test_pruning_a_backup_removes_its_files_archive_too(tmp_path: Path, shop) -> None:  # type: ignore[no-untyped-def]
    add(shop, 90)
    old = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)
    assert backup.run_backup(tmp_path, tenant="files-backup", include_master=False, now=old)[0].ok
    assert backup.run_backup(tmp_path, tenant="files-backup", include_master=False, now=old.replace(hour=22))[0].ok
    assert backup.run_backup(tmp_path, tenant="files-backup", include_master=False, now=NOW)[0].ok
    folder = tmp_path / "files-backup"
    # the run itself pruned (two months on): August's oldest and the newest stay, the archive of the dropped dump goes
    assert sorted(p.name for p in folder.glob("*.files.tar")) == [
        "files-backup-20260810T030000Z.files.tar", "files-backup-20261014T120000Z.files.tar"]
    assert len(list(folder.glob("*.dump"))) == len(list(folder.glob("*.json"))) == 2


def test_an_archive_with_a_hostile_name_is_not_unpacked(tmp_path: Path) -> None:
    evil = tmp_path / "evil.tar"
    with tarfile.open(evil, "w") as tar:
        info = tarfile.TarInfo("../../outside.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="not trusted"):
        archive.extract(evil, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()

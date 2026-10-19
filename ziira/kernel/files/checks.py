"""`ziira verify` for files: rows against stored bytes, in both directions.

Reported: a file whose bytes are missing or the wrong size or checksum, a record that no longer exists, a deleted file
whose bytes are still stored, and stored bytes that no row mentions (an upload that never committed). With `--fix` the
leftovers (deleted files' bytes, bytes nobody mentions that are over an hour old) are removed; missing or damaged
originals can only be restored from a backup, so they are reported every time.
"""

import hashlib
import time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.checks import INTEGRITY_CHECK, IntegrityCheck
from ziira.kernel.extensions import provides
from ziira.kernel.files import service
from ziira.kernel.files.store import FileStore, get_store

ORPHAN_AGE_SECONDS = 3600


@provides(INTEGRITY_CHECK)
class FilesCheck(IntegrityCheck):
    name = "files"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        # A restore test hands in the backup's archive as the store and checks rows against it only; bytes in the
        # archive that no row mentions are normal there (they were uploaded after the database snapshot).
        store: FileStore = session.info.get("files_store") or get_store()
        restore_test = "files_store" in session.info
        gone_in_backup: set[str] = session.info.get("files_missing_ok", set())    # removed while the backup was running
        tenant_id: UUID = session.execute(text("select kernel.current_tenant()")).scalar_one()
        problems: list[str] = []
        wanted: set[str] = set()
        for row in session.execute(text(
                "select id, status, entity_type, entity_id, storage_key, web_key, thumb_key, size_bytes, checksum, "
                "web_bytes, thumb_bytes from kernel.attachment order by created_at")):
            keys = [k for k in (row.storage_key, row.web_key, row.thumb_key) if k]
            if row.status == "deleted":
                left = [k for k in keys if store.size(k) is not None]
                if left:
                    problems.append(f"file {row.id}: deleted, but {len(left)} stored copy(ies) remain")
                    if fix:
                        for k in left:
                            store.delete(k)
                continue
            wanted.update(keys)
            if str(row.id) in gone_in_backup:
                continue
            for label, key, size in (("original", row.storage_key, row.size_bytes), ("web copy", row.web_key,
                                                                                     row.web_bytes),
                                     ("thumbnail", row.thumb_key, row.thumb_bytes)):
                if key is None:
                    continue
                found = store.size(key)
                if found is None:
                    problems.append(f"file {row.id}: the {label} is missing from the store")
                elif found != size:
                    problems.append(f"file {row.id}: the {label} is {found} bytes, expected {size}")
            original = store.size(row.storage_key)
            if original == row.size_bytes and hashlib.sha256(store.get(row.storage_key)).hexdigest() != row.checksum:
                problems.append(f"file {row.id}: the original does not match its checksum (damaged)")
        problems += self._records_gone(session)
        now = time.time()
        for key in () if restore_test else store.keys(str(tenant_id)):
            if key not in wanted and key not in self._deleted_keys(session):
                age = now - (store.modified(key) or now)
                problems.append(f"stored file {key} has no row")
                if fix and age > ORPHAN_AGE_SECONDS:
                    store.delete(key)
        if fix and not restore_test:
            service.purge_deleted(session)
        return problems

    @staticmethod
    def _deleted_keys(session: Session) -> set[str]:
        cache: set[str] | None = session.info.get("files_deleted_keys")
        if cache is None:
            cache = set()
            for r in session.execute(text("select storage_key, web_key, thumb_key from kernel.attachment "
                                          "where status = 'deleted'")):
                cache.update(k for k in (r.storage_key, r.web_key, r.thumb_key) if k)
            session.info["files_deleted_keys"] = cache
        return cache

    @staticmethod
    def _records_gone(session: Session) -> list[str]:
        out: list[str] = []
        kinds = service.entities(session)
        for row in session.execute(text(
                "select entity_type, entity_id, count(*) as n from kernel.attachment where status = 'active' "
                "group by entity_type, entity_id")):
            kind = kinds.get(row.entity_type)
            if kind is not None and kind.scope(session, row.entity_id) is None:
                out.append(f"{row.n} file(s) belong to a {row.entity_type} ({row.entity_id}) that no longer exists")
        return out

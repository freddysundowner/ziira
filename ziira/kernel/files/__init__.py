"""Files and photos attached to records (docs/files.md).

Units use this through `ziira.sdk`:

    from ziira.sdk import files
    files.attach(session, entity_type="jobs.job", entity_id=job.id, data=body, name="front-left.jpg", category="damage")
    files.list_files(session, "jobs.job", job.id)

and offer a record type for attachments by implementing `kernel.attachable_entity` (`AttachableEntity`).
"""

from ziira.kernel.files import checks as _checks  # noqa: F401 - registers the integrity check
from ziira.kernel.files import privacy as _privacy  # noqa: F401 - registers the personal data provider
from ziira.kernel.files.service import (
    ATTACHABLE_ENTITY,
    AttachableEntity,
    Category,
    FileContent,
    FileInfo,
    Limits,
    PublicFile,
    SignedLink,
    access_log,
    attach,
    counts,
    delete_file,
    entities,
    entity,
    get_file,
    limits_for,
    list_files,
    local_id_from,
    public_links,
    purge_deleted,
    read,
    remove_for_entity,
    revoke_links,
    revoke_links_for_entity,
    signed_link,
    update_file,
    usage,
)

__all__ = [
    "ATTACHABLE_ENTITY", "AttachableEntity", "Category", "FileContent", "FileInfo", "Limits", "PublicFile",
    "SignedLink", "access_log", "attach", "counts", "delete_file", "entities", "entity", "get_file", "limits_for",
    "list_files", "local_id_from", "public_links", "purge_deleted", "read", "remove_for_entity", "revoke_links",
    "revoke_links_for_entity", "signed_link", "update_file", "usage",
]

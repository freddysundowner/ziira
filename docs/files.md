# Files and photos

Photos and PDFs attached to any record: the intake photos of a car, a receipt for a re-billed expense, a member's picture, an
engagement letter. One kernel service, used by every unit through `ziira.sdk`. It is **not** antivirus, it takes **no video**, and
it is not a document-management system: a file belongs to one record, in one business.

## What it does

* **Private storage.** The bytes live in a folder on the server (`ZIIRA_FILES_DIR`), never in a public path and never in the
  database. Rows (`kernel.attachment`, forced row-level security) say what each file is, who added it and what it belongs to. The
  storage sits behind `FileStore` (`ziira/kernel/files/store.py`), so object storage can replace the folder later.
* **Attach to any record** by `(entity_type, entity_id)`. A unit offers a record type by implementing `kernel.attachable_entity`.
* **Real type checking.** The type is read from the bytes. Accepted: JPEG, PNG, WebP pictures and PDF. A name or content type that
  says otherwise is ignored; anything else (a renamed program, a Word file, HEIC, an animated picture, a locked PDF) is refused
  with a plain message. Pictures are limited to 50 million pixels.
* **Location removed.** A picture is re-encoded without GPS, camera and time information (company setting
  `files_strip_location`, on by default). Every picture also gets a web-size copy (1600 px) and a thumbnail (320 px).
* **Limits as data** (company settings, Settings > Photos and files): largest file (`files_max_file_mb`, 10), files per record
  (`files_max_per_record`, 60), space per company (`files_storage_limit_mb`, 0 = none), and the plan's cap for the whole business
  (plan limit `storage_mb`, data in the plan, shown as `PlanLimitReached` / 402).
* **Visibility per file**: `staff` (default) or `shareable`. Everyone with permission on the record sees every file in the
  app; only `shareable` files can appear on public approval or insurer response pages.
* **Authorised downloads.** A signed-in person opens a file with their token, or with a signed address that ends in minutes
  (`/api/v1/files/dl/<token>`, for an `<img>`). Opening a full-size picture or document is logged (who, when, how) in
  `kernel.attachment_access`; people with `files.audit` read it (`GET /api/v1/files/{id}/access`).
* **Delete with a reason.** The row stays (who, when, why) without caption or name; the bytes go once the delete commits and every
  address made for the file stops working. A record that disappears must call `remove_for_entity`; otherwise `ziira verify`
  reports its files.
* **Photo consent note** for records where a business photographs customers (`photo_consent = True` on the record type).

## For a unit (`from ziira.sdk import files`)

Declare the record type in `hooks.py` (and `kernel.attachable_entity` under `[extends] implements` in the manifest):

```python
@provides(ATTACHABLE_ENTITY)
class JobFiles(AttachableEntity):
    entity_type = "jobs.job"            # "<unit>.<record>"
    label = "Job"
    view_permission = "jobs.view"       # who sees and opens the files
    edit_permission = "jobs.manage"     # who adds, changes and removes them
    photo_consent = False               # True: the screen shows a consent note field (salon before/after)
    def scope(self, session, entity_id):            # (company_id, branch_id), or None when there is no such record
        ...
    def categories(self, session):                  # the kinds of photo; read your own data (a pack may supply them)
        return [Category("intake", "Intake"), Category("damage", "Damage"), Category("progress", "Progress")]
```

Functions (all check the actor against the record's permissions, so a caller cannot forget; system code acts with all rights):

| Function | Does |
|---|---|
| `files.attach(session, entity_type=, entity_id=, data=bytes, name=, category=, caption=, visibility=, consent_note=, local_id=)` | store a file, returns `FileInfo`. A `local_id` (client-made UUID) makes a retry return the first result |
| `files.list_files(session, entity_type, entity_id, category=None, shareable_only=False)` | `FileInfo` list, oldest first |
| `files.counts(session, entity_type, [ids])` | `{entity_id: number}` for a badge in a list |
| `files.get_file(session, file_id)` / `files.update_file(session, file_id, caption=, category=, visibility=, consent_note=)` | details / change |
| `files.read(session, file_id, variant="web")` | `FileContent(data, content_type, name)`; `variant`: `original`, `web`, `thumb`; logged |
| `files.delete_file(session, file_id, reason)` / `files.remove_for_entity(session, entity_type, entity_id, reason)` | remove one / all files of a record |
| `files.signed_link(session, file_id, variant, seconds=300)` | short-lived address for a signed-in browser |
| `files.public_links(session, entity_type, entity_id, label=, seconds=1800, category=None)` | **for public pages** (below) |
| `files.revoke_links(session, file_id)` / `files.revoke_links_for_entity(session, entity_type, entity_id)` | end every address made so far |
| `files.access_log(session, file_id)`, `files.usage(session, company_id=None)`, `files.limits_for(session, company_id)` | who opened it; space used; the limits |

`FileInfo` fields: `id, entity_type, entity_id, company_id, branch_id, category, caption, visibility, consent_note, kind
("image"/"pdf"), content_type, name, size_bytes, checksum, width, height, page_count, has_web, has_thumb, location_stripped,
created_at, created_by, created_by_name`.

### Showing shareable files on a public page (approval link, insurer response page)

Your public router authenticates the visitor with **your own** link, runs in `system_session`, then calls:

```python
shown = files.public_links(session, "claims.estimate", estimate_id, label=f"insurer response {claim_number}", seconds=1800)
# -> [PublicFile(id, category, caption, kind, content_type, name, size_bytes, width, height, thumb, web, original), ...]
# each of thumb / web / original is a SignedLink(path="/api/v1/files/dl/<token>", expires_at) or None
```

Only `shareable` files come back. The addresses work without an account until they end (30 minutes by default, 24 hours at most);
every opening of a full-size file is logged with your `label`, the purpose `public` and the visitor's address. When your link is
revoked or closed, call `files.revoke_links_for_entity(...)`: every address made so far stops at once. Making a file staff-only or
deleting it does the same for that file. The visitor's browser should be given the `path` prefixed with the API address
(`ziira.sdk.settings_public_base_url()`).

## HTTP (`/api/v1/files`)

`GET /config?entity_type=&entity_id=` (kinds of photo, limits, may the actor edit) | `GET ?entity_type=&entity_id=` list
| `POST ?entity_type=&entity_id=&category=&visibility=` upload: **the body is the file**; name, caption and consent note go in the
headers `X-File-Name`, `X-File-Caption`, `X-File-Consent` (percent-encoded UTF-8, so they never appear in a URL); `Idempotency-Key`
makes a retry safe | `GET /{id}` | `PATCH /{id}` | `POST /{id}/delete {reason}` | `GET /{id}/content?variant=` |
`POST /{id}/link` | `POST /{id}/revoke-links` | `GET /{id}/access` | `GET /usage` | `GET /dl/{token}` (no sign-in: the signed address).

Permission `files.audit` (Owner by default) reads the access list. Whoever holds `privacy.manage` may also open a file a data
subject request found.

## Web

`Attachments` (from `@/sdk`): `<Attachments entityType="jobs.job" entityId={job.id} />`. Take a photo from a phone camera or choose
files, categorised grid with captions and a staff-only/shareable toggle, a viewer, delete with a reason, upload progress, and a
retry for an upload that failed (for example with no signal). English and Swahili. A unit adds it to its own screens.

## Privacy

Provider `kernel.files` plugs into `kernel.personal_data`: **find** (captions, names and consent notes that contain the person's
email, phone or id, plus every file on a record another unit found for them), **export** (details and where to download the
file), **anonymise** (a photo cannot be made anonymous, so the file is removed and the removal is kept). Retention: company
setting `retention_files_years` (0 = off) puts files older than that into the exceptions inbox for review (nothing is deleted by
itself); `retention_file_access_days` (365) limits how long the access list is kept.

## Operations

* Set `ZIIRA_FILES_DIR` to a folder only the application user can read, on a disk with room; `scripts/check_env.py` checks it.
  Development uses `var/files`. Disk use is shown in Settings > Photos and files and is capped by the plan.
* **Back it up with the databases.** `ziira backup --dir PATH` also archives each business's files; `ziira restore-test` checks the
  restored rows against that archive. See `docs/operations.md`.
* `ziira verify` checks rows against bytes both ways (missing, wrong size, damaged, deleted-but-still-stored, bytes with no row,
  files of a record that no longer exists); `--fix` removes leftovers.

## Not done

No antivirus, video, HEIC, Word/Excel files, in-browser image editing, face blurring or object storage driver (the interface is
ready). Files are not shown in list columns.

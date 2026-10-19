# Wave 2, agent E: files and photos (kernel service)

Status: built and tested; see docs/files.md for the contract other units use.

## Done
- Kernel service `ziira/kernel/files/` (media checks, `FileStore` + folder store, signed links, service, privacy provider, integrity
  check, backup archive), migration `0017_files` (tables `kernel.attachment`, `kernel.attachment_access`: the old unused
  `kernel.file` from 0001 was left alone), API `ziira/kernel/api/file_routes.py` (`/api/v1/files`), sdk surface `from ziira.sdk import files`
  plus `AttachableEntity`, `ATTACHABLE_ENTITY`, `Category`, `FileInfo`.
- Extension point `kernel.attachable_entity`; Products offers `products.product` (picture + document) and its page shows `<Attachments>`.
- Company settings (Settings > Policies > Photos and files): `files_strip_location`, `files_max_file_mb`, `files_max_per_record`,
  `files_storage_limit_mb`, `retention_files_years`, `retention_file_access_days`; plan cap through plan limit `storage_mb`.
- Web `Attachments` (frontend/src/sdk/attachments), English and Swahili.
- `ZIIRA_FILES_DIR` / `ZIIRA_FILES_MAX_UPLOAD_BYTES`: settings, `scripts/check_env.py`, installer (env, folder, nginx 27 MB location for
  `POST /api/v1/files`, goldens updated), operations docs.
- `ziira backup` archives files beside each dump; `restore-test` checks rows against the archive; `ziira restore --files-into`.
- Tests: tests/test_files_domain.py, test_files_api.py, test_files_backup.py, frontend sdk/attachments, deploy and check_env tests.

## Cut / not done
No antivirus, video, HEIC, Word/Excel, image editing, object-storage driver, file columns in lists, stored/revocable share-link table (links
are stateless signed addresses revoked by a per-file generation counter). Fuzzer not run (Speed rule).

## Doubts
- A file removed during the seconds between a dump and its archive is listed in the manifest (`missing`), not an error.
- Public addresses can live up to 24 h; callers choose (default 30 min) and call `revoke_links_for_entity` when their own link closes.
- `kernel.file` (0001) is an unused legacy table; dropping it is the lead's call.

## Resume
`set -a; . ./.env; set +a; .venv/bin/pytest tests/test_files_domain.py tests/test_files_api.py tests/test_files_backup.py -q`;
`cd frontend && npx vitest run src/sdk/attachments`; `make api-types` last.

# Connectors (standalone mode)

Ziira Intelligence on the system a business already has. Connectors (`public.py`) read ERPs, file exports and bank or
mobile-money statements into a canonical model, stored read-only in `connect.src_*`; `standalone_checks.py` checks it; `pulse.py`
feeds the Command Center; `services/sync.py` is the sync engine; `services/uploads.py` the file path; `privacy.py` the
personal-data provider. API connectors: `connectors/{erpnext,odoo,zoho_books,quickbooks}.py` (`docs/connectors.md`); file
kinds: `connectors/csv_exports.py`, `connectors/statements.py`. See `docs/standalone-mode.md`.

File reading is layered: `domain/tabular.py` (CSV, Excel, text PDF via `domain/pdfreader.py`, grid of text) ->
`domain/words.py` (rows from positioned words, shared with OCR) -> `domain/layout.py` (header, columns, formats, wrapped
lines) -> `services/uploads.py` (preview, confidence, commit). Pictures: `ocr/` (Pillow tidying, Tesseract engine behind
`connect.ocr_engine`) and `services/scans.py` (the background job and the lines waiting for confirmation).

Moving to Core: `services/move.py` proposes Core records from `connect.src_*`, has the owning units' importers check them (through
`imports.public`) and stages Data Import batches tagged with the connection; `domain/move.py` holds the pure rules,
`repository/move_repo.py` the SQL, `api/move_routes.py` the endpoints and the `connect.move_advance` job (`jobs.py`) stages the second
group. `services/overlap.py` decides which areas Core now covers (units plug in `connect.core_coverage`; see `public.py`) so standalone
checks stay silent there. See `docs/standalone-mode.md`, "Moving to Core".

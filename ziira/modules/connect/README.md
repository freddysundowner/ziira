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

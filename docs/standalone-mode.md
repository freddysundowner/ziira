# Standalone mode: Ziira Intelligence on the system a business already has

Some businesses will not move their books and tills to Ziira, but still want Ziira Intelligence to check the business every day
and tell the owner what needs attention. **Standalone mode** is that: Ziira reads the system the business keeps (an ERP, a
POS export, a bank or mobile-money statement), copies what it reads into a read-only store of its own, and runs the same kind of
checks it runs for Core businesses. It is the "Standalone" mode of `docs/specs/Ziira_Intelligence_1.0.txt`.

Who it is for: an owner who runs on Odoo, ERPNext, Zoho Books, QuickBooks Online, a till that exports a spreadsheet, or nothing but
a bank account and a mobile-money till, and wants alerts, a daily brief and a Command Center without changing how the business
works. A business can also use Core units and connect other systems; see "Core units and standalone checks" below.

```
other system ──▶ connector ──▶ canonical model ──▶ connect.src_*  (read-only copy)
 (ERP, file, statement)  (reads, never writes)                         │
                                                  standalone checks ◀──┘──▶ findings, alerts, briefs, pulse figures
```

## The read-only guarantee

- Every connector only reads. API connectors send reads only (`docs/connectors.md` lists them); file connectors never
  talk to anything. Nothing in `ziira/modules/connect` writes to a source system.
- Access is a key or an approval the business can withdraw at any time. Secrets are stored encrypted in the kernel credential
  store (`kernel.integration_credential`), are never returned by any API, never put in the audit log, and are overwritten with a
  marker when a connection is disconnected.
- A file you upload is read, its rows are stored, and the file itself is not kept.

## Setting up

**Registering**: the registration form asks "I want to run my business on Ziira" (`mode: core`, the default) or "I already have a
system and want Ziira to watch it" (`mode: standalone`). A standalone business gets only the units in `ZIIRA_STANDALONE_UNITS`
(default `connect,intel,command,imports`; what they require comes along). The web app then shows Home, Command Center, Findings,
Connected systems and Settings only, and Home starts with "Connect your first system". Operators:
`ziira create-tenant ... --mode standalone`.

**Connecting** (web: Connected systems > Add connection):

1. Choose the system, grouped as **Your ERP** and **Statements and exports**. Each kind shows plain steps for what access to create
   or which file to export (`how_to`).
2. Give the details. Secret fields are write-only. Tick "create a Ziira branch for each of its branches" if the business wants
   branches made automatically.
3. Test the connection (API kinds) or authorise with the vendor (Zoho Books, QuickBooks: a browser approval; see
   `docs/connectors.md`).
4. First read (API kinds: queued for the worker, with progress) or drop a file (file kinds: Ziira works out the layout, says
   what it found in a sentence, and the person answers "Looks right" or "Something is wrong"; see "Files" below). On the first
   screen of the wizard a person can simply drop the file and Ziira names its kind.
5. Map its branches to Ziira branches, or ignore some. Unmapped branches are checked at company level.

Command line: `ziira connect sync <tenant> [--connection NAME]` and
`ziira connect upload <tenant> <connection> FILE [--check]` (CSV, Excel or text PDF; `--check` stores nothing) and
`ziira connect ocr-check` (can this server read pictures?).

## What each source gives, and how fresh

| Source | Gives | Freshness | Needs |
|---|---|---|---|
| ERPNext, Odoo, Zoho Books, QuickBooks Online | sales, invoices, payments, stock, expenses, journals, parties, users (see `docs/connectors.md`) | read every `sync_every_minutes` (default 1,440; "live" kinds 15) by `ziira worker` | a read-only key, or a browser approval |
| Sales export (`csv_sales`) | sales: receipt, date, total, cashier, branch, payment method and code; or one row per item | when you upload | an Excel or CSV export from the till or POS |
| Invoices and bills (`csv_invoices`) | customer invoices / supplier bills and the parties | when you upload | an Excel or CSV export |
| Stock movements (`csv_stock`) | movements with kind, branch, user, cost | when you upload | an Excel or CSV export |
| Expenses (`csv_expenses`) | expenses with category | when you upload | an Excel or CSV export |
| Bank statement (`bank_statement`), mobile-money statement (`mobile_money_statement`) | payments: money in and out with its code, time, payer or payee, account | when you upload | the statement as PDF, Excel or CSV, or a photo of it |

### Files: drop it, Ziira works out the rest

A person drops a PDF, an Excel (.xlsx) file, a CSV file or a photo (PNG/JPG) on a file connection (or on the first wizard
screen, which also detects the kind: `POST /api/v1/connect/files/detect`). What the file *is* is decided from its first bytes,
never its name. Nothing is asked up front:

1. **Reading**: CSV (byte-order mark, UTF-16/Windows-1252, any delimiter, quoted line breaks), Excel (the sheet with most rows;
   real dates and numbers; formulas as last saved), text PDF (ruled tables first; else words placed under the header line by
   their position; else, with no column names at all, lines read by shape: date, code, details, amounts). Multi-page PDFs reuse
   the header of the page before; repeated headers, page footers, titles, "opening/closing balance" and total lines are
   recognised and skipped; description lines that wrap are joined to the line above. Amounts with thousands separators,
   brackets, trailing minus, DR/CR; "Paid in"/"Withdrawn" pairs; running balances.
2. **Layout** (`domain/layout.py`): the header row is the line with the most known column names (alias tables in the
   connectors' `FileField`s, data, not code); columns the names did not place are found by what they contain (dates, amounts,
   codes, text, a balance column that reconciles with the amounts decides which numeric column is which). Date order (`dd/mm`
   or `mm/dd`) is read from the numbers; a file where both fit (03/04/2026 only) is reported as ambiguous and the person is
   asked once. Decimal separator is voted from the amounts. No country appears in code.
3. **Summary**: "We found 214 transactions from 3 Jan to 28 Feb 2026", money in/out (or totals), a small sample in plain words,
   a confidence score and the reasons for any doubt (`check_reasons`: `missing`, `unsure`, `problems`, `dates`, `picture`,
   `wrong_kind`). The person confirms with "Looks right", or "Something is wrong" opens a guided fix: one dropdown per thing
   we need, pre-filled with the guess and showing the cells, plus how dates and amounts are written. The first confirmed upload
   saves the layout on the connection (`config.file`), so the next file is one drop. The word "mapping" never appears on this path.
4. **Wrong kind**: a sales file dropped on a statement connection (or the reverse) says so and names the kind it looks like.
5. **Problems**: lines that cannot be used are left out and listed in plain words with what they said; the list can be downloaded.
   Re-uploading overlapping statements adds nothing twice, also across formats (the same statement as CSV, then PDF, then Excel):
   a line's reference is made from the account, the transaction code, the amount, the direction and the time.

**Protected PDFs** (mobile-money statements often are): the upload form asks for the password and sends it in the
`X-File-Password` header, used once to open the file. It is never stored, logged or audited (the audit entry names the file and
counts only). A scanned PDF that is also protected is refused (remove the password first).

**Pictures** (photos, and PDFs whose pages are images) are read by OCR behind the `connect.ocr_engine` extension point
(`OcrEngine.read(png) -> positioned words`). The default engine is a self-hosted Tesseract (nothing leaves the server; set up
in `docs/operations.md`). Without it the person is told "Reading pictures is not switched on on this server yet" and nothing
crashes. Reading is a background job (`connect.read_scan`, progress by page, at most `ZIIRA_OCR_MAX_PAGES` pages): the upload
stores the file in `connect.scan`, the page polls `GET .../scans/{id}`, the file is cleared once read, and the lines read wait
there until confirmed (deleted after a day). Page images are tidied (grey, contrast, enlarged, straightened) and the words are
rebuilt into rows by the same code as text PDFs. Because digits are misread, a picture is **never stored without the person
confirming**, lines whose running balance does not follow from the line before are rejected and shown for correction
(`PATCH .../scans/{id}` fixes cells, then the preview is rerun), and lines with a doubtful word and no balance to vouch for them
are flagged too.

Limits: 10 MB per file (the request-size cap is raised to this for uploads: `ZIIRA_MAX_UPLOAD_BYTES`), 50,000 rows, 300 PDF
pages (text) or `ZIIRA_OCR_MAX_PAGES` (pictures). The old `.xls` format is refused with advice to save as `.xlsx`.
Per-connection file settings (`PUT .../file-settings`: columns, decimal separator, date format, options such as the words that
mark a cash deposit) can still be set, with `"auto"` meaning "work it out from each file".

A read never waits inside a request: "Read now" queues a background job. A failed read keeps what it already stored, resumes from
the last complete cursor, retries with growing delays (5 minutes up to 6 hours), and shows in the exceptions inbox. A refused key
stops the connection (status "Needs attention") until fixed.

## The canonical model and the store

`ziira/modules/connect/public.py` defines the model every connector produces (Branch, Party, Product, User, Sale with lines
and payments, Payment, StockMovement, Invoice, Expense, JournalEntry with lines). It is stored in typed tables `connect.src_*`, with
`tenant_id` and forced row-level security, `connection_id`, `ref` (unique per connection), `company_id`, the mapped `branch_id`,
`first_seen_at` and `last_seen_at`. Also: `connect.connection`, `connect.sync_run` (history), `connect.cursor` (where the last complete read
ended, and up to when the data is complete), `connect.branch_map`.

**Complete days only.** A cursor row exists once an entity was read to the end. Checks judge a day only when the data of the
entity is complete for it (`data_through`), so a connection that has not been read lately, or a statement that ends early, never
makes a quiet day look like a bad one.

## What the checks do on what data

The checks are `standalone.<name>` (`ziira/modules/connect/standalone_checks.py`). One set serves every source, because they read
only `connect.src_*`. A check whose entity was never connected stays silent, and the **Coverage** panel (Connected systems page and
Command Center) shows, by area, what can and cannot be checked today and which connection would switch more on.

| Area | Check | Needs |
|---|---|---|
| Cash and sales | `sale_without_payment`: mobile-money or bank sales with no matching statement line (code, or amount within a time window) | sales + payments |
| | `cash_deposit_gap`: cash sales over the last days well above cash deposits (per branch if the deposits say which) | sales + payments |
| | `branch_sales_low`: a branch far below its weekday normal | sales |
| Controls | `cashier_void_rate`, `cashier_refund_rate`, `cashier_discount_rate`: unusual against the cashier's own baseline | sales |
| | `large_exception`: one big void, refund or discount | sales |
| | `out_of_hours_sales` (company time zone), `late_entered_sales` (entered days after their date) | sales (late: a source that records the entry time) |
| Customers | `customer_overdue`, `credit_to_overdue_customer` | invoices |
| | `customer_paying_slower` | invoices + payments that name the invoice |
| Suppliers | `supplier_price_rise` (latest purchase cost vs earlier) | stock movements |
| | `duplicate_supplier_invoice`, `duplicate_payment` | invoices / payments |
| Stock | `stock_adjustment` (large, odd hours or back-dated), `shrinkage_by_product`, `negative_stock` | stock movements |
| Books | `manual_journal` (large, round, odd hours, back-dated, created and approved by the same person) | journal entries |
| | `expense_unusually_high` (vs its category's normal) | expenses |
| | `unmatched_receipt` (money received that matches no sale or invoice; cash deposits are left out) | payments + sales or invoices |
| People | `new_user` | users |

Every check follows `docs/intelligence.md` ("Writing a check"): limits are `params` a business can change, findings carry the mapped branch
(`branch_id`, so branch managers see their own), evidence records of type `connect.src_*`, plain-language summaries in the company
currency, and *state* checks close their findings when the problem clears. Baselines (`standalone.cashier_*_rate`,
`standalone.branch_daily_sales`, `standalone.expense_by_category`) are learned like any other. Pulse figures for the Command Center
(`connect.sales_total`, `sales_count`, `payments_received`, `overdue_receivables`, `expenses_total`, `stock_adjustments`) are
supplied per day, and per mapped branch for sales, expenses and adjustments.

Limits of the checks, honestly: `negative_stock` is only as good as the movement history connected (it needs the opening stock or
history from the start); a role or pay-type *change* is not seen (only a new user is); `sale_without_payment` matches a statement
line to any sale of the same code or amount and time, not one-to-one; matching depends on how well the source records payment
codes; "complete up to" for a file is the time of its last record.

### Core units and standalone checks

Standalone checks look only at `connect.src_*`, never at a Core unit's tables, and Core units' checks never look at `connect.src_*`.
A business that runs some Core units and also connects another system (for example a Core POS plus a bank statement) gets each
set about its own data and nothing is counted twice; they are separate findings with different codes.

## By source type

- **Cash, sales, basic stock** from a POS export or statements: levels 1-2 of the Intelligence spec (report, and ask a person to
  explain). Daily at best, because it needs an export. Control checks are limited to what the export carries (a till export
  without voids or discounts cannot show cashier habits).
- **More from an ERP**: invoices and credit, suppliers, journals and expenses, daily or more often.

## Privacy and consent

The business is the controller. It chooses what to connect and can pause, disconnect, or disconnect and **delete everything read**
(`POST /connections/{id}/disconnect` with `delete_data`). Customers, suppliers and users read from other systems are findable,
exportable and anonymisable through the privacy tooling (`docs/privacy.md`; provider `connect`); an anonymised record stays
anonymised when the source is read again, but the source system still holds the person's details, so the business must correct it there
too. Personal data is read only to name people in findings; checks use the source's own references.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `ZIIRA_STANDALONE_UNITS` | `connect,intel,command,imports` | units for a business that registers (or is created) in standalone mode |
| per connection `sync_every_minutes` | 1,440 (live kinds 15) | the freshness window; at least 15 |
| per connection `auto_create_branches` | off | create a Ziira branch for each branch of the other system |

## Adding a connector

Subclass `Connector` (`public.py`): `kind`, `title`, `description`, `how_to`, `entities`, `config_fields`, `freshness`; `check` and
`pull` (yield `CanonicalBatch`es, `cursor` and `complete`; raise `ConnectorError(retryable=...)`; reads only). Register with
`@provides(CONNECTOR)` (`connectors/registry.py` for API connectors, `connectors/file_kinds.py` for files) and list
`connect.connector` under `[extends] implements`. A vendor that rotates secrets sets `updated_secrets`; the engine saves them even
when the read fails. `notes` appear in the sync history. For a file kind subclass `FileConnector` (`connectors/files.py`): list the
`fields` with their usual column names and write `records(rows, reader, account)`; reading the file (CSV, Excel, PDF, pictures), finding the
header and columns, preview, validation report and idempotent storing are done for you. Set `family`, `needs_any`, `skip_phrases`
and `lenient` when the kind has titles, totals or wrapped lines around its table. Test with a fake in-memory connector as `tests/test_connect_sync.py` does.

## What is not verified

The API connectors are untested against the real services (`docs/connectors.md`). The statement layouts are written from common
shapes of public statements and tested on constructed files (PDF in eight layouts, Excel, CSV: `tests/connect_file_fixtures.py`);
try a real statement from each provider before relying on it. The OCR path is tested with a stand-in engine for the plumbing and
balance checks; the real Tesseract test (`tests/test_connect_files_layout.py`) runs only where the program is installed, and no
accuracy figure on real photos exists yet.

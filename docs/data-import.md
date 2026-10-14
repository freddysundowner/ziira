# Moving a business onto Ziira: data import

A business arrives with products, customers, suppliers, staff and opening stock in spreadsheets or exports of an older
system. The **Data Import** unit (`ziira/modules/imports`, permission `imports.manage`, Owner only by default) reads a
CSV file, checks every row without writing, imports the valid rows in the background and shows a reconciliation
report. Nothing is written to a unit's tables directly: each row is created by the **owning unit's own service**
(`create_product`, `create_customer`, `post_opening_stock`, ...), so every rule, permission, audit entry, number series
and event applies exactly as if the record had been typed in.

## Workflow

1. **Upload** (`POST /api/v1/imports/batches?kind=...&company_id=...`, the file as the request body). Choose how the
   file writes decimals (`.` or `,`) and dates (`iso` = `2026-01-31`, `dmy`, `mdy`). The reply lists the columns of the
   file and the mapping we suggest.
2. **Map columns** (`PUT .../batches/{id}/mapping`). Suggested by header similarity (the importer lists aliases such as
   "Item Code" for `sku`); the user adjusts. Required fields must have a column.
3. **Check** (`POST .../validate`): a dry run of every row. Per row: `valid`, `invalid` (with plain messages), or
   `skipped` (the record already exists in Ziira). Duplicates inside the file are rejected from their second
   appearance (the message names the first row). Nothing is written.
4. **Commit** (`POST .../commit`, answers 202): a background job (`imports.commit`, run by `ziira worker`) imports the
   valid rows, 200 per job run, **each in its own savepoint**; a failed row is marked `failed` with its message and
   never blocks the others. Asking to commit twice, or a job delivered twice, changes nothing: a handled row is never
   handled again. Records that appeared between the check and the commit are skipped.
5. **Report** (`GET .../report`): rows in file / imported / skipped / rejected / failed, and for each money or quantity
   column the sum in the whole file, the sum of the rows that were imported, and the same figure read back from the
   records that were created. A difference between the last two is listed in plain words.
6. **Fix and re-upload only what was rejected**: `GET .../rejected.csv` returns the invalid and failed rows with your
   original columns plus an `error` column. Fix them, upload the file again (the `error` column is ignored; a leading
   apostrophe that spreadsheet-safe downloads put before `+`, `-`, `=`, `@` is removed).

Other endpoints: `GET /imports/kinds` (what can be imported, with columns), `GET /imports/kinds/{kind}/template` (a
sample CSV), `GET /imports/batches` and `/batches/{id}` (progress: `counts` by row state), `GET /batches/{id}/rows`
(`status=`, `only_errors=true`, paged), `DELETE /batches/{id}` (discards the staged file of an import that created
nothing).

The web app has the same four steps under **Admin > Import data** (`/imports`): file, columns, check (filter "only
problems", per-row messages), import (live progress, then the reconciliation with the rejected-rows download).

### Command line (assisted onboarding)

```bash
.venv/bin/ziira import demo-hardware products products.csv                 # check only (the default); exit 1 if rows have problems
.venv/bin/ziira import demo-hardware products products.csv --commit --rejected rejected.csv
.venv/bin/ziira import demo-hardware opening_stock stock.csv --decimal , --date-format dmy --company "Demo Hardware Ltd" --commit
.venv/bin/ziira import demo-hardware customers c.csv --map name="Customer name" --map phone=Mobile
```

`--company` takes the company's name or id (companies have no code); it can be left out when the business has one.
`--commit` runs the import in the foreground and prints the reconciliation.

## File format

- CSV, UTF-8 with or without a byte-order mark. UTF-16 (with BOM) is read; other text is read as Windows-1252 with a
  warning. Excel workbooks (`.xlsx`) are refused with a message to save as CSV (not supported yet).
- Delimiter detected: comma, semicolon, tab or bar. Quoted cells with commas or line breaks, spaces around values and
  blank lines are fine. Rows longer than the header lose the extra cells (with a warning).
- Limits: 5 MB, 5,000 rows, 100 columns, 2,000 characters in a cell. Split bigger files.
- The first row is the header. Row numbers in messages are the spreadsheet row numbers (the header is row 1).
- Numbers: with `.` decimals `1250.50` or `1,250.50`; with `,` decimals `1250,50` or `1.250,50`; spaces and `'` as
  thousands separators are fine; `(12.00)` is minus 12. A value that could be read two ways (`1.5` in a file whose
  decimals are commas) is **refused**, never guessed. Yes/no: `yes y true 1 x` / `no n false 0`.

## Kinds and columns

Required columns are marked *. Download the sample file of a kind from the API for a ready header.

| Kind (unit) | Needs permission | Columns |
|---|---|---|
| `products` (Products) | `products.manage` (`prices.manage` for prices) | sku*, name*, unit* (unit code that exists), tax_code* (tax code that exists), type (`stock`/`non_stock`/`service`), batch_tracked, reorder_level, price (tax-inclusive; goes into the company's default price list, made as "Retail prices" if there is none) |
| `opening_stock` (Inventory) | `stock.adjust` | sku*, location* (location code), quantity*, unit_cost*, batch_no, expiry_date, as_of |
| `customers` (CRM) | `customers.manage` | name*, code, kind, phone, email, tax_id, group, payment_terms_days |
| `suppliers` (Purchasing) | `suppliers.manage` | code*, name*, tax_id, phone, email, payment_terms_days |
| `employees` (People) | `employees.manage` | full_name*, hire_date*, employee_no, branch (code), department (must exist), national_id, tax_id, phone, email, residency, is_director |
| `accounts` (Finance) | `accounts.manage` | code*, name*, type* (`asset liability equity income expense`), subtype |

A kind appears only when its unit is enabled for the business and the user holds both `imports.manage` and the
permission of that data (checked for the chosen company, again at check and at commit).

Order for a new business: units and tax codes (Products > Setup), locations (Stock), **products**, **opening stock**,
customers, suppliers, staff. Open Finance once before importing accounts (its books must exist; accounts already in the
default chart are skipped).

### Duplicates and "already in Ziira"

A row whose record already exists is **skipped**, not an error, so uploading the same file again changes nothing:
products by SKU, customers by code (or, without a code, name + phone), suppliers by code, employees by number (or name
+ start date), accounts by code, opening stock when the product already has stock history at that location.

### Reconciliation figures

| Kind | Figures added up |
|---|---|
| products | selling prices (price column, against the open prices in the price list) |
| opening_stock | quantity, and stock value = quantity x unit cost per row, with the ledger's own rounding (cost to 6 places, value to 2); read back from the opening movements |
| the others | counts only |

## Rollback

**No kind is reversible in this release** (`reversible: false` in `GET /imports/kinds`, with a note saying what to do
instead). The owning units cannot delete what they created (products, customers, suppliers, employees and accounts are
switched off or put on hold; posted stock and journal entries are corrected with adjustments and reversals), and the
import does not hack around that. Check the file carefully, import a few rows first, and use the dry run. A discarded
batch (`DELETE`) only removes the staged file.

## What cannot be imported yet, and why

- **Customer opening balances (money customers owe at the start).** Point of Sale keeps receivables as invoices and
  receipts; there is no service to bring in an opening balance without inventing a fake sale (which would also post
  revenue and tax). Needs a proper opening-balance document in POS, posted to the customer control account.
- **Supplier opening balances** (same reason: no opening-bill service in Purchasing).
- **Opening trial balance / opening journals.** Manual journals refuse control accounts (stock, customers, suppliers,
  mobile-money clearing), and a real opening balance includes them; and a journal must balance as a whole, which does
  not fit a row-by-row import. Needs an "opening balances" document in Finance that takes the control balances from the
  subledgers. Until then: import stock (which posts to inventory), and have the accountant post the rest.
- **Customer credit limits** (raising credit needs a second person's approval) and **supplier bank details** (fraud
  control: proposed, confirmed by another person and approved) are never imported. Add them in the screens.
- **Employee pay terms and bank details** (own permission, `employee.pay_edit`).
- **Excel workbooks** (`.xlsx`): save as CSV. No new dependency was added.
- **Opening stock as one document per file**: each row is its own opening-stock document, so one bad row never holds
  back the others (the stock ledger and the books are the same as if one document were posted).
- Rows are created in the name of the system; the person who started the import is recorded on the batch and in the
  audit log (`imports.batch` entries), not as `created_by` of each record.

## Adding an importer for a unit

Implement `Importer` (`ziira/modules/imports/public.py`) inside the unit that owns the data, register it with
`provides("imports.importer")` in the unit's `hooks.py`, and add `"imports.importer"` under `[extends] implements` and
`"imports"` under `optional` in its manifest (see `ziira/modules/products/importers.py`, the smallest complete one):

- `columns`: name, required, description, example, aliases (for the mapping suggestion), `total` (the name of a figure
  to add up).
- `validate_row(session, company_id, row)`: plain messages, **reads only**. Reuse the unit's own rules
  (`attempt(errors, lambda: rules.check_name(...))` collects a rule's message) and look up codes with queries on the
  unit's own schema. Say how to fix each problem ("Add it under Products > Setup first").
- `import_row(session, company_id, row, local_id)`: call the unit's service and return the new record's id; raise on any
  problem (the row becomes `failed`). `local_id` is the staged row's id, stable across retries.
- `key(row)`: what makes a row unique in the file; `existing(...)`: a message when the record is already in Ziira.
- `totals(rows)` and `imported_totals(session, company_id, ids)`: the file's sums and the same figures read back from
  the records; name money figures in `money_totals`.

## Not yet verified

- Tested against generated files only. No export from a real third-party system was available, so column aliases are
  guesses based on common names; real exports will need their aliases added and probably their quirks (fixed-width
  fields, multi-line headers, totals rows) handled.
- The web wizard type-checks, lints and has unit tests for its logic, but was not exercised in a browser.
- Speed, measured once on a development laptop with 1,000 product rows (each with a price): upload 0.3 s, check 8.5 s
  (the check is one request, so it is why the limit is 5,000 rows, about 45 s), import 34 s in the worker (about 30
  rows a second: every row goes through the full product and price services). Nothing here was tuned (lookups are
  not cached between rows). A big migration is therefore several files; the CLI avoids the request time limit.

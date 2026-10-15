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
.venv/bin/ziira import demo-hardware customer_balances owed.csv --as-of 2026-06-30 --commit      # opening balances
.venv/bin/ziira import demo-hardware opening_trial_balance tb.csv --as-of 2026-06-30 --tolerance 0.05 --commit [--confirm]
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
| `customer_balances` (POS) | `receivables.manage` | customer_code*, amount* (negative: the customer is in credit), reference, invoice_date, due_date. **Needs the go-live date.** |
| `supplier_balances` (Purchasing) | `bills.manage` | supplier_code*, reference*, invoice_date*, amount*, due_date. **Needs the go-live date.** |
| `opening_trial_balance` (Finance) | `journal.approve` | account_code*, debit, credit, party_code, branch. **Needs the go-live date.** All rows or none. |

A kind appears only when its unit is enabled for the business and the user holds both `imports.manage` and the
permission of that data (checked for the chosen company, again at check and at commit).

Order for a new business: units and tax codes (Products > Setup), locations (Stock), **products**, **opening stock**,
customers, suppliers, staff. Open Finance once before importing accounts (its books must exist; accounts already in the
default chart are skipped). The opening balances have their own order, below; the web app lists it under **Admin > Import
data > Opening balances checklist** with each step's state.

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

## Opening balances: moving onto Ziira with money already owed

A business starts on a **go-live date** (the day the balances are as at, normally the last day of a month, in an open accounting
period, not in the future; every balance file of the business uses the same one). Three kinds bring the money in. Upload them
**in this order** (each refuses clearly when its predecessors are missing):

1. **Accounts** (the chart), **customers**, **suppliers**, **products**, **opening stock** (give its movements the go-live date: the
   file's `as_of` column, or the *Business date* of the opening-stock screen).
2. **`customer_balances`**: one row per open invoice (`customer_code`, `reference` = the old invoice number, `invoice_date`, `due_date`
   (default: invoice date + the customer's terms), `amount`). A customer who paid in advance is a *negative* amount (no dates needed).
3. **`supplier_balances`**: one row per open supplier invoice (`supplier_code`, `reference` = the supplier's invoice number,
   `invoice_date`, `due_date` (default: + the supplier's terms), `amount` above zero).
4. **`opening_trial_balance`** last: the accountant's trial balance at the go-live date.

Upload with the go-live date: `POST /imports/batches?kind=customer_balances&as_of=2026-06-30...`, the wizard's *Go-live date*
field, or `ziira import <tenant> customer_balances file.csv --as-of 2026-06-30`.

### What each one posts (Finance's posting engine, always dated the go-live date; `docs/localisation.md` rule 15 applies: no country)

| Import | Creates | Entry |
|---|---|---|
| `customer_balances` | an **opening invoice** per row: no lines, no tax, no stock, no revenue; keeps the original date, due date and number, so ageing, statements and reminders work; paid by ordinary customer receipts. A credit is an **opening receipt** (method `opening`) held unallocated on the customer's account (apply it to invoices or refund it as any advance). | Dr Accounts receivable (that customer) / Cr **Opening balance equity**; a credit the other way round |
| `supplier_balances` | an **opening bill** per row: posted, no lines, no goods, no tax, no three-way match; paid like any bill, shown in payables ageing | Dr Opening balance equity / Cr Accounts payable (that supplier) |
| `opening_stock` (already there) | opening stock movements | Dr Inventory / Cr Opening balance equity |
| `opening_trial_balance` | **one** opening balance entry (document `OB-...`) for the whole file | every *ordinary* balance-sheet line as listed, and a line on Opening balance equity that cancels the three entries above |

**Opening balance equity** is account `3100` in the default chart; which account each opening entry uses is a posting rule
(`opening_receivable`, `opening_payable`, `opening_balance`, role `opening_equity`), so a business can point it elsewhere.

### The trial balance

- Rows: `account_code`, `debit` or `credit`, and for the receivable and payable accounts the `party_code` of the customer or supplier
  (one row per party; a total for the control account alone is **refused**). Optional `branch`.
- **Income and expense accounts are refused** (a trial balance for the balance sheet only: profit before go-live belongs in an equity
  account). **Other control accounts** (mobile money clearing, goods received not invoiced, transfers, net pay payable) are refused:
  they are kept by their own records; put such a balance in an ordinary account.
- **Control lines are checked, not posted**: the file's receivable, payable and inventory lines must equal, party by party, what the
  customer, supplier and stock imports put in at the go-live date. Differences are listed ("CUST-A: file 3,000.00, Ziira 3,500.50").
  Import those first. After the trial balance is posted, customer and supplier balances can no longer be added (reverse it first).
- **It must balance as a whole.** If debits and credits differ, the check shows the difference and the import is refused until the
  user **confirms** (`commit?confirm=true`, the wizard's checkbox, `ziira import ... --confirm`): the difference is then posted to
  Opening balance equity, and recorded on the opening balance document. A difference up to the **allowed difference** (`tolerance`,
  chosen at upload, default 0) is posted to Opening balance equity without asking and is noted.
- One entry per company. A second needs the first reversed (**Finance > Opening balances**, or reversing the import).
- Needs `journal.approve` (the approver's permission) as well as `journal.post_manual`: an opening balance is never waiting in an approval
  queue, so whoever posts it is the approver.
- Period: the entry is dated exactly the go-live date. A period that is not open **refuses** it (the late-posting policy never moves an
  opening balance into another month).

### Reconciliation

The report of each kind adds up the file and compares it with what was created and with the books:

| Kind | Figures |
|---|---|
| `customer_balances` | *customer balances*: the file, the opening documents (invoices less credits), and *posted to the books*: the receivable lines of the entries those documents made |
| `supplier_balances` | the same for what is owed to suppliers |
| `opening_trial_balance` | *debits* and *credits* account by account: the file against each account's balance at the go-live date in the books |

`ziira verify` covers the rest and keeps covering it: the **customer ledger** check (invoices less held credits = the receivable account,
customer by customer; every opening document has its entry) and a **supplier ledger** check (bills = the payable account, supplier
by supplier; every opening bill has its entry), next to the books check.

### Reversing a whole import

`POST /imports/batches/{id}/reverse` with a reason (button *Reverse this import* in the wizard) takes everything a finished import of
these kinds created out again, **all or nothing**, by the owning unit's own reversal: opening invoices are cancelled and opening
credits reversed (Finance posts the mirror entries), opening bills are reversed, the opening balance entry is reversed. The batch
is marked `reverted`. Limits:

- **Refused, changing nothing, once later activity touched the documents**: an opening invoice with a payment or credit on it, a
  credit that was applied or refunded, a bill that was paid or credited. The message names the documents; reverse those payments
  first (Receipts / Bill payments) and reverse the import after.
- Reverse the trial balance **before** the customers or suppliers it was checked against. Opening stock has its own import and is
  not reversed with the balances (correct it with stock adjustments).
- An opening document is never edited or cancelled one by one: an opening invoice cannot be cancelled by hand, an opening bill cannot be
  reversed as a bill, the opening entry cannot be reversed as a plain journal entry.
- Uploading the corrected file after a reversal imports it again; uploading the same file twice without reversing imports nothing
  the second time (rows already there are skipped by customer/supplier + reference; a second trial balance is refused).

## Rollback

The other kinds are **not reversible** (`reversible: false` in `GET /imports/kinds`, with a note saying what to do instead). Their
owning units cannot delete what they created (products, customers, suppliers, employees and accounts are switched off or put on
hold; posted stock and journal entries are corrected with adjustments and reversals), and the import does not hack around that.
Check the file carefully, import a few rows first, and use the dry run. A discarded batch (`DELETE`) only removes the staged file.

## What cannot be imported yet, and why

- **Supplier balances the other way round** (a supplier owes you money): a credit note in Purchasing, not an opening bill.
- **Other control accounts in a trial balance** (mobile money clearing, goods received not invoiced, stock in transit, transfers, net
  pay payable): there are no records to bring in; put the balance in an ordinary account or settle it before go-live.
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
  the records; name money figures in `money_totals`. (`read_back(session, company_id, rows, ids)` replaces `imported_totals` when
  the figures depend on the rows themselves.)
- Balances as at a date: set `needs_go_live = True` (the upload then requires `as_of`, which arrives as `row.options.as_of`).
- Rows that only make sense together (a trial balance): `whole_file = True`, then `check_file(rows)` returns a `FileCheck` (problems
  stop the import; `confirm` is a warning the user must accept) and `import_file(rows, confirmed=)` creates the one record; every row
  is imported with it or none is. The file is checked again just before the import.
- Undoable imports: `reversible = True` and `reverse(session, company_id, record_ids, reason)`, which reverses through the owning
  unit's own service and raises, changing nothing, when later activity makes that unsafe.

## Not yet verified

- Tested against generated files only. No export from a real third-party system was available, so column aliases are
  guesses based on common names; real exports will need their aliases added and probably their quirks (fixed-width
  fields, multi-line headers, totals rows) handled.
- Opening balances: hand-calculated tests with one set of numbers, a Hypothesis property over random balances and the pure rules,
  but no accountant has checked the postings, and nothing has been run against a real ledger export (see "Accounting decisions" in
  the finance README).
- The web wizard type-checks, lints and has unit tests for its logic, but was not exercised in a browser.
- Speed, measured once on a development laptop with 1,000 product rows (each with a price): upload 0.3 s, check 8.5 s
  (the check is one request, so it is why the limit is 5,000 rows, about 45 s), import 34 s in the worker (about 30
  rows a second: every row goes through the full product and price services). Nothing here was tuned (lookups are
  not cached between rows). A big migration is therefore several files; the CLI avoids the request time limit.

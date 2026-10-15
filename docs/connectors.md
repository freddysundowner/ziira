# API connectors: ERPNext, Odoo, Zoho Books, QuickBooks Online

Intelligence can run on top of a business's existing system ("standalone mode"). A **connector** reads the other system
and turns what it finds into Ziira's canonical model (`ziira/modules/connect/public.py`); the Connectors module stores
that read-only and Intelligence's standalone checks read only that store. This page covers the four connectors that talk
to a system's own API. File and statement connectors are in the standalone-mode doc.

**Read-only is a rule, not a hope.** Every connector sends only reads (`GET`, Odoo's `search_read`/`read`/
`search_count`/`fields_get`, QuickBooks queries) and asks the business for a key or approval that can be withdrawn at
any time. No password is ever shared or stored.

> ## WARNING: never run against the real service first
>
> **These four connectors have been written from each vendor's public documentation and tested only against recorded-
> style mock replies. They have never been run against a real ERPNext site, Odoo database, Zoho Books organisation or
> QuickBooks company.** Request formats, field names, error replies and rate limits may differ in practice. The first live
> run of each must be against a **demo or sandbox company** (checklists below). Do not connect a customer's real books
> until that checklist is complete and its notes are written into this page.

## What is read (all four)

| Canonical entity | ERPNext | Odoo | Zoho Books | QuickBooks Online |
|---|---|---|---|---|
| branches | Warehouse (not groups) | stock.warehouse, pos.config | (not read) | Department (locations) |
| parties | Customer, Supplier | res.partner (customer or supplier rank) | contacts | Customer, Vendor |
| products | Item | product.product | items | Item (not categories) |
| users | User (+ roles) | res.users | users | Employee |
| sales | POS Invoice, Sales Invoice (with items, payments) | pos.order (+lines, payments) | invoices (+line items) | SalesReceipt, Invoice, CreditMemo, RefundReceipt |
| invoices (receivable/payable) | Sales Invoice, Purchase Invoice | account.move: out/in invoices and refunds | invoices, bills | Invoice, Bill |
| payments | Payment Entry | account.payment | customer payments, vendor payments | Payment, BillPayment |
| stock_movements | Stock Ledger Entry | stock.move.line (done) | (not read) | (not read) |
| expenses | Expense Claim | hr.expense (if installed) | expenses | Purchase |
| journal_entries | Journal Entry (manual) | account.move of type entry | journals | JournalEntry, Deposit |

Mapping rules worth knowing:

- **Only finished documents.** Drafts are never read. Cancelled or voided documents are read and marked
  (`voided`/`cancelled`) so Intelligence can see them; where the canonical model has no status field (payments, expenses,
  stock movements, journals) a cancelled document is kept with amount/quantity 0 (journals: no lines, memo "cancelled")
  so the earlier copy is neutralised when the record is replaced.
- **Returns and credit notes** are separate sales with a negative total and `refunded` status (ERPNext returns,
  Odoo POS refunds, QuickBooks CreditMemo/RefundReceipt). Odoo and QuickBooks credit notes on the invoices list are
  negative amounts.
- **Records are upserted by their source id (`ref`).** Reading a record twice is harmless; that is why every cursor
  re-reads the last five minutes.
- Source ids that could clash are prefixed: QuickBooks `customer:12` vs `vendor:12`, `invoice:5` vs `bill:5`; Odoo
  `stock.warehouse:1` vs `pos.config:1`.
- **Payment methods** are mapped by the words in the name the business gave them (cash, card, bank, mobile-money
  wording) and fall back to `other`. Unusual names will show as `other`.
- Money is read as text into `Decimal`; nothing is rounded.

### Not read, on purpose

ERPNext: GL Entry (system-generated postings; manual Journal Entries are read), HR "Branch" (sales carry warehouses).
Odoo: sales invoices outside the Point of Sale (they appear as invoices, not sales, to avoid counting a POS order and
its invoice twice), stock.move (move lines carry the same facts). Zoho: credit notes, inventory, locations.
QuickBooks: accounts, inventory adjustments, deleted transactions (see "Known limits").

## How access is controlled

1. Ziira asks the business for a **dedicated, limited** key or approval (never a person's own login).
2. The business can withdraw it at any time in the other system (steps per system below). Withdrawing stops Ziira at once;
   the next sync shows "needs reconnecting".
3. Secrets are stored encrypted (`store_credential`), are never shown again, never put in addresses, logs or audit
   entries, and are removed from any vendor error text before the owner sees it.
4. A web address entered for ERPNext or Odoo must be public `https://`: in production addresses inside a private network
   (loopback, 10.x, 192.168.x, link-local, bare names) are refused so a connection cannot be used to probe the platform's
   own network.

---

## ERPNext

**Access terms:** an API key and secret; no extra cost. ERPNext Cloud (Frappe Cloud) and self-hosted sites both work.

### Create the read-only access

1. In ERPNext open **Users** and add a new user, for example `ziira-readonly@yourbusiness.example`. Do not use a person.
2. Open **Role Permissions Manager** (search for it). Create a role such as **Ziira Reader** and give it **Read** (and
   **Report**) only, no Write/Create/Submit/Cancel/Delete, on: Warehouse, Customer, Supplier, Item, User, Has Role, Sales
   Invoice, POS Invoice, Purchase Invoice, Payment Entry, Stock Ledger Entry, Stock Entry, Expense Claim, Journal Entry.
   Give the user **only** that role. (Shortcut if you prefer: the standard Accounts User, Stock User, Sales User and
   Purchase User roles can read all of this but can also write; use the custom role if you can.)
3. Open the new user, scroll to **API Access** and click **Generate Keys**. Copy the **API Secret** immediately (shown
   once) and the **API Key**.
4. In Ziira choose ERPNext, paste the web address (for example `https://mybusiness.erpnext.com`), the API key and secret.
   Set the **time zone** to ERPNext's System Settings time zone: ERPNext sends times without a zone.

### What it asks ERPNext

`GET /api/method/frappe.auth.get_logged_user` and `GET /api/resource/<DocType>` with
`Authorization: token <key>:<secret>`, `fields`, `filters` (`docstatus in (1, 2)`, `modified > <cursor>`),
`order_by=modified asc, name asc`, `limit_start`, `limit_page_length=200`. Invoices, payment entries, journal entries and
users are then read one by one (`GET /api/resource/<DocType>/<name>`) for their child tables, so a first read of a
large site makes many requests; later runs read only what changed.

Newer fields (`is_consolidated`, `is_cancelled`, `mobile_no`, `email_id`) are requested if present: a version that lacks
them is detected from the error and the field is dropped, not fatal. POS Invoices that ERPNext has merged into a
consolidated Sales Invoice are read as the POS Invoices; the consolidated summary is skipped so nothing is counted twice.

### Freshness and limits

Daily by default. No vendor-imposed allowance on self-hosted; Frappe Cloud may rate-limit very busy sites (HTTP 429
is honoured and retried later).

### Withdraw access

Disable the user, or open it and click **Generate Keys** again (the old pair stops working), or remove the API Access.

### First-run checklist (demo site only)

1. Use ERPNext's demo/test site (or a throwaway site with the "ERPNext demo" data), never a customer's books.
2. **Test connection** succeeds and names the user; a wrong secret gives the friendly "did not accept" message.
3. Remove the role's read permission on Journal Entry: the journals sync should fail with a "not allowed to read" message
   naming the area, not crash. Restore it.
4. Sync **branches, parties, products**: counts match the site's lists (Warehouses without groups; Customers+Suppliers; Items).
5. Sync **sales**: compare 5 POS Invoices and 5 Sales Invoices with the site: totals, tax, discount, payment methods and
   amounts (a cash sale with change: the cash amount is net of change). Check a cancelled invoice shows `voided` and a
   return shows `refunded` with negative totals.
6. Check **time**: a document made at a known local time shows the same time in Ziira (confirms the time-zone setting).
7. Sync **stock movements**: a delivery shows `sale`, a purchase receipt `purchase`, a Stock Entry transfer
   `transfer_out`/`transfer_in`, a reconciliation `count`. Cancel one entry on the site and sync again: it shows quantity 0.
8. Sync **payments, invoices, expenses, journal entries**; confirm a payment shows its invoice reference.
9. Change one invoice on the site, sync again: one record changed, nothing duplicated.
10. Confirm the server log and the audit log contain no key or secret.
11. Record anything that differed below.

---

## Odoo

**Access terms:** self-hosted Odoo (Community or Enterprise): yes. **Odoo's own hosted service (Odoo Online): only on the
Custom plan**; on other plans the external API is closed and the business must use daily exports (the file connectors).
Odoo.sh and self-hosted databases work. Ziira says so in the failure message when Odoo answers 403/404 at `/jsonrpc`.

### Create the read-only access

1. **Settings > Users & Companies > Users > New.** Name it "Ziira (read only)", with its own login (for example
   `ziira@yourbusiness.example`). Do not reuse a person.
2. Give it the lowest access that can read what you want us to see: **Invoicing: Read-only** (or *Auditor*), **Sales: User**,
   **Inventory: User**, **Point of Sale: User** (only if you use POS), **Expenses: Team Approver** (only if you use
   expenses). No Administrator or Manager rights anywhere. Odoo's access rights, not Ziira, are the real limit: Ziira
   additionally refuses to send any method but the reads.
3. Sign in once as that user (this sets its password). Open **My Profile > Account Security > New API Key**. Name it
   "Ziira", confirm, and **copy the key now** (shown once). Odoo 14 has no API keys: use the user's password instead
   (not recommended; upgrade or create a dedicated login and rotate the password).
4. In Ziira choose Odoo and enter: web address, **database name** (shown on the sign-in page or at `/web/database/selector`),
   the user's **login** and the **API key**.

### What it asks Odoo

`POST /jsonrpc` with `common.version`, `common.authenticate`, and `object.execute_kw` with only `fields_get`,
`search_read` (with `fields`, `order`, `limit`, `context.active_test=false`) and `read`. `search_count` is allowed by
the guard but unused. Anything else is refused inside the connector before any request is made (a test proves it for
`write`, `create`, `unlink`, `execute`, `exec_workflow` and any name outside the list).

Pages are read in `write_date, id` order with a keyset condition (after the last `write_date` and id), so rows sharing
a timestamp cannot be lost at a page boundary.

### Versions 14 to 17

Each model is asked which fields it has (`fields_get`) and only those are requested. Known differences handled:
`stock.move.line.qty_done` (to 16) vs `quantity` (17); `account.payment.payment_method_id` (to 16) vs
`payment_method_line_id` (17); `reconciled_invoice_ids` (14+); `pos.order` user and config fields; `hr.expense`
totals. Odoo 18 and later are accepted but flagged "outside the versions we have tested" by the connection test.
Odoo 13 and older are not supported (no `customer_rank`).

A model that is not installed (no POS, no Expenses) or that the user may not read is **skipped with a note**
(`connector.notes`), never failing the whole sync, for the optional ones (`pos.order`, `pos.config`, `hr.expense`). For
a core model (invoices, payments, stock) a missing permission is a clear, non-retryable error naming the model.

### Freshness and limits

Daily. Odoo has no published per-key rate limit; hosted databases have worker limits, so Ziira reads 200 records per call.
Large first reads may take several runs (each run continues from the saved cursor).

### Withdraw access

Delete the API key (**My Profile > Account Security**) or archive the user. Access stops at once.

### First-run checklist (Odoo demo database only)

1. Use a fresh Odoo demo database (Odoo.sh trial or a local install with demo data), never a customer's.
2. **Test connection** shows the Odoo version and user. A wrong key, wrong login, and wrong database each give their own
   friendly message.
3. Sync **branches, parties, products, users**; counts match.
4. Create a POS order (cash and a second method), a refund, and a cancelled order; sync **sales**: totals, tax, discount
   (percent discount becomes money), payment methods, refund negative, cancelled `voided`.
5. Sync **invoices** and **payments**: an out_invoice with a partial payment shows paid = total - residual; a credit note
   is negative; a bill is `supplier`.
6. Sync **stock movements**: a delivery `sale`, a receipt `purchase`, a warehouse-to-warehouse transfer gives a
   `transfer_out` and a `transfer_in` pair, an inventory adjustment `adjustment`. Confirm which field name your version used.
7. Uninstall or deny **Expenses**: the expenses sync must finish with a note, not an error.
8. Sync **journal entries**: a manual miscellaneous entry has `is_manual` true; automatic ones (journal type other than
   *general*) false.
9. Re-sync after editing a record: changed, not duplicated.
10. Confirm no key appears in logs or audit entries. Record differences below.

---

## Zoho Books

**Access terms:** the business approves Ziira with one click (OAuth 2.0). Zoho limits how much an app may read per minute
and **per day, depending on the business's Zoho plan** (roughly 1,000 requests a day on free plans up to about 10,000 on
the top plans; check the business's plan: Zoho changes these).

### Approve

1. In Ziira choose Zoho Books, pick the **data centre** (the ending of the address you sign in at: `com`, `eu`, `in`,
   `com.au`, `jp`, `ca`, `sa`, `cn`). Data centres are listed in `zoho_books.DATA_CENTRES`: adding one is a data change.
2. Press **Connect**. Zoho shows the read-only permissions requested (contacts, settings, invoices, customer payments, bills,
   vendor payments, expenses, accountant/journals: all `.READ` scopes). Approve while signed in as a Zoho Books user who
   has **view-only** rights if you want a hard limit: the app can never read more than that user.
3. Choose the organisation if there are several. Ziira stores the refresh token encrypted.

The platform operator registers Ziira once as a Zoho API client (Zoho API Console, "Server-based Applications") and sets
`ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_ID` and `ZIIRA_OAUTH_ZOHO_BOOKS_CLIENT_SECRET`. The redirect URI to register is
`<ZIIRA_PUBLIC_BASE_URL>/api/v1/connect/oauth/callback` exactly. Without those settings a business can register its own
client and type the client id and secret into Ziira (they are stored encrypted and not shown again).

### Pacing and limits (what the connector does)

- At most `requests_per_minute` requests a minute (default 60, never above 90; Zoho's limit is about 100 per organisation).
- At most `max_requests_per_run` requests per run (default 500). When used up, the run stops cleanly, the connection shows
  it stopped early, and the next scheduled run continues from the saved cursor. Set it below the business's daily allowance
  shared across all its runs.
- A throttle reply (HTTP 429 or Zoho code 44/45) waits for `Retry-After` (capped at a minute) and retries once; if still
  throttled it fails as "retry later".
- Line items and payment-to-invoice links cost one request per document. Turn **fetch_details** off ("no") to read only
  list pages: cheaper, but item-level checks and payment links are then empty. Choose per business.
- Access tokens last an hour and are refreshed automatically (once, then the run stops with "connect again" if Zoho keeps
  refusing). Zoho limits token refreshes (about 10 per 10 minutes): a run refreshes once.

### Freshness and limits

Daily. Lists are asked for `last_modified_time` ordering and a `last_modified_time` filter; rows older than the cursor are
also dropped on our side in case Zoho ignores the filter on some lists.

### Withdraw access

In Zoho: your profile > **Sessions** / connected apps (or the API Console for your own client) and remove Ziira; or revoke
the refresh token. Disabling the Zoho user also stops it.

### First-run checklist (a Zoho Books trial organisation only)

1. Create a free Zoho Books trial organisation with sample data in the data centre you will use. Never a customer's.
2. Register a Zoho API client in that data centre; add the redirect URI above; note client id/secret.
3. **Connect**: approval screen lists only `.READ` scopes. After approving, the connection shows the organisation name.
4. **Test connection**: name shown. Revoke the approval in Zoho and test again: clear "connect again" message.
5. Sync **parties/products/users** then **sales/invoices/payments/expenses/journal entries**. Compare counts with the Zoho
   lists; check totals, void invoices as `voided`/`cancelled`, line item discount (percent and amount) and tax.
6. **Confirm the vendor details in "Doubts" below**, especially the `last_modified_time` filter and the rate-limit codes:
   watch the request log for `code` values; note any limit hit.
7. Run with `fetch_details` off and on; note requests used per document.
8. Lower `max_requests_per_run` to 5: the run must stop early and the next run must continue, not restart.
9. Confirm no token or secret in logs/audit.

---

## QuickBooks Online

**Access terms:** the business approves Ziira (OAuth 2.0, Intuit). **Intuit charges apps for reading data above a free
monthly allowance** (the Intuit "App Partner" programme: tiers and prices change; confirm the current terms before
onboarding a business). Ziira therefore reads only what changed since the last run (5-minute overlap) and uses one query
per page of up to 500 records.

### Approve

1. The operator registers Ziira once as an Intuit app (developer.intuit.com), sets `ZIIRA_OAUTH_QUICKBOOKS_CLIENT_ID` and
   `ZIIRA_OAUTH_QUICKBOOKS_CLIENT_SECRET`, and registers the redirect URI
   `<ZIIRA_PUBLIC_BASE_URL>/api/v1/connect/oauth/callback` exactly (production keys need Intuit's app review).
2. In Ziira choose QuickBooks Online, environment **production** (real company) or **sandbox** (Intuit test company), press
   **Connect**, sign in to Intuit as a QuickBooks user and choose the company.
3. **Honest note on permissions:** Intuit has only one accounting scope, `com.intuit.quickbooks.accounting`, which covers
   reading and writing. There is no read-only scope. Ziira sends only `GET` queries, but the approval screen will not say
   "read only". To make that a hard limit, approve while signed in as a QuickBooks user with **reports-only** or
   **view-only** rights: the app cannot exceed that user.

### Refresh tokens rotate

Intuit issues a refresh token valid for about 100 days that **changes when it is used**. The connector exposes the newest
one as `connector.updated_secrets = {"refresh_token": ...}`. **The sync engine must save these over the stored secrets,
including when the pull then fails**, or the next run finds the old token invalid and the business must reconnect. Also
a connection unused for 100 days expires and must be reconnected.

### What it asks Intuit

Token endpoint (POST) and `GET /v3/company/<realm>/query?query=select * from <Entity> [where Metadata.LastUpdatedTime >
'<cursor>'] order by Metadata.LastUpdatedTime startposition N maxresults 500&minorversion=75`, plus `companyinfo` for the
connection test and one `PaymentMethod` query per run. Production host `quickbooks.api.intuit.com`, sandbox
`sandbox-quickbooks.api.intuit.com` (the choice is stored as the connection's `environment`). Deleted records are not
returned by queries (see "Known limits").

### Freshness and limits

Daily. Intuit allows about 500 requests a minute per company (with a concurrency cap); the connector stays at 300 a
minute, and honours throttle replies (429) as "retry later".

### Withdraw access

In QuickBooks: **Apps > My Apps** (or Settings > Manage apps), find Ziira and **Disconnect**; or revoke at
accounts.intuit.com. Access stops at once.

### First-run checklist (an Intuit sandbox company only)

1. Create an Intuit developer account, an app with development keys, and a **sandbox company** (prefilled sample data).
2. Register the redirect URI on the app. Use environment **sandbox**.
3. **Connect**; confirm `realm_id` was filled in and the connection test shows the sandbox company name.
4. Sync every entity; compare counts with the sandbox company. Check: invoice discount lines become discount money; a
   voided invoice shows `voided`/`cancelled` (see Doubts); a CreditMemo and RefundReceipt are negative; payments link to
   their invoice/bill; a Deposit shows balanced debits and credits.
5. **Rotation:** note the refresh token in storage, run a sync, confirm it changed and was saved (only if your Intuit app
   rotates). Run twice more; no "connect again".
6. Disconnect in QuickBooks; test: clear "connect again" message.
7. Count the Intuit API calls the dev dashboard reports for a full sync; compare with the allowance before any live use.
8. Confirm no token or secret in logs/audit.

---

## File connectors (statements and exports)

Bank and mobile-money statements, and sales, invoice, stock and expense exports, are connectors too (`freshness = "on_upload"`).
They take PDF, Excel, CSV and pictures; layout is detected rather than mapped by hand, password-protected PDFs are opened with a
password used once, and pictures are read by a replaceable OCR engine (`connect.ocr_engine`). All of it is described in
`docs/standalone-mode.md` ("Files: drop it, Ziira works out the rest"); the OCR install is in `docs/operations.md`.

## Known limits

- **Deleted records** are not seen by incremental reads in any of the four (a deleted ERPNext document is cancelled first,
  which is seen; Odoo, Zoho and QuickBooks deletions of posted records are mostly prevented or voided instead). QuickBooks
  hard deletes would need its Change Data Capture API; not built.
- **Backdated edits** older than the 5-minute overlap are caught only if the edit changes the modified time, which it does
  in all four.
- ERPNext first reads make one request per invoice/payment/journal (child tables); budget for them.
- Zoho first reads of a large organisation take several runs under the daily allowance.
- Several companies in one system are read as one set of records; branch mapping in Ziira separates them by warehouse,
  POS, department, etc.
- Time: ERPNext sends local times (set the time zone); Odoo sends UTC; Zoho and QuickBooks send offsets. Date-only
  fields become midnight in the offset the system used when the document was created.

## Doubts: vendor details that could not be confirmed from here

Checked against memory of public documentation only. Each must be confirmed in the first sandbox run.

1. **ERPNext:** unknown-column replies may use a status other than 400/403/417/500 (then the optional-field fallback does
   not trigger); `Sales Invoice` `is_consolidated`, `Payment Entry` `paid_*_account_currency` and `Stock Ledger Entry`
   `is_cancelled` exist only in newer versions; Branch doctype unused.
2. **Odoo:** whether cash `pos.payment` rows are net of change or carry a separate negative change row (both net
   correctly); `account.payment` states ('cancel' vs 'cancelled'); API keys exist from Odoo 14.0? (they were introduced
   in 14.0 for Online and later for all editions: if absent, the user's password is used in the same field);
   `stock.location.warehouse_id` is stored from 14.
3. **Zoho:** the exact scope names (`ZohoBooks.<module>.READ`, in particular for items/users under `settings` and
   journals under `accountants`); whether every list accepts the `last_modified_time` filter (we also filter client-side);
   the error codes for per-minute (45?) and daily (44?) limits; `created_by_id` presence on invoice and journal detail;
   discount shape on line items (`discount` as '10%' or number, `discount_amount`); `has_more_page` pagination; the
   daily limits per plan (published figures change).
4. **QuickBooks:** whether `order by Metadata.LastUpdatedTime` plus `startposition` is stable under concurrent edits (the
   overlap covers drift); the spelling `Metadata.LastUpdatedTime` in queries; minor version 75 (older versions are
   being retired by Intuit); how a **voided** transaction looks (we detect total 0 with "Void" in the private note; confirm);
   the Intuit read-volume fees and free allowance; refresh-token expiry (about 100 days) and whether rotation happens on
   every refresh; `PrimaryTaxIdentifier` availability.
5. **All:** none of the HTTP behaviour (redirects, TLS, compression, unusually large replies) has been exercised for real.

## How to add another connector

1. Create `ziira/modules/connect/connectors/<name>.py` with a `Connector` subclass (see `public.py`): `kind`, `title`,
   `description`, `how_to` (plain steps to create read-only access), `config_fields` (mark secrets), `entities`,
   `needs_oauth`, `freshness`, `check()` (never raises, friendly message) and `pull()` (yields `CanonicalBatch`).
2. Decorate it with `@provides("connect.connector")` and import it from `connectors/registry.py`.
3. Use the helpers in `connectors/_http.py`: `raise_for_status` (friendly, secret-free errors; 429/5xx become
   `RetryAfterError`), `Pacer`, `normalise_base_url`, `decode_cursor`/`encode_cursor`/`cursor_time` (cursor per source,
   five-minute overlap), `seal` (marks only the final batch complete, always yields at least one), `payment_method`.
4. Order reads by modification time ascending and carry the cursor in every batch so an interrupted read resumes.
5. Rotating secrets: set `self.updated_secrets` as soon as you have them.
6. Test with `httpx.MockTransport` through `FakeSystem` (`tests/api_helpers.py`): assert exact requests (method, address,
   filters, paging), the mapping field by field, the cursor and its resume, error mapping, and that secrets never appear
   in any message. Copy `tests/test_erpnext.py` as the pattern.
7. Add a section to this page: how to create read-only access, what is read, limits, withdrawal, a first-run checklist, doubts.

## OAuth endpoints

`ziira/modules/connect/api/oauth_routes.py`. Needs permission `connect.manage`.

- `POST /api/v1/connect/oauth/{kind}/start` with `{connection_id, client_id?, client_secret?}` (kind `zoho_books` or
  `quickbooks`; the connection is created first with its data centre or environment). Platform app credentials
  (`ZIIRA_OAUTH_<KIND>_CLIENT_ID`/`_CLIENT_SECRET`) win if set; otherwise the business's own are used. Returns
  `{authorization_url, redirect_uri, expires_in_seconds}`.
- `GET /api/v1/connect/oauth/callback` is public (no sign-in; the signed state is the proof) and must be mounted on the
  unit's `public_router`. It redirects to `<ZIIRA_PUBLIC_WEB_URL>/connect/connections/<id>?oauth=success` or
  `?oauth=failed&reason=<code>` (`invalid_state`, `denied`, `no_code`, `already_used`, `unknown_connection`,
  `missing_app`, `exchange_failed`, `vendor_unavailable`, `error`).
- The state is `base64(payload).signature`, signed with the platform key, expires in 15 minutes, names the tenant,
  connection and user, and contains a one-time nonce kept encrypted with the connection's secrets; a second use fails.
  No token, secret or code is ever placed in an address or a log line.

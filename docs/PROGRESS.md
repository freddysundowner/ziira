# Progress

The handover between sessions. **Start of a session:** read "Current state" and "Start here".
**End of a session:** update this file, `CLAUDE.md` if commands or rules changed, then commit and
push (see the end-of-session steps in `CLAUDE.md`).

## Current state

| | |
|---|---|
| Phase | **Phases 1, 2, 3, 4, 6, 7, 8 and 9 done**, MFA and CD deferred · **next: phase 10, Command Center and Intelligence** · eTIMS is parked (below) |
| Architecture | One database per tenant + master database ([decision 0004](decisions/0004-database-per-tenant.md)) |
| Tests | 1230 backend (PostgreSQL 16; incl. fuzzing, security, Hypothesis properties, concurrency, offline sync) + 13 web · lint clean (ruff, mypy strict, import-linter; eslint, tsc) · see `docs/testing.md` |
| CI | GitHub Actions: backend lint + tests, and a web job (API types up to date, lint, types, tests, build) |
| Repository | https://github.com/freddysundowner/ziira.git, branch `main` |
| Last updated | 2026-10-14 |

## Start here (next session)

**Order (decided with the owner):** 7 Purchasing -> 6 Customers and sales -> 8 Finance reports -> 9 People and payroll ->
**10 Intelligence** -> 11 Hardening. Pull MFA and sign-in rate limiting forward if a customer goes live before phase 11.
**eTIMS is parked**, not planned: taxes are entered by hand (each product's tax code and VAT rate) until it is settled with
KRA, and it will then be an installable plugin. Everything about it is in `docs/parked/etims.md`.

Phases 4, 7, 6, 8 and 9 are done, including their loose ends. Next: **phase 10, Command Center and Intelligence** (daily checks
of business data and alerts to owners **by SMS or email**; WhatsApp is out for now). The building blocks exist: the exceptions
inbox, `ziira verify` checks, recurring tasks (`@periodic`), the notification queue, and every module's `public.py` reads.

**Rule from the owner (2026-10-14): no country in code** (`CLAUDE.md` rule 15, `docs/localisation.md`). Statutory deductions
are rules each business defines; currency, phone calling code and tax numbers are company data; mobile money is a generic
method with a provider. Kenya's M-Pesa (Daraja) stays as one payment provider and eTIMS stays a parked plugin.

Decisions in phase 8: SMS is BlessedTexts, email is SMTP, Brevo, Resend or SendGrid, WhatsApp is out for now; expenses are paid at
once (credit costs go through supplier bills); bank reconciliation clears ledger lines against the statement's balance;
the QuickBooks and Sage export layouts are untried in the real software (go-live checklist).

To do before real use (they need credentials and accounts, not code): the go-live checklist in `docs/go-live-checklist.md`.

Phase 4 left open (small, do when convenient):
- [ ] **Run the Daraja flows in Safaricom's sandbox.** Request formats in `payments/providers.py` are from the public
      docs and untested live; check real responses before any production use.
- [ ] A sale payment line that points at a succeeded STK prompt (`intent_id`) instead of a typed M-Pesa code.
- [ ] Web POS shell; quotations, orders and invoices (tables exist); credit sales and credit notes with phase 6.

## What exists, and where

| Area | What it does | Code |
|---|---|---|
| Tenants | Each business has its own database + login; master database lists them; template copy; drop | `kernel/tenants.py`, `kernel/db.py`, `kernel/master_migrations/` |
| Registry | Install on platform; enable/disable/remove per tenant database; upgrades; SDK check | `kernel/registry.py`, `kernel/manifest.py` |
| Sign-in | Workspace code + email/phone + password; access/refresh tokens; sessions; API keys | `kernel/auth.py`, `kernel/security.py` |
| Access | Roles, scopes (tenant/company/branch/own), permission checks, no escalation | `kernel/context.py`, `kernel/users.py` |
| Approvals | Matrix by company, document type, amount, steps; creator ≠ approver | `kernel/approvals.py` |
| Numbering | ADJ-THK-000001 style numbers per type and branch | `kernel/numbering.py` |
| Reason codes | Managed lists; seeded from manifests | `kernel/reasons.py` |
| Events | In-transaction subscribers; outbox; after-commit delivery with retries | `kernel/events.py`, `kernel/outbox.py` |
| Audit | Append-only, hash-chained log per tenant | `kernel/audit.py` |
| HTTP API | Auth, users, roles, API keys, settings, approvals; every unit's routes | `kernel/api/`, `kernel/app.py` |
| SDK | The only kernel interface for modules and plugins | `sdk/__init__.py` |
| CLI | `ziira units / install / tenants / create-tenant / enable / disable / remove / drop-tenant / outbox-run` | `kernel/cli.py` |
| Products | Reference module: UoMs, tax codes, products with permissions and scope | `modules/products/` |
| Sockets | Extension points and validation hooks between units; `[extends]` in manifests, checked at install | `kernel/extensions.py`, `docs/extending-units.md` |
| Web app | Shell + modules mirroring backend units, slots, typed API client, English/Swahili: sign-in, Products (with SKU suggestions), Users, Roles, plugin widget and tab | `frontend/`, `docs/frontend.md` |
| Inventory | Immutable stock ledger, locked balances, weighted average cost, locations, opening stock, adjustments, transfers via in-transit, counts, sale/return/receipt events, nightly check | `modules/inventory/` (README has the rules and endpoints) |
| Company settings | Negative stock policy, count variance threshold; audit log records device and IP | `kernel/company_settings.py`, `kernel/audit.py` |
| Integrity checks | `ziira verify` / `stock-verify`: units verify and rebuild their derived data | `kernel/checks.py`, `inventory/hooks.py` |
| Finance | Double-entry ledger, statements, exports, expenses, bank reconciliation: chart of accounts, posting engine, posting rules as data, periods and closing, manual journals with approval, reversals, trial balance, general ledger, books check | `modules/finance/` (README has the rules and endpoints) |
| Platform (phase 4) | Idempotency keys, job queue + `ziira worker`, exceptions inbox, encrypted credentials | `kernel/idempotency.py`, `jobs.py`, `exceptions_inbox.py`, `credentials.py` |
| Payments | Payments model, M-Pesa STK push and C2B, statements, matching engine, settlements, daily close | `modules/payments/` (README) |
| POS | Devices, tills, sales, voids, returns, price overrides, offline sync; price lists live in Products | `modules/pos/` (README) |
| Purchasing | Suppliers with guarded bank details, requests, orders, receipts, bills with the three-way match, payment, payables | `modules/purchasing/` (README) |
| CRM | Customers, contacts, versioned credit (increases approved), leads, follow-ups | `modules/crm/` (README) |
| Receivables | Credit sales, invoices, quotations/orders, customer payments, credit notes, statements, ageing, reminders, ledger check | `modules/pos/` (README) |
| Messaging | Notification queue, opt-outs, channel set-up (kernel); email/SMS providers (plugin); recurring tasks | `kernel/notifications.py`, `plugins/messaging/`, `docs/notifications.md` |
| Other modules | Tables, manifests and folders only | `modules/*/` |

Local development: Docker PostgreSQL 16 on port **5433** (`.env`); demo business: workspace
`demo-hardware`, login `owner@demo-hardware.test`, password `demo-pass-123`. Commands in `README.md`.

## Build plan (technical specification, section 21)

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Foundation: tenancy, auth, users, roles, scopes, audit, numbering, events and outbox, registry, SDK, CI/CD. Exit: isolation, permission and lifecycle tests pass | ✅ Done | MFA and CD deferred (below) |
| 2 | Catalogue and inventory: costing, stock ledger, transfers, counts. Exit: stock and costing invariants pass | ✅ Done | Property tests + concurrency tests; web screens later |
| 3 | Ledger: chart of accounts, posting engine, periods, trial balance | ✅ Done | Hypothesis and concurrency tests; reports beyond TB/GL are phase 8 |
| 4 | POS and payments: offline POS, tills, STK push, C2B, matching, daily close | ✅ Done | Daraja untested live (sandbox run pending); web POS shell later |
| 5 | eTIMS **plugin**: direct KRA integration, credit notes, retry | ⏸ Parked | Not planned; manual tax entry meanwhile. See `docs/parked/etims.md` |
| 6 | Customers and sales: CRM, credit, invoices, receivables, advances, statements, reminders (sent) | ✅ Done | Messaging gateways untested live |
| 7 | Purchasing: orders, receipts, bills, three-way match, returns, credit notes, reversals | ✅ Done | Includes supplier refunds and statement reconciliation |
| 8 | Finance reports: expenses, bank recon, P&L, balance sheet, cash flow, VAT, exports | ✅ Done | QuickBooks/Sage layouts untried live |
| 9 | People and payroll: employees, pay with approvals, attendance, leave, user-defined statutory rules, payroll runs, payslips, returns | ✅ Done | Statutory rules are the business's data; golden cases are hand-calculated |
| 10 | Command Center, Intelligence (owner alerts by SMS or email) | ⬜ | |
| 11 | Hardening: performance, security test, backups, monitoring | ⬜ | Includes MFA, rate limiting, PgBouncer |

## Deferred items

| Item | Why it waits | Target |
|---|---|---|
| Platform reference tables (`people.statutory_rate_table`, `intel.check_definition`) are copied into every tenant database | Rate changes must be pushed to all tenant databases | Phase 9 / 11 (operations) |
| Faster test suite (fuzz and unit-alone tests dominate) | Correctness first | Phase 11 |
| Web app: product edit, Inventory screens, offline POS shell | Phase 2+ follows the backend | Per module |
| Expiry warnings from batch dates | Needs the notification layer | Phase 10 |
| FEFO picking on transfers (lines name their batch for now) | Simplicity | When asked |
| Cancelling a dispatched transfer (receive with a reason instead) | Rare; reversal flow | When asked |
| Inventory web screens; product edit screen | Backend first | With the POS web work |
| MFA and one-time codes (spec 18) | Need an SMS/email gateway; **required before real customer data** | Phase 11 |
| Rate limiting / lockout on sign-in | Failed sign-ins are audited meanwhile | Phase 11 |
| Redis/Celery for jobs | `ziira worker` (database queue) is enough for now | When load needs it |
| CD (deployment pipeline) | No server yet; CI exists | When hosting is set up |
| OAuth 2.0 for third-party apps; webhooks | No third-party apps yet | Phase 10 at the latest |
| Workflow rules engine, notifications, file storage | Kernel features with no phase in the spec | Phase 10 |
| Plugin signature check on install | With the third-party plugin policy | Open |
| Year in document numbers | Prefix can be changed per series; no automatic yearly reset | When asked |
| Operations for many databases | PgBouncer, per-tenant backups and monitoring | Phase 11 |

## Decisions

Made (records in `docs/decisions/`):
- Kernel + pluggable modules and plugins, one schema per unit (0001).
- Row-level security on every tenant table (0002), kept as a second layer.
- Sign-in by email or phone and password (the master database's login directory finds the business; a workspace code is
  optional, for a login that works for several businesses); tokens, sessions, API keys, scoped roles; MFA deferred (0003).
- One database per tenant with a master database (0004; departs from spec section 04).
- Hosting on a VPS (not documented in specs) · stack Python/FastAPI/SQLAlchemy/PostgreSQL ·
  eTIMS integrated directly with KRA · 1.0 = 12 modules (projects and support tickets in 1.x) ·
  go to market with Ziira Intelligence first.

Open:
- Spec deviations: **migrations** are plain SQL (spec says Alembic) · **primary keys** are UUID v4
  (spec says UUID v7, time-ordered).
- From the spec: AI provider · POS packaging (apps vs web) · payroll
  compliance sign-off · third-party plugin policy · pricing model.

## Session log

| Date | What was done |
|---|---|
| 2026-10-13 (o) | **Email providers Brevo, Resend and SendGrid added** (with SMTP); **SMS through BlessedTexts; WhatsApp removed.** New provider `blessedtexts` (JSON POST, status_code "1000" = sent). WhatsApp left out for now: provider, fake, tests, channel values and docs removed; messages go by SMS or email, and Intelligence alerts will use those. Daraja stays as built, to be run in Safaricom's sandbox (`docs/go-live-checklist.md`). `make lint` clean; `make test` 1090 passed. |
| 2026-10-14 (s) | **Self-service registration** (owner: this is a SaaS, businesses must register themselves). `POST /api/v1/register` saves a request (password hashed, token only as a hash, nothing provisioned) and emails a link; `POST /api/v1/register/verify` creates the business (own database and login, owner, default units `ZIIRA_REGISTRATION_UNITS`, login directory entry) and signs the owner in. Workspace codes are generated from the business name. Abuse: email step, per-email and per-address rate limits (a real defect found by the tests: replacing an earlier request must not erase its history), modes open/invite/closed with `ziira invite create`, failed provisioning cleans up and leaves the link usable, purge by the worker. The platform sends the verification email through a configured provider (`ZIIRA_PLATFORM_EMAIL_*`); production refuses to start with open registration and no way to send. Web: two-step Register (country picks calling code and currency) and Verify screens and a link from sign-in (English and Swahili). Not built: CAPTCHA, billing and plans, operator console. See `docs/registration.md`. Suite: 1,259 passed. |
| 2026-10-14 (r) | **Sign-in without a workspace code** (owner's request: people just log in and reach their own database). The master database has `master.login_directory` (keyed hashes of each user's email and phone -> tenant); sign-in looks the login up, checks the password inside the business's own database, and signs in there. If the same login and password work for several businesses the reply is `409 choose_business` listing them and the client asks again with `workspace`. A wrong login or password always gets one answer; a stale directory entry is harmless (the password is verified in the tenant). Registered when a user is created and for a new tenant's owner; `ziira index-logins` rebuilds it (run by `run_local.sh`; run it once on existing installs). The web sign-in screen has no workspace field (it appears as a choice only when asked). Also: an end-to-end journey test (`tests/test_end_to_end.py`) and a live-server smoke script (`scripts/smoke_live.py`), which found and fixed a leftover 11-character tax-id limit. |
| 2026-10-14 (q) | **Phase 9 done (People and payroll) and the localisation sweep.** Statutory deductions (taxes, contributions, levies) are **rules each business defines as data** (`people/domain/rules.py`: rate, bands with a credit, fixed; base, order, reduces taxable pay, residency, employer part, effective date, payable account; entered by one person, verified by another); no country's values anywhere in code (the Kenyan seed was deleted). Employees (national ID encrypted), pay terms and salary bank details proposed then approved by someone else, pay items, shifts, attendance (manual and from the till), leave with approval and balances, payroll runs (calculate with review exceptions and blockers, approve by someone other than the preparer with a recalculation check, post to Finance by branch, pay, payment file), payslip printing, yearly tax card, a return per rule, payslips by email or SMS. Finance: payroll accounts, posting rules and recipes. **Localisation:** `kra_pin` -> `tax_id`, eTIMS fields -> `authority_code`/`authority_item_class`/`authority_ref` (unused `kernel.etims_*` tables dropped), currency chosen at company creation (`--currency`), phone numbers read with the company's calling code (`ziira.sdk.normalise_phone`), payment method `mpesa` -> `mobile_money` (accounts have a provider; Daraja is one), chart template neutral, credentials accept any provider name. Test caveat: run only one pytest session at a time (they share test database names) and under `caffeinate -dimsu` (a sleeping Mac makes tests hang). `make lint` clean; `make test` 1230 passed. |
| 2026-10-14 (p) | **Phase 8 done (Finance reports).** Statements: profit and loss (consolidated, one branch or split by branch), balance sheet (profit not yet closed shown so it always balances), cash flow summary, VAT summary, all with `format=csv` (formula-safe); journal export in generic, QuickBooks and Sage layouts with per-company account mapping (`finance/0003`). Expenses (`0004`, table existed since 0001): draft, submit, approval matrix (`expense`), posted Dr expense and VAT input / Cr cash, bank, M-Pesa or card, reversible. Bank reconciliation (`0005`): clear ledger lines until the cleared balance equals the statement, statement upload with suggested matches, final once completed; a period with one open cannot close (and neither with expenses awaiting approval). New permission `bank.reconcile`. Also this session: BlessedTexts SMS, Brevo/Resend/SendGrid email, WhatsApp removed. `make lint` clean; `make test` 1140 passed. |
| 2026-10-13 (n) | **Open items of phases 6 and 7 closed; eTIMS archived.** Supplier refunds of overpaid bills (`purchasing/0004_refunds`, `supplier.refunded`/`refund_reversed` posted by Finance), supplier statement reconciliation (JSON or CSV; matched / amount differs / missing here / missing there, balance difference explained), printable sale receipts, invoices and payment receipts (text 32/40/48 wide, HTML escaped, JSON; company settings `receipt_footer`, `invoice_footer`; extension point `pos.receipt_extras` for a future eTIMS plugin). eTIMS moved out of every to-do list into `docs/parked/etims.md`; sandbox runs and security items are in `docs/go-live-checklist.md`. `make lint` clean; `make test` 1090 passed. |
| 2026-10-13 (m) | **Loose ends of phase 6 closed.** Recurring tasks (`@periodic`, claimed per business per interval) running the expiry of old quotations; advance payments (`hold_balance`, `apply-credit`, refunds, reversal in either place, credit counted against the limit, ledger check updated); messaging: kernel notification queue with opt-outs, retries and the exceptions inbox, channel set-up API, the `messaging` plugin (SMTP, Africa's Talking, WhatsApp Cloud, fake), reminders sent on request, in a batch and daily by company setting, CRM do-not-contact. Fixed: the settings API did not expose `bill_match_tolerance_percent`. Migrations `kernel/0005`, `pos/0004`. |
| 2026-10-13 (l) | **Phase 6 done (Customers and sales).** CRM: customers, contacts, credit limits and terms with history (raises approved by someone else), leads with sources and conversion, follow-ups. POS: credit sales (limit and terms enforced, serialised per customer; offline credit accepted and raised), invoices to business customers, quotations and sales orders delivered by invoice, customer receipts (oldest first or named, via Payments, cash through the till), reversal of customer payments, credit notes for goods taken back (sales and invoices), voids, statements, ageing, reminders, `receivables.*` permissions, customer ledger integrity check. Finance: customer payment recipes. Products: customer-group price lists. Migrations `crm/0002`, `pos/0003`. |
| 2026-10-13 (k) | **Purchasing completed.** Reversing a payment updates the bill and the books (`payment.reversed` from Payments, `supplier.payment_reversed`); reversing a posted bill (mirror entry, quantities back, invoice number reusable); returning goods to a supplier (`goods.returned`, stock out, order reopened, flagged until credited); supplier credit notes (goods at stock value, variance, expense credits); landed-cost lines on bills. Finance: mirrored recipes, `credit_note.posted`. Migration `purchasing/0003`. Tests 953 -> 976. |
| 2026-10-13 (j) | **Phase 7 done (Purchasing).** Suppliers; bank details changed only by propose -> confirm by a different person -> approval, stored encrypted and shown masked; requests and orders with approval by amount; goods receipts (partial, never more than ordered, costed at the order, landed cost, supplier price history); supplier bills with the three-way match (tolerance setting `bill_match_tolerance_percent`), exceptions that need someone else, expense bills, payment through Payments, payables by age. Finance: recipes and rules for `bill.posted` and `supplier.paid`, purchase price variance account, recipe lines that name their own account. Products: `tax_code_rate`; Inventory: `location_scope`. Plan changed: eTIMS last, as a plugin. |
| 2026-10-13 (i) | **Phase 4 done.** Platform: idempotency keys, job queue and `ziira worker`, exceptions inbox, encrypted credentials. Payments: one payments model, C2B and STK (fake + Daraja providers, signed callbacks, status checks), statement import, matching engine with undo, settlements and cash deposits (Finance postings), daily close with reopening through approval. Products: price lists with history. POS: devices, tills with X/Z reports and variance posting, sales (VAT-inclusive, overrides, change, retry-safe), voids, returns with approval, immutable sale records, offline snapshot + exactly-once upload with kept rejections. Fixes found by tests: Payments never reopened a day on approval (no `approval.decided` handler); default-rule seeding restored deliberately removed posting rules. Tests 712 -> 912. |
| 2026-10-13 (h) | **Phase 3 done.** Finance module: pure domain (entries, periods, chart template, recipes, posting rules), chart of accounts, posting engine (`post_entry`: balanced, immutable, branch dimension, period policy, numbering, `journal.posted`), posting rules as data, subscribers for `stock.moved`, `sale.posted`, `sale.returned` (atomic with the operation), periods and closing checklist, manual journals with approval, reversals (manual entries only), trial balance and general ledger (reproducible for any past date, branch-limited), books check (`ziira verify`, with `--fix` catching up unposted movements). New migration `finance/0002_manual_journals`; new company setting `late_posting`; Inventory `stock.moved` carries branch and location kind; Inventory public stock-value reads. Tests 554 -> 712 (incl. Hypothesis and race tests; fuzzer covers Finance). Also fixed a scaling limit found by the full suite: every tenant database kept its own connection pool, so ~80 tenants exhausted PostgreSQL's connections; the least recently used pools are now closed beyond `ZIIRA_MAX_CACHED_TENANT_ENGINES` (25). |
| 2026-10-13 (g) | **Hardening pass on phases 1 and 2** (`docs/testing.md`). Added schema-driven fuzzing of every endpoint, adversarial security tests, concurrency tests, kernel and Products unit tests, every unit enabled alone, domain and service edge cases. Fixed 12 real defects: unstorable numbers (500s), bad paging, NUL text, malformed signed tokens, two races (simultaneous counts, simultaneous opening stock), `%`/`_` search wildcards, blank names, unknown eTIMS types, email/phone/password validation, corrupt settings, last-owner check, expired approvals listed, DB wording in 409s, NaN quantities. New migration `0003_one_open_count`. Tests 270 -> 554. Note: the full suite now takes ~6 minutes (the fuzz test is slower when many test databases exist). |
| 2026-10-13 (f) | **Phase 2 done.** Audit log records device and IP (`trust_forwarded_for` for proxies); company settings with API and `company_setting`. Inventory: pure domain rules (weighted average costing with negative stock, movement validation, FEFO, landed cost, transfers, counts), the immutable ledger (`post_movement`: locked cost and balance rows, events `stock.moved/negative/below_reorder`), locations, opening stock, adjustments with approval, transfers through in-transit with differences and approval, counts that compare against the system's figure at counting time (movement sequence numbers, share lock for the snapshot), cost visibility (`stock.cost`), subscribers for `sale.posted/returned`, `goods.received` (fake-event tests), `ziira verify` / `stock-verify` (new `kernel.integrity_check` extension point), demo opening stock. Tests 90 -> 270 (Hypothesis properties; a race test proven to fail without row locks). |
| 2026-10-13 (e) | Finished and committed the work left uncommitted after (d): extension points and validation hooks (`kernel/extensions.py`, Products sockets, `catalog_stats` plugs in), `GET /companies`, UoM/tax-code lists, SKU suggestions; the `frontend/` web app. Verified in the browser (sign-in, widget, SKU suggestions, duplicate-name block, plugin tab). Fixed stale suggestions in the new-product form; added `make web*`/`api-types` and a CI web job; wrote `docs/extending-units.md` and `docs/frontend.md`. Tests 80 → 90 backend, 13 web. |
| 2026-10-13 (d) | Clean-up: test runs now drop their databases; removed old shared databases (`ziira`, `ziira_test`) and the `ziira_app` login; updated decisions 0001/0002, module READMEs, guides; restructured this file with a phase 2 checklist. |
| 2026-10-13 (c) | Switched to one database per tenant: master database, template, per-tenant logins with encrypted connection strings, provisioning with cleanup, per-tenant enable/remove, upgrades across tenant databases, CLI (`tenants`, `remove`, `drop-tenant`). Unknown tenants in credentials now give 401, not 404. Tests 75 → 80. |
| 2026-10-13 (b) | Completed phase 1: auth, users/roles/scopes, permission checks, numbering, reason codes, approvals, outbox processor, SDK check, CI workflow, docs. Fixed cross-tenant company references and third-party plugin event matching. Tests 27 → 75. First push to GitHub. |
| 2026-10-13 (a) | Studied the codebase and specs. Saved text copies of the spec PDFs (`docs/specs/*.txt`). Checked phase 1 against spec section 21: it was incomplete; status corrected. |
| 2026-10-08 | Specs finalised. Project created: kernel, registry, SDK, 110-table schema, Products module, example plugin, tests, run script, demo data. |

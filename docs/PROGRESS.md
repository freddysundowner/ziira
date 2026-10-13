# Progress

The handover between sessions. **Start of a session:** read "Current state" and "Start here".
**End of a session:** update this file, `CLAUDE.md` if commands or rules changed, then commit and
push (see the end-of-session steps in `CLAUDE.md`).

## Current state

| | |
|---|---|
| Phase | **1 (Foundation) done**, MFA and CD deferred · **next: phase 2, Inventory** |
| Architecture | One database per tenant + master database ([decision 0004](decisions/0004-database-per-tenant.md)) |
| Tests | 80 passing on PostgreSQL 16 · lint clean (ruff, mypy strict, import-linter) |
| CI | GitHub Actions runs lint + tests on every push (green on `191549e`) |
| Repository | https://github.com/freddysundowner/ziira.git, branch `main` |
| Last updated | 2026-10-13 |

## Start here (next session)

Phase 2 · Catalogue and inventory. **Exit criterion (spec section 21): stock and costing
invariants pass.** Engine rules are in spec section 08 (`docs/specs/Ziira_Core_1.0_Technical_Specification.txt`).
Tables already exist in `ziira/modules/inventory/migrations/0001_init.up.sql`; the manifest already
has default role grants and reason codes. Follow `ziira/modules/products` and `docs/adding-a-module.md`.

- [ ] **2.0 Small kernel items first**
  - [ ] Fill `audit_log.device_id` and `ip_address` (session device, request IP) — gap from phase 1.
  - [ ] Company settings in `kernel.company.settings`: `negative_stock_allowed`, `count_variance_threshold`;
        an SDK function to read them; a settings endpoint (`settings.manage`).
- [ ] **2.1 Domain rules** (`inventory/domain/`, pure, unit-tested)
  - [ ] Weighted average cost per company: new average = (existing value + receipt value) ÷ (existing qty + receipt qty).
  - [ ] Outbound movements take the current average; value goes to cost of goods sold.
  - [ ] Movement validation: quantity ≠ 0; reason required for adjustment, count_variance, write_off.
  - [ ] Negative-stock policy (block, or allow and raise an exception for review).
  - [ ] Batches: first-expiry-first-out picking.
- [ ] **2.2 Locations**: create/list per branch (store, warehouse, transit, virtual).
- [ ] **2.3 Stock ledger service**: post movements, lock balance rows per product and location,
      update `stock_balance` and `product_cost` in the same transaction, publish `stock.moved`
      and `stock.below_reorder`.
- [ ] **2.4 Opening stock** (movement type `opening`).
- [ ] **2.5 Adjustments**: draft → submit (reason + `submit_for_approval`, number `ADJ`) →
      `@subscribe("approval.decided")` posts or rejects.
- [ ] **2.6 Transfers**: dispatch to in-transit → receive at destination; differences need a reason
      and approval (number `TRF`).
- [ ] **2.7 Stock counts**: snapshot at start, count lines, variance against the right expected figure,
      approval above the threshold, post `count_variance` movements (number `CNT`).
- [ ] **2.8 Subscribers** for `sale.posted`, `sale.returned`, `goods.received`, tested with fake events
      (POS and Purchasing do not exist yet).
- [ ] **2.9 `public.py`**: stock on hand, average cost (for POS and Purchasing later).
- [ ] **2.10 API and tests**: endpoints with permissions; permission tests per role; property tests
      (add Hypothesis): balance always equals the sum of movements; costing stays correct across
      receipts, returns, transfers and negative stock.
- [ ] **2.11** `ziira stock-verify`: rebuild balances from movements and compare (the nightly check).

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
| Other modules | Tables, manifests and folders only | `modules/*/` |

Local development: Docker PostgreSQL 16 on port **5433** (`.env`); demo business: workspace
`demo-hardware`, login `owner@demo-hardware.test`, password `demo-pass-123`. Commands in `README.md`.

## Build plan (technical specification, section 21)

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Foundation: tenancy, auth, users, roles, scopes, audit, numbering, events and outbox, registry, SDK, CI/CD. Exit: isolation, permission and lifecycle tests pass | ✅ Done | MFA and CD deferred (below) |
| 2 | Catalogue and inventory: costing, stock ledger, transfers, counts. Exit: stock and costing invariants pass | ⏳ Next | Plan above |
| 3 | Ledger: chart of accounts, posting engine, periods, trial balance | ⬜ | Tables exist; balance trigger works |
| 4 | POS and payments: offline POS, tills, STK push, C2B, matching, daily close | ⬜ | Needs idempotency keys, background jobs |
| 5 | eTIMS: direct KRA integration, credit notes, retry | ⬜ | KRA integrator certification before live |
| 6 | Customers and sales: CRM, credit, invoices, receivables | ⬜ | |
| 7 | Purchasing: orders, receipts, bills, three-way match | ⬜ | |
| 8 | Finance reports: expenses, bank recon, P&L, balance sheet, VAT | ⬜ | |
| 9 | People and payroll: HR, attendance, payroll, payslips | ⬜ | Rates verified by an accountant before launch |
| 10 | Command Center, Intelligence, WhatsApp | ⬜ | |
| 11 | Hardening: performance, security test, backups, monitoring | ⬜ | Includes MFA, rate limiting, PgBouncer |

## Deferred items

| Item | Why it waits | Target |
|---|---|---|
| Audit device and IP | Small gap found after phase 1 | Phase 2 (step 2.0) |
| Company settings (negative stock, limits) | First needed by Inventory | Phase 2 (step 2.0) |
| MFA and one-time codes (spec 18) | Need an SMS/email gateway; **required before real customer data** | Phase 11 |
| Rate limiting / lockout on sign-in | Failed sign-ins are audited meanwhile | Phase 11 |
| Idempotency keys on create requests | Needed for POS offline sync | Phase 4 |
| Background worker (Celery/Redis) | `ziira outbox-run` loop is enough for now | Phase 4 or 5 |
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
- Sign-in by workspace code; tokens, sessions, API keys, scoped roles; MFA deferred (0003).
- One database per tenant with a master database (0004; departs from spec section 04).
- Hosting on a VPS (not documented in specs) · stack Python/FastAPI/SQLAlchemy/PostgreSQL ·
  eTIMS integrated directly with KRA · 1.0 = 12 modules (projects and support tickets in 1.x) ·
  go to market with Ziira Intelligence first.

Open:
- Spec deviations: **migrations** are plain SQL (spec says Alembic) · **primary keys** are UUID v4
  (spec says UUID v7, time-ordered).
- From the spec: AI provider · WhatsApp number model · POS packaging (apps vs web) · payroll
  compliance sign-off · third-party plugin policy · pricing model.

## Session log

| Date | What was done |
|---|---|
| 2026-10-13 (d) | Clean-up: test runs now drop their databases; removed old shared databases (`ziira`, `ziira_test`) and the `ziira_app` login; updated decisions 0001/0002, module READMEs, guides; restructured this file with a phase 2 checklist. |
| 2026-10-13 (c) | Switched to one database per tenant: master database, template, per-tenant logins with encrypted connection strings, provisioning with cleanup, per-tenant enable/remove, upgrades across tenant databases, CLI (`tenants`, `remove`, `drop-tenant`). Unknown tenants in credentials now give 401, not 404. Tests 75 → 80. |
| 2026-10-13 (b) | Completed phase 1: auth, users/roles/scopes, permission checks, numbering, reason codes, approvals, outbox processor, SDK check, CI workflow, docs. Fixed cross-tenant company references and third-party plugin event matching. Tests 27 → 75. First push to GitHub. |
| 2026-10-13 (a) | Studied the codebase and specs. Saved text copies of the spec PDFs (`docs/specs/*.txt`). Checked phase 1 against spec section 21: it was incomplete; status corrected. |
| 2026-10-08 | Specs finalised. Project created: kernel, registry, SDK, 110-table schema, Products module, example plugin, tests, run script, demo data. |

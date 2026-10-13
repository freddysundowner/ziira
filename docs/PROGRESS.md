# Progress

Update this file at the end of every working session.

## Current state

**Phase:** 1 (Foundation) done · next: Inventory (phase 2)
**Tests:** 75 passing on PostgreSQL 16 (Docker, port 5433) · lint clean (ruff, mypy strict, import-linter)
**Repository:** https://github.com/freddysundowner/ziira.git (branch `main`)
**CI:** GitHub Actions (`.github/workflows/ci.yml`) runs lint + tests on every push
**Last updated:** 2026-10-13

## Build plan (from the technical specification, section 21)

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Foundation: tenancy, auth, users, roles, scopes, audit, numbering, events and outbox, registry, SDK, CI/CD. Exit: isolation, permission and lifecycle tests pass | ✅ Done | All exit tests pass. Products module is the template (with permissions); example plugin `catalog_stats`. Deferred items listed below |
| 2 | Catalogue and inventory: costing, stock ledger, transfers, counts | ⏳ Next | Tables exist; manifest has default role grants and reason codes |
| 3 | Ledger: chart of accounts, posting engine, periods, trial balance | ⬜ | Tables exist; balance trigger works |
| 4 | POS and payments: offline POS, tills, STK push, C2B, matching, daily close | ⬜ | |
| 5 | eTIMS: direct KRA integration, credit notes, retry | ⬜ | KRA integrator certification required before live |
| 6 | Customers and sales: CRM, credit, invoices, receivables | ⬜ | |
| 7 | Purchasing: orders, receipts, bills, three-way match | ⬜ | |
| 8 | Finance reports: expenses, bank recon, P&L, balance sheet, VAT | ⬜ | |
| 9 | People and payroll: HR, attendance, payroll, payslips | ⬜ | Rates verified by an accountant before launch |
| 10 | Command Center, Intelligence, WhatsApp | ⬜ | |
| 11 | Hardening: performance, security test, backups, monitoring | ⬜ | |

## Phase 1: what was built (2026-10-13)

- Sign-in by workspace code + email/phone + password; 15-minute access tokens checked against the
  session; device-bound rotating refresh tokens; sign-out and remote sign-out; API keys. See
  `docs/decisions/0003-authentication-and-access.md`.
- Users, roles, scoped grants (tenant/company/branch/own); default roles per tenant; units grant
  permissions to default roles through `[roles]` in their manifest; no privilege escalation.
- Permission checks on every endpoint (kernel and Products); scope checks in services.
- Kernel services in the SDK: `next_document_number`, `check_reason` (+ `[reason_codes]` seeding),
  `submit_for_approval` (multi-step matrix by amount, creator ≠ approver, `approval.decided` event),
  `check_company`, `@subscribe_after` with the outbox processor (`ziira outbox-run`).
- Registry: re-install applies new migrations (upgrades); SDK version check; enable seeds defaults.
- Fixed: third-party plugin handlers were matched to the wrong unit name.
- Fixed (found by the new tests): a tenant could save a record pointing at another tenant's company,
  because foreign keys ignore row-level security. Services now call `check_company`.
- Kernel migration `0002_auth_numbering_approvals` (hand-written).

## Deferred from phase 1 (decide when to do each)

- **MFA and one-time codes** (spec section 18): phase 11; needed before real customer data. Needs an SMS/email gateway.
- **Idempotency keys** on create requests: phase 4, with POS offline sync.
- **OAuth 2.0** for third-party apps; **webhooks** for tenants: when needed (phase 10 at the latest).
- **Rate limiting / lockout** on sign-in: phase 11 (failed sign-ins are audited now).
- **Plugin signature check** on install (spec section 02): with the third-party plugin policy.
- **Background worker** (Celery/Redis per spec) instead of the `ziira outbox-run` loop: phase 4 or 10.
- **Year in document numbers** (INV-THK-2026-...): prefixes can be changed per series now; no automatic yearly reset.

## Then phase 2: Inventory

1. `inventory` domain rules: weighted average cost, movement validation, negative-stock policy.
2. Services: receive opening stock, post adjustment (with reason + approval), transfer dispatch/receive, stock count.
3. Subscriber for `sale.posted` (stock out at average cost) once POS exists; test with a fake event now.
4. API + tests, including costing property tests (balance always equals sum of movements).

## Decisions made

- Hosting on a VPS (not documented in specs).
- Stack: Python/FastAPI/SQLAlchemy/PostgreSQL.
- eTIMS: integrate directly with KRA.
- 1.0 includes general ledger, CRM, HR and payroll (12 modules); projects and support tickets deferred to 1.x.
- Go to market with Ziira Intelligence on existing systems; Ziira Core as the deeper option.

## Open decisions

Spec deviations to confirm or fix: **migrations** are plain SQL (`docs/decisions/0001`) but the spec says
Alembic · **primary keys** use `gen_random_uuid()` (v4) but the spec says UUID v7 (time-ordered).

AI provider · WhatsApp number model · POS packaging (apps vs web) · payroll compliance sign-off ·
third-party plugin policy · pricing model.

## Session log

| Date | What was done |
|---|---|
| 2026-10-13 (b) | Completed phase 1: auth, users/roles/scopes, permission checks, numbering, reason codes, approvals, outbox processor, SDK check, CI workflow, docs. Docker PostgreSQL 16 on port 5433 (`.env`). Tests 27 → 75. First push to GitHub. |
| 2026-10-13 (a) | Studied the codebase and specs (no code changes). Created local dev roles from `scripts/setup_local_db.sql`; local PostgreSQL is 14, so 13 database tests error (schema needs 15+, spec says 16+). Saved text copies of the spec PDFs (`docs/specs/*.txt`). Checked phase 1 against spec section 21: not complete (auth/users/roles/scopes, numbering, CI/CD, outbox processing and permission tests missing); status corrected and next steps rewritten. |
| 2026-10-08 | Specs finalised (Core 1.0, Intelligence, Technical Specification with schema). Project created: kernel, registry, SDK, 110-table schema, Products module, example plugin, tests, run script, demo data. |

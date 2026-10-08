# Progress

Update this file at the end of every working session.

## Current state

**Phase:** 1 (Kernel) complete · next: Inventory module (phase 2)
**Tests:** 27 passing · lint clean
**Last updated:** 2026-10-08

## Build plan (from the technical specification, section 21)

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Kernel: tenancy, RLS, registry, events/outbox, audit, CLI, SDK | ✅ Done | Products module done as the template; example plugin `catalog_stats` |
| 2 | Catalogue and inventory: costing, stock ledger, transfers, counts | ⏳ Next | Tables exist in `inventory` schema |
| 3 | Ledger: chart of accounts, posting engine, periods, trial balance | ⬜ | Tables exist; balance trigger works |
| 4 | POS and payments: offline POS, tills, STK push, C2B, matching, daily close | ⬜ | |
| 5 | eTIMS: direct KRA integration, credit notes, retry | ⬜ | KRA integrator certification required before live |
| 6 | Customers and sales: CRM, credit, invoices, receivables | ⬜ | |
| 7 | Purchasing: orders, receipts, bills, three-way match | ⬜ | |
| 8 | Finance reports: expenses, bank recon, P&L, balance sheet, VAT | ⬜ | |
| 9 | People and payroll: HR, attendance, payroll, payslips | ⬜ | Rates verified by an accountant before launch |
| 10 | Command Center, Intelligence, WhatsApp | ⬜ | |
| 11 | Hardening: performance, security test, backups, monitoring | ⬜ | |
| — | Authentication and users (login, roles, permissions on endpoints) | ⬜ | Needed before any real customer data |

## Next steps (phase 2: Inventory)

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

AI provider · WhatsApp number model · POS packaging (apps vs web) · payroll compliance sign-off ·
third-party plugin policy · pricing model.

## Session log

| Date | What was done |
|---|---|
| 2026-10-08 | Specs finalised (Core 1.0, Intelligence, Technical Specification with schema). Project created: kernel, registry, SDK, 110-table schema, Products module, example plugin, tests, run script, demo data. |

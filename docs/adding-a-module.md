# Building out a module

Every module already has its folder, `manifest.toml` and `migrations/0001_init.up.sql`.
Use `ziira/modules/products` as the template.

## Steps

1. **Domain rules** in `domain/`: pure functions that validate and calculate. No database, no HTTP.
   Unit-test them in `tests/`.
2. **Models** in `repository/models.py`: map the tables already created by the migration
   (`__table_args__ = {"schema": "<module>"}`).
3. **Repository** in `repository/<module>_repo.py`: queries for this schema only.
4. **Services** in `services/`: one file per use case. A service validates with domain rules,
   reads and writes through the repository, calls `audit_record(...)`, and `publish(...)` events.
5. **API** in `api/schemas.py` and `api/routes.py`. Routes only convert HTTP to service calls and use
   `Depends(db_session)`. Every route declares the permission it needs:
   `dependencies=[Depends(require_permission(STOCK_ADJUST))]`.
6. **Public interface** in `public.py`: the functions other modules may call.
7. **Event handlers** in `events.py` with `@subscribe("event.type")`. They run inside the publisher's
   transaction, only for tenants that have this module enabled.
8. **Tests**: domain unit tests in the module's `tests/`, API and database tests in `tests/`.

## Permissions, scope and kernel services

Everything below comes from `ziira.sdk`. Products shows the pattern.

| Need | Use |
|---|---|
| Reject users who lack a permission anywhere | route: `dependencies=[Depends(require_permission("stock.view"))]` |
| Check the scope (which company or branch) | service: `current_context().require("stock.adjust", company_id=..., branch_id=...)` |
| Show only records the user may see | service: `current_context().companies_with("stock.view")` (None = all) and filter |
| Make sure a company or branch id belongs to this tenant | service: `check_company(session, company_id, branch_id)` before saving. Foreign keys are checked without row-level security, so they accept another tenant's id |
| A human document number (ADJ-THK-000001) | `next_document_number(session, company_id=..., branch_id=..., doc_type="stock_adjustment", prefix="ADJ")` |
| A required reason (voids, refunds, overrides, adjustments) | `check_reason(session, "stock_adjustment", reason_code_id, note)` |
| Approval before posting | `submit_for_approval(session, company_id=..., doc_type=..., doc_id=..., amount=...)` returns `"approved"` or `"pending"`; then `@subscribe("approval.decided")` and act when `event.aggregate_type == doc_type` (`event.payload["status"]` is `approved` or `rejected`) |
| Work after commit (notifications, webhooks) | `@subscribe_after("event.type")`; must be safe to run twice. Delivered by `ziira outbox-run` |

Scope rules: a tenant-wide grant reaches everything; a company grant reaches that company and its
branches; a branch grant reaches only that branch, so it cannot change company-wide records (such
as products); an `own` grant reaches only records the user created (`owner_id=`).

In the manifest, give the default roles their permissions and seed reason codes. They are applied
to each tenant when the unit is enabled (the Owner role always receives every permission):

```toml
[roles]
"Branch Manager" = ["stock.view", "stock.adjust"]
"Cashier" = ["stock.view"]

[reason_codes.stock_adjustment]
DAMAGED = "Damaged"
```

Default roles: Owner, Finance Manager, Branch Manager, Cashier, Storekeeper, Sales Rep, HR, Accountant.

Tests: API tests sign in with real users (`tests/conftest.py: make_tenant`, `sign_in`) and check
that each role can do exactly what it should. The development `X-Tenant-ID` header acts with every
permission, so it cannot test permissions.

## Changing tables

Never edit `0001_init.up.sql` after it has been applied anywhere. Add a new pair:

```
migrations/0002_add_something.up.sql
migrations/0002_add_something.down.sql
```

`ziira install <module>` applies any migrations not yet recorded in `kernel.schema_migration`.
Remember: foreign keys only to the kernel and to modules listed in `requires`; enable and force
row-level security on new tenant tables.

## Imports allowed

| From a module you may import | Not allowed |
|---|---|
| `ziira.sdk` | `ziira.kernel...` |
| your own module's packages | another module's services, repository or models |
| `ziira.modules.<other>.public` | |

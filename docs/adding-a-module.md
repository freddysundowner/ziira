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
   `Depends(db_session)`.
6. **Public interface** in `public.py`: the functions other modules may call.
7. **Event handlers** in `events.py` with `@subscribe("event.type")`. They run inside the publisher's
   transaction, only for tenants that have this module enabled.
8. **Tests**: domain unit tests in the module's `tests/`, API and database tests in `tests/`.

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

# Writing a plugin

A plugin adds a capability without changing any module. `ziira/plugins/catalog_stats` is a small example, and
`ziira plugin new` writes a complete working one for you.

## The kit

```bash
ziira plugin new my_plugin --category data [--countries KE,UG] [--dir /srv/ziira/plugins]
ziira plugin check ziira/plugins/my_plugin      # fast static checks + migration round trip; run it before every commit
ziira plugin test  ziira/plugins/my_plugin      # the plugin's own tests, on a throw-away platform
ziira plugin pack  ziira/plugins/my_plugin      # my_plugin-0.1.0.zplugin with a checksum, for distribution
ziira plugin install-archive FILE --expect-sha256 H   # operator: verify and unpack into the extra folder
ziira plugin list                               # what the extra folder holds, and what was refused
```

`new` writes a manifest (category, countries, permissions, roles, one published event), a migration pair that creates
`plg_my_plugin.item` with `tenant_id` and forced row-level security, `hooks.py` with a commented extension-point example,
`api/` (routes with `require_permission`, schemas), `services/` (validate, save, audit, publish), `domain/` (pure rules),
`repository/`, `public.py`, a README, and tests that already use the testing kit. Without `--dir` it goes into
`ziira/plugins/`; with `--dir` into any folder, which the platform finds through `ZIIRA_EXTRA_UNIT_PATHS` (the same
architecture rules apply; code there imports as `ziira_ext.<name>`).

`ziira plugin check` reports each problem with where it is and how to fix it, and ends with PASS or FAIL. It checks:
manifest schema; imports (only `ziira.sdk`, the plugin itself, and other units' `public.py`); foreign keys only to the
kernel, the plugin and units it `requires`; `tenant_id` + forced row-level security + policy on every table (statically
and on a scratch database); up and down migrations that exist and round-trip; permissions used are declared; every
endpoint has `require_permission`; published events are declared; no `float` money; no raw SQL against other units'
schemas or writes to kernel tables; no network calls at import time. Warnings (environment reads, network calls,
`subprocess`, ...) are what a reviewer will ask about. It is static and fast; it is not a security audit (docs/plugin-review.md).

## Folder

```
my_plugin/
  manifest.toml        kind = "plugin", category, countries, requires, permissions, [roles], publisher, homepage
  migrations/          0001_init.up.sql / .down.sql, creating schema plg_my_plugin
  hooks.py             @validate / @provides: plug into other units' sockets (declare under [extends])
  events.py            @subscribe handlers (optional)
  api/routes.py        router mounted at the manifest's api_prefix (/api/v1/plugins/<name>)
  services/ domain/ repository/    one use case per file / pure rules / this schema's SQL
  public.py            the only file other units may import
  tests/  README.md
```

## Rules

- Use only `ziira.sdk` and other units' `public.py`.
- Keep all tables in your own schema `plg_<name>`; `tenant_id` on every table; enable and **force** row-level security.
- Declare permissions in the manifest, give default roles theirs under `[roles]`, and protect every route with
  `Depends(require_permission("<name>.view"))`. Check scope in services: `current_context().require(perm, company_id=...)`,
  and call `check_company(session, company_id)` before saving anything that names a company or branch.
- Money is `Decimal` (`ziira.sdk`: `Amount`, `Quantity`, `Rate`, `UnitCost`, `money()`), never `float`. No country in code:
  rates, codes, accounts are data a business enters (CLAUDE.md rule 15). Country-specific plugins say `countries = ["KE"]`.
- `@subscribe` handlers run inside the publisher's transaction: keep them small. An exception rolls back the original
  operation, so only raise to block an operation deliberately.
- Slow or external work (webhooks, messages, provider calls) goes in `@subscribe_after` handlers or `@job`s, which run after
  commit (via `ziira worker`), are retried on failure, and must be safe to run twice. Never call out to the network in a
  request, or when the module is imported.
- To block or extend another unit's action (validation hooks, extension points) see `docs/extending-units.md`.
- A plugin can add screens to the web app through slots; see `docs/frontend.md`.
- A plugin that stores data about people implements `kernel.personal_data` (docs/privacy.md).
- Events other systems may subscribe to by webhook are marked in the **publishing unit's** manifest (docs/webhooks.md); a
  plugin can mark its own with `[provides.public_events."my_plugin.item_created"]` (description + the payload fields).

## Testing kit (`ziira.sdk.testing`)

Tests import from `ziira.sdk.testing` only (it is the supported surface; it is small on purpose). The scaffold's
`tests/conftest.py` pulls in the `registry` and `client` fixtures (a throw-away platform with every unit installed,
databases `ziira_test_*` dropped afterwards; runs queue on a file lock).

| Helper | Use |
|---|---|
| `make_tenant(name, units=[...])` | A business with a company, a branch and an owner, with the units switched on |
| `sign_in(client, tenant)` / `user_with_role(client, tenant, "Cashier")` or `permissions=[...]` | Real sign-in as the owner, a default role, or exactly these permissions (`[]` = may do nothing) |
| `run_outbox_once()` / `run_jobs_once()` | Deliver events to `@subscribe_after` handlers; run the due background jobs |
| `freeze_company_date(date(2026, 3, 1))` | `company_today()` answers that day inside the block |
| `fake_http(handler_or_status, json=...)` | A pretend web service (`.transport()`, `.client()`, `.requests`) for provider plugins; nothing touches the network |
| `assert_all_routes_guarded(app, "/api/v1/plugins/x", client=client, tenant=shop)` | Every endpoint under the prefix gives 401 without a login and 403 to a person with no permissions |
| `assert_tenant_isolation(client, other_owner, record_path, list_path=..., record_id=...)` | Another business cannot read the record or see it in a list |

Run a plugin's tests with `ziira plugin test PATH`, or `pytest PATH/tests --import-mode=importlib` (set
`ZIIRA_EXTRA_UNIT_PATHS` to the plugin's folder when it is outside `ziira/plugins`; needs the database from `make db-up`).
Tests for plugins inside the repository also run with `make test`.

## Distributing and trusting

`ziira plugin pack` writes `<name>-<version>.zplugin`: the plugin files, `ziira-pack.json` (sha256 of every file and one
checksum over all of them) and the checksum in the manifest. Publish the **archive's sha256** next to it. The operator
installs with `install-archive ... --expect-sha256`, reviews it (docs/plugin-review.md), and lists it in
`ZIIRA_ALLOWED_PLUGINS`: production loads nothing else from the extra folder. Fill in `publisher`, `homepage` and
`description` in the manifest; reviewers read them first.

## Country packs

A **country pack** brings a country's *data* to a business: tax codes, a chart of accounts, payroll tables, and the defaults the
sign-up form shows. It is a plugin with `category = "country"` and `countries = ["KE"]` (empty `countries` = worldwide, like
`pack_international`). It has no tables and no logic: `hooks.py` reads TOML files in `data/` and hands them to the units that offer
a socket for them. Copy `ziira/plugins/pack_ke`.

| File | Socket (owner) | Contract |
|---|---|---|
| `data/country.toml` | read by the kernel for `GET /api/v1/countries` | `[[country]]`: `code`, `name`, `currency`, `phone_calling_code`, `timezone`, `tax_id_label`, `tax_id_pattern` (a hint, not enforced), `date_format`, `number_format` |
| `data/tax_codes.toml` | `products.tax_code_seed` | `TaxCodeSeed.tax_codes() -> list[TaxCodeRow]` |
| `data/chart.toml` | `finance.chart_template` | `ChartTemplate.accounts() / journals() / rules()` |
| `data/payroll.toml` | `people.statutory_table_seed` | `StatutoryTables.tables() -> list[StatutoryTableSeed]` |

* Declare `countries = (...)` on the provider classes too (`countries = ("KE",)`): a company gets the providers that name its
  country, else the worldwide ones. Load data with `ziira.sdk.read_pack_data(__file__, "tax_codes.toml")`.
* Units copy the data into the business's own tables when the pack is switched on (see `docs/localisation.md`): idempotently, only
  what is missing, never overwriting what the business entered, never touching posted records. Do not write to unit tables
  yourself.
* **Never invent figures.** Every file says where its numbers come from and what must be verified; payroll tables are saved
  unverified. If you do not know a rate, leave the table out or mark the row as an example.
* A unit that wants to accept pack data offers its own extension point plus a generic fallback, and implements
  `kernel.country_seeder` (`CountrySeeder.seed(session, company_id, country)`, which must be idempotent and add only what is
  missing). See `ziira/modules/products/services/seed_tax_codes.py`.

## Provider plugins

A **provider plugin** is one vendor behind a module's extension point. The module keeps the provider-neutral models, rules and
URLs; the plugin supplies the formats. The reference is `ziira/plugins/mpesa` for `payments.provider`:

* Subclass `PaymentProvider` (from `ziira.modules.payments.public`): `stk_push`, `query_stk` (required), `parse_stk_callback`,
  `parse_c2b`, `normalize_phone`, plus plain attributes: `name`, `title`, `credential_fields` / `config_fields` (a list of
  `FormField`: the web app draws the forms from them; secrets are stored encrypted and never shown), the prompt limits, the
  `callback_reply` the provider expects, and `development_only` for simulators (refused in production).
* A statement format is a separate `StatementReader` on `payments.statement_format`.
* Callback URLs stay the module's (`/api/v1/payments/callbacks/...`); the module authenticates the address, the plugin only reads
  what the provider sends. Accounts keep `provider = '<your name>'`.
* Credentials go through the module (`PUT /accounts/{id}/credentials`), never your own table.
* **Upgrade step.** When a plugin takes over from code that used to be built in, add to its manifest
  `[upgrade] enable_if_sql = "select 1 from <schema>.<table> where ... limit 1"`: `ziira install` then switches the plugin on
  for the businesses where the query finds a row (read-only SQL; a business that never used it is left alone).
* Test the formats with the provider replaced by a mock transport (see `ziira/plugins/mpesa/tests/test_daraja.py`) and never
  claim a format works until it has been run in the provider's sandbox.

## Lifecycle

```bash
ziira install <name>                # offers it on the platform (master database)
ziira enable <tenant> <name>        # creates plg_<name> in that tenant's database
ziira disable <tenant> <name>       # data kept
ziira remove <tenant> <name>        # drops plg_<name> from that tenant's database (after disable)
ziira uninstall <name>              # refused while any tenant database still has it
```

Entry points (`[project.entry-points."ziira.units"]` in a package's own `pyproject.toml`) still work for plugins installed
as Python packages, but they are not covered by the allow-list or the archive checks: prefer the extra folder.

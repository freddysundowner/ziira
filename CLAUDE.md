# CLAUDE.md · Ziira Core

Read this first in every session, then read `docs/PROGRESS.md`: "Current state" and the
"Start here" checklist say exactly where work stands and what to do next.

**At the end of every session (always, without being asked):**
1. Run `make lint` and `make test`; record the result.
2. Update `docs/PROGRESS.md`: current state, phase table, next steps, session log line.
3. Update this file if commands, rules or conventions changed.
4. Commit everything and push to `origin` (https://github.com/freddysundowner/ziira.git).
   Never commit `.env` or other secrets (they are gitignored).

## What this is

Ziira Core is a modular ERP for small and medium businesses (first customers: multi-branch retail and distribution
in Kenya). **It is used worldwide: nothing in the platform assumes a country** (see rule 15 and `docs/localisation.md`). Standalone mode: a unit that reads another system must never write to it, and `connect.src_*` is read only by the `standalone.*` checks.
It pairs with **Ziira Intelligence**, a layer that checks business data daily and alerts owners by
message. Product and technical specifications are in `docs/specs/` (each PDF has a `.txt` copy
with the same name; read the `.txt`, since the PDFs need extra tools to read):

- `Ziira_Core_1.0.pdf`: the 12 modules and 1.0 scope
- `Ziira_Intelligence_1.0.pdf`: what Intelligence does
- `Ziira_Core_1.0_Technical_Specification.pdf`: architecture, engines (ledger, inventory, POS,
  payments, eTIMS, payroll), security, build plan; Appendix A is the full database schema

## Stack (decided)

Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic v2, PostgreSQL 16, Redis (later, for jobs),
React + TypeScript + Vite web app in `frontend/` (POS later). The public marketing website is a separate static Astro site in `site/` (SEO first; never import from `frontend/` or `ziira/`). Hosting is a VPS (do not document hosting details).
Country-specific integrations (Kenya's eTIMS, M-Pesa, ...) are plugins or providers behind extension points.

## Commands

```bash
bash scripts/run_local.sh     # one step: venv, master DB + template, demo business, API on :8000
make db-up                    # PostgreSQL 16 in Docker (port from ZIIRA_DB_PORT in .env)
make test                     # all tests (use `caffeinate -i make test` on a Mac: a sleeping laptop expires the test tokens) (creates/drops ziira_test_master, _template, _t_* databases)
make lint                     # ruff + mypy + import-linter
make web-setup | web | web-check   # web app: npm ci | dev server :5173 | lint+types+tests+build
make site-setup | site | site-build | site-check   # marketing website in site/ (static Astro, SEO audit; docs/marketing-site.md, site/SEO.md)
make site-catalog           # regenerate site/src/content/checks.catalog.json from the real check/action registry (scripts/export_check_catalog.py; plain text in site/src/content/*.plain.json; run by site-build/site-check)
make e2e-setup | e2e        # real-browser journeys (Playwright, folder e2e/): npm ci + Chromium | run all against a throwaway stack (docs/testing.md, docs/e2e-findings.md)
make deploy-test | deploy-test-docker   # production installer kit (deploy/, docs/installation.md): fake-server tests | real nginx -t in Docker
make api-types                # regenerate frontend/src/api/schema.d.ts after backend API changes (commit it)
.venv/bin/ziira units | install --all | uninstall <unit>          # platform (master database)
.venv/bin/ziira tenants | enable <tenant> <unit> | disable ... | remove ...   # <tenant> = code or id
.venv/bin/ziira drop-tenant <code> --confirm <code>                # deletes the tenant's database
.venv/bin/ziira create-tenant NAME --code CODE --company ... --branch-code ... --branch-name ... \
    --owner-name ... --owner-email ... --currency USD [--phone-country-code 44] [--tax-id ...]
                                            # owner password from prompt or ZIIRA_OWNER_PASSWORD
                                            # (businesses normally register themselves: docs/registration.md)
.venv/bin/ziira invite create [--uses N --days D]   # invitation code for ZIIRA_REGISTRATION_MODE=invite
.venv/bin/ziira plugin new|check|test|pack|install-archive|list    # plugin kit (docs/writing-a-plugin.md); tests use ziira.sdk.testing; production loads extra plugins only if in ZIIRA_ALLOWED_PLUGINS (docs/plugin-review.md)
.venv/bin/ziira index-logins [tenant]      # rebuild the login directory (sign-in without a workspace code)
.venv/bin/ziira apply-packs [tenant]       # copy the data of the country packs switched on into the business (adds only what is missing)
.venv/bin/ziira outbox-run [--once]         # deliver events to @subscribe_after handlers
.venv/bin/ziira worker [--once]             # outbox + background jobs (M-Pesa prompts, matching) + recurring tasks (checks, briefs) + purge
.venv/bin/ziira connect upload <tenant> <connection> FILE [--check] | ocr-check   # statements/exports: CSV, Excel, PDF; ocr-check = can this server read pictures (Tesseract)?
.venv/bin/ziira run-task <tenant> <name>    # run one recurring task now, e.g. intel.run_checks, command.refresh_pulse, command.send_briefs
.venv/bin/ziira verify [tenant] [--unit U] [--fix]   # units' integrity checks; `stock-verify` = Inventory's (nightly)
.venv/bin/python scripts/seed_demo_rich.py [--scale tiny|small|full] [--reset --confirm demo-hardware]   # ~90 days of demo history + 10 planted stories (docs/demo-data.md)
.venv/bin/ziira import <tenant> <kind> FILE.csv [--company NAME] [--commit]   # bring in products, customers, stock...: validates by default (docs/data-import.md)
.venv/bin/ziira backup --dir PATH [--tenant CODE] [--keep-daily 35 --keep-monthly 12]   # pg_dump master + tenants, manifest, pruning
.venv/bin/ziira restore-test --dir PATH [--tenant CODE]   # restore newest dump to a scratch DB, check counts/journal/integrity, drop
.venv/bin/ziira restore --tenant CODE --dir PATH --into NEWDB [--keep-ownership]   # into a NEW database only
python scripts/check_env.py [.env]          # validate a production configuration; python scripts/secret_scan.py
# GET /healthz /readyz /metrics (bearer ZIIRA_METRICS_TOKEN); backups need pg_dump >= server version: see ZIIRA_PG_DUMP_COMMAND in docs/operations.md
```

On this Mac a Homebrew PostgreSQL 14 uses port 5432, so `.env` points everything at Docker on 5433.
`make test` loads `.env`; running pytest directly needs `set -a; . ./.env; set +a` first.
Demo business: login `owner@demo-hardware.test`, password `demo-pass-123` (workspace `demo-hardware`, if asked).
Key settings (`ZIIRA_*`): `MASTER_DATABASE_URL`, `TENANT_SERVER_URL`, `CREDENTIALS_KEY` (encrypts tenant
connection strings; losing it locks out every tenant), `SECRET_KEY` (signs tokens), `ENV`.

- Super Admin (`docs/platform-admin.md`, `docs/licensing.md`): `ZIIRA_DEPLOYMENT_MODE=saas|selfhosted`; plans, prices, subscriptions, invoices and licences are master-DB data (`ziira/kernel/platform/`); operator roles/permissions via `require("platform.x")` on every operator route.
- Platform email and behaviour settings are managed in the Super Admin (`platform.settings`, superadmin only): `kernel/platform/mail.py` (providers described in `kernel/mail_providers.py`, secrets encrypted in master, env fallback), `kernel/platform/behaviour.py` (registration mode, public URLs/links; `GET /api/v1/public/config`). Send platform mail only through `platform_mail.send(to, subject, body, kind)`; never put a secret or a full recipient in the mail log or the operator trail (`docs/platform-admin.md`).
- Website content (`docs/platform-admin-content.md`): the static marketing site (`site/`) takes its editable facts, legal/content pages and plans from the master DB (`kernel/site_*.py`, permission `platform.content`, master tables `site_*`) through an explicit, audited publish and `GET /api/v1/public/site`; a publish POSTs the signed `ZIIRA_SITE_BUILD_HOOK_URL`. Page text is Markdown rendered safely (no raw HTML); the site reads everything through `site/src/lib/siteConfig.ts` and warns loudly in production builds that are not on real published content.
- Entitlements (`platform/entitlements.py`) decide units, limits (`check_limit` in `users`/`organisation`) and access by status (402 `subscription_suspended|subscription_ended|not_in_plan|plan_limit_reached`); never delete data for billing reasons. No subscription row = unmanaged.
- Licences: `ziira licence keygen|issue|install|status|verify|revocations|instance-id`; `ziira billing-run`; `ziira operator create ... --role | reset-password EMAIL | reset-mfa EMAIL`.

## Architecture rules (do not break)

0. **One database per tenant** (decision 0004). The master database (`ziira_master`) lists tenants
   and their encrypted connection strings; business data never goes there. Each tenant database is
   copied from `ziira_template` (kernel only) and gets a unit's tables when the tenant enables it.
   Each tenant has its own login. Code reaches a tenant only through `tenant_session(tenant_id)`.
1. **Kernel + units.** `ziira/kernel` is always on. Modules (`ziira/modules/*`) and plugins
   (`ziira/plugins/*`) are units: installed on the platform, enabled per tenant (tables created in
   that tenant's database), disabled, removed from a tenant, uninstalled.
2. **One PostgreSQL schema per unit** inside each tenant database (`products`, `pos`, ...;
   plugins use `plg_<name>`).
3. **Foreign keys only to the kernel and to units listed in `requires`.** Links to optional units
   are plain UUIDs ("soft references").
4. **Units import only `ziira.sdk`** (never `ziira.kernel`) and other units only via their
   `public.py`. Enforced by `tests/test_architecture.py` and import-linter.
5. **Units communicate by events**: `publish(session, Event(...))` and `@subscribe("type")` in
   `events.py`. Subscribers run inside the publisher's transaction.
6. **Every tenant table** still has `tenant_id` with forced row-level security (second layer). The app
   connects with the tenant's own login (non-owner). Tenant is set per transaction (`app.tenant_id`).
7. **Immutable records:** posted documents are never edited; correct with reversals.
   Stock movements, journal entries/lines and the audit log reject UPDATE/DELETE in the database.
8. **Money is Decimal**, never float (`ziira.sdk.money`).
9. **Every endpoint checks access.** Routes declare `require_permission(...)`; services check scope with
   `current_context().require(perm, company_id=..., branch_id=...)` and filter lists with `companies_with`.
10. **Check ids before saving.** Call `check_company(session, company_id, branch_id)` before saving
   records that name a company or branch, so a wrong id gives a clear error (and foreign keys,
   which ignore row-level security, are never the only check).

11. **Sockets between units:** to block or extend another unit's action use validation hooks and extension
   points (`hooks.py`, `[extends]` in the manifest), not direct calls. See `docs/extending-units.md`.
12. **Web modules mirror units** (`frontend/src/modules/<unit>`); they import only `@/sdk` and other modules'
   `public.ts` (ESLint). Every web page names a permission (or `anySignedIn: true`, e.g. My account). New screens follow the kit and
   patterns in `docs/frontend.md` ("Design system and screen patterns"): tokens not raw colours, `unwrap` on every request, all states designed.
   Menu entries name an `area` (the sidebar has one expandable section per area, pages of the same kind of list share one entry via `under` with a small tab bar; `setup` = last; Settings = grouped list): `docs/frontend.md` "Navigation".

13. **Stock changes only through `inventory/services/ledger.py: post_movement`** (immutable movements, locked
   balances, weighted average cost). Other units publish `sale.posted`, `sale.returned`, `goods.received`
   (payloads in `inventory/services/stock_events.py`); they never write stock tables. Costs are shown only to
   users with `stock.cost`.

14. **Journal entries are made only by Finance's posting engine** (`finance/services/posting.py: post_entry`), from events
   (`stock.moved`, `sale.posted`, `sale.returned`), in the operation's own transaction. Units never write finance tables.
   Which account a line uses is a posting rule (data), not code. Control accounts are never posted by hand.

15. **No country in code.** Currency, phone calling code, tax numbers, statutory deductions (payroll taxes, contributions,
   levies), tax codes and the chart of accounts are *data a business enters*, never constants in code or a default
   that only fits one country. Country-specific services (a payment provider, a tax authority's submission system)
   are providers or plugins behind extension points. Tests may use any country's values as *fixtures*, never as logic.
   Country data comes from **country packs** (plugins `pack_*`, `category = "country"`, data in TOML; `docs/localisation.md`) and each
   vendor is a **provider plugin** (`ziira/plugins/mpesa`); `tests/test_architecture.py` fails on a country or vendor name in
   `ziira/modules` or `ziira/kernel` (known leftovers: its `ALLOWED` table and `docs/plugin-audit.md`).

## Module layout (copy `ziira/modules/products`)

```
manifest.toml      name, version, requires, optional, permissions, events, api_prefix,
                   [roles] (default role grants), [reason_codes] (seeded per tenant)
migrations/        0001_init.up.sql / .down.sql; new changes = new numbered pair, never edit applied ones
hooks.py           sockets offered / plugged into (optional)
api/               routes.py (HTTP only) + schemas.py
services/          one file per use case: validate (domain) → repository → audit_record → publish
domain/            pure business rules, unit-tested, no DB/HTTP
repository/        models.py + <module>_repo.py, this schema only
events.py          @subscribe handlers
public.py          the only file other units may import
tests/             unit tests for domain rules
```

## Conventions

- Type hints everywhere; clear names (`post_stock_adjustment`, not `proc_adj`); docstrings on public functions.
- Every change ships with tests. Domain rules get unit tests (and Hypothesis property tests where invariants matter);
  flows get API/database tests in `tests/` (shared stock setup: `tests/stock_helpers.py`).
- Reason codes required for voids, refunds, discounts above policy, price overrides, stock adjustments.
- Record creator and approver separately; enforce separation of duties where configured.
- Statutory payroll rates live in `people.statutory_rate_table` (effective-dated data), never in code.
- Kernel services for modules (via `ziira.sdk`): `next_document_number`, `check_reason`, `submit_for_approval`
  (+ `@subscribe("approval.decided")`), `@subscribe_after`, `idempotent` / `idempotency_key_header` (retry-safe creates),
  `flag_for_review` (exceptions inbox: anything a person must look at), `@job` / `enqueue` (background jobs with retry and
  backoff, run by `ziira worker`), `store_credential` / `read_credential` (encrypted integration secrets),
  `system_session` (work nobody signed in for, such as a Safaricom callback), `periodic` (recurring tasks, run by the
  worker once per interval per business), `send_notification` / `opt_out_contact` (email and SMS through the
  business's channel; see `docs/notifications.md`). See `docs/adding-a-module.md`.
- **Intelligence and the Command Center**: a unit adds *checks* (`intel.check`), *baseline metrics* (`intel.baseline_metric`) and
  *pulse figures* (`command.pulse_source`) for its own data through extension points, in its own `hooks.py`, with `"intel"`/`"command"`
  under `optional` in its manifest; `intel` and `command` never read another unit's tables. A check never writes, is bounded by a
  look-back window, sets `branch_id` (it decides who sees it), keeps limits as `params` a business can change, and is tested end to
  end with the real engine. Alerts and briefs are queued through the notification layer, never sent in a request. See `docs/intelligence.md`.
- **Intelligence actions (levels 3-4)**: a unit offers an `intel.action` provider (`action_providers.py`) that proposes and executes through its
  own services; approving runs it as the approver (their permissions apply), only `auto_allowed` non-monetary providers may run under an owner's
  rule, and Ziira never moves money, changes prices, credit limits or stock without a person. See "Actions: levels 3 and 4" in `docs/intelligence.md`.
- **UI vocabulary**: the Simple layer of the Intelligence screens (and Home widgets, Settings pages, My account notification card) never shows technical terms (finding, baseline, severity, check code, fingerprint, coverage, entity, connector ...): use the plain words in `docs/intelligence.md` ("Plain words"; single source), in English and Swahili; technical names only behind "Show technical details". Every registered check needs plain text in `ziira/modules/intel/domain/plain_checks.json` (`tests/test_intel_plain.py`); `frontend/src/modules/intel/bannedTerms.json` lists the banned words.
- **AI layer** (`docs/ai.md`): opt-in per business with a consent record; a model writes sentences, never figures (every number must be in the facts or tool results); all calls go through `intel/services/ai.py` (consent, budget, scrub, log) with **no database transaction open** (`@unbound_periodic`, `tenant_transaction`); Ask Ziira data comes only from `intel.ask_tool` tools that filter by the asker's `branch_scope`. AI providers (Anthropic, Gemini, OpenAI plugins; keys, models, default, spend cap and quality check) are managed in the Super Admin (`platform.ai`, `kernel/platform/ai.py`, `docs/ai.md` section 12); provider names live only in plugins and their `models.toml`; request formats are untested live (`scripts/live_check.py ai --provider X`).
- **Moving from a connected system to Core** (`docs/standalone-mode.md`): `connect/services/move.py` proposes records from `connect.src_*`, has the owning units' importers check them, and stages Data Import batches (`imports.public`: `stage_rows`, `check_rows`, `find_existing`, tagged with the connection); it never writes another unit's tables. Core units tell Connectors what they cover through `connect.core_coverage` (`CoreCoverage`), so standalone checks stay silent where Core runs the same area at the same branch (unless the business chose keep-both); findings carry `source` (`connected`/`ziira`).
- **Channels** (`docs/channels.md`): a channel exists only while a provider for it is enabled (`kernel/channels.py`; `GET /notifications/channels/available`); email/SMS come from the `messaging` plugin, WhatsApp only from the `leadsintel` plugin. No platform code (kernel, modules, sdk) names a chat service (`tests/test_channel_registry.py` scans for it): send with `send_templated` (customers) or `notify_user` (staff: own channel per kind, capability e.g. `buttons`, quiet hours defer, fallbacks); a gone channel falls back, nothing is dropped; only a *verified* number is matched to a user (replies run as that user, audit channel `chat`).
- Lead Intel (`ziira/plugins/leadsintel`) is WhatsApp only (no SMS); its template requests are `# UNVERIFIED` (`unverified.py`) and nothing has run against the live service.
- Anything a client may send twice (a sale from a till, a payment prompt) is made safe with a client-made id
  (`local_id`) or an `Idempotency-Key`: the second request returns the first result and changes nothing.
- A business event that already happened (an offline sale) is accepted and its problems are flagged, not refused.
- Daraja (M-Pesa) request formats in `payments/providers.py`, and the SMS formats in
  `plugins/messaging/providers.py`, are written from public documentation and have not been run against the real services:
  test in their sandboxes before any live use.
- A unit that stores data about people (customers, employees, suppliers, payers, recipients) implements `kernel.personal_data` in its
  `hooks.py` (find / export / anonymise; `docs/privacy.md`); retention periods and what must be kept are company settings, never code.
- **Operator console** (`/operator`, `frontend/src/operator`, `kernel/operator_console.py`, `api/operator_unit_routes.py`): platform units install/upgrade/uninstall, per-business unit switches (mandatory reason), health, upgrade-all, operators; same registry functions as the CLI; every change needs a recent confirmation within `ZIIRA_OPERATOR_MFA_MAX_AGE_MINUTES` (the operator's password again, or a fresh code when `ZIIRA_OPERATOR_MFA=totp`) and is logged to `master.operator_action_log` (and the business's audit log); see `docs/security.md`.
- Platform staff are `master.operator`s (first one CLI-made, then by superadmins; sign-in is email + password, with an authenticator code only when `ZIIRA_OPERATOR_MFA=totp`; the default `off` is refused in production unless `ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED=true`; 12-character passwords, short sessions, every sign-in in `master.operator_action_log`, optional `ZIIRA_OPERATOR_ALLOWED_NETWORKS`: `docs/security.md`), never tenant users; they enter a business only through a
  business-made support grant (`ziira/kernel/support.py`), re-checked on every request, and everything they do is logged twice. Do not add other staff back doors.
- Never send a message in the caller's request: queue it. Respect the do-not-contact list (the kernel does).
- **Sign-in security** (`docs/security.md`): wrong passwords are counted and locked out per login/address (`kernel/throttle.py`, 429 with
  `Retry-After`); a second factor (TOTP, backup codes) is compulsory by the business's policy (`kernel.tenant.mfa_policy`; production refuses
  `ZIIRA_MFA_DEFAULT_POLICY=off`) and a person who must use it but has not set it up gets a session limited to the setup calls
  (`MfaSetupRequired`); forgotten passwords use an emailed one-use link; every CSV download is audited. New guessable actions use
  `throttle.action_counters`; never add a sign-in path that skips `auth.sign_in`/`complete_mfa`.
- **Add-ons** (sidebar entry at `/addons`, was Apps & plugins, then Features; display name = key `nav.areas.addons` in `frontend/src/i18n/*.json`, route = `ADDONS_PATH` in `modules/admin/paths.ts`; `units.manage`, Owner): `ziira/kernel/unit_admin.py` + `api/unit_routes.py` enable/disable/remove units per business with the same `Registry` the CLI uses (audited; `remove` needs `confirm` = unit name; manifests carry a `description`); the web page then calls `session.refresh()` so menus update.
- Auth: sign-in with email/phone + password only (no workspace code): the master database's login directory
  (`kernel/directory.py`, keyed hashes of logins -> tenants) says which business database to check; a `workspace` code is
  optional and needed only when the same login (and password) works for several businesses (the reply is `409
  choose_business` with the list). Users are registered in the directory when created; `ziira index-logins` rebuilds it.
  Bearer tokens; API keys (`X-API-Key`).
  Development only: `X-Tenant-ID` (or `ZIIRA_DEV_DEFAULT_TENANT`) acts with every permission; refused in production.
- Manifests carry `category` (groups the Apps page) and, for plugins, optional `countries` (empty = worldwide); an edition only ever switches units on. The web menu, Home checklist and landing page follow the business's edition (`useEdition`, `docs/registration.md`).
- New endpoints are covered by the fuzzer automatically (`tests/test_robustness.py`: add a valid baseline body to its
  `valid_body` if the generic sample cannot pass your rules). Request numbers use `ziira.sdk` `Quantity`, `UnitCost`,
  `Amount`, `Rate`; list endpoints use `page_limit()` / `page_offset()`. See `docs/testing.md`.
- Permission tests sign in as real users (`tests/conftest.py`: `make_tenant`, `sign_in`), never the dev header.

- **Subscription payments** (`docs/subscription-payments.md`): payment providers are plugins implementing `kernel.payment_gateway` (`platform_scope = true`, found at platform level, never switched on by a business); `platform/payments.py` owns attempts, selection and **confirm-before-credit** (never credit from a webhook or the browser alone); nothing in kernel/modules names a provider, currency or country. The worker's `_recover_payments` polls open attempts.

## Where things are

`docs/public-api.md` · `docs/platform-admin-content.md` (website content, publish flow, rebuild hook) · `docs/webhooks.md` · `docs/plugin-review.md` · `docs/security.md` · `docs/channels.md` (channel registry, templates, reply to act, Lead Intel) · `docs/privacy.md` · `docs/performance.md` · `docs/data-import.md` · `docs/operations.md` (deploy, backups/restore test, monitoring, logging, PgBouncer, incidents) · `docs/standalone-mode.md` (Intelligence on a business's existing system: the `connect` unit, connectors, `connect.src_*`; `ziira connect sync|upload`, `create-tenant --mode standalone`) · `docs/intelligence.md` (checks, findings, briefs: how a unit adds a check or figures) · `docs/ai.md` (AI layer, ask tools, providers) · `docs/offline-pos.md` (selling offline) · `docs/registration.md` (how businesses join; **editions**: retail / distribution / books / intelligence / full, data in `ziira/kernel/editions.toml`, `--edition`, `mode` is an alias) · `docs/organisation.md` (companies and branches after registration) · `docs/localisation.md` · `docs/privacy.md` (data subject requests, retention, data map) · `docs/PROGRESS.md` (state, checklist, log) · `docs/testing.md` · `docs/adding-a-module.md` · `docs/writing-a-plugin.md` · `docs/extending-units.md` · `docs/frontend.md` ·
`docs/decisions/0001-0004` · `docs/specs/*.txt` · kernel code map in PROGRESS.md "What exists, and where".

## Working style for this project

- The owner builds mostly with AI assistance; keep code simple to follow and well separated.
- Prefer finishing one module end to end (with tests) over partial work across many.
- Run `make test` before saying something works.

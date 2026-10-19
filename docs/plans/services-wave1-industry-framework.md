# Services wave 1: industry framework, custom fields, Services edition (package 5)

Status: paused by the owner. The package is essentially complete; nothing is half-registered. Not committed.

## Done and tested
* Web area **Services** (`frontend/src/sdk/areas.ts`, `module.ts` AREA_IDS and MENU_GROUPS "services", icon `calendar`, i18n en/sw), edition **services** in `ziira/kernel/editions.toml` (landing `/services/calendar`, 4 checklist steps with en/sw text), `enable_edition` skips units not shipped. Tests: `tests/test_editions.py`, `frontend/src/sdk/*.test.ts`.
* **Custom fields**: kernel migration `0016_custom_fields_packs` (`custom_field_def`, `custom_field_value`, `pack_seed_log`), `ziira/kernel/custom_fields.py`, API `ziira/kernel/api/custom_field_routes.py`, permission `customfields.manage`, privacy provider `kernel.custom_fields`, SDK exports. Tests: `tests/test_custom_fields.py` (43 pass).
* **Industry packs**: `ziira/kernel/industry.py`, `api/industry_routes.py`, `GET /api/v1/industries`, `UnitCard.editions`, registration `business_type` = pack name enables the pack, `ziira apply-packs` covers industry packs, scaffold `ziira plugin new NAME --category industry`, reference pack `ziira/plugins/pack_demo_services`, products seeder (`services/seed_industry.py`, migration products `0005_service_minutes`, `ProductOut.service_minutes`), products entity `products.product`. Tests: `tests/test_industry_packs.py` (16 pass alone).
* Web: `sdk/customFields/*` (CustomFields, CustomFieldsForm, helpers), Settings page `/admin/custom-fields`, Add-ons "Industry" and "Recommended for your edition" badges, wizard question "What kind of service business are you?". Vitest for all of these pass; eslint and tsc clean for my folders.
* Docs: `docs/custom-fields.md`, `docs/industry-packs.md`, updates to registration, adding-a-module, privacy, CLAUDE.md.

## Built but untested
* Fuzzer hint for `POST /custom-fields` added in `tests/test_robustness.py` (fuzzer not run).
* Combined run was clean except items below; last edit renamed test tenants ("Industry ...") to avoid a name clash with `tests/test_country_packs.py` (not re-run after rename).

## Remaining (ordered)
1. Re-run the combined command below; confirm no clash.
2. `tests/test_privacy.py::test_the_socket_...` expects a fixed set of personal-data units: it now fails because bookings, jobs, timebilling, memberships implement it (their owners must add them to the set).
3. After the four modules settle, regenerate API types (`make api-types`); schema names that collide across units (e.g. bookings `SeriesOut`, `SettingsOut`, `CancelIn`) rename existing types to `ziira__...` and broke `NumberingTab.tsx` (`SeriesOut`): the new modules should use unique schema class names.
4. Services area holds more than 8 pages now; `areas.test.ts` allows 12 for services: tidy the menu.
5. Per-unit industry seeders for bookings, jobs, intel (see docs/industry-packs.md "planned"); wave-two packs.
6. Add `<CustomFields>` to unit screens; implement `kernel.custom_field_entity` in bookings/jobs/crm.

## Defined interfaces
Extension points `kernel.custom_field_entity` (`CustomFieldEntity`), `kernel.industry_seeder` (`IndustrySeeder`, `PackData`, `SeedReport`, `SeededItem`); SDK: `custom_fields.{definitions_for,validate_values,read_values,write_values,find_entity_ids,seed_definition}`, `check_pack`. No events.

## Files and migrations
Kernel migration 0016; products migration 0005. New: `ziira/kernel/{custom_fields,industry}.py`, `ziira/kernel/api/{custom_field_routes,industry_routes}.py`, `ziira/plugins/pack_demo_services/`, tests above, frontend `sdk/customFields/`, `modules/admin/pages/{CustomFieldsPage,fields/*}`, i18n `*.fields.json`.

## Shared files touched
`ziira/kernel/{app,cli,editions,editions.toml,manifest(.py,.toml),packs,privacy,registration,unit_admin}`, `kernel/api/{schemas,unit_routes,edition_routes}`, `kernel/plugin_kit/scaffold.py`, `ziira/sdk/__init__.py`, products (hooks, manifest, models, schemas, repo), `CATEGORIES` now includes "industry" and "services", frontend `sdk/{areas,module,icons,index}`, `i18n/{en,sw}.json`, `shell/Register.tsx` and register steps, admin `module.ts`, AppsPage, `frontend/src/api/schema.d.ts` (regenerated).

## Resume commands
```
set -a; . ./.env; set +a
caffeinate -dimsu .venv/bin/pytest tests/test_custom_fields.py tests/test_industry_packs.py tests/test_editions.py tests/test_privacy.py tests/test_plugin_kit.py tests/test_architecture.py -q
.venv/bin/ruff check ziira tests; .venv/bin/mypy ziira; .venv/bin/lint-imports
cd frontend && npx tsc -b --noEmit && npx eslint src && npx vitest run src/sdk src/shell src/modules/admin
```

# Industry packs

An **industry pack** is a plugin (`category = "industry"`) that brings the data a kind of business starts with: its services, job statuses,
checklists, message templates, custom fields, check settings. It has no tables and no logic of its own. It is the sibling of the country packs
(`docs/localisation.md`): a country pack carries what a *country* needs, an industry pack what a *kind of business* needs. Both are data a
business can edit afterwards.

When a pack is switched on (at sign-up for the Services edition, or later in Add-ons), each unit that implements the extension point
`kernel.industry_seeder` copies the pack's data for that unit into its own tables, for each company. The promise is the same as the country packs':
**idempotent** (running it again adds nothing), **non-destructive** (it only adds what is missing; a row the business has changed, hidden or
removed on purpose is never overwritten or brought back), and it never touches a posted record.

## Writing a pack

```bash
ziira plugin new pack_yourname --category industry     # a skeleton: manifest, data files, a test, README
ziira plugin check ziira/plugins/pack_yourname          # static checks (also run by CI)
ziira plugin test ziira/plugins/pack_yourname
ziira apply-packs [tenant]                              # seed switched-on packs again (country and industry packs)
```

`ziira/plugins/pack_demo_services` is the smallest working example (three service items and one custom field).

```
pack_yourname/
  manifest.toml            category = "industry", requires = ["products"], optional = [units the pack can feed if present]
  data/pack.toml           [pack] units = [...], editions = ["services"]
  data/products.toml       one file per unit that has something to seed (the file name is the unit's name)
  data/custom_fields.toml  read by the kernel
  migrations/0001_init.*   only the empty plg_<name> schema (every plugin has one)
  tests/test_pack.py       check_pack("pack_yourname") == []
```

* `manifest.toml`: `title` is what the sign-up question and Add-ons show ("Salon or spa"), `description` is the one-sentence summary. `requires` is what the
  pack cannot work without (its first item is usually `products`); units it can use when present go in `optional`.
* `data/pack.toml` `[pack]`: `units` lists the units the pack feeds (each must be in `requires` or `optional`; every `data/<unit>.toml` must be listed here);
  `editions` lists the editions it is **recommended for** (Add-ons shows the badge "Recommended for your edition"). A pack with an empty list is never recommended
  but can still be switched on.
* `check_pack(name)` (in `ziira.sdk`) returns plain-word problems: a missing or invalid `pack.toml`, an unknown unit or edition, a data file for a unit not listed,
  a unit missing from `requires`/`optional`, a file that is not valid TOML. The framework runs the same checks; keep it in the pack's test.
* **No country in a pack.** Prices, currency, tax codes and statutory figures are money and law the business sets; a pack gives services and durations, not prices.
  Names and labels are plain words (English; the business can edit them).

## What each unit accepts

Each unit's seeder reads its own file. Units add their part when they are built; today:

| Unit | File | Accepts |
|---|---|---|
| `products` | `data/products.toml` | `uom` and `tax_code` (optional codes to use), `[[service]]` tables: `sku`, `name`, `minutes` (usual duration, 1 to 1440). Creates `service` products without a price; if the business has no unit of measure or tax code yet nothing is added (and the report says so). A SKU the business already has is skipped. Switching the pack off can hide the untouched ones. |
| kernel | `data/custom_fields.toml` | `[[field]]` tables: `entity_type`, `key`, `label`, `kind` (`text`, `number`, `date`, `bool`, `choice`), and optionally `choices`, `required`, `searchable`. A field for a record type whose unit is off is skipped until `ziira apply-packs` runs with it on. A key the business already has is left alone. |
| `products` (catalogue) | `data/products.toml` | `[[category]]` (`name`), `[[unit]]` (`code`, `name`; a unit the business has is left alone), `[[product]]` (`sku`, `name`, `category`, `unit` = base unit code, `batch_tracked`, `reorder_level`, `pack_units = [{unit, factor}]`, `fields = {custom field values}`): example stock products without prices (see `seed_catalogue.py`). Example: `ziira/plugins/pack_pharmacy`. |
| `purchasing` | `data/purchasing.toml` | `[[supplier]]` templates: `code`, `name`, `payment_terms_days`. Switching the pack off puts untouched ones on hold. |
| `intel` | `data/intel.toml` | `[check."code"]` tables of limits for checks the business has not tuned. |
| kernel | `data/checklist.toml` | `[[step]]` tables (`id`, `title`, `hint`, `to`, optional `unit`): first steps shown on Home after the edition's own (ids are prefixed with the pack's name). |
| `memberships` | `data/memberships.toml` | `[settings]` (policies, written only if the company never saved any), `[waiver]` (terms, only if none), `[[plan]]` (fee is an example, marked `is_example`; `service_sku` links the service item), `[[package]]`, `[intel."check.code"]` (limits). A code the business has is skipped. Example: `ziira/plugins/pack_fitness` (gym) and `pack_education` (term fee plans). |
| `bookings` | `data/bookings.toml` | `[settings]` (applied once), `[[resource]]` templates with hours, `[[service]]` offers (linked to the Products items by `sku`, prices are examples), `[[variant]]` prices by staff level, `[[commission]]` rules, `[[step]]` first-run checklist, `[intel."code"]` check limits; see the header of `ziira/modules/bookings/services/seed_industry.py` and `docs/pack_salon.md` |
| `jobs` *(planned)* | `data/jobs.toml` | status workflow rows (statuses and allowed moves), intake checklists |
| others | | A unit that wants pack data implements `kernel.industry_seeder` (below) and documents its file here. |

## Writing a seeder (for a unit)

```python
@provides(INDUSTRY_SEEDER)
class JobsIndustrySeeder(IndustrySeeder):
    name = "jobs.statuses"      # identifies the seeder in the log
    unit = "jobs"               # the data file: data/jobs.toml

    def seed(self, session, pack: PackData, company_id) -> SeedReport:
        data = pack.unit_data(self.unit)          # {} when the pack has no such file
        report = SeedReport()
        ...                                       # for each row not already there: create it, then
        report.added.append(SeededItem("job_status", row.id, "Diagnosing"))
        ...                                       # for each one already there: report.skipped += 1
        return report

    def untouched(self, session, item_type, item_id) -> bool: ...   # optional: still as the pack made it and unused?
    def remove(self, session, item_type, item_id) -> None: ...      # optional: what "remove untouched" does (hide, or delete)
```

Declare `kernel.industry_seeder` under `[extends] implements`. A seeder must be idempotent, add only what is missing, use the unit's own services or
repository (never another unit's tables), and run with the system context (all permissions) inside the caller's transaction. Report every row you add: the kernel
writes them to `kernel.pack_seed_log` (pack, seeder, item type, item id, label). A seeder that does not implement `untouched` is never offered for removal.

## Switching a pack off

Switching a pack off keeps everything it seeded (like every unit). `GET /api/v1/industry/packs/{pack}/seeded` lists what the pack added and which of it is
**untouched**; `POST .../remove-untouched` removes (or, for products, hides) exactly those rows. What the business changed, priced or used stays. Both need
`units.manage` and the second is audited.

## When seeding runs

* when an industry pack is switched on (at registration, from Add-ons, or by an edition switch), for every company;
* when a unit that has a seeder is switched on while a pack is already on;
* on `ziira apply-packs` (all businesses, or one).

A failure is logged and does not stop the switch-on; `ziira apply-packs` runs it again. At registration, the optional "pack" step is retried by the worker.

## Registration

A pack recommended for the shop editions (`editions = ["retail"]`, e.g. `pack_pharmacy`) is offered after the usual four kinds in the sign-up's business step for Retail and
Distribution. With the `services` edition the sign-up wizard asks "What kind of service business are you?"; the choices are the installed industry packs (`GET /api/v1/industries`)
plus "Something else", and the chosen pack is switched on after the business is created (`docs/registration.md`).

## Not done yet

The per-unit parts marked *planned* above, an "Industry" filter on Add-ons (packs share the flat grid with a badge), sample-data recipes, and menu label overrides.

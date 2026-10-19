# Shared design: service businesses on Ziira (PAUSED 2026-10-18; resume from the status files docs/plans/services-wave1-*.md)

Owner request (binding): "add service business plugins and modules, a super structure that is plug and play."
Service businesses = salons and spas, barbers, clinics and dental practices (appointments and billing only: NO clinical
records), garages and repair shops, tailors, cleaners, agencies, consultants, accountants, lawyers, photographers, gyms,
trainers, schools and tutors. Ziira today is strong on goods (till, stock, purchasing), books, people, payments and
Intelligence. This work adds the service side. Read first: CLAUDE.md (architecture rules 0-15: units import only
`ziira.sdk` and other units' `public.py`; foreign keys only to kernel and `requires`; events; RLS on every table; money is
Decimal; no country in code), docs/adding-a-module.md, docs/extending-units.md, docs/writing-a-plugin.md,
docs/intelligence.md (checks, baselines, pulse), docs/localisation.md, docs/frontend.md (design system, navigation: a
sidebar of areas with pages; merged tab pages only for near-duplicate lists), docs/privacy.md (personal data provider),
docs/registration.md (editions), ziira/kernel/editions.toml, and a module that is a good model (`ziira/modules/purchasing`
or `crm`).

## The four modules (each its own unit, schema, migrations, API, web module, tests) and one framework
1. **bookings** (schema `bookings`): resources (staff, chair, room, equipment) with working hours and time off;
   *service offers* (a bookable service: duration, buffer before/after, price, which resources can do it) linked by a
   soft reference to a `products` service item (`product_type = service`); appointments with a lifecycle
   `requested -> confirmed -> checked_in -> in_service -> completed`, plus `cancelled` and `no_show`; availability engine
   (pure domain code, property-tested: no overlaps for one resource, respects hours, time off, buffers, minimum notice);
   a database exclusion constraint (`tstzrange` with gist, per resource, ignoring cancelled) so double booking is impossible
   even under concurrency; waitlist; recurring appointments; calendar screens (day and week, by resource), a
   reception/front-desk view; reminders through the notification layer (templates, preferred channel, quiet hours: queue,
   never send in the request); a public booking page (`GET/POST /api/v1/public/book/<business-slug>`: tenant resolved by
   a per-business slug setting, only services and free slots are exposed, rate limited, honeypot, no personal data
   leaked, consent text, customer matched or created through `crm.public`); on completion publish an event so billing can
   follow (see invoicing).
2. **jobs** (schema `jobs`): work orders for repairs and projects (garage, tailor, appliance repair, installation):
   customer, *asset* (a vehicle, device or item with free identifiers: plate, serial, IMEI), intake checklist and
   condition notes, status workflow as DATA per business (defaults: received, diagnosing, quoted, approved, in progress,
   waiting for parts, ready, collected, closed; statuses and allowed moves are rows, so industry packs can ship their own),
   tasks with an assignee, parts used (stock issued through `inventory.public` only: never write stock tables), labour
   lines (hours x rate), estimate/quote and customer approval, invoice from the job, warranty/return-visit link, job board
   (kanban by status) and list views, attachments are NOT part of v1 unless the kernel already offers them.
3. **timebilling** (schema `timebilling`): clients and projects (budget in hours or money, status), rate cards (by person,
   role, service, client, with effective dates), timesheet entries (hours, date, project, task, note, billable flag),
   weekly submit and approval (separation of duties: the approver is not the author), billable but not yet invoiced
   ('unbilled work', WIP) view, **invoice from approved time and expenses** (grouped by project, person or task),
   retainers (prepaid hours or a fixed monthly fee, drawdown), project profitability (billed against cost using payroll
   rates only if the people unit exposes them through `public.py`: otherwise cost rate on the person's rate card),
   timers (start/stop in the web app).
4. **memberships** (schema `memberships`): membership plans (monthly fee, visits included, discounts), session packages
   ('10 massages', expiry), prepaid balances and credits consumed by appointments or job/time lines, freezes and
   cancellations, and **recurring invoices** for any customer (schedule, next run date, auto-issue through the invoice
   function, pause, end date). A periodic task issues due invoices (idempotent per schedule and period).
5. **Industry framework + custom fields + the Services edition** (kernel/sdk and plugins; owned by one agent):
   - `category = "industry"` plugins (**industry packs**) are DATA: when switched on for a business they seed, through the
     extension point `kernel.industry_seeder` implemented by each unit (the same idea as the country packs and
     `kernel.country_seeder`): the service catalogue (as `products` service items with duration hints), resource
     templates, job statuses, checklists, reminder message templates, custom fields, Intelligence check settings, menu
     labels, the edition's onboarding checklist and an optional sample-data recipe. Idempotent, non-destructive, editable
     afterwards. A pack declares which units it needs; the Add-ons page shows packs in the flat grid with a badge.
   - **Custom fields** (kernel service in `ziira.sdk`): a business or a pack defines fields per record type (appointment,
     work order, asset, customer, project...): text, number, date, yes/no, choice list, required, searchable. Values in a
     kernel table keyed by (entity type, entity id), tenant-scoped with RLS; units expose the record types through an
     extension point `kernel.custom_field_entity`; web: a shared `CustomFields` form component and a Settings page to
     manage definitions. Never used for money or for stock.
   - **Edition `services`** in `ziira/kernel/editions.toml` (units: products, crm, pos, payments, finance, people, imports,
     intel, command, bookings, jobs, timebilling, memberships) with landing page, sidebar order, checklist, plus the web
     sidebar area **Services** (pages: Calendar, Appointments, Jobs, Time and projects, Memberships and packages) in
     `frontend/src/sdk/areas.ts`.
   - Packs (wave two, after the modules exist): `pack_salon` (salons, spas, barbers), `pack_garage` (garages and repair
     shops), `pack_professional` (consultants, agencies, accountants, lawyers), `pack_clinic` (clinics and dental:
     appointments, recalls, packages: NO clinical or medical records), `pack_fitness` (gyms, trainers), `pack_education`
     (tutors, schools: classes as recurring appointments, term fees as recurring invoices).

## Rules every service module follows
- Units talk through `public.py`, events and extension points. **Invoices are made only by the POS unit's invoice
  service** (customer credit invoices; see `ziira/modules/pos`): services never write pos tables. If `pos/public.py` has no
  function to issue an invoice from plain lines, the **timebilling agent adds** `issue_invoice_from_lines(session, *,
  company_id, branch_id, customer_id, lines, source_type, source_id, due_days=None, memo=None)` returning a small
  `InvoiceRef` (id, number, total) as its first change (within the first minutes, tested, additive, idempotent by
  (source_type, source_id)); every other agent calls it and builds its invoicing step last, re-reading `pos/public.py`
  until it exists. Stock only through `inventory.public`. Customers and consent through `crm.public`. Staff through
  `people.public` when needed, else `kernel` users. Payments and deposits through `payments.public` (v1: record a deposit
  as a customer payment on account; no gateway work).
- Every table has `tenant_id` and forced RLS; every endpoint `require_permission`; scope checks with `current_context()`
  and `check_company`; permissions declared in the manifest with default role grants (Owner all; Branch Manager their
  branch; Receptionist/Front desk new role data if the role model allows, else Sales Rep); audit; idempotency keys for
  anything a client may send twice (public booking, timers, timesheet submit).
- **Personal data**: each module implements `kernel.personal_data` (find, export, anonymise) for client names, phones,
  notes; retention settings are company settings, never code.
- **Intelligence and Command Center**: each module supplies its own checks (`intel.check`), baselines and pulse figures in
  its `hooks.py` with `intel`/`command` under `optional`: bookings (no-show rate by resource, late cancellations,
  utilisation far below normal, double-booking attempts refused, long idle gaps, appointments completed but never
  invoiced), jobs (jobs stuck in a status too long, estimate not approved after N days, parts used but job never
  invoiced, repeat returns within warranty, ready-for-collection not collected), timebilling (unbilled time ageing, project
  over budget, timesheets not submitted, retainer nearly used up, billable ratio drop), memberships (memberships
  expiring, unused packages about to expire, failed recurring invoice runs, revenue at risk). Checks follow the rules in
  docs/intelligence.md (bounded look-back, branch scope, params as data, plain text fields `plain_title`,
  `why_it_matters`, `what_to_do`, `value_kind`; plain English and Swahili strings in the plain-language catalogue as the
  other units do: look at `ziira/modules/intel/domain/plain_checks.json` and add entries for your checks).
- **Web**: module in `frontend/src/modules/<unit>` (imports only `@/sdk` and other modules' `public.ts`), pages placed in
  the **Services** sidebar area through the registry (`area: "services"`), designed states (loading, empty with a next
  action, error with retry), forms with validation, English and Swahili with key parity (plain business words: no jargon),
  responsive, accessible, `unwrap` on every request; regenerate API types last. A calendar component is shared: the
  bookings agent builds `Calendar` in its own module and exports it from `public.ts`.
- **Tests**: hand-calculated domain tests (+ Hypothesis where invariants matter: no overlap, no negative balances, totals),
  API tests with real sign-ins and permission matrices (`tests/conftest.py` helpers), tenant isolation, concurrency
  (two bookings for one slot: one wins), idempotency, events, privacy provider, Intelligence checks end to end with the
  real engine (flagged, silent, tuned, auto-resolve), architecture. Add fuzzer valid-body hints for new endpoints in
  `tests/test_robustness.py` but do NOT run the fuzzer.
- **Docs**: `docs/<unit>.md` (what it is, the data model in plain words, lifecycle, events, extension points, Intelligence
  checks, how a pack customises it), a short entry in `docs/PROGRESS.md` is NOT yours (the lead does it), CLAUDE.md only for
  a changed convention (one line each).
- **No country in code.** Currency, tax and phone formats are data.
- **Speed rule**: run ONLY your own tests plus `tests/test_architecture.py` (the pytest lock serialises sessions; no fuzzer,
  no full suite, no e2e), ruff, mypy, lint-imports, eslint/tsc/vitest on your touched folders. Other agents edit shared
  files (`ziira/kernel/editions.toml`, `frontend/src/sdk/areas.ts`, `frontend/src/modules/index.ts`,
  `frontend/src/api/schema.d.ts`, manifests of other units): re-read right before each edit, keep edits additive, never
  revert theirs, take the next free migration number right before creating a migration. Regenerate API types last. Do not
  commit or push. Report briefly: what is done, what is cut, design doubts, public functions/events/extension points other
  agents or packs rely on.

# Jobs and Repairs

Work orders for businesses that take an item in, fix or build something and hand it back: garages, tailors, phone and appliance
repair, plumbing and electrical call-outs, installers. The unit is `jobs` (schema `jobs`, API `/api/v1/jobs`, web module
`frontend/src/modules/jobs`, sidebar area **Services**). It requires `products`; `crm` (customers), `inventory` (stock for parts), `pos`
(invoices), `finance`, `intel` and `command` are optional.

## The data, in plain words

| Thing | What it is |
|---|---|
| **Job** (work order) | One piece of work: customer, the item, what is wrong, who is in charge, a promised date. Numbered `JOB-<branch>-000001` from the kernel number series. |
| **Item** (asset) | A vehicle, phone, garment or place the customer brings. Free identifiers (plate, serial, IMEI, size, address); many jobs can point at one item, and the item page lists them all. |
| **Stage** (`job_status`) | A step a job moves through. Per company, editable. Each has a *kind* (open, waiting, done, closed) and may hold one *role* (below). |
| **Move** (`job_status_move`) | A move that is allowed from one stage to another. The server refuses any other. |
| **Checklist** | Lines checked at intake ("fuel level noted"). A template (`checklist_template`, data) is **copied** into the job when it is made; changing the template later does not change old jobs. |
| **Task** | A piece of work on the job with a person and a due date. |
| **Part** | Stock issued from the branch store (cost from the ledger) or something bought in and priced by hand. |
| **Labour line** | Hours x rate. The rate is the company's labour rate unless given; `source` says where it came from (`manual` now, `timer` from Time and Billing later). |
| **Estimate** | A priced list of parts and labour with a version number. Draft, sent, approved, declined or superseded. |
| **Timeline** (`job_event`) | Every status change, note, approval, invoice and collection. |

Prices include tax, as everywhere in Ziira's selling screens. A line is worth quantity x price to the cent and the tax inside it is
`total x rate / (100 + rate)`, rounded per line, exactly as the invoice does it, so the job's totals equal the invoice's.

## Stages as data

The default stages are `received`, `diagnosing`, `quoted`, `approved`, `in_progress`, `waiting_for_parts`, `ready`, `collected`, `closed`
and `cancelled`, seeded the first time anything needs them (`jobs/domain/workflow.py: DEFAULT`). A business changes them in
**Job settings > Stages**; an industry pack can ship its own.

The platform itself acts on a few **roles**. A role is held by at most one stage per company, whatever it is called:

| Role | Meaning |
|---|---|
| `initial` | where a new job starts (cannot be switched off) |
| `quoted` | sending an estimate moves the job here (when the move is allowed) |
| `approved` | an approved estimate moves the job here (when allowed; the approval is recorded either way) |
| `ready` | entering it tells the customer ("your item is ready") |
| `collected` | entering it records who collected, starts the warranty |
| `closed`, `cancelled` | the job is over (kind `closed`); a cancelled job cannot be invoiced |

Stage *kinds* drive the screens and checks: `open` and `waiting` jobs are live (the board, "stuck" and "late"), `done` is finished but
not over, `closed` is over and locked.

## Lifecycle

```
receive -> (diagnose) -> estimate -> customer approves -> work (parts, labour, tasks) -> ready -> collect -> invoice -> close
```

- **Receive an item** (`POST /jobs`): customer (a CRM record, or a name and phone for a walk-in), the item (existing or new, inline),
  a checklist, a promised date, a person in charge. Safe to retry with an `Idempotency-Key`.
- **Parts.** A stock product is issued through `inventory.public.issue_stock_to_job` (one `job_issue` movement; never a write to stock
  tables). The cost shown comes from the ledger's average cost, and only people with `stock.cost` see it. Removing a part puts the stock
  back at the cost it left at (`return_stock_from_job`, a `job_return` movement). Finance books both as cost of goods sold against
  inventory. A product that holds no stock (a service) and a part with no product take no stock and need a price. A cancelled job does
  **not** return its parts by itself: remove them first if they went back on the shelf.
- **Estimates.** `from_job` copies the parts and labour so far. Only a draft is edited; a sent estimate is revised by making the next
  version, and sending a new version replaces the older ones. **Sending** returns a link path (`/job-approval/<secret>`) once; only a hash
  is stored. `tell_customer` also queues the link as the `job_estimate` message.
- **The customer's answer.** Staff can record it on the customer's behalf (approve or decline, with a note and the customer's name).
  The customer can use the link: `GET/POST /api/v1/jobs/public/job-approval/{token}` (no sign-in; the token is `<business id>.<secret>`).
  It shows only the estimate (business, item, lines, totals; no customer details, no costs), answers once, refuses an expired one, is
  rate limited per link and per address (`sdk.rate_limit`), and answers a wrong link like one that never existed (404).
- **Collection** (`POST /jobs/{id}/collect`): moves to the `collected` stage, notes who collected and sets `warranty_ends` = collection
  day + `warranty_days` (default from the company's job settings, changeable per job, also after invoicing).
- **Return visit** (`POST /jobs/{id}/return-visit`): a new job for the same customer and item, `is_rework`, pointing at the original;
  `rework_in_warranty` records whether the warranty was still running. Allowed on an invoiced job.
- **Invoice** (`POST /jobs/{id}/invoice`): uses `pos.public.issue_invoice_from_lines` (idempotent by source `job` + job id). Stock parts are
  already out of stock, so invoicing them under their own product would take them out again: every stock or hand-priced part is
  invoiced under the **Parts item** of the company's job settings and labour under the **Labour item** (both service items), and **those
  items' tax codes are the job's tax**. A service product used as a part is invoiced under its own product. After invoicing the job is
  **locked**: no new parts, labour, tasks, estimates or edits; only notes, the warranty days, return visits and collection (and status
  moves) work. The caller needs `jobs.invoice` and POS's `invoices.manage` at the branch.
- **Ready message.** Entering the `ready` stage queues the `job_ready` template (English and Swahili, `kernel/message_templates.json`)
  through the notification layer to the customer's phone (the company's reminder channel when set up, else SMS, else email). Never sent in the
  request; the do-not-contact list is respected; a job note says so when the customer cannot be reached. Switch it off in the job settings.

## Workshop features (garages, body shops, repair shops, tailors)

See `docs/pack_garage.md` for the data a garage starts with. Everything below is data or a business setting.

- **Intake.** A job keeps the kind of job (`job_type`, data: checklist, warranty, photos needed), odometer in and out, fuel level, key tag,
  belongings and who signed for the drop-off. The odometer updates the item's last reading (a lower reading is kept on the visit with a note).
  The intake screen shows the item's previous visits with what was done (`GET /assets/{id}/visits`). An item has a **next service** (date and/or
  reading); `GET /service-due` lists what is near; a periodic task (`jobs.service_reminders`) queues the `job_service_due` message once per due date
  when the business switched reminders on.
- **Walk-ins.** A job needs a customer name (or record), not a record. Invoicing a job with no record matches or makes a customer from its
  phone, else uses the shop's catch-all customer (code `WALKIN`). A stranger has no credit, so pay at the same step: `POST /jobs/{id}/invoice`
  with `{"pay_method": "cash"}` invoices and records the payment together.
- **Estimates.** An estimate has a validity date. A staff member can record the answer, or the customer answers on the link (which also shows the
  photos the business made shareable and each part's class). **Additional work** (`kind: additional`) lists only what was added after the latest
  approval and is approved separately; it does not replace the approved estimate. The job tracks `approved total` against the live total; what is
  above it is *unapproved work*: business setting `unapproved_work` = off, warn (a note on the timeline and a banner) or block (409 until an
  additional estimate is approved). A job nobody quoted is never checked; for an insurer job the claim's authorised amount and rule decide.
- **Labour.** Work types carry an hourly rate; the **task library** holds standard times and an optional fixed price. A labour line has `hours` (billed)
  and `booked_hours` (really worked); `GET /reports/technicians` compares them per person (people without invoice/settings rights see only
  themselves). A fixed-price task is one invoice line.
- **Parts.** Each part may be genuine, aftermarket or used; a category prices it from its cost (`cost x (1 + markup%) x (1 + tax%)`, tax-inclusive like
  every price here). Sources: from stock, bought in, **ordered for this job** (`order_status` to_order, ordered, arrived; linked to a purchase order
  by number; `goods.received` marks non-stock parts arrived, a stock part is taken from the store when staff press Arrived; the invoice refuses
  while one has not arrived) and the **customer's own part** (listed, never invoiced). `return` puts some of a part back (stock goes back at the cost it
  left at).
- **Charges.** Towing, courtesy car, storage and other fees (`job_charge`) are invoiced under the Fees item (else the Labour item). **Storage**: a
  per-day fee after free days from the ready date, added as a charge on request or automatically at invoicing; it can be waived.
- **Deposit.** `POST /jobs/{id}/deposit` records a customer payment on account through Payments and keeps the total on the job (a tailor's advance).
- **Release on payment.** Setting `release_unpaid` = off, warn (collect needs `acknowledge_unpaid`, noted on the timeline) or block. A customer on
  credit terms is released without a warning. For an insurer job the customer's share (excess) is what must be settled.
- **Bays.** `bay` and `bay_booking` (a database exclusion rule: a bay holds one job at a time); `GET /bay-board`.
- **Courtesy cars.** An item of kind `courtesy-car` is lent on a `loan` (out and in dates, readings, fuel); one loan at a time per car.
- **Technician and floor views.** `waiting_on` (parts, approval, insurer) on lists and the board; the Workshop screen has my jobs, bay board,
  technicians, service due and cars out. Waiting on the insurer comes from Claims.
- **Photos.** A job and an item accept photos through the files service (`docs/files.md`; entity types `jobs.job` and `jobs.asset`). The kinds
  are data (`photo_category`, else a usual list). A job type can require photos before a stage (`required_photos`: category, how many, the stage
  role); the setting `required_photos` decides whether moving on without them is allowed, noted or refused. Shareable photos appear on the customer's
  approval page; using the link ends its photo addresses.
- **Insurer and fleet jobs.** A job can have a claim (`docs/claims.md`). Jobs reads it only through `claims.public` (`services/claims_link.py`):
  the claim's lines (approved, countered, rejected, waiting) show on the job; the payer's labour rate per work type and parts discount price labour and
  parts that have no typed price; a person without `jobs.estimate` or `jobs.invoice` sees only the authorised work, without prices; the claim's
  estimate is drafted from the job's parts and labour; the completion sign-off and the invoicing (payer invoice less the excess, customer invoice) run
  through Claims, so a job with a claim is invoiced there (`job.invoiced_at` set, `invoice_id` empty, the number reads "INV-1 (payer) / INV-2
  (customer)"). Events from Claims put notes on the timeline, move the job to *Waiting for insurer* when the estimate is sent and to *Approved* when work is
  authorised. A fleet customer on credit is a payer of kind `fleet`.
- **Comebacks and warranty.** Return visits link to the original (unchanged); the item page and the intake history show them.

Extra permissions: none; extra settings: `odometer_unit`, `unapproved_work`, `release_unpaid`, `required_photos`, `fees_product_id`, `storage_fee_per_day`,
`storage_grace_days`, `remind_service_due`, `service_reminder_days`, `ready_reminder_days`.

Extra events consumed: `goods.received`, `claim.*`. Extra Intelligence checks: `jobs.part_overdue`, `jobs.courtesy_car_overdue`. New messages:
`job_extra_work`, `job_service_due`, `job_pickup_reminder`.

## Permissions

| Permission | Allows |
|---|---|
| `jobs.view` | see jobs, items, the board |
| `jobs.manage` | take items in, edit jobs, move stages, checklist, tasks, labour, notes, collect, return visits |
| `jobs.parts` | use stock or hand-priced parts |
| `jobs.estimate` | make, send and record answers to estimates |
| `jobs.invoice` | invoice a job |
| `jobs.settings` | stages, moves, checklists, rates, service items |

Default roles: Branch Manager (all but settings), Finance Manager (view, invoice, settings), Sales Rep (view, manage, estimate),
Storekeeper (view, parts), Cashier (view, manage), Accountant (view, invoice). There is no technician role in the fixed role set: a business
makes one in Settings and ticks the permissions. Scope follows the usual rules (company and branch); jobs belong to a branch.

## Events

`job.received`, `job.status_changed` (with `to_role`), `job.estimate_approved`, `job.estimate_declined`, `job.collected`, `job.invoiced`.
Payloads carry ids and the number, never personal data.

## Public functions and extension points other units use

- `jobs.public.seed_statuses(session, company_id, definition)` and `parse_definition(data)`: add stages and moves a company does not have;
  never changes or removes anything; running it again does nothing. `seed_checklist(...)`, `find_job(...)`.
- `jobs.public.add_labour_line(session, job_id, hours=..., description=..., source=..., source_id=...)`: time worked from another unit
  (Time and Billing timers); idempotent by (`source`, `source_id`).
- `inventory.public.issue_stock_to_job` / `return_stock_from_job` (added for this unit; movement kinds `job_issue` and `job_return`, with
  the finance recipe `Dr cost of goods sold / Cr inventory`).
- **Industry packs** feed Jobs through `kernel.industry_seeder` (`JobsSeeder` in `hooks.py`, data file `data/jobs.toml`):

  ```toml
  [settings]                      # only applied while still unset
  default_labour_rate = 1500
  default_warranty_days = 30

  [[status]]
  code = "awaiting_customer"
  name = "Awaiting customer"
  kind = "waiting"                # open | waiting | done | closed
  # role = "ready"                # optional; ignored when another stage already holds it

  [[move]]
  from = "diagnosing"
  to = "awaiting_customer"

  [[checklist]]
  name = "Appliance intake"
  asset_kind = "appliance"
  items = ["Power cord", "Model plate read"]
  ```
  Statuses and checklists the pack added and nobody used or edited can be removed when the pack is switched off.
- **Custom fields:** the entity types `jobs.work_order` and `jobs.asset` (`kernel.custom_field_entity`); values live in the kernel
  tables and are read and saved through `/api/v1/custom-fields`.
- Personal data (`kernel.personal_data`): finds jobs by the customer's phone or name, exports the job, notes and checklist, and on
  erasure replaces the customer name and phone and empties notes. A job still open is refused (the item must be returned).
- Integrity check `job invoices` (`ziira verify`): an invoiced job must have its invoice in POS.

## Intelligence and the Command Center

Checks (all in `intel_checks.py`, limits are parameters a business changes; plain English and Swahili texts in
`intel/domain/plain_checks.json`): `jobs.stuck_in_stage` (open jobs 7 days, waiting 14, urgent 30), `jobs.estimate_not_approved` (5 days),
`jobs.parts_not_invoiced` (collected or closed 2 days ago with parts and labour but no invoice, looking back 90 days),
`jobs.repeat_returns` (3 in-warranty return visits traced to one person's work in 90 days), `jobs.ready_not_collected` (7 days, urgent
30). Every finding carries the job's branch. Pulse figures: `jobs.open`, `jobs.late`, `jobs.ready_for_collection`,
`jobs.awaiting_approval`, `jobs.received_today` (company and per branch).

## What is not done / untested

- No technician timers on the job screen (Time and Billing adds time through `add_labour_line`; a `timer` line counts as booked).
- A deposit is a payment on the customer's account; it is not allocated to the invoice by Jobs (release-on-payment treats a covering advance as paid).
- Storage that accrues after invoicing and before collection is not added to the invoice.
- The customer's approval page is a web page at `/job-approval/<secret>`; the link is built from `ZIIRA_PUBLIC_BASE_URL`.
- WhatsApp-style channels need template approval before the first message (the notification layer falls back to SMS or email).
- Nothing was run against a real message channel, insurer or purchasing flow other than in the tests and a local browser walk.

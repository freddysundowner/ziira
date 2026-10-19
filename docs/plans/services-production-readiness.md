# Service businesses: production readiness (wave 2)

Owner request (binding): "think about those industries and how they operate and make it production ready ... super ready to go to
production for those businesses." Then: photos in garages are NOT out of scope; garages that deal with **insurers** (jobs, parts,
requests, insurer rejects / accepts / counters) must work; **gyms robust and ready to use**; "review everything again and make
everything needed in those businesses be in."

Status: PLAN, for the owner to read and correct before anything is built.

Read first (agents): `docs/plans/services-shared-design.md` (rules, binding), `docs/bookings.md`, `docs/jobs.md`,
`docs/memberships.md`, `docs/industry-packs.md`, `docs/custom-fields.md`, `docs/plans/services-wave1-*.md`, CLAUDE.md.

## What "production ready" means here
A real owner signs up, picks the kind of business, and **on day one** has: a sensible service list and prices to edit, staff or
rooms to name, working hours, reminder wording, job statuses or checklists, the right custom fields, Intelligence checks tuned, and a
short first-run checklist. Then a normal working day runs with no workaround. Nothing exaggerated: no marketing pages, no feature for
its own sake, plain words, few clicks. Reception and workshop staff are busy and not technical: tablet and phone friendly, large tap
targets, keyboard speed, fast (a check-in or a booking in under a second on a modest server).

## New shared building blocks (built first, used by several businesses)

### E. Files and photos (kernel service, `ziira.sdk`): NOT out of scope any more
The kernel has no file storage today. Build it once, properly:
- Private per-business storage (a configured directory on the server by default; the storage is behind an interface so object storage
  can replace it later). Never served from a public path: every download goes through an authorised endpoint and a short-lived
  signed link. Tenant-scoped rows with forced RLS (name, type, size, checksum, who, when, record it belongs to).
- Attach to any record by (entity type, entity id) like custom fields; units declare attachable record types through an extension point.
- Images: accept from a phone camera, validate real type (not the file name), strip location metadata by default (setting),
  generate a thumbnail and a sensible-size copy, size and count limits per record and per business (plan limit data), PDF accepted.
- Web: shared `Attachments` component (take photo/choose file, grid with captions, view, delete with reason), works on a phone.
- Privacy: attachments are personal data when they show people; `kernel.personal_data` find/export/anonymise/delete; retention
  settings; a photo-consent note field where a business photographs customers (salon before/after).
- Backups include files; `ziira verify` checks rows against files; deleting a record never leaves orphan files silently.
- Not antivirus (documented); no video in v1.

### F. Third-party payer claims: unit `claims` (insurers for garages and clinics, any "someone else pays")
A job or an appointment can be paid partly or wholly by another party (an insurer, a fleet owner, a medical scheme, an employer).
New unit, schema `claims`, requires only the kernel (links by soft reference to customers, jobs, appointments, invoices):
- **Payer** = a customer account marked as a payer (insurer), with per-payer terms as data: labour rate per hour by work type,
  parts discount or markup, paint/materials rates, approval limit, required documents, payment days, contact people.
- **Claim** (one per job/appointment where a payer is involved): payer, policy number, claim number, loss/incident date, insured
  customer, assessor (name, phone), excess/deductible the customer pays, status.
- **Submission** of an **estimate** to the payer: a numbered version of the lines (labour, parts, paint, sundries, each with a
  quantity and price), printable/emailable document, photos attached, `submitted_at`.
- **Payer response**, per line: *approved*, *approved at a different amount* (counter-offer), *rejected (with the payer's reason)*,
  *needs information*. A whole-claim response too: accepted, partly accepted, countered, rejected, withdrawn. History of every
  round (who, when, what changed), so a counter-offer can be accepted, argued (resubmit a new version with a note) or dropped.
- **Supplementary estimate**: extra damage found after teardown: a new version linked to the first, approved separately; the job
  must not do unapproved work without a recorded decision (warning, or block as a business setting).
- **Authority to repair** (the payer's approval or LPO number and amount) recorded; completion note / satisfaction signature
  captured as name + time; re-inspection and assessor visits as dated notes.
- **Invoicing split** through `pos.public`: payer invoice for the approved amount less excess, customer invoice for the excess plus
  rejected or betterment lines the customer agrees to pay; credit notes if the payer later reduces. Never edits a posted invoice.
- **Payments and ageing**: payer receipts allocated to invoices through `payments.public`/`pos.public`; ageing per payer (30/60/90),
  short-pays (paid less than approved) flagged with the difference; rejected-claim write-off or recharge to the customer.
- **Total loss / salvage / cash-in-lieu** as claim outcomes (a closed reason with a note), not a workflow of its own.
- Intelligence checks: estimate waiting for the payer's answer N days; approved but job not started; counter-offer unanswered;
  supplementary needed but not submitted; claim completed but not invoiced; payer invoice overdue; payer rejects or short-pays far
  above normal; rejection reasons repeating.
- Clinics reuse the same unit for insurer/scheme billing (plain "bill to" with member number, pre-authorisation reference, approved
  amount, patient co-pay), with no clinical content.
- Web: Claims list by payer and status, claim page (timeline of rounds, line approvals side by side: asked / approved / countered),
  payer setup, ageing report; embedded claim panel on the job page.

## How each business really works (design from this, not from our module list)

**Salon, spa, barber (`pack_salon`)**
- Mix of walk-ins and bookings; a barber may be 90% walk-ins with a queue, a spa 100% booked. Front desk shows who is free now,
  who is next, and adds a walk-in in two taps.
- One visit = several services in sequence, sometimes by different staff; duration and buffer per service; **processing time**
  (colour sits 30 min while the stylist serves someone else).
- Price varies by staff level and hair length: price variants on a service offer, editable at checkout.
- Checkout is the centre of the day: services done, retail products (stock down), discount with reason, **tip** (to the stylist, not
  revenue), deposit already paid, **gift voucher / package / membership credit / loyalty points** consumed, split payment, one receipt.
- **Staff commission**: percent or fixed per service and on products, tips separate, period report per person, a figure payroll can
  read; never silently posts pay. **Rota**: working hours per person per week, time off, a chair/room rental option for barbers
  (booth rent as a recurring invoice).
- Deposits or card-on-file for long services; no-show / late-cancel policy (window, fee) as settings.
- Reminders (day before, 2 hours before), rebooking prompt after the visit, "haven't been in 8 weeks" nudge: queued through the
  notification layer, respecting do-not-contact and quiet hours.
- Client card: past services, formula/notes, allergies (a plain note), **patch-test date** with an expiry warning (not medical
  advice), preferred staff, **before/after photos with a consent flag** (files service).
- Day end: cash-up per till, tips owed, commission, no-shows, vouchers sold and redeemed.

**Garage, body shop, repair shop, tailor, phone/appliance repair (`pack_garage`)**
- Vehicle/device is an asset with history: plate/VIN/IMEI, make, model, year, colour, odometer per visit; show previous visits and
  what was done on the intake screen; next-service due (date or mileage) reminder.
- **Photos everywhere they matter** (files service): intake photos (all sides, damage, odometer, fuel gauge, belongings), progress,
  before/after, parts-condition photos (old part), photo categories as data, required photos per job type as a checklist rule,
  photos included in the estimate sent to an insurer, photos on the job card and invoice-free (not printed by default).
- Intake: condition notes, fuel level, belongings, customer acknowledged (name, phone, time), key tag number.
- Diagnose -> **estimate** (parts + labour + paint + sundries, validity date) -> approval by the customer (link, or recorded by staff
  with who/when) **or by an insurer through the claims unit** -> work -> **additional work found** needs a fresh approval ->
  ready -> collected -> invoiced -> warranty window.
- **Insurer jobs (claims unit)**: the job knows its claim; line approvals/counters from the insurer flow back onto the job
  (approved lines go ahead; rejected lines wait for the customer's decision); insurer-set labour rates and parts rules apply as
  data; the technician sees only what is authorised; excess collected at hand-over; the payer invoice and the customer invoice
  come out right; ageing and rejection follow-up in claims. Fleet customers on credit work the same with "payer = the fleet".
- Labour priced by **flat-rate task** (library of standard times as data) or hours x rate, per work type (mechanical, body, paint,
  electrical) with its own rate.
- Parts: from stock or **ordered for this job** (supplier order linked through purchasing.public; arrival moves the job on);
  customer-supplied parts (labour only); returns of unused parts; used/genuine/aftermarket class on a line (insurers care);
  parts markup by category as data; old-part retention note.
- Technician productivity: hours booked vs billed per technician, jobs waiting for parts / approval / insurer, ready-not-collected
  N days (storage fee optional), a bay/booking board (jobs can be scheduled into bays), **courtesy/hire car** as a simple asset
  loan with out/in dates (not a rental business), towing as a service line.
- Tailor/repair variant: measurements as custom fields on the customer, fittings as appointments (bookings optional), pickup due
  date, deposit on order, photos of the garment/item.
- Release only on payment: a warning that a business may turn into a block; warranty/comeback links a new job to the earlier one.

**Consultants, agencies, accountants, lawyers (`pack_professional`)**
- Time is the stock: timers and a weekly grid; **missed-time nudges** matter most.
- Matters/engagements per client with fee types: hourly, fixed fee with milestones, capped fee, retainer drawdown, monthly recurring.
- Disbursements/expenses re-billed with or without markup, with a receipt photo (files service); write-offs/write-downs at review
  with a reason (never an edit of approved time); rate by person x matter; partner review before invoicing; narrative from entries.
- Trust/client money (lawyers): out of scope, stated plainly in docs.
- WIP ageing, realisation, utilisation, over-budget projects; recurring engagements (monthly bookkeeping, annual returns) with due
  dates and a checklist; engagement letters/documents attached (files service).

**Clinics and dental (`pack_clinic`) - appointments and billing only, NO clinical or medical records, diagnoses, prescriptions or lab data.**
- Appointment types by practitioner and room (a chair + a machine), new vs follow-up, **recall** lists and reminders, waitlist that
  fills a freed slot, treatment plans as an accepted **quote billed in instalments**, deposits, session packages (physio: 6).
- **Insurer / scheme billing through the claims unit**: pre-authorisation reference, approved amount, patient co-pay, rejection
  reasons, payer ageing. Administrative documents (consent forms, referral letters as files) may be attached but the unit states
  clearly it is not a medical record system.
- Privacy: only what is needed; administrative notes; `kernel.personal_data` and retention settings; reminders are the revenue.

**Gyms, studios, trainers (`pack_fitness`) - robust, ready to use**
- **Members**: profile with **photo** (files service; shown at check-in), member number from kernel numbering, emergency contact,
  waiver / terms acceptance recorded (who, when, version; **no health data**), source/referral, trial status, family or corporate
  grouping (one payer, many members), notes, tags.
- **Plans** (data): monthly, annual, fixed-term contract with minimum term, visit packs (10 visits), day/week pass, trial pass,
  off-peak plans, class-only plans, per-branch or all-branch access, joining fee, cancellation notice period, **pro-rata** on joining
  mid-month, upgrade/downgrade with proration, freeze rules (max days, fee), pause for injury/travel.
- **Billing that does not leak money**: auto-renew invoices on schedule, payment retries and an *overdue / past due* state with
  dunning messages (queued), grace days before access is restricted (setting), failed or late payment list, arrears per member,
  write-off with reason, refunds through reversals, mobile-money/card/cash receipts, receipts for staff-taken payments, annual
  renewals reminded, price changes applied from a date (not retroactively).
- **Check-in**: desk screen by name, phone, member number or **QR/barcode scan** (a camera in the browser or a USB scanner typing
  the number), shows photo, plan, status (active, frozen, overdue, expired), classes booked today, outstanding balance, and a clear
  **allow / deny / warn** decision with the reason; staff override with a reason (audited); works fast and offline-tolerant like the
  till (queue and sync). A small **access-decision API** (`/api/v1/...` with an API key) lets a turnstile or door controller ask
  "may member X enter now?" without any hardware code in Ziira; hardware itself is out of scope.
- **Classes**: weekly schedule that repeats with holiday exceptions, instructors, rooms, capacity, booking by member or desk,
  **waitlist that auto-promotes** (with a window to confirm), late-cancel rule that consumes the credit, no-show handling, a
  class pack decrements on attendance, drop-in price, instructor sub, cancelled-class notice to everyone booked.
- **Personal training**: 1-to-1 sessions as appointments, session packs with expiry, trainer commission/pay per session, trainer
  availability and time off; a trainer's client list; **progress notes limited to measurements the member shares (custom fields:
  weight, goals), not medical advice**.
- **Retail and extras**: POS sales of drinks/supplements (stock), locker or towel rental (a small recurring fee or deposit), guest
  passes, gift vouchers, simple **loyalty points** and referral credit (credits ledger), day-end cash-up.
- **Leads and retention**: enquiries and trial visits tracked to conversion (via crm.public leads), "hasn't visited in N weeks",
  "membership ends in N days", "payment late", birthday message; churn and reasons for leaving.
- **Reports an owner acts on**: active members, new/ended per month, monthly recurring revenue, revenue by plan, retention curve,
  attendance by hour and day (peak times), class fill rate, trainer utilisation, arrears, freezes, revenue at risk.
- **Robustness**: capacity and credit updates are race-safe (many people booking the last class place; two desks checking in the
  same member), renewals and retries idempotent, tested with thousands of members and a check-in latency target, multi-branch
  aware, every money step audited and reversible only by reversal.

**Tutors, schools, training centres (`pack_education`)**
- Classes as recurring group sessions with roster and capacity; **term fees** as recurring invoices per term with instalments and
  sibling discount; the payer (parent) differs from the learner (billing contact); attendance per session; make-up sessions;
  end-of-term reminders; tutors' sessions as hours for payment; report/result documents attached (files service); fee arrears list.

## Cross-cutting requirements (all businesses)
- Public booking page end to end: service -> staff or anyone -> time -> details -> consent -> deposit link when required ->
  confirmation queued -> reschedule/cancel link within the business's window.
- Keyboard, responsive, English and Swahili, loading/empty/error states designed; no jargon.
- Every setting is data; no country, currency or tax in code. Every cash step idempotent and audited; posted invoices never edited.
- Intelligence: only checks a real owner would act on, each with a plain entry; thresholds per pack as data; silent when fine.
- **Sample-data recipe** per pack (a believable week), idempotent and removable. **First-run checklist** per pack (5-7 steps).
- Docs: one short `docs/<pack>.md` per pack (what it sets up, what to edit first, what it does NOT do) and `docs/files.md`,
  `docs/claims.md`, `docs/timebilling.md`. No marketing prose. Do not invent regulations.
- Data protection: photos and documents covered by personal-data tools and retention; an access log for who viewed a customer's file.

## Ownership (agents edit only what they own; shared files: re-read right before each edit, additive, never revert others)
Order: **E first** (small, shared); **F** in parallel with the rest, joining jobs/bookings through `public.py`.
- **E - files service**: `ziira/kernel` files module + `ziira/sdk` surface + `frontend/src/sdk` Attachments component + docs/files.md.
- **F - claims unit**: `ziira/modules/claims`, `frontend/src/modules/claims`, docs/claims.md.
- **A - bookings + salon + clinic**: `ziira/modules/bookings`, `frontend/src/modules/bookings`, `ziira/plugins/pack_salon`, `pack_clinic`.
- **B - jobs + garage**: `ziira/modules/jobs`, `frontend/src/modules/jobs`, `ziira/plugins/pack_garage`.
- **C - time billing + professional**: `ziira/modules/timebilling`, `frontend/src/modules/timebilling`, `ziira/plugins/pack_professional`.
- **D - memberships + fitness**: `ziira/modules/memberships`, `frontend/src/modules/memberships`, `ziira/plugins/pack_fitness`
  (check-in, access-decision API, classes with agent A's group sessions, retail, vouchers and loyalty, reports).
- **G - education** (starts after D's recurring invoices are stable): `ziira/plugins/pack_education`.
- Cross-unit needs go through `public.py`, events and extension points (rules 3-5, 11). Need something from a unit you do not
  own: add a small additive function to its `public.py` and tell the owner; do not rewrite it.
- The Services menu grouping, landing page and Help guides are the lead's, after agents report.

## Rules for every agent
- Follow `docs/plans/services-shared-design.md` and its Speed rule (own tests, `tests/test_architecture.py`, ruff, mypy,
  lint-imports, eslint/tsc/vitest on touched folders; no fuzzer, full suite or e2e). Do not commit or push.
- New migrations: take the next free number right before creating; never edit applied ones.
- Use your OWN new browser tab, never the first tab; close it when done.
- Regenerate `frontend/src/api/schema.d.ts` LAST; API schema class names unique and unit-prefixed (`tests/test_openapi_names.py`).
- Write `docs/plans/services-wave2-<letter>.md`: done, cut, doubts, next, resume commands. Final report: what now works end to
  end per business, what is missing and why, public functions/events/extension points, every known gap. Do not claim what you did not run.

## Decisions by the owner (binding)
1. **Insurers: support every way of working**, because businesses differ. The estimate can be sent by email, WhatsApp (channel
   registry), as a printable/PDF document, or as a **secure response link** where the insurer opens the estimate (photos included),
   answers each line (approve / counter with an amount and note / reject with a reason / ask for information) and signs off
   without an account. Responses received any other way (phone, email, portal) are recorded by staff with who/when. Ziira does
   not integrate with insurer portals.
2. **Gym entry: support every way**: desk check-in by name, phone or member number; QR/barcode scan; a card, tag or wristband
   number stored on the member (a USB reader types it like a scanner); a self-service **kiosk check-in screen**; and the
   door/turnstile **access-decision API plus a webhook** so any controller can integrate. Hardware drivers stay out of scope.
3. **Photos and files are visible to anyone with permission**, with a per-file visibility flag (staff only / shareable). Shareable
   files appear on customer approval links and insurer response links; each access through a link is logged.
4. **All businesses are built at the same time** (salon, garage with insurers, professional, clinic, gym, education); each gets
   the same depth.

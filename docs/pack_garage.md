# Garage pack (`pack_garage`)

An industry pack for garages, body shops, repair shops, phone and appliance repair and tailors. It is data only: no tables and no logic of
its own. Switching it on (at sign-up, or in Add-ons) copies the data below into the business through the units' own seeders
(`docs/industry-packs.md`). Everything is editable afterwards and nothing is overwritten once the business has changed it. It needs the
`products` and `jobs` units; `crm`, `inventory`, `pos`, `claims` and `intel` are used when present.

## What it sets up

| Area | What you get |
|---|---|
| Service items | Workshop labour, Parts and materials, Towing storage and fees (no prices). Jobs invoices under these; the pack links them in the job settings (it retries on a later run if the unit of measure or tax code did not exist yet). |
| Stages | the usual ones plus *Waiting for insurer*, *Waiting for customer*, *Quality check*, with the moves between them |
| Checklists | vehicle intake, body repair intake, insurer job, phone or device intake, garment intake |
| Work types | mechanical, body, paint, electrical, tailoring (rates are the business's own, left blank) |
| Task library | about 30 standard jobs with standard times. **Marked as examples**: edit them for your workshop; the first-run step ticks when none is left as an example |
| Part categories | genuine, aftermarket, used, tyres, batteries, oil, filters, brakes, panels, paint, electrical, fabric, each with a **markup on cost** (examples) |
| Kinds of photo | intake, damage, odometer, fuel, belongings, progress, before, after, old part, the garment or item |
| Job types | service, body repair, insurer repair, device repair, alteration, made to measure. Each has its checklist; body, insurer and tailoring types ask for photos before a stage |
| Bays | Bay 1, Bay 2, Paint booth |
| Settings (once) | warranty 30 days; unapproved extra work: warn; release before payment: warn; missing required photos: warn |
| Custom fields | vehicle (make, model, year, VIN, colour, fuel, gearbox), device (IMEI), job (fault as described, road tested), customer measurements (neck, chest, waist, hips, shoulder, sleeve, inseam, outseam, height, notes) |
| Messages | `job_ready`, `job_estimate`, `job_extra_work`, `job_service_due`, `job_pickup_reminder` in English and Swahili (shipped with the platform) |
| Intelligence | limits for stuck jobs, unanswered estimates and ready-not-collected suited to a workshop; the unit adds checks for late parts and overdue courtesy cars |
| First-run steps | seven steps on Job settings > Getting started and a banner on Jobs: choose the three items, set the labour rate, check the standard times, switch on service reminders, take a first vehicle, send a first estimate, add insurers |
| Sample week | six jobs: a finished service nobody collected, a clutch waiting for a part on order, an estimate waiting for the customer, an insurer repair with its claim (and payer), a phone screen, a tailoring alteration. Load and remove it in Getting started |

## What to edit first
1. Choose the labour, parts and fees items and set your hourly rate (Job settings > Rates and invoicing); give each kind of work its rate
   (Labour and parts).
2. Check the standard times and markups against your own workshop. They are examples.
3. Add your insurers in Claims (rates per work type and the parts discount apply by themselves on their jobs).
4. Switch on service reminders when a message channel is set up.

## What it does not do
No country, currency, tax or price is in the pack. It does not invent standard times for any make, it does not talk to insurer portals (answers
received outside the response link are written down by staff), and it keeps no clinical or medical data (it is not for clinics).

# Time and Billing (`timebilling`)

Hours, expenses and fees for a practice that bills time: consultants, agencies, accountants, lawyers. It records time, has it
approved by a second person, values it at rate cards, and turns approved work into one invoice through POS's invoice service.

**Not in this unit: trust or client money** (money held for a client, such as a lawyer's client account). Ziira does not hold or
account for it; keep it in a separate account and record it in your books. Nothing here posts to the books by itself: invoices go
through POS and Finance as every invoice does.

## Data model in plain words
* **Client** = a CRM customer (billing terms and markup in `client_terms`). **Project** = an engagement or matter, with a fee type.
* **Fee types** (`billing_mode`): `time_and_materials` (hourly), `fixed_fee` (billed by milestone), `capped_fee` (hourly, never more
  than `fee_cap`), `retainer` (prepaid hours, or a monthly fee).
* **Entry** = a block of time; **expense** = a disbursement (optional markup, receipt photo, category). **Week** = a person's week,
  submitted then approved by someone else. Approved time is fixed: rates and retainer cover are recorded on it and it is never edited.
* **Invoice review** (`invoice_batch`) = what will be invoiced, built from approved work, edited, optionally reviewed by a partner,
  then issued as one invoice (idempotent by the review).
* **Recurrence / task** = repeating work with a due date and checklist (dated tasks are made ahead of time by the worker).
* **Template, activity, snippet** = data a business edits: engagement templates, activity names, standard invoice wording.

## Lifecycle
log time or timer -> submit week -> approve (not your own; or the approvals inbox when a `timesheet` rule exists) -> unbilled work
(WIP, aged 30/60/90) -> invoice review -> (partner review) -> issue -> invoice in POS. Cancelling the invoice releases the work.

## Fees
* **Capped fee**: time is billed at the rates; the part above the cap is written down automatically with the reason "Fee cap
  reached" (newest work first). Work in progress and project summaries respect the cap; the summary shows the value above it.
* **Fixed fee**: milestones are marked ready and billed; no hourly time is billed.
* **Retainer**: an hours retainer is drawn down on approval, only the overage is billed, top-ups are billed with a review line; a
  monthly-fee retainer covers all time and its fee is billed once a month. With `auto_draft` the worker drafts the month's review on
  `bill_day` (a discarded draft stays discarded). Nothing is ever issued automatically.

## Write-downs, write-offs, partner review
* On a review line, billing less than the work is worth is a **write-down** and needs a reason; billing more is refused (add a line
  of your own). Billing nothing is a **write-off**: it needs `time.partner`, the line is left off the invoice, the work is marked
  `written_off` (never editing the approved time) and leaves work in progress. Cancelling the invoice brings it back. If every
  line is written off, the review is issued without an invoice.
* **Realisation** = billed / worth over work invoiced in a period (`GET /reports/realisation`).
* **Partner review** (setting `partner_review`, optionally above an amount): the review must be approved by someone with
  `time.partner` before it can be issued, unless that person issues it. Any later change takes the approval back.
* **Narrative**: written from entries' notes (`POST /invoice-reviews/{id}/narrative`), editable, optionally shortened into the line
  wording (300 characters per line, a POS limit); the time schedule downloads as CSV.

## Disbursements
Markup starts from the client's usual markup, else the company's, else 0; typing 0 bills at cost. A receipt photo or PDF is attached
through the files service (`timebilling.expense`); `receipt_required_above` stops a week being sent in without one. Engagement
documents attach to `timebilling.project` (letters, deliverables).

## Reminders (queued, never sent in a request)
Run hourly by `ziira worker` (task `timebilling.run`; `ziira run-task <tenant> timebilling.run`): missed time (a working day below
`nudge_minutes`, sent after `nudge_hour`), week not sent, approval waiting (the person's approver first unless away, then everyone,
weekly after), partner review waiting, work coming due or late. Only fee-earners are reminded (they hold `time.log` and logged time
in the last eight weeks or have a capacity set; staff can switch reminders off). Each reminder is sent once per subject and day,
through the person's channel for `alerts` or `approvals`, in their language (templates `time_missing`, `time_submit`,
`approval_reminder`, `partner_review`, `review_sent_back`, `engagement_due`).

## Reports for the owner
`GET /reports/owner`: WIP by age, realisation, utilisation, projects near or over budget (hours, money, fee cap), retainers nearly
used or expiring, late work, approvals waiting. Also `/reports/at-risk`, `/reports/realisation`, `/reports/utilisation`,
`/unbilled` (+ CSV).

## Permissions
`time.log`, `time.view`, `time.approve`, `time.bill`, `time.partner` (review invoices, write a line off), `projects.manage`,
`rates.manage`, `time.cost`, `time.settings`.

## Extension points and events
Implements `intel.check` (9 checks), `command.pulse_source`, `kernel.personal_data`, `kernel.integrity_check`,
`kernel.custom_field_entity` (`timebilling.project`, `timebilling.client`), `kernel.attachable_entity` (`timebilling.expense`,
`timebilling.project`), `kernel.industry_seeder` (file `data/timebilling.toml`: `[settings]`, `[[template]]`, `[[rate]]` examples,
`[[activity]]`, `[[snippet]]`, `[intel."code"]`, `[sample]`). Publishes `timesheet.approved|rejected`, `timebilling.invoiced`;
subscribes `approval.decided`, `invoice.cancelled`. `public.unbilled_value(session, client_id)`.

## Known limits
No trust accounting; fee cap is not reflected in the Command Center pulse figure or `unbilled_value`; invoice line wording is limited
to 300 characters by POS; example rates price nothing until confirmed.

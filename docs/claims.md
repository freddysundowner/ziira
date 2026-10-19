# Claims: when someone else pays

The unit is `claims` (schema `claims`, API `/api/v1/claims`, web module `frontend/src/modules/claims`, sidebar area **Services**).
It serves garages and body shops (insurers, fleet owners on credit) and clinics (insurers and schemes: administrative billing only,
**no clinical or medical content**). A claim exists for one job or appointment where a payer other than the customer pays all or part.
It requires only the kernel; customers (`crm`), jobs, appointments (`bookings`), invoices and receipts (`pos`) are optional and are
reached through their `public.py`.

## The data, in plain words

| Thing | What it is |
|---|---|
| **Payer** | An insurer, scheme, fleet owner or employer. Linked to a customer account (that is who gets invoiced). Terms are data: hourly labour rate per work type (`default` key as fallback), paint rate, parts discount % and markup %, approval limit, payment days, required documents, contact people, an address for estimates. |
| **Claim** (`CLM-<branch>-000001`) | One per job or appointment. Payer, the insured customer, policy number, the payer's claim number, member number and pre-authorisation reference (clinics), date and description of the loss, assessor, **excess** (the customer's share; a clinic's co-pay). |
| **Estimate** | A numbered version of the priced lines sent to the payer. The first chain is the *original* (versions 1, 2, 3 ...); extra damage found later is a *supplementary* chain (its own versions, approved separately). Draft -> submitted -> answered; a newer version supersedes the older one. |
| **Line** | labour, parts (genuine / aftermarket / used), paint, sundries, other; quantity, price (tax included, like every selling screen), the payer's answer, and who decided what next. |
| **Answer** | per line: *approved*, *countered* (the payer offers a lower amount), *rejected* (with the reason) or *needs information*. Every answer ever given is kept (append-only), with who, when, how (response link or recorded by staff: phone, email, portal, in person, message, letter). |
| **Decision** | After a counter: accept it (and say who carries the difference: the business, or the customer who agreed) or decline it (argue again in the next version). After a rejection: the customer agrees to pay, or declines the work. |
| **Authority** | The payer's approval or order (LPO) number and amount, given on the link or written down by staff. |
| **Completion** | Name and time of whoever signed the work off. |
| **Invoice run** | One billing: a payer invoice and a customer invoice (below). A supplementary estimate approved later, or a line the payer reduced, is a later run. |
| **Payer receipt** | Money received from a payer, allocated to its invoices. |
| **Short payment** | The payer paid less than the invoice and called it settled: the difference, flagged until decided. |
| **Closed reason** | `total_loss`, `salvage`, `cash_in_lieu`, `rejected`, `withdrawn`, `cancelled`, `written_off` (an outcome with a note, not a workflow). |

## Lifecycle

```
open claim -> estimate (draft) -> send -> payer answers each line -> [counter: accept / argue again]
   -> [extra damage: supplementary estimate] -> authority recorded -> work -> completion sign-off
   -> invoice (payer + customer) -> payer pays (receipts) -> settled      (short pay: recharge / dispute / accept)
```

Status: `draft` (no estimate sent), `open` (with the payer), `authorised` (something is approved), `completed` (signed off),
`invoiced`, `settled`, `closed`. It is worked out in one place (`services/status.py`) after every change. "Who are we waiting for"
(`payer`, `us`, `customer`) comes from the lines.

### Sending the estimate: every way
* **Email or any message channel the business has** (`POST /estimates/{id}/submit` with `channel` and `recipient`): the secure response
  link is queued as the `claim_estimate` message (never sent in the request; do-not-contact respected). Claims names no channel: the
  business's own channels come from the channel registry (`GET /api/v1/notifications/channels/available`).
* **Secure response link** (`make_link`, the default): the staff get the link path once and can pass it on any way they like.
* **Printable / PDF**: `GET /estimates/{id}/document?format=html` is a self-contained page the browser prints or saves as PDF;
  `format=text` is plain text.
* **By hand** (phone, portal): submit with `make_link=false`; the payer's answer is written down with `POST /estimates/{id}/responses`
  (who answered, how, when).

### The response link (no account)
`/claim-response/<token>` in the web app; API `GET|POST /api/v1/claims/public/claim-response/{token}`. The token is
`<business id>.<secret>`; only a hash of the secret is stored. The link is made for one estimate version, **expires**
(`link_valid_days`, default 14), can be **revoked**, is **rate limited** per link and per address, answers an unknown or tampered
token like one that never existed (404), takes **one sign-off** (a second attempt changes nothing), is replaced when a newer version is
sent, and **every view, answer and refusal is written to `claims.link_access`** (time, address, browser, outcome). The page shows the
business, the payer's own claim and policy numbers, the item, the lines and totals, and shareable photos once the files service lands;
it shows no customer name, phone or cost. The payer answers every line (approve / counter with an amount / reject with a reason /
ask for information), may give an authority number, types their name and signs off.

### Money
* **Payer invoice** = what the payer pays (approved lines, accepted counter-offers) **less the customer's excess**. The excess is spread
  over the payer lines as line discounts (largest remainder, to the cent) so no invoice line is negative.
* **Customer invoice** = the excess, plus rejected lines the customer agreed to pay, plus the difference of an accepted counter-offer
  the customer agreed to carry. Due on issue. (Differences the business absorbs are not invoiced to anyone and are shown as "given up".)
* Both invoices are made by Point of Sale (`pos.public.issue_invoice_from_lines`), every amount under the one service item chosen in
  **Claim settings**; that item's tax code is the claim's tax. The payer invoice's due date follows the payer's payment days.
* The work must be signed off first. A line with no decision yet is left for a later run. Posted invoices are never edited.
* **The payer reduces after invoicing** (`POST /claims/{id}/reductions`): the invoice lines made for that claim line are credited in full
  by a credit note (`pos.public.credit_invoice_lines`; the caller needs POS's refund permission and the credit must not wait for
  approval), the line gets its new answer, and it is billed again in the next run. The excess already charged stays charged.
* **Receipts** (`POST /payers/{id}/receipts`): recorded through POS (`pos.public.receive_invoice_payment`) against named payer invoices;
  a repeated `reference` returns the first receipt. Mark an allocation `closes_invoice` when the payer treats the invoice as paid:
  any difference above the settings' tolerance becomes a **short payment** (also raised in the exceptions inbox).
* **Short payment**: `recharge` (invoice the customer for the difference), `dispute` (note required, stays open) or `accept` (note
  required; the business takes the loss: **the unpaid balance stays on the payer's invoice in Point of Sale until a credit note is made
  there**, because POS has no write-off).
* **Ageing**: `GET /ageing` lists what each payer owes in buckets not due / 1-30 / 31-60 / 61-90 / over 90 days past due.

### Work that is not approved
`work_gate` (public.py) tells Jobs and Bookings whether work may start. Business setting `unapproved_work`: `warn` (default) or
`block`. A decision to go ahead (`POST /claims/{id}/work-decisions`, who and why, audited) lifts it until the next estimate is sent.

## Permissions

| Permission | Allows |
|---|---|
| `claims.view` | see claims, payers, estimates, ageing |
| `claims.manage` | open and edit claims, notes (assessor visits, re-inspections), authority, completion, close, work decisions |
| `claims.estimate` | make, send, withdraw estimates; record answers and decisions; response links |
| `claims.invoice` | invoice a claim; record a payer's reduction (credit notes) |
| `claims.payments` | record receipts; resolve short payments |
| `claims.settings` | payers and their terms; claim settings |

Default roles: Branch Manager (all but payments and settings), Finance Manager (view, invoice, payments, settings), Sales Rep (view,
manage, estimate), Cashier (view), Accountant (view, invoice, payments). POS permissions still apply to what POS does for us: invoices
need `invoices.manage`, credit notes `sales.refund`, receipts `receivables.manage` (at the claim's branch). Claims belong to a branch; payers
belong to a company.

## Public functions, events and extension points other units use

`ziira.modules.claims.public` (read the module docstring):
`claim_for_source(session, "job"|"appointment", id)` -> `ClaimState | None`; `claims_for_sources`; `approved_lines(...)` ->
`list[ApprovedLine]` (state, what the payer pays, what the customer pays, `work_authorised`, `waiting_on`); `payable_split(...)` ->
`PayableSplit`; `work_gate(...)` -> `WorkGateResult(allowed, state, policy, message, ...)`; `open_claim(...)`.

Events (payloads carry ids, number, `source_type`, `source_id`; no personal data): `claim.created`, `claim.estimate_submitted`,
`claim.response_recorded`, `claim.authorised`, `claim.completed`, `claim.invoiced`, `claim.credited`, `claim.payment_recorded`,
`claim.short_paid`, `claim.closed`.

Claims plugs into `intel.check`, `command.pulse_source`, `kernel.personal_data` and `kernel.integrity_check`. It offers no extension
point of its own yet. A job screen embeds the claim panel through the web module's `public.ts` (`ClaimPanel`).

## Intelligence

Checks (limits are parameters a business changes; plain English and Swahili in `intel/domain/plain_checks.json`):
`claims.estimate_waiting` (a payer has had an estimate N days), `claims.approved_not_started` (approved N days, job not started),
`claims.counter_unanswered` (a counter-offer nobody answered), `claims.supplementary_not_sent` (extra work drafted, not sent),
`claims.completed_not_invoiced`, `claims.payer_invoice_overdue`, `claims.payer_rejects_more` (a payer rejects far more than
the others), `claims.rejection_reasons_repeat`, `claims.short_pay_open`. Pulse figures: `claims.open`, `claims.waiting_payer`,
`claims.owed`.

## Privacy

`kernel.personal_data`: finds claims by the insured customer's phone or name; exports the claim and its timeline; erasure replaces the
insured name and phone and empties free text of a **closed** claim (open claims are refused). Policy numbers, amounts and invoices are
kept: they are the business's and the payer's records. The response link shows no customer details.

## What is not done / untested

* Photos on the response link need the files service (`docs/files.md`); `services/photos.py` is the seam and returns nothing today.
* Ziira does not integrate with insurer portals: answers received there are written down by staff.
* No write-off in Point of Sale: an accepted short payment is recorded in Claims only.
* Message wording uses the shipped `claim_estimate` template; channels that need approved templates need approval in Settings first.
* Estimate lines carry tax-inclusive amounts only; the tax split comes from the invoice item's tax code when invoiced.
* Nothing was run against a real insurer, scheme or message channel.

# Memberships, packages and recurring invoices

Unit `memberships` (schema `memberships`, web module `frontend/src/modules/memberships`). It answers three questions for any
business that is paid again and again by the same customers: *who is a member and what do they get*, *what did they buy in
advance and how much is left*, and *which invoices should be made by themselves, and when*. It needs Customers (`crm`);
Products, Point of Sale (invoices), Intelligence and the Command Center are optional. It names no country: currency, tax,
phone formats and message wording are data.

## What it holds, in plain words

| Thing | What it is |
|---|---|
| **Plan** | A kind of membership: fee, billing interval (month, quarter, year), visits or credits included each period, discount on services, the services the credits pay for (empty: all), whether unused credits carry over, the service item the fee is invoiced as, terms. Active or retired. |
| **Member** | A customer on a plan. Copies the plan's price, interval, credits, discount and covered services when it starts (the *price snapshot*): changing the plan later never rewrites what the member agreed to. Status `active`, `paused`, `frozen`, `cancelled` or `expired`; start date, next renewal date, optional end date (a fixed term), optional cancel-at date, reason and note. |
| **Package** | Something sold once: "10 massages", "Term 1 lessons". Credits, price, expiry in days (optional), services covered, service item for the invoice. |
| **Sold package** | A package a customer bought: its own credit balance and expiry date. Active, expired or refunded. |
| **Credit entry** | The ledger. Every change of a balance is one immutable row (`grant`, `purchase`, `use`, `refund`, `expiry`, `adjustment`, `reversal`). A balance is the sum of its entries. The database refuses UPDATE and DELETE. |
| **Recurring invoice (schedule)** | For any customer, member or not: the lines, interval (week, month, quarter, year) and "every N", an anchor day, start, an end date or a run count, `issue` (made by itself) or `draft` (waits for a person), pause and resume, the result of the last run. |
| **Invoice run** | One try to invoice one period of a schedule, a membership or a package sale. Unique per (owner, period start): this is what makes a period invoice exactly once. |
| **Policies** | Per company: allow credits below zero, how many missed periods to catch up, prorate the first period, reminders on or off and their lead times, quiet hours, language of reminders. |

## Credits

* A visit is paid from the membership first (its credits expire at the end of the period unless the plan carries them over), then
  from the sold package that expires soonest. A package pays only for the services it covers; a service not named is not covered by a
  restricted package.
* A balance never goes below zero unless the company allows overdraw (policy). What credits cannot cover is returned as `remaining`.
* Spending is **idempotent by (`source_type`, `source_id`)**: an appointment completed twice, a job line posted twice, spends once.
  Releasing the source writes `reversal` entries (once; asking again gives back nothing more). The same source may spend again
  after a release.
* A membership that is paused, frozen, cancelled or expired, and a package that is expired, refunded or past its date, pay for nothing.
* Manual adjustments (permission `memberships.credits`) need a note and cannot take a balance below zero (unless overdraw is on).

## Billing and the recurring task

`ziira worker` runs two tasks every hour (`ziira run-task <tenant> memberships.run_billing` runs one now):

* `memberships.run_billing`, for each company on the company's own date:
  * each due **schedule**: invoices every period that has started and not been invoiced, exactly once (key: schedule + period start). If more
    periods were missed than the policy "most missed periods to bill at once" (default 3), the oldest are recorded as `skipped` and put in
    the exceptions inbox (never silently dropped). A paused schedule skips the periods it was paused for.
  * each **membership** due to renew: invoices the period (when `auto_invoice`), writes off unused credits (unless the plan rolls over),
    grants the new period's credits once, moves the renewal date, publishes `membership.renewed`. A cancelled-at-period-end membership
    becomes `cancelled`; one past its end date becomes `expired`; a held membership with a resume date resumes (the days held are added).
  * packages past their expiry date become `expired` and the unused credits are written off.
* `memberships.send_reminders`: renewal reminders (default 7 days before) and package-expiry reminders (default 14 days), queued through the
  notification layer with the shipped templates `membership_renewal` and `package_expiring` (English and Swahili, in
  `ziira/kernel/message_templates.json`). Never sent in a request, never inside the company's quiet hours (they go at the next run after),
  never to someone who asked not to be contacted (the notification layer skips them). Each renewal date and each expiry date is reminded once.

Every item is done in its own savepoint. A failure is put in the exceptions inbox (`recurring_invoice_failed`, `recurring_period_skipped`,
`task_failed`) and tried again by the next run; a failed invoice is retried up to 5 times by the task and then waits for a person
(**Needs a look** tab: Try again or Do not invoice). Failed-payment chasing is not here: invoices are on credit and the receivables screens chase them.

**Invoices** are made only by Point of Sale's invoice service (`pos.public.issue_invoice_from_lines`, idempotent by source; the source is the
invoice run). Nothing here writes sales tables. The one place that calls it is `services/invoicing.py`; if Point of Sale is off, plans,
members and credits still work and the screens say that nothing can be invoiced from here. Prices on lines include tax, as everywhere in sales.
Signing a member up or selling a package invoices at once and, if that fails (for example the customer is over their credit limit), nothing
is saved and the person sees why.

**Proration** (policy, off by default): off means anniversary billing (a member who joins on the 15th renews on the 15th); on charges the first
period for the days left in the calendar month, quarter or year (credits rounded to the nearest whole credit) and renews on the 1st.

## Using it from another unit (bookings, jobs, time billing, industry packs)

Import only `ziira.modules.memberships.public`. All functions take the caller's session; the caller has checked its own permissions.

```python
from ziira.modules.memberships import public as memberships

memberships.member_credit_balance(session, customer_id, service_ref=None) -> Decimal
memberships.consume_credit(session, *, customer_id, service_ref, quantity, source_type, source_id) -> CreditUse
memberships.release_credit(session, *, source_type, source_id) -> Decimal      # how much came back
memberships.active_membership(session, customer_id) -> MembershipView | None
memberships.member_discount_percent(session, customer_id) -> Decimal
```

`CreditUse` has `covered` (paid with credits), `remaining` (still to charge; the member's `discount_percent` applies to it), `discount_percent`,
`covered_by` (list of `(holder_type, holder_id, quantity)`), and `replayed` (True when this source had already spent). Typical use: when
an appointment is completed, `consume_credit(... source_type="booking", source_id=appointment.id)`, invoice only `remaining`; when it is
cancelled afterwards, `release_credit(source_type="booking", source_id=appointment.id)`. `service_ref` is any stable text the plan or package
lists under "services covered" (a service item's SKU or id; the business decides). These signatures are kept stable.

## Events

`membership.activated | renewed | paused | resumed | cancelled | expired` (aggregate `memberships.member`, payload: company, branch, customer,
member id, plan id, number, plus details such as `period_start`) and `package.sold | used | expiring | expired` (aggregate `memberships.sold_package`).
`package.expiring` is published once per expiry date, even when customer reminders are switched off. `membership.plan_changed`, `checkin.recorded` (aggregate `memberships.checkin`; a public webhook event) and `voucher.sold`
are published too (see "Gyms and studios"). The unit subscribes to `customer.paid`, `invoice.cancelled` and `sale.returned` (Sales: arrears are read again
at once), `appointment.completed` (a trainer's earning) and the `class.attendee_*` events (Bookings: credits on attendance).

## API (prefix `/api/v1/memberships`)

`/summary`, `/invoicing`, `/settings`; `/plans`, `/packages` (catalogue); `/members` (+ `/{id}`, `/history`, `/credits`, `/pause`, `/resume`, `/cancel`,
`/undo-cancel`); `/sold-packages` (+ `/{id}`, `/credits`, `/refund`); `/customers/{id}/credits`, `/credits/adjust|consume|release`;
`/recurring-invoices` (+ `/{id}`, `/pause`, `/resume`, `/end`, `/run`); `/invoice-runs` (+ `/{id}/issue`, `/discard`, `/credit`, `/dunning`).
The gym additions are listed under "Gyms and studios": `/profiles`, `/groups`, `/waiver/versions`, `/customers/{id}/waiver|value|measurements`, `/plans/{id}/price-changes`,
`/members/{id}/change-quote|change-plan|dues|payments|freezes|freeze-allowance|guests`, `/arrears`, `/checkin*`, `/access/*`, `/lockers`, `/vouchers`,
`/credits/give`, `/trainers/*`, `/reports/overview`, `/exports/{kind}`, `/setup-steps`.

Permissions: `memberships.view`, `memberships.plans` (catalogue and policies), `memberships.manage` (sign up, sell, pause, cancel, spend credits),
`memberships.credits` (adjust, refund, write off, waive a fee), `recurring.manage` (schedules and drafts), `memberships.checkin` (the desk, the kiosk, the door API),
`memberships.override` (let in someone refused) and `memberships.reports`. Default roles: Finance Manager all; Branch Manager view, manage,
credits, checkin, override, reports; Sales Rep view, manage, checkin; Accountant view, recurring, reports; Cashier view, checkin. Issuing an invoice also needs Point of Sale's `invoices.manage`.
Records belong to a company and carry a branch (members, sold packages, schedules); a branch-level grant sees only that branch's records.
Cancelling a membership requires a reason from the seeded `membership_cancel` list (Settings > Reasons).

## Screens (Services area)

Memberships (figures, members with status chips, plan and "renewing this month" filters, packages sold), Member (credits, invoices, history, hold, cancel,
use or adjust credits), Plans and packages (catalogue editor and policies), Recurring invoices (schedules with next run and last result, "Needs a look" for
drafts and failures). A tab on the customer page shows a customer's memberships and packages. A member can carry the business's own custom fields
(`memberships.member` is a custom-field record type).

## Intelligence and the Command Center

Checks (`memberships.*`, area Customers; limits are data a business can change): `ending` (memberships cancelling or reaching their end date within
`days`), `packages_expiring` (credits left, expiring within `days`, at least `min_credits`), `recurring_invoice_failed` (urgent after `high_after_days`),
`revenue_at_risk` (share of monthly membership income that is cancelling, on hold or failing to renew, from `min_percent`, urgent from `high_percent`, at
least `min_members`). Pulse figures: active members, membership income per month, renewals in 7 days, packages expiring in 30 days, failed recurring invoices
(company and per branch). Plain-language text is in `ziira/modules/intel/domain/plain_checks.json` and `site/src/content/checks.plain.json` (run
`make site-catalog` after changing checks).

## Personal data

The unit holds only a customer id and free-text notes (member notes, cancellation note, history notes, package notes). The notes are found, exported and
cleared by the `memberships` personal-data provider (it also covers the profile: emergency contact, birth date, card and photo link, measurements, guests;
waiver acceptances and check-ins are kept because they name only the customer id and are the record of consent and entry); names, phones and emails live in Customers. Records are kept: the ledger and invoices point at them.

## How an industry pack customises it

A pack ships `data/memberships.toml` (`[settings]`, `[waiver]`, `[[plan]]`, `[[package]]`, `[intel."code"]` limits), read by this unit's industry seeder
(`memberships.catalogue`). Plans and packages are marked `is_example`; a code the business already has is never touched (only a missing service-item link is
topped up); policies are written only if the company never saved any; the terms only if there are none. See `docs/industry-packs.md` and `docs/pack_fitness.md`.

## Gyms and studios

Everything below is part of this unit; the **fitness pack** (`docs/pack_fitness.md`) only supplies starting data. Nothing names a country.

### Members, terms, households

* **Profile** (`memberships.profile`, one per customer): member number (kernel numbering, prefix `M-`), a card/tag/wristband number, emergency
  contact, birth date, source, who referred them, tags, trial dates, "entry stopped" with a reason. The photo is a file on the profile
  (`docs/files.md`, record type `memberships.profile`); `photo_file_id` must be a picture attached to that profile. **No health data is kept.**
  Business-defined fields: `memberships.profile` and `memberships.member` are custom-field record types.
* **Terms (waiver)**: `waiver_version` is never edited (new wording is a new version); `waiver_acceptance` says who typed their name, when, by which
  method (desk, kiosk, online), recorded by whom. Never edited or deleted. With the policy `waiver_required` a member who has not accepted the
  current version is refused at the door.
* **Households and companies** (`account_group`): one payer, many members. The members' invoices (memberships, packages, freezes, rentals) go to the
  payer; the member stays the member (`billing_customer_id` on the membership). **Billing contact for other units (pack_education):** a recurring
  invoice's `customer_id` is who is billed; `for_customer_id` and `for_label` (on schedules and on invoice runs) say whom it is for (a learner, a
  locker). Use `schedules.create_schedule(..., customer_id=<parent>, for_customer_id=<learner>, for_label="Term 1")` and read `GET /recurring-invoices`.
* **Trial**: a plan of kind `pass` with `is_trial`; the profile is `trial` until a real membership starts; a follow-up message goes after it.

### Plans

A plan has: kind (`recurring`, `fixed_term` with `term_periods`, `pass` with `valid_days`), billing interval (month, quarter, year), fee, credits per
period, discount, joining fee (invoiced on the first invoice only), notice days, early-exit fee (inside a contract), freeze rules (`freeze_max_days` a
year: empty none, 0 not allowed; `freeze_fee`), per-plan proration, **access windows** (off-peak: days and times on the company's clock; a window can
cross midnight), a **branch list** (empty: every branch), `gym_access` (false: classes only), `classes_mode` (`included` free, `credits` cost a credit,
`none`), guest passes a period, a description, and `is_example` (a pack's example price: cleared when the fee is edited).
**Prices from a date**: `POST /plans/{id}/price-changes {effective_from, fee, apply_to_existing}`: never in the past; new members pay it from the date;
existing members only with `apply_to_existing` and not `price_locked`, at their first renewal on or after the date. Invoices already issued are never touched.
**Changing plan**: `GET /members/{id}/change-quote?plan_id=` then `POST .../change-plan {plan_id, when: now|next_renewal}`. An upgrade now invoices the
difference for the days left (and grants the extra credits for those days); a cheaper plan or another billing period starts at the next renewal.
**Holds**: a member's freeze follows the plan (days used in the last 12 months, fee invoiced at once, resume date) and the days are added back when it
ends (renewal, term end and end date move). A hold the business puts on (`frozen: true`) has no limits. Cancelling: at the end of the period, but not before
the notice period and the minimum term; immediately inside a term charges the early-exit fee unless waived by someone holding `memberships.credits`.

### Money that does not leak

* Each issued invoice run keeps `due_date`, `outstanding` and `settle_state` (open, paid, credited, cancelled), read from Sales. The memberships carry
  `arrears` and `past_due_since`, refreshed by the hourly task and **at once** when `customer.paid`, `invoice.cancelled` or `sale.returned` arrive.
* **Late-payment messages** (`membership_payment_late`, English and Swahili): policy `dunning_days` ("1,7,14": days after the due date), one message per
  invoice per step (`dunning_log`), never in quiet hours, never to someone who asked not to be contacted; `POST /invoice-runs/{id}/dunning` pauses them.
* **Grace days** (policy): up to that many days late a member is let in with a warning at the desk; after it entry is refused (a manager may override).
* **Hold for unpaid fees** (policy `auto_freeze_days`, 0 = off): the membership is frozen (kind `arrears`, no new invoices) and a message says why; it
  resumes by itself when the arrears are paid.
* **Late list**: `GET /arrears` (per paying customer, oldest first), CSV `GET /exports/arrears`, and `GET /members?past_due=true`.
* **Taking payment**: `POST /members/{id}/payments` (amount, method, reference) allocates to the oldest unpaid invoices of that membership through Sales'
  receipts (cash goes through the cashier's open till); the receipt number comes back.
* **Write-off and refund** by credit note: `POST /invoice-runs/{id}/credit {reason_code_id (a Sales sale_return reason), refund_method:
  credit_note|cash|mobile_money, amount?, note}` through Sales' return rules and approval limit (`pos.public.credit_invoice`). Needs `memberships.credits`.
  The invoice is never edited.
* **Vouchers, credit, points, referral** (`value_account`, `value_entry`, immutable ledger): gift vouchers have a code (`GV-...`) and may be sold
  (invoiced to the purchaser when a voucher service item is set in the policies); referral and promo credit belong to a customer; points are one
  account per customer (earned on payments at `points_per_unit`, redeemed into credit at `point_value`). A credit or voucher code reduces the next
  invoice this unit makes (policy `auto_apply_credit`, a voucher code on sign-up or package sale) as a line discount, recorded against the invoice run
  and given back if the run is discarded. The **referral reward** (policy) goes to the referrer when the referred person starts their first paid membership.
  At Bookings' front desk the same value is spent through `bookings.checkout_tender` (kinds `voucher`, `credit`, `loyalty`; `tender.py`).

### Check-in and the door

One decision (`domain/access.py`, pure and property-tested) for every way in: a profile that is **blocked** is refused; **terms** missing (when required)
refuse; a membership must be active, started, not ended, **plan hours** (off-peak windows) and **branch** must fit, `gym_access` must be on; **late
payment** is a warning inside the grace days and a refusal after; otherwise a **visit pack** (a package that covers the service `gym`, or covers
everything) pays one visit, the soonest-expiring first. Outcome `allow`, `warn` (in, but the reasons are shown) or `deny`. One counted visit a day per
person; a second scan the same day takes nothing; a repeat inside `repeat_window_minutes` returns the first answer (no new row). A visit taken by mistake is
given back with `POST /checkins/{id}/give-back`.

* **Desk**: `GET /checkin/search?company_id&q` (name, phone, member number, card) then `POST /checkin {company_id, branch_id, customer_id | identifier,
  method, device, local_id}`. **Scan / card / kiosk** send the number or card (QR text is `ZM:<number>`; both are accepted). `override_reason` lets in someone
  refused: needs `memberships.override`, a reason, is audited and flagged to Intelligence when one person does it too often.
* **Every attempt is a row** (`memberships.checkin`, immutable) with the decision, the reasons, the method, the device, whether it was overridden or offline.
* **Offline desks**: `GET /checkin/roster` returns today's decision for everyone with a way in (cache it; `valid_hours` says how long to trust it);
  the browser queues check-ins with a client id and the time they happened and sends them with `POST /checkin/sync`. The server records each (a repeat
  records nothing new), and anyone it would have refused is recorded as a fact and put in the exceptions inbox.
* **Access-decision API** for a turnstile or door controller (API key with permission `memberships.checkin`, scoped to a company or branch;
  these two calls are part of the public API, `docs/public-api.md`): `POST /access/decision {branch_id, identifier, device, record}` answers
  `{allowed, decision, code, message, member_number, first_name, reasons}` (only the member number and first name leave); `record: false` is a dry run;
  `GET /access/allowed?branch_id` lists the numbers and cards allowed right now, without names, for a controller that keeps its own list.
  **Webhook**: the event `checkin.recorded` (company, branch, member number, decision, code, method, device, overridden, offline, counted) is in the webhook
  catalogue (`docs/webhooks.md`). No hardware code is in Ziira.
* Speed: a check-in is about ten indexed queries; with 4,000 members it answers in tens of milliseconds (tests assert a median under 250 ms through the API,
  a 4,000-member roster under 6 s).

### Classes (Bookings' group sessions)

Bookings owns the timetable, rooms, instructors, capacity, waitlist and cancellation notices (`docs/bookings.md`). This unit owns the **credits**:
`class.attendee_attended` spends one credit (the plan's, when its `classes_mode` is `credits`, else a class pack that covers the class's name, `class`
or the service) once per person per class; `class.attendee_reset` gives it back; `class.attendee_no_show` and a late cancellation
(`class.attendee_cancelled` with `late`) spend it when the policies `no_show_consumes` / `late_cancel_consumes` say so; a class the business called off
(`session_cancelled`) gives everything back. A plan with `classes_mode = included` spends nothing. Drop-in prices are the service item's price at checkout.

### Personal training, lockers, guests, measurements

* **Packs with expiry** are packages (`PT5`: covers `pt`, expires after N days). **Trainer pay**: `PUT /trainers/rates` (fixed or percent, per service or
  all), earnings are written from `appointment.completed` once per session and trainer (`trainer_earning`), `GET /trainers/earnings`, `mark-paid` after payroll.
  Nothing is paid from here; payroll reads the figures.
* **Lockers and towels**: add by codes with rent and deposit; assigning invoices the deposit once and creates a recurring invoice for the rent
  (`for_label` says which locker); releasing ends it. The deposit goes back with a credit note.
* **Guest passes**: plan field; `POST /members/{id}/guests` counts them per period and puts a guest with a phone in CRM as a lead.
* **Measurements** a member chooses to share (weight, waist, a lift): `POST /customers/{id}/measurements`; removable on request.

### Retention and leads

Queued messages (policies; quiet hours; do-not-contact respected): not seen for `inactive_weeks` weeks, birthday, follow-up after a trial, late payment,
renewal and package-expiry reminders. Leads: Customers' lead functions (`crm.public.capture_lead`, `make_customer_from_lead`) are used for guests; trial to
member conversion is counted in the report.

### Reports (permission `memberships.reports`)

`GET /reports/overview?company_id&start&end&branch_id`: members (active, held, trials, cancelling, quiet 4 weeks), income per month (a quarter counts a third,
a year a twelfth), income at risk (cancelling, held or late, with its share), by plan, new and ended per month, retention by month of joining, visits by
weekday and hour, money owed aged (7/30/60/60+ days), holds and freeze fees, trials started and converted, why people leave, trainers' sessions and
earnings, and class fill per class (booked places over capacity, from Bookings' sessions when Bookings is on). CSV: `GET /exports/members|arrears` (audited).
Trainer utilisation (hours booked against hours available) is not in this report: it needs the trainers' availability from Bookings; the sessions and earnings per trainer are.

### Intelligence

New checks: `memberships.members_inactive` (silent when check-in is not used), `memberships.payment_late`, `memberships.entry_overrides`; pulse figures
"Members who owe fees" and "Visits today". A pack can set the limits (`apply_check_defaults`).

## Not done / limits

* No "unlimited" plans for credits: give a large number of credits (for example 999). (Entry is unlimited on a plan without credits.)
* No member portal and no card-on-file charging: late payers are reminded by message (steps in the policies) and can be held at the door or frozen,
  but nobody is charged automatically. Money is taken at the desk (cash, mobile money, card, bank) through Sales; the receipt is Sales' receipt.
* A mid-period downgrade refunds nothing: it starts at the next renewal. A part-paid invoice can be credited only by an amount (the credit is taken
  proportionally from its lines, so with a very large invoice a few cents can remain).
* Credits are counted in whole or part units (two decimals); there is one credit price per visit, not a per-service credit cost.
* Reminder wording is shipped in English and Swahili; the language is a company policy (a customer's own language is not stored).
* Hardware is out of scope (turnstiles, card writers): a controller asks the access-decision API; a reader types the number like a keyboard.
* Camera scanning in the browser needs a browser that has `BarcodeDetector`; a USB scanner works everywhere.
* The check-in screen shows the classes booked today only when Bookings offers them to it (not yet: see the gaps in `docs/plans/services-wave2-d.md`).

## Paying at the front desk (Bookings checkout)

Bookings' checkout screen ("Check out") bills a visit in one step and can pay it with credit from this unit:

* **Packages and membership credits** need nothing more from this unit: the checkout calls `member_credit_balance` / `consume_credit` /
  `release_credit` (public.py) with `source_type="bookings.checkout_line"` and the checkout line's id. A package that lists the service under
  "services covered" pays for it. Checkout tries the service item's **SKU**, then its id, then the offer's id, then the service's name, so
  type the SKU of the service item under "services covered". The member's `discount_percent` is applied to what the credits do not cover.
* **Gift vouchers, member credit and loyalty points** are built here (`ziira/modules/memberships/tender.py`, kinds `voucher`, `credit`, `loyalty`) and plug in through `bookings.checkout_tender`; this is how another unit does it: implement `CheckoutTender`
  (`ziira.modules.bookings.public`), register it with `@provides("bookings.checkout_tender")` in `hooks.py`, add `"bookings.checkout_tender"`
  to `[extends] implements` and `"bookings"` to `optional`. `kind` is a short stable word ("voucher", "loyalty"), `needs_code` says whether the
  desk types a code. `balance(session, customer_id=, code=)` returns what can be paid now (or None); `redeem(session, customer_id=, code=,
  amount=, invoice_id=, source_type=, source_id=)` takes up to `amount`, moves your own liability, and **settles that much of the invoice** with
  `pos.public.settle_invoice_non_cash(session, invoice_id, applied, kind="voucher", reference=...)`. It is safe to be called twice for one
  `(source_type, source_id)`. If the invoice does not come down by exactly what you report, the checkout is rolled back. `release(...)` gives it
  back when a checkout is reversed (optional).
* A class: Bookings publishes `class.attendee_attended` etc. (see `docs/bookings.md`, "Group sessions"); spend or give back credits from there.

# Appointments and Bookings

The `bookings` unit lets a service business (salon, clinic front desk, garage, tutor, consultant, gym) take and run
appointments: who can be booked and when they work, what can be booked, a calendar, a front desk for the day, a waitlist,
repeating appointments, classes, reminders, an online booking page, and billing the finished appointment. It holds no
clinical or personal-case notes: an appointment has a service, a time, who is serving, who is coming and a short note.

Code: `ziira/modules/bookings` (schema `bookings`), web `frontend/src/modules/bookings`, public page
`frontend/src/modules/bookings/booking-page`. Requires `products`; works better with `crm` (customers), `pos`
(invoices), `intel` and `command`.

## The data, in plain words

| Thing | What it is |
|---|---|
| Resource | A person, room, chair or machine that can be booked, in one branch. It has weekly **working hours** (several windows a day allow a break) and **time off** (leave, repairs). |
| Service offer | What can be booked: duration, set-up minutes before and clean-up minutes after, price, which resources can do it, and whether it needs **any one** of them or **all** together. Linked by a soft reference to a `products` service item (`product_type = service`) so it can be invoiced. A `class` offer has a capacity. |
| Appointment | A booking. Holds one or more resources from `start - buffer_before` to `end + buffer_after`. Number `APT-<branch>-000001`. |
| Attendee | A person on a class (capacity N). |
| Waitlist entry | A client wanting a time between two dates. Statuses `waiting`, `offered`, `booked`, `removed`. |
| Booking settings | One row per company: online booking on/off, address (slug), auto-confirm, minimum notice, furthest ahead, cancellation window, reminders and quiet hours, slot granularity, default clean-up, show people online, invoice on completion, consent wording. |

Hours, buffers, notice and granularity are data a business enters. Hours are wall-clock times in the company's time zone
(`company_zone`), so a 09:00 opening stays 09:00 across a clock change. An end time of 23:59 means "until midnight".

## Why double booking cannot happen

Each live appointment has a row in `bookings.appointment_resource` per resource it holds, with the blocked time range
(`tstzrange`, half-open, buffers included). An **exclusion constraint** (`btree_gist`: same `resource_id`, overlapping
`blocked`, `where holds`) is checked by the database, so two requests for the same time at the same moment cannot both
win: the second gets `409` ("That time is already taken") and the attempt is noted in `bookings.booking_refusal` for
Intelligence. Cancelled and no-show appointments set `holds = false`, which frees the time. Finished appointments keep
holding (their time was used). The availability engine (`domain/availability.py`) is pure code, property-tested.

## Lifecycle

`requested -> confirmed -> checked_in -> in_service -> completed`, plus `cancelled` (from requested, confirmed or
checked_in) and `no_show` (from confirmed or checked_in, only after the start time). `domain/lifecycle.py` is the only
place that says which moves are allowed; finished states never move. Reschedule is allowed while `requested` or
`confirmed`. Cancelling needs a reason from the `appointment_cancel` list, rescheduling one from `appointment_reschedule`
(seeded: client / business / other; `NO_SHOW` is used automatically for no-shows). A cancellation inside the company's
cancellation window is marked `late_cancellation`.

Who may book what: staff with `bookings.manage` at the branch may book at short notice and, by asking explicitly
(`allow_outside_hours`), outside working hours or over time off; a time already held is never allowed. Online visitors get
the full rules (hours, time off, buffers, minimum notice, furthest ahead).

Other features: **walk-ins** (a booking that starts now and is already checked in), **repeats** (weekly, every two
weeks, monthly, for N times or until a date: each is a real appointment at the same local time; an occurrence that does
not fit is skipped and reported with the reason), **classes** (one appointment with a capacity and a list of attendees),
**waitlist** (join; when a time frees up the cancel reply says how many waiting clients match; offer a free time, which
messages the client; accept books it), and a client-made `local_id` that makes a retried create return the first booking.

## Permissions

| Permission | Allows | Default roles |
|---|---|---|
| `bookings.view` | Calendar, appointments, waitlist, resources, services | Branch Manager, Sales Rep, Cashier, Finance Manager, Accountant |
| `bookings.manage` | Book, move, cancel, confirm, check in, start, finish, no-show, waitlist, classes | Branch Manager, Sales Rep, Cashier (the front desk) |
| `bookings.setup` | Resources, hours, time off, services offered, booking settings | Branch Manager |

Scope is by company and branch. Creating an **invoice** from an appointment also needs Point of Sale's own
`invoices.manage` at the branch (the front-desk roles do not have it by default: give it to the role that bills, or let
a manager press the button; the web app hides the button from people without it). There is no separate Receptionist role
yet: the Cashier and Sales Rep roles are the front desk.

## Messages

Confirmation, "request received", reminder, cancellation and waitlist offer are shipped templates in English and
Swahili (`ziira/kernel/message_templates.json`: `appointment_confirmation`, `appointment_received`,
`appointment_reminder`, `appointment_cancelled`, `waitlist_offer`). They are only **queued** through the notification
layer, never sent in a request. The channel is the best one the business has set up for which the client has a contact
(a chat channel, then SMS, then email; the rest become fall-backs). Someone on the do-not-contact list is skipped by the
notification layer. Each kind is queued once per appointment (`appointment_message`); moving an appointment allows a new
confirmation and reminder. The recurring task `bookings.send_reminders` (every 15 minutes, run by `ziira worker`) queues
reminders for confirmed appointments starting within the reminder lead time, never inside the company's quiet hours
(default 21:00-07:00, company time) and never after the start. Clients have no quiet-hours preference of their own yet.

## The online booking page

- Address: `/book/<slug>` in the web app (a page outside the signed-in app: choose a service, a day, a time, your
  details, done; English and Swahili; phone first; no login). The slug is chosen in Booking settings and must be unique
  across the platform: `master.booking_slug` (master migration `0018_booking_slug`) maps slug to business and company;
  the SDK functions are `claim_booking_slug`, `release_booking_slug`, `resolve_booking_slug` and `rate_limit`.
- API (no sign-in): `GET /api/v1/bookings/public/book/{slug}` (business name, note, consent wording, services, and the
  people the business chose to show), `GET .../{slug}/slots?service=&date=&resource=` (free start times only) and
  `POST .../{slug}/appointments`. These sit under the module prefix (`/api/v1/bookings`), not `/api/v1/public`, because the
  platform mounts a module's public router under its prefix.
- A booking needs the visitor's consent (the wording is the business's, with a default), a name and a phone or email. It
  is safe to send twice with an `Idempotency-Key`. A hidden field is a trap for robots: a filled one gets a success reply
  and nothing is kept. Requests are counted per address and per phone/email (`rate_limit`, HTTP 429).
- The customer is matched or created through `crm.public.match_or_create_customer` (phone or email; the phone is read
  with the company's calling code). The appointment is `requested` unless the business chose to auto-confirm.
- Nothing leaks: only services, shown people and free start times are returned; never who is booked or any client data. An
  unknown, closed or disabled address all answer the same `404`. People appear only if "let clients choose who they book
  with" is on, and a service with one person never names them.
- The settings page shows the link, a QR code and a button snippet to paste on a website.

## Invoicing

Finishing an appointment publishes `appointment.completed` (payload: `appointment_id`, `number`, `offer_id`,
`customer_id`, `resource_ids`, `minutes`, `service`, `product_id`, `lines` with `product_id`, `description`, `quantity`,
`unit_price`). "Create invoice" (and the setting "invoice automatically on completion") calls
`pos.public.issue_invoice_from_lines` with one line for the service at the price the appointment was booked at, source
`bookings.appointment`, idempotent per appointment. The adapter is `services/invoicing.py`: without Point of Sale and
Customers the answer is "Invoicing is not available". A problem with the automatic invoice never blocks finishing: it is
put in the exceptions inbox. A class is billed per person at the till, not from here. A customer must be linked to the
appointment. Deposits and the rest of the bill are handled by Checkout (below).

## Events

Publishes `appointment.created`, `appointment.confirmed`, `appointment.rescheduled`, `appointment.cancelled`,
`appointment.no_show`, `appointment.checked_in`, `appointment.completed`, `appointment.invoiced`. A business may subscribe
to `appointment.completed` with an outgoing webhook (no client contact details leave the system). Bookings subscribes to
nothing.

## Public functions (`public.py`)

`find_appointment(session, id)` and `customer_appointments(session, customer_id)` return small views. Services offered are
read through `products.public.service_items(session, company_id, search)` (added for this unit, additive), and customers
through `crm.public.match_or_create_customer` (also added).

## Intelligence and the Command Center

Checks (all read only, bounded by a look-back, set `branch_id`, limits are params a business can change):
`bookings.no_show_rate` (per resource), `bookings.late_cancellations` (per branch), `bookings.low_utilisation` (booked
share of working hours below a limit: a fixed limit the business sets, not a learned baseline), `bookings.double_booking_refused`
(per branch), `bookings.idle_gaps` (long empty stretches in the coming days) and `bookings.completed_not_invoiced` (only when
Point of Sale is on). Plain English and Swahili text is in `intel/domain/plain_checks.json` (topic "Customers").
Pulse figures: appointments today, finished, no-shows, booking requests waiting. Baseline metrics are not supplied in v1.

## Privacy

`privacy.py` implements `kernel.personal_data` for appointments, class attendees and waitlist entries: find (by phone,
email, name), export, anonymise (name replaced, phone, email and notes removed; the appointment, service, time, price and
invoice link stay as the business's record). An appointment still to come is left as it is, with the reason. Retention is
described as a rule that a person reviews; there is no automatic purge.

## Web screens (Services area)

Calendar (day and week, a column per person or room, working hours shaded, time off hatched, a current-time line, colours
by status with a legend; click an empty time to book, drag an appointment to move it; on a phone it becomes a day agenda),
Appointments (filters and quick actions), Front desk (today's arrivals: arrived, start, finish, did not come, invoice),
Waitlist, Staff and rooms (hours, time off), Services offered, Booking settings. The shared `Calendar` component is
exported from `frontend/src/modules/bookings/public.ts` for other modules.

## How an industry pack customises it

A pack (data) can add resources and their hours, service offers and the matching `products` service items, reminder
wording (the templates above), the default clean-up minutes and the cancellation window, and Intelligence limits. It
never changes the rules in code. Seeding is done through `kernel.industry_seeder` once the framework offers it; Bookings
does not implement it yet.

## Not done in v1

Client self-service links to move or cancel (only the public booking page exists), deposits, per-client message
preferences and quiet hours, a seeder for packs, class booking from the public page, invoices per class attendee, and
baseline metrics for Intelligence. Calendar drag-and-drop works with a mouse only (the phone layout is an agenda list, and
the Move button does the same by keyboard or touch).


## Group sessions (classes, workshops, lessons) - for gyms, studios and schools to build on

A class is a service offer of kind `class` with a capacity; one occurrence is a **session** (an appointment of kind `class`, shown in
`GET /api/v1/bookings/sessions`). Everything below is in `ziira.modules.bookings.public` (the signatures are kept stable; read its module
docstring) and also on HTTP.

* **Places**: `capacity` places, shared by people booked on and by places *held* for people on the waitlist who were offered one. The session
  row is locked for every change, so two desks (or a desk and a member) cannot take the last place together: one is booked, the other is
  put on the waitlist (`book_attendee(..., join_waitlist=False)` raises Conflict instead).
* **Waitlist**: a full class puts the person on the waitlist, in order. When a place frees (a cancellation, a bigger room, an offer that ran
  out) the first person waiting is **offered** it and the place is held for the business setting `waitlist_confirm_minutes` (default 30). A
  person is told (queued message `class_place_offered`) and the desk confirms for them (`confirm_waitlist_offer`, or the Classes screen).
  With a window of 0 the next person is put straight on the class (`class_booked`). An offer that runs out lapses (worker task
  `bookings.expire_waitlist_offers`, every 5 minutes) and the next person is offered the place.
* **Late cancellation**: `cancel_attendee` marks the attendee `late_cancellation` when the cancellation comes inside the class's own window
  (`group_late_cancel_hours`) or, if none, the business's `cancel_window_hours`. The unit that owns the credit decides what that costs.
* **Attendance**: `mark_attendee(..., "attended" | "no_show" | "booked")`. A class pack spends a credit on `class.attendee_attended`.
* **Closed days**: holidays are data (`/closed-days`); a weekly series skips them and says so. Clients cannot book a closed day.
* **Changes**: `set_session_capacity`, `substitute_session_resource` (another instructor or room), `cancel_session` (everyone is told, each
  cancellation is published with `session_cancelled = true` and `late = false`, the waitlist is cleared).
* **Events** (aggregate `bookings.appointment`, id = the session): `class.attendee_booked`, `class.attendee_cancelled` (`late`, `by_client`,
  `session_cancelled`), `class.attendee_attended`, `class.attendee_no_show`, `class.attendee_reset`, `class.waitlist_joined`,
  `class.waitlist_offered`, `class.waitlist_promoted`, `class.waitlist_expired`, `class.cancelled`, `class.resource_changed`. Every payload has
  `company_id`, `branch_id`, `appointment_id`, `offer_id`, `starts_at`; attendee events add `attendee_id` and `customer_id`.
* **Credits**: Bookings takes no money for a class. The unit that sells passes and packs subscribes to these events and spends or returns
  credits with the attendee id as the source (`memberships.consume_credit(..., source_type="class", source_id=attendee_id)`; give it back on
  a cancellation that is not late, on `class.attendee_reset` and on `session_cancelled`).
* Not done: booking a class from the public booking page, a confirm link in the "place is free" message (the desk confirms), a client's own
  quiet hours.

## Paying at the front desk with something other than money (`bookings.checkout_tender`)

A unit that holds credit the client can pay with (gift vouchers, loyalty points) implements `CheckoutTender` from `ziira.modules.bookings.public`
and plugs it in with `@provides("bookings.checkout_tender")` (declare `bookings.checkout_tender` under `[extends] implements`, and `bookings` under
`optional`). The checkout lists the kinds found, asks `balance(...)` for a code, and calls `redeem(...)` while completing the bill, inside the same
transaction: `redeem` takes up to `amount` from the credit, does its own books, and settles that much of the invoice with
`pos.public.settle_invoice_non_cash(session, invoice_id, applied, kind=..., reference=...)`. Bookings checks that the invoice came down by exactly
the amount, so a provider that forgets rolls the whole checkout back. See `docs/memberships.md` ("Paying at the front desk").


## Wave 2: what a working day needs

### Checkout (one screen from a visit to a paid bill)
`/checkout/<id>` (API `/api/v1/bookings/checkouts`). Opened from a checked-in, in-service or finished appointment (or a visit of several), or empty for a retail
sale. It holds: **service lines** (price editable, the person who gets the credit, a price variant), **retail products** (stock leaves through the invoice), **fees**
from earlier late cancellations or no-shows, a **discount with a reason** (a business limit above which a manager must approve), **credit** from a package or
membership (used by default when the client has some; the member's percent is applied to the rest), a **deposit** already held, **tips** per person (not
revenue), a **co-pay** and payer for insurers, and **split payments** (cash, mobile money, card, bank, other, plus other ways to pay from `bookings.checkout_tender`).
Completing is **one transaction**: spend credit, issue the invoice (Point of Sale), apply the deposit, take the payments, record tips and commission, finish the
appointments. If any step fails nothing is kept; completing twice returns the finished bill. A client with no credit limit can still pay at once (the invoice is
made knowing it is settled in the same transaction); one who leaves a balance is checked against their limit. A bill with no client uses a walk-in client account.
The front desk bills through the permission `bookings.checkout`, which lends `invoices.manage`, `receivables.manage`, `customers.manage` and
`bookings.manage` for the length of the call at that branch only (`services/delegate.py`): the Cashier role gets it by default.

### Walk-ins, the board and visits
`GET /front-desk/board` shows each person as free, busy until, processing (free while colour sets) or off, their next booking, the queue, who is arriving and
who is ready to bill. A walk-in (`POST /front-desk/walk-in`) starts now when someone is free, else joins the queue at the earliest time the calendar allows.
A **visit** (`POST /visits`) books several services one after another, each by anyone, all or nothing. A service can have **processing time** (the person is
free for N minutes inside it) and **prices by staff level** or named variants (`PUT /offers/{id}/variants`). The Rota (`GET /rota`) lists weekly hours and
time off; chair or room rent (`/rentals`) is invoiced each period by the worker, once per period.

### Policies: deposits, fees, recalls
Per service: deposit (percent or amount; an online booking that needs one waits as a request until it is recorded: `POST /appointments/{id}/deposit` keeps the
money on the client's account and the checkout uses it), "due again after N days", "needs a patch test". Per business: late-cancel and missed-appointment fee
percents (a line on the client's next bill; waive with a reason), a fee service item, the patch-test validity, rebook-invitation delay, reminder/recall/rebook
wording. `GET /recalls` lists clients due again with nothing booked; reminders and the rebooking invitation are queued by the worker (outside quiet hours, once
per visit, never to someone on the do-not-contact list); an outcome (phoned, declined, snoozed) keeps the list honest.

### Commission, tips, day end
Rules (percent or fixed, per service or product, per person, level or service; the most specific wins) are data. Every checkout writes **immutable commission
lines** (a reversal adds negative ones); `GET /commission/report` shows per person services, products, commission and tips kept apart; `public.commission_figure`
gives Payroll one number for a period. Commission is information: nothing is paid or posted. Tips held for staff (card, mobile money) are owed until
`POST /tips/pay-out`; no ledger entry is made (not revenue). `GET /day-end` gives takings by method, services/products/fees, discounts, credit used, tips,
commission, no-shows, late cancellations, walk-ins, visits not billed and bills still owing.

### Client card, photos, documents
`bookings.client` is a custom-field record type (preferred staff, allergy note, formula, patch-test date ... from a pack or the business) and an attachable record
type (before/after photos with a consent note, consent forms, referral letters) through the files service; `bookings.appointment` likewise. `GET /clients/{id}/card`.

### Insurers and schemes
See `docs/pack_clinic.md`. Without Claims the checkout splits the bill between the patient's co-pay and a payer's customer account. With Claims on,
`POST /appointments/{id}/claim` opens a claim and Claims invoices that appointment.

### Public interface additions
Events: `checkout.completed`, `checkout.voided`, `appointment.deposit_paid`, `client.fee_added`, plus the group-session events above. Extension point
`bookings.checkout_tender`. `public.py`: group sessions, `commission_figure`. Additive functions in `pos.public` used here: `take_payment`, `customer_credit`,
`apply_account_credit`, `settle_invoice_non_cash`, `issue_invoice_from_lines(location_id=, settled_now=)`. Worker tasks: `bookings.expire_waitlist_offers`,
`bookings.send_recalls`, `bookings.run_rentals`. Intelligence: `bookings.tips_held`, `bookings.deposits_unpaid` (and `completed_not_invoiced` ignores visits billed by checkout).

### Known gaps
No online payment link for deposits (a person records it); no confirm link in the "place is free" message (the desk confirms); class booking is not on the
public page; drag-and-drop works with a mouse only; a one-off date with different hours (use time off) is not modelled; tips are not posted to the books;
commission edits cannot clear a rule's person/level (add a new rule).

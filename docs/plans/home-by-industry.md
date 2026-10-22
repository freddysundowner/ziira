# Home and sidebar by kind of business

One resolver decides the kind: `profileFor(editionId, enabledUnits)` in `frontend/src/sdk/kindProfile.ts`. A switched-on industry pack
(`pack_clinic`, `pack_garage`, `pack_fitness`, `pack_salon`, `pack_professional`, `pack_education`, `pack_pharmacy`) wins; otherwise the edition
(`retail`, `distribution`, `books`, `intelligence`, `services`); anything else is `full`. The sign-up "business type" is only a hint stored in
`master.tenant.onboarding` (not exposed to the business's API); what it chooses (an edition or a pack) is what the web app reads.

## Where the data lives
- `sdk/kindProfile.ts`: `SIDEBAR[kind]` = area order after Intelligence, areas open by default (1-3), `till` (show Point of sale and
  Tills and devices). With `till: false` Sell is titled "Invoices and payments" (`nav.areas.sellNoTill`). Hiding only hides menu entries.
- `shell/homeProfiles.ts`: `PROFILES[kind]` = `stats` (first four that exist become number tiles; topped up to 3 from other boxes),
  `lists`, `areas` (shortcut order); `WIDE` = tiles with several figures. A box is named by its `dashboard.widgets` label (`W`).
  Boxes not placed go behind "More". A box whose unit is off or permission missing never appears.
- Sidebar: `buildNavigation(modules, access, groups, plan)`; `Layout.tsx` passes the plan; `Sidebar.tsx` opens `plan.open` plus Intelligence plus
  the current section; a hand-made choice (`ziira.sidebar.sections`) wins.

## What each kind sees (tiles first row; list rows after)
| Kind | Tiles | Lists |
|---|---|---|
| retail | sales today, open tills, low stock, things to look at | approvals, exceptions, payments, today's figure |
| distribution | sales (orders), owed by customers, low stock, bills to pay | things, approvals, exceptions, payments |
| books | cash and profit, owed by customers, bills to pay, payments today | bank to match, things, approvals, exceptions |
| intelligence | things to look at, today's figure, connections | approvals, exceptions |
| salon | appointments today, free now, checkouts waiting, sales | due again, things, approvals, exceptions, people |
| clinic | appointments today, due again (recalls), claims waiting, owed | things, approvals, exceptions, people, payments |
| gym | check-ins today, class fill, expiring memberships, payments late | appointments, payments, things, approvals, exceptions, people |
| education / services | appointments today (+ jobs, work, payments) | things, approvals, exceptions, people (+ checkouts waiting, deadlines for services) |
| garage | jobs board (in progress, to collect, late), estimates awaiting approval, waiting for parts | waiting for insurer, claims waiting, approvals, exceptions, things, low stock, bills, owed, sales |
| professional | work to bill, deadlines, approvals, owed | things, exceptions, people, appointments |
| pharmacy | sales today, expiring soon (inventory), low stock, things to look at | approvals, exceptions, bills to pay, payments |
| full | sales, things, low stock, owed | approvals, exceptions, bills, payments, figure |

Sidebar: retail Sell, Stock (open); distribution Sell, Buy, Stock (open); books Money, Buy (open); service kinds Services, Customers (open),
no till; garage Services, Sell (open); professional Services, Customers (open).

## Notices are not cards
`BillingNotice` (all pages) renders `NoticeStrip`: one line, icon, message, "Open Plan & billing". On Home it also says when a longer trial ends.
Hidden for the session only for a running trial (`dismissible`); never an ended trial, ended plan or overdue payment. The old
dashboard card (`BillingBannerWidget`) is removed.

## Widgets
A widget gets `variant="stat"` in a tile (number + one context line) or `"full"`. A list widget with nothing to show marks its text
`data-clear`; `WidgetCard` then shrinks it to a one-line "all clear" row at the end. Several figures in a row use `StatRow` + `Figure` (sdk/ui),
never hand columns (wrap-safe, labels small and sentence case, figures on one baseline, long values wrap).

## Adding a kind
1. Add the id to `ProfileId` and its pack/edition to `PACKS`/`EDITIONS` (kindProfile.ts). 2. Add a `SIDEBAR` and a `PROFILES` row.
3. A new box: register it in the module's `dashboard.widgets` with a label key, add the key to `W`, support `variant`. Tests: `homeProfiles.test.ts`,
`sdk/areas.test.ts`.

## Built boxes (counting boxes)
All use `HomeBox` (`sdk/ui/homeBox.tsx`): a tile (number + one line) or a full box (number, a few rows, a link); loading is a skeleton, an error says
what went wrong with "Try again", and nothing to show is a `0` and a plain line in a tile or the one-line "all clear" row in a list. The module that owns the
data registers the box in its `dashboard.widgets`; no box invents a figure, each reads an endpoint that already existed (one small field was added, below).

| Box (label) | Module, permission | Reads | Counts |
|---|---|---|---|
| Free now `bookings:widget.freeNow` | bookings, `bookings.view` | `GET /bookings/front-desk/board` | people/rooms working now and free (name and "free for N min") |
| Checkouts waiting `bookings:widget.checkoutsWaiting` | bookings | same board (one request shared) | visits finished or in service and not billed (`to_bill`) |
| Due again `bookings:widget.dueAgain` | bookings | `GET /bookings/recalls` (200, "200+") | clients due for their service again with nothing booked |
| Class fill `bookings:widget.classFill` | bookings | `GET /bookings/sessions` (next 7 days, first 5) | places taken over places in all, cancelled classes ignored |
| Estimates awaiting approval, Waiting for parts, Waiting for insurer `jobs:widget.approvalTitle/partsTitle/insurerTitle` | jobs, `jobs.view` | `GET /jobs/jobs/board` (`waiting_on`, shared with the jobs box; "+" when truncated) | jobs held up by that reason; the insurer box is left out when Claims is off |
| Claims waiting `claims:widget.title` | claims, `claims.view` | `GET /claims/claims?open_only=true` | claims waiting on the payer, and offers from the payer we must answer (shown first) |
| Check-ins today `memberships:widget.checkinsTitle` | memberships, `memberships.view` | `GET /memberships/checkin/today` | visits, and how many were turned away |
| Expiring memberships `memberships:widget.expiringTitle` | memberships | `GET /memberships/summary` (new field `ending_30_days`) | memberships whose scheduled end or fixed end date falls in 30 days; renewals in 7 days and packages running out are separate lines (renewing is not ending) |
| Payments late `memberships:widget.lateTitle` | memberships | `GET /memberships/arrears` (100, "100+") | members who owe, and the sum (exact decimals) |
| Deadlines `timebilling:widget.deadlinesTitle` | timebilling, `time.view` | `GET /timebilling/tasks?status=open&due_before=+7 days` | work due within 7 days or already late (late shown in red) |
| Bank to match `payments:bankToMatch.title` | payments, `payments.view` | `GET /payments/transactions?match_status=unmatched` and `proposed` | provider/bank lines with no payment matched, and suggested matches waiting for a yes |

"Unbilled work" already existed as the Time and billing box (`timebilling:widget.title`); "Bank to match" lives in Payments because that unit holds the
statement lines (Finance's reconciliations are a screen, not a count). Tests: each module's `slots/widgets.test.tsx` (data, empty collapse, errors,
shared requests), `sdk/ui/homeBox.test.tsx`, `shell/homeProfiles.test.ts`; the shared fakes are in `src/test/widgetKit.tsx`.

## Not available yet
Nothing from the earlier list. Possible later: recall boxes only count the first 200 clients; class fill is for the branch chosen in Bookings.

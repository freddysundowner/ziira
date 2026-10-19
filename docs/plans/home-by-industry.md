# Home and sidebar by kind of business

One resolver decides the kind: `profileFor(editionId, enabledUnits)` in `frontend/src/sdk/kindProfile.ts`. A switched-on industry pack
(`pack_clinic`, `pack_garage`, `pack_fitness`, `pack_salon`, `pack_professional`, `pack_education`) wins; otherwise the edition
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
| books | cash and profit, owed by customers, bills to pay, payments today | things, approvals, exceptions |
| intelligence | things to look at, today's figure, connections | approvals, exceptions |
| salon / clinic / gym / education / services | appointments today (+ sales or payments, things) | approvals, exceptions, people |
| garage | jobs board (in progress, to collect, late), sales, owed, things | approvals, exceptions, low stock, bills |
| professional | work to bill, approvals, owed, appointments | things, exceptions, people |
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

## Not available yet (no widget or API)
Who is free now, checkouts waiting, due-again clients (salon); estimates awaiting approval, waiting for parts (garage); recalls due, claims waiting
(clinic); check-ins, expiring memberships, class fill (gym); deadlines (professional); bank to match (books). Nearest existing boxes are used.

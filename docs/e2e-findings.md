# End-to-end findings

What the real-browser journeys (`make e2e`, see `docs/testing.md`) found in the web app and the API behind it. "Fixed"
means fixed in the same change that added the journeys, and the journey would fail again if it came back.

## Fixed

| # | Where | What was wrong | Fix |
|---|---|---|---|
| 1 | `frontend/src/sdk/ui/forms.tsx` (`Field`) | When a control sat inside a wrapper (the sign-in password with its show/hide button, the "spread one payment" box, every input with a button beside it) the label was attached to the wrapper, not the input: screen readers announced an unnamed text box and clicking the label did nothing. | `Field` now gives its id through a context that `Input`, `Select` and `Textarea` pick up. |
| 2 | `sdk/ui/combobox.tsx` | The searchable pickers (product, supplier, customer, account) had no accessible name. | `aria-label` from the placeholder and selection when no `Field` labels it. |
| 3 | `products/pages/SetupPage.tsx` | The Save button on the unit, tax code and price list drawers read "Save product". | New `saveSetup` string ("Save"), English and Swahili. |
| 4 | `purchasing/pages/OrderFormPage.tsx`, `RequestDrawer.tsx` | Opening **New order** directly (page load, bookmark, refresh) sent `company_id: ""` and the API answered 422: the company was copied into state before the company list had loaded. | The id is derived (`chosen || first company`) instead of frozen in state. |
| 5 | `crm/components/ReceivePayment.tsx` | A business with one branch could not receive a customer payment: the branch picker is hidden for one branch, so no branch was sent and the API refused ("Say which branch is taking the payment"). | The first branch is the default and is sent; the picker (several branches) no longer offers "Any branch". |
| 6 | `pos/terminal/components/CartPanel.tsx` | A `<p>` inside the cart's `<dl>` (invalid markup, flagged as serious). | Moved outside the list. |
| 7 | `sdk/ui/layout.tsx` (`Tabs`) | Tab buttons had no `type="button"`: a tab inside a form would submit it. | Added. |
| 8 | Colours: `index.css`, `forms.tsx`, `shell/AuthShell.tsx`, `shell/Layout.tsx`, 20 link and button classes | Contrast below 4.5:1 (WCAG AA): the primary button (white on teal 3.7:1), links in `text-brand` (3.5:1), the sidebar group labels (`text-muted/80`), status badges (ok, warn, bad, info soft backgrounds), placeholders (`text-muted/70`), the sign-in panel's grey text, "Import another file". | Primary buttons use `brand-strong`; links use `text-brand-strong`; the light-theme status colours are darker (all above 5:1 on their soft background); opacity tints removed from small text. Dark theme was already fine. |

## Found, not fixed

| # | Where | What | Why not fixed / suggestion |
|---|---|---|---|
| A | Several lists (users, price lists, API keys; one run each) | A list did not show the record just created, although it existed on the server, for more than 10 seconds. Three times in about 60 runs; not reproduced in 150 create-then-list loops against the API, nor in 5 loops in the browser. | Not understood. The journey harness now prints the last 25 API calls of a failing test, so the next occurrence shows whether the list was fetched before the create finished. Worth a look: `db_session` (`ziira/sdk/__init__.py`) commits when its generator exits, and FastAPI 0.118+ runs that **after** the response is sent, so a very fast refetch could read before the commit. `Depends(db_session, scope="function")` would commit first; it touches about 390 route signatures, so it needs the owner's decision. |
| B | Paying a supplier bill with no payment account set up | The page shows no "Pay from" list and the API refuses ("Choose the payment account the money went through"): the user has no way forward on that screen. | Say where to add an account (Payments > Accounts) or hide the pay button until one exists. |
| C | `/finance/bank` (Start reconciliation) | The account list offers every asset account (receivables, inventory...) although the hint says "bank, mobile money or card". | Filter to cash/bank/clearing subtypes. |
| D | Expense category list | Starts with Cost of goods sold, Inventory shrinkage, Purchase price variance (system accounts). | Offer operating expense accounts first or only. |
| E | Till terminal: a mobile-money sale without a mobile-money account | The refusal is clear but shows the code word `mobile_money` ("No mobile_money account is set up for this branch"). | Backend message: use the display name. |
| F | `/pos/terminal` payment dialog | The "Handed over" label sits above the amount while the "Balance" button is beside it, so the row looks misaligned. | Cosmetic. |
| G | Intelligence, new business | The first findings are "Olive Owner was given the role Owner" and the same for the second user: noise on day one. | Skip the role grants made at registration, or make them informational. |
| H | `POST /api/v1/intel/run` | Took about 4.4 s for a business with almost no data, in the request. | Fine for a button, but it will grow with data; consider running it as a background job like the imports. |
| I | `ziira worker` | With no work to do it logs "Retention applied: {...}" once a second per business. | Log only when something was changed, or run it once a day. |
| J | `/finance/reports/<unknown>` | An unknown report name silently shows Profit and loss. | Redirect to the default URL. |
| K | Branch-limited users | The journeys cannot test "sees only their own branch's data": a business can have one branch in the UI, and there is no branch-creation screen or API (only the CLI). J8 checks the role limits (what a Cashier sees and may open) instead. | Add a branch screen, then extend J8 with two branches. |

## Not covered by the journeys

Sandbox-only integrations (Daraja prompts against the real service, SMS and email gateways), printing, the offline
queue of the till, two-step sign-in (the suite starts with `ZIIRA_MFA_DEFAULT_POLICY=off`), Swahili, dark mode, phone
width, and the privacy and support pages (being rebuilt by another change).

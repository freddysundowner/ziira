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
| 9 | `purchasing` pay screens (`components/PayFrom.tsx`) | Paying a supplier with no payment account left no way forward: no "Pay from" list, and the API refused ("Choose the payment account the money went through"). | A business with no account for the chosen method sees why, and a person who may manage payment accounts adds a bank or card account in place (it is chosen at once); mobile money, which needs provider set-up, links to Payments; someone without the right is told who can. The Pay button stays off until an account is chosen. Cash needs none (the branch's till cash is made on first use). J4b. |
| 10 | same, found by J4b | The add-account drawer's submit also submitted the payment page's own form (React events bubble through a portal), which opened the "Confirm payments" dialog behind it. | `stopPropagation` in the drawer's submit. |
| 11 | `finance/pages/BankPage.tsx` | The reconciliation account list offered every asset account (receivables, inventory...). | Only cash, bank, mobile-money and card clearing accounts (`MONEY_SUBTYPES`; the chart already carries the subtype, no migration). J6. |
| 12 | `finance/components/ExpenseDrawer.tsx` | The category list started with accounts the system posts by itself (cost of goods sold, shrinkage, price variance). | Those, till variances and employer payroll costs are left out (`SYSTEM_EXPENSE_SUBTYPES`). J6. |
| 13 | `finance/pages/ReportsPage.tsx` | An unknown report name silently showed Profit and loss. | A "This report does not exist" state with a link to the reports. J6. |
| 14 | `kernel/auth.py` (`complete_mfa`) | **Signing in with a backup code answered 500**: the audit entry for a used backup code needs a request context and none was set yet. (The pytest client reuses its worker's context, which hid it.) | The context is set before the code is checked; `test_a_backup_code_signs_in_in_a_request_with_no_earlier_context` runs the call in an empty context. J12. |
| 15 | `shell/Home.tsx` | At phone width the home page was 732px wide: an automatic grid column grew to the widest widget. | `grid-cols-1` and `min-w-0`. J14. |
| 16 | `pos/terminal/components/Frame.tsx` | On a phone the terminal's way back to the office was an icon-only link with no accessible name (the text is hidden below the small breakpoint). | `aria-label`. J14. |
| 17 | `purchasing/components/SupplierReconcileTab.tsx` | A failed reconciliation showed two toasts (its own and the mutation cache's). | `meta: { silent: true }`; `sdk/toastOnce.test.ts` fails when any `useMutation` toasts its own error without it. |
| 18 | `pos/services/*` | "No mobile_money account is set up for this branch" showed the code word. | "No mobile money account...". J3. |
| 19 | `kernel/privacy.py` | The daily retention task logged `Retention applied` for every business each time it ran, with nothing changed. | Logged only when something changed (the task itself runs once a day per business). |
| 20 | `sdk/i18n.ts` | The page's `lang` stayed `en` in Swahili. | It follows the chosen language. J13. |

## Settled since the first pass

| # | What | Outcome |
|---|---|---|
| A | A list sometimes missing the record just created | Not seen again since "commit before the reply is sent" (`db_session` now commits before the response leaves; `tests/test_commit_before_reply.py`), through the 19 journey tests that now run. Kept here in case it returns: the failing test prints the last API calls. |
| G | First Intelligence findings about the owner's own role | The check ignores grants made at registration; J9 asserts the owner's role is not a finding. |
| K | Branch-limited users could not be tested with two branches | Branches are managed in Settings > Organisation (`docs/organisation.md`); J8b adds a second branch, a scoped manager, a sale and a short till at each branch, and checks screens and API (403 or 404 for the other branch). |

## Found, not fixed

| # | Where | What | Why not fixed / suggestion |
|---|---|---|---|
| F | `/pos/terminal` payment dialog | The "Handed over" label sits above the amount while the "Balance" button is beside it, so the row looks misaligned. | Cosmetic, in the offline till's files (another change is working there). |
| H | `POST /api/v1/intel/run` | Took about 4.4 s for a business with almost no data, in the request. | Fine for a button, but it will grow with data; consider running it as a background job like the imports. |
| L | Cash supplier payment on a bill with no branch | `Choose the payment account the money went through`: a bill made without a branch has no till-cash account to use. | The payment page shows the message against the bill. A bill's branch is optional by design; ask for one when paying in cash if this proves common. |

## Not covered by the journeys

Sandbox-only integrations (Daraja prompts against the real service, SMS and email gateways); a real printer (print mode and PDF output
are checked, not paper); a real phone (a 390 x 844 Chromium window, not touch gestures or a mobile keyboard); a screen reader; two-step
sign-in with a real authenticator app (the codes are made in the test with the same algorithm, checked against the RFC 6238 vector);
Swahili wording (the journeys find missing and raw text, not whether a translation reads well); dark mode by eye (contrast and
light backgrounds are scanned); the AI layer.

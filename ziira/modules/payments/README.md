# Payments and Reconciliation

**Status:** working for phase 4 (the payments core): payments, mobile-money payment prompts and till callbacks, statement
import, the matching engine, settlements and cash deposits, and the daily close. **The module knows no provider.** A provider
(M-Pesa's Daraja is `ziira/plugins/mpesa`; see `docs/plugin-audit.md`) is a plugin that implements the `payments.provider`
extension point; its request and callback formats were written from public documentation and have **not been tried against
the real service**: test them in the provider's sandbox before going live (see "Going live"). Card and bank-feed connectors
are not built (statements are imported as files).

| | |
|---|---|
| Schema | `payments` (migrations `0001` to `0005`) |
| Requires | kernel only |
| Optional | pos, crm, finance |
| Publishes | `payment.received`, `payment.made`, `payment.matched`, `payment.unmatched`, `payment.settled`, `payment.banked`, `stk.completed`, `close.completed`, `close.variance` |
| Subscribes | `approval.decided` (kernel): reopens a locked day once approved |
| Offers | extension points `payments.provider` (a way to ask for money and read what the provider reports: formats, credential and settings forms, limits) and `payments.statement_format` (a statement format people upload) |
| API | `/api/v1/payments`; providers' callbacks under `/api/v1/payments/callbacks/...` (no sign-in; secret in the URL); `GET /providers` describes the providers switched on, as data |
| Permissions | `payments.view`, `payments.record`, `recon.match`, `close.submit`, `close.reopen`, `payments.manage`, `payments.collect` |
| Background jobs | `payments.send_stk`, `payments.check_stk`, `payments.match` (run by `ziira worker`) |

## How it works

- **One payments model.** Cash, mobile money, card and bank money all become a `payment` with allocations to documents. POS
  and people record payments through `public.record_payment`. A locked day refuses changes.
- **External transactions** are what the provider says happened (C2B confirmations, STK results, imported statements).
  Each is recorded once per provider reference; a repeated reference with another amount is flagged, not overwritten.
- **Matching** pairs payments to external transactions in stages: exact reference, paybill account number, then scored
  rules (applied at 0.9 or more, otherwise only proposed). Every match records its stage and can be undone; matched
  amounts never exceed either side. Anything nobody claims goes to the exceptions inbox.
- **STK push.** `POST /intents` stores the request (the phone number is masked, hashed and held encrypted in the job only);
  the worker sends it through the account's provider; the provider's callback (signed URL) or a status check settles it. A refusal marks it failed and
  flags it; an outage retries with backoff; an unanswered prompt times out.
- **Daily close.** Counts the day's takings against what the provider covered, records the cash banked, requires an
  explanation for any variance, and locks the day. Reopening goes through the approval matrix (`daily_close`).
- **Settlements and cash deposits** record money moving between the business's own accounts; Finance posts them from the
  events.

## Going live

1. Switch on the provider's plugin (Add-ons), create the mobile-money account with that provider (an account with no
   provider is `manual`: payments are recorded by hand or from statements), set its credentials (the form the provider
   describes), and generate its callback token.
2. Register the returned URLs with the provider (till callbacks; prompt callbacks are sent per request).
3. Run the sandbox flows end to end, then check the real responses against the plugin's code before switching
   `environment` to `production`.

## Layout

```
api/          routes.py (router + public callbacks), schemas.py, callbacks.py
services/     one file per use case
domain/       mobile_money (neutral values), matching (scoring), statements (bank CSV and helpers for plugins): no database or HTTP
repository/   models.py, payments_repo.py
hooks.py      declares the provider and statement-format extension points
jobs.py       background jobs
events.py     handler for approval.decided
public.py     what other units may import, with the PaymentProvider and StatementReader contracts a provider plugin implements
tests/        domain tests (flows are in the top-level tests/; the provider's tests are in its plugin)
```

# Payments and Reconciliation

**Status:** working for phase 4 (the payments core): payments, M-Pesa STK push and C2B, statement import, the matching
engine, settlements and cash deposits, and the daily close. The Daraja request formats were written from the public
documentation and have **not been tried against Safaricom**: test them in the sandbox before going live (see "Going
live"). Card and bank-feed connectors are not built (statements are imported as files).

| | |
|---|---|
| Schema | `payments` (migrations `0001_init`, `0002_phase4`) |
| Requires | kernel only |
| Optional | pos, crm, finance |
| Publishes | `payment.received`, `payment.made`, `payment.matched`, `payment.unmatched`, `payment.settled`, `payment.banked`, `stk.completed`, `close.completed`, `close.variance` |
| Subscribes | `approval.decided` (kernel): reopens a locked day once approved |
| Plugs into | extension point `payments.provider` (Daraja and a fake for tests are built in) |
| API | `/api/v1/payments`; Safaricom's callbacks under `/api/v1/payments/callbacks/...` (no sign-in; secret in the URL) |
| Permissions | `payments.view`, `payments.record`, `recon.match`, `close.submit`, `close.reopen`, `payments.manage`, `payments.collect` |
| Background jobs | `payments.send_stk`, `payments.check_stk`, `payments.match` (run by `ziira worker`) |

## How it works

- **One payments model.** Cash, M-Pesa, card and bank money all become a `payment` with allocations to documents. POS
  and people record payments through `public.record_payment`. A locked day refuses changes.
- **External transactions** are what the provider says happened (C2B confirmations, STK results, imported statements).
  Each is recorded once per provider reference; a repeated reference with another amount is flagged, not overwritten.
- **Matching** pairs payments to external transactions in stages: exact reference, paybill account number, then scored
  rules (applied at 0.9 or more, otherwise only proposed). Every match records its stage and can be undone; matched
  amounts never exceed either side. Anything nobody claims goes to the exceptions inbox.
- **STK push.** `POST /intents` stores the request (the phone number is masked, hashed and held encrypted in the job only);
  the worker sends it; Safaricom's callback (signed URL) or a status check settles it. A refusal marks it failed and
  flags it; an outage retries with backoff; an unanswered prompt times out.
- **Daily close.** Counts the day's takings against what the provider covered, records the cash banked, requires an
  explanation for any variance, and locks the day. Reopening goes through the approval matrix (`daily_close`).
- **Settlements and cash deposits** record money moving between the business's own accounts; Finance posts them from the
  events.

## Going live

1. Create the M-Pesa account (`provider: daraja`), set its credentials, and generate its callback token.
2. Register the returned URLs with Safaricom (C2B validation and confirmation; STK callbacks are sent per request).
3. Run the sandbox flows end to end, then check the real responses against `providers.py` before switching
   `environment` to `production`.

## Layout

```
api/          routes.py (router + public callbacks), schemas.py, callbacks.py
services/     one file per use case
domain/       mpesa (parsing), matching (scoring), statements (parsers): no database or HTTP
repository/   models.py, payments_repo.py
providers.py  DarajaProvider and FakeProvider
hooks.py      registers the providers
jobs.py       background jobs
events.py     handler for approval.decided
public.py     what other units may import
tests/        domain and provider tests (flows are in the top-level tests/)
```

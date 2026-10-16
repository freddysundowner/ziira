# Subscription payments: a business pays its own invoices

A business owner can choose a plan and pay the invoice in the app, with M-Pesa (a prompt on the phone) or a card, when its
trial or plan ends. This is **how the vendor gets paid**, not how a business takes money from its customers (that is the
`payments` module). Related: `docs/platform-admin.md` (billing, dunning), `docs/security.md`, `docs/localisation.md`.

## How it fits together

```
owner: Plan & billing ──▶ "Choose a plan" ──▶ POST /billing/subscribe        plan request + invoice, issued at once
                          "Pay now"       ──▶ GET  /billing/pay/options       which providers serve this invoice
                                          ──▶ POST /billing/payments          start an attempt (one open per invoice)
                                                 │ platform/payments.py       provider.start()
                                                 ▼
                          prompt flow:  phone prompt ── owner enters PIN        redirect flow: provider's page ── back to
                          app polls GET /billing/payments/{id} every 3 s        /billing?attempt=ID&payment=success|cancelled
                                                 │
 provider ──signed notification──▶ POST /billing/webhooks/<provider>  (public; signature on the RAW body first)
                                                 │ only makes us ASK
                                                 ▼
                          provider.check()  ── status + amount + currency + invoice reference must all match
                                                 │ yes                              │ no
                                                 ▼                                  ▼
              billing.record_payment (method, reference)        status `mismatch`, emailed to billing operators,
              invoice paid, subscription active at once,        nothing credited
              receipt emailed
 worker, every minute: recover_pending()  ── asks about open attempts (young ones each pass, older hourly), fails ones that
                                              never reached the provider, expires after 24 h. Lost notifications recover here.
```

The rules that hold for every provider:

* **Confirm before credit.** A notification or a browser return never credits anything; it makes the platform ask the provider
  (`check`). Credit needs: status completed, amount equal to the attempt's (exact decimal), currency equal, and the invoice
  reference equal where the provider reports one.
* **Safe under concurrency.** The attempt row is locked while it is settled; two notifications and the poller at once credit
  once (`tests/test_subscription_payments.py`). A crash between recording the payment and closing the attempt is healed by a
  lookup of the provider reference on the invoice's payments.
* **One open attempt per invoice** (unique partial index). A second click returns the first attempt; after the provider's
  `retry_after_seconds` the old attempt is asked about once more, then replaced. At most **5 attempts per business per hour**.
* **Never convert currencies.** A provider serves the currencies it declares; with none that fits, the owner sees the
  provider's own hint (for example "ask us for a KES price") and the manual payment instructions.
* **Personal data.** The payer's phone number is not stored: only its last four digits and a keyed hash (to answer a data
  request; `kernel.payment_payers` privacy provider). A receipt email is kept on the attempt and removed on erasure.
* **No country in code.** Currencies, countries, payer fields, settings and wording come from the plugin's declaration;
  `ziira/kernel` and `ziira/modules` name no provider (`tests/test_architecture.py`).

## Providers are plugins

A provider is a plugin that sets `platform_scope = true` in its manifest, lists `implements = ["kernel.payment_gateway"]` and
registers a `PaymentGateway` subclass in `hooks.py` (`provides("kernel.payment_gateway")`). It is found at platform level
(`extensions.implementations_of`), so it appears in the Super Admin once installed (`ziira install --all`) and **no business
switches it on** (it is hidden from Apps & plugins and refused by `enable`). The contract is in
`ziira/kernel/platform/gateways.py`:

| Attribute / method | Meaning |
|---|---|
| `name`, `title`, `pay_label`, `description` | identity and wording |
| `flow` | `prompt` (a prompt on the phone, live status) or `redirect` (the provider's page) |
| `currencies`, `countries` | what it serves; empty means any |
| `currency_hint` | shown when the country fits but the currency does not |
| `config_fields` | `SettingField`s the operator enters; `secret=True` ones are write-only and encrypted |
| `payer_fields` | what the payer is asked for (`phone`, `email`) |
| `normalise_payer`, `validate_config` | clean and check input (raise `ValidationFailed`) |
| `start`, `check`, `verify_webhook`, `test_connection` | the four provider calls; they receive an `httpx.Client` made by `gateways.new_http_client()` (tests replace `gateways.http_client_factory` with a `MockTransport`) |

Errors: raise `GatewayError(message, retryable=...)`; `classify_response` maps HTTP statuses (5xx and 429 retryable, other 4xx
not; a 401/403 says the key was not accepted). Messages are shown to people: never put a key or a full phone number in one.

Installed now: `billing_sunpay` (M-Pesa through SunPay, KES, Kenya), `billing_stripe` (cards, hosted Checkout, any currency),
`billing_paystack` (cards and bank, NGN GHS ZAR KES USD).

## Choosing what to offer

`payments.options_for(tenant, invoice)`: the providers that are **enabled** by the operator, **configured** (every required
setting and secret present), serve the **invoice currency**, and serve the business's **country** (its first company's; if
unknown, country-limited providers are still offered). Providers whose "Preferred for" list holds the currency or country come
first. One qualifying provider: the dialog goes straight to its fields; several: a "Pay with" choice; none: the hint plus the
manual instructions (`billing.payment_instructions`). Setting: Super Admin > Billing > Payment methods > "Preferred for".

## Settings (Super Admin > Billing > Payment methods)

One card per installed provider: an on/off switch, its settings, its secrets (write-only: the field shows "set" and a new
value replaces it; "Remove" clears one), "Preferred for" codes, **the notification address to register with the provider**
(built from `ZIIRA_PUBLIC_BASE_URL`; withheld, with a reason, when that is `http://` and not local), and **Test connection**
(a harmless call that does not move money). Changing or testing needs `platform.billing` and a fresh second factor and is
written to the operator trail with the field *names* only. A provider cannot be switched on until it is configured.

Stored in `master.payment_gateway` (secrets as a Fernet token under `ZIIRA_CREDENTIALS_KEY`: losing that key loses them).
Notifications are still processed for a provider that was switched off while a payment was in flight.

## The attempt record

`master.payment_attempt`: invoice, business, provider, amount, currency, status (`initiated`, `pending`, `completed`,
`failed`, `expired`, `mismatch`), the provider's ids, the payment reference, a plain reason, phone last four + keyed hash,
timestamps. `master.payment_attempt_event` is its append-only timeline (the database refuses update and delete) and also holds
the notification keys already handled (a repeat is ignored). Super Admin > Billing > Payment attempts lists them (status filter),
opens the timeline, and offers **Re-check now** and **Mark as paid manually** (reason required; it credits through the same
payment service and says so in the timeline). An invoice's drawer lists its attempts.

## In the business app

* Plan & billing shows the **amount due** with "Pay now", a **Choose a plan** step (interval, optional coupon) that creates the
  invoice at once, and the invoices list with "Pay now" and "Receipt" (the printable invoice, which shows it paid).
* The pay dialog: choose a method if several, type what it asks for, confirm the amount. Prompt flow: "Check your phone and enter
  your PIN", a 2-minute countdown, then "We have not heard back: if you paid, it will appear shortly" with **Check again**.
  Redirect flow: the browser goes to the provider and comes back to `/billing?attempt=ID&payment=success|cancelled`; the page
  then follows the attempt exactly like a prompt (the return is never trusted: the status comes from the server).
* A suspended business: the owner is sent straight to Plan & billing with "Your trial ended on <date>. Choose a plan to keep
  going. Your data is safe." (all of `/api/v1/billing/*` stays reachable; other routes still answer 402). Banners for a trial
  ending within a week, an overdue payment and an ended plan show above every page for owners. Reminder and renewal emails link
  to `<ZIIRA_PUBLIC_WEB_URL>/billing`.
* Only a user with `billing.manage` can see options, pay or read an attempt; a business never sees another's.

## SunPay (M-Pesa)

Settings: `base_url` (default **https://sunpay.co.ke**; SunPay's documentation page prints `api.sunpay.co.ke`, which the owner says
is wrong, so the address is a setting), `api_key` (secret, `sp_...`), `webhook_secret` (secret). Currency KES, country KE, prompt flow.

* Start: `POST {base}/api/v1/payments/stk-push` with `Authorization: Bearer <key>` and `{"phoneNumber": "254XXXXXXXXX", "amount":
  <number>, "externalRef": "<invoice number>"}`. The per-transaction `callbackUrl` is **not** sent (it is unsigned).
* Check: `GET {base}/api/v1/payments/{transactionId}` -> `status` pending | completed | failed, `amount`, `mpesaRef`.
* Notification: `X-Webhook-Signature` = hex HMAC-SHA256 of the raw body with the webhook secret; events `payment.completed` and
  `payment.failed` (settlement and withdrawal events are ignored); deduplicated by event + transaction id.
* Phone numbers: `07..`, `01..`, `+254..`, `254..` or `7..` become `254XXXXXXXXX`; anything else is refused. Helper text: "The
  number that will receive the M-Pesa prompt".

**UNVERIFIED (written from the public documentation, never run against SunPay):**
1. every request and response field name above (the documentation shows examples only);
2. that the status endpoint accepts the `transactionId` and answers 404 for an unknown id (used by Test connection: 404 means
   "key accepted", 401/403 "rejected");
3. that the status response carries no `externalRef`, so the invoice reference cannot be re-checked there (the transaction id we
   stored at start, the amount and the status are what is checked);
4. what a cancelled or timed-out prompt reports (`failed` is assumed) and how long a pending payment can stay pending;
5. retries of notifications, sandbox or test numbers, idempotency of the STK push, rate limits and the error body format
   (none documented: a refusal's `message` or `error` text is shown when present);
6. whether `amount` is returned as a number or a string (both are read) and whether partial amounts can occur.

Live-test checklist: SunPay sandbox/test key if any (otherwise a real key with KES 1); create a plan priced KES 1 and an invoice;
pay with your own number; check the STK push body in SunPay's dashboard; register the notification address and secret; confirm
the signature verifies (a bad secret must give 401 in the logs); cancel the prompt on the phone (expect "failed" with a plain
reason); let one time out (expect the timeout message, then Check again); disable the notification and confirm the worker's
recovery pass credits within a minute; send the same notification twice (one credit); pay KES 1 against a KES 2 invoice (expect
`mismatch` and an email, no credit).

## Stripe (cards)

Settings: `base_url` (default https://api.stripe.com), `secret_key`, `webhook_secret` (`whsec_...`). Redirect flow, hosted Checkout:
no card data touches Ziira.

* Start: `POST /v1/checkout/sessions` (form encoded; header `Idempotency-Key` = our attempt reference) with `mode=payment`, one
  line item (`price_data` currency lower case, `unit_amount` in the smallest unit, product name "Invoice <number>"),
  `client_reference_id` and `metadata[invoice_number|attempt_reference]` (also on the payment intent), `success_url`,
  `cancel_url` back to `/billing?attempt=ID&payment=success|cancelled`, `customer_email` when given.
* Smallest unit from data (`billing_stripe/currencies.json`): zero-decimal currencies (JPY ...) x1, three-decimal (KWD ...) x1000,
  everything else x100.
* Check: `GET /v1/checkout/sessions/{id}`: complete + paid, `amount_total`, `currency`, `client_reference_id` must be ours,
  `metadata.invoice_number` must match; `expired` fails the attempt.
* Notification: `Stripe-Signature: t=...,v1=...`; HMAC-SHA256 of `t + "." + raw body`; other schemes ignored; timestamp within 5
  minutes. Events: `checkout.session.completed` / `async_payment_succeeded` (completed), `checkout.session.expired` /
  `async_payment_failed` / `payment_intent.payment_failed` (failed; the session check decides: a declined card on an open session is
  still pending). Deduplicated by event id.

**UNVERIFIED:** form field names and the exact response fields (from docs.stripe.com, not run); that a restricted key can read
`/v1/balance` (Test connection: 401/403 means rejected); asynchronous payment methods (only cards are expected); idempotency-key
reuse semantics; the automatic-tax and invoice features are not used.

Live-test checklist: test-mode keys; pay with 4242 4242 4242 4242; a declined card (4000 0000 0000 0002: the session stays open);
close the page (cancel_url return shows the cancelled message); register the endpoint and use the CLI (`stripe listen`) to
confirm signature verification and a replay; wait past the 5-minute tolerance with an old event; a zero-decimal currency (JPY).

## Paystack (cards and bank)

Settings: `base_url` (default https://api.paystack.co), `secret_key` (also signs notifications). Currencies NGN, GHS, ZAR, KES, USD.

* Start: `POST /transaction/initialize` JSON `email`, `amount` (string, smallest unit = x100), `currency`, `reference` (our attempt
  reference), `callback_url`, `metadata` (JSON text with `invoice_number` and `attempt_reference`) -> `authorization_url`.
* Check: `GET /transaction/verify/{reference}`: `status` success, `amount`, `currency`, `reference` must be ours, metadata invoice
  number; `ongoing`, `pending`, `processing`, `queued`, `abandoned` stay pending, anything else fails.
* Notification: `x-paystack-signature` = hex HMAC-SHA512 of the raw body with the secret key; `charge.success` matched by reference.

**UNVERIFIED:** that every served currency has 100 subunits; field names and the metadata form (docs show a string); that
`abandoned` is not final; the 404 on verify for an unknown reference (Test connection); retry behaviour beyond the documentation
(3-minute retries for four attempts, then hourly for 72 hours in live mode).

Live-test checklist: test keys; the test card from Paystack's documentation; abandon the page; register the address; a replayed
notification; compare amounts in each served currency.

## Operating it

* `ziira worker` runs the recovery pass every minute (and `billing.run_due` hourly). `payments.recover_pending()` can be called
  by hand; it is idempotent.
* Seed sample plans with KES prices to try the M-Pesa flow: `python scripts/seed_sample_plans.py` (SAMPLE prices only).
* A payment in `mismatch` is never credited: read the timeline, then either refund at the provider and leave it, or "Mark as paid
  manually" with the reason once the money is right.
* Nothing here calls a real provider in tests or scripts.

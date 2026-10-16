# M-Pesa (Safaricom Daraja) provider plugin

Everything specific to M-Pesa lives here; the Payments module (`ziira/modules/payments`) knows no provider. This plugin
implements two of its extension points:

| Extension point | Class | What it does |
|---|---|---|
| `payments.provider` | `DarajaProvider` (name `daraja`) | STK push (the payment prompt on the customer's phone), the status query, reading Safaricom's STK and C2B callbacks, the credentials form (consumer key, consumer secret, STK passkey) and settings form (till type, till number) |
| `payments.provider` | `SimulatedDarajaProvider` (name `fake`, development only) | Accepts every prompt and reports the outcome a test sets; refused in production |
| `payments.statement_format` | `MpesaStatement` (name `mpesa`) | Reads the business statement CSV downloaded from the M-Pesa portal |

Callbacks stay at the Payments module's addresses (`/api/v1/payments/callbacks/...`); Payments authenticates the address, this
plugin only reads what Safaricom sends. Accounts, credentials, prompts and transactions stay in Payments' tables
(`provider = 'daraja'`), so switching the plugin on or off changes no data.

**Upgrading an existing business.** `ziira install --all` (or `ziira install mpesa`) switches this plugin on for every business
that already has a payment account whose provider is `daraja` or `fake` (`[upgrade] enable_if_sql` in the manifest). A business
that never used M-Pesa is left alone and can switch it on from Add-ons.

> The Daraja request formats were written from Safaricom's public documentation and **have not been run against the real
> service**. Test them in Safaricom's sandbox (`scripts/live_check.py daraja`) before any live use.

Tests: `ziira/plugins/mpesa/tests` (formats, the provider with Safaricom replaced by a mock) and, through the Payments API,
`tests/test_payments_*.py`.

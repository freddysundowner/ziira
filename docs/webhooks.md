# Outgoing webhooks

A business can have Ziira call its own web address when something happens (a sale is posted, goods are received, a
finding is raised), so its other systems need not poll the API. Set them up in **Settings -> Webhooks** (permission
`webhooks.manage`, held by the Owner). Code: `ziira/kernel/webhooks.py`, `ziira/kernel/api/integration_routes.py`.

## How it works

1. A unit publishes an event as usual. The events that may leave the system are the ones a unit marks public in its
   `manifest.toml` (below); everything else stays internal.
2. After the sale (or whatever it was) is committed, the outbox hands the event to the webhook fan-out, which writes one
   **delivery** per subscribed, active endpoint and queues a background job. **No request ever waits on a customer's
   server**; `ziira worker` sends the deliveries.
3. The job posts the signed JSON body. Any 2xx answer is success. Anything else, a timeout, a refused connection, or a
   redirect (not followed) is a failure and is retried with growing waits.
4. Every attempt is written to the delivery log (status, response code, duration), shown in Settings.

A paused endpoint receives nothing while paused (events in that time are not queued for it). To catch up after an outage
use the **redeliver** button on failed deliveries, or read the API.

## The catalogue

`GET /api/v1/webhooks/events` (and the picker in Settings) lists the events and the payload fields each carries. In 1.0:

| Event | Unit | When | Fields in `data` |
|---|---|---|---|
| `sale.posted` | pos | A sale was completed (at a till, or a credit sale) | `company_id branch_id business_date number location_id net tax customer_id offline payments lines` |
| `sale.returned` | pos | Goods from a sale were returned, or the sale was voided | `company_id branch_id business_date number location_id net tax customer_id sale_id voided payments lines` |
| `invoice.issued` | pos | An invoice was issued to a customer | `company_id branch_id number customer_id total due_date sale_id` |
| `goods.received` | purchasing | Goods were received from a supplier into stock | `company_id branch_id location_id business_date number supplier_id landed_cost order_id lines` |
| `payment.received` | payments | A payment was recorded | `company_id branch_id number method amount business_date party_type party_id payment_account_id` |
| `stock.below_reorder` | inventory | A product fell below its reorder level | `company_id product_id sku quantity reorder_level` |
| `finding.created` | intel | Ziira Intelligence found something | `check severity company_id branch_id amount` |
| `customer.created` | crm | A customer was added | `company_id code` |
| `product.created` | products | A product was added | `company_id sku name` |

`lines` and `payments` are lists of ids, quantities, methods and amounts (no names). A test event, `webhook.ping`, is
always available from the **Send test** button.

### Adding an event to the catalogue (unit authors)

Only an event that already exists (listed under `publishes`) can be made public, and the manifest says exactly which
payload keys leave the system:

```toml
[provides.public_events."sale.posted"]
description = "A sale was completed"
fields = ["company_id", "number", "net", "tax", "customer_id", "lines"]
```

Rules for choosing fields: ids, codes, dates and amounts are fine; **no names, phone numbers, emails, addresses, free
text (a finding's summary is left out on purpose), staff ids or anything secret**. Keys that look like secrets
(`secret`, `password`, `token`, `hash`, `ciphertext`) are dropped anywhere in a payload as a second line of defence.
Once published, a field is part of the contract: add fields freely, never remove or rename one in a minor version.

## The request

```
POST <your address>
Content-Type: application/json
User-Agent: Ziira-Webhooks/1
Ziira-Event-Id: 6c1f5a3e-...        same on every retry and redelivery of this delivery
Ziira-Timestamp: 1791990000          unix seconds when this attempt was signed
Ziira-Signature: v1=<hex>            HMAC-SHA256
```

```json
{
  "id": "6c1f5a3e-6b0e-4d61-9c3a-0d2d1c2f7a11",
  "type": "customer.created",
  "created_at": "2026-10-15T09:30:12.512345+00:00",
  "business_id": "1620d754-f2b5-4c60-b25c-0a721bf2a4c0",
  "aggregate": {"type": "crm.customer", "id": "3f0a..."},
  "data": {"company_id": "...", "code": "C-0001"}
}
```

`id` equals the `Ziira-Event-Id` header. Money and quantities are decimal strings (as in the API). A body is limited to
about 500 KB; a larger one is sent with `"data": {"too_large": true}` and the aggregate id, so you can fetch the record
through the API.

### Verifying the signature

The signature is `v1=` followed by the hex HMAC-SHA256, keyed with the endpoint's **signing secret** (`whsec_...`, shown
once when the endpoint is created or its secret is changed), over the text `{Ziira-Timestamp}.{raw body}`. Verify
against the raw bytes you received, before parsing; compare in constant time; reject a timestamp more than five
minutes old (replay protection).

```python
# --- ziira webhook receiver (tested in tests/test_webhooks.py)
import hashlib
import hmac
import time


def verify_ziira_webhook(secret, headers, body, tolerance_seconds=300, now=None):
    """True if `body` (the raw bytes) was signed with `secret`. `headers` has lower-case names."""
    try:
        timestamp = headers["ziira-timestamp"]
        signature = headers["ziira-signature"]
        age = abs((now or time.time()) - int(timestamp))
    except (KeyError, ValueError):
        return False
    if age > tolerance_seconds:
        return False
    expected = "v1=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

The same in Node.js (not run by our tests; check it against yours):

```js
const crypto = require("crypto");
function verify(secret, headers, rawBody, toleranceSeconds = 300) {
  const timestamp = headers["ziira-timestamp"], signature = headers["ziira-signature"];
  if (!timestamp || !signature || Math.abs(Date.now() / 1000 - Number(timestamp)) > toleranceSeconds) return false;
  const expected = "v1=" + crypto.createHmac("sha256", secret).update(`${timestamp}.`).update(rawBody).digest("hex");
  const a = Buffer.from(expected), b = Buffer.from(signature);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
```

### Receiver guidance

- **Answer quickly** (within 10 seconds) with a 2xx, then do the work. A slow or failing receiver is retried.
- **Be idempotent.** Delivery is at least once. Remember `Ziira-Event-Id` (or the body's `id`) and ignore repeats.
- **Replay protection:** the timestamp check above, plus the event-id memory. Keep your clock correct (NTP).
- Do not trust the payload alone for anything sensitive: it is a notification with ids. Fetch the record through the
  [public API](public-api.md) with an API key when you need more.
- Use `https://` with a certificate from a public authority. Answer `410 Gone` only if you never want these again: it
  **switches the endpoint off**.

## Retries, failure and what you see

| Situation | What happens |
|---|---|
| 2xx | Delivered. |
| Other answer, timeout, connection error | Retried after 30 s, 2 min, 8 min, 32 min, ~2 h, ~8.5 h, 12 h, 12 h (at most `ZIIRA_WEBHOOK_MAX_ATTEMPTS` = 9 tries, and never later than `ZIIRA_WEBHOOK_RETRY_HOURS` = 24 h after the event). |
| Out of tries | The delivery is **failed**, the endpoint's failure count goes up, and an item *webhook_failing* appears in the exceptions inbox (at most one a day per endpoint). The endpoint stays active. |
| `410 Gone` | The endpoint is **disabled** with a reason, its waiting deliveries are cancelled, and an item *webhook_disabled* is raised. Enable it again in Settings once the receiver is fixed. |
| Redirect (3xx) | A failure; redirects are never followed. |

Settings -> Webhooks shows each endpoint's status, last success and failures, and per delivery the attempts (time, result
code, duration, error), the content hash and first bytes, a **Redeliver** button (same event id) and a **Send test**
button. A redelivery needs the stored content (see below).

## Safety of the address (SSRF)

An address must be `https://`, name a host (no user name or password in it), and resolve **only to public addresses**:
private ranges (10/8, 172.16/12, 192.168/16, 100.64/10, fc00::/7), loopback, link-local (including the cloud metadata
address 169.254.169.254), multicast and unspecified addresses are refused, also when a public name resolves to one of them
or to a mix. The name is resolved **again at every delivery** and the connection goes to the address that was just
checked (so a DNS record changed later cannot point a delivery inside); redirects are not followed. `http://localhost`
(and 127.0.0.1) is accepted only when `ZIIRA_ENV=development`, for building a receiver on your own machine.

## Privacy and retention

- Payloads carry the fields listed above only: ids, codes, dates, amounts. No customer names, phone numbers or emails.
- A delivery keeps its **content** for `ZIIRA_WEBHOOK_BODY_DAYS` (7) so it can be retried and redelivered; after that
  only its SHA-256, size and first 200 bytes remain, and the log line is deleted after `ZIIRA_WEBHOOK_LOG_DAYS` (90).
  The purge runs hourly in the worker (`kernel.webhook_purge`).
- Data subject requests: the kernel's `kernel.webhooks` personal-data provider finds, exports and removes stored content
  that mentions the person (practically never, given the field list), and the retention view lists this rule.
- The signing secret is encrypted with `ZIIRA_CREDENTIALS_KEY`, never returned by the API after creation (only its last
  four characters), and never written to the audit log. Every create, change, secret change, test, redelivery and delete
  is audited.

## Operating notes

- Needs `ziira worker` running (it runs the jobs). With it stopped, deliveries wait in the queue.
- At most 20 endpoints per business. A failing receiver costs one short database transaction per try (10 s timeout);
  the job runs inside the worker's transaction for that tenant, so a very slow receiver slows that tenant's other
  background jobs by up to the timeout.
- Not covered by automated tests: a real TLS connection to a real server (tests use a fake transport and a fake DNS).
  Try it once with the test button against a receiver you control before relying on it.

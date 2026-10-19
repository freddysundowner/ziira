# Public API

Integrations (a website, a stock system, a BI tool) talk to a business through the **public API**: a documented, stable
subset of `/api/v1`, used with an **API key**. Everything else in `/api/v1` is the web app's own API and may change.
Code: `ziira/kernel/public_api.py`, `ziira/kernel/api_keys.py`, `ziira/kernel/api/integration_routes.py`.

## Getting started

1. Settings -> API keys -> **New key** (permission `api_keys.manage`, Owner by default). Choose the permissions the key
   needs, tick *read-only* if it only reads, optionally limit it to one company, set a requests-a-minute limit and an expiry.
2. Copy the key now: it is shown once (`zk_...`). Only its hash is stored.
3. Send it in the `X-API-Key` header:

```bash
curl -H "X-API-Key: zk_..." https://your-ziira.example/api/v1/pos/sales?limit=20
```

The machine-readable description of the public API alone is at `GET /api/v1/public/openapi.json` (no sign-in needed). The
full description (`/openapi.json`, `/docs`) tags the same operations **Public**.

## What is in it (v1)

| Method and path | Needs permission | Notes |
|---|---|---|
| `GET /api/v1/auth/me` | any | who the key is, and its permissions: a way to test a key |
| `GET /api/v1/products/products`, `GET .../{product_id}` | `products.view` | |
| `POST /api/v1/products/products` | `products.manage` | send an `Idempotency-Key` header |
| `GET /api/v1/crm/customers`, `GET .../{customer_id}` | `customers.view` (or `customers.manage`) | |
| `POST /api/v1/crm/customers` | `customers.manage` | send an `Idempotency-Key` header |
| `GET /api/v1/pos/sales`, `GET .../{sale_id}` | one of `sales.sell`, `sales.void`, `sales.refund`, `till.review` | |
| `GET /api/v1/pos/invoices`, `GET .../{invoice_id}` | `invoices.manage` or `receivables.view` | |
| `GET /api/v1/inventory/balances`, `GET /api/v1/inventory/products/{product_id}/stock` | `stock.view` | costs only with `stock.cost` |
| `GET /api/v1/payments/payments`, `GET .../{payment_id}` | `payments.view` (or a payments manage permission) | |
| `GET /api/v1/intel/findings`, `GET .../{finding_id}` | `findings.view` | scoped to the key's branches |
| `POST /api/v1/memberships/access/decision` | `memberships.checkin` | may member X enter now? (door/turnstile controller); records the entry, `record: false` is a dry run |
| `GET /api/v1/memberships/access/allowed` | `memberships.checkin` | numbers and cards allowed at a branch right now, no names |

(The authoritative list is `PUBLIC_ENDPOINTS` in code and the Public tag; a test checks that every entry exists. The
permission codes are the ones each endpoint declares; the description lists them.)

An API key can call **only** these endpoints: anything else answers 403 *not part of the public API*, even if the key
has the permission, so a leaked key can never reach user management, settings or other keys.

## Scopes

- **Permissions**: the key acts with exactly the permission codes chosen, at most the creator's own, over the whole
  business, one company, or one branch of a company (`company_id`, `branch_id`). Lists are filtered the same way as for a
  person with that role.
- **Read-only**: a read-only key can make `GET` requests only (403 otherwise).
- **Expiry**: optional; an expired key answers 401.
- **Rate limit**: requests a minute per key (default `ZIIRA_API_KEY_RATE_LIMIT_PER_MINUTE`, 600). Over the limit: `429` with
  `Retry-After` (seconds) and the usual error body. Counting is per key in a one-minute window. Rejected calls count too.
- **Usage**: Settings shows each key's last use, number of requests and last address.
- **Rotation**: *Replace key* makes a new key with the same access and limits, and lets the old one work for the overlap
  you choose (0 to 168 hours, default 24) so you can switch without a gap. Revoke at any time.
- Every create, rotate and revoke is audited (never the key itself).

## Errors and conventions

Errors are JSON: `{"error": "forbidden", "message": "...", "request_id": "..."}` (quote the `request_id` to support).
Money and quantities are **decimal strings**, never floats. Lists take `limit` (1 to 500) and `offset`. A create that may
be sent twice should carry an `Idempotency-Key` header: the second request returns the first result and changes nothing.
Dates are ISO 8601.

## Website assistant (public, not part of the keyed API)

`GET /api/v1/public/assistant/config` and `POST /api/v1/public/assistant/stream` serve the marketing site's chat (no key, no
sign-in, rate limited per address, CORS only for the site's own origin). Events and limits: `docs/ai.md` section 14.

## Versioning and deprecation policy

- The version is in the path: `/api/v1`. Every API response carries `Ziira-API-Version: 1`.
- **Inside v1 nothing breaks.** We may add endpoints, optional request fields and response fields (clients must ignore
  fields they do not know), and new enum values only where the description says the set may grow. We do not remove or
  rename endpoints, fields or permissions, make an optional field required, or change a meaning or a type.
- A breaking change needs `/api/v2`, run **alongside** v1.
- Before an operation or field is removed it is **deprecated for at least six months**. A deprecated operation answers with
  `Deprecation: @<unix time of the announcement>` ([RFC 9745](https://www.rfc-editor.org/rfc/rfc9745)), `Sunset: <HTTP
  date of removal>` and `Link: <migration notes>; rel="deprecation"`. Code: add an entry to `DEPRECATIONS` in
  `public_api.py` (tested). The release notes and this file say what replaces it.
- Webhook payloads follow the same rule (docs/webhooks.md): fields are only added.
- An endpoint joins the public API only when it has tests, a permission, filtered lists, and a stable shape; adding one is
  adding it to `PUBLIC_ENDPOINTS`.

## Not covered

No OAuth or per-user delegation yet: a key is a business-level credential for server-to-server use, and should live in a
server's secret store, never in a browser or mobile app. Not tested live: rate-limit behaviour behind several API
processes shares the database counter, so it holds, but a very high limit costs a database write per request.

# Selling at the till without a connection

The web terminal (`/pos/terminal`) keeps working with no network. Sales made offline are kept on the device and sent when
the connection returns, exactly once.

## How it works

- **App shell.** A service worker (`frontend/service-worker.js`, written into the build as `sw.js` by `vite.config.ts`,
  production build only) saves `index.html` and every script and style after one online visit. Page loads use the network
  when it answers, else the saved shell. It never touches `/api`. Serve `sw.js` with `Cache-Control: no-cache`.
- **Session.** `sdk/session.tsx` keeps a copy of who is signed in (`ziira.session` in localStorage). With no connection the
  session starts from it; tokens are refreshed by the first request after the connection returns. It is removed on sign-out.
- **Copy on the device** (IndexedDB database `ziira-pos`, store `kv`): for the till's branch, the products with the price in
  force, tax rate, barcodes and stock; tax codes; units; customers (id, name, phone, credit limit); mobile money accounts
  (names only); reason lists; receipt header and footer (`GET /pos/receipt-settings`); and the open till and devices.
  Refreshed in the background every 5 minutes while online. "Prices and stock as of ..." shows when offline or when the copy
  is older than 30 minutes.
- **Outbox** (store `outbox`): each sale made offline, with its client-made `local_id`, the exact request, the device clock
  and the last known server clock offset, and a provisional receipt `OFFLINE-<till>-<n>` marked "to be confirmed", printed
  from local data. Writing a sale is one transaction: the cashier is told "saved" only after it is durable.
- **Sync engine.** Sales go to `POST /pos/sync/upload` one at a time, oldest first, on reconnect, every 15 s and on demand.
  Without a device key (a browser has none) the endpoint accepts only sales for the signed-in cashier's own till
  (`till_session_id`). The server records a sale per `local_id` once (`duplicate` on a repeat), so a lost reply or a reload
  in the middle never double-sells. Each sale carries the price charged, so a price change before sync only raises a warning.
- **Retry:** 5 s, 10 s, 20 s ... up to 5 min. No answer, 401, 408, 429, 5xx: retried. 4xx or `rejected`: the sale goes to
  "Needs attention" with the reason (and the server keeps it in `GET /pos/sync/rejections`); it is never dropped.
- **Held sales** are kept in the browser and at the server (`POST /pos/tills/{id}/held`, `.../resume`, `.../discard`; a
  draft that moves no stock and posts nothing; the terminal's own id may be used for resume and discard). Held offline, they
  are uploaded on reconnect. Held sales still there when the till closes expire (`held_expired` in the till report).

## What works offline

Sell with cash, card slips and mobile money typed codes; hold, resume, remove lines; price override only if the cached
permissions allow it; scan barcodes (looked up on the device first). Refused with a plain reason: opening a new till,
closing the till, mobile money prompts, credit on account (the limit must be checked), returns, voids of sent sales.
If IndexedDB is unavailable the terminal says so and refuses offline selling.

## Status chip and queue

Chip in the bar: Online / Offline / Sending n / n waiting / n need attention. Tap it for the queue (retry, copy details,
remove after copying, warnings the server sent with accepted sales). Banners warn of no connection, a queue older than a
day or of 50+ sales. Closing the till with sales waiting asks first.

## Failure cases

| Failure | Result |
|---|---|
| Reload mid-sale | Cart is in localStorage and comes back |
| Reload / browser restart with a queue | Outbox is in IndexedDB; sales still sending are put back to waiting |
| Answer lost after the server recorded the sale | Resent with the same id: `duplicate`, one sale |
| Server refuses a sale | "Needs attention" with the reason |
| Storage full or denied | Offline selling refused; a failed save leaves the cart untouched |
| Signed out while offline | Sales wait; sign in again to send |

## Limits (not tested in real devices)

Sales are sent only while the terminal page is open (no background sync). Safari/iOS service worker and storage limits
(eviction after inactivity) are untested; the terminal asks for persistent storage. Two tills sharing one browser profile
share an outbox. Provisional receipt numbers are per browser.

## Testing

`cd frontend && npx vitest run src/modules/pos` (outbox, engine, retry, freshness, receipts, search, held). Backend:
`pytest tests/test_pos_till_gaps.py`. Browser: `bash e2e/run.sh tests/j11` (J11 offline till, J11b no storage).

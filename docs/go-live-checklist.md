# Go-live checklist

Things that need accounts, credentials or a decision, not code. None of them can be done from the test suite: the code
for each exists, but its request formats were written from public documentation and have **not been run against the real
service**. Tick each off (with the date and who did it) before a customer relies on it.

## Integrations to run in their sandboxes

- [ ] **Safaricom Daraja** (M-Pesa): STK push, STK query, C2B register/confirmation/validation URLs, callbacks reaching
      our public URL. Code: `ziira/modules/payments/providers.py`. Check real response shapes and error codes.
- [ ] **Africa's Talking SMS**: sender id approved, delivery reports, cost per message. Code: `ziira/plugins/messaging/`.
- [ ] **WhatsApp Cloud API**: business verified, message templates approved (reminders and alerts need templates outside
      the 24-hour window), opt-in captured. Code: `ziira/plugins/messaging/`.
- [ ] **Email (SMTP)**: sending domain with SPF/DKIM, bounce handling.
- [ ] A real **receipt printer**: print `GET /sales/{id}/receipt?format=text&width=...` on the thermal printers the first
      customers use and pick the width (32, 40 or 48) that fits.

## Security before real data

- [ ] **Multi-factor sign-in** and **sign-in rate limiting** (deferred to phase 11; pull forward if a customer goes live
      first).
- [ ] Production `ZIIRA_SECRET_KEY` and `ZIIRA_CREDENTIALS_KEY` generated, stored outside the repository and backed up
      (losing the credentials key locks out every tenant). `ZIIRA_ENV=production` so the development header is refused.
- [ ] Database backups tested by restoring one; the master database and every tenant database are included.
- [ ] HTTPS only; the API not reachable except through the reverse proxy.
- [ ] `ziira verify` and `ziira stock-verify` scheduled nightly and their output watched.
- [ ] A worker running (`ziira worker`, `ziira outbox-run`) and restarted automatically.

## Business decisions

- [ ] Chart of accounts, tax codes and VAT rates entered for each company (taxes are entered by hand for now).
- [ ] Receipt and invoice footers set per company (company settings `receipt_footer`, `invoice_footer`).
- [ ] Credit limits and terms for existing customers loaded; opening balances for customers, suppliers and stock.
- [ ] Approval rules (who approves credit raises, bank-detail changes, refunds) reviewed with the owner.

Not on this list on purpose: eTIMS, which comes later as a plugin (see `docs/parked/etims.md`).

# Go-live checklist

Things that need accounts, credentials or a decision, not code. None of them can be done from the test suite: the code
for each exists, but its request formats were written from public documentation and have **not been run against the real
service**. Tick each off (with the date and who did it) before a customer relies on it.

## Integrations to run in their sandboxes

- [ ] **Safaricom Daraja** (M-Pesa): STK push, STK query, C2B register/confirmation/validation URLs, callbacks reaching
      our public URL. Code: `ziira/modules/payments/providers.py`. Check real response shapes and error codes.
- [ ] **BlessedTexts SMS** (provider `blessedtexts`): send a real message with the live key and approved sender id; check
      the error codes it returns for a bad key, bad sender and no credit (only "1000" is known to mean success).
      Africa's Talking (`africastalking`) is also built but unused. Code: `ziira/plugins/messaging/`.
- [ ] **Email** (providers `smtp`, `brevo`, `resend`, `sendgrid`): send one real message through the provider the customer
      uses; sending domain/sender verified with SPF/DKIM; check the error replies for a bad key and unverified sender.
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

## Accounting software

- [ ] **QuickBooks and Sage journal imports**: export a small month (`GET /api/v1/finance/exports/journal?format=quickbooks`
      or `sage`) and import it into the accountant's real software; fix the layouts in
      `ziira/modules/finance/domain/exports.py` if it is refused. Set each account's mapping first.
- [ ] **Bank reconciliation** with a real statement: upload its CSV to the suggestions endpoint and check the column names
      the bank uses are understood (`domain/reconciliation.py: ALIASES`).

## Payroll

- [ ] **Each business's statutory rules** (taxes, contributions, levies) are entered from the official notices, then verified by
      a second person; an accountant checks a few payslips against an independent calculation before the first real run.
- [ ] **Returns**: the per-rule CSV (`/payroll-runs/{id}/returns/{code}?format=csv`) matched to the form each authority
      asks for; adapt the columns before first filing.
- [ ] The bank's bulk payment upload format against the payment file; payslip email/SMS tried with a test employee.

## Business decisions

- [ ] Chart of accounts, tax codes and VAT rates entered for each company (taxes are entered by hand for now).
- [ ] Receipt and invoice footers set per company (company settings `receipt_footer`, `invoice_footer`).
- [ ] Credit limits and terms for existing customers loaded; opening balances for customers, suppliers and stock.
- [ ] Approval rules (who approves credit raises, bank-detail changes, refunds) reviewed with the owner.

Not on this list on purpose: eTIMS, which comes later as a plugin (see `docs/parked/etims.md`).

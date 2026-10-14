# Localisation: nothing in the platform is for one country

Ziira is used in any country. What differs between countries is **data a business enters**, never code:

| What | Where it lives |
|---|---|
| Currency | `kernel.company.base_currency`, chosen when the company is created (`--currency`); price lists copy it |
| Phone numbers | the company setting `phone_country_code` (e.g. `44`); `ziira.sdk.normalise_phone` reads national numbers with it, numbers written with `+` or `00` are taken as written |
| Time zone and business dates | the company setting `timezone` (IANA name, default `UTC`); see "Business dates" below |
| Tax number | `tax_id` on companies, customers, suppliers and employees: kept as the authority writes it (3-30 letters, digits, `-`, `/`, `.`) |
| Tax codes (VAT, GST, sales tax ...) | `products.tax_code`: a rate, plus an optional `authority_code` the tax authority uses |
| Payroll taxes, contributions and levies | the business's **statutory rules** (`people.statutory_rate_table`, see `ziira/modules/people/domain/rules.py`): rate, bands, caps, who pays, whether it reduces taxable pay, calculation order, effective date, the account it is owed through |
| Weekend, overtime, unpaid-leave day | company settings `weekend_days`, `overtime_multiplier`, `overtime_hours_per_month`, `payroll_unpaid_day_divisor` |
| Chart of accounts | a general template a business edits (`finance/domain/chart.py`); posting rules are data |
| Payment methods | `cash`, `mobile_money`, `bank`, `card`, ...; which service provides mobile money is the payment account's `provider` |
| Credentials of integrations | `kernel.integration_credential`, any provider name |

## Business dates

"Today", a document's date, and the day a stock movement, sale, receipt, payment, journal entry or price belongs to are the
**calendar date in the company's own time zone**, never the server's and never a country's. The zone is the company
setting `timezone` (Settings in the web app, `PATCH /companies/{id}/settings`); a company that never set one is in `UTC`.

* **In code:** `ziira.sdk.company_today(session, company_id)` is today's date where the company is;
  `company_date_of(session, company_id, moment)` is the company's date of an aware moment (a naive one is read as UTC).
  Both use `company_setting`, which is read once per transaction and company, so a hot path adds no query per call.
  Never write `datetime.now(<a zone>).date()`, `date.today()` or a fixed UTC offset to date a record. Where a date is a
  default for something that names a company (a movement, an entry, an invoice, a payment) pass that company's id.
* **A report across companies** (receivables ageing, payables) with no date asked for is "as of today" for each invoice or bill
  in its own company's zone; the date shown is the latest of them.
* **At creation:** `ziira create-tenant ... --timezone Europe/London` and the registration request (`timezone` in
  `POST /register`; the web sign-up sends the main zone of the chosen country, kept as data in
  `frontend/src/shell/countries.ts`) set it. Without one the company starts in `UTC`, and the owner changes it later in
  Settings. Changing it affects dates of records made afterwards; posted records are never re-dated.
* **Existing businesses** made before this setting existed are in `UTC` until their owner sets the zone. To keep a business
  on its old day boundary, set it once: `PATCH /companies/{id}/settings {"timezone": "Africa/Nairobi"}`.
* **Tests** create their tenants in `Africa/Nairobi` (`LOCALE["timezone"]` in `tests/conftest.py`, a fixture value, passed
  with `--timezone`); `tests/test_business_date.py` shows the same instant on different days in UTC, Nairobi, Auckland and
  Los Angeles for a movement, a till, a journal entry, a receipt, a return and a price.
* **Not a company date:** the M-Pesa provider reads and writes Safaricom's timestamps, which are East Africa Time by that
  service's definition (`payments/domain/mpesa.py`); that is provider code, not the business date.

## Country-specific things live outside the core

* **Providers behind extension points.** Safaricom's Daraja (M-Pesa) is one `payments.provider`; its request formats, STK
  push and the M-Pesa statement parser are in the payments module as that provider's code. Another country's mobile money
  or card service is another provider.
* **Plugins.** Kenya's eTIMS will be an installable plugin (`docs/parked/etims.md`) that listens to documents and keeps its own
  tables. Core columns that such a plugin fills are neutral (`tax_code.authority_code`, `product.authority_item_class`,
  `supplier_bill.authority_ref`).
* **Demo and tests.** The demo business is a Kenyan shop (`scripts/seed_demo.py`), and many tests use Kenyan phone numbers
  and amounts as *fixtures*. They never decide behaviour.

## Rule for new code

No constant that is true in one country only (a rate, a limit, a format, a currency, a provider name, a calling code). If a
value differs between businesses, make it a setting or a row the business enters. See rule 15 in `CLAUDE.md`.

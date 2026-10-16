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
| Chart of accounts | a general template a business edits (`finance/domain/chart.py`); a country pack refines it; posting rules are data |
| Payment methods | `cash`, `mobile_money`, `bank`, `card`, ...; which service provides mobile money is the payment account's `provider` (a plugin) |
| Country defaults (currency, calling code, time zone, what the tax number is called, formats) | `ziira/kernel/data/countries.json`, refined by country packs; `GET /api/v1/countries` |
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
* **Not a company date:** the M-Pesa plugin reads and writes Safaricom's timestamps, which are East Africa Time by that
  service's definition (`ziira/plugins/mpesa/formats.py`); that is provider code, not the business date. Bank statements are
  read in the company's own time zone.

## Country-specific things live outside the core

The rule is **anything that is a vendor, a country or a format is a plugin; core logic stays in modules**
(`docs/plugin-audit.md` lists what was moved and what is left). `tests/test_architecture.py` fails when a currency code, a
tax authority or a vendor name appears in `ziira/modules/**` or `ziira/kernel/**`.

* **Country packs: a country's DATA.** A plugin with `category = "country"` and `countries = ["KE"]` carries data files
  (TOML) and hands them to the units that asked for them: `products.tax_code_seed` (tax codes), `finance.chart_template`
  (accounts, journals, posting rules), `people.statutory_table_seed` (payroll taxes, contributions and levies as
  effective-dated tables), and its `country.toml` (currency, calling code, time zone, the name and pattern of the tax number,
  date and number formats) which the sign-up form reads through `GET /api/v1/countries`. Each unit has its own generic
  fallback and works with no pack at all. `ziira/plugins/pack_ke` is the reference pack; `pack_international` (worldwide)
  is used when no pack names the country and adds only tax codes that charge nothing.
  * **When it is applied:** at sign-up (the pack of the chosen country, else the international one), when the pack is
    switched on later from Add-ons, when a unit that seeds is switched on afterwards, and on `ziira apply-packs`.
  * **How:** the units copy the pack's rows into **the business's own tables**, as data it can edit. Only what is missing is
    added; a code, account or table the business already has is never overwritten, renamed or given a newer version; nothing
    is removed; posted records are never touched; running it again changes nothing. Payroll tables arrive **unverified**, so a
    second person must check each against the official notice before a payroll run that used it can be approved.
  * **Which pack applies to a company** is chosen by its `country` (`kernel.company.country`): a pack naming it, else the
    worldwide pack. A company with no country recorded takes every pack that is switched on.
  * **Figures:** only data files, each with its source and a "verify" note. The Kenya pack's payroll tables are *examples*
    taken from the repository's tests and are not guaranteed current law.
* **Providers: a vendor behind an extension point.** Safaricom's Daraja is the `mpesa` plugin (`payments.provider`, plus the
  `payments.statement_format` for its statement); the Payments module keeps the models, matching, jobs and callback URLs.
  Another country's mobile money or card service is another plugin with the same shape.
* **Other plugins.** Kenya's eTIMS is a skeleton plugin (`ziira/plugins/etims`, design in `docs/parked/etims.md`): its contract and
  status table exist, nothing is sent. Core columns such a plugin fills are neutral (`tax_code.authority_code`,
  `product.authority_item_class`, `supplier_bill.authority_ref`).
* **Demo and tests.** The demo business is a Kenyan shop (`scripts/seed_demo.py`), and many tests use Kenyan phone numbers
  and amounts as *fixtures*. They never decide behaviour.

### Adding a country

1. `ziira plugin new pack_xx --category country --countries XX` (the plugin kit scaffolds the folder).
2. Put the data in `data/`: `country.toml`, and any of `tax_codes.toml`, `chart.toml`, `payroll.toml`; copy `pack_ke/hooks.py`
   to read them. Cite a source for every figure; mark what must be verified; do not enter a rate you are unsure of.
3. `ziira install pack_xx`; a business in that country gets it at sign-up, others add it from Add-ons.

## Rule for new code

No constant that is true in one country only (a rate, a limit, a format, a currency, a provider name, a calling code). If a
value differs between businesses, make it a setting or a row the business enters. See rule 15 in `CLAUDE.md`.

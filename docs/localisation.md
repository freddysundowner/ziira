# Localisation: nothing in the platform is for one country

Ziira is used in any country. What differs between countries is **data a business enters**, never code:

| What | Where it lives |
|---|---|
| Currency | `kernel.company.base_currency`, chosen when the company is created (`--currency`); price lists copy it |
| Phone numbers | the company setting `phone_country_code` (e.g. `44`); `ziira.sdk.normalise_phone` reads national numbers with it, numbers written with `+` or `00` are taken as written |
| Tax number | `tax_id` on companies, customers, suppliers and employees: kept as the authority writes it (3-30 letters, digits, `-`, `/`, `.`) |
| Tax codes (VAT, GST, sales tax ...) | `products.tax_code`: a rate, plus an optional `authority_code` the tax authority uses |
| Payroll taxes, contributions and levies | the business's **statutory rules** (`people.statutory_rate_table`, see `ziira/modules/people/domain/rules.py`): rate, bands, caps, who pays, whether it reduces taxable pay, calculation order, effective date, the account it is owed through |
| Weekend, overtime, unpaid-leave day | company settings `weekend_days`, `overtime_multiplier`, `overtime_hours_per_month`, `payroll_unpaid_day_divisor` |
| Chart of accounts | a general template a business edits (`finance/domain/chart.py`); posting rules are data |
| Payment methods | `cash`, `mobile_money`, `bank`, `card`, ...; which service provides mobile money is the payment account's `provider` |
| Credentials of integrations | `kernel.integration_credential`, any provider name |

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

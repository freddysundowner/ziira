# Kenya country pack (the reference example of a pack)

A **country pack** is a plugin (`category = "country"`, `countries = ["KE"]`) that brings a country's *data* to a business.
It has no tables and no logic: `hooks.py` reads the files in `data/` and hands them to the units that asked for them.

| File | Goes to | Extension point |
|---|---|---|
| `data/country.toml` | the sign-up form (currency, calling code, time zone, tax-number label, formats) | read by the kernel (`GET /api/v1/countries`) |
| `data/tax_codes.toml` | Products > Tax codes | `products.tax_code_seed` |
| `data/chart.toml` | the company's chart of accounts | `finance.chart_template` |
| `data/payroll.toml` | People > Statutory rules, saved **unverified** | `people.statutory_table_seed` |

**Check every figure.** The VAT rates and payroll tables are what the repository's tests and notes use; they are examples,
not legal advice, and they change. The payroll tables are saved unverified so a second person has to check each against the
official notice before payroll can use them. The business's accountant owns the final numbers.

How it is applied: when the pack is switched on (at sign-up for a Kenyan business, or later from Add-ons), each unit
adds what the business lacks. It never overwrites or removes what the business entered, and running it again changes
nothing. See `docs/localisation.md`.

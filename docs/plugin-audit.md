# Plugin audit: what in the core is a vendor, a country or a format

Rule: **anything that is a vendor, a country or a format is a plugin; core logic stays in modules.** This is the inventory
taken before the move, what became of each item, and what is still left. `tests/test_architecture.py`
(`test_modules_and_kernel_name_no_country_currency_or_vendor`) now fails when a country, currency, tax authority or vendor
name appears in `ziira/modules/**` or `ziira/kernel/**` (tests, `data/` reference files and SQL migration history are
exempt); its `ALLOWED` table is the list of known leftovers, each with its reason.

Risk = what could go wrong when it moves (data, URLs, existing businesses), not effort.

## Moved

| # | What it was | Where it was | Now | Risk, and how it was handled |
|---|---|---|---|---|
| 1 | M-Pesa / Daraja request code: OAuth token, STK push, status query, the password, East Africa timestamps | `payments/providers.py`, `payments/domain/mpesa.py` | plugin `ziira/plugins/mpesa` (`daraja.py`, `formats.py`), category `payments`, `countries = ["KE"]`, implementing `payments.provider` | Medium. Payments keeps the provider-neutral models, matching engine, jobs and the extension point; the plugin supplies formats, limits (whole amounts, 1 to 150000), credential and settings forms. Account rows keep `provider = 'daraja'`, so no data changed. Existing businesses get the plugin switched on by an upgrade step (see "Upgrade path") |
| 2 | Safaricom callback formats (C2B confirmation, STK callback) and the reply Safaricom expects | `payments/domain/mpesa.py`, `api/routes.py` | `DarajaProvider.parse_c2b / parse_stk_callback / callback_reply`; the routes stay in Payments at the same URLs and ask the account's provider | Medium. URLs unchanged (`/api/v1/payments/callbacks/{token}/c2b/...`, `/callbacks/stk/{tenant}/{intent}/{signature}`); a callback for an account whose plugin is off is refused (422) instead of silently parsed |
| 3 | M-Pesa business statement parser | `payments/domain/statements.py` | `MpesaStatement` on the new `payments.statement_format` extension point; the generic CSV helpers are public in Payments | Low. `format: "mpesa"` still accepted; the upload names a format, not a provider |
| 4 | Kenyan phone normalisation (`254...`), masking, fingerprints | `payments/domain/mpesa.py` | normalising: the provider (`normalize_phone`, default = the company's calling code via `ziira.sdk.normalise_phone`); masking and hashing: provider-neutral `mobile_money.py` | Low. Fingerprints are the same SHA-256 of international digits, so stored hashes still match |
| 5 | "Fake" payment provider (tests, demo) | `payments/providers.py` | `SimulatedDarajaProvider` (name `fake`) in the M-Pesa plugin: it speaks Daraja's callback shapes and is refused in production | Low. Test helpers and demo seeds switch the plugin on |
| 6 | Credentials form (consumer key, secret, passkey) typed into the web app and the API schema | `payments/api/schemas.py` (`CredentialsIn`), web `AccountSecurity.tsx` | `FormField` descriptions on the provider; `GET /api/v1/payments/providers`; the web draws every provider's forms from it | Medium (API shape): `PUT /accounts/{id}/credentials` now takes a free object validated against the provider's fields; the old three keys still work |
| 7 | `payment_account.provider` default `'daraja'`; `external_transaction.source` limited to Daraja/M-Pesa names | payments migrations 0001/0002 | migration `0005_provider_neutral`: default `'manual'`; sources are any `[a-z][a-z0-9_]{2,39}` | Low: existing rows are valid under the new rule |
| 8 | Statutory payroll figures | none in code (rate tables are business data); example figures only in tests | `pack_ke/data/payroll.toml`, seeded **unverified**; the international pack seeds none | Low |
| 9 | Tax code seeds | none in code; demo scripts typed them in | `pack_ke/data/tax_codes.toml`, `pack_international/data/tax_codes.toml` | Low |
| 10 | Chart of accounts template | `finance/domain/chart.py` (already general: "Mobile money clearing", "VAT input") | stays as the generic fallback; `pack_ke/data/chart.toml` refines it (names, PAYE/NSSF/SHIF/levy payables) through `finance.chart_template` | Low: only adds accounts a company lacks |
| 11 | Country list: calling codes, currencies, time zones | `frontend/src/shell/countries.ts` | `ziira/kernel/data/countries.json` (the same reference data) refined by packs, served at `GET /api/v1/countries`; the web uses it and keeps the static list as the offline fallback | Low |
| 12 | Kenyan mobile-number rule for suppliers' mobile-money details | `purchasing/domain/rules.py` | 8 to 15 digits, a leading `+` for international numbers | Low (looser; no data changed) |
| 13 | A `'KES'` default in the price-list model | `products/repository/models.py` | removed (the column has had no default since the localisation migration) | None |
| 14 | `Africa/Nairobi`, `KES`, `254...` in examples, messages and comments across modules/kernel | many files | neutral examples (`Europe/London`, `USD`, `44...`) | None |
| 15 | East Africa Time used to read bank statements | `payments/domain/statements.py` | the company's own time zone (`company_setting("timezone")`) | Low: a bank CSV is now read in the business's zone, which is what "business date" means |

## Skeleton only

| What | Where | Note |
|---|---|---|
| eTIMS | before: design only (`docs/parked/etims.md`), neutral columns in the core. Now: `ziira/plugins/etims` | There was no eTIMS code to move. The plugin has its manifest (`category = "tax"`, `countries = ["KE"]`), the status table `plg_etims.submission` and the contract in `public.py` (`AuthorityGateway`, `SaleDocument`, `SubmissionResult`). **It sends nothing and listens to nothing.** Building it needs the arrangements with the authority first |

## Still in the core (known leftovers)

| What | Where | Why it stays | Proposed |
|---|---|---|---|
| Words that tell a mobile-money payment method from a bank one in a customer's export (`mpesa`, `airtel`, ...) | `connect/connectors/_http.py`, `files.py`, `csv_exports.py` (the `ALLOWED` table in the architecture test) | They are **source-system aliases** (data about what other people's systems call things), not behaviour; moving three tuples to a plugin would add an extension point for no gain | Move to a data file in `connect` when a format-alias socket is added |
| Vendor connectors: Odoo, ERPNext, Zoho Books, QuickBooks (HTTP APIs) | `connect/connectors/*.py` | They are vendors living in a module. Owned by the Connectors work, which was changing them in parallel | One plugin per vendor on the existing `connect.connector` extension point. Risk: medium (OAuth callbacks, stored configuration) |
| SQL migration history naming M-Pesa and KRA (`mpesa_till`, `kra_pin`, ...) | `*/migrations/0001..0006*` | Applied migrations are never edited | None |
| `scripts/live_check.py` | scripts | A developer tool for Safaricom's sandbox | Move beside the plugin as `ziira/plugins/mpesa/live_check.py` later |
| Demo business is Kenyan | `scripts/seed_demo*.py` | Fixtures, as `docs/localisation.md` says | Make the demo country a parameter |
| Examples and comments in the web app (`KES 5,000` in a comment, `Africa/Nairobi` in a hint) | `frontend/src/**` | Illustrations in text | Reword when the strings are next edited |
| Messaging gateways (BlessedTexts, Africa's Talking, Brevo, ...) | `ziira/plugins/messaging` | Already a plugin; vendors are where they should be | None |
| AI vendor (Anthropic) | `ziira/plugins/ai_anthropic` | Already a plugin | None |

## Upgrade path (existing businesses)

* `ziira install --all` (run on every deploy) installs the new plugins, applies payments migration 0005 and runs each plugin's
  **upgrade step**: a read-only query in the plugin's manifest (`[upgrade] enable_if_sql`). For `mpesa` it is "this business has a
  payment account whose provider is `daraja` or `fake`"; those businesses get the plugin switched on, the others are left alone.
  Nothing is deleted and no payment table changes.
* Country packs are **not** switched on for existing businesses automatically (that would add accounts and tax codes they did
  not ask for). An owner adds one from Add-ons ("Recommended for Kenya"), or an operator runs
  `ziira enable <tenant> pack_ke` then `ziira apply-packs <tenant>`.

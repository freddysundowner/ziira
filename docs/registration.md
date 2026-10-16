# Registration: how a business joins

Ziira is a SaaS: a business creates itself, with no operator involved.

```
POST /api/v1/register          the person asks for a business     -> 202, nothing created yet
   (email with a link)         https://<web app>/register/verify?token=...
POST /api/v1/register/verify   the link is used                   -> the business exists, the owner is signed in
```

1. **Register** (`POST /api/v1/register`): business name, owner name, email, password, currency, phone country code, and
   optionally a tax number and an invitation code, and an `edition` (see *Editions* below; default `full`). The older `mode` still works: `core` is the `full` edition,
   `standalone` the `intelligence` edition (`docs/standalone-mode.md`); an `edition` wins if both are sent. The request is saved in the master database (`master.registration`)
   with the password already hashed and the emailed token only as a hash. **No database, login or tenant exists yet.**
   The reply is the same whatever the email, so it reveals nothing. Outside production it also carries `dev_token` (the
   token the email holds) so tests and local development need no mailbox.
2. **Verify** (`POST /api/v1/register/verify`, from the emailed link, works once, expires after
   `ZIIRA_REGISTRATION_TOKEN_HOURS`): the business is provisioned (its own database and login, copied from the template in
   about a second), the owner gets the Owner role, the default units are switched on, the owner's email goes into the login
   directory, and the owner is signed in. The workspace code is made from the business name (`acme-traders`, then
   `acme-traders-2` ...); people never type it.
   If a **country pack** is installed for the chosen country it is switched on and seeds the business's tax codes and, when the
   units are on, its chart of accounts and (unverified) payroll tables; otherwise the international pack is used. Any country
   registers: the currency and calling code can be typed when no pack names it (`GET /api/v1/countries`, `docs/localisation.md`).
3. **Later**: the owner signs in with just email and password (`docs/localisation.md` explains what each business sets for
   its own country: currency, phone code, tax numbers, payroll rules).

One person can register several businesses with the same email; signing in then asks which one.

## The sign-up wizard and resilience

The web form (`/register`) is a full-page five-step wizard: what you need (edition), about you (name, email, phone, role), password
(live rules from `POST /auth/password/check`), your business (country, currency, time zone, calling code, tax number, branches,
staff, kind of business) and review (consent, then create). Answers survive a refresh in sessionStorage (never the password).
Deep links: `/register?edition=retail` and `/register?plan=<public plan code>` (preselect only; unknown values are ignored; a
plan also selects its edition and, if still public at verification, is the trial the business starts on). The terms and privacy
links come from `VITE_TERMS_URL` and `VITE_PRIVACY_URL` at build time (no link when unset). `GET /api/v1/register/trial?edition=&plan=`
tells the form which trial to promise (null when there is no default plan: nothing is promised).

Optional request fields `phone`, `owner_role` (owner, manager, accountant, other), `business_size` (1, 2-5, 6-20, more),
`staff_size` (1-5, 6-20, 21-50, more), `business_type` (retail, wholesale, services, other) and `plan` are stored on
`master.registration` and, as onboarding hints only, on `master.tenant.onboarding`. A 422 from `register` carries `field` (the request
field at fault) so the form can show it on the right step.

**A business is never lost to an optional step.** Core creation (database, company, branch, owner, edition units) fails loudly:
`503 registration_failed` with the request id and `registration` id, the half-made tenant dropped, the link usable again. After it,
the country pack, the trial plan and the onboarding hints are optional: a failure is logged with the registration id, written to the
operator trail (`registration.setup_step_failed`), queued in `master.registration_repair` and retried by `ziira worker` every minute
(`registration.repair_pending`, idempotent; `ziira apply-packs <tenant>` does the pack by hand). A unit whose `hooks.py`, `events.py`
or `jobs.py` cannot be imported is skipped and logged by `registry.load_event_handlers` and reported by `/readyz`; tests, `ziira install` and
`ziira verify` raise instead.

## Editions

An *edition* is a named bundle: the units switched on, the order of the menu, the page opened after sign-in, a first-steps
checklist, the plugin categories recommended and the sample data on offer. They are **data** in `ziira/kernel/editions.toml`
(never per country); `ZIIRA_EDITIONS_FILE` points to a file of the same shape to replace them. Code: `ziira/kernel/editions.py`.

| Edition | For | Units (what each requires comes along) |
|---|---|---|
| `retail` | shops with a till | products, inventory, payments, pos, crm, imports, intel, command |
| `distribution` | retail plus buying and credit | retail + purchasing, finance |
| `books` | accounts, bills, customers | finance, purchasing, crm, imports, intel, command |
| `intelligence` | keep your system, add Ziira's checks | `ZIIRA_STANDALONE_UNITS` (connect, intel, command, imports) |
| `full` (default) | everything | `ZIIRA_REGISTRATION_UNITS` |

* `GET /api/v1/editions` (public) lists them for the sign-up form ("What do you need?"). The business's own is on
  `kernel.tenant.edition`; `GET /api/v1/edition` returns it with the checklist progress.
* `POST /api/v1/edition {"edition": "..."}` (permission `units.manage`) **switches**: the new edition's units are switched on; nothing is ever
  switched off and no data is touched. Taking a unit away stays an explicit act on Add-ons.
* First steps (`checklist`: id, title, hint, page, unit) show on Home only while their unit is on; people tick them
  (`PUT /api/v1/edition/steps/{id}`), the owner can hide the list. Progress is a manual tick, not detected from data.
* `sample_data` names kinds of sample data an edition offers; nothing creates it yet (the field is declared for the screens that will).
* The web menu follows `menu_groups`; signing in opens `landing` (once per browser session, only if the person may open it). Add-ons
  shows the edition, "what is on in my business", units grouped by `category`, and plugins recommended for the edition and the
  company's country (a plugin with `countries = [...]` is recommended only there; empty means worldwide).
* `ziira create-tenant ... --edition retail` switches the edition's units on (without `--edition` no unit is switched on, as before;
  `--mode standalone` still means `--edition intelligence`).

## Plans and trials

A business that registers starts a trial on the default plan (`billing.default_plan_code` in Super Admin settings, else
`ZIIRA_DEFAULT_PLAN_CODE`, else the edition's optional `default_plan` key in `editions.toml`). With no default plan it is
*unmanaged*: no limits and no billing. Units of the edition that the plan does not include are switched off (data kept).
The plan's units, limits and price are copied into its subscription. See `docs/platform-admin.md`.

## Settings (environment, prefix `ZIIRA_`)

| Setting | Meaning |
|---|---|
| `REGISTRATION_MODE` | `open` (anyone), `invite` (needs a code from `ziira invite create`), `closed` (operator creates businesses) |
| `EDITIONS_FILE` | optional TOML file of editions replacing the built-in `editions.toml` |
| `STANDALONE_UNITS` | units of the `intelligence` edition (older: `standalone` mode) (default `connect,intel,command,imports`; what they require comes along) |
| `REGISTRATION_UNITS` | units of the `full` edition (the default), comma separated (default: every business module: `pos,finance,crm,purchasing,people,imports,intel,command`; what they require comes along) |
| `REGISTRATION_PER_EMAIL_PER_HOUR`, `REGISTRATION_PER_IP_PER_HOUR` | rate limits (default 3 and 10): over them the answer is `429` |
| `REGISTRATION_TOKEN_HOURS` | how long the emailed link lasts (default 24) |
| `PUBLIC_WEB_URL` | where the emailed link points: the web app |
| `PLATFORM_EMAIL_PROVIDER`, `PLATFORM_EMAIL_SECRET`, `PLATFORM_EMAIL_CONFIG` | how the platform sends the verification email: a provider name from the messaging plugin (`smtp`, `brevo`, `resend`, `sendgrid`), its secret and config as JSON, e.g. `{"api_key": "..."}` and `{"from_address": "no-reply@example.com"}`. Empty: development and tests use a fake one |

**Production refuses to start** with open or invitation registration and no `PLATFORM_EMAIL_PROVIDER` (a link that cannot
be sent would make registration look broken), and with an unknown mode.

## What limits abuse

* **The email step.** Nothing is created until the link is used, so typing someone else's address creates nothing.
* **Rate limits** per email and per client address (`429 too_many_requests`). A new request for the same email makes the
  earlier link stop working; its row stays and still counts towards the limit.
* **Modes.** `invite` registration needs a code (`ziira invite create --uses 5 --days 30`; shown once, kept as a hash,
  spent when a link is verified); `closed` turns self-service off.
* **A failed provisioning** removes what was half made and leaves the link usable, so the person can try again.
* Registrations that expired (or were verified) more than a week ago are purged by `ziira worker`.

Not built yet: a CAPTCHA, billing and plans (a business is free), and an operator console (operators use `ziira tenants`,
`ziira enable`, `ziira drop-tenant`).

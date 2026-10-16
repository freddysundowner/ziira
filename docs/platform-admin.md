# Super Admin platform: plans, subscriptions, billing, subscribers

The operator console (`/operator`, same sign-in, still `master.operator`; email and password, plus an authenticator code only
when `ZIIRA_OPERATOR_MFA=totp`: see `docs/security.md`, "Platform staff sign-in") is the
**Super Admin**: where the platform owner manages plans and prices, subscribers, invoices and licences. Everything is
rows in the master database entered by the owner; no price, currency, tax rate or country is in code (rule 15).
Code: `ziira/kernel/platform/` (services), `ziira/kernel/api/platform_routes.py` (operator API),
`ziira/kernel/api/billing_routes.py` (the business's Plan & billing), `ziira/kernel/api/public_plan_routes.py`.
Licences: `docs/licensing.md`. Website content (company name, contact, legal text, social handles) is a separate
area of the same console (`platform.content`, `docs/platform-admin-content.md`).

## Deployment mode

`ZIIRA_DEPLOYMENT_MODE=saas` (default): this deployment sells subscriptions and enforces them.
`selfhosted`: subscription rows are ignored; a signed licence (`ziira licence install`) decides units, limits and
expiry. `ZIIRA_LICENCE_REQUIRED=true` makes an instance with no valid licence read-only.

## Operator roles and permissions

| Role | Permissions |
|---|---|
| superadmin | all |
| billing | view, subscribers, plans, billing, licences |
| support | view, subscribers |
| content | view, content |
| readonly | view |

Permissions: `platform.view` (every role), `platform.subscribers`, `platform.plans`, `platform.billing`,
`platform.licences`, `platform.units`, `platform.content`, `platform.ai` (AI providers, superadmin only: keys, models, default provider, spend cap, quality check; `docs/ai.md` section 12), `platform.operators`. Every operator route declares one
with `require("platform....")` (`api/operator_routes.py`); `tests/test_platform_roles.py` walks the routes and
calls each with every role. The command line makes the first superadmin
(`ziira operator create NAME EMAIL`, `--role` for others; `ziira operator role EMAIL ROLE`). Superadmins add and
disable operators, change roles, reset a password (a temporary one, shown once, changed at the next sign-in) and, in `totp` mode,
reset a second factor in the console (secrets are shown once and never logged). Everyone changes their own password under
Account ("Change my password"), where "Sign out everywhere" also lives; `ziira operator reset-password EMAIL` does the
reset from the command line.
Nobody changes their own role/status; the last active superadmin cannot be disabled or demoted. Every change needs a
recent confirmation (the operator's password again, or a fresh code in `totp` mode; `ZIIRA_OPERATOR_MFA_MAX_AGE_MINUTES`)
and leaves a line in `master.operator_action_log` (refusals too); changes to a subscriber
are filed under its workspace code.

## Plans, prices, add-ons, coupons

- **Plan**: code, name, edition and/or units, plugin add-on units, limits (`max_users`, `max_branches`,
  `max_companies`; empty = unlimited; extra informational caps in `limits`), trial days, billing intervals offered
  (`month`, `year`, `one_time`), public/hidden, active/retired. A retired plan keeps its subscribers but cannot be chosen.
- **Price**: one row per plan, currency, interval with `effective_from`. Append-only: the price in force is the latest
  row that started. A change adds a row (now or later); a "withdrawn" row stops offering it. A new price must start
  after the newest row; a scheduled price can be removed; one in force cannot be edited. Prices carry `tax_inclusive`.
- **Add-on**: a unit, or extra users/branches/companies, with its own priced rows. (Add-ons are listed publicly and
  priced; a subscription's limits today come from its plan, so selling an add-on is an invoice line plus a
  `sync`/comp by an operator. Automatic add-on quantities on subscriptions are not built.)
- **Coupon**: percent or a fixed amount per currency; `once`, `repeating N` invoices or `forever`; max redemptions,
  expiry, optional plan restriction.

`GET /api/v1/public/plans` (no sign-in, cached 60 s): `{plans:[{code,name,description,edition,highlights[],limits{},
trial_days,prices:[{currency,interval,amount,tax_inclusive}]}], addons:[...], updated_at}`; only public, active plans and
the prices in force now. Scheduled prices appear when they start (within the cache time).

## Subscriptions (SaaS)

`master.subscription`, one per business, copying the plan's units, limits and the price it was sold at; later plan
edits do not change it (`sync-plan` moves one over on purpose). Statuses:

`trialing -> active -> past_due -> grace -> suspended -> expired` (money not received), `cancelled`
(ended on request). Registration starts a trial on the default plan (setting `billing.default_plan_code`, else
`ZIIRA_DEFAULT_PLAN_CODE`, else the edition's `default_plan` in `editions.toml`; none = the business is *unmanaged*).
Businesses made from the command line stay unmanaged unless `--plan CODE` is given. Operators can start one, change plan,
extend a trial, comp (free, optionally until a date), apply a coupon, suspend/reactivate, cancel (at period end or now),
and delete (below).

**Plan change rules** (simple, by days): during a trial or comp the new plan applies at once. On a paid subscription a
dearer plan in the same currency and interval applies at once and the rest of the period is charged
`(new - old) x days left / days in period` (a part day counts as a day, rounded to the cent). A cheaper plan, another
interval or another currency starts at the end of the period (setting `billing.proration.downgrade = now` makes
downgrades immediate, with no credit). Units outside the new plan are switched **off** (data kept); users/branches over a
new limit stay, but no more can be added.

## Enforcement

`platform/entitlements.py`, used by the kernel:

| Status | Access |
|---|---|
| trialing, active | full |
| past_due, grace | full; the owner sees a banner (`GET /billing/status`) |
| suspended | only sign-in, `/billing/*`, the shell's start-up reads, privacy requests, CSV exports (`?format=csv`) and the till's `POST /pos/sync/upload`; everything else is **402** `subscription_suspended` |
| cancelled, expired | reads work; writes are **402** `subscription_ended` (billing and till uploads still work) |

Also: switching on a unit outside the plan is **402** `not_in_plan` ("not in your plan: upgrade"); adding a user, branch
or company over the limit is **402** `plan_limit_reached`. Platform staff in a support session are not stopped.
A business event that already happened (an offline sale) is accepted while suspended and flagged as usual.
Nothing is ever deleted by enforcement. Deleting is a separate, deliberate act:

- `POST /operator/subscribers/{code}/delete` needs the code typed, a reason, a subscription that is not live, and
  (unless `early`, which is for the business's own request) the retention period after it ended (`billing.retention_days`,
  default 90). It schedules the deletion after `billing.cooling_off_days` (default 7); the worker carries it out unless the
  subscription became live again; either can be cancelled; the operator trail records both. Invoices survive (the
  tenant link is cleared, the bill-to name stays).
- Decisions are cached ~10 s per process.

Self-hosted: see `docs/licensing.md`.

## Billing

- **Settings** (`billing.*`, `vendor`; Super Admin > Billing > Settings): vendor details, tax lines (name + rate,
  copied onto each invoice), payment instructions, invoice prefix, days until due, renewal lead days, dunning schedule,
  proration, default plan, retention and cooling-off days, extra notification emails.
- **Invoice**: lines, tax (exclusive: `round(net x rate)` per line; inclusive: the price holds the tax, `round(net x rate
  / (100 + sum of rates))`, last line takes rounding), discount lines, totals; draft (no number) -> issued (number from a
  counter in the same transaction, dates and vendor details fixed) -> paid | void. An issued invoice is never edited; a
  void number is never reused. Printable page: `GET .../invoices/{id}/html` (escaped, no scripts).
- **Payments**: recorded by hand (method, reference, amount, date), partial allowed, reversible. Paying in full marks the
  invoice paid; for a subscriber it applies a carried plan change and moves the period on (from the end of the last one, or
  from now if paid very late) and sets `active`. A reversal puts the invoice back to issued but does not move a
  subscription back; dunning re-evaluates.
- **Recurring pass** `billing.run_due()` (the worker runs it hourly in saas mode; `ziira billing-run`; Billing > "Run
  now"): renewal invoices `renewal_lead_days` before the period (or trial) ends (price = the subscription's, or the
  scheduled plan's; coupon applied and counted; free plans just roll on), cancellations that fall due, reminders and
  status moves, due deletions. Safe to repeat; takes a frozen `now` in tests.
- **Dunning** (`billing.dunning`, defaults): reminders at -7, 0, 3, 7 days from the due date (only the latest due one is
  emailed; earlier ones are marked done); past_due after 1 day, grace after 7, suspended after 21, expired after 90.
  Payment sets `active` again.
- **Providers** (`platform/providers.py`): the socket for a payment gateway (`checkout_link`, `charge`, `parse_webhook`).
  `manual` (money outside the system) and `fake` (tests; refuses production) exist; **no real gateway is implemented**.
- **Self-serve upgrade**: the business's Plan & billing page (`/api/v1/billing/*`, permission `billing.manage`) shows
  plan, status, usage vs limits, invoices (own only), payment instructions, cancel/resume, and "request a plan": it makes
  a request (and a draft invoice where money is due now), emails the billing operators, and the operator approves
  (invoice issued) or declines. Paying the invoice changes the plan.
- **Paying by oneself** (`docs/subscription-payments.md`): payment-gateway plugins (`kernel.payment_gateway`; M-Pesa,
  card ...) are switched on and given their keys in Super Admin > Billing > Payment methods; a business picks a plan
  ("Choose a plan" creates and issues the invoice at once) and pays it in the app; the provider's confirmation (never the
  browser, never a notification alone) credits the invoice through the same payment service as a manual payment. Billing >
  Payment attempts lists every try, with "Re-check now" and "Mark as paid manually".

## Subscribers directory and dashboard

`GET /operator/subscribers` (search, status, plan, edition, country, flag `trial_ending|past_due|churned|unmanaged`)
and `/subscribers/{code}` (profile, owners, subscription and timeline, invoices/payments/requests, usage vs limits,
units, support grants and sessions, operator audit trail, deletion state). Impersonation is only through the business's
support grant. `GET .../export` gives the platform's records about the subscriber; the business's own data is exported by
the business or with `ziira backup --tenant CODE`. Contact erasure (`/privacy/contact/erase`) anonymises a person's name
and email on invoices (the money record stays) and deletes their registrations.

The dashboard shows MRR/ARR **per currency, never converted** (paying subscriptions, yearly / 12, after running
coupons; comps, trials and one-time purchases excluded), new and churned in 30 days, trials and conversion, overdue
totals, counts by status/plan/edition/country, usage hot spots (>= 80% of a limit), renewals due in 14 days, failed
jobs, pending plan requests.

## Threat model and limits

Operators: password (12+ characters, throttled, short sessions) with an optional second factor (`ZIIRA_OPERATOR_MFA`; password-only
is a documented risk, refused in production unless acknowledged), a recent confirmation per change, roles, immutable action trail. Business
isolation: `/billing/*` reads only the caller's own subscription and invoices (invoice ids of others answer 404). Not
built / honest limits: no real payment gateway; add-on quantities are not applied to a subscription automatically;
the enforcement cache lets a status change take up to ~10 s on another process; non-owner users get the same 402 as owners
when suspended (they cannot reach billing without `billing.manage`); a suspended account's data export is the CSV
download endpoints and privacy requests, not a one-click full export.

## Email and platform settings (Super Admin > Platform > Email / Settings)

Permission `platform.settings` (superadmin only). Every change needs a fresh confirmation and leaves a line in the operator
trail that names the fields changed, never a secret.

**Email** (`kernel/platform/mail.py`, providers described in `kernel/mail_providers.py`, API `/api/v1/operator/email*`).
Pick a provider (SMTP, Brevo, Resend, SendGrid: the channels the messaging plugin registers), type its credentials (stored
encrypted in `master.platform_email_provider`; write-only, shown only as set / not set), set the sender (from address, name,
reply-to), send a test email and then **Make live**. Making a provider live is refused until a test through it was delivered;
any later edit of it or of the sender starts the test again. "Check configuration" gives advice (SPF/DKIM hints, free-mail
senders, port/security mismatch) and looks nothing up. The page shows the source in use (platform settings / environment /
development fake), the last test, the last successful send and the failures of the last 24 hours, and a log of the last 50
messages (kind, recipient masked as `j***@gmail.com`, result; never the message or a secret; kept 90 days, purged by the worker).
The mailer reads the live configuration from the master tables (cached 30 s, cleared on change) and falls back to the
`ZIIRA_PLATFORM_EMAIL_*` environment settings, then to the development fake. When the page says "currently using environment
settings", **Move to platform settings** copies the plain fields and the sender; type the secret, test, make live.
To add a provider: write its channel, then `register(MailProvider(...))` in `kernel/mail_providers.py`.

**Settings** (`kernel/platform/behaviour.py`, `/api/v1/operator/platform/behaviour/{key}`, same table as the billing settings but
a separate key set that the billing route cannot write): registration mode (open / invite / closed; open and invite are refused
unless email works, and in production a mode other than closed reads as closed to the public while no email works), default
edition, trial length override, public web and API addresses (used in emailed links), and the terms, privacy, help, website and
support-email links. `GET /api/v1/public/config` exposes only the sign-up state and those links; the web app's Register page uses
it (closed / invite-only states) with the `VITE_*` values as fallback. An empty value means "use the environment".
The start-up refusal "open registration needs ZIIRA_PLATFORM_EMAIL_PROVIDER" is gone (check_env.py warns instead).

**Installer alignment (deploy/ not edited):** these installer questions/flags become optional: the SMTP/mailer prompts and
`ZIIRA_PLATFORM_EMAIL_*`, `--registration-mode` / `ZIIRA_REGISTRATION_MODE`, and any public URL prompt for the *links* (the
public base URLs are still needed as environment values for nginx/TLS and before the first sign-in, but can be overridden in
Settings). All existing flags keep working as the fallback. Fresh installs should leave registration to the Super Admin.

**Settings still in the environment (recommendation):** `ZIIRA_METRICS_TOKEN` (keep in env: monitoring must work without the
database), `ZIIRA_SITE_BUILD_HOOK_URL/SECRET` (move to Platform > Website later), `ZIIRA_SECRET_KEY` / `CREDENTIALS_KEY` (must stay
in env), AI keys (moving to the Super Admin AI page), payment providers (done), SMS provider for platform messages (none exists:
businesses use their own channel credentials). OAuth app credentials for Zoho Books / QuickBooks and the Lead Intel platform key
are **not** platform-level today: each business enters its own client id/secret and key (`connect`, `leadsintel`), so nothing was
moved; a shared Ziira-owned OAuth app would be a design change.

Tests: `tests/test_platform_email.py` (mocked transports; secrets never in responses, trail or log; masking; env fallback and move;
registration guard; public config). Not run: real mail providers (request shapes are from public documentation).

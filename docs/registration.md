# Registration: how a business joins

Ziira is a SaaS: a business creates itself, with no operator involved.

```
POST /api/v1/register          the person asks for a business     -> 202, nothing created yet
   (email with a link)         https://<web app>/register/verify?token=...
POST /api/v1/register/verify   the link is used                   -> the business exists, the owner is signed in
```

1. **Register** (`POST /api/v1/register`): business name, owner name, email, password, currency, phone country code, and
   optionally a tax number and an invitation code, and a `mode`: `core` (default: run the business on Ziira) or `standalone` (Ziira only
   watches the system the business already has, `docs/standalone-mode.md`). The request is saved in the master database (`master.registration`)
   with the password already hashed and the emailed token only as a hash. **No database, login or tenant exists yet.**
   The reply is the same whatever the email, so it reveals nothing. Outside production it also carries `dev_token` (the
   token the email holds) so tests and local development need no mailbox.
2. **Verify** (`POST /api/v1/register/verify`, from the emailed link, works once, expires after
   `ZIIRA_REGISTRATION_TOKEN_HOURS`): the business is provisioned (its own database and login, copied from the template in
   about a second), the owner gets the Owner role, the default units are switched on, the owner's email goes into the login
   directory, and the owner is signed in. The workspace code is made from the business name (`acme-traders`, then
   `acme-traders-2` ...); people never type it.
3. **Later**: the owner signs in with just email and password (`docs/localisation.md` explains what each business sets for
   its own country: currency, phone code, tax numbers, payroll rules).

One person can register several businesses with the same email; signing in then asks which one.

## Settings (environment, prefix `ZIIRA_`)

| Setting | Meaning |
|---|---|
| `REGISTRATION_MODE` | `open` (anyone), `invite` (needs a code from `ziira invite create`), `closed` (operator creates businesses) |
| `STANDALONE_UNITS` | units switched on for a business that registers in `standalone` mode (default `connect,intel,command,imports`; what they require comes along) |
| `REGISTRATION_UNITS` | units switched on for every new business, comma separated (default: every business module: `pos,finance,crm,purchasing,people,imports,intel,command`; what they require comes along) |
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

# Security

What protects a business's data, what is switched on by default, what the operator must do, and what an external
penetration tester should be given. Specification: `docs/specs/Ziira_Core_1.0_Technical_Specification.txt` section 18.
**Status: the controls below are built and tested; no external penetration test has been done yet (it is a phase 11 exit
criterion: see "Penetration test").**

## Who can do what (access)

| Layer | How |
|---|---|
| Tenancy | One database per business with its own login (`decisions/0004`), and row-level security on every table as a second layer. Code reaches a business only through `tenant_session`. |
| Permissions | Every route names a permission; services check the scope (tenant, company, branch, own). Roles are data; no escalation (a role cannot give what its holder lacks). |
| Separation of duties | Creator and approver differ where configured (approvals, payroll, pay terms, manual journals, bank-detail changes); Intelligence flags where they did not (`controls.*`, `finance.same_person_approval`, `people.pay_self_approved`). |
| Immutability | Stock movements, journal entries and the audit log reject UPDATE/DELETE in the database; the audit log is hash-chained per business (`kernel/audit.py`, `verify_chain`). |
| API keys | Scoped to permission codes (optionally read-only, one company or branch), public API endpoints only, per-key rate limit and usage log, expiry and rotation; stored as hashes, shown once, revocable (docs/public-api.md). |
| Outgoing webhooks | HTTPS to public addresses only (re-resolved at every send), HMAC-signed, payloads limited to listed fields, bodies purged after days (docs/webhooks.md). |
| Third-party plugins | Extra folder only; production loads them only when allow-listed with a reviewed checksum (docs/plugin-review.md). |

## Signing in

- **Password**: hashed with scrypt; at least 8 characters, not one of the passwords everybody tries first, not the login
  (`kernel/passwords.py`). Unknown logins take as long as real ones and get the same answer.
- **Throttling** (`kernel/throttle.py`): failed attempts are counted per login from one address (5), per login from anywhere (20) and per
  address (60) in 15 minutes; then that key is locked for 15 minutes and the API answers `429` with `Retry-After`. A good sign-in
  clears the login counters. The same mechanism limits second-factor codes (5 per person), password reset requests (3 per login,
  10 per address) and reset-link guesses. Counters hold only keyed hashes. Settings: `ZIIRA_THROTTLE_*`.
  *Behind a proxy set `ZIIRA_TRUST_FORWARDED_FOR=true`* so the limits see the real client address (`kernel/auth.py client_ip`).
- **Second factor** (`kernel/mfa.py`): time-based one-time codes (RFC 6238; verified against the RFC's test vectors), ten single-use
  backup codes, replay protection, 30-second drift. The secret is stored encrypted, backup codes hashed. The business chooses
  who must use it (`PATCH /settings/security`: `off`, `privileged` = people holding a powerful permission such as users.manage,
  roles.manage, settings.manage, journal.approve, period.close, payroll.approve/pay, `everyone`). Someone who must but has not set it
  up can only do the setup (`403 mfa_setup_required` on everything else). An administrator resets a lost device
  (`POST /users/{id}/mfa/reset`: signs them out). **Production refuses to start with `ZIIRA_MFA_DEFAULT_POLICY=off`**; new businesses start with
  the default policy. Codes by SMS/email are not offered (they are weaker; the authenticator app and backup codes cover it).
- **Forgotten password** (`kernel/password_reset.py`): an emailed one-use link (hash stored, valid `ZIIRA_PASSWORD_RESET_HOURS`, default 2),
  the answer never reveals whether the login exists, using it signs the person out everywhere and does **not** bypass the second factor.
- **Sessions**: access tokens last 15 minutes and name a session checked on every request (sign-out and disabling take effect at once);
  refresh tokens are bound to the device and replaced on every use; a session idle for `ZIIRA_SESSION_IDLE_HOURS` (12) must sign in again;
  remote sign-out of any device.

## Data in transit and at rest

- TLS is the operator's (terminate at the proxy); HSTS is sent in production. Database encryption at rest and encrypted backups are the
  operator's (`docs/operations.md`). Integration secrets (Daraja, bank, SMS/email) and tenant connection strings are encrypted with Fernet
  using `ZIIRA_CREDENTIALS_KEY` (losing it locks out every business: back it up separately from the database).
- Secrets and personal numbers are redacted from logs (`kernel/http_middleware.py`, `docs/operations.md`).

## The AI assistant

Optional and off until an Owner consents (`docs/ai.md`). What it adds to the attack surface and how it is bounded: the provider's API
key is a platform secret entered in the Super Admin (stored encrypted in the master database, write-only, only its last four characters shown; `ZIIRA_AI_API_KEY` is the development fallback), never stored per business and removed from every log and error; personal details are
scrubbed from what is sent and people's names become labels; the model can only call defined tools (no SQL, no writes), each tool
filters by the asking person's permissions and branches and the model's arguments are checked against a schema; a tool the person may
not use is not offered and is refused if named; loops, tokens and time are capped, and a monthly token limit per business is a hard
stop; every call and refusal is logged (hash of what was sent, tools, tokens, outcome) without text; conversations are visible to
their owner and to `ai.manage` holders only. Prompt injection: text in records (a customer name, a note) can reach the model through
a tool result, so the model's output is never trusted: it cannot act, and its numbers are checked against the data. Production refuses
every call to a provider until the operator acknowledges its no-training and retention terms in the Super Admin (who/when recorded; `ZIIRA_AI_TERMS_CONFIRMED` for the environment fallback). A monthly spend cap and a per-provider acknowledgement are platform controls (`docs/ai.md` section 12).

## Application security

Input validation on every request (Pydantic types, `Quantity`/`Amount` for numbers; the fuzzer in `tests/test_robustness.py` checks every endpoint
for server errors), parameterised SQL everywhere (tests try injection-style logins and inputs: `tests/test_security.py`), security headers,
CORS allow-list, request size limit, `Cache-Control: no-store` on API replies, CSV formula-injection protection (`ziira.sdk.safe`), no
tenant data in error messages. **Every CSV download is written to the audit log** (`kernel/export_audit.py`: who, address, which export, how many bytes).

## Audit and detection

Logins and failed logins, second-factor events (enabled, failed, backup code used, disabled, reset by an administrator), password
changes and resets, role grants, API key creation, approvals, every posted document, and data exports are in the immutable
audit log; Intelligence turns some patterns into findings (approval by the requester, wide access granted, activity at odd hours, exceptions
nobody reviewed). `GET /metrics` and the alerting list in `docs/operations.md` cover availability.

## Staff access to a business's data

Platform staff ("operators") are not users of any business and see nothing without the business's consent (Spec 18, "Access by staff").

- **Consent.** A business user with `support.grant` (Owner by default) gives a *support grant* under Settings, Support access (or
  `POST /api/v1/support/grants`): a reason, a level (`read` or `full`), and a length of 1 hour to 7 days (default 24 hours). They can
  list grants, see who used each, and revoke at any moment; revoking ends every open support session with the next request.
- **Operators.** The first is made by the CLI (`ziira operator create`), the rest by a superadmin in the Super Admin. They are stored in
  the master database with a scrypt password hash. How they sign in is a setting, `ZIIRA_OPERATOR_MFA` (see "Platform staff sign-in"
  below): `off` (the default) is email and password alone; `totp` adds a code from an authenticator app (`/operator/mfa/verify`).
  Either way sign-in is throttled like business sign-ins, and operator tokens (kind `op`, revocable) are refused by every business
  endpoint, as business tokens are by the operator endpoints.
- **Sessions.** `POST /api/v1/operator/businesses/{code}/support-session` works only while that business has a grant that is neither
  expired nor revoked, and returns a token for at most 60 minutes. The token is re-checked against the grant (and the operator's
  status) on **every request**, so expiry, revocation and disabling an operator apply to sessions already open. A grant in one
  business gives nothing in another.
- **Limits.** A `read` session holds only `*.view` permissions (not `payroll.view`) and every non-GET request is refused. A `full`
  session holds every permission except `users.manage`, `roles.manage`, `api_keys.manage`, `support.grant`, `privacy.manage` and
  `units.manage`, and may not change passwords, two-step verification, roles, users, API keys, the security policy, support grants, or
  sign anyone out. There is no user behind a support session (the audit `user_id` is empty).
- **Logging.** Every request is written (after the response) to the business's own audit log (channel `support`, action
  `support_request`, with method, route template and status) and to `master.support_access_log` (start, end, revoked, each request or
  refusal: operator, business, grant, route template, status; the database refuses updates and deletes). Writes made in a session
  also carry `support_operator_id` and `support_operator` in the audit entry's `changes`. The owner reads this at
  `GET /api/v1/support/access-log` and on the Support access page. When a session opens, the person who gave the access is emailed
  (through the business's email channel, if it has one) and `/auth/me` carries `support_session` so the web app shows a red bar.

Not covered: the database credentials in the master database still let someone with server access read any tenant database directly;
that is an infrastructure control (who has server access), not something this feature can prevent. Request logging is written after
the response and a failure to write is logged at error level, not shown to the operator.

### The operator console (`/operator`)

Platform staff also have a web area at `/operator` (a separate small app, loaded only when opened; it has no business menu).
It uses the operator sign-in described above (email and password; then a code when `ZIIRA_OPERATOR_MFA=totp`), keeps its token apart from any business session (in memory
and the tab's session storage), and is only a screen over `/api/v1/operator/...`: a business user's token is refused there (401),
and an operator token is refused by every business endpoint.

What it can do, all through the same functions the command line uses:

- **Platform units:** list every unit found on disk (version on disk and installed, status, what it requires, how many businesses have
  it on); install a unit and what it requires; upgrade (new migrations in every business database that has it); uninstall (refused
  for the kernel, for units that installed units require, and while any business database still has the unit, which the answer
  names). Uninstalling never deletes business data, because none can exist at that point.
- **Businesses:** a list with figures only (edition, country, users, units on, last activity; never records); one business's units can
  be switched on or off with a **mandatory reason**, and the grant state and open support sessions are shown. A support session still
  opens only under the business's own grant (the console calls the same endpoint and shows the same 403).
- **Platform health and operators:** readiness, which businesses are behind on migrations (with an "upgrade businesses" action, one
  business at a time), backup age (read from the backup manifests in `ZIIRA_BACKUP_DIR`; nothing is run), queue and worker figures,
  pending registrations, plugins loaded from extra folders and their checksum and allow-list state; the operators and their second
  factor state (read only: creating, disabling and resetting stay on the command line).

How it is held to account:

- **Recent confirmation.** Every change (not reading) needs the operator's identity confirmed within
  `ZIIRA_OPERATOR_MFA_MAX_AGE_MINUTES` (default 10); signing in counts. Otherwise the answer is 403 `mfa_step_up_required` (the code is
  kept for compatibility; the message reads "Confirm your password to make this change") and the screen asks for the **password again**
  (`POST /api/v1/operator/confirm` {password}, throttled like sign-in; with `totp` it asks for a fresh authenticator code instead) and
  repeats the change. This covers installing and uninstalling units, plans and prices, licences, operator management, payment and
  billing settings, marking invoices paid and deleting subscribers: every console change goes through the same gate.
- **Logged twice.** Each change, and each refused one, is a line in `master.operator_action_log` (who, what, target, reason, result;
  the database refuses updates and deletes). A change inside a business (switching a unit) is also written to that business's own
  audit log, channel `support`, naming the operator and the reason, so the owner sees it under Support access.
- **Nothing secret goes out:** no connection strings, keys, password hashes or second-factor secrets appear in any response (a test
  searches the responses). The access token of a support session is the one thing shown, once, when a session is opened.

What it cannot do: read a business's records without a grant, delete business data, install or load a plugin
from outside the configured extra folders (production loads only plugins on `ZIIRA_ALLOWED_PLUGINS`; the console reports that state but
does not change it), or change settings in the environment. An operator with a recent confirmation can still install any unit found on disk, so
who becomes an operator, and who can write to the extra plugin folders, is the real control.

### Super Admin roles and billing

### Platform staff sign-in: `ZIIRA_OPERATOR_MFA`

| Setting | Sign-in | Changes ask for |
| --- | --- | --- |
| `off` (default) | email + password, session issued at once | the password again, when the last confirmation is older than `ZIIRA_OPERATOR_MFA_MAX_AGE_MINUTES` |
| `totp` | email + password, then a 6-digit code from an authenticator app (the behaviour before this setting existed) | a fresh code |

**The risk of `off`, stated plainly:** one stolen, guessed, phished or reused Super Admin password gives control of every business on
the platform (units, plans, prices, licences, payment settings, subscribers' state, support access to any business that has given a
grant). Production therefore refuses to start with `ZIIRA_OPERATOR_MFA=off` unless `ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED=true` is also
set, `scripts/check_env.py` prints the risk as a WARNING (an ERROR without the acknowledgement), and the Super Admin shows a warning
banner ("Two-step verification is off for the Super Admin"; it can be dismissed for the browser session and comes back).

Controls that stay or are added when it is off:

- **Passwords:** at least 8 characters (the same as users), not on the common list, not the email; checked when an operator is created, a
  password is changed or reset. Stored as scrypt hashes. A password made by someone else (a console-made account, a reset) is
  temporary: the person must choose their own at the first sign-in (`must_change_password`; every other call answers 403
  `password_change_required` until then). A reset is `ziira operator reset-password EMAIL` (prints a random temporary password once;
  with `ZIIRA_OPERATOR_PASSWORD` set it uses that one instead) or "Reset password" in the Super Admin (superadmins; never your own).
- **Throttling:** wrong passwords are counted and locked per login (5), per address (30), 429 with `Retry-After`; the same for the
  password re-entry and a password change. The answer for a wrong email, a wrong password and a disabled account is the same message.
- **Short sessions:** an operator sign-in ends after `ZIIRA_OPERATOR_SESSION_HOURS` (default 8) or after `ZIIRA_OPERATOR_IDLE_MINUTES`
  (default 30) without a request. "Sign out everywhere" (account page, `POST /operator/sign-out-all`) and changing the password end
  the other sign-ins; disabling an operator or changing their role ends all of theirs.
- **Audit:** every sign-in success and failure, every password confirmation, change and reset, and every sign-out is a line in
  `master.operator_action_log` (actions `auth.*`) with the address and the reason code (`wrong password`, `unknown login`,
  `disabled`); never the password, a code or a typed email that is not shaped like one. Attempts refused for being locked out are
  not logged one by one (that would let an attacker fill the log); the failures that caused the lock are.
- **New-address emails:** with `ZIIRA_OPERATOR_SIGNIN_EMAILS=true` and the platform email provider configured, the operator is emailed
  when a sign-in comes from an address with no earlier successful sign-in. Sent after the reply; a failure is logged and never blocks
  sign-in. Only the address is compared (there is no device fingerprint).
- **Address allow-list:** `ZIIRA_OPERATOR_ALLOWED_NETWORKS` (comma separated CIDRs, IPv4 or IPv6; empty: no restriction) is enforced on
  every `/api/v1/operator` route, sign-in included (403 `network_not_allowed`); business routes are not affected. The address is the
  connection's own, or, with `ZIIRA_TRUST_FORWARDED_FOR=true` behind a proxy you control, the **last** `X-Forwarded-For` entry (the one
  the proxy appended; earlier entries can be forged and are ignored). A caller whose address cannot be read is refused. Set the same
  restriction at the reverse proxy for `/operator` and `/api/v1/operator`: this is the second lock.
- **Also:** keep operator passwords in a secrets manager (long, unique, never reused), give each person their own operator, keep the
  number of superadmins small, and read the trail (`select occurred_at, operator_name, action, outcome, ip_address, detail from
  master.operator_action_log where action like 'auth.%' order by id desc limit 200;`) in the monthly review.

Switching modes: operators made while it was `off` have no authenticator secret; under `totp` they cannot sign in until
`ziira operator reset-mfa EMAIL` gives them one. Operators who had a secret keep it, but while the setting is `off` it is not asked for
(this lowers their protection: an owner who wants it back sets `totp`). The tests for `totp` mode are unchanged
(`tests/test_support_access.py`, `test_operator_console.py`, `test_platform_roles.py` pin it); the password mode is
`tests/test_operator_password_only.py`. Not covered by any test: a real proxy's header handling, real email delivery of the
new-address notice.

### Super Admin roles and billing

Operators have a role (superadmin, billing, support, content, readonly) and every operator route checks a permission
(`platform.view|subscribers|plans|billing|licences|units|content|operators`); a matrix test covers every route. Superadmins
manage operators in the console; secrets and temporary passwords are shown once and never written to the trail. A business reads only its own
plan and invoices (`/api/v1/billing/*`, permission `billing.manage`). Licences are Ed25519-signed; the private key never
leaves the vendor side. Details and limits: `docs/platform-admin.md`, `docs/licensing.md`.

### Subscription payments (`docs/subscription-payments.md`)

Gateway keys and webhook secrets are entered by an operator with `platform.billing` and a fresh second factor, stored
encrypted (`master.payment_gateway.secrets_encrypted`, the credentials key) and never returned, logged or written to the
trail (the trail keeps the gateway and the field names only). A provider's notification (`POST
/api/v1/billing/webhooks/<provider>`, public) is verified on the **raw body** with a constant-time comparison before it is
read (Stripe: `t=` timestamp within 5 minutes; others: HMAC of the body); it only makes the platform ask the provider,
and an invoice is credited only when the provider's own answer confirms status, amount, currency and invoice reference.
A mismatch is never credited and is emailed to the billing operators. One open attempt per invoice and five attempts an
hour per business; the payer's phone number is never stored whole (last four digits and a keyed hash only).

## Dependencies and supply chain

CI runs dependency scanning (`pip-audit`, `npm audit`) and a secret scan (see `.github/workflows/`). Pin and review updates; run
`npm audit --omit=dev --audit-level=high` and `pip-audit` before each release.

## Operator checklist (before real customers)

- [ ] `ZIIRA_ENV=production` (the start-up checks refuse dev shortcuts: dev tenant header, default keys, open registration with no way to send mail, MFA policy off).
- [ ] `ZIIRA_SECRET_KEY` and `ZIIRA_CREDENTIALS_KEY` random (32+ characters), stored in a secrets manager, backed up apart from the database.
- [ ] Super Admin sign-in decided on purpose: `ZIIRA_OPERATOR_MFA=totp`, or `off` with `ZIIRA_OPERATOR_MFA_OFF_ACKNOWLEDGED=true`, `ZIIRA_OPERATOR_ALLOWED_NETWORKS` set (and the same at the proxy) and `ZIIRA_OPERATOR_SIGNIN_EMAILS=true`.
- [ ] `ZIIRA_MFA_DEFAULT_POLICY=privileged` (or `everyone`); every existing owner and finance user set up their second factor and saved their backup codes.
- [ ] `ZIIRA_TRUST_FORWARDED_FOR=true` only behind the proxy; the proxy overwrites `X-Forwarded-For`; TLS 1.2+; HSTS preload decision.
- [ ] CORS origins, `ZIIRA_PUBLIC_WEB_URL`, platform email provider verified (reset and registration links work end to end).
- [ ] Database not reachable from the internet; one login per business; least-privilege roles; backups encrypted and the monthly restore test running.
- [ ] `scripts/check_env.py` passes for the production `.env`.
- [ ] If the AI assistant will be offered: the provider's data terms (no training on API data, retention) are in place and the provider is
      listed as a sub-processor; `ZIIRA_AI_API_KEY` set and `ZIIRA_AI_TERMS_CONFIRMED=true`; `scripts/live_check.py ai` passed (`docs/ai.md`).
- [ ] Penetration test done and its findings fixed (below).

## Penetration test (scope to hand to the testers)

Targets: the API (`/api/v1`, OpenAPI at `/openapi.json` on a staging copy), the web app, the POS terminal flows, the public callbacks
(payment provider callbacks, signed URLs), registration/reset/verify links, and the worker's inputs (CSV/bank statement imports).
Ask them to try in particular: tenant isolation (another business's ids in every parameter; direct database role abuse), branch/company scope bypass,
permission escalation through role editing and API keys, authentication (throttle bypass by address rotation, token and refresh replay, challenge reuse,
second-factor bypass, reset-link guessing and replay, enumeration by timing or message), idempotency abuse (double submit of money-moving calls),
file/CSV import abuse (formula injection, oversized files, encoding tricks), SSRF through configurable provider URLs, mass assignment, race conditions
on approvals, payroll and stock, and denial-of-service by expensive queries. Provide: staging with two businesses, accounts for each role, API keys,
the OpenAPI file, and this document. Track findings in the issue tracker with severity, fix, and a regression test in `tests/test_security.py`.

## Reporting a vulnerability

Give an address that reaches the operator (security@ your domain), acknowledge within two working days, fix and disclose responsibly,
and credit reporters who wish. Put the real contact in the web app's footer and `/.well-known/security.txt` when the domain is known.

## Inbound webhooks and replies by chat (`docs/channels.md`)

* **A webhook is verified before it is read.** The Lead Intel endpoint checks, in this order: the address token (which names the
  business and one connection; an unknown token, a wrong business and a bad signature all get the same `401`), a timestamp within
  five minutes, the lower-case hex `HMAC-SHA256(webhook secret, "<timestamp>.<raw body>")` compared in constant time over the exact
  bytes, then records the event id so a replay does nothing. Only then is the body parsed. The webhook secret and the platform key
  are in the credential store (encrypted), never returned by an API, never logged, never in a job payload or an audit entry
  (`tests/test_leadsintel.py` scans for them).
* **A reply acts as one verified person.** A number is matched to a user only if it is that user's *verified* number on a channel that receives replies
  (a code was typed back; one verified number per person) and the user is active. Anything else is stored and ignored with no reply,
  so nothing is revealed about who is known. A matched command runs with that user's own permissions and the audit channel `chat`,
  limited to 30 commands per 10 minutes, and each command is audited (`channel.command`). A suggestion that is no longer open is
  refused. Core permissions still decide: a reply can never do more than the person could in the app.
* **STOP always works**, from any sender, on every channel.


## The chat bot's public inbound address and its secrets (`docs/ai.md` section 15)

* **Same order as the business webhook, with one address for the whole platform.** `POST /api/v1/public/chat/inbound/{token}`: body limit (64 KB); the token is looked up by its SHA-256 hash (the token is random, 256 bits, made by the server, stored only as that hash); the provider checks
  the timestamp (five minutes) and `HMAC-SHA256(secret, "<timestamp>.<raw body>")` in constant time; only then is the event id recorded (a repeat does nothing) and the body read. An unknown token, a bad or stale signature, an oversize body and a bot that is not set up all return the same `401 Not accepted`
  and cost the caller one count against its address only (never against the token, so a stranger who learns the address cannot lock the provider out). A body that is genuine but unreadable gets `204`, never a `500`.
* **Secrets.** The provider key and the webhook secret are one Fernet token in `master.chat_bot.secrets_encrypted`: write-only, never returned by an API (the page sees "set / not set"), never logged, never in the operator trail, the queue or an error message (a provider's reason is stripped of them first).
  `tests/test_chat_bot.py` scans every reply, the log, the trail, the stored row and the queue for the key, the secret and the token. The token also appears in the *path* the provider calls, so it shows in a reverse proxy's access log: keep access logs private, and use "Rotate the secret" if one leaks.
* **No SSRF.** The only address the bot ever calls is the provider's fixed base address (`https://app.leadsintel.net/api`, changeable only by the environment variable `ZIIRA_LEADSINTEL_PLATFORM_BASE_URL`, for tests); nothing in a delivery or a setting makes the server call another host, and redirects are not followed.
* **No personal data at rest beyond what is needed.** Senders are keyed hashes plus a masked display; their words (scrubbed of emails and long numbers) live at most 7 days; the number is in the queue only encrypted and only until the job ends; logs hold the outcome and a short hash, never a word. A person's STOP is honoured at once.
* **Prompt injection** is handled as for the website assistant: the system rules come last, the person's words and history are quoted as untrusted text, the bot has no tools and no data of any business, and every sentence with a figure, address or email that is not in the knowledge is replaced before it is sent.

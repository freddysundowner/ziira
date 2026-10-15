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
| API keys | Scoped to permission codes, stored as hashes, shown once, revocable. |

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
key is a platform secret (`ZIIRA_AI_API_KEY`), never stored per business and removed from every log and error; personal details are
scrubbed from what is sent and people's names become labels; the model can only call defined tools (no SQL, no writes), each tool
filters by the asking person's permissions and branches and the model's arguments are checked against a schema; a tool the person may
not use is not offered and is refused if named; loops, tokens and time are capped, and a monthly token limit per business is a hard
stop; every call and refusal is logged (hash of what was sent, tools, tokens, outcome) without text; conversations are visible to
their owner and to `ai.manage` holders only. Prompt injection: text in records (a customer name, a note) can reach the model through
a tool result, so the model's output is never trusted: it cannot act, and its numbers are checked against the data. Production refuses
every call until the operator confirms the provider's no-training and retention terms (`ZIIRA_AI_TERMS_CONFIRMED`).

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
- **Operators.** Created only by the CLI (`ziira operator create`), stored in the master database with a scrypt password hash and an
  encrypted authenticator secret. The second factor is compulsory: sign-in is password (`POST /api/v1/operator/sign-in`), then a code
  (`/operator/mfa/verify`); both steps are throttled like business sign-ins, a code works once, and operator tokens (kind `op`, 30
  minutes, revocable) are refused by every business endpoint, as business tokens are by the operator endpoints.
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

## Dependencies and supply chain

CI runs dependency scanning (`pip-audit`, `npm audit`) and a secret scan (see `.github/workflows/`). Pin and review updates; run
`npm audit --omit=dev --audit-level=high` and `pip-audit` before each release.

## Operator checklist (before real customers)

- [ ] `ZIIRA_ENV=production` (the start-up checks refuse dev shortcuts: dev tenant header, default keys, open registration with no way to send mail, MFA policy off).
- [ ] `ZIIRA_SECRET_KEY` and `ZIIRA_CREDENTIALS_KEY` random (32+ characters), stored in a secrets manager, backed up apart from the database.
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

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

The operator reaches a business's data only through the database credentials (kept in the master database, encrypted) and the CLI.
A consent-based, time-limited, logged "support access" feature is **not built**: until it is, do not access tenant data without the
business's written consent, and record each access in the operator's ticket. (Spec 18, "Access by staff": open.)

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

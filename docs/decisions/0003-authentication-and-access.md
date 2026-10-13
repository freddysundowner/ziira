# 0003 · Authentication and access control

**Status:** accepted · October 2026

## Decision

- **Sign-in** uses a workspace code (one per tenant, e.g. `demo-hardware`), an email or phone, and a
  password. The same person can belong to two businesses with the same email.
- **Passwords** are hashed with scrypt (Python standard library).
- **Access tokens** are HMAC-signed and last 15 minutes. Each names a session row, which is checked
  on every request, so signing out, remote sign-out and disabling a user take effect at once.
- **Refresh tokens** are random, stored hashed, bound to the device that signed in, replaced on
  every use, and refused after 12 hours idle or 30 days.
- **API keys** are for server-to-server integrations. Their scopes are permission codes over the
  whole tenant.
- **Roles** are granted per user with a scope: tenant, company, branch, or own records. Endpoints
  declare a permission; services check the scope for the company or branch they act on.
- **Default roles** (Owner, Finance Manager, Branch Manager, Cashier, Storekeeper, Sales Rep, HR,
  Accountant) are created with each tenant. Each unit's manifest says which of its permissions
  they get when the unit is enabled; Owner gets all.
- **No escalation:** nobody can grant a role, or put a permission in a role or API key, that they
  do not hold themselves. The last tenant-wide owner cannot be removed.
- The **development** `X-Tenant-ID` header acts with every permission. It is refused when
  `ZIIRA_ENV=production`, and so is the development secret key.

## Why

- The specification (sections 13, 15 and 18) asks for short-lived access tokens, device-bound
  refresh tokens, remote sign-out, scoped roles and API keys.
- Standard library hashing and signing avoid new dependencies and are easy to review.
- Checking the session on every request costs one indexed query and makes sign-out immediate.

## Consequences

- MFA and one-time codes are not in place yet (deferred to phase 11, hardening; they need an SMS
  or email gateway). Owners, finance and admin roles must get MFA before real customer data.
- OAuth 2.0 for third-party apps is not in place yet (needed when outside apps act for users).
- Foreign keys are checked without row-level security, so services must confirm that company and
  branch ids belong to the tenant (`ziira.sdk.check_company`).
- Rate limiting and lockout after failed sign-ins are left to hardening; failed sign-ins are audited.

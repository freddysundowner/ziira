# Reviewing a third-party plugin

A plugin is Python code that runs **inside** the platform, in the same process as every business, with a database login
that can reach every tenant's database it is enabled for. Row-level security and the architecture rules limit what honest
code can do by accident; they do not stop deliberately hostile code. So a plugin someone else wrote is **reviewed by a
person before it runs in production**, and production refuses to load one that was not. This page is for that person
(the operator). Developers: docs/writing-a-plugin.md.

## How the platform enforces it

- Built-in modules and plugins (in this repository) are trusted as part of the release.
- Third-party plugins live in an **extra folder** (`ZIIRA_EXTRA_UNIT_PATHS`, `:`-separated) and are imported as
  `ziira_ext.<name>`. Install one with `ziira plugin install-archive FILE --expect-sha256 H` (operator only, command line
  only, never from a web request): it verifies the archive's hash and every file's checksum, refuses unsafe paths, and runs
  the static checks before unpacking.
- With `ZIIRA_ENV=production` a plugin from an extra folder **loads only if it is listed in `ZIIRA_ALLOWED_PLUGINS`** as
  `name=<checksum>` (the checksum of exactly the files you reviewed; `ziira plugin list` prints it) and its files still hash
  to that value. Any edit after review, even a comment, stops it loading (the reason is logged and shown by
  `ziira plugin list`). A name listed without a checksum loads only if its manifest carries a checksum that matches.
  In development and tests extra plugins load without listing (a manifest checksum that does not match is still refused).
- Installing is not enabling: a business (an owner with `units.manage`, in Add-ons) or the operator still enables it
  per business. Its permissions go to the Owner role and to the default roles its `[roles]` table names (read that table).

`ziira plugin list` shows each extra plugin, whether it loaded, why not, and its checksum.

## What to check (in this order)

1. **Who and what.** `manifest.toml`: `publisher`, `homepage`, `description`, `category`, `countries`, `version`, `sdk`. Does the
   description match what the code does? Is the publisher someone you can hold to account? Ask for a signed or
   hash-published release, and compare the archive hash they publish with the one you were given.
2. **Run the kit.** `ziira plugin check PATH` must pass with no errors. Read every warning. The kit checks: only
   `ziira.sdk` imports (plus its own package and other units' `public.py`); foreign keys only to the kernel, itself and units
   it `requires`; every table has `tenant_id`, forced row-level security and a policy (also verified on a scratch database);
   up and down migrations that round-trip; permissions used are declared; every endpoint has `require_permission`; events
   published are declared; no `float` money; no raw SQL against other units' schemas or writes to kernel tables; no network
   calls at import time. It is a **static** check: it finds mistakes and lazy shortcuts, **not** determined attackers
   (code can be obfuscated, built at run time, or reach things through the interpreter). It does not replace reading.
3. **Read the code.** It should be small. Look for the red flags below. Every `warning` the kit prints is a pointer.
4. **Run its tests** (`ziira plugin test PATH`) on a scratch platform: they should pass and should cover permissions and
   isolation (the scaffold's tests do: `assert_all_routes_guarded`, `assert_tenant_isolation`).
5. **Try it** on a scratch business (`ziira create-tenant ...`, enable the plugin) with fake data, with the network blocked
   if you can, and watch the database log and outgoing connections.
6. **Pin it.** Put `name=<checksum>` in `ZIIRA_ALLOWED_PLUGINS`, restart, `ziira install <name>`. Keep the reviewed archive
   and your notes. A new version is a new review (a diff against the last reviewed one is enough).

## Red flags

| Flag | Why it matters |
|---|---|
| `eval`, `exec`, `compile`, `__import__`, `importlib`, `pickle`, `marshal`, `ctypes` | Runs code you have not read. |
| `subprocess`, `os.system`, `os.popen`, file writes outside a temp folder | Leaves the sandbox of the application. |
| Reading `os.environ`, other settings, the filesystem, `/proc` | Secrets (`ZIIRA_SECRET_KEY`, `ZIIRA_CREDENTIALS_KEY`, database URLs) are in the environment of the process. A plugin has no reason to read them. |
| Any `socket`, `httpx`, `requests`, `urllib`, `smtplib` use | See network egress below. |
| Importing `ziira.kernel`, other units' internals, `sqlalchemy.create_engine`, `psycopg` | Bypasses the SDK, tenant scoping or row-level security. The kit refuses the imports, but check for indirect routes (`sys.modules`, `getattr` on modules). |
| Raw SQL with `set role`, `set_config('app.tenant_id'`, `reset`, `security definer`, `create function`, `create extension`, `copy ... program` | Defeats row-level security or runs commands on the database host. |
| `public_router` (endpoints without sign-in) | Must authenticate callers itself (a signed callback). Read how. |
| Permissions: `*.manage` that can do anything, or names of other units' permissions | See permission escalation. |
| Event handlers that raise on purpose, or that are slow | `@subscribe` runs inside other units' transactions: a plugin can block sales. |
| Large dependency lists, unpinned downloads at install or start-up | Supply-chain risk; a plugin ships no packages the platform does not already have. |
| Obfuscated or minified code, base64 blobs, very long lines | Reviewers cannot read it: refuse. |

### How permissions escalate

A plugin declares its own permissions (`<name>.<action>`); the Owner role receives all of them when the plugin is enabled
and the plugin's `[roles]` table gives default roles theirs. Nothing else is granted. Read `[roles]`: a plugin that hands
`name.manage` to Cashier changes what cashiers can do. The plugin's code can also *check* other units' permissions, but it
cannot grant them, and it cannot act as a user beyond the request it is serving (`current_context()`). It can, however,
use `system_session` and `enqueue`d jobs, which run with every permission for one business: read each use. An API key
or webhook a plugin creates through the SDK still goes through the same checks as any other.

### Data access

Row-level security is a second layer: the application login cannot read another tenant's rows even with a bug. Within a
business, a plugin enabled for it can read what the SDK and `public.py` of the units it requires expose, and its own tables.
It can also read **any kernel or other-schema table through raw SQL** unless the static check or your reading catches
it (the app login has grants on the schemas of units enabled in that tenant database). Ask: what personal data does it
store (it must implement `kernel.personal_data`: docs/privacy.md), for how long, and does it respect retention and erasure?

### Network egress

The platform makes no promise about what a plugin calls out to. List every host in the plugin's README and compare with
the code; check provider plugins' request formats against the provider's documentation; block everything else at the
firewall of the VPS if you can (an allow-list of hosts). A plugin that sends business data to its author's server is a
data leak even when it works as described: refuse it unless the business knowingly chose that service (and then the
privacy page must say so).

## Records

Keep for each approved plugin: name, version, archive sha256, plugin checksum, date, reviewer, notes, the allow-list entry.
Removing a plugin from `ZIIRA_ALLOWED_PLUGINS` and restarting stops it loading (data stays until a business removes the
unit).

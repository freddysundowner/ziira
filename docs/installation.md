# Installation on a VPS

One command installs the business app, the landing page and the Super Admin on a single server, with TLS, nginx,
PostgreSQL (role and databases only, when a server exists), systemd services, nightly backups and update/rollback tools.
No hosting provider is assumed. The three names are inputs: the examples use `ziira.io`, `app.ziira.io`, `admin.ziira.io`.

## Prerequisites
- A VPS running Ubuntu 22.04, Ubuntu 24.04 or Debian 12, with a public IPv4, root access, 2 CPU / 2 GB RAM / 10 GB disk or more.
- DNS **A records** for the root, `www`, the app host and the admin host pointing at the server. The installer checks them and
  stops (printing the exact records) before asking for any certificate. Ports 80 and 443 reachable from the internet.
- An email address for certificate notices; for registration, SMTP details for the platform mailer.

## Install
```bash
git clone <your repository> ziira && cd ziira
sudo bash deploy/install.sh                       # asks for the domain, emails, super admin password
sudo bash deploy/install.sh --dry-run --root-domain ziira.io ...      # prints the plan, changes nothing
sudo ZIIRA_OPERATOR_PASSWORD='...' bash deploy/install.sh --yes --root-domain ziira.io --email ops@ziira.io \
     --admin-email you@ziira.io --agree-tos --smtp-host smtp.example.com --smtp-from no-reply@ziira.io
```
`--config FILE` takes the same answers as `name=value` lines. Run `install.sh --help` for every option. It is idempotent:
run it again after fixing any problem and it skips what is done. Useful flags: `--staging` (Let's Encrypt test certificates),
`--self-signed`, `--cert-mode single|per-host`, `--hsts off|on|include-subdomains`, `--csp report-only|enforce|off`,
`--operator-networks CIDRS`, `--operator-mfa totp`, `--prebuilt` (use already built `frontend/dist` and `site/dist`),
`--repo URL --branch B` or `--tarball FILE`, `--postgres-new-cluster`, `--no-firewall`, `--skip-dns-check`.

What it does: preflight (OS, resources, ports, DNS) - packages - Python 3.12 (system, or `uv` into a private venv) - Node (only to
build) - service user - PostgreSQL - release + virtualenv - `/etc/ziira/ziira.env` (validated with `scripts/check_env.py`) -
`ziira install --all` and the first super admin - web app build - systemd services - nginx on port 80 - certificates - nginx over
HTTPS (HSTS only after HTTPS is verified) - website build - firewall, fail2ban, log rotation.

## Where things live
| What | Where |
|---|---|
| Code, virtualenv | `/opt/ziira/releases/<id>/`, `/opt/ziira/current` (symlink) |
| Configuration (secrets) | `/etc/ziira/ziira.env` (0640 root:ziira), `site-rebuild.env`, `install.json` (no secrets), `install-summary.txt` (0600, holds the credentials key) |
| Web roots | `/var/www/ziira/app/current`, `/var/www/ziira/site/current` (release folders + symlink, last 3 kept) |
| State, build workspace | `/var/lib/ziira` |
| Backups | `/var/backups/ziira` (nightly 02:17, weekly restore test, retention 35 days / 12 months) |
| nginx | `/etc/nginx/sites-available/ziira-*.conf`, `conf.d/ziira-common.conf`, `snippets/ziira-*.conf`, logs `/var/log/nginx/ziira/` |
| Services / timers | `ziira-api`, `ziira-worker`, `ziira-site-rebuild`, `ziira-backup|restore-test|stock-verify|verify .timer`, `ziira-nginx-reload.path` |
| Helper commands | `ziira-cli <ziira command>`, `ziira-doctor`, `ziira-update`, `ziira-backup-now` |

## The three hosts
- `https://ziira.io`: static website (www redirects here). Content comes from Super Admin > Website; Publish calls a signed hook
  (`https://admin.../_hooks/site-rebuild/<secret path>`, HMAC checked by a localhost receiver that rebuilds into a new release and
  swaps atomically). Until you publish, the site shows placeholder text.
- `https://app.ziira.io`: the business web app and `/api/`. Staff screens and `/api/v1/operator` answer 404 here; `/healthz`,
  `/readyz`, `/metrics`, `/docs` are not reachable from outside.
- `https://admin.ziira.io`: Super Admin only (`/` goes to `/operator`; only staff, public-plans and editions APIs; `noindex`; stricter
  rate limit on sign-in). The API repeats the host rule (`ZIIRA_OPERATOR_HOST`, `ZIIRA_APP_HOST`). Unknown Host names get no answer.

First sign-in: the Super Admin with the email and password you gave; then create plans and publish the website.

## PostgreSQL handling
| Situation | What the installer does |
|---|---|
| none | installs PostgreSQL 16 from the official apt repository (key fingerprint verified), localhost only, tuned from RAM |
| 16 or newer, running | leaves it alone; creates only role `ziira` (login, createdb, createrole; not superuser) and `ziira_master` |
| stopped 16+ cluster | starts it, then as above |
| older than 16 | stops and explains; with `--postgres-new-cluster` adds a separate 16 cluster on another port |
| present but cannot be logged into as `postgres` (peer) | stops and explains |
| role/database already exist | kept; login verified; never altered or dropped; an existing role with an unknown password stops the install |

The superuser connection is the local `postgres` OS user (no superuser password anywhere). PostgreSQL is never opened to the network.

## Update, rollback, doctor, uninstall
```bash
sudo ziira-update --from-dir /path/to/new/checkout     # or --repo URL --branch main, --tarball FILE
sudo ziira-update --rollback
sudo ziira-doctor                                      # exit 0 ok, 1 warnings, 2 failures (--json available)
sudo bash deploy/backup-now.sh
sudo bash deploy/uninstall.sh [--purge-data]           # typed confirmation; databases are kept unless --purge-data (asked twice)
```
Update builds a new release beside the live one, checks the configuration with the new code, dumps the master database, runs
migrations with the new code while the old keeps serving, switches, waits for `/readyz`, then publishes the web app and rebuilds the
site. If the new release is not ready, the symlink and services go back. Migrations are never reversed automatically.

## What to back up
`/etc/ziira/ziira.env` and above all **`ZIIRA_CREDENTIALS_KEY`** (losing it locks out every business; keep it offline, not with the
backups), and copy `/var/backups/ziira` off the server (encrypted). See `docs/operations.md`.

## Hardening choices
Super Admin sign-in defaults to email + password (`ZIIRA_OPERATOR_MFA=off`, acknowledged by the installer after a warning). Reduce the
risk with `--operator-networks` (enforced in nginx and in the API) or `--operator-mfa totp`. Registration is `closed` without SMTP,
`invite` with it (`--registration-mode`). The web app CSP starts as report-only: check the browser console, then `--csp enforce`.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| Stops at DNS | create the A records it prints; wait; re-run |
| Certificate not issued | port 80 blocked (provider firewall), DNS wrong, rate limit (use `--staging`); see `/var/log/letsencrypt/letsencrypt.log`; re-run resumes |
| `nginx -t` fails | the previous configuration is restored automatically; the message shows the line |
| API not ready | `journalctl -u ziira-api`; `ziira-doctor`; `check_env.py` errors |
| Publish does nothing | doctor "website rebuild hook": the server must reach its own public name; else map the admin host to 127.0.0.1 in `/etc/hosts` |
| Role exists, password unknown | put its password in the database URLs of the env file, or use `--db-role` |
| Postgres older than 16 | upgrade it, or `--postgres-new-cluster` |

## Testing and what is NOT proven
`make deploy-test` (fake-server unit tests, golden nginx/systemd files), `make deploy-test-docker` (real nginx `-t` and requests in
an Ubuntu 24.04 container). The full flow also ran on Ubuntu 24.04 in a systemd container with a self-signed certificate. **Not
tested on a real server:** Let's Encrypt issuance and renewal, DNS/IP detection, Ubuntu 22.04 and Debian 12 (the `uv` Python path, PGDG on
those), ufw/fail2ban, the website build with Node on the server, hairpin access to the server's own public name, nginx older than 1.24,
and the app's web CSP in a browser.

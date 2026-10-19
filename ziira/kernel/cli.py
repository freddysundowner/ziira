"""Command-line tool for administering Ziira Core.

Every business (tenant) has its own database; the master database lists them.
<tenant> is a workspace code or a tenant id.

    ziira units                         list units and whether the platform offers them
    ziira install <unit> | --all        offer units (and what they require); upgrades existing ones
    ziira uninstall <unit>              stop offering a unit (refused while any tenant has it)
    ziira create-tenant NAME --code CODE --company NAME --branch-code CODE --branch-name NAME
                        --owner-name NAME --owner-email EMAIL   (password asked, or ZIIRA_OWNER_PASSWORD)
    ziira tenants                       list tenants and their databases
    ziira enable <tenant> <unit>        enable a unit (creates its tables in the tenant's database)
    ziira disable <tenant> <unit>       disable a unit for a tenant (data kept)
    ziira remove <tenant> <unit>        drop a disabled unit's tables from the tenant's database
    ziira drop-tenant <code> --confirm <code>   delete a tenant's database and login (cannot be undone)
    ziira mfa-policy off|privileged|everyone (--tenant CODE | --all)   who must use a second factor
    ziira outbox-run [--once]           deliver committed events to after-commit subscribers
    ziira worker [--once]               deliver events and run background jobs (replaces outbox-run)
    ziira run-task <tenant> <name>      run one recurring task now (intel.run_checks, command.send_briefs, ...)
    ziira backup [--tenant CODE] --dir PATH [--keep-daily 35 --keep-monthly 12]   pg_dump of master + tenants, pruned
    ziira restore-test [--tenant CODE] --dir PATH   restore the newest dump to a scratch database, check it, drop it
    ziira restore --tenant CODE --dir PATH --into NEWDB   restore a dump into a NEW database (never over a live one)
    ziira operator create NAME EMAIL [--role ROLE] | list | disable|enable|reset-mfa|reset-password EMAIL
                                        | role EMAIL ROLE
                                        platform staff (Super Admin); ROLE: superadmin billing support content readonly
    ziira licence keygen | issue ... | install FILE | status | verify FILE | revocations | instance-id
                                        licences for self-hosted copies (docs/licensing.md)
    ziira billing-run                   renewal invoices, reminders and dunning now (the worker does this hourly)
    ziira verify [tenant] [--unit U] [--fix]   check units' derived data (exit 1 if a problem remains)
    ziira stock-verify [tenant] [--fix]        the same, for Inventory only (run it nightly)
    ziira import <tenant> <kind> FILE.csv [--company NAME] [--commit]   check (and with --commit import) a file
    ziira connect sync <tenant> [--connection NAME]      read the connected systems now (standalone mode)
    ziira connect upload <tenant> <connection> FILE [--check]   upload a CSV, Excel or text-PDF file or statement
    ziira connect ocr-check                              can this server read pictures (scanned statements, photos)?
    ziira plugin new NAME --category C [--countries KE,UG] [--dir PATH]   scaffold a plugin (docs/writing-a-plugin.md)
    ziira plugin check|test|pack PATH | install-archive FILE --expect-sha256 H | list   check, test, package, install
"""

import argparse
import getpass
import os
import sys
from uuid import UUID

from ziira.kernel import outbox
from ziira.kernel.errors import ZiiraError
from ziira.kernel.observability import configure_logging
from ziira.kernel.registry import Registry, load_event_handlers
from ziira.kernel.tenants import create_tenant, drop_tenant, find_tenant, list_tenants


def _tenant(value: str) -> UUID:
    return find_tenant(value).id


def cmd_units(reg: Registry, _: argparse.Namespace) -> None:
    installed = reg.installed()
    for m in reg.units.values():
        state = "installed" if m.name in installed else "available"
        req = ", ".join(m.requires) or "-"
        print(f"{m.name:<12} {m.kind:<7} {m.version:<8} {state:<10} requires: {req}")


def cmd_install(reg: Registry, a: argparse.Namespace) -> None:
    done = reg.install_all() if a.all else reg.install(a.unit)
    print("Installed: " + (", ".join(done) if done else "nothing new"))
    load_event_handlers(reg.units, strict=True)          # a unit whose code cannot be imported must not pass quietly


def cmd_uninstall(reg: Registry, a: argparse.Namespace) -> None:
    reg.uninstall(a.unit)
    print(f"Uninstalled: {a.unit}")


def cmd_create_tenant(reg: Registry, a: argparse.Namespace) -> None:
    password = os.environ.get("ZIIRA_OWNER_PASSWORD") or getpass.getpass("Owner password: ")
    from ziira.kernel import editions

    edition = editions.resolve(a.edition, a.mode if a.mode == "standalone" else None)
    t = create_tenant(name=a.name, code=a.code, company=a.company, branch_code=a.branch_code,
                      branch_name=a.branch_name, owner_name=a.owner_name, owner_email=a.owner_email,
                      owner_password=password, tax_id=a.tax_id, currency=a.currency,
                      phone_country_code=a.phone_country_code, country=a.country,
                      vat_registered=a.vat_registered, timezone=a.timezone, edition=edition,
                      registry=reg)
    if a.edition or a.mode == "standalone":
        editions.enable_edition(reg, t.tenant_id, edition)
        from ziira.kernel import packs

        packs.enable_country_pack(reg, t.tenant_id, a.country)
    if a.plan:
        from ziira.kernel.platform import subscriptions

        subscriptions.start(t.tenant_id, a.plan, currency=a.currency, mode=a.plan_mode, by="cli")
        print(f"subscription = {a.plan} ({a.plan_mode})")
    print(f"tenant_id  = {t.tenant_id}\ncompany_id = {t.company_id}\nbranch_id  = {t.branch_id}\n"
          f"owner_id   = {t.owner_id}")


def cmd_tenants(_: Registry, __: argparse.Namespace) -> None:
    for t in list_tenants():
        print(f"{t.code:<24} {t.status:<12} {t.db_name:<32} {t.id}")


def cmd_remove(reg: Registry, a: argparse.Namespace) -> None:
    reg.remove_from_tenant(_tenant(a.tenant), a.unit)
    print(f"Removed {a.unit} from {a.tenant} (its tables and data are gone)")


def cmd_mfa_policy(_: Registry, a: argparse.Namespace) -> None:
    """Who must use a second factor, for one business or all of them (each business can also change it in Settings)."""
    from sqlalchemy import text

    from ziira.kernel.db import tenant_session

    if not a.all and not a.tenant:
        raise ZiiraError("Name a business with --tenant CODE, or use --all")
    targets = list_tenants() if a.all else [_tenant(a.tenant)]
    for t in targets:
        tid = t.id if hasattr(t, "id") else t
        with tenant_session(tid) as s:
            s.execute(text("update kernel.tenant set mfa_policy = :p where id = kernel.current_tenant()"),
                      {"p": a.policy})
    print(f"Second-factor policy is now '{a.policy}' for {len(targets)} business(es)")


def cmd_drop_tenant(_: Registry, a: argparse.Namespace) -> None:
    if a.confirm != a.code:
        raise ZiiraError("Repeat the workspace code with --confirm to delete the tenant")
    drop_tenant(_tenant(a.code))
    print(f"Dropped tenant {a.code}: database, login and master record deleted")


def cmd_outbox_run(reg: Registry, a: argparse.Namespace) -> None:
    configure_logging()
    load_event_handlers(reg.units)
    if a.once:
        print(f"Delivered {outbox.process_all()} event(s)")
    else:
        outbox.run_forever()


def cmd_verify(reg: Registry, a: argparse.Namespace) -> int:
    from ziira.kernel import files as _files  # noqa: F401 - its integrity check registers itself
    from ziira.kernel.checks import run_integrity_checks

    load_event_handlers(reg.units, strict=True)
    unit = "inventory" if a.cmd == "stock-verify" else a.unit
    tenants = [_tenant(a.tenant)] if a.tenant else reg.tenant_ids()
    problems = 0
    for tenant_id in tenants:
        for result in run_integrity_checks(tenant_id, fix=a.fix, unit=unit):
            status = "ok" if not result.problems else f"{len(result.problems)} problem(s)"
            print(f"{tenant_id}  {result.unit}: {result.check}: {status}")
            for line in result.problems:
                print(f"    {line}")
            problems += len(result.problems)
    if problems and a.fix:
        print("Rebuilt from the movements; run again to confirm.")
        return 0
    return 1 if problems else 0


def cmd_index_logins(reg: Registry, a: argparse.Namespace) -> None:
    from ziira.kernel import directory

    done = directory.rebuild([_tenant(a.tenant)] if a.tenant else None)
    print(f"Registered {done} login(s) in the login directory")


def cmd_apply_packs(reg: Registry, a: argparse.Namespace) -> None:
    """Seed the data of the country packs switched on (adds only what is missing; safe to run again)."""
    from ziira.kernel import industry, packs
    from ziira.kernel.registry import load_event_handlers

    load_event_handlers(reg.units)
    for tenant in [_tenant(a.tenant)] if a.tenant else reg.tenant_ids():
        done = packs.apply_to_tenant(tenant)
        done_industry = industry.apply_to_tenant(reg, tenant)
        added = [f"{k}: {v}" for c in [*done.values(), *done_industry.values()] for k, v in c.items()]
        print(f"{tenant}: " + (", ".join(added) or "nothing to add"))


def cmd_operator(_: Registry, a: argparse.Namespace) -> None:
    from ziira.kernel import operators

    if a.action == "create":
        password = os.environ.get("ZIIRA_OPERATOR_PASSWORD") or getpass.getpass("Operator password: ")
        _id, secret, uri = operators.create_operator(a.name, a.email, password, a.role)
        if secret:
            print("Operator created. Add this to an authenticator app now: it is shown once, every sign-in needs it.")
            print(f"secret: {secret}\naddress: {uri}")
        else:
            print("Operator created. They sign in with their email and password (ZIIRA_OPERATOR_MFA=off).")
    elif a.action == "list":
        for o in operators.list_operators():
            print(f"{o['email']:<36} {o['status']:<9} {o['role']:<10} {o['name']}   "
                  f"last sign-in: {o['last_sign_in_at'] or 'never'}")
    elif a.action == "role":
        operators.set_role(a.name, a.email)
        print(f"Operator {a.name} is now {a.email}")
    elif a.action in ("disable", "enable"):
        operators.set_status(a.name, "disabled" if a.action == "disable" else "active")
        print(f"Operator {a.name} {a.action}d")
    elif a.action == "reset-mfa":
        secret, uri = operators.reset_mfa(a.name)
        print(f"New secret (shown once): {secret}\naddress: {uri}")
    elif a.action == "reset-password":
        chosen = os.environ.get("ZIIRA_OPERATOR_PASSWORD")
        new = operators.reset_password(a.name, password=chosen)
        if chosen:
            print(f"The password of {a.name} is set to the one in ZIIRA_OPERATOR_PASSWORD; their sign-ins ended.")
        else:
            print(f"Temporary password (shown once; {a.name} must change it at the next sign-in): {new}")


def cmd_licence(_: Registry, a: argparse.Namespace) -> int:
    """Licences: the vendor makes keys and licences; a self-hosted copy installs and checks them (docs/licensing.md)."""
    from datetime import UTC, datetime
    from pathlib import Path

    from ziira.kernel.platform import licences

    def when(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None

    if a.action == "keygen":
        private, public = licences.generate_keypair()
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        key_file = out / "licence-signing.key"
        key_file.write_text(private + "\n")
        key_file.chmod(0o600)
        print(f"Private signing key written to {key_file}  (keep it ONLY on the vendor side; back it up offline)")
        print(f"Public key (set ZIIRA_LICENCE_PUBLIC_KEY on customers' copies):\n{public}")
    elif a.action == "issue":
        key = Path(a.key).read_text().strip() if a.key else None
        row = licences.issue(customer=a.customer, contact_email=a.email, plan_code=a.plan,
                             units=[u for u in (a.units or "").split(",") if u], edition=a.edition,
                             max_users=a.max_users, max_branches=a.max_branches, max_companies=a.max_companies,
                             valid_until=when(a.valid_until), update_until=when(a.update_until),
                             grace_days=a.grace_days,
                             instance_id=a.instance, notes=a.notes or "", issued_by="cli", private_key=key)
        out_file = Path(a.out or f"{row['licence_no']}.ziira-licence")
        out_file.write_text(row["token"])
        print(f"Licence {row['licence_no']} for {row['customer']} written to {out_file}")
    elif a.action == "install":
        info = licences.install(Path(a.file).read_text(), by="cli")
        print(f"Installed {info['licence_no']} for {info['customer']}: {info['status']}. {info['message']}")
    elif a.action == "verify":
        from ziira.kernel.config import get_settings

        payload = licences.verify(Path(a.file).read_text(), get_settings().licence_public_key)
        print(f"Valid signature: {payload.get('kind')} {payload.get('licence_no', '')} {payload.get('customer', '')}")
    elif a.action == "status":
        info = licences.describe()
        for key in ("instance_id", "installed", "status", "access", "customer", "licence_no", "valid_until",
                    "update_until", "days_left", "message"):
            if info.get(key) is not None:
                print(f"{key}: {info[key]}")
        return 0 if info["access"] != "read_only" else 1
    elif a.action == "revocations":
        if a.file:
            print(f"{licences.install_revocations(Path(a.file).read_text())} revoked licence(s) installed")
        else:
            out_file = Path(a.out or "revocations.ziira-licence")
            key = Path(a.key).read_text().strip() if a.key else None
            out_file.write_text(licences.revocation_list(private_key=key))
            print(f"Signed revocation list written to {out_file}")
    elif a.action == "instance-id":
        print(licences.instance_id())
    return 0


def cmd_billing_run(_: Registry, a: argparse.Namespace) -> None:
    from ziira.kernel.platform import billing

    print(billing.run_due())


def cmd_invite(reg: Registry, a: argparse.Namespace) -> None:
    from ziira.kernel import registration

    code = registration.create_invite(uses=a.uses, days=a.days or None, note=a.note)
    print(f"Invitation code (shown once): {code}   uses: {a.uses}")


def cmd_run_task(reg: Registry, a: argparse.Namespace) -> None:
    """Run one recurring task now, for one business (for example `intel.run_checks`, or `command.send_briefs`)."""
    from ziira.kernel import jobs

    load_event_handlers(reg.units)
    if a.name not in jobs.periodic_names():
        raise ZiiraError(f"Unknown recurring task '{a.name}'. Known: {', '.join(jobs.periodic_names())}")
    tenant = _tenant(a.tenant)
    ran = jobs.run_periodic(tenant, only=a.name, force=True) + jobs.run_unbound(tenant, only=a.name, force=True)
    print(f"Ran {a.name}" if ran else f"{a.name} did not run (is its unit enabled for {a.tenant}?)")


def cmd_import(reg: Registry, a: argparse.Namespace) -> int:
    """Move data in from a CSV file: a dry run by default, `--commit` imports the valid rows (docs/data-import.md)."""
    from pathlib import Path

    from ziira.modules.imports.cli import run_import

    load_event_handlers(reg.units)
    mapping = dict(item.split("=", 1) for item in a.map or [] if "=" in item)
    return run_import(_tenant(a.tenant), kind=a.kind, path=Path(a.file), company=a.company, commit=a.commit,
                      decimal_separator=a.decimal, date_format=a.date_format, mapping=mapping,
                      rejected=Path(a.rejected) if a.rejected else None, as_of=a.as_of, tolerance=a.tolerance,
                      confirm=a.confirm)


def cmd_connect(reg: Registry, a: argparse.Namespace) -> int:
    """Standalone mode from the command line: read connected systems now, or upload a file or statement."""
    from pathlib import Path

    from ziira.modules.connect.cli import run_sync, run_upload

    if a.action == "ocr-check":
        from ziira.modules.connect.cli import run_ocr_check
        return run_ocr_check()
    load_event_handlers(reg.units)
    tenant = _tenant(a.tenant)
    if a.action == "sync":
        return run_sync(tenant, a.connection)
    return run_upload(tenant, a.connection, Path(a.file), check_only=a.check)


def cmd_plugin(reg: Registry, a: argparse.Namespace) -> int:
    """The plugin kit: scaffold, check, test, pack and install plugins (docs/writing-a-plugin.md)."""
    from ziira.kernel import plugin_kit_cli

    return plugin_kit_cli.run(a.action, a)


def cmd_worker(reg: Registry, a: argparse.Namespace) -> None:
    from ziira.kernel import jobs, notifications  # noqa: F401 - notifications registers its send job

    configure_logging()
    load_event_handlers(reg.units)
    if a.once:
        from ziira.kernel import registration, site_hook

        registration.repair_pending()
        print(f"Delivered {outbox.process_all()} event(s), ran {jobs.run_all()} job(s), "
              f"made {site_hook.run_pending()} website rebuild call(s)")
        return
    import time

    from ziira.kernel import site_hook

    purged_at = 0.0
    recovered_at = 0.0
    while True:
        busy = outbox.process_all() + jobs.run_all() + site_hook.run_pending()
        if time.monotonic() - recovered_at > 60:
            recovered_at = time.monotonic()
            _recover_payments()
            _repair_registrations()
        if time.monotonic() - purged_at > 3600:
            purged_at = time.monotonic()
            _purge_idempotency_keys(reg)
            from ziira.kernel import registration

            registration.purge()
            from ziira.kernel.platform import mail

            mail.purge_log()
            from ziira.kernel import throttle

            throttle.purge()
            _run_billing()
        if busy == 0:
            time.sleep(2.0)


def _repair_registrations() -> None:
    """Retry the optional setup steps (country pack, trial plan) that failed when a business registered. Never fatal."""
    import logging

    try:
        from ziira.kernel import registration

        registration.repair_pending()
    except Exception:  # noqa: BLE001
        logging.getLogger("ziira.registration").exception("The registration repair pass failed")


def _recover_payments() -> None:
    """Ask the payment providers about payments still open, so a lost notification still ends in a credit (every
    minute: young attempts are asked each time, older ones hourly). A failure is logged, never fatal to the worker."""
    import logging

    from ziira.kernel.config import get_settings

    if get_settings().deployment_mode != "saas":
        return
    try:
        from ziira.kernel.platform import payments

        payments.recover_pending()
    except Exception:  # noqa: BLE001
        logging.getLogger("ziira.payments").exception("The payment recovery pass failed")


def _run_billing() -> None:
    """The platform's recurring billing pass (SaaS deployments only); a failure is logged, never fatal to the worker."""
    import logging

    from ziira.kernel.config import get_settings

    if get_settings().deployment_mode != "saas":
        return
    try:
        from ziira.kernel.platform import billing

        billing.run_due()
    except Exception:  # noqa: BLE001
        logging.getLogger("ziira.billing").exception("The billing pass failed")


def _purge_idempotency_keys(reg: Registry) -> None:
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session
    from ziira.kernel.idempotency import purge_old_keys
    from ziira.kernel.jobs import purge_finished

    for tenant_id in reg.tenant_ids():
        system_context(tenant_id)
        with tenant_session(tenant_id) as s:
            purge_old_keys(s)
            purge_finished(s)


def cmd_backup(_: Registry, a: argparse.Namespace) -> int:
    from pathlib import Path

    from ziira.kernel import backup

    configure_logging()
    problem = backup.tools_available()
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    failed = 0
    for r in backup.run_backup(Path(a.dir), tenant=a.tenant, include_master=not a.tenant and not a.no_master,
                               keep_daily=a.keep_daily, keep_monthly=a.keep_monthly):
        if r.ok:
            print(f"ok      {r.target:<24} {r.size:>12,} bytes  {r.file.name if r.file else ''}"
                  + (f"  (pruned {len(r.pruned)})" if r.pruned else ""))
        else:
            failed += 1
            print(f"FAILED  {r.target:<24} {r.error}", file=sys.stderr)
    return 1 if failed else 0


def cmd_restore_test(_: Registry, a: argparse.Namespace) -> int:
    from pathlib import Path

    from ziira.kernel import backup

    configure_logging()
    problem = backup.tools_available()
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    targets = [a.tenant] if a.tenant else ["master", *[t.code for t in list_tenants() if t.status != "closed"]]
    failed = 0
    for target in targets:
        r = backup.restore_test(Path(a.dir), target)
        print(f"{'ok     ' if r.ok else 'FAILED '} {target:<24} {r.backup}")
        for line in r.problems:
            print(f"    {line}")
        failed += 0 if r.ok else 1
    return 1 if failed else 0


def cmd_restore(_: Registry, a: argparse.Namespace) -> int:
    from pathlib import Path

    from ziira.kernel import backup

    configure_logging()
    found = backup.list_backups(Path(a.dir), a.tenant)
    if a.file:
        found = [b for b in found if b.dump_path.name == a.file]
    if not found:
        raise ZiiraError(f"No matching backup of '{a.tenant}' in {a.dir}")
    chosen = found[-1]
    url = backup.restore_into_new_database(chosen, a.into, keep_ownership=a.keep_ownership)
    if a.files_into:
        done = backup.restore_files(chosen, Path(a.files_into))
        print(f"Unpacked {done} photo(s) and file(s) into the new folder {a.files_into}.")
    elif chosen.files_path is not None:
        print("This backup also holds the business's photos and files: add --files-into NEWFOLDER to unpack them.")
    print(f"Restored {chosen.dump_path.name} into the new database '{url.database}'. Nothing live was changed.\n"
          "To use it, follow 'Restoring a business' in docs/operations.md (point the tenant at it in the master "
          "database, or copy the data you need).")
    return 0


def cmd_enable(reg: Registry, a: argparse.Namespace) -> None:
    done = reg.enable(_tenant(a.tenant), a.unit)
    print("Enabled: " + (", ".join(done) if done else "already enabled"))


def cmd_disable(reg: Registry, a: argparse.Namespace) -> None:
    reg.disable(_tenant(a.tenant), a.unit)
    print(f"Disabled: {a.unit} (data kept)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ziira", description="Ziira Core administration")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("units").set_defaults(fn=cmd_units)
    s = sub.add_parser("install")
    s.add_argument("unit", nargs="?")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_install)
    s = sub.add_parser("uninstall")
    s.add_argument("unit")
    s.set_defaults(fn=cmd_uninstall)
    s = sub.add_parser("create-tenant")
    s.add_argument("name")
    s.add_argument("--code", required=True, help="workspace code used to sign in, e.g. demo-hardware")
    s.add_argument("--company", required=True)
    s.add_argument("--branch-code", required=True)
    s.add_argument("--branch-name", required=True)
    s.add_argument("--owner-name", required=True)
    s.add_argument("--owner-email", required=True)
    s.add_argument("--tax-id")
    s.add_argument("--currency", required=True, help="Base currency code, such as USD")
    s.add_argument("--country", help="Two-letter country code, such as GB")
    s.add_argument("--phone-country-code", default="", help="Calling code of the business's phone numbers, such as 44")
    s.add_argument("--timezone", help="IANA time zone of the business, such as Europe/London (default UTC)")
    s.add_argument("--vat-registered", action="store_true")
    s.add_argument("--mode", choices=["core", "standalone"], default="core",
                   help="older spelling: standalone = --edition intelligence")
    s.add_argument("--edition", help="switch on an edition's units (retail, distribution, books, intelligence, full); "
                                     "without it no units are switched on")
    s.add_argument("--plan", help="give the business a subscription on this plan (Super Admin > Plans)")
    s.add_argument("--plan-mode", choices=["trial", "active", "comp"], default="trial")
    s.set_defaults(fn=cmd_create_tenant)
    sub.add_parser("tenants").set_defaults(fn=cmd_tenants)
    s = sub.add_parser("mfa-policy")
    s.add_argument("policy", choices=["off", "privileged", "everyone"])
    s.add_argument("--tenant", default=None, help="workspace code or id")
    s.add_argument("--all", action="store_true", help="every business")
    s.set_defaults(fn=cmd_mfa_policy)
    s = sub.add_parser("drop-tenant")
    s.add_argument("code")
    s.add_argument("--confirm", required=True)
    s.set_defaults(fn=cmd_drop_tenant)
    s = sub.add_parser("outbox-run")
    s.add_argument("--once", action="store_true", help="one pass, then stop")
    s.set_defaults(fn=cmd_outbox_run)
    s = sub.add_parser("run-task", help="run one recurring task now for a business (e.g. intel.run_checks)")
    s.add_argument("tenant", help="workspace code or id")
    s.add_argument("name", help="the task, e.g. intel.run_checks, intel.refresh_baselines, command.send_briefs")
    s.set_defaults(fn=cmd_run_task)
    s = sub.add_parser("import", help="check a CSV file and (with --commit) import it: products, customers, ...")
    s.add_argument("tenant", help="workspace code or id")
    s.add_argument("kind", help="what the file holds, e.g. products, customers, suppliers, opening_stock")
    s.add_argument("file", help="the CSV file")
    s.add_argument("--company", help="the company's name or id (not needed when the business has one)")
    s.add_argument("--commit", action="store_true", help="import the valid rows (default: check only)")
    s.add_argument("--decimal", default=".", choices=[".", ","], help="decimal separator the file uses")
    s.add_argument("--date-format", default="iso", choices=["iso", "dmy", "mdy"])
    s.add_argument("--map", action="append", metavar="FIELD=HEADER", help="choose a column (repeatable)")
    s.add_argument("--rejected", help="write the rejected rows (with an error column) to this CSV file")
    s.add_argument("--as-of", metavar="YYYY-MM-DD", help="the go-live date (customer_balances, supplier_balances, "
                                                         "opening_trial_balance)")
    s.add_argument("--tolerance", default="0", help="opening_trial_balance: how far the file may be out of balance "
                                                    "before it must be confirmed")
    s.add_argument("--confirm", action="store_true", help="opening_trial_balance: post a difference to opening "
                                                          "balance equity")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("connect", help="standalone mode: sync connected systems, or upload a file or statement")
    c = s.add_subparsers(dest="action", required=True)
    cs = c.add_parser("sync", help="read the connected systems now")
    cs.add_argument("tenant", help="workspace code or id")
    cs.add_argument("--connection", help="only this connection (its name)")
    cu = c.add_parser("upload", help="upload a CSV file or statement to a file connection")
    cu.add_argument("tenant", help="workspace code or id")
    cu.add_argument("connection", help="the connection's name")
    cu.add_argument("file", help="the CSV file")
    cu.add_argument("--check", action="store_true", help="show what would be read, store nothing")
    c.add_parser("ocr-check", help="can this server read pictures of statements (Tesseract installed)?")
    s.set_defaults(fn=cmd_connect)
    s = sub.add_parser("plugin", help="plugin kit: new, check, test, pack, install-archive, list")
    k = s.add_subparsers(dest="action", required=True)
    pn = k.add_parser("new", help="scaffold a complete plugin")
    pn.add_argument("name")
    pn.add_argument("--category", required=True)
    pn.add_argument("--countries", default="", help="comma separated ISO codes, e.g. KE,UG (default: worldwide)")
    pn.add_argument("--dir", help="create it in this folder instead of ziira/plugins (an extra plugin folder)")
    for action, text_ in (("check", "static checks and a migration round trip"), ("test", "run the plugin's tests"),
                          ("pack", "build a distributable archive with a checksum")):
        pc = k.add_parser(action, help=text_)
        pc.add_argument("path")
        if action == "check":
            pc.add_argument("--no-db", action="store_true", help="skip the migration round trip (no database needed)")
        if action == "pack":
            pc.add_argument("--out", default="dist", help="folder for the archive")
    pi = k.add_parser("install-archive", help="verify and unpack an archive (operator only)")
    pi.add_argument("file")
    pi.add_argument("--expect-sha256", required=True, help="the archive's sha256 as the publisher gave it")
    pi.add_argument("--replace", action="store_true", help="replace an installed version")
    k.add_parser("list", help="plugins in the extra folders, and any that were refused")
    s.set_defaults(fn=cmd_plugin)
    s = sub.add_parser("worker")
    s.add_argument("--once", action="store_true", help="one pass, then stop")
    s.set_defaults(fn=cmd_worker)
    s = sub.add_parser("invite", help="make an invitation code for registration mode 'invite'")
    s.add_argument("--uses", type=int, default=1)
    s.add_argument("--days", type=int, default=30, help="valid for this many days (0: no expiry)")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_invite)
    s = sub.add_parser("operator", help="platform staff who may open support sessions (create, list, disable)")
    s.add_argument("action", choices=["create", "list", "disable", "enable", "reset-mfa", "reset-password", "role"])
    s.add_argument("name", nargs="?", help="create: the name; disable/enable/reset-mfa/reset-password/role: the email")
    s.add_argument("email", nargs="?", help="create: the email; role: the new role")
    s.add_argument("--role", default="superadmin", help="create: superadmin, billing, support, content or readonly")
    s.set_defaults(fn=cmd_operator)
    s = sub.add_parser("licence", help="licences for outright purchase / self-hosted copies (docs/licensing.md)")
    s.add_argument("action", choices=["keygen", "issue", "install", "status", "verify", "revocations", "instance-id"])
    s.add_argument("file", nargs="?", help="install/verify: the licence file; revocations: a list to install")
    s.add_argument("--out", help="keygen: folder for the key; issue/revocations: the file to write")
    s.add_argument("--key", help="issue/revocations: file holding the signing key "
                                 "(default: ZIIRA_LICENCE_SIGNING_KEY_FILE)")
    s.add_argument("--customer"), s.add_argument("--email"), s.add_argument("--plan"), s.add_argument("--edition")
    s.add_argument("--units", help="comma-separated unit names")
    s.add_argument("--max-users", type=int), s.add_argument("--max-branches", type=int)
    s.add_argument("--max-companies", type=int)
    s.add_argument("--valid-until", help="YYYY-MM-DD; omit for a perpetual licence")
    s.add_argument("--update-until", help="YYYY-MM-DD: updates released after this need a renewal")
    s.add_argument("--grace-days", type=int, default=30)
    s.add_argument("--instance", help="bind to one installation (its `ziira licence instance-id`)")
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_licence)
    s = sub.add_parser("billing-run", help="renewal invoices, reminders and dunning now (the worker does this hourly)")
    s.set_defaults(fn=cmd_billing_run)
    s = sub.add_parser("apply-packs", help="copy the data of the country and industry packs switched on into the "
                                           "business's tables (adds what is missing; changes nothing else)")
    s.add_argument("tenant", nargs="?", help="workspace code or id (all tenants if omitted)")
    s.set_defaults(fn=cmd_apply_packs)
    s = sub.add_parser("index-logins", help="rebuild the login directory used to sign in without a workspace code")
    s.add_argument("tenant", nargs="?", help="workspace code or id (all tenants if omitted)")
    s.set_defaults(fn=cmd_index_logins)
    s = sub.add_parser("backup", help="dump the master database and the tenants' databases (pg_dump, custom format)")
    s.add_argument("--tenant", help="back up only this workspace code (default: master and every tenant)")
    s.add_argument("--all", action="store_true", help="every tenant and the master database (the default)")
    s.add_argument("--no-master", action="store_true", help="skip the master database")
    s.add_argument("--dir", required=True, help="folder for the dumps and manifests")
    s.add_argument("--keep-daily", type=int, default=35, help="keep the newest backup of each of the last N days")
    s.add_argument("--keep-monthly", type=int, default=12, help="keep the oldest backup of each of the last N months")
    s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("restore-test", help="restore the newest dump into a scratch database and check it")
    s.add_argument("--tenant", help="workspace code (default: master and every tenant)")
    s.add_argument("--dir", required=True)
    s.set_defaults(fn=cmd_restore_test)
    s = sub.add_parser("restore", help="restore a dump into a NEW database (never over an existing one)")
    s.add_argument("--tenant", required=True, help="workspace code, or 'master'")
    s.add_argument("--dir", required=True)
    s.add_argument("--file", help="a specific dump file name (default: the newest)")
    s.add_argument("--into", required=True, help="name of the new database to create")
    s.add_argument("--keep-ownership", action="store_true",
                   help="restore owners and grants too (needed before it can replace a live database)")
    s.add_argument("--files-into", metavar="NEWFOLDER", default=None,
                   help="also unpack the backup's photos and files into this new (empty or missing) folder")
    s.set_defaults(fn=cmd_restore)
    for name in ("verify", "stock-verify"):
        s = sub.add_parser(name)
        s.add_argument("tenant", nargs="?", help="workspace code or id (all tenants if omitted)")
        if name == "verify":
            s.add_argument("--unit", help="check only this unit")
        s.add_argument("--fix", action="store_true", help="rebuild derived data from the source records")
        s.set_defaults(fn=cmd_verify, unit=None)
    for name, fn in (("enable", cmd_enable), ("disable", cmd_disable), ("remove", cmd_remove)):
        s = sub.add_parser(name)
        s.add_argument("tenant")
        s.add_argument("unit")
        s.set_defaults(fn=fn)
    args = p.parse_args(argv)
    if args.cmd == "operator":
        if args.action == "create" and not (args.name and args.email):
            p.error("operator create needs NAME and EMAIL")
        if args.action in ("disable", "enable", "reset-mfa", "reset-password", "role") and not args.name:
            p.error(f"operator {args.action} needs the operator's EMAIL")
        if args.action == "role" and not args.email:
            p.error("operator role needs EMAIL and ROLE")
    if args.cmd == "licence" and args.action == "issue" and not args.customer:
        p.error("licence issue needs --customer")
    if args.cmd == "licence" and args.action in ("install", "verify") and not args.file:
        p.error(f"licence {args.action} needs the licence FILE")
    if args.cmd == "install" and not args.all and not args.unit:
        p.error("give a unit name or --all")
    try:
        return int(args.fn(Registry(), args) or 0)
    except ZiiraError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

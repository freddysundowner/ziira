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
    ziira outbox-run [--once]           deliver committed events to after-commit subscribers
    ziira worker [--once]               deliver events and run background jobs (replaces outbox-run)
    ziira run-task <tenant> <name>      run one recurring task now (intel.run_checks, command.send_briefs, ...)
    ziira backup [--tenant CODE] --dir PATH [--keep-daily 35 --keep-monthly 12]   pg_dump of master + tenants, pruned
    ziira restore-test [--tenant CODE] --dir PATH   restore the newest dump to a scratch database, check it, drop it
    ziira restore --tenant CODE --dir PATH --into NEWDB   restore a dump into a NEW database (never over a live one)
    ziira operator create NAME EMAIL | list | disable|enable|reset-mfa EMAIL   platform staff (support access)
    ziira verify [tenant] [--unit U] [--fix]   check units' derived data (exit 1 if a problem remains)
    ziira stock-verify [tenant] [--fix]        the same, for Inventory only (run it nightly)
    ziira import <tenant> <kind> FILE.csv [--company NAME] [--commit]   check (and with --commit import) a file
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


def cmd_uninstall(reg: Registry, a: argparse.Namespace) -> None:
    reg.uninstall(a.unit)
    print(f"Uninstalled: {a.unit}")


def cmd_create_tenant(reg: Registry, a: argparse.Namespace) -> None:
    password = os.environ.get("ZIIRA_OWNER_PASSWORD") or getpass.getpass("Owner password: ")
    t = create_tenant(name=a.name, code=a.code, company=a.company, branch_code=a.branch_code,
                      branch_name=a.branch_name, owner_name=a.owner_name, owner_email=a.owner_email,
                      owner_password=password, tax_id=a.tax_id, currency=a.currency,
                      phone_country_code=a.phone_country_code, country=a.country,
                      vat_registered=a.vat_registered, timezone=a.timezone, registry=reg)
    print(f"tenant_id  = {t.tenant_id}\ncompany_id = {t.company_id}\nbranch_id  = {t.branch_id}\n"
          f"owner_id   = {t.owner_id}")


def cmd_tenants(_: Registry, __: argparse.Namespace) -> None:
    for t in list_tenants():
        print(f"{t.code:<24} {t.status:<12} {t.db_name:<32} {t.id}")


def cmd_remove(reg: Registry, a: argparse.Namespace) -> None:
    reg.remove_from_tenant(_tenant(a.tenant), a.unit)
    print(f"Removed {a.unit} from {a.tenant} (its tables and data are gone)")


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
    from ziira.kernel.checks import run_integrity_checks

    load_event_handlers(reg.units)
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


def cmd_operator(_: Registry, a: argparse.Namespace) -> None:
    from ziira.kernel import operators

    if a.action == "create":
        password = os.environ.get("ZIIRA_OPERATOR_PASSWORD") or getpass.getpass("Operator password: ")
        _id, secret, uri = operators.create_operator(a.name, a.email, password)
        print("Operator created. Add this to an authenticator app now: it is shown once and every sign-in needs it.")
        print(f"secret: {secret}\naddress: {uri}")
    elif a.action == "list":
        for o in operators.list_operators():
            print(f"{o['email']:<36} {o['status']:<9} {o['name']}   last sign-in: {o['last_sign_in_at'] or 'never'}")
    elif a.action in ("disable", "enable"):
        operators.set_status(a.name, "disabled" if a.action == "disable" else "active")
        print(f"Operator {a.name} {a.action}d")
    elif a.action == "reset-mfa":
        secret, uri = operators.reset_mfa(a.name)
        print(f"New secret (shown once): {secret}\naddress: {uri}")


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
    ran = jobs.run_periodic(_tenant(a.tenant), only=a.name, force=True)
    print(f"Ran {a.name}" if ran else f"{a.name} did not run (is its unit enabled for {a.tenant}?)")


def cmd_import(reg: Registry, a: argparse.Namespace) -> int:
    """Move data in from a CSV file: a dry run by default, `--commit` imports the valid rows (docs/data-import.md)."""
    from pathlib import Path

    from ziira.modules.imports.cli import run_import

    load_event_handlers(reg.units)
    mapping = dict(item.split("=", 1) for item in a.map or [] if "=" in item)
    return run_import(_tenant(a.tenant), kind=a.kind, path=Path(a.file), company=a.company, commit=a.commit,
                      decimal_separator=a.decimal, date_format=a.date_format, mapping=mapping,
                      rejected=Path(a.rejected) if a.rejected else None)


def cmd_worker(reg: Registry, a: argparse.Namespace) -> None:
    from ziira.kernel import jobs, notifications  # noqa: F401 - notifications registers its send job

    configure_logging()
    load_event_handlers(reg.units)
    if a.once:
        print(f"Delivered {outbox.process_all()} event(s), ran {jobs.run_all()} job(s)")
        return
    import time

    purged_at = 0.0
    while True:
        busy = outbox.process_all() + jobs.run_all()
        if time.monotonic() - purged_at > 3600:
            purged_at = time.monotonic()
            _purge_idempotency_keys(reg)
            from ziira.kernel import registration

            registration.purge()
            from ziira.kernel import throttle

            throttle.purge()
        if busy == 0:
            time.sleep(2.0)


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
    s.set_defaults(fn=cmd_create_tenant)
    sub.add_parser("tenants").set_defaults(fn=cmd_tenants)
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
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("worker")
    s.add_argument("--once", action="store_true", help="one pass, then stop")
    s.set_defaults(fn=cmd_worker)
    s = sub.add_parser("invite", help="make an invitation code for registration mode 'invite'")
    s.add_argument("--uses", type=int, default=1)
    s.add_argument("--days", type=int, default=30, help="valid for this many days (0: no expiry)")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_invite)
    s = sub.add_parser("operator", help="platform staff who may open support sessions (create, list, disable)")
    s.add_argument("action", choices=["create", "list", "disable", "enable", "reset-mfa"])
    s.add_argument("name", nargs="?", help="create: the name; disable/enable/reset-mfa: the email")
    s.add_argument("email", nargs="?", help="create: the email")
    s.set_defaults(fn=cmd_operator)
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
        if args.action in ("disable", "enable", "reset-mfa") and not args.name:
            p.error(f"operator {args.action} needs the operator's EMAIL")
    if args.cmd == "install" and not args.all and not args.unit:
        p.error("give a unit name or --all")
    try:
        return int(args.fn(Registry(), args) or 0)
    except ZiiraError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

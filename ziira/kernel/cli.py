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
    ziira verify [tenant] [--unit U] [--fix]   check units' derived data (exit 1 if a problem remains)
    ziira stock-verify [tenant] [--fix]        the same, for Inventory only (run it nightly)
"""

import argparse
import getpass
import logging
import os
import sys
from uuid import UUID

from ziira.kernel import outbox
from ziira.kernel.errors import ZiiraError
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
                      owner_password=password, kra_pin=a.kra_pin, vat_registered=a.vat_registered, registry=reg)
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
    logging.basicConfig(level=logging.INFO)
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


def cmd_worker(reg: Registry, a: argparse.Namespace) -> None:
    from ziira.kernel import jobs

    logging.basicConfig(level=logging.INFO)
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
    s.add_argument("--kra-pin")
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
    s = sub.add_parser("worker")
    s.add_argument("--once", action="store_true", help="one pass, then stop")
    s.set_defaults(fn=cmd_worker)
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
    if args.cmd == "install" and not args.all and not args.unit:
        p.error("give a unit name or --all")
    try:
        return int(args.fn(Registry(), args) or 0)
    except ZiiraError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

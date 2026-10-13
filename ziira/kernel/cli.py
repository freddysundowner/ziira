"""Command-line tool for administering Ziira Core.

    ziira units                         list units and whether they are installed
    ziira install <unit> | --all        install units (and what they require)
    ziira uninstall <unit>              remove a unit's tables (refused if in use)
    ziira create-tenant NAME --code CODE --company NAME --branch-code CODE --branch-name NAME
                        --owner-name NAME --owner-email EMAIL   (password asked, or ZIIRA_OWNER_PASSWORD)
    ziira enable <tenant-id> <unit>     enable a unit for a tenant
    ziira disable <tenant-id> <unit>    disable a unit for a tenant (data kept)
    ziira outbox-run [--once]           deliver committed events to after-commit subscribers
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
from ziira.kernel.tenants import create_tenant


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


def cmd_outbox_run(reg: Registry, a: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO)
    load_event_handlers(reg.units)
    if a.once:
        print(f"Delivered {outbox.process_all()} event(s)")
    else:
        outbox.run_forever()


def cmd_enable(reg: Registry, a: argparse.Namespace) -> None:
    done = reg.enable(UUID(a.tenant), a.unit)
    print("Enabled: " + (", ".join(done) if done else "already enabled"))


def cmd_disable(reg: Registry, a: argparse.Namespace) -> None:
    reg.disable(UUID(a.tenant), a.unit)
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
    s = sub.add_parser("outbox-run")
    s.add_argument("--once", action="store_true", help="one pass, then stop")
    s.set_defaults(fn=cmd_outbox_run)
    for name, fn in (("enable", cmd_enable), ("disable", cmd_disable)):
        s = sub.add_parser(name)
        s.add_argument("tenant")
        s.add_argument("unit")
        s.set_defaults(fn=fn)
    args = p.parse_args(argv)
    if args.cmd == "install" and not args.all and not args.unit:
        p.error("give a unit name or --all")
    try:
        args.fn(Registry(), args)
    except ZiiraError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

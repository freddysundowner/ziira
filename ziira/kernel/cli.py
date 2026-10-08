"""Command-line tool for administering Ziira Core.

    ziira units                         list units and whether they are installed
    ziira install <unit> | --all        install units (and what they require)
    ziira uninstall <unit>              remove a unit's tables (refused if in use)
    ziira create-tenant NAME --company NAME --branch-code CODE --branch-name NAME
    ziira enable <tenant-id> <unit>     enable a unit for a tenant
    ziira disable <tenant-id> <unit>    disable a unit for a tenant (data kept)
"""

import argparse
import sys
from uuid import UUID, uuid4

from sqlalchemy import text

from ziira.kernel.db import admin_session, tenant_session
from ziira.kernel.errors import ZiiraError
from ziira.kernel.registry import Registry


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


def cmd_create_tenant(_: Registry, a: argparse.Namespace) -> None:
    tenant_id, company_id, branch_id = uuid4(), uuid4(), uuid4()
    with admin_session() as s:
        s.execute(text("insert into kernel.tenant (id, name) values (:i, :n)"),
                  {"i": str(tenant_id), "n": a.name})
    with tenant_session(tenant_id, admin=True) as s:
        s.execute(text("insert into kernel.company (id, tenant_id, name, kra_pin, vat_registered) "
                       "values (:i, :t, :n, :p, :v)"),
                  {"i": str(company_id), "t": str(tenant_id), "n": a.company, "p": a.kra_pin,
                   "v": a.vat_registered})
        s.execute(text("insert into kernel.branch (id, tenant_id, company_id, code, name) "
                       "values (:i, :t, :c, :code, :n)"),
                  {"i": str(branch_id), "t": str(tenant_id), "c": str(company_id),
                   "code": a.branch_code, "n": a.branch_name})
    print(f"tenant_id  = {tenant_id}\ncompany_id = {company_id}\nbranch_id  = {branch_id}")


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
    s.add_argument("--company", required=True)
    s.add_argument("--branch-code", required=True)
    s.add_argument("--branch-name", required=True)
    s.add_argument("--kra-pin")
    s.add_argument("--vat-registered", action="store_true")
    s.set_defaults(fn=cmd_create_tenant)
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

"""Command line of the installer: collect answers, validate, run the steps, print the summary."""
from __future__ import annotations

import sys
from collections.abc import Sequence

from installer import __version__, config, util
from installer.config import Config
from installer.context import Ctx
from installer.steps import NAMES, STEPS
from installer.system import CommandFailed, System
from installer.ui import UI, Finished, StepFailed

LOG_PATH = "/var/log/ziira-install.log"


def collect_answers(cfg: Config, ui: UI) -> None:
    """Ask for what was not given (interactive only)."""
    if not ui.interactive:
        return
    ui.info("Ziira installer. Press Enter to accept a [default].")
    if not cfg.root_domain:
        cfg.root_domain = ui.ask("Root domain of the landing page (e.g. ziira.io)",
                                 validate=lambda v: None if util.valid_hostname(v.lower()) else "enter a domain such as ziira.io").lower()
    cfg.root_domain = cfg.root_domain.lower().rstrip(".")
    cfg.app_host = cfg.app_host or ui.ask("Host of the business app", f"app.{cfg.root_domain}")
    cfg.admin_host = cfg.admin_host or ui.ask("Host of the Super Admin", f"admin.{cfg.root_domain}")
    if not cfg.email and not cfg.self_signed:
        cfg.email = ui.ask("Email for Let's Encrypt certificate notices",
                           validate=lambda v: None if util.valid_email(v) else "enter an email address")
    if not cfg.admin_email:
        cfg.admin_name = ui.ask("First super admin: name", cfg.admin_name)
        cfg.admin_email = ui.ask("First super admin: email", cfg.email if util.valid_email(cfg.email) else "",
                                 validate=lambda v: None if util.valid_email(v) else "enter an email address")
    if not cfg.admin_password and not cfg.no_services and not cfg.dry_run:
        cfg.admin_password = _new_password(ui)
    if not cfg.smtp_host and ui.confirm("Configure the platform mailer (SMTP) now? Registration needs it", default=False):
        cfg.smtp_host = ui.ask("SMTP host")
        cfg.smtp_port = int(ui.ask("SMTP port", str(cfg.smtp_port)))
        cfg.smtp_user = ui.ask("SMTP user (empty if none)", cfg.smtp_user)
        cfg.smtp_password = ui.ask("SMTP password", secret=True)
        cfg.smtp_from = ui.ask("Sender address", cfg.admin_email)
    if cfg.smtp_host and not cfg.smtp_password and ui.interactive:
        cfg.smtp_password = ui.ask("SMTP password (empty if none)", secret=True)
    if not cfg.operator_networks:
        ui.info("Optional: limit the Super Admin to your own networks (CIDRs, comma separated, e.g. 203.0.113.0/24).")
        cfg.operator_networks = ui.ask("Allowed networks (Enter = anyone who has the password)", "",
                                       validate=lambda v: _cidr_problem(v))


def _cidr_problem(value: str) -> str | None:
    try:
        util.parse_cidrs(value)
    except ValueError as error:
        return str(error)
    return None


def _new_password(ui: UI) -> str:
    while True:
        first = ui.ask("Password for the first super admin (at least 12 characters)", secret=True)
        if len(first) < 12:
            ui.warn("too short")
            continue
        if ui.ask("Repeat the password", secret=True) == first:
            return first
        ui.warn("the two passwords differ")


def select_steps(cfg: Config) -> list[tuple[str, str, object]]:
    unknown = [n for n in cfg.only + cfg.skip if n not in NAMES]
    if unknown:
        raise SystemExit(f"Unknown step(s): {', '.join(unknown)}. Steps: {', '.join(NAMES)}")
    chosen = [s for s in STEPS if (not cfg.only or s[0] in cfg.only) and s[0] not in cfg.skip]
    return list(chosen)


def main(argv: Sequence[str] | None = None, *, system: System | None = None, ui: UI | None = None,
         environ: dict[str, str] | None = None, config_text: str | None = None) -> int:
    cfg, ns = config.load(list(sys.argv[1:] if argv is None else argv), environ, config_text)
    if ns.version:
        print(f"Ziira installer {__version__}")
        return 0
    if ns.list_steps:
        for name, title, _ in STEPS:
            print(f"{name:<10} {title}")
        return 0
    ui = ui or UI(interactive=not cfg.yes and sys.stdin.isatty())
    try:
        if not cfg.inspect:
            collect_answers(cfg, ui)
    except (EOFError, KeyboardInterrupt):
        ui.fail("cancelled")
        return 130
    cfg.resolve_defaults()
    problems = [] if cfg.inspect else cfg.validate()
    if not cfg.inspect and not cfg.dry_run and not cfg.no_services and not cfg.admin_password:
        problems.append("the first super admin's password is missing (set ZIIRA_OPERATOR_PASSWORD, or run interactively)")
    if cfg.admin_password and len(cfg.admin_password) < 12:
        problems.append("the super admin password must have at least 12 characters")
    if problems:
        ui.fail("some answers are missing or invalid:", "\n".join(f"  - {p}" for p in problems))
        return 2
    system = system or System(dry_run=cfg.dry_run, say=ui.plan)
    ctx = Ctx(cfg=cfg, sys=system, ui=ui)
    steps = [s for s in STEPS if s[0] == "inspect"] if cfg.inspect else select_steps(cfg)
    if not cfg.dry_run and not cfg.inspect:
        system.load_manifest()
    if cfg.dry_run:
        ui.info("DRY RUN: nothing will be changed. Read-only checks still run, so the plan reflects this machine.")
    exit_code = 0
    for number, (name, title, fn) in enumerate(steps, 1):
        ui.step(number, len(steps), title)
        try:
            fn(ctx)  # type: ignore[operator]
            if not cfg.inspect:
                system.save_manifest()
        except Finished as done:
            ui.info(str(done))
            break
        except StepFailed as error:
            ui.fail(error.message, error.hint)
            system.save_manifest()
            ui.info(f"Nothing is half-done that a re-run cannot resume. Run the installer again after fixing this "
                    f"(it skips what is finished). Step: {name}")
            exit_code = 1
            break
        except CommandFailed as error:
            ui.fail(str(error), "A re-run resumes where this stopped.")
            exit_code = 1
            break
    _final(ctx, exit_code if not cfg.inspect else 1)
    if not cfg.dry_run and system.is_root():
        try:
            with open(LOG_PATH, "a") as log:
                log.write("\n".join(ui.lines) + "\n")
        except OSError:
            pass
    return exit_code


def _final(ctx: Ctx, exit_code: int) -> None:
    cfg, ui = ctx.cfg, ctx.ui
    ui.info("")
    if exit_code:
        return
    rep = ui.report
    ui.info(f"{len(rep.changed)} change(s), {len(rep.skipped)} already in place, {len(rep.warnings)} warning(s)."
            + ("  (dry run: nothing was changed)" if cfg.dry_run else ""))
    if cfg.dry_run:
        return
    s = ctx.secrets()
    ui.info("")
    ui.info(f"  Landing page   https://{cfg.root_domain}")
    ui.info(f"  Business app   https://{cfg.app_host}")
    ui.info(f"  Super Admin    https://{cfg.admin_host}   (sign in as {cfg.admin_email})")
    ui.info(f"  Summary file   {ctx.summary_path}   |   check health any time with:  sudo ziira-doctor")
    if s.fresh_credentials_key:
        ui.info("")
        ui.info("  ================================================================================")
        ui.info("  BACK THIS KEY UP OFFLINE NOW (shown once; also in the summary file):")
        ui.info(f"  ZIIRA_CREDENTIALS_KEY = {s.credentials_key}")
        ui.info("  Losing it locks out every business. Do not store it with the backups.")
        ui.info("  ================================================================================")
    ui.info("")
    ui.info("Next: sign in to the Super Admin, create your plans, then publish the website content (Website > Publish):")
    ui.info("the landing page shows placeholder text until you do.")

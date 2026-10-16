"""Step 0: look at the server, say what would change, and ask. Changes nothing."""
from __future__ import annotations

from installer import inventory
from installer.context import Ctx
from installer.ui import Finished, StepFailed


def step_inspect(ctx: Ctx) -> None:
    cfg, ui = ctx.cfg, ctx.ui
    if not ctx.sys.is_root() and not cfg.dry_run:
        ui.warn("not running as root: nginx's configuration and some state cannot be read, so the inspection may be incomplete")
    inv = inventory.collect(ctx)
    ctx.facts["inventory"] = inv
    ctx.facts["ram_available_mb"] = inv.ram_available_mb
    for line in inventory.report(inv).splitlines():
        ui.info(line)
    plan = inventory.make_plan(ctx, inv)
    ctx.facts["plan"] = plan
    ui.info("")
    for line in inventory.plan_text(plan).splitlines():
        ui.info(line)
    # the plan decides these; every later step reads them from the configuration
    cfg.api_port, cfg.rebuild_port = plan.api_port, plan.rebuild_port
    if plan.mode == "behind":
        cfg.ports = plan.behind_port
    ctx.facts.update(mode=plan.mode, catch_all=plan.catch_all, packages=plan.packages,
                     nginx_preexisting=plan.nginx_preexisting, other_sites=[s.file for s in inv.nginx_sites
                                                                                 if not s.file.rsplit("/", 1)[-1].startswith("ziira-")])
    if plan.conflicts:
        raise StepFailed("the plan has conflicts; nothing was changed", hint="Resolve the items marked X above and run again.")
    if cfg.inspect:
        raise Finished("inspection finished: nothing was changed")
    if not (cfg.yes or cfg.dry_run) and not ui.confirm("Go ahead with this plan?", default=False):
        raise StepFailed("not confirmed; nothing was changed",
                         hint="Re-run and answer yes, or pass --yes for an unattended run. Take a snapshot or backup of the server first.")

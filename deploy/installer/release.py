"""Code releases: /opt/ziira/releases/<id> (code + virtualenv), a `current` symlink, atomic switch, rollback, pruning."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from installer import util
from installer.context import Ctx
from installer.ui import StepFailed

EXCLUDE = [".git", "node_modules", ".venv", "venv", ".env", ".env.*", "__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache",
           ".ruff_cache", ".cache", "e2e", "*.egg-info", ".DS_Store", ".claude"]
KEEP_RELEASES = 3


def repo_root_of_installer() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def is_checkout(ctx: Ctx, path: str) -> bool:
    return ctx.sys.exists(f"{path}/pyproject.toml") and ctx.sys.exists(f"{path}/ziira/kernel/app.py") \
        and ctx.sys.exists(f"{path}/deploy/installer/cli.py")


def fetch_source(ctx: Ctx, workdir: str) -> tuple[str, str]:
    """Where the code to install is: (directory, label). A repository or tarball is fetched into `workdir`."""
    cfg, sysm = ctx.cfg, ctx.sys
    if cfg.repo:
        target = f"{workdir}/src"
        sysm.run(["git", "clone", "--depth", "1", "--branch", cfg.branch, cfg.repo, target], timeout=900,
                 desc=f"git clone {cfg.repo} ({cfg.branch})")
        sha = sysm.run(["git", "-C", target, "rev-parse", "--short", "HEAD"], probe=True, check=False).out.strip() or "git"
        return target, sha
    if cfg.tarball:
        target = f"{workdir}/src"
        sysm.makedirs(target)
        sysm.run(["tar", "-xzf", cfg.tarball, "-C", target, "--strip-components=1"], desc=f"unpack {cfg.tarball}")
        return target, re.sub(r"[^A-Za-z0-9.]+", "", os.path.basename(cfg.tarball).split(".tar")[0])[:20] or "tarball"
    src = cfg.from_dir or repo_root_of_installer()
    if not is_checkout(ctx, src) and not cfg.dry_run:
        raise StepFailed(f"{src} does not look like a Ziira checkout (pyproject.toml, ziira/, deploy/ expected)",
                         hint="Run the installer from the repository, or give --from-dir, --repo or --tarball.")
    sha = sysm.run(["git", "-C", src, "rev-parse", "--short", "HEAD"], probe=True, check=False).out.strip() or "local"
    return src, sha


def new_release_id(label: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + label


def build_release(ctx: Ctx, src: str, rel_id: str, *, venv: bool = True) -> str:
    """Copy the code to releases/<id>, create its virtualenv and install the application into it. Returns the path."""
    cfg, sysm = ctx.cfg, ctx.sys
    final = f"{cfg.release_dir}/{rel_id}"
    partial = final        # a virtualenv is not relocatable: build it where it will live; `.complete` marks it finished
    sysm.makedirs(cfg.release_dir)
    if sysm.exists(partial):
        sysm.remove(partial)
    sysm.copy_tree(src, partial, exclude=EXCLUDE)
    if sysm.exists(f"{partial}/build"):
        sysm.remove(f"{partial}/build")           # a stale setuptools build folder must not leak into the install
    py = ctx.facts.get("python", "python3")
    if venv:
        sysm.run([py, "-m", "venv", f"{partial}/venv"], desc=f"create the virtual environment in {final}/venv")
        sysm.run([f"{partial}/venv/bin/pip", "install", "--quiet", "--no-cache-dir", "--upgrade", "pip"], timeout=600)
        sysm.run(util.niced([f"{partial}/venv/bin/pip", "install", "--quiet", "--no-cache-dir", partial]), timeout=1800,
                 env={"MAKEFLAGS": "-j1"},
                 desc=f"pip install the application ({final})")
        check = sysm.run([f"{partial}/venv/bin/python", "-c",
                          "from ziira.kernel.registry import discover; print(len(discover()))"],
                         cwd=cfg.state_dir if sysm.exists(cfg.state_dir) else "/", check=False, probe=False)
        if not cfg.dry_run and (not check.ok or not check.out.strip().isdigit() or int(check.out.strip()) < 5):
            sysm.run(["rm", "-rf", partial], check=False)
            raise StepFailed("the installed application cannot find its modules (packaging problem)",
                             hint=(check.err or check.out)[-500:])
    sysm.run(["chmod", "-R", "a+rX,go-w", partial], desc=f"make {final} readable and read-only for the service")
    sysm.write_text(f"{partial}/.complete", rel_id + "\n")
    return final


def activate(ctx: Ctx, release_path: str) -> str | None:
    """Point `current` at the release; returns the previous target (for rollback)."""
    previous = ctx.sys.readlink(ctx.cfg.current)
    ctx.sys.symlink(ctx.cfg.current, release_path)
    return previous


def list_releases(ctx: Ctx, base: str) -> list[str]:
    return [d for d in ctx.sys.listdir(base) if re.match(r"^\d{14}-", d) and not d.endswith(".partial")]


def prune(ctx: Ctx, base: str, keep: int = KEEP_RELEASES) -> list[str]:
    """Delete old releases beyond the newest `keep`, never the one `current` points at."""
    live = os.path.basename((ctx.sys.readlink(f"{base}/../current") or "").rstrip("/")) if base.endswith("/releases") else ""
    releases = sorted(list_releases(ctx, base))
    doomed = [r for r in releases[:-keep] if r != live] if len(releases) > keep else []
    for r in doomed:
        ctx.sys.remove(f"{base}/{r}")
    return doomed

"""Building the business web app, publishing built folders as releases, and the Content-Security-Policy hashes."""
from __future__ import annotations

import base64
import hashlib
import re

from installer import util
from installer.context import PATH, Ctx
from installer.release import KEEP_RELEASES, prune
from installer.ui import StepFailed

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)
PLACEHOLDER_HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ziira is being installed</title><body style="font-family:system-ui;margin:3rem"><h1>Ziira is being installed</h1>
<p>This page is replaced when the installation finishes.</p></body></html>
"""


def csp_hashes(index_html: str) -> list[str]:
    """base64 SHA-256 of every inline script in the built index.html (the CSP lists them instead of 'unsafe-inline')."""
    return [base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() for body in INLINE_SCRIPT.findall(index_html)]


def build_env(ctx: Ctx, extra: dict[str, str] | None = None) -> dict[str, str]:
    node = ctx.facts.get("node_bin", "")
    env = {"PATH": f"{node}:{PATH}" if node else PATH, "HOME": ctx.cfg.state_dir, "CI": "1",
           "npm_config_cache": f"{ctx.cfg.state_dir}/.npm", "npm_config_update_notifier": "false",
           "NODE_OPTIONS": f"--max-old-space-size={util.node_memory_mb(int(ctx.facts.get('ram_available_mb', 0) or 0))}",
           "npm_config_jobs": "1", "MAKEFLAGS": "-j1"}
    env.update(extra or {})
    return env


def publish_dir(ctx: Ctx, dist: str, kind: str, rel_id: str) -> str:
    """Copy a built folder to <web_root>/<kind>/releases/<id> and switch `current` to it atomically."""
    cfg, sysm = ctx.cfg, ctx.sys
    base = f"{cfg.web_root}/{kind}"
    final = f"{base}/releases/{rel_id}"
    sysm.makedirs(f"{base}/releases")
    if not sysm.exists(final):
        sysm.run(["rsync", "-a", "--delete", f"{dist}/", f"{final}/"], desc=f"copy {dist} to {final}")
        sysm.run(["chmod", "-R", "a+rX,go-w", final], desc=f"make {final} world-readable")
    sysm.symlink(f"{base}/current", final)
    prune(ctx, f"{base}/releases", KEEP_RELEASES)
    return final


def ensure_placeholders(ctx: Ctx) -> bool:
    """nginx needs a `current` folder for each root even before the first build. True when one was created."""
    cfg, sysm = ctx.cfg, ctx.sys
    created = False
    for kind in ("app", "site"):
        base = f"{cfg.web_root}/{kind}"
        if sysm.exists(f"{base}/current"):
            continue
        created = True
        sysm.makedirs(f"{base}/releases/initial")
        sysm.write_text(f"{base}/releases/initial/index.html", PLACEHOLDER_HTML)
        sysm.symlink(f"{base}/current", f"{base}/releases/initial")
    return created


def build_frontend(ctx: Ctx, release_path: str, rel_id: str) -> str | None:
    """Build frontend/ and publish it as the business app (also served on the admin host). Returns the published dir."""
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    src = f"{release_path}/frontend"
    if cfg.prebuilt:
        if not sysm.exists(f"{src}/dist/index.html") and not cfg.dry_run:
            raise StepFailed("--prebuilt was given but frontend/dist/index.html does not exist",
                             hint="Run `npm --prefix frontend ci && npm --prefix frontend run build` first.")
        dist = f"{src}/dist"
    else:
        work = f"{cfg.state_dir}/build/app"
        sysm.makedirs(f"{cfg.state_dir}/build", owner=cfg.service_user, group=cfg.service_user)
        sysm.makedirs(work, owner=cfg.service_user, group=cfg.service_user)
        user = cfg.service_user
        sysm.run(["rsync", "-a", "--delete", "--exclude", "node_modules", "--exclude", "dist", f"{src}/", f"{work}/"],
                 user=user, desc=f"copy frontend/ to the build workspace {work}")
        env = build_env(ctx, {"VITE_HELP_URL": f"https://{cfg.root_domain}/help"})
        sysm.run(util.niced(["npm", "ci", "--no-audit", "--no-fund"]), user=user, cwd=work, env=env, timeout=1800,
                 desc="npm ci (web app)")
        sysm.run(util.niced(["npm", "run", "build"]), user=user, cwd=work, env=env, timeout=1800, desc="npm run build (web app)")
        dist = f"{work}/dist"
    out = publish_dir(ctx, dist, "app", rel_id)
    ui.ok(f"web app published to {out}")
    return out


def app_csp_hashes(ctx: Ctx) -> list[str]:
    text = ctx.sys.read_text(f"{ctx.cfg.web_root}/app/current/index.html") or ""
    return csp_hashes(text)

"""Steps 12-18: nginx, certificates, the website, firewall and the other small system files, the summary."""
from __future__ import annotations

import json
import re
import time

from installer import nginxconf, units
from installer.context import Ctx
from installer.nginxconf import NginxOptions
from installer.ui import StepFailed

SITES = ("ziira-site.conf", "ziira-app.conf", "ziira-admin.conf", "ziira-default.conf")


# --------------------------------------------------------------------------- nginx
def other_sites(ctx: Ctx) -> list[str]:
    """Enabled nginx sites that are neither ours nor the distribution's stock 'default'."""
    sysm = ctx.sys
    found: list[str] = []
    for name in sysm.listdir("/etc/nginx/sites-enabled"):
        if name.startswith("ziira-") or name == "default":
            continue
        found.append(f"sites-enabled/{name}")
    for name in sysm.listdir("/etc/nginx/conf.d"):
        if name.endswith(".conf") and not name.startswith("ziira-"):
            found.append(f"conf.d/{name}")
    return found


def nginx_options(ctx: Ctx, *, https: bool, hsts: str = "off") -> NginxOptions:
    certs = cert_paths(ctx) if https else {}
    if "nginx_version" not in ctx.facts:
        v = ctx.sys.run(["nginx", "-v"], probe=True, check=False)
        ctx.facts["nginx_version"] = (v.err or v.out).strip()
    version = nginxconf.parse_version(str(ctx.facts.get("nginx_version", "")))
    others = ctx.facts.get("other_sites")
    if others is None:
        others = other_sites(ctx)
        ctx.facts["other_sites"] = others
    ocsp = ctx.facts.get("ocsp")
    if ocsp is None:        # a later run (update): keep what the installed configuration already does
        ocsp = "ssl_stapling on" in (ctx.sys.read_text("/etc/nginx/sites-available/ziira-app.conf") or "")
    brotli = ctx.facts.get("brotli")
    if brotli is None:
        brotli = "brotli on" in (ctx.sys.read_text("/etc/nginx/conf.d/ziira-common.conf") or "")
    from installer.nginxconf import directives_in
    o = NginxOptions(version=version, certs=certs, https=https, hsts=hsts, ocsp=bool(ocsp),
                     already_set=directives_in(ctx.sys.read_text("/etc/nginx/nginx.conf") or ""),
                     brotli=bool(brotli), catch_all=not others,
                     csp_hashes=[], hook_token=ctx.secrets().hook_token if ctx.rebuild_enabled else "",
                     public_ip=str(ctx.facts.get("public_ip", "")))
    from installer.webbuild import app_csp_hashes
    o.csp_hashes = app_csp_hashes(ctx)
    return o


def cert_paths(ctx: Ctx) -> dict[str, tuple[str, str, str]]:
    cfg = ctx.cfg
    out: dict[str, tuple[str, str, str]] = {}
    for lineage, hosts in cfg.lineages().items():
        if cfg.self_signed:
            base = f"{cfg.env_dir}/selfsigned/{lineage}"
            trio = (f"{base}/fullchain.pem", f"{base}/privkey.pem", f"{base}/fullchain.pem")
        else:
            base = f"/etc/letsencrypt/live/{lineage}"
            trio = (f"{base}/fullchain.pem", f"{base}/privkey.pem", f"{base}/chain.pem")
        for host in hosts:
            out[host] = trio
    return out


def apply_nginx(ctx: Ctx, files: dict[str, str]) -> bool:
    """Write the files, test the configuration, reload. On a failed test the previous files are put back."""
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    previous = {path: sysm.read_text(path) for path in files}
    # files of ours that must disappear (the catch-all, when other sites make it unsafe)
    stale = [f"/etc/nginx/sites-available/{n}" for n in SITES if f"/etc/nginx/sites-available/{n}" not in files
             and sysm.exists(f"/etc/nginx/sites-available/{n}")]
    changed = [p for p, text in files.items() if sysm.write_text(p, text)]
    new_links: list[str] = []
    for name in SITES:
        available, enabled = f"/etc/nginx/sites-available/{name}", f"/etc/nginx/sites-enabled/{name}"
        if available in files:
            if sysm.symlink(enabled, available):
                changed.append(enabled)
                new_links.append(enabled)
        elif sysm.exists(enabled):
            sysm.remove(enabled)
            changed.append(enabled)
    stock_default = sysm.readlink("/etc/nginx/sites-enabled/default")
    for path in stale:
        sysm.remove(path)
    if ctx.facts.get("other_sites") == [] and sysm.exists("/etc/nginx/sites-enabled/default"):
        text = sysm.read_text("/etc/nginx/sites-available/default") or ""
        if "default_server" in text:
            sysm.remove("/etc/nginx/sites-enabled/default")
            changed.append("sites-enabled/default")
            ui.info("disabled the stock nginx 'default' site (it would clash with the catch-all; the file in sites-available is kept)")
    test = sysm.run(["nginx", "-t"], probe=cfg.dry_run, check=False)
    if not test.ok and not cfg.dry_run:
        for path, text in previous.items():
            if text is None:
                sysm.remove(path)
            else:
                sysm.write_text(path, text)
        for link in new_links:
            sysm.remove(link)
        if stock_default and not sysm.exists("/etc/nginx/sites-enabled/default"):
            sysm.symlink("/etc/nginx/sites-enabled/default", stock_default)
        raise StepFailed("nginx rejected the generated configuration; the previous configuration was restored",
                         hint=(test.err or test.out).strip()[-1500:])
    if changed and ctx.real_services:
        active = sysm.run(["systemctl", "is-active", "--quiet", "nginx"], probe=True, check=False).ok
        sysm.run(["systemctl", "reload" if active else "restart", "nginx"], desc="reload nginx")
        sysm.run(["systemctl", "enable", "nginx"], check=False)
    return bool(changed)


def step_nginx(ctx: Ctx) -> None:
    ui = ctx.ui
    paths = {p for trio in cert_paths(ctx).values() for p in trio[:2]}
    if paths and all(ctx.sys.exists(p) for p in paths) and ctx.sys.exists("/etc/nginx/sites-enabled/ziira-app.conf"):
        ui.already("certificates and nginx sites exist: the port-80-only stage is skipped (no downtime on re-runs)")
        return
    files = nginxconf.all_files(ctx.cfg, nginx_options(ctx, https=False))
    ctx.sys.makedirs(nginxconf.LOG_DIR, owner="root", group="adm", mode=0o750)
    changed = apply_nginx(ctx, files)
    if ctx.facts.get("other_sites"):
        ui.warn("other nginx sites exist (" + ", ".join(ctx.facts["other_sites"]) + "): the catch-all that refuses unknown "
                "Host names was NOT installed so they keep working")
    if changed:
        ui.ok("nginx serves the three hosts on port 80 (ACME challenge ready)")
    else:
        ui.already("nginx port-80 configuration")


# --------------------------------------------------------------------------- certificates
def cert_names(ctx: Ctx, cert: str) -> set[str]:
    r = ctx.sys.run(["openssl", "x509", "-in", cert, "-noout", "-text"], probe=True, check=False)
    return set(re.findall(r"DNS:([A-Za-z0-9.*-]+)", r.out))


def cert_issuer(ctx: Ctx, cert: str) -> str:
    return ctx.sys.run(["openssl", "x509", "-in", cert, "-noout", "-issuer"], probe=True, check=False).out


def make_self_signed(ctx: Ctx, lineage: str, hosts: list[str]) -> bool:
    sysm, cfg = ctx.sys, ctx.cfg
    base = f"{cfg.env_dir}/selfsigned/{lineage}"
    cert = f"{base}/fullchain.pem"
    if sysm.exists(cert) and set(hosts) <= cert_names(ctx, cert) and \
            sysm.run(["openssl", "x509", "-in", cert, "-noout", "-checkend", str(30 * 86400)], probe=True, check=False).ok:
        return False
    sysm.makedirs(base, mode=0o750, owner="root", group="root")
    san = ",".join(f"DNS:{h}" for h in hosts)
    sysm.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365", "-keyout", f"{base}/privkey.pem",
              "-out", cert, "-subj", f"/CN={hosts[0]}", "-addext", f"subjectAltName={san}"],
             desc=f"openssl: self-signed certificate for {', '.join(hosts)}")
    sysm.run(["chmod", "600", f"{base}/privkey.pem"], check=False)
    return True


def request_cert(ctx: Ctx, lineage: str, hosts: list[str]) -> bool:
    """Ask Let's Encrypt (webroot challenge served by nginx on port 80). False when a good certificate already exists."""
    cfg, sysm = ctx.cfg, ctx.sys
    cert = f"/etc/letsencrypt/live/{lineage}/fullchain.pem"
    force = False
    if sysm.exists(cert):
        names = cert_names(ctx, cert)
        staging_now = "STAGING" in cert_issuer(ctx, cert).upper() or "(STAGING)" in cert_issuer(ctx, cert)
        if set(hosts) <= names and staging_now == cfg.staging:
            return False
        force = staging_now != cfg.staging
    cmd = ["certbot", "certonly", "--webroot", "-w", nginxconf.ACME_ROOT, "--cert-name", lineage, "--non-interactive",
           "--agree-tos", "-m", cfg.email, "--no-eff-email", "--expand"]
    for h in hosts:
        cmd += ["-d", h]
    if cfg.staging:
        cmd.append("--staging")
    if force:
        cmd.append("--force-renewal")
    r = sysm.run(cmd, check=False, timeout=600, desc=f"certbot: certificate '{lineage}' for {', '.join(hosts)}"
                 + (" (Let's Encrypt STAGING)" if cfg.staging else ""))
    if not r.ok and not cfg.dry_run:
        raise StepFailed(f"Let's Encrypt did not issue the certificate for {', '.join(hosts)}", hint=certbot_hint(r.out + r.err))
    return True


def certbot_hint(output: str) -> str:
    text = output.lower()
    tips = []
    if "rate limit" in text or "too many" in text:
        tips.append("Let's Encrypt rate limit reached: wait (an hour to a week depending on the limit) or test with --staging.")
    if "dns problem" in text or "nxdomain" in text or "no valid ip" in text:
        tips.append("DNS problem: the names must resolve to this server before certificates can be issued.")
    if "timeout" in text or "connection refused" in text or "firewall" in text or "unauthorized" in text:
        tips.append("The challenge on port 80 was unreachable: check the provider's firewall/security group allows 80 and 443, "
                    "and that nothing else answers on port 80.")
    if "authorization" in text and "email" in text:
        tips.append("Check the contact email (--email).")
    tips.append("Details: /var/log/letsencrypt/letsencrypt.log. Fix the cause and run the installer again: it resumes here.")
    return "\n".join(tips) + "\n\n" + output.strip()[-900:]


def step_ssl(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    issued: list[str] = []
    if cfg.self_signed:
        ui.warn("self-signed certificates: browsers will warn; for staging and tests only")
        for lineage, hosts in cfg.lineages().items():
            if make_self_signed(ctx, lineage, hosts):
                issued.append(lineage)
    elif cfg.no_services:
        ui.already("Let's Encrypt skipped (--no-services)")
    else:
        if not cfg.agree_tos and not ctx.ui.confirm("Do you accept the Let's Encrypt subscriber agreement "
                                                    "(https://letsencrypt.org/repository/)?", default=False):
            raise StepFailed("the Let's Encrypt subscriber agreement was not accepted",
                             hint="Run again and answer yes, or pass --agree-tos.")
        for lineage, hosts in cfg.lineages().items():
            if request_cert(ctx, lineage, hosts):
                issued.append(lineage)
    if issued:
        ui.ok("certificates ready: " + ", ".join(issued))
    else:
        ui.already("certificates are present and cover every host")
    # OCSP stapling only when the certificate names an OCSP responder (Let's Encrypt no longer does)
    if not cfg.self_signed and ctx.real_services:
        first = cert_paths(ctx)[cfg.app_host][0]
        r = sysm.run(["openssl", "x509", "-in", first, "-noout", "-ocsp_uri"], probe=True, check=False)
        ctx.facts["ocsp"] = bool(r.out.strip())
    # renewal
    if cfg.self_signed or cfg.no_services:
        return
    hook = "/etc/letsencrypt/renewal-hooks/deploy/ziira-reload-nginx.sh"
    sysm.makedirs("/etc/letsencrypt/renewal-hooks/deploy")
    if sysm.write_text(hook, units.certbot_deploy_hook(), mode=0o755):
        ui.ok("renewal hook installed: nginx reloads after every renewal")
    timer = sysm.run(["systemctl", "list-unit-files", "certbot.timer"], probe=True, check=False)
    if "certbot.timer" in timer.out:
        if ctx.units_to_enable(["certbot.timer"]):
            sysm.run(["systemctl", "enable", "--now", "certbot.timer"], desc="enable certbot.timer")
    elif ctx.units_to_enable(["ziira-certbot-renew.timer"]):
        service, tm = units.certbot_timer_fallback()
        sysm.write_text("/etc/systemd/system/ziira-certbot-renew.service", service)
        sysm.write_text("/etc/systemd/system/ziira-certbot-renew.timer", tm)
        sysm.run(["systemctl", "daemon-reload"])
        sysm.run(["systemctl", "enable", "--now", "ziira-certbot-renew.timer"])
        ui.ok("this system has no certbot.timer: installed ziira-certbot-renew.timer instead")
    if not issued:
        ui.already("automatic renewal (tested when the certificates were issued; run `certbot renew --dry-run` to test again)")
        return
    dry = sysm.run(["certbot", "renew", "--dry-run", "--non-interactive"], check=False, timeout=600,
                   desc="certbot renew --dry-run (proves renewal works)")
    if dry.ok or cfg.dry_run:
        ui.ok("certbot renew --dry-run succeeded: automatic renewal works")
    else:
        ui.warn("certbot renew --dry-run FAILED: certificates will not renew by themselves until this is fixed:\n"
                + (dry.out + dry.err).strip()[-600:])


def https_works(ctx: Ctx) -> bool:
    """Every host answers over TLS with a certificate this machine trusts (so HSTS cannot lock anyone out)."""
    for host in ctx.cfg.hosts():
        r = ctx.sys.run(["curl", "-sS", "--max-time", "10", "-o", "/dev/null", "--resolve", f"{host}:443:127.0.0.1",
                         f"https://{host}/"], probe=True, check=False)
        if not r.ok:
            ctx.ui.info(f"HTTPS check for {host} failed: {r.err.strip()[-120:]}")
            return False
    return True


def step_nginx_tls(ctx: Ctx) -> None:
    cfg, ui = ctx.cfg, ctx.ui
    trusted = not (cfg.self_signed or cfg.staging)
    # Phase 1: HTTPS without HSTS, so a certificate problem can never lock a browser out.
    existing_hsts = "Strict-Transport-Security" in (ctx.sys.read_text("/etc/nginx/snippets/ziira-headers-app.conf") or "")
    keep = cfg.hsts if (existing_hsts and trusted) else "off"
    changed = apply_nginx(ctx, nginxconf.all_files(cfg, nginx_options(ctx, https=True, hsts=keep)))
    if changed:
        ui.ok("nginx serves the site, the app and the Super Admin over HTTPS (TLS 1.2+, HTTP redirects to HTTPS)")
    else:
        ui.already("nginx HTTPS configuration")
    # Phase 2: HSTS, only after HTTPS is confirmed to work with a trusted certificate.
    if cfg.hsts == "off" or not trusted:
        ui.info("HSTS is off" + (" (test certificates)" if not trusted else " (--hsts off)"))
        return
    if keep != "off":
        ui.already(f"HSTS ({cfg.hsts})")
        return
    if not ctx.real_services:
        ui.info("HSTS not enabled (--no-services: HTTPS was not verified)")
        return
    if https_works(ctx):
        apply_nginx(ctx, nginxconf.all_files(cfg, nginx_options(ctx, https=True, hsts=cfg.hsts)))
        ui.ok(f"HSTS enabled ({nginxconf.hsts_value(cfg.hsts)}) after confirming HTTPS works on every host")
    else:
        ui.warn("HTTPS did not verify on every host, so HSTS was NOT enabled. Fix it, then run the installer again.")


# --------------------------------------------------------------------------- website
def step_site(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    current = sysm.readlink(f"{cfg.web_root}/site/current") or ""
    if current and "initial" not in current:
        ui.already(f"website {current.rsplit('/', 1)[-1]} is published (the Super Admin's Publish rebuilds it)")
        return
    release_path = str(ctx.facts.get("release", cfg.current))
    if cfg.prebuilt:
        dist = f"{release_path}/site/dist"
        if not sysm.exists(f"{dist}/index.html") and not cfg.dry_run:
            raise StepFailed("--prebuilt was given but site/dist/index.html does not exist",
                             hint="Build it first: PUBLIC_SITE_URL=... npm --prefix site ci && npm --prefix site run build")
        from installer.webbuild import publish_dir
        publish_dir(ctx, dist, "site", time.strftime("%Y%m%d%H%M%S"))
        sysm.run(["chown", "-R", f"{cfg.service_user}:{cfg.service_user}", f"{cfg.web_root}/site"], check=False,
                 desc="give the service user the site web root")
        ui.ok("published the prebuilt website (note: the Super Admin's Publish cannot rebuild it with --prebuilt)")
        return
    if cfg.no_services:
        ui.already("website build skipped (--no-services)")
        return
    env = {"PYTHONPATH": f"{release_path}/deploy", "ZIIRA_REBUILD_ENV": ctx.rebuild_env_path}
    r = sysm.run(["/usr/bin/python3", "-m", "installer.sitebuild", "build"], user=cfg.service_user, env=env,
                 cwd=cfg.state_dir, check=False, timeout=3600, desc="build and publish the website (npm ci, npm run build)")
    if not r.ok and not cfg.dry_run:
        raise StepFailed("the website build failed", hint=(r.out + r.err).strip()[-1500:])
    last = json.loads(sysm.read_text(f"{cfg.state_dir}/site-build/last.json") or "{}")
    if last.get("warning"):
        ui.warn("website: " + str(last["warning"]))
    ui.ok("website built and published")


# --------------------------------------------------------------------------- firewall and small system files
def ssh_port(ctx: Ctx) -> int | None:
    r = ctx.sys.run(["sshd", "-T"], probe=True, check=False)
    m = re.search(r"^port (\d+)$", r.out, re.M)
    if m:
        return int(m.group(1))
    listening = ctx.sys.run(["ss", "-ltnpH"], probe=True, check=False).out
    m = re.search(r':(\d+)\s+\S+\s+users:\(\("sshd"', listening)
    return int(m.group(1)) if m else None


def step_system(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    sysm.write_text("/etc/logrotate.d/ziira-nginx", units.logrotate_conf())
    if cfg.no_services:
        ui.already("firewall and fail2ban skipped (--no-services)")
        return
    # firewall
    if cfg.no_firewall:
        ui.already("firewall untouched (--no-firewall)")
    else:
        port = ssh_port(ctx)
        if port is None:
            ui.warn("could not find the SSH port, so the firewall was NOT enabled (enabling it could lock you out). "
                    "Run: ufw allow <ssh-port>/tcp && ufw allow 80,443/tcp && ufw enable")
        else:
            status = sysm.run(["ufw", "status"], probe=True, check=False).out
            rules = [f"{port}/tcp", "80/tcp", "443/tcp"]
            added = [r for r in rules if not re.search(rf"^{re.escape(r)}\s+ALLOW", status, re.M)]
            for r in added:
                sysm.run(["ufw", "allow", r], desc=f"ufw allow {r}")
            if "Status: active" not in status:
                sysm.run(["ufw", "default", "deny", "incoming"])
                sysm.run(["ufw", "default", "allow", "outgoing"])
                sysm.run(["ufw", "--force", "enable"], desc="ufw enable (SSH, 80 and 443 allowed first)")
                ui.ok(f"firewall enabled: only SSH ({port}), 80 and 443 are open; PostgreSQL is not exposed")
            elif added:
                ui.ok("firewall: opened " + ", ".join(added))
            else:
                ui.already("firewall allows SSH, 80 and 443")
    # fail2ban
    if cfg.no_fail2ban:
        ui.already("fail2ban skipped (--no-fail2ban)")
    elif sysm.write_text("/etc/fail2ban/jail.d/ziira.local", units.fail2ban_jail(cfg)):
        sysm.run(["systemctl", "enable", "--now", "fail2ban"], check=False)
        sysm.run(["systemctl", "restart", "fail2ban"], check=False)
        ui.ok("fail2ban: sshd and nginx rate-limit jails enabled")
    else:
        ui.already("fail2ban jails")

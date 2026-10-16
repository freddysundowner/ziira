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


def nginx_options(ctx: Ctx, *, https: bool, hsts: str = "off") -> NginxOptions:
    """Rendering options. In "behind" mode our files live under /etc/ziira/nginx and serve plain HTTP on 127.0.0.1."""
    cfg = ctx.cfg
    behind = cfg.ports if ctx.facts.get("mode") == "behind" else 0
    certs = cert_paths(ctx) if (https and not behind) else {}
    if "nginx_version" not in ctx.facts:
        v = ctx.sys.run(["nginx", "-v"], probe=True, check=False)
        ctx.facts["nginx_version"] = (v.err or v.out).strip()
    version = nginxconf.parse_version(str(ctx.facts.get("nginx_version", "")))
    ocsp = ctx.facts.get("ocsp")
    if ocsp is None:        # a later run (update): keep what the installed configuration already does
        ocsp = "ssl_stapling on" in (ctx.sys.read_text("/etc/nginx/sites-available/ziira-app.conf") or "")
    from installer.webbuild import app_csp_hashes
    return NginxOptions(
        version=version, certs=certs, https=https or bool(behind), hsts="off" if behind else hsts, ocsp=bool(ocsp) and not behind,
        catch_all=bool(ctx.facts.get("catch_all")) and not behind, csp_hashes=app_csp_hashes(ctx),
        default_cert=(f"{cfg.env_dir}/tls/default.crt", f"{cfg.env_dir}/tls/default.key"),
        hook_token=ctx.secrets().hook_token if ctx.rebuild_enabled else "", public_ip=str(ctx.facts.get("public_ip", "")),
        behind_port=behind, base=f"{cfg.env_dir}/nginx" if behind else "/etc/nginx", sites="sites" if behind else "sites-available")


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


def nginx_commands(ctx: Ctx) -> tuple[list[str], str]:
    """(argv prefix that tests our configuration, systemd unit that serves it): the shared nginx, or our own in behind mode."""
    if ctx.facts.get("mode") == "behind":
        return ["nginx", "-c", f"{ctx.cfg.env_dir}/nginx/nginx.conf"], "ziira-nginx"
    return ["nginx"], "nginx"


def apply_nginx(ctx: Ctx, files: dict[str, str]) -> bool:
    """Write our files, test the configuration, reload (never restart). If the test fails every file is put back."""
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    behind = ctx.facts.get("mode") == "behind"
    previous = {path: sysm.read_text(path) for path in files}
    changed = [p for p, text in files.items() if sysm.write_text(p, text)]
    new_links: list[str] = []
    for name in SITES:
        available, enabled = f"/etc/nginx/sites-available/{name}", f"/etc/nginx/sites-enabled/{name}"
        if behind:
            continue
        if available in files:
            if sysm.symlink(enabled, available):
                changed.append(enabled)
                new_links.append(enabled)
        elif sysm.exists(enabled) and sysm.manifest.known(enabled):     # only ever remove a link that is ours
            sysm.remove(enabled)
            changed.append(enabled)
    stock_default = sysm.readlink("/etc/nginx/sites-enabled/default")
    if not behind and files.get("/etc/nginx/sites-available/ziira-default.conf") and stock_default \
            and not ctx.facts.get("nginx_preexisting"):
        # Only on an nginx that we installed ourselves a minute ago: its welcome page would clash with our catch-all.
        sysm.remove("/etc/nginx/sites-enabled/default")
        changed.append("sites-enabled/default")
    test_cmd, unit = nginx_commands(ctx)
    test = sysm.run([*test_cmd, "-t"], probe=cfg.dry_run, check=False)
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
        raise StepFailed("nginx rejected the generated configuration; our files were put back and nothing else was touched",
                         hint=(test.err or test.out).strip()[-1500:])
    if changed and ctx.real_services:
        active = sysm.run(["systemctl", "is-active", "--quiet", unit], probe=True, check=False).ok
        if active:
            sysm.run(["systemctl", "reload", unit], desc=f"systemctl reload {unit} (never a restart)")
        elif unit == "ziira-nginx" or not ctx.facts.get("nginx_preexisting"):
            sysm.run(["systemctl", "enable", "--now", unit], desc=f"start {unit}")
        else:
            ui.warn("nginx is installed but not running; it was not started (it is not ours). Start it when you are ready: "
                    "systemctl start nginx")
    return bool(changed)


def step_nginx(ctx: Ctx) -> None:
    ui = ctx.ui
    if ctx.facts.get("mode") == "behind":
        ui.already("first (port 80) stage not needed: no certificates are requested behind another proxy")
        return
    paths = {p for trio in cert_paths(ctx).values() for p in trio[:2]}
    if paths and all(ctx.sys.exists(p) for p in paths) and ctx.sys.exists("/etc/nginx/sites-enabled/ziira-app.conf"):
        ui.already("certificates and nginx sites exist: the port-80-only stage is skipped (no downtime on re-runs)")
        return
    files = nginxconf.all_files(ctx.cfg, nginx_options(ctx, https=False))
    ctx.sys.makedirs(nginxconf.LOG_DIR, owner="root", group="adm", mode=0o750)
    if apply_nginx(ctx, files):
        ui.ok("nginx serves our three hosts on port 80 (ACME challenge ready); other sites untouched")
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
           "--agree-tos", "-m", cfg.email, "--no-eff-email", "--expand", "--deploy-hook", "systemctl reload nginx"]
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
    sysm.manifest.note("lineages", lineage)
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
    if ctx.facts.get("mode") == "behind":
        ui.already("no certificates: TLS is the other proxy's job (see the snippets)")
        return
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
    # Renewal: reuse the timer or cron job that is already there; install our own (renewing ONLY our lineages) if none.
    timer = sysm.run(["systemctl", "list-unit-files", "certbot.timer"], probe=True, check=False)
    existing_cron = any(sysm.exists(f) for f in ("/etc/cron.d/certbot", "/etc/cron.daily/certbot"))
    if "certbot.timer" in timer.out:
        ui.already("certificate renewal: the existing certbot.timer is reused")
        if ctx.units_to_enable(["certbot.timer"]):
            ui.warn("certbot.timer exists but is not enabled/active: enable it yourself (it also renews other certificates): "
                    "systemctl enable --now certbot.timer")
    elif existing_cron:
        ui.already("certificate renewal: the existing certbot cron job is reused")
    else:
        service, tm = units.certbot_timer_fallback(list(cfg.lineages()))
        changed = sysm.write_text("/etc/systemd/system/ziira-certbot-renew.service", service)
        changed |= sysm.write_text("/etc/systemd/system/ziira-certbot-renew.timer", tm)
        if changed:
            sysm.run(["systemctl", "daemon-reload"])
        if ctx.units_to_enable(["ziira-certbot-renew.timer"]):
            sysm.run(["systemctl", "enable", "--now", "ziira-certbot-renew.timer"])
            ui.ok("no renewal timer existed: installed ziira-certbot-renew.timer (renews only our certificates)")
    if not issued:
        ui.already("automatic renewal (tested when the certificates were issued)")
        return
    failed = []
    for lineage in cfg.lineages():
        dry = sysm.run(["certbot", "renew", "--dry-run", "--non-interactive", "--cert-name", lineage], check=False, timeout=600,
                       desc=f"certbot renew --dry-run --cert-name {lineage} (proves renewal works)")
        if not dry.ok and not cfg.dry_run:
            failed.append(f"{lineage}: {(dry.out + dry.err).strip()[-300:]}")
    if failed:
        ui.warn("certbot renew --dry-run FAILED: our certificates will not renew by themselves until this is fixed:\n" + "\n".join(failed))
    else:
        ui.ok("certbot renew --dry-run succeeded for our certificates: automatic renewal works")


def https_works(ctx: Ctx) -> bool:
    """Every host answers over TLS with a certificate this machine trusts (so HSTS cannot lock anyone out)."""
    for host in ctx.cfg.hosts():
        r = ctx.sys.run(["curl", "-sS", "--max-time", "10", "-o", "/dev/null", "--resolve", f"{host}:443:127.0.0.1",
                         f"https://{host}/"], probe=True, check=False)
        if not r.ok:
            ctx.ui.info(f"HTTPS check for {host} failed: {r.err.strip()[-120:]}")
            return False
    return True


def ensure_default_cert(ctx: Ctx) -> None:
    """nginx older than 1.19.4 cannot refuse a TLS handshake, so the catch-all HTTPS server needs a (throwaway) certificate."""
    cfg, sysm = ctx.cfg, ctx.sys
    cert, key = f"{cfg.env_dir}/tls/default.crt", f"{cfg.env_dir}/tls/default.key"
    if sysm.exists(cert):
        return
    sysm.makedirs(f"{cfg.env_dir}/tls", mode=0o750, owner="root", group="root")
    sysm.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-keyout", key, "-out", cert,
              "-subj", "/CN=ziira-default-refuse"], desc="openssl: throwaway certificate for the catch-all server")
    sysm.run(["chmod", "600", key], check=False)


def step_nginx_tls(ctx: Ctx) -> None:
    cfg, ui = ctx.cfg, ctx.ui
    if ctx.facts.get("catch_all") and ctx.facts.get("mode") != "behind":
        v = nginxconf.parse_version(str(ctx.facts.get("nginx_version", "")))
        if v < (1, 19, 4):
            ensure_default_cert(ctx)
    if ctx.facts.get("mode") == "behind":
        ctx.sys.makedirs(nginxconf.LOG_DIR, owner="root", group="adm", mode=0o750)
        ctx.sys.makedirs(f"{cfg.state_dir}/nginx-tmp", mode=0o750, owner=cfg.service_user, group=cfg.service_user)
        if apply_nginx(ctx, nginxconf.all_files(cfg, nginx_options(ctx, https=True))):
            ui.ok(f"our own nginx serves the three hosts on 127.0.0.1:{cfg.ports} (plain HTTP, for your proxy to front)")
        else:
            ui.already("our nginx configuration")
        from installer import snippets
        snippets.write(ctx)
        return
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
    """Log rotation for our logs; firewall and fail2ban only as far as the owner allowed."""
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    sysm.makedirs("/var/log/ziira", mode=0o750, owner="root", group="adm")
    sysm.write_text("/etc/logrotate.d/ziira", units.logrotate_conf())
    if cfg.no_services:
        ui.already("firewall and fail2ban skipped (--no-services)")
        return
    inv = ctx.facts.get("inventory")
    ufw = getattr(inv, "ufw", None)
    if ufw is None:
        ufw = "absent"
        if sysm.which("ufw"):
            ufw = "active" if "Status: active" in sysm.run(["ufw", "status"], probe=True, check=False).out else "inactive"
    behind = ctx.facts.get("mode") == "behind"
    if ufw == "active":
        if behind:
            ui.already("firewall: ufw is active; nothing to add (behind mode listens on 127.0.0.1 only)")
        else:
            status = sysm.run(["ufw", "status"], probe=True, check=False).out
            added = [r for r in ("80/tcp", "443/tcp") if not re.search(rf"^{re.escape(r)}\s+ALLOW", status, re.M)]
            for r in added:
                sysm.run(["ufw", "allow", r], desc=f"ufw allow {r} (an added rule; nothing is reset or deleted)")
            if added:
                ui.ok("firewall: ufw is active, opened " + ", ".join(added) + " (existing rules and policies unchanged)")
            else:
                ui.already("firewall: ufw already allows 80 and 443")
    elif cfg.manage_firewall and not behind:
        port = ssh_port(ctx)
        if port is None:
            ui.warn("could not find the SSH port, so ufw was NOT enabled (it could lock you out)")
        elif ui.confirm(f"Enable ufw now with SSH ({port}), 80 and 443 allowed and everything else incoming denied? "
                        "This can block other services on this server.", default=cfg.yes):
            for r in (f"{port}/tcp", "80/tcp", "443/tcp"):
                sysm.run(["ufw", "allow", r])
            sysm.run(["ufw", "default", "deny", "incoming"])
            sysm.run(["ufw", "--force", "enable"], desc="ufw enable")
            ui.ok(f"ufw enabled: SSH ({port}), 80 and 443 allowed")
        else:
            ui.already("firewall untouched (not confirmed)")
    else:
        ui.already("firewall untouched (ufw is not active; --manage-firewall would enable it after a confirmation)")
    if inv is not None and (getattr(inv, "iptables_rules", 0) or getattr(inv, "nftables", False) or getattr(inv, "firewalld", False)):
        ui.warn("iptables/nftables/firewalld rules exist outside ufw and were not touched: check that ports 80 and 443 are open")
    # fail2ban: only when asked, in a file of our own, never replacing an existing jail
    if not cfg.fail2ban:
        ui.already("fail2ban untouched (--fail2ban would add a ziira-only jail)")
    elif sysm.write_text("/etc/fail2ban/jail.d/ziira-nginx.local", units.fail2ban_jail(cfg)):
        sysm.run(["systemctl", "enable", "--now", "fail2ban"], check=False)
        sysm.run(["systemctl", "reload", "fail2ban"], check=False, desc="reload fail2ban (picks up the new jail; others unchanged)")
        ui.ok("fail2ban: added the jail 'ziira-limit-req' in jail.d/ziira-nginx.local")
    else:
        ui.already("fail2ban jail")

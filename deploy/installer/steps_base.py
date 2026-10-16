"""Steps 1-4: preflight checks, system packages, Python, Node.js."""
from __future__ import annotations

import re

from installer import pgdetect
from installer.context import SUPPORTED_OS, Ctx
from installer.ui import StepFailed

PACKAGES = ["ca-certificates", "curl", "gnupg", "openssl", "git", "rsync", "xz-utils", "build-essential", "python3",
            "python3-venv", "python3-pip", "nginx", "certbot", "logrotate", "ufw"]
PYTHON_CANDIDATES = ["python3.14", "python3.13", "python3.12"]
NODE_MAJOR = 22
MIN_NODE = 20


def parse_os_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"')
    return out


def dns_advice(cfg_hosts: list[str], ip: str, problems: dict[str, list[str]]) -> str:
    lines = ["DNS does not point at this server yet. Create these records at your DNS provider, wait until they",
             "resolve (usually minutes), then run the installer again:", ""]
    for host in cfg_hosts:
        lines.append(f"    {host:<32} A    {ip or '<this server public IPv4>'}")
    lines.append("")
    for host, found in problems.items():
        lines.append(f"  {host}: " + (f"currently resolves to {', '.join(found)}" if found else "does not resolve"))
    lines.append("")
    lines.append("(Use --skip-dns-check only for staging or tests: certificates cannot be issued until DNS is right.)")
    return "\n".join(lines)


def step_preflight(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    ctx.need_root()
    osr = parse_os_release(sysm.read_text("/etc/os-release") or "")
    ident, version = osr.get("ID", "?"), osr.get("VERSION_ID", "?")
    ctx.facts.update(os_id=ident, os_version=version, codename=osr.get("VERSION_CODENAME", ""))
    if (ident, version) not in SUPPORTED_OS:
        msg = f"{osr.get('PRETTY_NAME', ident + ' ' + version)} is not supported (Ubuntu 22.04/24.04 or Debian 12)"
        if not cfg.allow_unsupported_os:
            raise StepFailed(msg, hint="Use a supported system, or accept the risk with --allow-unsupported-os.")
        ui.warn(msg + "; continuing because of --allow-unsupported-os")
    else:
        ui.already(f"operating system {osr.get('PRETTY_NAME', ident + ' ' + version)}")

    cpus, ram, disk = sysm.cpu_count(), sysm.ram_mb(), sysm.disk_free_mb(cfg.install_dir)
    ctx.facts.update(cpus=cpus, ram_mb=ram, disk_free_mb=disk)
    ui.info(f"{cpus} CPU(s), {ram} MB RAM, {disk // 1024} GB free")
    if ram and ram < 900 and not cfg.prebuilt:
        raise StepFailed(f"only {ram} MB of RAM: the web builds need about 1 GB",
                         hint="Add swap or RAM, or build elsewhere and use --prebuilt.")
    if ram and ram < 2048:
        ui.warn(f"{ram} MB of RAM is below the 2 GB recommended for the API, worker, PostgreSQL and builds together")
    if cpus < 2:
        ui.warn("1 CPU: fine for a pilot, slow for builds")
    if disk < 5 * 1024:
        raise StepFailed(f"only {disk // 1024} GB free; at least 5 GB are needed (10 GB recommended)")
    if disk < 10 * 1024:
        ui.warn(f"{disk // 1024} GB free; 10 GB or more is recommended (backups grow)")

    # ports 80 and 443: free, or already nginx
    listening = pgdetect.parse_listening(sysm.run(["ss", "-ltnpH"], probe=True, check=False).out)
    for port in (80, 443):
        owner = listening.get(port)
        if owner is None:
            continue
        if owner in ("nginx", ""):
            ui.already(f"port {port} is served by nginx" if owner else f"port {port} is in use (process unknown, assuming nginx)")
        else:
            raise StepFailed(f"port {port} is already used by '{owner}'",
                             hint=f"Stop or reconfigure {owner} (for example: systemctl disable --now {owner}), then run again.")
    ctx.facts["listening"] = {str(k): v for k, v in listening.items()}

    # DNS
    hosts = cfg.hosts()
    ip = cfg.public_ip
    if not ip and not cfg.skip_dns_check:
        for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
            r = sysm.run(["curl", "-4", "-fsS", "--max-time", "5", url], probe=True, check=False)
            if r.ok and re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", r.out.strip()):
                ip = r.out.strip()
                break
    ctx.facts["public_ip"] = ip
    if cfg.skip_dns_check:
        ui.warn("DNS check skipped (--skip-dns-check): certificates cannot be issued until the names point here")
        return
    if not ip:
        raise StepFailed("could not find this server's public IP address",
                         hint="Pass it with --public-ip A.B.C.D (or --skip-dns-check for tests).")
    wrong: dict[str, list[str]] = {}
    for host in hosts:
        v4, v6 = sysm.resolve(host)
        if ip not in v4:
            wrong[host] = v4
        if v6:
            ui.warn(f"{host} has an AAAA (IPv6) record {', '.join(v6)}: make sure this server answers on it, or remove it "
                    "(Let's Encrypt may use IPv6 and fail)")
    if wrong:
        message = dns_advice(hosts, ip, wrong)
        if cfg.dry_run:
            ui.warn("DNS is not ready (a real run would stop here before requesting certificates):\n" + message)
            return
        raise StepFailed("the domain names do not point at this server", hint=message)
    ui.already(f"DNS: {', '.join(hosts)} all resolve to {ip}")


def step_packages(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    wanted = list(PACKAGES)
    if not cfg.no_fail2ban:
        wanted.append("fail2ban")
    missing = ctx.apt_missing(wanted)
    if not missing:
        ui.already("system packages: " + ", ".join(wanted))
    else:
        sysm.run(["apt-get", "update"], env={"DEBIAN_FRONTEND": "noninteractive"}, desc="apt-get update")
        ctx.apt_install(missing)
        ui.ok("installed " + ", ".join(missing))
    # Brotli is optional: use it when the distribution packages it.
    r = sysm.run(["apt-cache", "policy", "libnginx-mod-http-brotli-filter"], probe=True, check=False)
    available = r.ok and "Candidate:" in r.out and "(none)" not in r.out
    have = bool(sysm.listdir("/etc/nginx/modules-enabled")) and any("brotli" in f for f in sysm.listdir("/etc/nginx/modules-enabled"))
    if available and not have and ctx.real_services:
        sysm.run(["apt-get", "install", "-y", "libnginx-mod-http-brotli-filter", "libnginx-mod-http-brotli-static"],
                 env={"DEBIAN_FRONTEND": "noninteractive"}, check=False, desc="install the nginx brotli module")
        have = any("brotli" in f for f in sysm.listdir("/etc/nginx/modules-enabled"))
    ctx.facts["brotli"] = have
    v = sysm.run(["nginx", "-v"], probe=True, check=False)
    ctx.facts["nginx_version"] = (v.err or v.out).strip()


def find_python(ctx: Ctx) -> str | None:
    for name in PYTHON_CANDIDATES + ["python3"]:
        path = ctx.sys.which(name)
        if not path:
            continue
        r = ctx.sys.run([path, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], probe=True, check=False)
        if r.ok:
            major, minor = (int(x) for x in r.out.strip().split("."))
            if (major, minor) >= (3, 12):
                return path
    # a Python installed by an earlier run of this installer (uv)
    for candidate in (f"{ctx.cfg.install_dir}/python/current/bin/python3",):
        if ctx.sys.exists(candidate):
            return candidate
    return None


def step_python(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    if cfg.no_services:
        ui.already("Python skipped (--no-services: no virtual environment is built)")
        return
    found = find_python(ctx)
    if found:
        ctx.facts["python"] = found
        ui.already(f"Python 3.12+ found at {found}")
        return
    # 1. the distribution's own python3.12 (Ubuntu 24.04 ships it; Debian 12 and Ubuntu 22.04 do not)
    r = sysm.run(["apt-cache", "policy", "python3.12"], probe=True, check=False)
    if r.ok and "Candidate:" in r.out and "(none)" not in r.out:
        ctx.apt_install(["python3.12", "python3.12-venv"])
        ctx.facts["python"] = "/usr/bin/python3.12"
        ui.ok("installed python3.12 from the distribution")
        return
    # 2. uv, installed from PyPI into a private virtual environment (no curl | sh), fetches a standalone Python
    tools = f"{cfg.install_dir}/tools"
    py_dir = f"{cfg.install_dir}/python"
    sysm.makedirs(cfg.install_dir)
    sysm.run(["python3", "-m", "venv", tools], desc=f"create {tools} (virtual environment for uv)")
    sysm.run([f"{tools}/bin/pip", "install", "--quiet", "--no-cache-dir", "uv"], timeout=900)
    sysm.run([f"{tools}/bin/uv", "python", "install", "3.12"], env={"UV_PYTHON_INSTALL_DIR": py_dir}, timeout=1800,
             desc="uv python install 3.12")
    found_uv = sysm.run([f"{tools}/bin/uv", "python", "find", "3.12"], env={"UV_PYTHON_INSTALL_DIR": py_dir},
                        probe=True, check=False)
    path = found_uv.out.strip()
    if not path and not cfg.dry_run:
        raise StepFailed("Python 3.12 or newer is required and could not be installed",
                         hint="This distribution has no python3.12 package and the standalone download failed. Install "
                              "Python 3.12+ yourself (or use Ubuntu 24.04), then run the installer again.")
    ctx.facts["python"] = path or f"{py_dir}/cpython-3.12/bin/python3"
    if path:
        sysm.symlink(f"{py_dir}/current", path.rsplit("/bin/", 1)[0])
    ui.ok(f"installed a standalone Python 3.12 with uv at {ctx.facts['python']}")


def node_ok(ctx: Ctx, path: str) -> bool:
    r = ctx.sys.run([path, "--version"], probe=True, check=False)
    m = re.match(r"v(\d+)\.", r.out.strip())
    return bool(r.ok and m and int(m.group(1)) >= MIN_NODE)


def step_node(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    if cfg.prebuilt or cfg.no_services:
        ui.already("Node.js not needed (--prebuilt or --no-services)")
        return
    for candidate in (f"{cfg.install_dir}/node/current/bin/node", sysm.which("node") or ""):
        if candidate and node_ok(ctx, candidate):
            ctx.facts["node_bin"] = candidate.rsplit("/", 1)[0]
            ui.already(f"Node.js {sysm.run([candidate, '--version'], probe=True, check=False).out.strip()} at {candidate}")
            return
    arch = {"x86_64": "x64", "aarch64": "arm64"}.get(sysm.run(["uname", "-m"], probe=True, check=False).out.strip(), "x64")
    base = f"https://nodejs.org/dist/latest-v{NODE_MAJOR}.x"
    sums = sysm.run(["curl", "-fsSL", "--max-time", "60", f"{base}/SHASUMS256.txt"], probe=True, check=False)
    line = next((ln for ln in sums.out.splitlines() if ln.endswith(f"-linux-{arch}.tar.xz")), "")
    if not line:
        if cfg.dry_run:
            ui.plan(f"download Node.js {NODE_MAJOR} (linux-{arch}) from nodejs.org, verify its SHA-256, unpack into {cfg.install_dir}/node")
            ctx.facts["node_bin"] = f"{cfg.install_dir}/node/current/bin"
            return
        raise StepFailed("could not read the Node.js release list from nodejs.org",
                         hint="Check the server's outbound HTTPS, or install Node.js 20+ yourself, or use --prebuilt.")
    digest, filename = line.split()
    version = filename.removeprefix("node-").split("-linux")[0]
    target = f"{cfg.install_dir}/node/{version}"
    tmp = f"/tmp/{filename}"
    sysm.run(["curl", "-fsSL", "--max-time", "600", "-o", tmp, f"{base}/{filename}"], desc=f"download {filename}")
    if not cfg.dry_run:
        actual = sysm.run(["sha256sum", tmp]).out.split()[0]
        if actual != digest:
            sysm.run(["rm", "-f", tmp], check=False)
            raise StepFailed(f"the downloaded Node.js archive does not match its published SHA-256 ({filename})")
    sysm.makedirs(target)
    sysm.run(["tar", "-xJf", tmp, "-C", target, "--strip-components=1"], desc=f"unpack Node.js into {target}")
    sysm.run(["rm", "-f", tmp], check=False)
    sysm.symlink(f"{cfg.install_dir}/node/current", target)
    ctx.facts["node_bin"] = f"{cfg.install_dir}/node/current/bin"
    ui.ok(f"installed Node.js {version} into {target}")

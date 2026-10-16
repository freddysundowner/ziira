"""Steps 1-4: preflight checks, system packages, Python, Node.js."""
from __future__ import annotations

import re

from installer.context import END_OF_LIFE, SUPPORTED_OS, Ctx
from installer.ui import StepFailed
from installer.util import removeprefix

PYTHON_CANDIDATES = ["python3.14", "python3.13", "python3.12"]
NODE_MAJOR = 20          # Node 20 LTS: officially supports glibc 2.31 (Ubuntu 20.04)
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
        if (ident, version) in END_OF_LIFE:
            ui.warn(f"{osr.get('PRETTY_NAME')} is past its standard support: Ziira works on it with a private Python and Node, "
                    "but plan to move to a supported release; other software on this server may not get security updates")

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
    """Install only the packages the plan found missing (no upgrade, no recommends, nothing removed)."""
    sysm, ui = ctx.sys, ctx.ui
    wanted = list(ctx.facts.get("packages", []))
    if not wanted:
        ui.already("system packages: everything needed is present")
    else:
        ui.info("installing (missing only, --no-install-recommends): " + ", ".join(wanted))
        sysm.run(["apt-get", "update"], env={"DEBIAN_FRONTEND": "noninteractive"}, desc="apt-get update (package lists only; no upgrade)")
        ctx.apt_install(wanted)
        sysm.manifest.note("packages", " ".join(wanted))
        ui.ok("installed " + ", ".join(wanted))
    if sysm.which("nginx"):
        v = sysm.run(["nginx", "-v"], probe=True, check=False)
        ctx.facts["nginx_version"] = (v.err or v.out).strip()


def system_python_ok(ctx: Ctx) -> str | None:
    """A system python 3.12+ that already exists (the system python3 itself is never changed or replaced)."""
    for name in PYTHON_CANDIDATES + ["python3"]:
        path = ctx.sys.which(name)
        if not path:
            continue
        r = ctx.sys.run([path, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], probe=True, check=False)
        if r.ok:
            major, minor = (int(x) for x in r.out.strip().split("."))
            if (major, minor) >= (3, 12):
                return path
    return None


def find_python(ctx: Ctx) -> str | None:
    found = system_python_ok(ctx)
    if found:
        return found
    # a private Python installed by an earlier run of this installer (uv)
    candidate = f"{ctx.cfg.install_dir}/python/current/bin/python3"
    return candidate if ctx.sys.exists(candidate) else None


def uv_archive(arch: str) -> str:
    return {"x86_64": "x86_64-unknown-linux-gnu", "aarch64": "aarch64-unknown-linux-gnu"}.get(arch, "x86_64-unknown-linux-gnu")


def install_uv(ctx: Ctx) -> str:
    """The official uv release binary, checked against its published SHA-256, in <install>/tools/uv. Returns its path."""
    cfg, sysm = ctx.cfg, ctx.sys
    target = f"{cfg.install_dir}/tools/uv"
    binary = f"{target}/uv"
    if sysm.exists(binary):
        return binary
    arch = uv_archive(sysm.run(["uname", "-m"], probe=True, check=False).out.strip())
    name = f"uv-{arch}.tar.gz"
    base = "https://github.com/astral-sh/uv/releases/latest/download"
    tmp = f"/tmp/ziira-{name}"
    sysm.run(["curl", "-fsSL", "--max-time", "300", "-o", tmp, f"{base}/{name}"], desc=f"download {name} (the official uv release)")
    sums = sysm.run(["curl", "-fsSL", "--max-time", "60", f"{base}/{name}.sha256"], probe=True, check=False)
    if not cfg.dry_run:
        expected = sums.out.split()[0] if sums.out.split() else ""
        actual = sysm.run(["sha256sum", tmp]).out.split()[0]
        if not expected or actual != expected:
            sysm.run(["rm", "-f", tmp], check=False)
            raise StepFailed("the downloaded uv archive does not match its published SHA-256; refusing to use it",
                             hint="Check the server's outbound HTTPS, or install Python 3.12+ yourself and run again.")
    sysm.makedirs(target)
    sysm.run(["tar", "-xzf", tmp, "-C", target, "--strip-components=1"], desc=f"unpack uv into {target}")
    sysm.run(["rm", "-f", tmp], check=False)
    return binary


def step_python(ctx: Ctx) -> None:
    """The application needs Python 3.12+. The system python3 is never touched: use an existing 3.12+ or a private one (uv)."""
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    if cfg.no_services:
        ui.already("Python skipped (--no-services: no virtual environment is built)")
        return
    found = find_python(ctx)
    if found:
        ctx.facts["python"] = found
        ui.already(f"Python 3.12+ found at {found}")
        return
    uv = install_uv(ctx)
    py_dir = f"{cfg.install_dir}/python"
    sysm.makedirs(py_dir)
    env = {"UV_PYTHON_INSTALL_DIR": py_dir, "UV_NO_CONFIG": "1"}
    sysm.run([uv, "python", "install", "3.12"], env=env, timeout=1800, desc="uv python install 3.12 (private; system python untouched)")
    path = sysm.run([uv, "python", "find", "3.12"], env=env, probe=True, check=False).out.strip()
    if not path and not cfg.dry_run:
        raise StepFailed("Python 3.12 could not be installed", hint="Check the server's outbound HTTPS (github.com), then run again.")
    ctx.facts["python"] = path or f"{py_dir}/cpython-3.12/bin/python3"
    if path:
        sysm.symlink(f"{py_dir}/current", path.rsplit("/bin/", 1)[0])
        probe = sysm.run([path, "-c", "import ssl, sqlite3, venv; print('ok')"], probe=True, check=False)
        if probe.out.strip() != "ok":
            raise StepFailed("the private Python 3.12 does not run on this system", hint=(probe.err or probe.out)[-400:])
    ui.ok(f"installed a private Python 3.12 at {ctx.facts['python']} (the system python3 was not touched)")


def node_ok(ctx: Ctx, path: str) -> bool:
    r = ctx.sys.run([path, "--version"], probe=True, check=False)
    m = re.match(r"v(\d+)\.", r.out.strip())
    return bool(r.ok and m and int(m.group(1)) >= MIN_NODE)


def step_node(ctx: Ctx) -> None:
    cfg, sysm, ui = ctx.cfg, ctx.sys, ctx.ui
    if cfg.prebuilt or cfg.no_services:
        ui.already("Node.js not needed (--prebuilt or --no-services)")
        return
    for candidate in (f"{cfg.install_dir}/tools/node/current/bin/node", sysm.which("node") or ""):
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
            ui.plan(f"download Node.js {NODE_MAJOR} (linux-{arch}) from nodejs.org, verify its SHA-256, "
                    f"unpack into {cfg.install_dir}/tools/node")
            ctx.facts["node_bin"] = f"{cfg.install_dir}/tools/node/current/bin"
            return
        raise StepFailed("could not read the Node.js release list from nodejs.org",
                         hint="Check the server's outbound HTTPS, or install Node.js 20+ yourself, or use --prebuilt.")
    digest, filename = line.split()
    version = removeprefix(filename, "node-").split("-linux")[0]
    target = f"{cfg.install_dir}/tools/node/{version}"
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
    sysm.symlink(f"{cfg.install_dir}/tools/node/current", target)
    ctx.facts["node_bin"] = f"{cfg.install_dir}/tools/node/current/bin"
    ui.ok(f"installed Node.js {version} into {target}")

"""What is already on this server (read-only), and what the installer would do about it.

`collect` only runs probes (nothing is changed). `report` prints it. `make_plan` turns the inventory and the answers into a
list of intended actions, warnings and CONFLICTS; a conflict stops the install before anything is changed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from installer import pgdetect, util
from installer.context import Ctx

WEB_SERVERS = {"nginx": "nginx", "apache2": "apache2", "httpd": "apache2", "caddy": "caddy", "traefik": "traefik",
               "haproxy": "haproxy", "docker-proxy": "docker-proxy", "envoy": "envoy", "lighttpd": "lighttpd"}
# systemd services that are part of the operating system, not "other apps"
SYSTEM_SERVICES = re.compile(r"^(systemd|dbus|cron|rsyslog|ssh|sshd|getty|serial-getty|networkd|network|polkit|snapd|"
                             r"unattended|multipathd|chrony|ntp|apparmor|ufw|irqbalance|udisks|packagekit|"
                             r"user@|user-runtime|accounts-daemon|ModemManager|qemu|cloud|open-vm|lxd|fwupd|"
                             r"thermald|lvm|plymouth|keyboard|console|apport|blk|kmod|ubuntu|motd|e2scrub)")


@dataclass
class Site:
    file: str
    names: list[str]
    listens: list[str]


@dataclass
class Listener:
    address: str
    port: int
    process: str


@dataclass
class Inventory:
    os_name: str = "?"
    cpus: int = 0
    ram_mb: int = 0
    ram_available_mb: int = 0
    disk_free_mb: int = 0
    listeners: list[Listener] = field(default_factory=list)
    web_servers: dict[str, str] = field(default_factory=dict)          # name -> installed / running
    nginx_sites: list[Site] = field(default_factory=list)
    certs: dict[str, list[str]] = field(default_factory=dict)          # lineage -> names
    ufw: str = "absent"                                                # absent | inactive | active
    iptables_rules: int = 0
    nftables: bool = False
    firewalld: bool = False
    fail2ban: str = "absent"                                           # absent | installed | active
    pg: pgdetect.PgFacts = field(default_factory=pgdetect.PgFacts)
    pg_databases: dict[int, list[str]] = field(default_factory=dict)   # port -> database names
    pg_roles: dict[int, list[str]] = field(default_factory=dict)
    pg_connections: dict[int, tuple[int, int]] = field(default_factory=dict)    # port -> (max_connections, in use)
    pythons: list[str] = field(default_factory=list)
    node: str = ""
    other_services: list[str] = field(default_factory=list)
    ssh_port: int | None = None
    user_state: str = "absent"                                         # absent | ours | foreign
    ziira_installed: bool = False

    def owner(self, port: int) -> str | None:
        for item in self.listeners:
            if item.port == port:
                return item.process or "unknown"
        return None

    def taken_ports(self) -> set[int]:
        return {item.port for item in self.listeners}


# --------------------------------------------------------------------------- parsing (pure)
def parse_ss(text: str) -> list[Listener]:
    """`ss -ltnpH` lines -> listeners."""
    out: list[Listener] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] != "LISTEN":
            continue
        address, _, port = parts[3].rpartition(":")
        if not port.isdigit():
            continue
        m = re.search(r'users:\(\("([^"]+)"', line)
        out.append(Listener(address.strip("[]"), int(port), m.group(1) if m else ""))
    return out


def parse_nginx_dump(text: str) -> list[Site]:
    """`nginx -T` output -> one Site per configuration file that declares a server_name."""
    sites: list[Site] = []
    for chunk in re.split(r"^# configuration file ", text, flags=re.M)[1:]:
        file, _, body = chunk.partition(":\n")
        body = re.sub(r"(?m)^\s*#.*$", "", body)
        names = [n for m in re.findall(r"\bserver_name\s+([^;]+);", body) for n in m.split()]
        if names:
            sites.append(Site(file.strip(), names, [m.strip() for m in re.findall(r"\blisten\s+([^;]+);", body)]))
    return sites


def parse_san(text: str) -> list[str]:
    return sorted(set(re.findall(r"DNS:([A-Za-z0-9.*-]+)", text)))


def count_iptables_rules(text: str) -> int:
    """Rules in `iptables -S` output beyond the policies, ignoring the chains ufw/docker maintain."""
    return sum(1 for ln in text.splitlines() if ln.startswith("-A ") and not re.match(r"-A (ufw-|DOCKER|FORWARD -j DOCKER)", ln))


def pick_port(taken: set[int], preferred: int, low: int, high: int) -> int:
    """`preferred` if free, otherwise the first free port in [low, high]."""
    if preferred not in taken:
        return preferred
    for port in [*range(preferred + 1, high + 1), *range(low, preferred)]:
        if port not in taken and low <= port <= high:
            return port
    raise ValueError(f"no free port between {low} and {high}")


# --------------------------------------------------------------------------- collection
def collect(ctx: Ctx) -> Inventory:
    from installer.steps_base import parse_os_release
    from installer.steps_pg import detect, psql_admin

    sysm, cfg = ctx.sys, ctx.cfg
    inv = Inventory()
    inv.os_name = parse_os_release(sysm.read_text("/etc/os-release") or "").get("PRETTY_NAME", "?")
    inv.cpus, inv.ram_mb, inv.disk_free_mb = sysm.cpu_count(), sysm.ram_mb(), sysm.disk_free_mb(cfg.install_dir)
    m = re.search(r"MemAvailable:\s+(\d+) kB", sysm.read_text("/proc/meminfo") or "")
    inv.ram_available_mb = int(m.group(1)) // 1024 if m else inv.ram_mb
    inv.listeners = parse_ss(sysm.run(["ss", "-ltnpH"], probe=True, check=False).out)
    inv.ziira_installed = sysm.exists(ctx.state_path)

    for binary, label in (("nginx", "nginx"), ("apache2", "apache2"), ("httpd", "apache2"), ("caddy", "caddy"),
                          ("traefik", "traefik"), ("haproxy", "haproxy")):
        if sysm.which(binary):
            active = sysm.run(["systemctl", "is-active", label if label != "apache2" else binary], probe=True, check=False).out.strip()
            inv.web_servers[label] = "running" if active == "active" else "installed"
    for item in inv.listeners:
        if item.process in WEB_SERVERS and WEB_SERVERS[item.process] not in inv.web_servers:
            inv.web_servers[WEB_SERVERS[item.process]] = "running"
    if "nginx" in inv.web_servers:
        inv.nginx_sites = parse_nginx_dump(sysm.run(["nginx", "-T"], probe=True, check=False).out)

    for name in sysm.listdir("/etc/letsencrypt/live"):
        cert = f"/etc/letsencrypt/live/{name}/fullchain.pem"
        if sysm.exists(cert):
            inv.certs[name] = parse_san(sysm.run(["openssl", "x509", "-in", cert, "-noout", "-text"], probe=True, check=False).out)

    if sysm.which("ufw"):
        inv.ufw = "active" if "Status: active" in sysm.run(["ufw", "status"], probe=True, check=False).out else "inactive"
    if sysm.which("iptables"):
        inv.iptables_rules = count_iptables_rules(sysm.run(["iptables", "-S"], probe=True, check=False).out)
    if sysm.which("nft"):
        inv.nftables = "table " in sysm.run(["nft", "list", "ruleset"], probe=True, check=False).out
    inv.firewalld = sysm.run(["systemctl", "is-active", "firewalld"], probe=True, check=False).out.strip() == "active"
    if sysm.which("fail2ban-client") or sysm.exists("/etc/fail2ban"):
        inv.fail2ban = "active" if sysm.run(["systemctl", "is-active", "fail2ban"], probe=True, check=False).out.strip() == "active" \
            else "installed"

    inv.pg = detect(ctx)
    for port in inv.pg.reachable:
        inv.pg_databases[port] = psql_admin(ctx, port, "select datname from pg_database where not datistemplate order by 1;",
                                            probe=True, check=False).out.split()
        inv.pg_roles[port] = psql_admin(ctx, port, "select rolname from pg_roles where rolname !~ '^pg_' order by 1;",
                                        probe=True, check=False).out.split()
        usage = psql_admin(ctx, port, "select current_setting('max_connections') || ' ' || count(*) from pg_stat_activity;",
                           probe=True, check=False).out.split()
        if len(usage) == 2 and all(x.isdigit() for x in usage):
            inv.pg_connections[port] = (int(usage[0]), int(usage[1]))

    for name in ("python3.10", "python3.11", "python3.12", "python3.13", "python3.14", "python3"):
        path = sysm.which(name)
        if path:
            r = sysm.run([path, "--version"], probe=True, check=False)
            inv.pythons.append(f"{path} ({(r.out or r.err).strip()})")
    if sysm.which("node"):
        inv.node = sysm.run(["node", "--version"], probe=True, check=False).out.strip()

    units = sysm.run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"], probe=True,
                     check=False).out
    for line in units.splitlines():
        unit = line.split()[0] if line.split() else ""
        base = util.removesuffix(unit, ".service")
        if base and not SYSTEM_SERVICES.match(base) and not base.startswith("ziira-") and not base.startswith("postgresql"):
            inv.other_services.append(base)
    sshd = sysm.run(["sshd", "-T"], probe=True, check=False).out
    pm = re.search(r"^port (\d+)$", sshd, re.M)
    inv.ssh_port = int(pm.group(1)) if pm else next((i.port for i in inv.listeners if i.process == "sshd"), None)

    passwd = sysm.run(["getent", "passwd", cfg.service_user], probe=True, check=False).out.strip()
    if passwd:
        fields = passwd.split(":")
        inv.user_state = "ours" if len(fields) > 5 and fields[5] == cfg.state_dir else "foreign"
    return inv


# --------------------------------------------------------------------------- report
def report(inv: Inventory) -> str:
    lines = ["WHAT IS ALREADY ON THIS SERVER (read-only inspection; nothing has been changed)", ""]
    lines.append(f"System        {inv.os_name}; {inv.cpus} CPU, {inv.ram_mb} MB RAM ({inv.ram_available_mb} MB available), "
             f"{inv.disk_free_mb // 1024} GB free; SSH port {inv.ssh_port or 'unknown'}")
    lines.append("Listening ports (local address, port, process):")
    for item in sorted(inv.listeners, key=lambda x: x.port):
        lines.append(f"  {item.address:<18} {item.port:<6} {item.process or '-'}")
    if not inv.listeners:
        lines.append("  (none)")
    lines.append("Web servers   " + (", ".join(f"{k} ({v})" for k, v in sorted(inv.web_servers.items())) or "none"))
    if inv.nginx_sites:
        lines.append("nginx sites already configured (never edited by the installer):")
        for site in inv.nginx_sites:
            lines.append(f"  {site.file}: {' '.join(site.names)}   listen {', '.join(site.listens) or '-'}")
    if inv.certs:
        lines.append("Certificates in /etc/letsencrypt (never touched):")
        for name, names in sorted(inv.certs.items()):
            lines.append(f"  {name}: {', '.join(names) or '-'}")
    lines.append(f"Firewall      ufw {inv.ufw}; iptables rules outside ufw/docker: {inv.iptables_rules}; nftables ruleset: "
             f"{'yes' if inv.nftables else 'no'}; firewalld: {'active' if inv.firewalld else 'no'}")
    lines.append(f"fail2ban      {inv.fail2ban}")
    if inv.pg.clusters or inv.pg.reachable or inv.pg.listening:
        lines.append("PostgreSQL:")
        for c in inv.pg.clusters:
            lines.append(f"  cluster {c.version}/{c.name} port {c.port} {c.status}")
        for port in sorted(inv.pg.reachable):
            used = inv.pg_connections.get(port)
            lines.append(f"  port {port}: PostgreSQL {inv.pg.reachable[port]}"
                     + (f", connections {used[1]}/{used[0]}" if used else ""))
            lines.append(f"    databases (names only): {', '.join(inv.pg_databases.get(port, [])) or '-'}")
            lines.append(f"    roles (names only):     {', '.join(inv.pg_roles.get(port, [])) or '-'}")
        for port in inv.pg.unreachable_ports:
            lines.append(f"  port {port}: answers, but the installer cannot log in as 'postgres' over the socket")
    else:
        lines.append("PostgreSQL    not installed")
    lines.append("Python        " + ("; ".join(inv.pythons) or "none"))
    lines.append("Node.js       " + (inv.node or "none"))
    lines.append("Other running services (may be other apps): " + (", ".join(inv.other_services[:25]) or "none"))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- plan
@dataclass
class Plan:
    mode: str = "join"                         # join | install-nginx | behind
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    api_port: int = 8000
    rebuild_port: int = 9001
    behind_port: int = 0
    catch_all: bool = False
    nginx_preexisting: bool = False


BASE_PACKAGES = ["ca-certificates", "curl", "rsync", "logrotate"]


def make_plan(ctx: Ctx, inv: Inventory) -> Plan:
    cfg = ctx.cfg
    plan = Plan()
    owner80, owner443 = inv.owner(80), inv.owner(443)
    foreign = [(p, o) for p, o in ((80, owner80), (443, owner443)) if o not in (None, "nginx")]
    state = ctx.existing_state()
    already_ours = bool(state)

    # --- who serves ports 80/443
    if cfg.behind:
        plan.mode = "behind"
        plan.behind_port = pick_port(inv.taken_ports(), cfg.ports or 8081, 8081, 8199) if not already_ours \
            else int(state.get("config", {}).get("ports") or cfg.ports or 8081)
        plan.actions.append(f"run OUR OWN nginx on 127.0.0.1:{plan.behind_port} (plain HTTP) as ziira-nginx.service; "
                            "no certificates are requested; ports 80/443 and the other proxy are not touched")
        plan.actions.append(f"write proxy snippets (nginx, Caddy, Apache, HAProxy, Traefik) to "
                            f"{cfg.snippet_dir or cfg.install_dir + '/proxy-snippets'} for you to adopt by hand")
    elif foreign:
        who = ", ".join(f"port {p} is used by '{o}'" for p, o in foreign)
        plan.conflicts.append(
            f"{who}. The installer will not stop or replace it, and will not install nginx on those ports.\n"
            "      Options: --proxy-mode snippet  (run Ziira behind that proxy on a local port and write its config snippets), or\n"
            "               --ports 8081          (the same, choosing the local port), or free the ports yourself.")
    else:
        installed_by_us = any("nginx" in pkgs.split() for pkgs in ctx.sys.manifest.extra.get("packages", []))
        others = [s for s in inv.nginx_sites if not s.file.rsplit("/", 1)[-1].startswith("ziira-")]
        plan.nginx_preexisting = "nginx" in inv.web_servers and not installed_by_us
        if "nginx" in inv.web_servers and not installed_by_us:
            plan.mode = "join"
            plan.actions.append("JOIN the existing nginx: add our own files only (sites-available/ziira-*.conf, snippets/ziira-*.conf, "
                                "conf.d/ziira-common.conf); no existing file is edited or deleted; reload (never restart) after nginx -t")
            plan.catch_all = False
        else:
            plan.mode = "install-nginx"
            plan.actions.append("install nginx (not present) and serve the three hosts on ports 80 and 443")
            plan.catch_all = not others

    # --- name clashes
    ours = set(cfg.hosts())
    for site in inv.nginx_sites:
        if not site.file.rsplit("/", 1)[-1].startswith("ziira-"):
            clash = sorted(ours & set(site.names))
            if clash:
                plan.conflicts.append(f"{', '.join(clash)} already served by nginx in {site.file}. Never reused or overwritten: "
                                      "use other host names or remove it from that site yourself.")
    for lineage, names in inv.certs.items():
        if not lineage.startswith("ziira-"):
            clash = sorted(ours & set(names))
            if clash:
                plan.conflicts.append(f"{', '.join(clash)} already covered by the certificate '{lineage}' (not ours; left alone). "
                                      "Choose other names, or let that certificate be handled by whoever owns it and use "
                                      "--proxy-mode snippet.")
    if inv.user_state == "foreign":
        plan.conflicts.append(f"a system user '{cfg.service_user}' already exists and is not Ziira's (its home is not "
                              f"{cfg.state_dir}). Pass --user NAME for another name.")

    # --- ports for our own processes
    taken = inv.taken_ports()
    if already_ours:
        plan.api_port = int(state.get("config", {}).get("api_port", cfg.api_port))
        plan.rebuild_port = int(state.get("config", {}).get("rebuild_port", cfg.rebuild_port))
    else:
        plan.api_port = pick_port(taken, cfg.api_port, 8000, 8099)
        plan.rebuild_port = pick_port(taken | {plan.api_port}, cfg.rebuild_port, 9001, 9099)
        if plan.api_port != cfg.api_port:
            plan.warnings.append(f"port {cfg.api_port} is taken; the API will use 127.0.0.1:{plan.api_port}")
    plan.actions.append(f"API on 127.0.0.1:{plan.api_port}, website rebuild receiver on 127.0.0.1:{plan.rebuild_port} "
                        "(never on 0.0.0.0)")

    # --- packages (only missing ones; no upgrade, no recommends)
    wanted = list(BASE_PACKAGES)
    if plan.mode == "install-nginx" or plan.mode == "behind" and not ctx.sys.which("nginx"):
        wanted.append("nginx")
    if plan.mode != "behind" and not cfg.self_signed:
        wanted.append("certbot")
    if any(("3.12" in p or "3.13" in p or "3.14" in p) for p in inv.pythons):
        wanted.append("python3-venv")             # only the system python 3.12+ needs it; a private python brings its own
    if not cfg.prebuilt:
        wanted.append("xz-utils")                 # to unpack the private Node.js tarball
    if cfg.repo:
        wanted.append("git")
    if cfg.manage_firewall:
        wanted.append("ufw")
    if cfg.fail2ban:
        wanted.append("fail2ban")
    plan.packages = ctx.apt_missing(wanted)
    listed = " ".join(plan.packages) if plan.packages else "(nothing: all present)"
    plan.actions.append(f"apt-get install --no-install-recommends {listed}   "
                        "[no apt upgrade, no package removed, no system python3/node change]")

    # --- python / node
    if not any(("3.12" in p or "3.13" in p or "3.14" in p) for p in inv.pythons):
        plan.actions.append("a private Python 3.12 is installed ALONGSIDE the system python3 (official uv binary, SHA-256 verified, under "
                            f"{cfg.install_dir}/tools and {cfg.install_dir}/python); the default python3 is not changed")
    if not cfg.prebuilt and not (inv.node and int(inv.node.lstrip("v").split(".")[0] or 0) >= 20):
        plan.actions.append(f"private Node.js 20 LTS (official tarball, SHA-256 verified) in {cfg.install_dir}/tools/node; "
                            "the system node is not touched; npm only without -g")

    # --- PostgreSQL
    pf = inv.pg
    good = {p: v for p, v in pf.reachable.items() if v >= pgdetect.MIN_MAJOR}
    if good:
        if cfg.pg_port and cfg.pg_port in good:
            port = cfg.pg_port
        elif len(good) > 1:
            plan.conflicts.append("several PostgreSQL servers run (ports " + ", ".join(map(str, sorted(good))) +
                                  "): choose one with --pg-port.")
            port = min(good)
        else:
            port = next(iter(good))
        plan.actions.append(f"PostgreSQL {good[port]} on port {port} is used as it is (no restart, no reload, no config change): "
                            f"create role '{cfg.db_role}' and databases '{cfg.master_db}', '{cfg.template_db}' and "
                            f"'{cfg.tenant_db_prefix}<business>'")
        existing_db, existing_roles = inv.pg_databases.get(port, []), inv.pg_roles.get(port, [])
        if not already_ours:
            for db in (cfg.master_db, cfg.template_db):
                if db in existing_db:
                    plan.conflicts.append(f"a database named '{db}' already exists on port {port} and is not ours. "
                                          "Pass --db-prefix with another prefix (for example zi_).")
            if cfg.db_role in existing_roles:
                plan.conflicts.append(f"a role named '{cfg.db_role}' already exists on port {port} and is not ours. "
                                      "Pass --db-prefix with another prefix.")
        usage = inv.pg_connections.get(port)
        if usage and usage[0] - usage[1] < 120:
            plan.warnings.append(f"PostgreSQL on port {port} has only {usage[0] - usage[1]} free connection slots "
                                 f"({usage[1]} of {usage[0]} in use); Ziira may need up to about 100. Raise max_connections "
                                 "yourself or use PgBouncer (docs/performance.md)")
    elif pf.unreachable_ports and not cfg.postgres_new_cluster:
        plan.conflicts.append("PostgreSQL answers on port " + ", ".join(map(str, pf.unreachable_ports)) +
                              " but the installer cannot log in as 'postgres' over the local socket (peer authentication). Fix that, "
                              "or pass "
                              "--postgres-new-cluster to leave every existing server alone and add a separate PostgreSQL 16 cluster "
                              "on a free port.")
    elif any(v < pgdetect.MIN_MAJOR for v in pf.reachable.values()) or any(c.version < pgdetect.MIN_MAJOR for c in pf.clusters):
        if cfg.postgres_new_cluster:
            plan.actions.append("an older PostgreSQL stays untouched; a NEW separate PostgreSQL 16 cluster 'ziira' is created on "
                                "another port (apt postgresql-16 from the official repository)")
        else:
            plan.conflicts.append("only PostgreSQL older than 16 is installed (never upgraded or reconfigured by the installer). "
                                  "Upgrade it yourself, or pass --postgres-new-cluster for a separate cluster on another port.")
    else:
        plan.actions.append("install PostgreSQL 16 (official apt repository, localhost only), then create the role and databases")

    # --- firewall / fail2ban
    if inv.ufw == "active":
        plan.actions.append("ufw is active: ADD allow rules for 80/tcp and 443/tcp if missing (no reset, no deletion, default "
                            "policies unchanged)" if plan.mode != "behind" else "ufw is active: no rule is added (behind mode)")
    elif cfg.manage_firewall:
        plan.actions.append("ufw is not active: ENABLE it with SSH, 80 and 443 allowed (you pass --manage-firewall and will be asked)")
    else:
        plan.actions.append("firewall: left alone (ufw is not active; pass --manage-firewall to let the installer enable it)")
    if inv.iptables_rules or inv.nftables or inv.firewalld:
        plan.warnings.append("iptables/nftables/firewalld rules exist outside ufw: they are not touched; make sure ports 80 and "
                             "443 are open in them if needed")
    if cfg.fail2ban:
        plan.actions.append("fail2ban: separate jail file /etc/fail2ban/jail.d/ziira-nginx.local (existing jails untouched; reload only)")

    # --- certificates
    if plan.mode != "behind":
        if cfg.self_signed:
            plan.actions.append("self-signed certificates under /etc/ziira/selfsigned (testing only)")
        else:
            plan.actions.append("certbot certonly (webroot) for ONLY our names, lineages " + ", ".join(cfg.lineages()) +
                                "; other certificates and their renewal are never touched; an existing renewal timer is reused")

    plan.actions.append(f"everything we add lives under {cfg.install_dir}, {cfg.env_dir}, {cfg.state_dir}, /var/log/ziira, "
                        f"{cfg.backup_dir}, {cfg.web_root}; systemd units ziira-*; every changed system file is recorded in "
                        "/var/lib/ziira/install-manifest.json (uninstall.sh undoes exactly that)")

    # --- resources
    if inv.ram_available_mb and inv.ram_available_mb < 1500 and not cfg.prebuilt:
        plan.warnings.append(f"only {inv.ram_available_mb} MB of RAM is available; the Node build is limited and run at low "
                             "priority, but consider --prebuilt (build elsewhere)")
    if inv.disk_free_mb and inv.disk_free_mb < 8 * 1024:
        plan.warnings.append(f"only {inv.disk_free_mb // 1024} GB of disk is free (8 GB or more is comfortable)")
    return plan


def plan_text(plan: Plan) -> str:
    lines = [f"PLAN (mode: {plan.mode}); the installer will:"]
    lines += [f"  + {a}" for a in plan.actions]
    if plan.warnings:
        lines += ["", "WARNINGS"] + [f"  ! {w}" for w in plan.warnings]
    if plan.conflicts:
        lines += ["", "CONFLICTS (nothing will be changed until these are resolved)"] + [f"  X {c}" for c in plan.conflicts]
    return "\n".join(lines) + "\n"

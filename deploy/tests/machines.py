"""Ready-made fake servers for the installer tests."""
from __future__ import annotations

from fakes import FakeSystem
from ui_helpers import quiet_ui  # noqa: F401  (re-exported for tests)

from installer.system import Result

OS_RELEASE = {
    "ubuntu24": 'PRETTY_NAME="Ubuntu 24.04 LTS"\nID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n',
    "ubuntu22": 'PRETTY_NAME="Ubuntu 22.04 LTS"\nID=ubuntu\nVERSION_ID="22.04"\nVERSION_CODENAME=jammy\n',
    "debian12": 'PRETTY_NAME="Debian GNU/Linux 12"\nID=debian\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\n',
    "fedora": 'PRETTY_NAME="Fedora Linux 40"\nID=fedora\nVERSION_ID="40"\n',
}
IP = "203.0.113.10"
HOSTS = ["example.org", "www.example.org", "app.example.org", "admin.example.org"]
PGDG_FPR = "fpr:::::::::B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8:"
SOURCE = "/src/ziira"


class Machine(FakeSystem):
    """A fake server. State that changes while the installer runs (roles, databases, installed packages) lives here."""

    def __init__(self, *, os_name: str = "ubuntu24", dry_run: bool = False, dns_ok: bool = True) -> None:
        super().__init__(dry_run=dry_run)
        self.files["/etc/os-release"] = OS_RELEASE[os_name]
        self.files["/proc/meminfo"] = "MemTotal:        8000000 kB\n"
        self.dirs |= {"/etc/logrotate.d", "/etc/systemd", "/etc/systemd/system", "/usr/local", "/usr/local/bin", "/var/lib", "/var/log",
                      "/var/www", "/var/backups", "/etc/fail2ban", "/etc/fail2ban/jail.d", "/etc/cron.d", "/etc/nginx", "/etc/nginx/sites-enabled", "/etc/nginx/sites-available", "/etc/nginx/conf.d", "/etc/nginx/snippets"}
        # the source checkout
        for f in ("pyproject.toml", "ziira/kernel/app.py", "deploy/installer/cli.py", "scripts/check_env.py", "frontend/dist/index.html",
                  "site/dist/index.html", "site/package-lock.json", "frontend/package.json"):
            self.files[f"{SOURCE}/{f}"] = "x"
        self.files[f"{SOURCE}/frontend/dist/index.html"] = "<html><script>var a=1</script><script src='/a.js'></script></html>"
        if dns_ok:
            for h in HOSTS:
                self.dns[h] = ([IP], [])
        self.installed: set[str] = set()
        self.pg_major: int | None = None            # a PostgreSQL that exists before the installer runs
        self.pg_installed_by_us = False
        self.roles: dict[str, str] = {}             # name -> password
        self.databases: set[str] = {"postgres", "template1"}
        self.certbot_fails = False
        self.programs |= {"runuser", "psql", "pg_isready", "df", "stat"}
        self.running_units = ""
        self.packages_present = False
        self.listening = ""
        self.clusters: list[tuple[int, str, int, str]] = []
        self.operators: list[tuple[str, str]] = []
        self.max_connections = 100
        self.connections_in_use = 5
        self.passwd: dict[str, str] = {}              # user -> home directory of users that already exist
        self.enabled: set[str] = set()
        self.ufw_on = False
        self.certbot_timer = False
        self.pg_port = 5432

    def preinstall_pg(self, major: int, port: int = 5432, status: str = "online", name: str = "main") -> None:
        """A PostgreSQL that is already on the server before the installer runs."""
        self.clusters.append((major, name, port, status))
        self.installed.add(f"postgresql-{major}")
        self.files[f"/usr/lib/postgresql/{major}/bin/pg_dump"] = "x"
        self.programs.add("pg_lsclusters")
        if status == "online":
            self.pg_major = major if self.pg_major is None or major > self.pg_major else self.pg_major
            self._listen(port)

    def _listen(self, port: int) -> None:
        self.listening += f'LISTEN 0 244 127.0.0.1:{port} 0.0.0.0:* users:(("postgres",pid=1,fd=5))\n'

    def _exec(self, argv, input, env, cwd, timeout):  # type: ignore[no-untyped-def]
        self.calls.append(list(argv))
        self.inputs.append(input)
        self._builtin(argv)
        for match, result in self.rules:                 # rules added by a test win over the machine's own behaviour
            if callable(match):
                if match(argv, input):
                    return result
            elif match in " ".join(argv) or (input and match in input):
                return result
        answer = self._answer(argv, input)
        return answer if answer is not None else Result()

    def _answer(self, argv: list[str], input: str | None) -> Result | None:
        j = " ".join(argv)
        if argv[0] == "dpkg-query":
            if "postgresql-[0-9]*" in j:
                return Result(0, "\n".join(sorted(self.installed)) + "\n" if self.installed else "")
            pkg = argv[-1]
            installed = pkg in self.installed or self.packages_present
            return Result(0 if installed else 1, "install ok installed" if installed else "")
        if argv[0] == "pg_lsclusters":
            return Result(0, "".join(f"{v} {n} {p} {st} postgres /var/lib/postgresql/{v}/{n} /log\n" for v, n, p, st in self.clusters))
        if argv[0] == "pg_dropcluster":
            gone = [c for c in self.clusters if (c[0], c[1]) == (int(argv[1]), argv[2])]
            self.clusters = [c for c in self.clusters if c not in gone]
            for c in gone:
                self.listening = "".join(ln + "\n" for ln in self.listening.splitlines() if f":{c[2]} " not in ln)
            return Result()
        if argv[0] == "pg_createcluster":
            self.clusters.append((int(argv[1]), argv[2], int(argv[argv.index("--port") + 1]), "online"))
            self.pg_major = int(argv[1])
            self._listen(int(argv[argv.index("--port") + 1]))
            return Result()
        if argv[0] == "pg_ctlcluster" and argv[3] == "start":
            self.clusters = [(v, n, p, "online" if (v, n) == (int(argv[1]), argv[2]) else st) for v, n, p, st in self.clusters]
            self.pg_major = int(argv[1])
            return Result()
        if argv[0] == "apt-get" and "install" in argv:
            if "nginx" in argv:
                self.programs.add("nginx")
            for a in argv:
                if a.startswith("postgresql-client-"):
                    self.files[f"/usr/lib/postgresql/{a.rsplit('-', 1)[1]}/bin/pg_dump"] = "x"
            if "postgresql-16" in argv:
                self.installed.add("postgresql-16")
                port = 5432
                while f":{port} " in self.listening:
                    port += 1
                self.clusters.append((16, "main", port, "online"))     # the Debian package creates a 'main' cluster
                self.pg_major = 16
                self._listen(port)
            self.packages_present = True
            return Result()
        if argv[0] == "apt-cache":
            return Result(0, "x:\n  Candidate: 3.12.3\n" if "python3.12" in j else "x:\n  Candidate: (none)\n")
        if "-c" in argv and "import ssl" in j:
            return Result(0, "ok\n")
        if "-c" in argv and "sys.version_info" in j:
            return Result(0, "3.12\n")
        if "discover" in j:
            return Result(0, "14\n")
        if argv[:2] == ["nginx", "-v"]:
            return Result(0, "", "nginx version: nginx/1.24.0 (Ubuntu)\n")
        if argv[0] == "curl" and "ipify" in j:
            return Result(0, IP)
        if argv[0] == "gpg":
            return Result(0, PGDG_FPR + "\n")
        if argv[0] == "ss":
            if "sport" in " ".join(argv):                                  # ss -ltnH 'sport = :5432'
                port = argv[-1].rsplit(":", 1)[-1]
                return Result(0, "".join(ln + "\n" for ln in self.listening.splitlines() if f":{port} " in ln))
            return Result(0, self.listening)
        if argv[0] == "runuser" and "psql" in argv:
            return self._psql(argv, input)
        if argv[0] == "psql":
            return self._login(argv)
        if argv[0] == "certbot" and "certonly" in argv:
            if self.certbot_fails:
                return Result(1, "", "Challenge failed: unauthorized, connection refused")
            name = argv[argv.index("--cert-name") + 1]
            sans = [argv[i + 1] for i, a in enumerate(argv) if a == "-d"]
            for f in ("fullchain.pem", "privkey.pem", "chain.pem"):
                self.files[f"/etc/letsencrypt/live/{name}/{f}"] = "SANS:" + ",".join(sans) + ("\nSTAGING" if "--staging" in argv else "")
            return Result()
        if argv[0] == "certbot" and "delete" in argv:
            name = argv[argv.index("--cert-name") + 1]
            for f in [f for f in self.files if f.startswith(f"/etc/letsencrypt/live/{name}/")]:
                del self.files[f]
            self.dirs.discard(f"/etc/letsencrypt/live/{name}")
            return Result()
        if argv[0] == "systemctl":
            return self._systemctl(argv)
        if argv[0] == "openssl":
            return self._openssl(argv)
        if argv[-2:] == ["operator", "list"] or (len(argv) > 2 and argv[-3:-1] == ["operator", "list"]):
            return Result(0, "".join(f"{e:<36} active    superadmin {n}\n" for e, n in self.operators))
        if "operator" in argv and "create" in argv:
            self.operators.append((argv[argv.index("create") + 2], argv[argv.index("create") + 1]))
            return Result()
        if argv[:2] == ["getent", "passwd"]:
            home = self.passwd.get(argv[2])
            return Result(0, f"{argv[2]}:x:999:999::{home}:/usr/sbin/nologin\n") if home else Result(2)
        if argv[:2] == ["systemctl", "list-units"]:
            return Result(0, self.running_units)
        if argv[0] == "useradd":
            self.passwd[argv[-1]] = argv[argv.index("--home-dir") + 1]
            self.users.add(argv[-1])
            return Result()
        if argv[0] == "sshd":
            return Result(0, "port 22\n")
        if argv[0] == "ufw" and argv[1] == "status":
            return Result(0, "Status: active\n22/tcp ALLOW Anywhere\n80/tcp ALLOW Anywhere\n443/tcp ALLOW Anywhere\n") \
                if self.ufw_on else Result(0, "Status: inactive\n")
        if argv[0] == "ufw" and "enable" in argv:
            self.ufw_on = True
            return Result()
        if argv[0] == "python3" and "check_env" in j:
            return Result(0, "WARN ZIIRA_REGISTRATION_MODE: open\n\n0 error(s), 1 warning(s)")
        return None

    def _systemctl(self, argv: list[str]) -> Result:
        sub = argv[1]
        names = [a for a in argv[2:] if a.endswith((".service", ".timer", ".path"))] + [a for a in argv[2:] if a == "nginx"]
        if sub == "enable":
            self.enabled |= set(names)
            return Result()
        if sub == "is-enabled":
            return Result(0, "enabled\n") if argv[-1] in self.enabled else Result(1, "disabled\n")
        if sub == "is-active":
            return Result(0, "active\n") if argv[-1] in self.enabled | {"nginx"} else Result(3, "inactive\n")
        if sub == "list-units":
            return Result(0, self.running_units)
        if sub == "list-unit-files":
            return Result(0, "certbot.timer enabled\n" if self.certbot_timer else "")
        return Result()

    def _openssl(self, argv: list[str]) -> Result:
        if argv[1] == "req":
            for flag in ("-keyout", "-out"):
                san = argv[argv.index("-addext") + 1].replace("subjectAltName=", "").replace("DNS:", "")
                self.files[argv[argv.index(flag) + 1]] = "SANS:" + san
            return Result()
        if argv[1] == "x509":
            path = argv[argv.index("-in") + 1]
            body = self.files.get(path, "")
            if "-text" in argv:
                sans = body.split("SANS:")[-1].split("\n")[0].split(",") if "SANS:" in body else []
                return Result(0, ", ".join(f"DNS:{s}" for s in sans))
            if "-issuer" in argv:
                return Result(0, "issuer=O = (STAGING) Let's Encrypt\n" if "STAGING" in body else "issuer=O = Let's Encrypt\n")
            return Result()                                # -checkend, -ocsp_uri ...
        return Result()

    # ---------------------------------------------------------------- PostgreSQL
    def _psql(self, argv: list[str], input: str | None) -> Result:
        sql = input or ""
        if "show server_version_num" in sql:
            return Result(0, f"{self.pg_major}0004\n") if self.pg_major else Result(2, "", "psql: could not connect")
        if "from pg_roles where rolname !~" in sql:
            return Result(0, "\n".join(["postgres", *sorted(self.roles)]) + "\n")
        if "from pg_roles where rolname" in sql and "rolcanlogin" in sql:
            return Result(0, "1110\n")
        if "from pg_roles" in sql:
            import re
            name = re.search(r"rolname = '([^']+)'", sql)
            return Result(0, "1\n" if name and name.group(1) in self.roles else "")
        if "not datistemplate" in sql:
            return Result(0, "\n".join(sorted(d for d in self.databases if d not in ("template1",))) + "\n")
        if "current_setting('max_connections')" in sql:
            return Result(0, f"{self.max_connections} {self.connections_in_use}\n")
        if "from pg_database" in sql:
            import re
            name = re.search(r"datname = '([^']+)'", sql)
            return Result(0, "1\n" if name and name.group(1) in self.databases else "")
        if sql.startswith("create role"):
            import re
            m = re.match(r'create role "([^"]+)".*password \'([^\']+)\'', sql)
            assert m
            self.roles[m.group(1)] = m.group(2)
            return Result()
        if sql.startswith("drop database"):
            import re
            self.databases.discard(re.match(r'drop database "([^"]+)"', sql).group(1))  # type: ignore[union-attr]
            return Result()
        if sql.startswith("drop role"):
            import re
            self.roles.pop(re.search(r'"([^"]+)"', sql).group(1), None)  # type: ignore[union-attr]
            return Result()
        if sql.startswith("create database"):
            import re
            self.databases.add(re.match(r'create database "([^"]+)"', sql).group(1))  # type: ignore[union-attr]
            return Result()
        return Result()

    def _login(self, argv: list[str]) -> Result:
        user = argv[argv.index("-U") + 1] if "-U" in argv else ""
        return Result(0, "1\n") if user in self.roles else Result(2, "", "FATAL: password authentication failed")


# --------------------------------------------------------------------------- servers that already run other things
NGINX_DUMP = """# configuration file /etc/nginx/nginx.conf:
user www-data;
http { include /etc/nginx/sites-enabled/*; gzip on; }
# configuration file /etc/nginx/sites-enabled/shop:
server { listen 80; listen 443 ssl; server_name shop.example.com www.shop.example.com; }
# configuration file /etc/nginx/sites-enabled/blog:
server { listen 80; server_name blog.example.net; }
# configuration file /etc/nginx/sites-enabled/default:
server { listen 80 default_server; server_name _; }
"""
OTHER_CONF = {
    "/etc/nginx/nginx.conf": "user www-data;\nhttp { include /etc/nginx/sites-enabled/*; gzip on; }\n",
    "/etc/nginx/sites-available/shop": "server { listen 80; listen 443 ssl; server_name shop.example.com; }\n",
    "/etc/nginx/sites-available/blog": "server { listen 80; server_name blog.example.net; }\n",
    "/etc/nginx/sites-available/default": "server { listen 80 default_server; server_name _; }\n",
}


def busy_server(**kw) -> Machine:  # type: ignore[no-untyped-def]
    """Ubuntu 24.04 that already runs nginx with two sites (+ the stock default), an app on 3000 and 8000, PostgreSQL 16
    with other people's databases and roles, a Let's Encrypt certificate for another name, and a running app service."""
    m = Machine(**kw)
    m.programs |= {"nginx", "python3.12", "node", "ufw"}
    for path, text in OTHER_CONF.items():
        m.files[path] = text
    for name in ("shop", "blog", "default"):
        m.links[f"/etc/nginx/sites-enabled/{name}"] = f"/etc/nginx/sites-available/{name}"
    m.dirs |= {"/etc/nginx/snippets", "/etc/letsencrypt", "/etc/letsencrypt/live", "/etc/letsencrypt/live/shop.example.com"}
    m.files["/etc/letsencrypt/live/shop.example.com/fullchain.pem"] = "SANS:shop.example.com,www.shop.example.com"
    m.on(lambda a, i: a[:2] == ["nginx", "-T"], out=NGINX_DUMP)
    m.on(lambda a, i: a[:2] == ["nginx", "-v"], err="nginx version: nginx/1.24.0 (Ubuntu)")
    m.on(lambda a, i: a[0].endswith("node") and "--version" in a, out="v22.14.0\n")
    m.on(lambda a, i: a[0].endswith("python3.12") and "--version" in a, out="Python 3.12.3\n")
    m.on(lambda a, i: a[:2] == ["systemctl", "is-active"] and a[-1] == "nginx", out="active\n")
    m.running_units = "shop-api.service loaded active running Shop API\nbackup-agent.service loaded active running agent\n"
    m.listening = ('LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1,fd=6))\n'
                   'LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1,fd=7))\n'
                   'LISTEN 0 511 127.0.0.1:3000 0.0.0.0:* users:(("node",pid=5,fd=3))\n'
                   'LISTEN 0 511 127.0.0.1:8000 0.0.0.0:* users:(("gunicorn",pid=6,fd=3))\n'
                   'LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=7,fd=3))\n')
    m.preinstall_pg(16)
    m.databases |= {"shopdb", "blogdb"}
    m.roles["shopuser"] = "their-password"
    return m


def snapshot(m: Machine) -> tuple[dict[str, str], dict[str, str], set[str]]:
    return dict(m.files), dict(m.links), set(m.dirs)

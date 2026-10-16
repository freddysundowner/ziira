"""Finding out what PostgreSQL is already on the machine, and deciding what to do about it (pure functions)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_MAJOR = 16


@dataclass(frozen=True)
class Cluster:
    version: int
    name: str
    port: int
    status: str             # online | down | ...


@dataclass
class PgFacts:
    clusters: list[Cluster] = field(default_factory=list)
    listening: dict[int, str] = field(default_factory=dict)       # port -> process name ("" when unknown)
    reachable: dict[int, int] = field(default_factory=dict)       # port -> server major (peer login as postgres worked)
    unreachable_ports: list[int] = field(default_factory=list)    # something answers on the port but the login failed
    packages: list[int] = field(default_factory=list)             # installed postgresql-NN server packages


@dataclass(frozen=True)
class PgPlan:
    action: str        # use_existing | start_then_use | install_new | new_cluster | stop_too_old | stop_unreachable
    port: int = 0
    major: int = 0
    cluster: Cluster | None = None
    message: str = ""


def parse_lsclusters(text: str) -> list[Cluster]:
    """`pg_lsclusters --no-header`: '16  main  5432 online postgres /var/lib/postgresql/16/main ...'."""
    out: list[Cluster] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].isdigit() and parts[2].isdigit():
            out.append(Cluster(int(parts[0]), parts[1], int(parts[2]), parts[3]))
    return out


def parse_listening(text: str) -> dict[int, str]:
    """`ss -ltnpH`: 'LISTEN 0 244 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=1,fd=5))' -> {5432: 'postgres'}."""
    out: dict[int, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] != "LISTEN":
            continue
        local = parts[3]
        port = local.rsplit(":", 1)[-1]
        if not port.isdigit():
            continue
        m = re.search(r'users:\(\("([^"]+)"', line)
        out.setdefault(int(port), m.group(1) if m else "")
    return out


def parse_version_num(text: str) -> int:
    """`show server_version_num` (160004) -> major 16."""
    return int(text.strip()) // 10000


def free_port(listening: dict[int, str], start: int = 5432) -> int:
    port = start
    while port in listening:
        port += 1
    return port


def classify(facts: PgFacts, *, allow_new_cluster: bool) -> PgPlan:
    """What to do about PostgreSQL. Never touches a server that is already there."""
    good = sorted((p for p, major in facts.reachable.items() if major >= MIN_MAJOR),
                  key=lambda p: (p != 5432, p))
    if good:
        port = good[0]
        return PgPlan("use_existing", port, facts.reachable[port],
                      message=f"PostgreSQL {facts.reachable[port]} is already running on port {port}: it is left as it is; "
                              "only the Ziira role and databases are created")
    if facts.unreachable_ports and not allow_new_cluster:
        ports = ", ".join(str(p) for p in sorted(facts.unreachable_ports))
        return PgPlan("stop_unreachable", message=(
            f"Something answers on port {ports}, but the installer could not log in as the 'postgres' operating-system "
            "user over the local socket (peer authentication), so it cannot create the Ziira role and databases. "
            "Options: allow peer login for postgres in pg_hba.conf, or create the role and databases yourself "
            "(docs/installation.md, 'PostgreSQL'), or pass --postgres-new-cluster to leave every existing server alone "
            "and add a separate PostgreSQL 16 cluster on a free port."))
    down_good = [c for c in facts.clusters if c.version >= MIN_MAJOR and c.status != "online"]
    if down_good:
        c = sorted(down_good, key=lambda c: (c.port != 5432, c.port))[0]
        return PgPlan("start_then_use", c.port, c.version, c,
                      f"PostgreSQL {c.version} cluster '{c.name}' exists but is not running: it will be started (nothing else changed)")
    old = sorted({c.version for c in facts.clusters if c.version < MIN_MAJOR}
                 | {v for v in facts.reachable.values() if v < MIN_MAJOR})
    if old:
        listing = ", ".join(str(v) for v in old)
        if not allow_new_cluster:
            return PgPlan("stop_too_old", message=(
                f"PostgreSQL {listing} is installed, but Ziira needs {MIN_MAJOR} or newer, and an existing server is never "
                "upgraded or reconfigured by the installer. Safe options:\n"
                f"  1. upgrade that server to {MIN_MAJOR}+ yourself (pg_upgradecluster), then run this again; or\n"
                f"  2. run this again with --postgres-new-cluster: the installer adds a separate PostgreSQL {MIN_MAJOR} "
                "cluster on another port and leaves the old one alone."))
        port = free_port(facts.listening, 5433)
        return PgPlan("new_cluster", port, MIN_MAJOR,
                      message=f"PostgreSQL {listing} is left alone; a new {MIN_MAJOR} cluster 'ziira' is created on port {port}")
    port = 5432 if 5432 not in facts.listening else free_port(facts.listening, 5433)
    return PgPlan("install_new", port, MIN_MAJOR, message=f"PostgreSQL {MIN_MAJOR} is not installed: it will be installed "
                                                          f"from the official PostgreSQL apt repository (port {port}, localhost only)")

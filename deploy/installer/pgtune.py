"""PostgreSQL settings for a cluster the installer creates, as data computed from the machine's RAM."""
from __future__ import annotations


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def tuning(ram_mb: int) -> dict[str, str]:
    """Conservative values for a server shared with the API, worker and nginx (so PostgreSQL gets about a quarter).

    max_connections: every cached tenant database keeps a small pool per API worker, so 200 (300 above 8 GB).
    """
    max_conn = 300 if ram_mb >= 8192 else 200
    shared = clamp(ram_mb // 4, 128, 8192)
    work_mem = clamp((ram_mb - shared) // (max_conn * 4), 4, 64)
    return {
        "listen_addresses": "'localhost'",
        "max_connections": str(max_conn),
        "shared_buffers": f"{shared}MB",
        "effective_cache_size": f"{clamp(ram_mb * 3 // 4, 256, 49152)}MB",
        "maintenance_work_mem": f"{clamp(ram_mb // 16, 64, 1024)}MB",
        "work_mem": f"{work_mem}MB",
        "wal_compression": "on",
        "checkpoint_completion_target": "0.9",
        "random_page_cost": "1.1",
        "password_encryption": "scram-sha-256",
        "log_min_duration_statement": "1000",
        "log_checkpoints": "on",
    }


def conf_text(ram_mb: int) -> str:
    lines = ["# Written by the Ziira installer for a cluster it created. Sized from "
             f"{ram_mb} MB of RAM; edit freely, the installer never rewrites it."]
    lines += [f"{k} = {v}" for k, v in tuning(ram_mb).items()]
    return "\n".join(lines) + "\n"

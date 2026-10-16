"""Small pure helpers: secrets, quoting, validation, sizes."""
from __future__ import annotations

import ipaddress
import re
import secrets
from urllib.parse import quote

HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
EMAIL = re.compile(r"^[^@\s'\"\\]+@[^@\s'\"\\]+\.[^@\s'\"\\]+$")


LOW_PRIORITY = ["nice", "-n", "10", "ionice", "-c3"]


def niced(argv: list[str]) -> list[str]:
    """Run a heavy command at low CPU and disk priority so other software on a shared server is not starved."""
    return [*LOW_PRIORITY, *argv]


def node_memory_mb(available_mb: int) -> int:
    """Heap limit for the Node build: half of the free RAM, between 512 MB and 1536 MB."""
    return max(512, min(1536, available_mb // 2)) if available_mb else 1536


def removeprefix(text: str, prefix: str) -> str:
    """str.removeprefix is Python 3.9+; the installer must run on 3.8."""
    return text[len(prefix):] if prefix and text.startswith(prefix) else text


def removesuffix(text: str, suffix: str) -> str:
    return text[: -len(suffix)] if suffix and text.endswith(suffix) else text


def new_secret(nbytes: int = 48) -> str:
    """A URL-safe random secret (64 characters for the default)."""
    return secrets.token_urlsafe(nbytes)


def new_password() -> str:
    """A database password: 32 URL-safe characters."""
    return secrets.token_urlsafe(24)


def valid_hostname(value: str) -> bool:
    return bool(HOSTNAME.match(value))


def valid_email(value: str) -> bool:
    return bool(EMAIL.match(value))


def valid_ident(value: str) -> bool:
    """A PostgreSQL role or database name we are willing to put inside double quotes."""
    return bool(IDENT.match(value))


def sql_literal(value: str) -> str:
    """A string as an SQL literal (standard_conforming_strings is on in every supported PostgreSQL)."""
    if "\x00" in value:
        raise ValueError("NUL character in SQL literal")
    return "'" + value.replace("'", "''") + "'"


def sql_ident(value: str) -> str:
    if not valid_ident(value):
        raise ValueError(f"not a safe SQL identifier: {value!r}")
    return '"' + value + '"'


def database_url(user: str, password: str, host: str, port: int, database: str) -> str:
    """A SQLAlchemy/psycopg URL with every part quoted."""
    return f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(database, safe='')}"


def parse_cidrs(text: str) -> list[str]:
    """Comma separated CIDRs -> normalised list. Raises ValueError naming the bad entry."""
    out: list[str] = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(str(ipaddress.ip_network(item, strict=False)))
        except ValueError:
            raise ValueError(f"'{item}' is not a network such as 203.0.113.0/24") from None
    return out


def parse_size_mb(text: str) -> int:
    """'16G' / '512M' / '2048' (MB) -> megabytes."""
    m = re.fullmatch(r"(\d+)\s*([kKmMgG]?)[bB]?", text.strip())
    if not m:
        raise ValueError(text)
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"k": n // 1024, "m": n, "g": n * 1024, "": n}[unit]

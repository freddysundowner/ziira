"""Small pure helpers: secrets, quoting, validation, sizes."""
from __future__ import annotations

import ipaddress
import re
import secrets
from urllib.parse import quote

HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
EMAIL = re.compile(r"^[^@\s'\"\\]+@[^@\s'\"\\]+\.[^@\s'\"\\]+$")


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

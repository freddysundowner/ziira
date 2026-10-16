"""Reading, merging and writing /etc/ziira/ziira.env.

Every value is written in single quotes: systemd's EnvironmentFile, `. file` in bash and scripts/check_env.py all read
that the same way, and nothing inside is expanded. (A value must therefore not contain a single quote or a newline.)
"""
from __future__ import annotations

import re

SECRET_NAME = re.compile(r"(KEY|SECRET|PASSWORD|TOKEN)", re.I)
URL_WITH_PASSWORD = re.compile(r"://[^/@\s:]+:[^@\s]+@")
HEADER = ("# Ziira production configuration. Written by deploy/install.sh; safe to edit.\n"
          "# Mode 0640 root:{group}. Back up ZIIRA_CREDENTIALS_KEY offline: without it every business is locked out.\n")


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip().removeprefix("export ").strip()] = value
    return out


def quote(value: str) -> str:
    if "'" in value or "\n" in value or "\r" in value:
        raise ValueError("an environment value cannot contain a single quote or a line break")
    return f"'{value}'"


def render(values: dict[str, str], group: str = "ziira", comments: dict[str, str] | None = None) -> str:
    """The file text, keys sorted into sections by prefix of meaning (kept stable so diffs are readable)."""
    lines = [HEADER.format(group=group).rstrip("\n")]
    for key in sorted(values):
        if comments and key in comments:
            lines.append(f"# {comments[key]}")
        lines.append(f"{key}={quote(values[key])}")
    return "\n".join(lines) + "\n"


def mask(key: str, value: str) -> str:
    """A value that is safe to print."""
    if SECRET_NAME.search(key) or URL_WITH_PASSWORD.search(value):
        return "[hidden]"
    return value


def merge(existing: dict[str, str], wanted: dict[str, str]) -> tuple[dict[str, str], list[str], list[str]]:
    """Add the keys the file lacks; never overwrite one that is there.

    Returns (merged, added keys, differing keys): `differing` are keys present with another value than the installer
    would write now. They are reported (values masked) and left alone, so an edit by hand is never lost.
    """
    merged = dict(existing)
    added = [k for k in sorted(wanted) if k not in existing]
    for k in added:
        merged[k] = wanted[k]
    differing = [k for k in sorted(wanted) if k in existing and existing[k] != wanted[k]]
    return merged, added, differing


def diff_lines(existing: dict[str, str], wanted: dict[str, str], differing: list[str]) -> list[str]:
    out: list[str] = []
    for k in differing:
        if SECRET_NAME.search(k) or URL_WITH_PASSWORD.search(existing[k] + wanted[k]):
            out.append(f"{k}: differs from what the installer would set (value hidden); kept as it is")
        else:
            out.append(f"{k}: file has '{existing[k]}', installer would set '{wanted[k]}'; kept as it is")
    return out

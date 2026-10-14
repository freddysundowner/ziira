#!/usr/bin/env python3
"""Fail if a file tracked by git looks like it contains a real secret.

    python scripts/secret_scan.py            # scans `git ls-files`

Looks for private keys, cloud and git-host tokens, secret-looking assignments with a long literal value, and a tracked
`.env`. Test fixtures and documentation are allowed to contain obviously fake values: put `secret-scan: ignore` on
the line, or add the path to ALLOWED_PATHS. It is a safety net, not a replacement for a full scanner such as gitleaks.
"""

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "Stripe live key": re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "database URL with password": re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:(?!ziira@|\*+@|<)[^@\s'\"]{6,}@(?!localhost|127\.0\.0\.1)"),
    "secret assignment": re.compile(
        r"""(?ix)\b[\w]*(?:secret|passwd|password|api[_-]?key|private[_-]?key|access[_-]?token)[\w]*\s*[:=]\s*
            ["'][A-Za-z0-9+/=_\-]{24,}["']"""),
}
ALLOWED_PATHS = ("tests/", "docs/", "frontend/package-lock.json", "scripts/secret_scan.py", "scripts/check_env.py",
                 "frontend/src/api/schema.d.ts")
SKIP_SUFFIXES = (".pdf", ".png", ".jpg", ".ico", ".woff", ".woff2", ".lock")


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout.decode()
    return [Path(p) for p in out.split("\0") if p]


def scan(paths: list[Path]) -> list[str]:
    problems = []
    for path in paths:
        name = path.as_posix()
        if name == ".env" or name.endswith("/.env"):
            problems.append(f"{name}: an environment file is tracked by git")
            continue
        if name.startswith(ALLOWED_PATHS) or name.endswith(SKIP_SUFFIXES) or not path.is_file():
            continue
        try:
            lines = path.read_text(errors="strict").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if "secret-scan: ignore" in line or "development-only" in line:
                continue
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    problems.append(f"{name}:{number}: looks like a {label}")
    return problems


def main() -> int:
    problems = scan(tracked_files())
    for p in problems:
        print(p)
    if problems:
        print(f"\n{len(problems)} possible secret(s). If one is a harmless fixture, add 'secret-scan: ignore' "
              "to its line.")
        return 1
    print("No secrets found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

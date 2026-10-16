#!/usr/bin/env bash
# Ziira production installer (bootstrap). Checks root and the operating system, makes sure a Python 3.10+ exists for the
# installer itself, then hands over to the Python installer in deploy/installer (standard library only).
#
#   sudo bash deploy/install.sh                      # asks for what it needs
#   sudo bash deploy/install.sh --dry-run ...        # prints the plan, changes nothing
#   sudo bash deploy/install.sh --help
#
# Safe to run again: every step checks the machine first and reports "already" when there is nothing to do.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { printf '\n\033[1;31mStopped: %s\033[0m\n' "$1" >&2; exit 1; }

wants_help=0
for arg in "$@"; do
  case "$arg" in -h|--help|--version|--list-steps|--dry-run|--inspect) wants_help=1 ;; esac
done

if [ "$(id -u)" -ne 0 ] && [ "$wants_help" -eq 0 ]; then
  die "run as root:  sudo bash deploy/install.sh"
fi

if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:20.04|ubuntu:22.04|ubuntu:24.04|debian:12) ;;
    *) if [[ " $* " != *" --allow-unsupported-os "* ]]; then
         printf '\033[1;33mWarning: %s is not a tested system (Ubuntu 20.04/22.04/24.04, Debian 12).\033[0m\n' "${PRETTY_NAME:-unknown}" >&2
       fi ;;
  esac
fi

# The installer itself needs only a python3 of version 3.8 or newer (Ubuntu 20.04 ships 3.8). It never installs or replaces a
# system python: the application gets its own private Python 3.12 later, if the system one is older.
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    PY="$(command -v "$candidate")"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then
    die "python3 is $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo unknown) but the installer needs 3.8 or newer. Nothing was changed. Install a newer python3 yourself (for example: apt install python3.8), then run this again; the application's own Python 3.12 is installed separately and privately."
  fi
  die "python3 is not installed. Nothing was changed. Install it yourself (apt install python3), then run this again. The installer never installs or replaces the system python."
fi

cd "$HERE"
exec "$PY" -m installer "$@"

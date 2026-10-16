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
  case "$arg" in -h|--help|--version|--list-steps|--dry-run) wants_help=1 ;; esac
done

if [ "$(id -u)" -ne 0 ] && [ "$wants_help" -eq 0 ]; then
  die "run as root:  sudo bash deploy/install.sh"
fi

if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:22.04|ubuntu:24.04|debian:12) ;;
    *) if [[ " $* " != *" --allow-unsupported-os "* ]]; then
         printf '\033[1;33mWarning: %s is not a tested system (Ubuntu 22.04/24.04, Debian 12).\033[0m\n' "${PRETTY_NAME:-unknown}" >&2
       fi ;;
  esac
fi

PY=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$(command -v "$candidate")"; break
  fi
done
if [ -z "$PY" ]; then
  [ "$(id -u)" -eq 0 ] || die "python3 (3.10 or newer) is needed to run the installer"
  echo "Installing python3 for the installer ..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq python3 python3-venv >/dev/null
  PY="$(command -v python3)" || die "could not install python3"
fi

cd "$HERE"
exec "$PY" -m installer "$@"

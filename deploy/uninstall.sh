#!/usr/bin/env bash
# Remove services, timers and nginx sites (databases are kept unless --purge-data, which asks twice).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo bash deploy/uninstall.sh" >&2; exit 1; }
cd "$HERE"
exec /usr/bin/env python3 -m installer.uninstall "$@"

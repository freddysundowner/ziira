#!/usr/bin/env bash
# Deploy a newer version (with a master-database backup first and automatic rollback of the code).
#   sudo bash deploy/update.sh --from-dir /path/to/new/checkout
#   sudo bash deploy/update.sh --repo URL --branch main
#   sudo bash deploy/update.sh --rollback
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo bash deploy/update.sh ..." >&2; exit 1; }
cd "$HERE"
exec /usr/bin/env python3 -m installer.update "$@"

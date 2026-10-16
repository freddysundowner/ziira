#!/usr/bin/env bash
# Take a backup right now (the same as the nightly timer): master database and every business, into the backup folder.
#   sudo bash deploy/backup-now.sh [--tenant CODE]
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo bash deploy/backup-now.sh" >&2; exit 1; }
if command -v ziira-backup-now >/dev/null 2>&1; then
  exec ziira-backup-now "$@"
fi
echo "ziira-backup-now is not installed: run deploy/install.sh first" >&2
exit 1

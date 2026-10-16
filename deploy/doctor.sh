#!/usr/bin/env bash
# Health report: DNS, ports, certificates, nginx, services, database, disk, backups, readiness, configuration.
# Exit code: 0 all good, 1 warnings, 2 failures. After installing, the same thing is available as `sudo ziira-doctor`.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
exec /usr/bin/env python3 -m installer.doctor "$@"

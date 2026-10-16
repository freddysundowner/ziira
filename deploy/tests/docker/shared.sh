#!/usr/bin/env bash
# The "server that already runs other things" test: a systemd container that ALREADY runs nginx with two unrelated sites and
# PostgreSQL with unrelated databases. After the install the unrelated sites and databases must be byte-for-byte unchanged and
# still answering (and nginx/PostgreSQL never restarted); after the uninstall the container is back to its original state.
#   bash deploy/tests/docker/shared.sh [image]        default: jrei/systemd-ubuntu:24.04 (systemd + Ubuntu 24.04)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
IMAGE="${1:-jrei/systemd-ubuntu:24.04}"
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 || { echo "Docker is not running: skipping the shared-server test" >&2; exit 0; }
[ -f "$ROOT/frontend/dist/index.html" ] && [ -f "$ROOT/site/dist/index.html" ] || {
  echo "frontend/dist and site/dist are needed (make web-check, make site-build): skipping the shared-server test" >&2; exit 0; }
NAME="ziira-shared-test"
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw -v "$ROOT":/src:ro "$IMAGE" >/dev/null || exit 1
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
for _ in $(seq 1 30); do docker exec "$NAME" systemctl is-system-running 2>/dev/null | grep -qE "running|degraded" && break; sleep 1; done
docker exec "$NAME" bash /src/deploy/tests/docker/shared_inside.sh

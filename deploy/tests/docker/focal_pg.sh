#!/usr/bin/env bash
# The riskiest path on Ubuntu 20.04, for real: PostgreSQL 12 already running on 5432 and something else on 5433,
# `--postgres-new-cluster` adds a separate PostgreSQL 16 cluster from the PGDG archive and leaves the 12 cluster untouched.
# Also runs the private Python 3.12 (uv) and the private Node on glibc 2.31 and checks the certbot 0.40 command line.
#   bash deploy/tests/docker/focal_pg.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 || { echo "Docker is not running: skipping" >&2; exit 0; }
NAME="ziira-focal-pg"
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw -v "$ROOT":/src:ro jrei/systemd-ubuntu:20.04 >/dev/null || exit 1
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
for _ in $(seq 1 30); do docker exec "$NAME" systemctl is-system-running 2>/dev/null | grep -qE "running|degraded" && break; sleep 1; done
docker exec "$NAME" bash /src/deploy/tests/docker/focal_pg_inside.sh

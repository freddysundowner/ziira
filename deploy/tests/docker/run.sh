#!/usr/bin/env bash
# Build the throwaway image and run the config-only installer test inside it.  Needs Docker; never touches this machine.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
command -v docker >/dev/null 2>&1 || { echo "Docker is not installed: skipping the container test" >&2; exit 0; }
docker info >/dev/null 2>&1 || { echo "Docker is not running: skipping the container test" >&2; exit 0; }
docker build -q -t ziira-installer-test "$HERE" >/dev/null
exec docker run --rm -v "$ROOT":/src:ro ziira-installer-test bash /src/deploy/tests/docker/inside.sh

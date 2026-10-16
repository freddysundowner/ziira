#!/usr/bin/env bash
# Build throwaway images and run the config-only installer test inside each. Needs Docker; never touches this machine.
#   bash deploy/tests/docker/run.sh                    # Ubuntu 20.04, 22.04, 24.04
#   bash deploy/tests/docker/run.sh ubuntu:20.04       # one image
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
command -v docker >/dev/null 2>&1 || { echo "Docker is not installed: skipping the container test" >&2; exit 0; }
docker info >/dev/null 2>&1 || { echo "Docker is not running: skipping the container test" >&2; exit 0; }
images=("$@")
[ "${#images[@]}" -gt 0 ] || images=(ubuntu:20.04 ubuntu:22.04 ubuntu:24.04)
failed=0
for image in "${images[@]}"; do
  echo "################ $image"
  tag="ziira-installer-test:$(echo "$image" | tr ':/' '--')"
  docker build -q --build-arg BASE="$image" -t "$tag" "$HERE" >/dev/null || { echo "build failed for $image"; failed=1; continue; }
  docker run --rm -v "$ROOT":/src:ro "$tag" bash /src/deploy/tests/docker/inside.sh || failed=1
done
exit "$failed"

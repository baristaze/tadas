#!/usr/bin/env bash
# Start every Tadas application process on the host against the local
# compose stack. Ctrl-C stops them all.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

# Application processes are appended here by the scaffold steps that add them.
uv run --package tadas-api tadas-api serve --port "${TADAS_PORT:-8000}" &
pids+=($!)
uv run --package tadas-maintenance tadas-maintenance serve &
pids+=($!)
pnpm --filter @tadas/portal dev &
pids+=($!)

wait

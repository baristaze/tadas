#!/usr/bin/env bash
# Start every Tadas application process on the host against the local
# compose stack. Ctrl-C stops them all.
set -euo pipefail
cd "$(dirname "$0")/.."

# .env is a dotenv file, not a shell script: `make up` copies .env.example
# over, and values there are unquoted words (SEED_NAME=Local Owner) and JSON
# (TADAS_CORS_ORIGINS=["http://..."]). Sourcing it runs the second word as a
# command and strips the quotes out of the first. Read it the way
# pydantic-settings and compose do instead: one KEY=VALUE per line, comments
# and blanks skipped, one layer of matching quotes removed, no expansion.
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    [ "${line#*=}" = "$line" ] && continue
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in ''|*[!A-Za-z0-9_]*) continue ;; esac
    case "$value" in
      \"*\") value="${value:1:${#value}-2}" ;;
      \'*\') value="${value:1:${#value}-2}" ;;
    esac
    export "$key=$value"
  done < .env
fi

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

uv run --package tadas-api tadas-api serve --port "${TADAS_PORT:-8000}" &
pids+=($!)
uv run --package tadas-maintenance tadas-maintenance serve &
pids+=($!)
pnpm --filter @tadas/portal dev &
pids+=($!)

wait

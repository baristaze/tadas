#!/bin/sh
# Shared entrypoint for every Tadas image. The image's CMD names the
# console script and its subcommand; this file only prepares the process.
set -eu

# Fail fast on a missing database URL: every process needs storage.
: "${TADAS_DATABASE_URL:?TADAS_DATABASE_URL must be set}"

exec "$@"

#!/bin/sh
# Shared entrypoint for every Tadas image. The image's CMD names the
# console script and its subcommand; this file only prepares the process.
set -eu

# Fail fast on a missing database URL: every process needs storage, and the
# system scope reads on a login of its own. A missing one would fall back to
# the local default and point those reads at another database.
: "${TADAS_DATABASE_URL:?TADAS_DATABASE_URL must be set}"
: "${TADAS_DATABASE_SYSTEM_URL:?TADAS_DATABASE_SYSTEM_URL must be set}"

exec "$@"

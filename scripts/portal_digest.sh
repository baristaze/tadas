#!/usr/bin/env bash
# The digest of a portal build: one sha256 over every file's path and
# content, in a fixed order, so the same build in two places digests the
# same. deploy-staging.yml records it when it keeps the build;
# deploy-production.yml recomputes it over the replicated copy and refuses a
# copy whose digest differs.
#
#   scripts/portal_digest.sh <build dir>
set -euo pipefail

dir="${1:?usage: scripts/portal_digest.sh <build dir>}"
[ -d "$dir" ] || { echo "no such directory: $dir" >&2; exit 2; }

cd "$dir"
digest="$(find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum)"
echo "sha256:${digest%% *}"

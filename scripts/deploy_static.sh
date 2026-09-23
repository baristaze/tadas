#!/usr/bin/env bash
# Publish a built static site, the portal or the company site, to the bucket
# and distribution an environment root just applied. Used by
# deploy-staging.yml and deploy-production.yml after `terraform apply`, with
# the build every environment of that commit receives; runs from the repo root
# with the AWS session that applied the environment.
#
#   scripts/deploy_static.sh portal deployment/terraform/environments/staging apps/portal/dist
#   scripts/deploy_static.sh site deployment/terraform/environments/staging apps/site/dist/staging
#
# The root's outputs name the bucket, the distribution, and the address:
# <name>_bucket, <name>_distribution_id, <name>_url.
set -euo pipefail

usage="usage: deploy_static.sh <portal|site> <terraform environment dir> <built dir>"
name="${1:?$usage}"
root="${2:?$usage}"
dist="${3:?$usage}"
case "$name" in
  portal|site) ;;
  *) echo "$usage" >&2; exit 2 ;;
esac
[ -f "$dist/index.html" ] || { echo "no index.html in $dist" >&2; exit 1; }

bucket="$(terraform -chdir="$root" output -raw "${name}_bucket")"
distribution="$(terraform -chdir="$root" output -raw "${name}_distribution_id")"

# Hashed assets first, cached for a year; the previous build's assets stay, so
# a tab still running the old index.html can load its lazy chunks.
aws s3 sync "$dist/assets" "s3://$bucket/assets" \
  --cache-control "public, max-age=31536000, immutable"

# Then the entry points, which browsers revalidate on every load. config.json
# is not in any build: Terraform writes the portal's per environment.
aws s3 cp "$dist" "s3://$bucket" --recursive \
  --exclude "assets/*" --exclude "config.json" \
  --cache-control "no-cache"

# Edges drop their copy of every entry point: the root, and each file outside
# assets/ (index.html, and the site's 404.html, favicon, robots.txt).
paths=("/")
while IFS= read -r file; do
  paths+=("/${file#./}")
done < <(cd "$dist" && find . -type f -not -path "./assets/*" -not -name config.json | LC_ALL=C sort)
invalidation="$(aws cloudfront create-invalidation --distribution-id "$distribution" \
  --paths "${paths[@]}" --query 'Invalidation.Id' --output text)"
aws cloudfront wait invalidation-completed --distribution-id "$distribution" --id "$invalidation"

echo "$name published to $(terraform -chdir="$root" output -raw "${name}_url")"

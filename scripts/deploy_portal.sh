#!/usr/bin/env bash
# Publish a built portal to the bucket and distribution an environment root
# just applied. Used by deploy-staging.yml and deploy-production.yml after
# `terraform apply`, with the one build every environment receives; runs from
# the repo root with the AWS session that applied the environment.
#
#   scripts/deploy_portal.sh deployment/terraform/environments/staging apps/portal/dist
set -euo pipefail

root="${1:?usage: deploy_portal.sh <terraform environment dir> <built portal dir>}"
dist="${2:?usage: deploy_portal.sh <terraform environment dir> <built portal dir>}"
[ -f "$dist/index.html" ] || { echo "no index.html in $dist" >&2; exit 1; }

bucket="$(terraform -chdir="$root" output -raw portal_bucket)"
distribution="$(terraform -chdir="$root" output -raw portal_distribution_id)"

# Hashed assets first, cached for a year; the previous build's assets stay, so
# a tab still running the old index.html can load its lazy chunks.
aws s3 sync "$dist/assets" "s3://$bucket/assets" \
  --cache-control "public, max-age=31536000, immutable"

# Then the entry points, which browsers revalidate on every load. config.json
# is not in the build: Terraform writes it per environment.
aws s3 cp "$dist" "s3://$bucket" --recursive \
  --exclude "assets/*" --exclude "config.json" \
  --cache-control "no-cache"

# Edges drop their copy of the entry point; every client route maps to it.
invalidation="$(aws cloudfront create-invalidation --distribution-id "$distribution" \
  --paths "/" "/index.html" --query 'Invalidation.Id' --output text)"
aws cloudfront wait invalidation-completed --distribution-id "$distribution" --id "$invalidation"

echo "portal published to $(terraform -chdir="$root" output -raw portal_url)"

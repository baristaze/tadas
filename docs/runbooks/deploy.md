# Deploy: the pause before `terraform apply`

Process: `.github/workflows/deploy.yml`, which follows every green `ci`
run on `main` (or a `workflow_dispatch`). The pause is
`.github/workflows/human_approval.yml`, bound to the `human_approval`
GitHub environment; the environment's one rule is a required reviewer,
the owner. The environment is created outside the repository (a
`PUT /repos/{owner}/{repo}/environments/human_approval` with the
reviewer), not by Terraform, since it is what protects the deploy role's
use.

## What happens

1. `cloud` checks the repository variables. Empty: the summary says the
   cloud deployment is not configured, every cloud job is skipped, and
   the run is green with only the portal built. Nothing to do.
2. `portal` builds the portal once; `plan` pushes both images by digest
   and runs `terraform plan` for dev. The plan text is in that job's
   summary and in the `dev-plan` artifact; the saved plan is in the state
   bucket under `plans/environments/dev/<run id>-<attempt>.tfplan`.
3. The run stops at `human approval`. GitHub shows "Review deployments"
   on the run page; the same review is at the job.
4. Approve: `dev` applies exactly that saved plan (Terraform refuses it
   if the state moved meanwhile), migrates, publishes the portal, then
   `production` waits for its own environment's approval as before.
   Reject: the run is cancelled; `dev` and `production` are skipped and
   nothing was applied.

## What to check at the pause

- The `Plan:` line: the counts of add, change, destroy against what the
  merged change intended. A destroy of a database, a cache, or a bucket
  is never routine; reject and look.
- The image digests in the summary are for this commit (`tadas-api:<sha>`
  built them).
- `terraform show`: the resources named match the change; nothing is
  replaced (`-/+`) that holds data.

## What to expect

- A waiting run holds the `deploy` concurrency group, so the next merge
  queues behind it until it is approved or rejected. GitHub cancels a
  waiting job after 30 days.
- The `human_approval_smoke` workflow (run it by hand from Actions) is
  the self-test: it waits at the same environment and applies nothing.

## When it fails

- `cloud` skipped everything although the account exists: set
  `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET`, `DNS_ZONE_NAME` as repository
  variables, and `API_DOMAIN_NAME`, `APP_DOMAIN_NAME` in the `dev` and
  `production` environments (deployment/terraform/modules/README.md).
- `apply` says the saved plan is stale: someone applied dev in between.
  Rerun the workflow; a fresh plan comes back for review.

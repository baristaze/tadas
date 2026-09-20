# Deploy: staging is `main`, production is `release`

Two branches, two workflows, one approval.

- `main` is staging. `.github/workflows/deploy-staging.yml` follows every
  green `ci` run on a push to `main` in this repository (or a
  `workflow_dispatch`): it builds the images once, tagged by the commit,
  keeps the portal build by the commit, and plans and applies staging
  with no approval. A merge is the deployment. A pull request never
  deploys, a fork's branch least of all: `ci` runs on every pull
  request, and a `workflow_run` carries this repository's staging role
  whatever the code it followed.
- `release` is production. It moves only by a fast-forward from `main`,
  which `.github/workflows/release.yml` makes when a person dispatches
  it; nobody commits to `release` and nothing merges into it. A push to
  `release` runs `.github/workflows/deploy-production.yml`: it refuses
  unless `release` is an ancestor of `main`, resolves the digests and
  the portal build staging made for that commit (a commit staging never
  built is refused), plans production, waits for a reviewer's approval
  on that plan, and applies exactly it.

The approval is the `production` GitHub environment's required reviewer,
the owner. The environment is created outside the repository, not by
Terraform, since it is what protects the deploy role's use; the
production workflow fails before it plans when the rule is missing.

## One credential per environment

Three roles, declared in `deployment/terraform/shared`, and each trusts
exactly one subject:

| Role | Assumed by a job that declares | On ref | May |
|------|--------------------------------|--------|-----|
| `tadas-deploy-staging` | `environment: staging` | `refs/heads/main` | apply staging |
| `tadas-plan-production` | `environment: production-plan` | `refs/heads/release` | read production, plan it |
| `tadas-deploy-production` | `environment: production` | `refs/heads/release` | apply production |

A GitHub job presents `repo:<owner>/<name>:environment:<name>` in its
token only when it declares that environment, and presents its branch
when it declares none. So the gate on the `production` environment is
the gate on the credential: a job that has not waited for the reviewer
never produces the subject the applying role trusts, and a staging run,
which waits for nobody by design, holds a credential that reaches no
production state, secret, bucket, queue, or database.

Each role's permissions stop at what its environment owns: names
beginning `tadas-<environment>`, secrets under `tadas/<environment>/`,
log groups under `/tadas/<environment>/`, its own key in the state
bucket, and the record names under its own base domain. Everything
tagged as the other environment is denied outright, and so is any path
by which a role could widen itself: the deploy roles, the OIDC trust,
a new user or access key, and a task role created without the
`tadas-task-boundary-<environment>` permissions boundary.

`tadas-plan-production` runs the jobs before the approval. It changes
nothing: it reads production, takes the state lock while it plans, and
writes the plan file the reviewer approves. It does read production's
secrets, because a plan reads the state and the state holds the
database password in clear. The approval holds the write, not the read.

Set once, by hand:

- Settings, Environments: `staging` (no rule, deployment branch
  `main`), `production-plan` (no rule, deployment branch `release`),
  `production` (required reviewer, deployment branch `release`). A
  reviewer on `production-plan` would hold the plan the reviewer is
  meant to read, so leave it without one.
- Settings, Variables: `AWS_STAGING_ROLE_ARN`,
  `AWS_PRODUCTION_PLAN_ROLE_ARN`, `AWS_PRODUCTION_ROLE_ARN`,
  `TF_STATE_BUCKET`, `DNS_ZONE_NAME`. The three role ARNs are outputs
  of the `shared` root. Setting the wrong ARN in one of them does not
  cross the boundary: the role refuses a subject it does not trust.
- In AWS, apply `deployment/terraform/shared` once, by a person, with
  an administrator profile. It creates the OIDC provider, the two task
  boundaries, and the three roles. `shared` is never applied by a
  deploy run; every deploy role denies the calls that would change the
  registry, the state bucket, or the trust.

## Cut a release

1. Pick the `main` commit: it has run on staging (the `deploy-staging`
   run for it is green) and staging looks right. The release is
   `main`'s tip; to release an older commit, see Roll back.
2. Actions, `release`, Run workflow on `main`. The job lists the commits
   `release` gains in its summary and pushes the fast-forward. If it
   says `release` is not an ancestor of `main`, someone committed to
   `release`: see When it fails.
3. `deploy-production` starts on the push (or is dispatched by the
   release job, when the push was made with the workflow token). Its
   `guard`, `resolve`, and `plan` jobs run on their own; the run stops
   at `apply the approved plan, migrate, and publish`. GitHub shows
   "Review deployments" on the run page.

## Approve a plan

Read the `plan production` job's summary (the whole text is in the
`production-plan` artifact) before pressing Approve:

- The `Plan:` line: the counts of add, change, destroy against what the
  release intended. A destroy of a database, a cache, or a bucket is
  never routine; reject and look.
- The images are the digests the `resolve` job names, tagged with the
  release commit by staging.
- `terraform show`: the resources named match the change; nothing is
  replaced (`-/+`) that holds data. The `terraform_data.pre_rollout`
  replacement under `module.environment.module.api` is the migration and
  appears on every image change.

Approve: `apply` applies exactly the saved plan (Terraform refuses it if
the state moved meanwhile). Inside the apply the migration runs as a
one-off task on the new API image, then the API rolls, then the worker;
the apply waits until the new tasks serve; then the portal files staging
kept for the commit are published. Reject: the run is cancelled and
nothing was applied; `release` still points at the commit, so a fix is
a new `main` commit and another release.

## Roll back

A rollback is a release of an earlier `main` commit. `release` is a
prefix of `main`, so moving it backwards is a reset, not a fast-forward;
the workflow refuses to do it, so it is done by hand, once, by someone
the ruleset lets push:

```bash
git fetch origin
git push --force origin <earlier main commit>:release
```

The push runs `deploy-production` on that commit; approve its plan as
above. It redeploys the digests and the portal build staging made for
that commit, which the registry and the bucket still hold (the registry
keeps the last 30 images per repository). The schema is not rolled
back: a migration is compatible with the release before it (expand and
contract), so the earlier release runs against the newer schema. The
next `release` dispatch fast-forwards `release` to `main` again.

## A failed migration stops the rollout

The migration is a one-off task on the new API task definition that
runs before either service rolls; the service depends on it. When the
task exits non-zero, the apply fails at `terraform_data.pre_rollout`,
the API and the worker keep their current tasks, and nothing else in
the plan that comes after the services was applied. Read the task's log
in the API's log group (`/tadas/production/api`, stream prefix `api`).
Fix on `main` (it runs on staging first, the same way), release again;
the new plan runs the migration again from where the chain stopped
(`tadas-api migrate --all` is idempotent per revision).

A rollout that ECS rolls back (the circuit breaker) also fails the
apply: the service waits for steady state. The old tasks serve; the
migration has already run, which expand and contract allows.

## Branch protection on `release`

Set by hand, once, as a ruleset on the repository (Settings, Rules,
Rulesets), target branch `release`:

- Restrict creations, restrict deletions, block force pushes.
- Restrict updates: nobody pushes, except the bypass actors.
- Require status checks: `no pull request into release`, so a pull
  request into `release` cannot merge (the check always fails).
- Bypass list: the deploy key below, and the repository admin role for
  the by-hand rollback push (bypass actors may force-push; keep the
  list to those two).

The workflow's own token cannot be a bypass actor, so a ruleset that
restricts updates blocks `release.yml`'s push unless it pushes with a
deploy key: generate a key pair (`ssh-keygen -t ed25519 -f release_key
-N ''`), add the public key as a deploy key with write access (Settings,
Deploy keys), add it to the ruleset's bypass list under "Deploy keys",
and store the private key as the `RELEASE_DEPLOY_KEY` repository secret.
A push with it fires the push event `deploy-production` listens for.
Without the secret, `release.yml` pushes with its token, which works
only while no ruleset restricts `release` (and fires no workflow, so
the job dispatches `deploy-production` itself).

The `production` environment: Settings, Environments, `production`,
Required reviewers, the owner; or

```bash
gh api -X PUT repos/{owner}/{repo}/environments/production \
  --input - <<'JSON'
{"reviewers": [{"type": "User", "id": <the owner's user id>}]}
JSON
```

The `staging` and `production-plan` environments exist with no rule;
each role trusts the name of the one it belongs to.

## What to expect

- A waiting production run holds the `deploy-production` concurrency
  group, so a second release queues behind it until the first is
  approved or rejected. GitHub cancels a waiting job after 30 days.
- Staging runs queue in `deploy-staging`; two merges in a row deploy
  one after the other.
- Staging and production each take the migration inside their apply; a
  staging apply that fails on it is the same signal one commit earlier.

## When it fails

- `deploy-staging` skipped every cloud job although the account exists:
  set `AWS_STAGING_ROLE_ARN`, `TF_STATE_BUCKET`, `DNS_ZONE_NAME` as
  repository variables (deployment/terraform/modules/README.md).
  `deploy-production` wants `AWS_PRODUCTION_PLAN_ROLE_ARN` and
  `AWS_PRODUCTION_ROLE_ARN` instead of the staging one. The
  public names follow the zone: `api.staging.<zone>`,
  `app.staging.<zone>`, `api.<zone>`, `app.<zone>`. `deploy-production`
  fails, not skips, on the same condition.
- `guard` says `release` is not an ancestor of `main`: someone committed
  to `release`. Reset it to a `main` commit by hand
  (`git push --force origin <main commit>:release`, by a bypass actor)
  and dispatch `release` again.
- `guard` says the production environment has no required-reviewers
  rule: add it (above) before releasing; the run refused to plan.
- `resolve` says staging never built the commit: the commit's
  `deploy-staging` run did not reach the cloud (skipped, failed, or was
  older than the registry's 30 kept images). Rerun `deploy-staging` on
  that commit from Actions, or release a newer one. A rerun is safe on a
  commit whose images are already pushed: the tags are immutable, so the
  `images` job resolves the digests that are there instead of pushing
  the same tag twice.
- `apply` says the saved plan is stale: someone applied production in
  between. Rerun the workflow; a fresh plan comes back for review.
- A job fails at `configure-aws-credentials` with "Not authorized to
  perform sts:AssumeRoleWithWebIdentity": the token's subject is not
  the one the role trusts. Either the job lost its `environment:` line,
  or it is running on a ref the role does not allow (`main` for
  staging, `release` for production), or the environment was renamed.
  A `workflow_dispatch` of `deploy-staging` on a branch other than
  `main` fails here by design.
- `release.yml`'s push is refused by a ruleset: set `RELEASE_DEPLOY_KEY`
  as above.

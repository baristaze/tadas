---
name: ops-cloud-deployment-create
description: "Create one cloud environment of the platform from nothing, in its own AWS account, as that account's administrator: the bootstrap root (state bucket, registry, OIDC trust, the deploy roles, the investigate role, the budget, the zones), the delegation of its public names at Cloudflare, the investigate profile, the GitHub environments and their variables, then the first deploy through the pipeline and the smoke test. Runs scripts/cloud_create.sh after checking the administrator profile, the account, and the GitHub login. Supports --dry-run. The one skill besides nuke that needs a credential that writes."
allowed-tools: Read, Grep, Glob, Bash(aws:*), Bash(gh:*), Bash(scripts/cloud_create.sh:*)
---

# ops-cloud-deployment-create

The bootstrap. Everything the pipeline needs before its first run is
made here, once per account, by a person holding the account's
administrator profile with an agent narrating. After this skill the
environment moves only by pull request, and the administrator's
permission set goes back to the organization.

## Input

`--env staging|production [--dry-run]`

`--env` is required; ask for it when missing. `--dry-run` runs the
script in its dry mode, which prints every command it would run and
runs none, so the whole path is readable before the first resource
exists. With `--dry-run` the skill runs the dry mode only and stops;
the real run is a second invocation without the flag. The script creates a cloud environment only; the compose stack
is `make up`, not this skill.

The accounts themselves, Identity Center, the permission sets, the
local profiles, and the Cloudflare token are made by hand, once, as
`deployment/cloud/first_time_manual.md` says. When a profile the skill
needs is missing, or Cost Explorer is off, point the person there
rather than working around it.

Everything about the environment's account comes from
`deployment/cloud/environments.json`: the account id, the region, the
administrator profile, the Identity Center profile an operator signs in
with, and the two public names. Read it first and say what it names.

The script also needs `OWNER_EMAIL` and `ALARM_EMAIL` (as environment
variables or as `--owner-email`, `--alarm-email`), and
`CLOUDFLARE_API_TOKEN` as an environment variable only: a token that
can edit DNS in the domain's zone at Cloudflare, so it never lands in
shell history. It refuses without them; ask for any that is missing.
The dry run needs no token.

## Order

Each environment is its own account, and production reads nothing from
staging's. What staging builds replicates into production's account,
and the replication needs production's state bucket to exist first. So
the environments are created in this order:

1. `--env staging`: staging's account, and its first deploy. The
   script finds no production bucket and leaves the replication off.
2. `--env production`: production's account. No release yet.
3. `--env staging` again: the script finds production's bucket and
   turns the replication on. Nothing else changes.

The first release is a commit merged to `main` after step 3, because
replication copies from the moment it is on and nothing before.

## Role and credential

This skill needs the administrator profile the environment names
(`tadas-staging-admin` or `tadas-prod-admin`) and refuses anything
else. Another environment's administrator is the wrong account, and a
sign-in profile (PowerUserAccess, TadasReadOnly) cannot write IAM. Before any other command,
run

```bash
aws sts get-caller-identity --profile <admin_profile>
```

and check that `Account` is the environment's `account_id` and that
`Arn` is an Identity Center administrator role
(`assumed-role/AWSReservedSSO_...`), never
`assumed-role/tadas-investigate-*`. When the session has expired, the
person signs in again with `aws sso login --profile <admin_profile>`;
the agent never does it for them. The script checks the account again
before every apply, and the Terraform providers pin it as well.

The script clears any `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or
`AWS_SESSION_TOKEN` exported in the shell, because Terraform prefers
them to a profile, and prints a `note:` line naming the ones it
cleared, dry run included. Put that line in the report: an exported
key is a long-lived one, and this platform uses none.

The GitHub login is `gh auth status`; it names a user who can write
the repository's environments and their variables.

No env file is read. The script writes one:
`~/.config/tadas/ops/<env>.env`, owner-only, with `TADAS_API_URL` set
and the operator, provisioner, and error tracker lines empty for the
person to fill in. It appends the `tadas-<env>-investigate` profile to
`~/.aws/config`, chained from the Identity Center profile. It writes no
key anywhere. The skill prints the names of what was written and never
a value.

## Procedure

1. Read `deployment/cloud/environments.json` and name the account, the
   region, and the two public names. Verify the administrator profile
   as Role and credential states. Check the GitHub login.
2. Run the script, in dry mode first when `--dry-run` was given, or
   when it is the first time this environment is created:

   ```bash
   scripts/cloud_create.sh <env> --dry-run
   scripts/cloud_create.sh <env>
   ```

3. Narrate each step as the script reaches it, in one line each, so
   the person can stop it between two:
   - Who am I: the account check, and the GitHub login.
   - The bootstrap root, `deployment/terraform/bootstrap/<staging|prod>`:
     the state bucket `tadas-state-<account>` with versioning, made on
     the first apply with local state and then adopted as the backend;
     the artifacts bucket `tadas-artifacts-<account>`, which keeps the
     portal builds and never the state; the registry; the GitHub OIDC provider; the deploy role (staging)
     or the plan and deploy roles (production); the task boundary; the
     investigate role `tadas-investigate-<env>`; the budget and the
     anomaly monitor; one hosted zone per public name. The monitor
     needs Cost Explorer, which only the organization's management
     account turns on; when the account's Cost Explorer does not
     answer, the script leaves the monitor out and says so, and the
     person decides whether to turn it on and run the script again.
     For staging, whether the replication into production is on. For
     production, the two grants that let staging's replication write
     in.
   - The delegation at Cloudflare: each public name gets NS records
     naming its zone's four name servers, and any stale NS record at
     that name is deleted. This is the only write outside AWS and
     GitHub, and the only one the token is for.
   - The investigate profile, `tadas-<env>-investigate`: the role's ARN
     with the Identity Center profile as its `source_profile`.
   - The GitHub environments and their variables: `staging`, or
     `production-plan` (no reviewer) and `production` (the owner as
     required reviewer). Each deploys from one branch only, `main` for
     staging and `release` for both production ones. Each holds
     `AWS_ROLE_ARN`, `TF_STATE_BUCKET`, and `ARTIFACTS_BUCKET` for its
     own account; the plan environment and
     staging also hold `API_DOMAIN_NAME`, `APP_DOMAIN_NAME`, and
     `ALARM_EMAIL`. No secret: the OIDC trust replaces keys.
   - The first deploy, through the pipeline: the script pushes
     nothing and applies no environment root itself. For staging it
     dispatches `deploy-staging.yml`. For production it prints the
     order above, because the first release waits for a replicated
     build.
   - The smoke test, which the script prints for the person to run
     once the deploy is green: one request through the edge, then
     `tadas-ops signals check --request-id` reading its log lines, its
     metric, its trace, and its error event back by that id.
4. Check the result with the investigate profile the script wrote,
   because that is the profile every later skill holds. The person
   signs in with the Identity Center profile first:

   ```bash
   aws sts get-caller-identity --profile tadas-<env>-investigate
   ```

   `Arn` is `assumed-role/tadas-investigate-<env>/...` in the
   environment's account. A dry run skips this step: the profile does
   not exist yet.

5. Write the report.

## What it never does

- No apply by hand: the script applies the bootstrap root, which has
  no pipeline, and dispatches the pipeline for the environment; it
  never runs `terraform apply` in an environment root.
- No IAM user and no access key, created or read.
- No secret value printed: the Cloudflare token, the operator
  password, the tracker token stay in the environment or in
  owner-only files, and appear in the report by name only.
- No console clicks: what the script cannot do with the CLI is
  reported as a manual step with its exact command.
- No tenant data; there is none yet.
- No run under any profile but the environment's administrator, and
  no run twice without `--dry-run` in between: the script is written
  to be rerun, and the dry run shows what a rerun would touch.

## Output

The budget is `monthly_budget_usd` in the bootstrap root's
`variables.tf`. In a dry run, write the report with "would be" for
what the script would make, and "decided on the real run" for the
replication and the anomaly monitor: their probes run only then. A
dry run's smoke test is "not yet".

```markdown
# Environment created: <env>

**Credential.** <admin_profile>, <Arn>, account <id>
**GitHub.** <login>, environments: <names>, variables set: <names>

## Made

- Bootstrap root: bootstrap/<staging | prod>, state in s3://tadas-state-<id>/bootstrap/
- Roles: <deploy, plan, investigate role names>; budget <usd>/month
- Zones: <api name>, <app name>, delegated at Cloudflare (<created | already there>)
- Replication into production: <on | off | n/a>
- Profile written: tadas-<env>-investigate (~/.aws/config), source_profile <sso_profile>
- Env file written: ~/.config/tadas/ops/<env>.env
- First deploy: workflow run <url>, <status> (or: waits for the order above)
- Smoke test: <passed | failed | not yet>, request id <id>

## Left for a person

- <the next step of the order, or nothing>

## Next

- Hand the administrator permission set back; every later skill runs
  under tadas-<env>-investigate.
```

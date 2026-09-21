---
name: ops-cloud-deployment-create
description: "Create one cloud environment of the platform from nothing, as the administrator: the state backend, the shared account resources (roles, boundaries, the budget, the operators user, the zone), the operator profiles, the GitHub variables and environments, then the first deploy through the pipeline and the smoke test. Runs scripts/cloud_create.sh after checking the administrator profile, the zone, and the GitHub login. Supports --dry-run. The one skill besides nuke that needs a credential that writes."
allowed-tools: Read, Grep, Glob, Bash(aws:*), Bash(gh:*), Bash(scripts/cloud_create.sh:*)
---

# ops-cloud-deployment-create

The bootstrap. Everything the pipeline needs before its first run is
made here, once, by a person holding the administrator profile with an
agent narrating. After this skill the environment moves only by pull
request; the administrator profile goes back in the drawer.

## Input

`--env staging|production [--dry-run]`

`--env` is required; ask for it when missing. `--dry-run` runs the
script in its dry mode, which prints every command it would run and
runs none, so the whole path is readable before the first resource
exists. The script creates a cloud environment only; the compose stack
is `make up`, not this skill.

The script also needs `DNS_ZONE_NAME`, `OWNER_EMAIL`, `ALARM_EMAIL`,
and `TF_STATE_BUCKET` (as environment variables or as
`--dns-zone-name`, `--owner-email`, `--alarm-email`, `--state-bucket`)
and refuses without them; ask for any that is missing.

## Role and credential

This skill needs the administrator profile `tadas-admin` and refuses
anything else. Before any other command, run

```bash
aws sts get-caller-identity --profile tadas-admin
```

and check that `Arn` is the administrator's own identity in the
account the environment belongs to (the account id
`deployment/terraform/environments/<env>/` names): a user or a role
with administrator access, never `assumed-role/tadas-investigate-*`.
An investigate profile cannot create a state bucket or a role, and
the skill stops rather than try. Every `aws` command below carries
`--profile tadas-admin`; the script refuses unless `AWS_PROFILE` (or
`--profile`) is `tadas-admin`.

The GitHub login is `gh auth status`; it names a user who can write
the repository's variables and environments.

No env file is read. The script writes one: `~/.config/tadas/ops/<env>.env`,
owner-only, with `TADAS_API_URL` set and the operator, provisioner, and
error tracker lines empty for the person to fill in. It writes the
operators' key into `~/.aws/credentials` and the profiles into
`~/.aws/config`. The skill prints the names of what was written and
never a value.

## Procedure

1. Verify the administrator profile as Role and credential states.
   Check the GitHub login. Cloud only: check the zone. `shared`
   creates the DNS zone when `create_dns_zone` is true and outputs its
   name servers; when the zone exists already, read it with
   `aws route53 list-hosted-zones-by-name --profile tadas-admin` and
   confirm the base domain of the environment (production the
   product's domain, staging its `staging.` subdomain) resolves to it
   or will after the delegation the script prints.
2. Run the script, in dry mode first when `--dry-run` was given, or
   when it is the first time this environment is created:

   ```bash
   scripts/cloud_create.sh <env> --dry-run
   scripts/cloud_create.sh <env>
   ```

3. Narrate each step as the script reaches it, in one line each, so
   the person can stop it between two:
   - The state backend: the state bucket with versioning, made by
     `shared` on its first apply; the lock is a lockfile beside each
     state (`use_lockfile`), and the environment's state lives under
     `environments/staging/` or `environments/prod/`.
   - `shared`: the investigate role `tadas-investigate-<env>` with its
     fences, the permission boundary, the budget and the anomaly
     monitor, the operators user `tadas-operators` with its one
     `sts:AssumeRole` policy, the zone.
   - The operators user's access key, minted once and written into
     `~/.aws/credentials` as `tadas-operators`, with
     `tadas-<env>-investigate` chained from it in `~/.aws/config` by
     `role_arn` and `source_profile`. The key is never printed and never lands in
     the repository.
   - The GitHub variables (account id, region, the base domain, the
     zone) and the environments `staging` and `production`, the
     latter with its required reviewers, and the OIDC trust for the
     deployer role.
   - The first deploy, through the pipeline: the script pushes
     nothing and applies nothing itself; it dispatches the deploy
     workflow, which applies the environment as every later merge
     does.
   - The smoke test, which the script prints for the person to run
     once the deploy is green: one request through the edge, then
     `tadas-ops signals check --request-id` reading its log lines, its
     metric, its trace, and its error event back by that id.
4. Check the result with the investigate profile the script wrote,
   because that is the profile every later skill holds:

   ```bash
   aws sts get-caller-identity --profile tadas-<env>-investigate
   ```

5. Write the report.

## What it never does

- No apply by hand: the script applies `shared` and the backend,
  which have no pipeline, and dispatches the pipeline for the
  environment; it never runs `terraform apply` in an environment
  root.
- No secret value printed: the access key, the operator password, the
  tracker token go into owner-only files and appear in the report as
  the file paths that hold them.
- No console clicks: what the script cannot do with the CLI is
  reported as a manual step with its exact command.
- No tenant data; there is none yet.
- No run under any profile but `tadas-admin`, and no run twice without
  `--dry-run` in between: the script is written to be rerun, and the
  dry run shows what a rerun would touch.

## Output

```markdown
# Environment created: <env>

**Credential.** tadas-admin, <Arn>, account <id>
**GitHub.** <login>, variables set: <names>, environments: <names>

## Made

- State backend: <bucket>, prefix environments/<staging | prod>/
- shared: <role>, <user>, budget <usd>/month, zone <name> (<created | existing>)
- Profiles written: tadas-operators, tadas-<env>-investigate (~/.aws/config)
- Env file written: ~/.config/tadas/ops/<env>.env
- First deploy: workflow run <url>, <status>
- Smoke test: <passed | failed>, request id <id>

## Left for a person

- <delegation of the zone at the registrar, or nothing>

## Next

- Put tadas-admin away; every later skill runs under tadas-<env>-investigate.
```

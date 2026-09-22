---
name: ops-cloud-deployment-nuke
description: "Destroy one cloud environment of the platform as its account's administrator: empty the buckets, destroy the environment root, and report what remains (the bootstrap root whole: the zones, the registry, the roles, the state). Runs scripts/cloud_nuke.sh after checking the administrator profile and the account. Refuses production unless --confirm production is typed and a released change on release, applied, sets the database's deletion protection off. Applies from a clean worktree of the deployed branch, never the working tree. Supports --dry-run. The one skill besides create that needs a credential that writes."
allowed-tools: Read, Grep, Glob, Bash(aws:*), Bash(gh:*), Bash(git fetch:*), Bash(git show:*), Bash(scripts/cloud_nuke.sh:*)
---

# ops-cloud-deployment-nuke

The opposite of create, and just as rare. An environment is destroyed
by a person holding its account's administrator profile, with an agent checking
the preconditions and narrating. Production is protected twice: by a
pull request that lifts deletion protection, merged before this skill
runs, and by the name typed into the command.

## Input

`--env staging|production [--confirm <env>] [--dry-run]`

`--env` is required; ask for it when missing. `--confirm production`
is required for production and must be typed by the person, never
filled in by the skill. `--dry-run` runs the script in its dry mode,
which prints every command it would run and runs none. The script
destroys a cloud environment only; the compose stack is `make reset`
or `make down`, not this skill.

The account, the region, the administrator profile, and the public
names come from `deployment/cloud/environments.json`. The script also
needs `ALARM_EMAIL` (as an environment variable or as
`--alarm-email`), the value the GitHub environment holds, and refuses
without it.

## Role and credential

This skill needs the administrator profile the environment names
(`tadas-staging-admin` or `tadas-prod-admin`) and refuses anything
else. The administrator's permission set is assigned for the run; when
it has been handed back, the person asks for it again first. Before
any other command, run

```bash
aws sts get-caller-identity --profile <admin_profile>
```

and check that `Account` is the environment's `account_id` and that
`Arn` is an Identity Center administrator role, never
`assumed-role/tadas-investigate-*`. Every `aws` command below carries
`--profile <admin_profile>`; the script refuses any other profile,
clears keys exported in the shell, and checks the account again before
the apply and before the destroy.

No env file is read. The script leaves the environment's
`~/.config/tadas/ops/<env>.env` and its profile in `~/.aws/config` in place
and lists them under what remains; removing them is the person's
call.

## Procedure

1. Verify the administrator profile as Role and credential states.
2. Production only, two checks, both before the script runs:
   - `--confirm production` is present and was typed by the person.
     Without it, stop and say what is missing; never suggest the
     flag as a paste.
   - The root's `database_deletion_protection` reads `false` on
     `release`, set by a merged pull request and released (the script
     reads the same line, then the applied state, and refuses
     otherwise):

     ```bash
     git fetch origin release
     git show origin/release:deployment/terraform/environments/prod/main.tf \
       | grep database_deletion_protection
     gh pr list --state merged --search "deletion protection" --limit 5
     ```

     A working tree or a `main` that reads `false` while `release`
     reads `true` is not enough: production applies `release`, so the
     protection is still on. Stop and name the release to run first.
3. Read what the environment holds, so the report can say what is
   gone and what stays:

   ```bash
   aws ecs describe-services --cluster tadas-<env> \
     --services tadas-<env>-api tadas-<env>-maintenance --profile <admin_profile>
   aws s3api list-buckets --query 'Buckets[?starts_with(Name, `tadas-<env>-`)].Name' \
     --profile <admin_profile>
   ```

4. Run the script, dry first:

   ```bash
   scripts/cloud_nuke.sh <env> --dry-run
   scripts/cloud_nuke.sh <env> [--confirm production]
   ```

   Narrate each step as the script reaches it: the clean worktree of
   `origin/main` (staging) or `origin/release` (production) the root is
   applied from, so no unreleased change reaches the environment; the
   `destroyable`
   switch applied (`force_destroy` on the buckets, no recovery window
   on the secrets, and for staging only `skip_final_snapshot` and the
   lifted protection on the database) through one apply of the
   environment root; production's database keeps its final snapshot
   `tadas-production-final` and its automated backups; `terraform
   destroy` of the environment root, which empties every
   `tadas-<env>-*` bucket it owns, versions included, and never the
   state bucket; then the list of what remains.
5. Read what remains and write the report. The bootstrap root stays
   whole: the zones, because Cloudflare delegates to them; the
   registry and its images; the roles, so the pipeline can deploy the
   environment again; the budget; and the state bucket, whose
   environment prefix stays, empty, so a recreate finds its backend.
   The GitHub
   environment and its variables, the local env file, and the
   profiles stay too; the script touches none of them. A resource
   the destroy could not remove is listed with the reason the script
   printed.

## What it never does

- No destroy without the preconditions: the profile, the typed
  confirmation, the merged change.
- No touch of the bootstrap root: the state bucket, the zones, the
  registry, the roles.
- No destroy of the other environment: it is another account, the
  profile is the one this environment names, and the script refuses a
  session that resolves to any other account.
- No secret value printed.
- No console clicks: a resource the CLI cannot remove is reported,
  not clicked away.

## Output

```markdown
# Environment destroyed: <env>

**Credential.** <admin_profile>, <Arn>, account <id>
**Confirmation.** <typed | not needed (staging)>
**Deletion protection on release.** <false, PR <url>, applied | not needed (staging)>
**Applied from.** origin/<main | release> at <sha>, in a clean worktree

## Gone

- Services: <names>
- Database: <identifier>, final snapshot <skipped (staging) | tadas-production-final>
- Buckets emptied and removed: <names>

## Remains

- The bootstrap root: zones <names> (delegated at Cloudflare), the registry, <role names>, budget
- State prefix environments/<staging | prod>/ in tadas-state-<id>, empty
- Production only: the final snapshot tadas-production-final and the automated backups
- Staging only: production's copies of what staging built, in production's account
- GitHub environment and variables; ~/.config/tadas/ops/<env>.env; the tadas-<env>-investigate profile
- <resource the destroy could not remove>: <reason>
```

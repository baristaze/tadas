---
name: audit-deploy-time
description: "Audit where a deploy's minutes go: the pipeline's jobs and steps from the Actions run, the Terraform apply's resources, the migration's one-off task, each service's rollout from its ECS events and its tasks' first log lines, and the settings that pace them (health-check grace, thresholds, deregistration delay, the steady-state wait). Read-only, under the investigate profile; reports each phase against a target with a fix and its effort. Never changes anything."
allowed-tools: Read, Grep, Glob, Write, Bash(uv run:*), Bash(git:*), Bash(gh run:*), Bash(aws:*)
---

# audit-deploy-time

One deploy, or the last few, taken apart into phases: what each took,
what it waited on, and which setting or step would shorten it. Every
number comes from what the pipeline and the cluster already record.

Read `.claude/skills/_shared/ops-preamble.md` before the first step: the
profiles, the account check, and the env file are there.

## Input

`--env staging|production [--run <run id>] [--last <n>] [--target <minutes>]`

`--env` is required; ask for it when missing. `--run` is one run of the
environment's deploy workflow (`deploy-staging.yml`,
`deploy-production.yml`); without it, the last `--last` runs (3 by
default) that succeeded. `--target` is the deploy time the report
judges against, 5 minutes for a deploy without a migration by default;
say which target and where it came from.

## Role and credential

Investigator, read-only. `gh` reads the runs and their logs under the
person's own GitHub sign-in (`gh auth status`). The cloud reads run
under `tadas-<env>-investigate`, checked with `sts get-caller-identity`
before any other `aws` command, as the preamble states. Refuse any
profile wider than the investigate role. Every `aws` command carries
`--profile tadas-<env>-investigate`. The skill reads no env file and no
token.

## Procedure

1. Pick the runs and make the evidence folder
   `~/Downloads/tadas_deploy_time_<yyyy-mm-dd>/`:

   ```bash
   gh run list --workflow deploy-<env>.yml --status success --limit <n> --json databaseId,headSha,createdAt,displayTitle
   ```

2. The pipeline's phases, per run:

   ```bash
   gh run view <run id> --json createdAt,updatedAt,jobs > ~/Downloads/tadas_deploy_time_<yyyy-mm-dd>/run_<run id>.json
   uv run python ops/audit/deploy_timeline.py steps ~/Downloads/tadas_deploy_time_<yyyy-mm-dd>/run_<run id>.json
   ```

   The job that holds the minutes is the apply's (`plan and apply
   <env>, migrate, and publish`). Read its log for the Terraform
   resources that took long: `gh run view <run id> --log --job <job id>`,
   and in it the `Creation complete after`, `Modifications complete
   after`, and `Still modifying... [<n>s elapsed]` lines. Name each
   resource over thirty seconds with its time: the migration
   (`terraform_data.pre_rollout`), each service
   (`aws_ecs_service.this`), and anything else.
3. The migration. `deployment/terraform/modules/service/pre_rollout.sh`
   and `deployment/terraform/modules/README.md` say when it runs a task.
   Say whether this run's release carried a migration (`git diff
   <previous deploy's sha> <this sha> --stat -- om/migrations/`), and
   whether the task ran anyway. A task's time is its cold start plus the
   migration: read the task's own log group, `/tadas/<env>/migrate`.
4. Each service's rollout. The ECS events of the window, and the new
   task's first lines:

   ```bash
   aws ecs describe-services --cluster tadas-<env> --services api maintenance \
     --profile tadas-<env>-investigate > ~/Downloads/tadas_deploy_time_<yyyy-mm-dd>/services.json
   uv run python ops/audit/deploy_timeline.py events ~/Downloads/tadas_deploy_time_<yyyy-mm-dd>/services.json \
     --since <the apply step's start> --until <its end>
   aws logs filter-log-events --log-group-name /tadas/<env>/api \
     --start-time <epoch ms> --end-time <epoch ms> --filter-pattern '"api started"' \
     --profile tadas-<env>-investigate
   ```

   ECS keeps the last hundred events of a service, so an old run's may be
   gone: say so. For each rollout: when the task started, when it
   registered with the target group, when the process logged its start,
   when the target turned healthy, and when the old task drained. A task
   that failed its health checks and was replaced is the costliest
   finding; the gap between the task's start and the process's start
   line is the cold start.
5. The settings that pace a rollout: in
   `deployment/terraform/modules/service/main.tf`,
   `health_check_grace_period_seconds`, `wait_for_steady_state`,
   `deployment_minimum_healthy_percent`, and `deployment_maximum_percent`;
   in `deployment/terraform/modules/load_balancer/main.tf`, the target
   group's `deregistration_delay` and its health check's `interval`,
   `healthy_threshold`, and `unhealthy_threshold`; the environment's root
   (`deployment/terraform/environments/<env>/main.tf`) for what it
   overrides. Hold each
   against what step 4 measured.
6. Write the report: the phases in a table with their times and a
   verdict against the target, then the findings by the minutes each
   would save, each with its fix, its effort, and a proposed ticket. The
   skill files none.

## What it never does

- Never writes to an environment: no `aws` verb but `describe`, `get`,
  `list`, and `filter-log-events`; no `terraform apply`, no dispatch of
  a workflow, no rerun of a job.
- Never modifies a tracked file, never commits, never opens a pull
  request: it writes a report and proposes tickets.
- No secret read or printed.
- Never reports a phase it could not read as fast: an event ECS no
  longer holds is "not read".

## Output

`~/Downloads/tadas_deploy_time_<yyyy-mm-dd>.md`:

```markdown
# Tadas: where a <env> deploy's minutes go

Runs <ids and shas>; read under <profile and Arn>. Target: <minutes> (<source>).

## The answer

<the total, the two phases that hold most of it, and what would bring it under the target>

## Phases

| Phase | Run <id> | Run <id> | Waits on | Verdict |
|---|---|---|---|---|

## Each rollout

| Service | Task started | Registered | Process up | Healthy | Old task gone | Replaced? |

## Findings, by minutes saved

1. **<finding>.** Evidence (times, events). Fix (the setting or step, and its value). Saves <minutes>. Effort S/M/L. Proposed ticket: <title>.

## What I could not read
```

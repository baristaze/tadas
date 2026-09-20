---
name: ops-root-cause
description: "Find the root cause of one tenant's problem in one environment: read that tenant's rows through the operator plane's read routes with a read-only operator identity, correlate them with the logs, the trace, and the error event by request id, and report the cause and the fix. Takes the org id and optionally a user id. Never a database login, never a write, never another tenant's data."
allowed-tools: Read, Grep, Glob, Bash(aws:*), Bash(curl:*), Bash(docker compose:*), Bash(uv run:*)
---

# ops-root-cause

The supporter's skill. An investigation ends at "tenant X sees Y"; this
skill opens tenant X, and only tenant X, through the operator plane,
and follows one request id across every signal until the cause is a
line of code, a row, or a resource.

## Input

`--env local|staging|production --org <org_id> [--user <user_id>] [--request-id <id>] [--since 24h]`

`--env` and `--org` are required; ask for them when missing. `--user`
narrows to one member of the tenant. `--request-id` starts from one
request; without it the skill finds the failing requests of the
window in the tenant's events and the error tracker. `--since` is the
window, a day by default.

`local` reads the compose stack and its twins; no cloud is needed.

## Role and credential

`--env local` needs the compose stack with the `devx` profile up
(`make devx-up`) and the env file below. No cloud credential.

`--env staging` and `--env production` need the investigate profile
of that environment, `tadas-<env>-investigate`, which assumes the role
`tadas-investigate-<env>`. Before any other command, run

```bash
aws sts get-caller-identity --profile tadas-<env>-investigate
```

and check that `Arn` reads
`arn:aws:sts::<account>:assumed-role/tadas-investigate-<env>/...`.
Refuse any other identity, the administrator profile `tadas-admin`
above all. Every `aws` command below carries
`--profile tadas-<env>-investigate`.

The tenant's rows come through the operator plane, never through a
database login: the role denies `rds-db:connect` and holds no database
URL. The operator identity is the env file's,
`~/.config/tadas/ops/<env>.env`, owner-only and outside the
repository: `TADAS_API_URL`, `TADAS_OPERATOR_EMAIL`,
`TADAS_OPERATOR_PASSWORD`, `TADAS_ERROR_TRACKER_URL`,
`TADAS_ERROR_TRACKER_TOKEN`, and for `local.env` the twins
`TADAS_PROMETHEUS_URL` and `TADAS_JAEGER_URL`. The identity's allowlist
entry is `READ`; a `WRITE` identity is refused by this skill even when
the file holds one. Never print the password or the token.

## Procedure

1. Verify the credential as Role and credential states. Read the env
   file. Sign the operator in through `POST /v1/auth/login` at
   `$TADAS_API_URL` with `curl` (the identity stage is what the operator
   plane admits; no tenant session is exchanged), keep the bearer in a
   shell variable, read `GET /v1/me/identity`, and check the answer
   names `operator_role: read`; stop on `write`.
2. Read the tenant, then its members, through the operator plane's
   read routes, every one under `/v1/admin/orgs/{org_id}/`:

   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" "$TADAS_API_URL/v1/admin/orgs/<org_id>"
   curl -s -H "Authorization: Bearer $TOKEN" "$TADAS_API_URL/v1/admin/orgs/<org_id>/members"
   ```

   With `--user`, keep that member alone. A route that answers 403 or
   404 ends the run: the identity is not allowed, or the tenant does
   not exist, and neither is guessed around.
3. Read the tenant's activity of the window: the events feed and the
   entity rows the product exposes on the plane:

   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" "$TADAS_API_URL/v1/admin/orgs/<org_id>/events?after_seq=<seq>&limit=200"
   ```

   Every event carries the request id and the actor of the write, so
   the feed is the map from what the tenant did to the requests that
   did it. Without `--request-id`, pick the request ids of the
   window's failed or missing writes here and in step 4.
4. The error tracker, by request id or by tenant window:

   ```bash
   curl -s -H "Authorization: Bearer $TADAS_ERROR_TRACKER_TOKEN" \
     "$TADAS_ERROR_TRACKER_URL/api/0/organizations/<org>/issues/?query=request_id%3A<id>"
   ```

   Local runs the same call against GlitchTip. An event names the
   exception, the file, the line, the release.
5. The logs, by request id. Cloud:

   ```bash
   aws logs start-query --profile tadas-<env>-investigate \
     --log-group-names /tadas/<env>/api /tadas/<env>/maintenance \
     --start-time <start> --end-time <end> \
     --query-string 'fields @timestamp, level, @message | filter request_id = "<id>" or caused_by_request_id = "<id>" | sort @timestamp asc'
   aws logs get-query-results --query-id <id> --profile tadas-<env>-investigate
   ```

   Local: `docker compose -f deployment/local/docker-compose.yml logs
   --since <since> | grep <id>` and the same `grep` over the host
   processes' log files. `caused_by_request_id` follows the request
   across a handoff into a worker.
6. The trace, by request id. Cloud:

   ```bash
   aws xray get-trace-summaries --profile tadas-<env>-investigate \
     --start-time <start> --end-time <end> \
     --filter-expression 'annotation.request_id = "<id>"'
   ```

   Local: `curl -s "$TADAS_JAEGER_URL/api/traces?service=tadas-api&tags=%7B%22request_id%22%3A%22<id>%22%7D"`.
   The trace says where the time went and which span failed.
7. Or in one call, the same four reads through the platform's own
   binary, which holds the twins and the cloud behind one interface:

   ```bash
   uv run tadas-ops signals check --env <env> --request-id <id>
   ```

8. Correlate. One request id ties the event row (what the tenant
   asked), the log lines (what the process decided), the trace (where
   it waited), and the error event (where it broke). The cause is the
   first of those that disagrees with the code's intent; read the
   code at the file and line the error names with `Read` and `Grep`.
9. Write the report. The fix is a pull request, a setting, or a
   resource, named; it is never applied here.

## What it never does

- No write to the cloud, no write to the tenant: only `GET` routes of
  the operator plane, only a `READ` identity.
- No database login: `rds-db:connect` is denied to the role; the
  compose Postgres is not opened either, so `local` proves the same
  path the cloud runs.
- No secret value printed, no bearer written to the report.
- No data outside `--org`: no list of orgs, no cross-tenant query, no
  second org id "for comparison".
- No `terraform apply`, no console clicks.

## Output

```markdown
# Root cause: <env>, org <org_id>[, user <user_id>]

**Credential.** <profile and Arn, or local>; operator <email domain only>, READ
**Tenant.** <name>, <members> members, <n> events in the last <since>
**Request.** <request id>, <route>, <status>, <when>

## Timeline

- <time> event: <kind> by <actor id>
- <time> log: <line>
- <time> trace: <span>, <ms>
- <time> error: <exception> at <file>:<line>

## Cause

<one paragraph: what happened, where, and why, with the line of code
or the row or the resource that decided it>

## Fix

<the pull request, setting, or resource change, one sentence each;
nothing applied>
```

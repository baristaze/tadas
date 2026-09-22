---
name: ops-investigate
description: "Investigate one environment of the platform with a read-only credential: the alarms, the error rate, the latency, the worker outcomes, the pool, the queue, the cost against the budget, and the platform's size, then report what is wrong and what to do next. Every read goes through the signals' own APIs (CloudWatch, X-Ray, the error tracker in the cloud; Prometheus, Jaeger, GlitchTip locally). Use when something looks off, when an alarm fires, or as the daily look. Never writes."
allowed-tools: Read, Grep, Glob, Bash(aws:*), Bash(curl:*), Bash(docker compose:*), Bash(uv run:*)
---

# ops-investigate

One environment, one window, one credential that can only read. The
skill looks at every signal the platform emits and says what is wrong,
how big the platform is, and which skill runs next. It changes
nothing.

## Input

`--env local|staging|production [--since 1h] [--request-id <id>] [--alarm <name>]`

`--env` is required; ask for it when missing. `--since` is the window,
a duration ending now, one hour by default. `--request-id` narrows the
look to one request across every signal. `--alarm` starts from one
alarm by name and reads the platform's size before anything else.

`local` reads the compose stack's twins (Prometheus, Jaeger, GlitchTip,
`docker compose logs`) and needs no cloud. The skill is testable with
no account.

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
Refuse to run under any other identity, the administrator profiles
(`tadas-staging-admin`, `tadas-prod-admin`) above all, and the bare
sign-in profiles (`tadas-staging`, `tadas-prod`), whose permission
sets (PowerUserAccess, TadasReadOnly) are wider than the role. A wider credential is not a convenience; it is
the boundary gone. Every `aws` command below carries
`--profile tadas-<env>-investigate`. Never read `AWS_PROFILE` as a
substitute.

Check the account too: `Account` in the same answer must equal the
environment's `account_id` in `deployment/cloud/environments.json`
(read the file; the value is `.environments.<env>.account_id`). Stop on
a mismatch: the right role in the wrong account is the wrong credential.

The env file `~/.config/tadas/ops/<env>.env` is owner-only and outside
the repository. It holds `TADAS_API_URL`, `TADAS_OPERATOR_EMAIL`,
`TADAS_OPERATOR_PASSWORD` (a `read` entry; the file's `write` entry,
`TADAS_PROVISIONER_EMAIL` with `TADAS_PROVISIONER_PASSWORD`, belongs to
the traffic generator alone), `TADAS_ERROR_TRACKER_URL`, and
`TADAS_ERROR_TRACKER_TOKEN`. `local.env` points at the compose stack
and adds the twins, `TADAS_PROMETHEUS_URL` and `TADAS_JAEGER_URL`, on
the ports `.env` names. Read the file, use its values in commands, and
never print the password or the token.

## Procedure

1. Verify the credential as Role and credential states. Read the env
   file. Compute the window: `--since` back from now, as epoch seconds
   for the cloud and as a Prometheus range for local.
2. Read the platform's size first:

   ```bash
   uv run tadas-ops size --env <env>
   ```

   It prints tenants, users, and the entities written in the last day
   (for a to-do product, the tasks and the events), through `GET /v1/admin/size` with the env file's
   operator identity. A platform of one tenant and one user is the
   developer. Every finding below is read against this number.
3. Alarms. Cloud:

   ```bash
   aws cloudwatch describe-alarms --alarm-name-prefix tadas-<env>- \
     --profile tadas-<env>-investigate
   ```

   Local has no alarm topic: run the alarm conditions as Prometheus
   queries against `$TADAS_PROMETHEUS_URL/api/v1/query`, over the
   window `[<since>]`:

   - 5xx ratio: `sum(rate(tadas_http_requests_total{status=~"5.."}[<since>])) / sum(rate(tadas_http_requests_total[<since>]))`, alarm above 0.01
   - targets up: `up{job!="prometheus"}`, alarm on any 0 (a host process
     and a container are two targets of one job; one of them is down
     by design)
   - p95 latency: `histogram_quantile(0.95, sum by (le) (rate(tadas_http_request_seconds_bucket[<since>])))`, alarm above 1 s
   - running processes: the `up` targets again, one per process
   - the database's CPU and free storage: no local exporter; report
     them as not read
   With `--alarm <name>`, start here and apply the first responder
   rule of step 10 before reading anything else.
4. Request rate, error ratio, p95, by route. Cloud, one query per
   panel of the dashboard `tadas-<env>`, namespace `Tadas`:

   ```bash
   aws cloudwatch get-metric-data --profile tadas-<env>-investigate \
     --start-time <start> --end-time <end> \
     --metric-data-queries '[{"Id":"req","Expression":"SUM(SEARCH('"'"'{Tadas,environment,method,route,service,status} MetricName=\"tadas_http_requests_total\" environment=\"<env>\"'"'"', '"'"'Sum'"'"', 60))","Period":60}]'
   ```

   Every series carries all its labels as dimensions and CloudWatch
   matches dimensions exactly, so a `MetricStat` naming only some of
   them finds nothing; the `SEARCH` expression is the dashboard's own.

   Local:

   ```bash
   curl -sG "$TADAS_PROMETHEUS_URL/api/v1/query" \
     --data-urlencode 'query=sum by (route, status) (rate(tadas_http_requests_total[5m]))'
   curl -sG "$TADAS_PROMETHEUS_URL/api/v1/query" \
     --data-urlencode 'query=histogram_quantile(0.95, sum by (le, route) (rate(tadas_http_request_seconds_bucket[5m])))'
   ```

5. Workers, queue, pool, cache: one counter carries every outcome,
   `tadas_outcomes_total{subsystem, outcome}` (subsystems `worker`,
   `outbox`, `queue`, `cache`, `rate_limit`, `admission`,
   `idempotency`), read as `sum by (subsystem, outcome)
   (increase(tadas_outcomes_total[<since>]))`. Queue depth, the oldest
   age, and pool checkouts have no metric; the cloud reads the queue
   from `aws sqs get-queue-attributes` and the pool from the database's
   connection count. Cloud also reads the
   running count against the desired count:

   ```bash
   aws ecs describe-services --cluster tadas-<env> \
     --services tadas-<env>-api tadas-<env>-maintenance \
     --profile tadas-<env>-investigate
   ```

6. Errors. Cloud: the error tracker's REST API at
   `$TADAS_ERROR_TRACKER_URL` with the token as a bearer, the issues
   of the window, newest first. Local: the same shape against
   GlitchTip:

   ```bash
   curl -s -H "Authorization: Bearer $TADAS_ERROR_TRACKER_TOKEN" \
     "$TADAS_ERROR_TRACKER_URL/api/0/organizations/<org>/issues/?statsPeriod=<since>"
   ```

   `<org>` is the slug `GET /api/0/organizations/` lists (locally
   `tadas`):

   ```bash
   curl -s -H "Authorization: Bearer $TADAS_ERROR_TRACKER_TOKEN" "$TADAS_ERROR_TRACKER_URL/api/0/organizations/"
   ```

7. Logs. Cloud, one log group per process, `/tadas/<env>/<process>`:

   ```bash
   aws logs start-query --profile tadas-<env>-investigate \
     --log-group-names /tadas/<env>/api /tadas/<env>/maintenance \
     --start-time <start> --end-time <end> \
     --query-string 'fields @timestamp, level, request_id, @message | filter level = "ERROR" | sort @timestamp desc | limit 100'
   aws logs get-query-results --query-id <id> --profile tadas-<env>-investigate
   ```

   Local: `docker compose -f deployment/local/docker-compose.yml -f
   deployment/local/docker-compose.full.yml logs --since <since> api
   maintenance` from the repository root when the processes
   run in containers. When they run on the host (`scripts/dev.sh`
   writes no file; it logs to its terminal), `grep` the file the
   process was started with, and say "not read" when there is none.
   A local line carries the request id in brackets, `[<id>]`, or as
   `"request_id"` when `TADAS_LOG_JSON` is on.
   With `--request-id`, filter every source on it: `filter request_id
   = "<id>"` in the cloud, `grep` locally.
8. Traces. Cloud:

   ```bash
   aws xray get-trace-summaries --profile tadas-<env>-investigate \
     --start-time <start> --end-time <end> \
     --filter-expression 'service("tadas-api") AND responsetime > 1'
   ```

   Local, Jaeger's v3 API (the service is the process name, `api`, and
   the request id is the span attribute `tadas.request_id`):

   ```bash
   curl -sG "$TADAS_JAEGER_URL/api/v3/traces" \
     --data-urlencode query.service_name=api \
     --data-urlencode "query.start_time_min=<start, RFC 3339>" \
     --data-urlencode "query.start_time_max=<end, RFC 3339>" \
     --data-urlencode query.duration_min=1s
   ```

   and filter the spans on the attribute client-side; the query API
   ignores attribute filters. An empty answer means the process ran
   with no `TADAS_OTEL_ENDPOINT`, which is a finding, not an error.
   With `--request-id`, filter on the `tadas_request_id` annotation in the
   cloud and the `tadas.request_id` attribute locally instead.
9. Cost, cloud only. The month to date against the budget:

   ```bash
   aws ce get-cost-and-usage --profile tadas-<env>-investigate \
     --time-period Start=<first of month>,End=<today> \
     --granularity MONTHLY --metrics UnblendedCost \
     --filter '{"Tags":{"Key":"environment","Values":["<env>"]}}'
   aws budgets describe-budgets --account-id <account> \
     --profile tadas-<env>-investigate
   ```

10. The first responder rule. In production nothing is suppressed:
    a new production's one tenant is its first customer, so every
    alarm and finding there is reported as a finding, with the request
    ids that prove it. Outside production, an alarm or a finding is
    read against the size of step 2, and it is suppressed only when
    the traffic behind it is the team's own: one tenant and one user,
    and that user is the team's. A suppression is never silent: it is
    reported as suppressed, with the reason, the size, and the request
    ids it rests on.
11. Write the report. Name the next skill: `ops-root-cause` with an
    org id when one tenant's rows explain it, `ops-watch` when the
    signal is still moving, `ops-infra-as-code` when the fix is a
    resource.

## What it never does

- No write to the cloud: no `aws` verb that is not `get`, `describe`,
  `list`, `start-query`, `get-query-results`, or `tail`.
- No secret value printed: the password and the token stay in the env
  file, `aws secretsmanager get-secret-value` is denied to the role
  and never attempted.
- No tenant data: the signals carry no tenant id, and this skill reads
  no tenant's rows. That is `ops-root-cause`, for one named tenant.
- No `terraform apply`, no console clicks, no scaling by hand.
- No re-reading a wider window than asked; a longer look is a second
  run with a longer `--since`.

## Output

```markdown
# Investigation: <env>, last <since>

**Credential.** <profile and the Arn it resolved to, or local>
**Size.** <tenants> tenants, <users> users, <n> written in the last day

## Alarms

- <alarm name>: <state since when>, <suppressed: reason | escalated>

## Signals

- Requests: <rate>, error ratio <ratio>, p95 <ms> by route
- Workers: <outcomes per kind>, queue depth <n>, oldest <age>
- Pool and cache: <checkouts, timeouts, hits, misses>
- Errors: <count>, top issue <title> (<request id, or none>)
- Cost: <month to date> of <budget> USD (cloud only)

## Findings

- <what is wrong, one sentence, with the request id that proves it>

## Next

<the skill to run next, with its arguments, or "nothing">
```

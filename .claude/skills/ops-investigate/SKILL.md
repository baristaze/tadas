---
name: ops-investigate
description: "Investigate one environment of the platform with a read-only credential: the alarms, the error rate, the latency, the worker outcomes, the pool, the queues and their dead letters, the providers (sign-in, billing, the Slack bridge), the cost against the budget, and the platform's size, then report what is wrong and what to do next. Every read goes through the signals' own APIs (CloudWatch, X-Ray, the error tracker in the cloud; Prometheus, Jaeger, GlitchTip locally). Use when something looks off, when an alarm fires, or as the daily look. Never writes."
allowed-tools: Read, Grep, Glob, Bash(aws:*), Bash(curl:*), Bash(docker compose:*), Bash(uv run:*)
---

# ops-investigate

One environment, one window, one credential that can only read. The
skill looks at every signal the platform emits and says what is wrong,
how big the platform is, and which skill runs next. It changes
nothing.

Read `.claude/skills/_shared/ops-preamble.md` before the first step:
the profiles, the account check, and the env file are there.

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

`--env staging` and `--env production` run under the investigate
profile of that environment, `tadas-<env>-investigate`, checked with
`sts get-caller-identity` before any other command as the preamble
states. Refuse any profile wider than the investigate role. Every
`aws` command below carries `--profile tadas-<env>-investigate`.

The env file `~/.config/tadas/ops/<env>.env` gives the API's URL, the
`read` operator token, and the error tracker's URL, token, org, and
project; the file's `TADAS_PROVISIONER_TOKEN`, a `write` token,
belongs to the traffic generator alone and is not used here. Never
read the env file; a command that needs a value sources it in the same
command, as every block below does. Never print a token. On a `401`
the token has expired: stop, and name the refresh the preamble gives.

## Procedure

The processes are `api`, `maintenance`, and `slack` (the Slack bridge,
one task that holds the Socket Mode connection), as
`deployment/README.md` lists them. Each is an ECS service of that
name in the cluster `tadas-<env>`, with the log group
`/tadas/<env>/<process>`. The queues are `tadas-<env>-webhooks` (the
payment processor's deliveries) and `tadas-<env>-slack` (what Slack
sent), each with a dead-letter queue named with `-dead` after it.

1. Verify the credential as Role and credential states. Compute the
   window: `--since` back from now, as epoch seconds
   for the cloud and as a Prometheus range for local.
2. Read the platform's size first:

   ```bash
   uv run tadas-ops size --env <env>
   ```

   It prints tenants, users, and the entities written in the last day
   (for a to-do product, the tasks and the events), through `GET /v1/admin/size`
   with the env file's operator token (`uv run tadas-ops size --env <env>`,
   which leaves the traffic generator's own tenants out). A platform
   of one tenant and one user is the developer. Every finding below is
   read against this number and against whose traffic it was.
3. Alarms. Cloud:

   ```bash
   aws cloudwatch describe-alarms --alarm-name-prefix tadas-<env>- \
     --profile tadas-<env>-investigate
   ```

   Local has no alarm topic: run the alarm conditions as Prometheus
   queries against `$TADAS_PROMETHEUS_URL/api/v1/query`, over the
   window `[<since>]`, each `curl` sourcing the env file in the same
   command:

   - 5xx ratio: `sum(rate(tadas_http_requests_total{status=~"5.."}[<since>])) / sum(rate(tadas_http_requests_total[<since>]))`, alarm above 0.01
   - targets up: `up{job!="prometheus"}`, alarm on any 0 (a host process
     and a container are two targets of one job; one of them is down
     by design)
   - p95 latency: `histogram_quantile(0.95, sum by (le) (rate(tadas_http_request_seconds_bucket[<since>])))`, alarm above 1 s
   - running processes: the `up` targets again, one per process
   - the database's CPU and free storage: no local exporter; report
     them as not read
   With `--alarm <name>`, start here and apply the first responder
   rule of step 11 before reading anything else.
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
   set -a; . ~/.config/tadas/ops/<env>.env; set +a
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
   age, and pool checkouts have no metric; the cloud reads the pool
   from the database's connection count, and each queue and its dead
   letter from SQS:

   ```bash
   for q in webhooks webhooks-dead slack slack-dead; do
     url="$(aws sqs get-queue-url --queue-name tadas-<env>-$q \
       --query QueueUrl --output text --profile tadas-<env>-investigate)"
     aws sqs get-queue-attributes --queue-url "$url" --profile tadas-<env>-investigate \
       --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
   done
   ```

   A message in a `-dead` queue is a delivery the worker could not
   handle after its retries: a finding, with the queue's name. Cloud
   also reads the running count against the desired count. `slack`
   runs exactly one task; zero running means no `/tadas` command is
   answered:

   ```bash
   aws ecs describe-services --cluster tadas-<env> \
     --services api maintenance slack \
     --profile tadas-<env>-investigate
   ```

6. Errors. There is one tracker project for the product, and every
   environment reports into it, so the read names that project and
   filters on the environment. Cloud: the error tracker's REST API at
   `$TADAS_ERROR_TRACKER_URL` with the token as a bearer, the issues
   of the window in this environment, newest first. Local: the same
   shape against GlitchTip, with `local` as the environment:

   ```bash
   set -a; . ~/.config/tadas/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $TADAS_ERROR_TRACKER_TOKEN" --get \
     --data-urlencode "query=environment:<env>" --data "statsPeriod=<since>" \
     "$TADAS_ERROR_TRACKER_URL/api/0/projects/$TADAS_ERROR_TRACKER_ORG/$TADAS_ERROR_TRACKER_PROJECT/issues/"
   ```

   An issue in that project can hold events of more than one
   environment, so an issue the query returned is not by itself this
   environment's: read its events
   (`/api/0/issues/<issue id>/events/`) and keep the ones whose
   `environment` tag is `<env>`. Dropping the filter reports every
   environment's errors as this one's, which is wrong, not wider.

   The org's slug is what `GET /api/0/organizations/` lists (locally
   `tadas`):

   ```bash
   set -a; . ~/.config/tadas/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $TADAS_ERROR_TRACKER_TOKEN" "$TADAS_ERROR_TRACKER_URL/api/0/organizations/"
   ```

   When the env file names no tracker, this step reads nothing and the
   report says "not read", never "no errors"; the other steps stand on
   their own, and an investigation is not stopped by it.

7. Logs. Cloud, one log group per process, `/tadas/<env>/<process>`:

   ```bash
   aws logs start-query --profile tadas-<env>-investigate \
     --log-group-names /tadas/<env>/api /tadas/<env>/maintenance /tadas/<env>/slack \
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
8. The providers. Each of the three says in its own log when it is
   not configured, and the skill reads that, never a secret: the
   secrets are denied to the role, and their names are enough. Cloud,
   over the same window:

   ```bash
   aws logs start-query --profile tadas-<env>-investigate \
     --log-group-names /tadas/<env>/api /tadas/<env>/maintenance /tadas/<env>/slack \
     --start-time <start> --end-time <end> \
     --query-string 'fields @timestamp, @log, @message | filter @message like /identity provider|WorkOS application|WorkOS credential check|payments=stripe|billing_unavailable|no Slack app token|no bot token|socket mode connection/ | sort @timestamp desc | limit 50'
   ```

   What each line means, and the secret it points to:

   - `identity provider: none (TADAS_WORKOS_API_KEY is not set)` and
     `every sign-in through one answers 503`: nobody can sign in
     through WorkOS. `tadas/<env>/workos_api_key` is `off`, or the
     API's tasks started before it was written.
   - `TADAS_WORKOS_API_KEY is not the API key of the WorkOS application`,
     and the API's tasks stop at start: the secret holds a key WorkOS
     refuses as the Tadas App's (the environment's API key, another
     application's, or the other WorkOS environment's). The key belongs
     on the Tadas App's own API keys tab. `the WorkOS credential check
     did not finish` or `answered` is a warning only: WorkOS could not
     say, and the API started.
   - `payments=stripe (not configured)`, or `billing_unavailable` on a
     request: checkouts answer 503 and every org keeps its plan.
     `tadas/<env>/stripe_runtime_key` is `off`. `payments=stripe
     (acct_..., <version>; the key lacks <resource>, ...)` names what
     the runtime key could not read at start, and the log line `the
     stripe runtime key lacks <resource> (group <group>)` says where
     the dashboard's editor keeps it: the person adds it to the key,
     which takes effect at once. A `503` on
     `/webhooks/stripe` is `tadas/<env>/stripe_webhook_secret`; a
     `400` there is a signing secret that does not match the
     endpoint's, and the processor retries it.
   - `no Slack app token is set; the Socket Mode connection stays
     closed` in `/tadas/<env>/slack`: `/tadas` answers nothing.
     `tadas/<env>/slack_app_token` is `off`. `slack socket mode
     connection is open` is the healthy line.
   - `slack post <id> dropped: no bot token is configured` in
     `/tadas/<env>/maintenance`: reminders go nowhere.
     `tadas/<env>/slack_bot_token` is `off`.

   The start lines are written once, when a task starts, so a window
   after the last rollout holds none: report "not in the window",
   never "configured". A finding here names the secret and
   `docs/runbooks/providers/<stripe|workos|slack>.md`; writing the
   value is a person's step under their own sign-in, never this
   skill's. Locally, `grep` the same lines in each process's own
   output, as step 7 reads it; a laptop holds no Slack app token on
   purpose, so a closed connection there is not a finding.
9. Traces. Cloud:

   ```bash
   aws xray get-trace-summaries --profile tadas-<env>-investigate \
     --start-time <start> --end-time <end> \
     --filter-expression 'service("tadas-api") AND responsetime > 1'
   ```

   Local, Jaeger's v3 API (the service is the process name, `api`, and
   the request id is the span attribute `tadas.request_id`):

   ```bash
   set -a; . ~/.config/tadas/ops/<env>.env; set +a
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
10. Cost, cloud only. The month to date against the budget:

   ```bash
   aws ce get-cost-and-usage --profile tadas-<env>-investigate \
     --time-period Start=<first of month>,End=<today> \
     --granularity MONTHLY --metrics UnblendedCost \
     --filter '{"Tags":{"Key":"environment","Values":["<env>"]}}'
   aws budgets describe-budgets --account-id <account> \
     --profile tadas-<env>-investigate
   ```

11. The first responder rule. In production nothing is suppressed:
    a new production's one tenant is its first customer, so every
    alarm and finding there is reported as a finding, with the request
    ids that prove it. Outside production, an alarm or a finding is
    read against the size of step 2, and it is suppressed only when
    the traffic behind it is the team's own: one tenant and one user,
    and that user is the team's. A suppression is never silent: it is
    reported as suppressed, with the reason, the size, and the request
    ids it rests on.
12. Write the report. Name the next skill: `ops-root-cause` with an
    org id when one tenant's rows explain it, `ops-watch` when the
    signal is still moving, `ops-infra-as-code` when the fix is a
    resource.

## What it never does

- No write to the cloud: no `aws` verb that is not `get`, `describe`,
  `list`, `start-query`, `get-query-results`, or `tail`.
- No secret value read or printed: the tokens stay in the env file,
  which is sourced and never read, and
  `aws secretsmanager get-secret-value` is denied to the role and
  never attempted.
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
- Queues: webhooks <n> (dead <n>), slack <n> (dead <n>); services api, maintenance, slack <running>/<desired>
- Providers: sign-in <configured | off: tadas/<env>/workos_api_key | not in the window>, billing <configured | off: tadas/<env>/stripe_runtime_key | lacks <resources>>, Slack posts <...: tadas/<env>/slack_bot_token>, Slack connection <open | closed: tadas/<env>/slack_app_token>
- Pool and cache: <checkouts, timeouts, hits, misses>
- Errors: <count>, top issue <title> (<request id, or none>), or "not
  read: the environment names no error tracker"
- Cost: <month to date> of <budget> USD (cloud only)

## Findings

- <what is wrong, one sentence, with the request id that proves it>

## Next

<the skill to run next, with its arguments, or "nothing">
```

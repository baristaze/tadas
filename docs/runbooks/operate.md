# Operate: read an environment

Every read of a deployed environment runs under its investigate profile,
and nothing that writes runs under it. This runbook says what to run
there. The `ops-investigate`, `ops-watch`, `ops-root-cause`, and
`ops-integration-silent` skills run the same commands; [ops/README.md](../../ops/README.md) names the
roles and the skills.

## The profile

`tadas-staging-investigate` and `tadas-production-investigate` assume
`tadas-investigate-<environment>`. It reads every log, metric, trace,
alarm, and resource, and the Terraform state. It is denied a secret's
value, an object in a data bucket, a database connection, the other
environment, and every IAM write. It chains from a person's Identity
Center sign-in, so sign in first:

```bash
aws sso login --profile tadas-staging              # or tadas-prod
export AWS_PROFILE=tadas-staging-investigate       # or tadas-production-investigate
aws sts get-caller-identity --query Arn --output text
# arn:aws:sts::<account>:assumed-role/tadas-investigate-staging/<session>
```

A skill that sees any other role in that answer stops. The commands
below are staging's; production's replace `staging` with `production`.

## The dashboard

One CloudWatch dashboard per environment, `tadas-<environment>`, from
`deployment/terraform/modules/dashboard`. Its first panels match the
local Grafana dashboard by title: targets up, requests and responses per
second, p95 latency, and outcomes per second. The rest are the cloud's:
the database, the cache, the queue, the running tasks, the sweep's pass
duration, the work queue's oldest ready item, and the outbox's oldest
pending row. Application metrics live in the `Tadas` namespace.

```bash
aws cloudwatch get-dashboard --dashboard-name tadas-staging \
  --query DashboardBody --output text | jq '.widgets[].properties.title'
```

The long-running records, the imports and each org's daily cleanup of
old done tasks, show on Outcomes per second under the subsystem
`orchestrations`, one outcome per kind and state (`task_cleanup_running`
when the sweep opens an org's day, `task_cleanup_succeeded`,
`task_import_parked`, `task_import_failed`). A failure that is a defect
is also an `ERROR` line in `/tadas/<environment>/maintenance` naming the
record and its org; reading that one org's rows is `ops-root-cause`.

## The alarms

All go to the topic `tadas-<environment>-alarms`, from
`deployment/terraform/modules/alarms`. The thresholds are the module's
defaults, and a busier platform moves them.

| Alarm | Fires when |
|-------|------------|
| `-http-5xx-ratio` | more than 5 percent of requests answer 5xx |
| `-http-p95-latency` | the load balancer's p95 passes 1 second |
| `-unhealthy-targets` | an API target fails its health check |
| `-read-latency-v1-billing` | `GET /v1/billing` passes 1 second at p95 |
| `-database-cpu`, `-database-free-storage` | CPU passes 80 percent; free storage falls under 2 GiB |
| `-webhooks-backlog`, `-webhooks-dead-letter` | the inbound queue's oldest message waited ten minutes; a message reached its `-dead` twin |
| `-slack-backlog`, `-slack-dead-letter` | Slack's queue's oldest message waited ten minutes; a message reached its `-dead` twin |
| `-sweep-duration` | a sweep pass took longer than 30 seconds |
| `-work-backlog`, `-work-dead-letter` | a ready work item waited ten minutes; an item failed for good |
| `-outbox-lag`, `-outbox-dead-letter` | the oldest pending outbox row is five minutes old; a row failed for good |
| `-api-tasks-below-desired`, `-maintenance-tasks-below-desired` | a service runs fewer tasks than it wants |

The work and outbox numbers come from the worker's own log line each
sweep pass, turned into metrics by filters, since both live in
Postgres. A worker that is not running writes no line, and the tasks
alarm reports it.

```bash
aws cloudwatch describe-alarms --alarm-name-prefix tadas-staging- \
  --query 'MetricAlarms[].{name:AlarmName,state:StateValue,since:StateUpdatedTimestamp}' --output table
```

Before escalating, read the platform's size: an alarm on a platform of
one tenant is a developer at work.

```bash
uv run tadas-ops size --env staging
```

Then read behind the alarm by request id:

```bash
uv run tadas-ops signals check --env staging --request-id <request id>
aws logs tail /tadas/staging/api --since 15m --format short
aws ecs describe-services --cluster tadas-staging --services api maintenance \
  --query 'services[].{name:serviceName,desired:desiredCount,running:runningCount}' --output table
```

An outbox lag is a relay that keeps failing. The worker's warning line
names the row, its kind, and the error. `the bus dropped the publish`
means Valkey refused the push or its breaker is open: the event is
already in the stream, and the row waits until the bus takes it
([ADR 0062](../adr/0062-a-dropped-publish-leaves-its-outbox-row-pending.md)).
Fix Valkey, and the next pass sends the backlog.

## A client answered 429

A 429 is `rate_limited` with a `Retry-After`, and its message names the
budget ([ADR 0059](../adr/0059-authenticated-routes-have-limits.md)):

| Message | Budget | Setting |
|---------|--------|---------|
| `rate limit exceeded`, on a sign-in route | the address's sign-ins | `TADAS_LOGIN_RATE_LIMIT` |
| `rate limit exceeded`, elsewhere | the credential's reads or writes | `TADAS_CREDENTIAL_RATE_LIMIT_READS`, `TADAS_CREDENTIAL_RATE_LIMIT_WRITES` |
| `too many failed authentications from this address` | the address's failed lookups | `TADAS_FAILED_AUTHENTICATION_LIMIT` |

A window is a minute, and the refusal lifts when it ends. A credential's
budget spent is usually a client polling too fast: ask it to listen on
the realtime channel. An address's budget spent is a client holding a
revoked key, or someone trying tokens; everyone behind that address
waits out the window. Raise a budget only when honest traffic needs it,
through the environment's `app_environment` and a deploy. The limits
fail open while the cache is down.

## A work item that failed for good

An item fails for good when its attempts run out, or at once when a
provider refused the call itself. It stays failed until a person sends it
back. The worker's log names it:

```bash
aws logs tail /tadas/staging/maintenance --since 24h --format short --filter-pattern '"failed for good"'
# work item <item id> (DELETE_ACCOUNT) in org <org id> failed for good: ...
```

The org's stream holds it too, as a `work.item.failed` event. Fix the
cause first. Then a person with a `write` operator entry sends it back,
in their own terminal; no agent runs it:

```bash
uv run tadas-ops work requeue --env staging --org <org id> <item id>
```

It signs the person in with the second factor, mints a `write` token for
that one call, and signs the token out after. The item runs again with
every attempt it had, and a `work.item.requeued` event names the
operator. An item that is not failed is refused.

## The costs

Each account has its own budget (`tadas-<environment>-monthly`) and
anomaly monitor, so the account's bill is the environment's. Every
resource also carries `tadas:environment`.

```bash
account=$(aws sts get-caller-identity --query Account --output text)
aws budgets describe-budget --account-id "$account" --budget-name tadas-staging-monthly \
  --query 'Budget.{limit:BudgetLimit.Amount,spent:CalculatedSpend.ActualSpend.Amount}'
aws ce get-cost-and-usage --time-period "Start=$(date +%Y-%m-01),End=$(date +%F)" \
  --granularity MONTHLY --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[].{service:Keys[0],usd:Metrics.UnblendedCost.Amount}' --output table
```

A cost that moved is read by service first (what grew), then on the
dashboard (why: traffic, a scale-out, a retention that lapsed).

## What this profile cannot do

Change anything. A threshold, a subscription, a scale-out, a retention:
each is a pull request to `deployment/terraform`, applied by the deploy.
An `AccessDenied` on a secret, a data bucket, or a deploy role is the
profile working as meant.

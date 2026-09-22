# Operate: read an environment under the investigate profile

Every read of an environment runs under its investigate profile, and
nothing that writes runs under it. `tadas-staging-investigate` and
`tadas-production-investigate` assume `tadas-investigate-<environment>`,
a role with `ReadOnlyAccess` plus the signal reads that policy leaves
out, fenced off secret values, data bucket objects, database
connections, the other environment, and every IAM write. An agent
holding it may look at everything it reaches. Each environment has an
AWS account of its own, so the profile also decides the account. The
investigate profile chains from a person's Identity Center sign-in
(`tadas-staging`, `tadas-prod`), so sign in first. [deploy.md](deploy.md)
says how the profiles are made; this runbook says what to run under
them. The `ops-investigate`, `ops-watch`, and `ops-root-cause` skills
run these same commands.

First, every time:

```bash
aws sso login --profile tadas-staging            # or tadas-prod; once per session
export AWS_PROFILE=tadas-staging-investigate   # or tadas-production-investigate
aws sts get-caller-identity --query Arn --output text
# arn:aws:sts::<account>:assumed-role/tadas-investigate-staging/<session>
```

A skill that sees any other role in that answer stops, the sign-in's
PowerUserAccess role included. The commands
below are staging's; production's replace `staging` with `production`
in every name.

## The dashboard

One CloudWatch dashboard per environment, `tadas-<environment>`,
declared in `deployment/terraform/modules/dashboard` from
`dashboard.json.tftpl`. Its first five widgets are the local Grafana
dashboard's panels by title (`infra/tests/test_dashboard_parity.py`
holds them equal): Targets up, HTTP requests per second by route, HTTP
responses per second by status, HTTP latency p95 by route, Outcomes per
second. The last row is the cloud's own: the database's CPU and
connections, the cache's CPU, the queue's visible and dead messages,
the running tasks.

```bash
aws cloudwatch get-dashboard --dashboard-name tadas-staging \
  --query DashboardBody --output text | jq '.widgets[].properties.title'
```

The application metrics live in the `Tadas` namespace with every
Prometheus label as a dimension. The three the dashboard reads:

```bash
aws cloudwatch list-metrics --namespace Tadas --metric-name tadas_http_requests_total \
  --dimensions Name=environment,Value=staging \
  --query 'Metrics[].Dimensions[?Name==`route`].Value' --output text | sort -u

now=$(date +%s); aws cloudwatch get-metric-data \
  --start-time "$((now - 3600))" --end-time "$now" \
  --metric-data-queries '[{"Id":"rps","Expression":"SUM(SEARCH('"'"'{Tadas,environment,method,route,service,status} MetricName=\"tadas_http_requests_total\" environment=\"staging\"'"'"', '"'"'Sum'"'"', 60)) / 60","Label":"requests per second"}]' \
  --query 'MetricDataResults[0].Values[:10]'
```

## The alarms

Seven per environment (one of them per service), to the topic `tadas-<environment>-alarms`, from
`deployment/terraform/modules/alarms`. Their thresholds are the
module's inputs with defaults: 5 percent 5xx, 1 second p95, 80 percent
database CPU, 2 GiB free storage, one unhealthy target, one task below
desired; three periods of one minute each, six for the tasks below
desired, which a routine worker deploy would otherwise trip.

```bash
aws cloudwatch describe-alarms --alarm-name-prefix tadas-staging- \
  --query 'MetricAlarms[].{name:AlarmName,state:StateValue,since:StateUpdatedTimestamp}' --output table

aws cloudwatch describe-alarm-history --alarm-name tadas-staging-http-5xx-ratio \
  --history-item-type StateUpdate --max-items 10 \
  --query 'AlarmHistoryItems[].{at:Timestamp,what:HistorySummary}' --output table
```

The first responder is an agent. Before it escalates, it reads the
platform's size (`uv run tadas-ops size --env staging`): an alarm on a
platform of one tenant and one user is the developer at work. What it
cannot explain, it escalates with everything it read.

Reading behind an alarm, by request id:

```bash
# The log line that names it, from the last hour.
now=$(date +%s); query=$(aws logs start-query --log-group-name /tadas/staging/api \
  --start-time "$((now - 3600))" --end-time "$now" \
  --query-string 'fields @timestamp, @message | filter request_id = "<request id>" | sort @timestamp' \
  --query queryId --output text)
sleep 2; aws logs get-query-results --query-id "$query" --query 'results[][].value' --output text

# A live tail while something is happening; ops-watch runs this in a loop.
aws logs tail /tadas/staging/api --since 15m --format short

# The trace, then its segments.
aws xray get-trace-summaries --start-time "$((now - 3600))" --end-time "$now" \
  --filter-expression 'http.url CONTAINS "/v1/tasks"' \
  --query 'TraceSummaries[].{id:Id,ms:Duration,error:HasError}' --output table
aws xray batch-get-traces --trace-ids <trace id> --query 'Traces[0].Segments[].Document' --output text | jq .

# What runs, and what wants to run.
aws ecs describe-services --cluster tadas-staging --services api maintenance \
  --query 'services[].{name:serviceName,desired:desiredCount,running:runningCount,rollout:deployments[0].rolloutState}' --output table
aws rds describe-db-instances --db-instance-identifier tadas-staging \
  --query 'DBInstances[0].{status:DBInstanceStatus,class:DBInstanceClass,storage:AllocatedStorage,max:MaxAllocatedStorage}'
aws sqs get-queue-attributes --queue-url "$(aws sqs get-queue-url --queue-name tadas-staging-webhooks-dead --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages
```

What the role refuses, by design, and what the refusal looks like:

```bash
aws secretsmanager get-secret-value --secret-id tadas/staging/database_url   # AccessDeniedException
aws s3 cp s3://tadas-staging-exports/some/key -                              # AccessDenied
aws sts assume-role --role-arn arn:aws:iam::<account>:role/tadas-deploy-staging --role-session-name x   # AccessDenied
```

Planning an infrastructure change is a read too. The role reads
staging's state and takes no lock, so the plan is the pull request's
preview and nothing more (`ops-infra-as-code`):

```bash
terraform -chdir=deployment/terraform/environments/staging init -input=false \
  -backend-config="bucket=tadas-state-<account>" \
  -backend-config="key=environments/staging/terraform.tfstate" \
  -backend-config="region=us-west-2"
terraform -chdir=deployment/terraform/environments/staging plan -lock=false -refresh=false \
  -var "api_image=<the digest deployed>" -var "maintenance_image=<the digest deployed>" \
  -var "api_domain_name=api.staging.tadas.fyi" -var "app_domain_name=app.staging.tadas.fyi" \
  -var "alarm_email=$ALARM_EMAIL"
```

The account and the two names are staging's entry in
`deployment/cloud/environments.json`.

## The costs

Each account has its own budget and anomaly monitor, declared by its
bootstrap root, so the account's bill is the environment's. The
`tadas:environment` tag on every resource splits a report the same way.

```bash
account=$(aws sts get-caller-identity --query Account --output text)
aws budgets describe-budget --account-id "$account" --budget-name tadas-staging-monthly \
  --query 'Budget.{limit:BudgetLimit.Amount,spent:CalculatedSpend.ActualSpend.Amount,forecast:CalculatedSpend.ForecastedSpend.Amount}'

first=$(date +%Y-%m-01); today=$(date +%F)
aws ce get-cost-and-usage --time-period "Start=$first,End=$today" --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=TAG,Key=tadas:environment \
  --query 'ResultsByTime[0].Groups[].{env:Keys[0],usd:Metrics.UnblendedCost.Amount}' --output table
aws ce get-cost-and-usage --time-period "Start=$first,End=$today" --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[].{service:Keys[0],usd:Metrics.UnblendedCost.Amount}' --output table

aws ce get-anomalies --date-interval "StartDate=$(date -d '-30 days' +%F 2>/dev/null || date -v-30d +%F)" \
  --query 'Anomalies[].{at:AnomalyStartDate,usd:Impact.TotalImpact,service:RootCauses[0].Service}' --output table
```

A cost that moved is a question for the environment tag first (which
one grew), the service dimension second (what grew), and the dashboard
third (why: traffic, a scale-out, a retention that lapsed).

## What this profile cannot do

Change anything. A threshold, a subscription, a scale-out, a retention:
each is a pull request to `deployment/terraform`, applied by the
deployer. A subscription of another address to the alarm topic is the
one write the runbook names, and it is the account's administrator's:

```bash
AWS_PROFILE=tadas-staging-admin aws sns subscribe --topic-arn "$(terraform -chdir=deployment/terraform/environments/staging output -raw alarm_topic_arn)" \
  --protocol email --notification-endpoint someone@example.com
```

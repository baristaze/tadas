# What the cloud costs

Tadas runs in AWS as two environments built from one graph: staging
from `main` and production from `release`
([../README.md](../README.md)). The graph is fixed. What an environment
costs comes from its numbers: the instance classes, the replica counts,
and whether the database and the cache keep a second zone. This page
names five sizes for those numbers, prices each one, and says which
size each environment runs today and why.

Every price here is an estimate: us-east-1, on demand, list price,
read in September 2026, and rounded. They are good enough to choose a
size, not to forecast a bill. Re-price in the AWS Pricing Calculator
before a change of size, and correct this page when a price moves.

## Where each environment stands

| Environment | Size | Where | About a month |
|-------------|------|-------|---------------|
| dev | none | the laptop, from `deployment/local` | $0 |
| staging | XS | AWS, `environments/staging/main.tf` | $115 |
| production | S | AWS, `environments/prod/main.tf` | $130 |
| shared | n/a | AWS, `shared/`: registry, state, DNS zone, budget | $2 |
| **Total** | | | **$245** |

This is the demo posture. There are no customers yet, only demos, so
production is sized to be shown and not to be leaned on. Dev has no
cloud environment on purpose: the local stack is its twin, and it
costs nothing.

## What every environment pays before it runs anything

About $75 a month per environment is fixed. It does not move with the
size:

| Item | About a month | Why it is there |
|------|---------------|-----------------|
| NAT gateway, and the data through it | $35 | The tasks live in private subnets and reach the registry and AWS APIs through it |
| Load balancer | $18 | The API's public edge, with its certificate |
| Three public IPv4 addresses | $11 | The NAT's address and one per zone for the load balancer |
| Telemetry: Container Insights, the app's metrics, logs, seven alarms, the dashboard | $10 | What an operator reads; this line grows with traffic |
| Secrets, queues, buckets, the portal's CDN, traces | $2 | At demo traffic most of it is inside the free allowances |

The telemetry line is the least certain. Each series the app exports
to CloudWatch costs $0.30 a month. The latency histogram is labelled
by route and method, so the line grows with how many routes traffic
touches. At demo traffic it is about $10. Under real traffic, plan for
$20 to $50.

## The five sizes

The fixed $75 is included in every total below.

| Size | API tasks | Worker tasks | Postgres | Valkey | Pool | Ceilings | About a month |
|------|-----------|--------------|----------|--------|------|----------|---------------|
| **XS** | 1 × 0.25 vCPU, 0.5 GB | 1 × 0.25, 0.5 | `db.t4g.micro`, one zone | 1 × `cache.t4g.micro` | 3 | 2, 1 | **$115** |
| **S** | 1 × 0.25, 0.5 | 1 × 0.25, 0.5 | `db.t4g.small`, one zone | 1 × `cache.t4g.micro` | 5 | 3, 1 | **$130** |
| **M** | 2 × 0.5, 1 | 1 × 0.25, 0.5 | `db.t4g.medium`, two zones | 2 × `cache.t4g.small` | 8 | 4, 2 | **$260** |
| **L** | 2 × 0.5, 1 | 2 × 0.5, 1 | `db.m6g.large`, two zones | 2 × `cache.m6g.large` | 12 | 6, 2 | **$560** |
| **XL** | 4 × 1, 2 | 2 × 1, 2 | `db.m6g.xlarge`, two zones, 100 GB | 2 × `cache.m6g.xlarge` | 12 | 12, 4 | **$1,125** |

The ceilings are the autoscaling maximums, API first and worker
second. A total is the month at the floor, with the flip off or with
no load to answer. With the flip on, a busy month can add the tasks up
to the ceilings: at most $9 at XS and $18 at S.

The unit prices behind them:

- **Fargate (x86).** 0.25 vCPU and 0.5 GB is about $9 a task. 0.5 and
  1 GB is $18. 1 and 2 GB is $36.
- **RDS Postgres, one zone.** `db.t4g.micro` is $12, `db.t4g.small`
  $23, `db.t4g.medium` $47, `db.m6g.large` $111, `db.m6g.xlarge` $222.
  A second zone doubles the instance and its storage. The default 20
  GB of gp3 is about $2.
- **ElastiCache Valkey, per node.** `cache.t4g.micro` is $9,
  `cache.t4g.small` $19, `cache.m6g.large` $87, `cache.m6g.xlarge`
  $174. Valkey is priced about 20 percent under Redis OSS.

What each size is for:

- **XS** proves that a deploy works. Nothing depends on it staying up.
- **S** is a demo that looks real. It is one of everything, and it
  survives a task restart but not the loss of a zone.
- **M** is the first real customers. The database and the cache each
  keep a standby in a second zone, and the API runs two replicas.
- **L** is production proper. It has headroom on every tier, and the
  database is out of the burstable class, so a long busy hour cannot
  run out of CPU credits.
- **XL** is growth. Before choosing it, read the dashboard and grow
  only the tier that is short. A mixed size is fine.

A size is a starting point, not a contract. An environment can run L's
database with M's tasks when the database is what is short. Every
knob the `environment` module exposes is one line in the root's module
call; the database's storage, the alarm thresholds, and the retentions
keep their module defaults until a change passes them through.

## The pool follows the database

Four database roles share one instance, and in the cloud they share
one URL and one set of bounds, so each process opens one pool of
`database_pool_size` connections for all four (the storage root builds
one engine per distinct URL and bounds). A role given a URL or a size
of its own gets a pool of its own on top. A rollout may double the
API's replicas for a moment, and the migration task opens a few more.

The rule each size keeps: twice the API's ceiling, plus the worker's
ceiling, times the pool, stays under the instance's `max_connections`.
Those limits are about 80 for `db.t4g.micro`, 180 for `db.t4g.small`,
400 for `db.t4g.medium`, 850 for `db.m6g.large`, and 1,700 for
`db.m6g.xlarge`. At XS that is 5 × 3 = 15, and at S it is 7 × 5 = 35;
the rule would still hold if a role moved to a pool of its own.

Because the rule holds at the ceilings and not only at the floor,
autoscaling stays one line at every size. `autoscaling_enabled` in the
root turns it on or off
([../../docs/runbooks/scale.md](../../docs/runbooks/scale.md)), and
nothing else has to change with it. Raise a ceiling and the pool is
the line to check in the same pull request.

## Postures

A posture is one choice of size per environment, with the budget that
goes with it. The budget is `monthly_budget_usd` in `shared/`.

| Posture | Staging | Production | About a month | Budget |
|---------|---------|------------|---------------|--------|
| **Demo, production off** | XS | not applied | $117 | $400 |
| **Demo** (today) | XS | S | $245 | $400 |
| **First customers** | S | M | $390 | $600 |
| **Real production** | S | L | $690 | $1,000 |
| **Growth** | M | XL | $1,385 | re-plan |

Staging stays small in every posture. It proves the deploy and the
migration, not the capacity. A load test that needs production's size
runs against production's size for an afternoon, and staging goes back
down after.

The budget is sized so that a normal month lands at 60 to 70 percent
of it. The 80 percent email then means something changed, not that
the month was ordinary.

## The budget is an alarm, not a cap

`shared/` declares the budget and a cost anomaly monitor. The budget
mails `owner_email` at 50, 80, and 100 percent of actual spend, and
when the forecast crosses 100. The monitor reports a jump of $20 or
more in one service, daily. Neither one stops anything. Spending past
the budget is still spent. Reading the email is what keeps the bill
down.

## Lowering the bill without changing the graph

These are ordered by what they save. None of them changes the
architecture.

1. **Leave production unapplied until the first demo.** That saves
   about $130 a month. `release` does not move, so nothing deploys it.
2. **Tear staging down between demo weeks**, with
   `scripts/cloud_nuke.sh staging`, and build it again with
   `scripts/cloud_create.sh staging`. That saves about $115, and
   staging's data goes with it.
3. **Commit once the size is settled.** A one-year reserved instance
   for RDS and ElastiCache, or a Compute Savings Plan for Fargate,
   takes 30 to 40 percent off those lines. Do not commit to a demo
   size you mean to grow out of.
4. **Apply for credits before the first apply.** AWS Activate gives
   credits to self-funded startups, and a new account starts with
   free-tier credits of its own.

These need a small Terraform change and not a new setting:

- **Fargate Spot for staging.** It takes about 70 percent off
  staging's tasks. The service module fixes `launch_type = "FARGATE"`
  today.
- **Graviton tasks.** They take about 20 percent off every task. The
  task definition fixes `X86_64`, and the images would need an arm64
  build.
- **Container Insights off in staging.** It saves a few dollars. The
  cluster module fixes it on.
- **A NAT instance in place of the NAT gateway.** It takes the largest
  fixed line from about $35 to about $4, at the price of patching an
  instance.

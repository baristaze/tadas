# Deployment

Tadas runs in two places, and the two are twins: the same processes,
the same backing services behind the same interfaces, the same
signals. One runs on a laptop from a compose file. The other runs in
the cloud from Terraform. Nothing is clicked into place in either.

## What runs where

| Piece | Locally (compose) | In the cloud (Terraform) |
|-------|-------------------|--------------------------|
| The API process | the `api` container, or a host process with hot reload | a container service behind a load balancer, as many replicas as the size names, rolled one task definition at a time |
| The maintenance worker | the `maintenance` container, or a host process | a container service of its own, rolled one at a time because it holds leases |
| The Slack bridge (`tadas-maintenance slack`) | not run; a host process by hand for a short run, since local and staging share one Slack app | exactly one task on the maintenance image, never two, not even during a rollout |
| The portal | nginx in a container, or Vite on the host | a private bucket behind a CDN, publishing the build staging made |
| The company site | Vite on the host (`pnpm --filter @tadas/site dev`) | the same module as the portal: a private bucket behind a CDN at `www.`, publishing the page for its environment from the one build staging made |
| Postgres | one container, four schemas, one per database role | a managed instance with backups and storage that grows on its own |
| Valkey (cache, topics) | one container | a managed cluster, encrypted in transit |
| Queues (`webhooks`, `slack`) | ElasticMQ over the SQS API, declared in `local/elasticmq/elasticmq.conf` | SQS, with a dead-letter queue each |
| Buckets | MinIO over the S3 API | S3, private and versioned |
| Secrets | the settings object, from `.env` | Secrets Manager, including the Slack app's bot and app tokens |
| Logs, metrics, traces, errors | Prometheus, Grafana, Jaeger, GlitchTip, under the `devx` profile | CloudWatch, X-Ray, Sentry, through a collector sidecar in every task |
| Alarms and the dashboard | Grafana's provisioned overview | one CloudWatch dashboard per environment, eight alarms to one topic |

Every process is one image, built in two stages, running as a
non-root user, with a liveness probe. Liveness decides whether a
process is restarted; readiness, which the load balancer asks the API
for, decides whether it is sent traffic. A replica that is up but
cannot reach its database leaves the rotation without being killed.

- [The local stack](local/README.md): the files, the profile, every
  URL and port, one service at a time, and what to do when something
  is off.
- [The Terraform](terraform/modules/README.md): the roots, the
  modules, the state, and the credentials each root needs.
- [What the cloud costs](cloud/README.md): the five sizes, what each
  environment runs, the postures and their budgets.

## The convention

`main` is staging and `release` is production. That is a choice, and
the one this repository makes.

- Every merge to `main` runs the checks, builds the images once, and
  applies staging with no approval. A merge is the deployment.
- `release` moves only by a fast-forward from `main`, which a person
  dispatches. A push to `release` plans production, waits for a
  reviewer's approval on exactly that plan, and applies it. Nothing is
  rebuilt for production: the images, the portal build, and the site
  build are the ones staging already made.
- The database migration runs inside the apply, before the service
  rolls. A failed migration fails the apply with the old tasks still
  serving. A migration is compatible with the release before it, so
  the old tasks serve the new schema meanwhile.
- Each environment has a credential of its own, and production has
  two: one that reads, for the plan, and one that writes, for the
  apply. The reviewer's approval holds the writing credential, not
  only the step.
- Both environments are the same graph with different variables,
  including the image digests. A new environment is another root,
  never a copy.

The steps, the rollback, and what to check at the approval are in
[the deploy runbook](../docs/runbooks/deploy.md).

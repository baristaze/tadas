# Changelog

The latest release has its entry here. It lists what changed since the
previous tag. A project that clones Tadas at a release checks out its
tag, such as `git clone --branch v0.7.0`.

## 0.17.0 (2026-10-03)

A clone of Tadas at this tag drops the position column whose contract
ADR 0050 had in flight, and its pin moves to guideline v0.49.0 by
merging the scaffold twice: an environment the nuke destroyed leaves no
secret or leftover behind, a recreate finds a zone for its database and
its site's name free, and production's create protects `release`. One
wire field leaves `/v1`, named below; nothing else is reversed.

- **The position's contract ends.** Core revision `202610220000` drops
  `core.tasks.position`, its two triggers, and their functions, and
  `TaskView.position` leaves the wire; the document and both client
  schemas are regenerated. No release from v0.7.0 on names the column,
  and no released client reads the field. (#198)
- **The database and the cache may sit in any zone of the region.** The
  network gives every zone a private subnet, and their subnet groups
  take them all; the tasks and the public subnets stay in the load
  balancer's two zones. (#203)
- **The nuke removes what Terraform does not own.** After the destroy,
  the tenants' secrets go when the database's final snapshot is not
  found (they stay beside it in production), and so do the cluster's
  Container Insights log group and every task definition revision. A
  root already destroyed is finished by running the nuke again. (#204)
- **A recreate finds its site's name free.** The create run removes a
  CNAME to CloudFront whose target no longer resolves, before the
  deploy, and refuses one that answers. (#204)
- **The production create protects `release`.** A deploy key with write
  access, stored as `RELEASE_DEPLOY_KEY` and never shown, is the one
  bypass actor of a ruleset that restricts creations, updates,
  deletions, and force pushes on `release`. (#204)
- **`tadas-ops workos-bootstrap` checks the identity webhook.** A
  missing, disabled, or unreadable endpoint is a dashboard step the run
  fails on. (#204)
- **A trace is found by its request id.** The collector copies
  `tadas.request_id` into `tadas_request_id`, the key X-Ray filters on. (#204)
- **An operator who has not enrolled is told to enrol**, with the
  runbook's section, instead of a traceback. (#204)
- **A Node with no corepack still gets pnpm**, and `dev.sh` stops loudly
  when a process fails. (#201)
- **The pin moves to guideline v0.49.0**, through v0.48.0, by merging
  the scaffold. (#202, #204)

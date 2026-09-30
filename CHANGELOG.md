# Changelog

Each release has an entry here, the newest first. An entry lists what
changed since the previous tag. A project that clones Tadas at a release
checks out its tag, such as `git clone --branch v0.7.0`.

## 0.11.0 (2026-09-30)

The two operational skills read a deployed environment: each signal
they report has its cloud call, on the schema the app's series carry.
The pin moves to guideline v0.42.0 by merging the scaffold. No route,
wire type, screen, or migration changes.

- **`ops-investigate` reads the requests of a deployed environment.**
  Step 4 searches the schema the app's series carry, with the
  exporter's `OTelLib`. The schema it wrote before matched no series,
  so the request query read zero. (#187)
- **Each skill gives the cloud call of every signal it reports.**
  `ops-watch` step 5 prints a batch's four numbers in one call: the
  requests, the 5xx, the p95, and the worker's failures.
  `ops-investigate` reads the request count, the counts by status and
  route, the p95, the outcomes, and the database's connections. (#187)
- **The cloud p95 is the load balancer's**: one number for every route
  together, in milliseconds, or `none` when no request crossed it. The
  cloud has no p95 by route. (#187)
- **A watch batch that read nothing says so.** In the cloud, a batch
  whose `requests` is 0 writes "metrics not read", never a zero: the
  load balancer's health checks are requests. (#187)
- **`ops-investigate` asks the error tracker for a window it takes.**
  Step 6 sends Sentry's own host the search term `lastSeen:-<since>`
  and keeps the issues by their `lastSeen` field. It sends no
  `statsPeriod`, which answered the default hour with a 400. (#187)
- **Tests hold the skills' schemas.** `infra/tests/test_ops_skills.py`
  holds every `SEARCH` schema the two skills write to the ones the
  dashboard module writes. (#187)
- **The guideline pin moves to v0.42.0.** `main` merges the `scaffold`
  branch at v0.42.0. `make arch-check` passes at v0.42.0, and nothing
  the release asks is a deviation. (#187)

Every release's notes stay on the repository host: <https://github.com/baristaze/tadas/releases>.

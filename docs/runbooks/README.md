# Runbooks

One file per operational procedure: what to check, what to run, what
to expect. A runbook names the process, the setting, or the table it
touches and the ADR that explains why it is shaped that way.

- [deploy.md](deploy.md): staging is `main`, production is `release`;
  cutting a release, approving its plan, rolling back, what a failed
  migration does, the protection on `release`, and what to do when the
  cloud is not configured.

Next candidates: rotating the database credentials, moving a database
role to its own database, and draining a worker before a rollout.

# Runbooks

One file per operational procedure: what to check, what to run, what
to expect. A runbook names the process, the setting, or the table it
touches and the ADR that explains why it is shaped that way.

- [deploy.md](deploy.md): staging is `main`, production is `release`;
  cutting a release, approving its plan, rolling back, what a failed
  migration does, the protection on `release`, and what to do when the
  cloud is not configured.
- [operate.md](operate.md): the profile an investigation runs under,
  the dashboard, the alarms, the costs, and the exact commands that
  read each of them.
- [scale.md](scale.md): the one variable that scales an environment,
  what turns on under it, and how to read that it happened.
- [tenant-isolation.md](tenant-isolation.md): where the cross-tenant
  cases live, how to run the negative control that says what they
  catch, what the last run showed, and what the two storage impls
  answer differently.
- [support.md](support.md): how a support investigation runs: a
  tenant names a problem, the supporter takes the org id, runs
  `ops-root-cause`, what it reads and in which order, and what is
  logged.

Next candidates: rotating the database credentials, moving a database
role to its own database, and draining a worker before a rollout.

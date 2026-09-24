# Runbooks

One file per operational procedure: what to check, what to run, what
to expect. A runbook names the process, the setting, or the table it
touches and the ADR that explains why it is shaped that way.

- [operator.md](operator.md): how a person gets onto the operator
  plane: sign in, the grant, enrolling the second factor, the check
  that the plane refuses a sign-in without a code, and the token an
  agent then works from.
- [deploy.md](deploy.md): staging is `main`, production is `release`;
  granting an operator, the smoke test, cutting a release, approving
  its plan, the fast rollback and the revert, what a failed
  migration does, the protection on `release`, and what to do when the
  cloud is not configured.
- [operate.md](operate.md): the profile an investigation runs under,
  the dashboard, the alarms, the costs, and the exact commands that
  read each of them.
- [scale.md](scale.md): the one variable that scales an environment,
  what turns on under it, and how to read that it happened.
- [tenant-isolation.md](tenant-isolation.md): where the cross-tenant
  cases live, how to run the negative control that says what they
  catch over the memory impls and the two-run control that says the
  row-level security policies are live, what the last runs showed, and
  what the two storage impls answer differently.
- [restore.md](restore.md): what is backed up and for how long, a
  restore as break-glass to a new instance, the rehearsal and its
  record, and relaying the outbox again when one role comes back
  earlier than the others.
- [providers/](providers/): the three providers Tadas depends on,
  one page each, written for a person who has never opened their
  dashboards: the provider's levels and which Tadas setting lives at
  each, which Tadas environment uses which provider environment, the
  first-time steps by hand in order, what the bootstrap commands and
  the deploy do on their own, local development, rotation, what breaks
  and where to look, and production.
  - [providers/stripe.md](providers/stripe.md): the payment
    processor. The sandbox and the live account, the restricted key and
    its permissions, `tadas-ops stripe-bootstrap` (products, prices,
    the Billing Portal, the webhook endpoint and its secret), and
    `stripe listen` on a laptop.
  - [providers/workos.md](providers/workos.md): the sign-in. The
    Staging and Production environments, the Tadas App application,
    its API key and its Redirects tab, `tadas-ops workos-bootstrap`, and
    the organizations Tadas makes.
  - [providers/slack.md](providers/slack.md): the Slack app. Its
    scopes, the two tokens, the one Socket Mode connection staging
    holds, and why a laptop holds none.
- [support.md](support.md): how a support investigation runs: a
  tenant names a problem, the supporter takes the org id, runs
  `ops-root-cause`, what it reads and in which order, and what is
  logged.

Next candidates: rotating the database credentials, moving a database
role to its own database, and draining a worker before a rollout.

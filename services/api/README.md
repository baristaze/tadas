# The API process

The one HTTP process of Tadas. It serves every route of the product
under `/v1`, the live channel, and the operational routes outside
`/v1`. Every replica is the same process; replicas share nothing but
the database, the cache, and the topic bus.

By default it mounts every namespace's routes. `TADAS_NAMESPACES`
names a subset (`["media"]`, say), which is how one namespace becomes
a service of its own: the same image with another value, and no code
change. A name the image does not host refuses the boot.

## Routes, by area

- **Sign-in.** Start a sign-in at the identity provider, WorkOS
  AuthKit, for this environment's portal callback, and finish it with
  the code the browser brought back, which the API exchanges
  server-side; a person nobody knew is signed up by it, with their
  personal org (`/v1/auth/sign-in`, `/v1/auth/callback`). Start and
  finish a device sign-in for the command line (`/v1/auth/device`,
  `/v1/auth/device/token`). Confirm an operator's second factor on a
  sign-in (`/v1/auth/second-factor`). List my places; exchange the
  login, or switch a session, for a session in one org; sign out
  (`/v1/auth/memberships`, `/v1/auth/sessions`, `/v1/auth/logout`).
  Locally and in the tests only, sign in by address alone
  (`/v1/auth/dev-sign-in`, ADR 0029); a deployed process refuses to
  start with it on.
- **Me.** The current org, my user, my identity, and my display name;
  a new team org I own. (`/v1/orgs/current`, `/v1/me`,
  `/v1/me/identity`, `/v1/orgs`)
- **Members.** The org's members and their roles a page at a time,
  a member's role, removing a member. (`/v1/users`, `/v1/memberships`,
  `/v1/memberships/{user_id}`)
- **Invitations and single sign-on.** Invite a person by email with a
  role, under an Idempotency-Key; the identity provider sends the
  email. The org's pending invitations a page at a time, sending one
  again, revoking one. A short-lived link to the provider's admin
  portal, where an owner or an admin of a team org sets up single
  sign-on or proves a domain. (`/v1/invitations`,
  `/v1/invitations/{invitation_id}/resend`,
  `/v1/invitations/{invitation_id}`, `/v1/orgs/current/sso-link`)
- **Credentials.** My live sessions and revoking one; the org's API
  keys, creating one, revoking one; a ticket for the live channel.
  (`/v1/sessions`, `/v1/api-keys`, `/v1/realtime/tickets`)
- **Tasks.** Open and done lists a page at a time, one task, create,
  edit, move, delete. (`/v1/tasks`, `/v1/tasks/{task_id}`,
  `/v1/tasks/{task_id}/move`)
- **Attachments.** A task's files a page at a time, starting an
  upload of one, removing one. (`/v1/tasks/{task_id}/attachments`,
  `/v1/tasks/{task_id}/attachments/{file_id}`)
- **Files.** A file; the form that posts its bytes straight to the
  store, or the bytes through the API where the store cannot take a
  form; the confirm once the upload is done; the link a download
  follows, or the bytes through the API; and the org's storage used.
  (`/v1/media/files/{file_id}`, `.../upload`, `.../content`,
  `.../confirm`, `.../download`, `/v1/media/usage`)
  edit, move, delete. A task's due date (`due_on`, `YYYY-MM-DD`, never a
  time) is set on the create and set, moved, or cleared (`null`) on the
  edit. `remind_at`, the due time it replaces, is deprecated: a request
  that sends it sets the due date to its date, and a response carries
  it as `null`. The release after this one removes it.
  (`/v1/tasks`, `/v1/tasks/{task_id}`, `/v1/tasks/{task_id}/move`)
- **Slack.** The org's installation (its workspace, its channel, and
  whether it works), any member; the install, which answers Slack's
  page to send the browser to with a one-time state, and the
  uninstall, an owner or an admin. (`/v1/slack/installation`: `GET`,
  `POST`, `DELETE`)
- **Events.** The org's diary after a sequence number. (`/v1/events`)
- **Billing.** The org's plan, where it comes from, its seats and
  active tasks against the plan's bounds, and the plans on offer; a
  checkout for a paid plan and the processor's own portal, each coming
  back only to a page of the portal; cancel at the period's end, and
  taking that back. Everyone in the org reads; an owner or an admin
  changes. (`/v1/billing`, `/v1/billing/checkout`,
  `/v1/billing/portal`, `/v1/billing/cancel`, `/v1/billing/resume`)
- **The payment processor's deliveries.** Outside `/v1`, since their
  shape is the processor's, pinned on the endpoint it delivers to. No
  credential: the route checks the processor's signature over the body
  and its timestamp, within a five-minute window, and queues the
  delivery for the worker; one that fails the check is a 400 and
  nothing is queued. (`/webhooks/stripe`)
- **Slack's calls.** Outside `/v1` too, since their shape is Slack's.
  No credential: a slash command and an event are each checked against
  the Slack app's signing secret over the body and its timestamp,
  within five minutes, acknowledged at once, and queued for the worker;
  one that fails the check is a 401 (`slack_signature_invalid`) and
  nothing is queued. With no Slack app configured, each answers 503
  (`slack_unavailable`). The events route answers Slack's URL check.
  The install's return is where Slack sends the browser back; it is
  not signed, the one-time state is its check, and it redirects to the
  portal's Settings with the outcome. (`/webhooks/slack/commands`,
  `/webhooks/slack/events`, `GET /webhooks/slack/oauth`)
- **Realtime.** The live channel, a websocket opened with a
  single-use ticket. (`/v1/realtime`)
- **The operator plane.** For an identity on the operator allowlist,
  across every org: create an org with its owner, add a member, read
  an org, its members, its tasks, and its events, list every org a
  page at a time, delete a team org (a personal org is refused), read
  an org's plan and grant it one with no payment, and read the
  platform's size: the tenant count, the
  user count, and the tasks of the last twenty-four hours.
  (`/v1/admin/orgs`, `/v1/admin/orgs/{org_id}`,
  `/v1/admin/orgs/{org_id}/members`, `/v1/admin/orgs/{org_id}/tasks`,
  `/v1/admin/orgs/{org_id}/events`, `/v1/admin/orgs/{org_id}/billing`,
  `/v1/admin/orgs/{org_id}/plan`, `/v1/admin/size`). A read route
  needs an operator who may read; a write route one who may write.
  The plane admits two credentials: a person's sign-in that verified a
  TOTP code, and an operator token. An operator enrols the second
  factor once, at the first sign-in to the plane, and until then only
  the two enrolment routes answer (`/v1/admin/me/totp`,
  `/v1/admin/me/totp/confirm`). A signed-in operator mints an operator
  token for an agent, one permission and an hour at most
  (`/v1/admin/me/tokens`).
- **Operational.** Liveness (`/healthz`, the process alone),
  readiness (`/readyz`, asks the database under a deadline shorter
  than the probe's interval), metrics (`/metrics`), and the OpenAPI
  document with its UI (`/docs`). The first three are never refused
  by admission.

## What the gateway guarantees

- **A request id on every answer.** The `x-request-id` header carries
  it. A caller may send one; otherwise the gateway mints it. Every
  log line of the request, its trace, and its error report carry the
  same id, and a refusal quotes it.
- **An idempotency key on every create.** A creating `POST` may carry
  `Idempotency-Key`, one to 255 characters; every client this repository
  ships sends one, and a create without it runs once per request. The same key with the same
  request gets the first answer back, marked `Idempotent-Replayed:
  true`; the same key with a different request is refused. A secret
  is in the first answer only. A 429 and a plan's bound (402) are
  answers about now and are not kept: the retry of the same create runs
  again, and lands once the org has room.
- **The calling app and its version.** `x-app` and `x-app-version`
  name the client, and travel into the provenance of every write.
- **One error envelope.** Every refusal, the framework's own included,
  is one shape: a code, a message, and the request id, under the HTTP
  status. A 5xx says `internal error` and the real message goes to the
  log under the request id; the admission 503 alone says which bound it
  hit, with a `Retry-After`. A plan's bound is a 402,
  `plan_limit_reached`, and its envelope also carries `plan_limit`: the
  lever, the org's plan, the bound, and the plan that lifts it, which
  is what a client turns into an offer to upgrade.
- **Bearer by prefix.** The credential's prefix says what it is: a
  session token, an API key, a login, a ticket, or an operator token. A missing or
  invalid one is a 401; a route asked with the wrong kind is refused.
- **Admission.** The process bounds what it has in flight. Past the
  bound a request is refused at once with a 503 and a `Retry-After`,
  so a saturated process answers and says why instead of queueing
  work it cannot start. Admission fails closed and is counted in the
  process's own memory.
- **Rate limits.** Per route, counted in the shared cache so every
  replica shares one budget, keyed on the credential or, on an
  unauthenticated route, the client address. Past the budget the
  answer is a 429. Rate limits fail open: they are fairness, not a
  security boundary.
- **The client address behind a load balancer.** The forwarded address
  is trusted only from the peers the settings name, never from
  everyone, so a caller cannot pick its own address.
- **A socket is bounded twice.** It closes at the expiry of the
  credential behind its ticket whatever the client does, and it
  closes at once when that credential is revoked. Both close with
  code 4401, which every client reads as "sign in again".
- **The socket ticket is never logged.** Access logging is the
  gateway's own, by route template, with no query string.

## The subcommands

`tadas-api` is one entry point with subcommands. Each boots the same
container the server does.

| Subcommand | Does |
|------------|------|
| `serve` | Runs the process. |
| `migrate` | Applies every role's migration chain (`--all`) or one role's. Idempotent per revision. `migrate ensure-logins` makes the database logins, as the master. |
| `bootstrap` | Seeds a fresh local environment with one org and its owner; `--operator` puts the owner on the operator allowlist with write, and `--plan` grants the org a plan with no payment. Local only, like every seed. |
| `grant-operator` | The grant job: `--email <e> --permission read\|write` puts an identity on the operator allowlist, `--email <e> --disable` takes it off, and `--email <e> --mint-token provisioner\|smoke [--expires-in N]` mints that identity's operator token into the secret store as `tadas-<env>-<holder>-token`, never printed in the cloud. An operator signs up first; the platform's own identities (`@platform.tadas.invalid`) are made by their first grant. |
| `add-member` | Seeds a person into an existing org; a no-op for a member. |
| `openapi` | Emits the OpenAPI document the clients are generated from. |

The migration runs inside every cloud deploy, as a one-off task before
the service rolls; a failed migration leaves the old tasks serving.

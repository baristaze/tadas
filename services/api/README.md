# The API process

The one HTTP process of Tadas. It serves every route of the product
under `/v1`, the live channel, and the operational routes outside
`/v1`. Every replica is the same process; replicas share nothing but
the database, the cache, and the topic bus.

## Routes, by area

- **Sign-in.** Sign in with email and password, and the code from an
  authenticator when a second factor is enrolled; exchange the login
  for a session in one org; sign out. (`/v1/auth/login`,
  `/v1/auth/sessions`, `/v1/auth/logout`)
- **Me.** The current org, my user, my identity, and my display name.
  (`/v1/orgs/current`, `/v1/me`, `/v1/me/identity`)
- **Members.** The org's members and their roles a page at a time,
  a member's role, removing a member. (`/v1/users`, `/v1/memberships`,
  `/v1/memberships/{user_id}`)
- **Credentials.** My live sessions and revoking one; the org's API
  keys, creating one, revoking one; a ticket for the live channel.
  (`/v1/sessions`, `/v1/api-keys`, `/v1/realtime/tickets`)
- **Tasks.** Open and done lists a page at a time, one task, create,
  edit, move, delete. A task's due time (`remind_at`, with its offset)
  is set on the create and set, moved, or cleared (`null`) on the edit.
  (`/v1/tasks`, `/v1/tasks/{task_id}`, `/v1/tasks/{task_id}/move`)
- **Slack.** The org's connected channel, any member; a one-time link
  code, shown once, and the disconnect, an owner or an admin.
  (`/v1/slack/connection`, `/v1/slack/link-codes`)
- **Events.** The org's diary after a sequence number. (`/v1/events`)
- **Realtime.** The live channel, a websocket opened with a
  single-use ticket. (`/v1/realtime`)
- **The operator plane.** For an identity on the operator allowlist,
  across every org: create an org with its owner, add a member, read
  an org, its members, its tasks, and its events, list every org a
  page at a time, delete an org, and read the platform's size: the tenant count, the
  user count, and the tasks of the last twenty-four hours.
  (`/v1/admin/orgs`, `/v1/admin/orgs/{org_id}`,
  `/v1/admin/orgs/{org_id}/members`, `/v1/admin/orgs/{org_id}/tasks`,
  `/v1/admin/orgs/{org_id}/events`, `/v1/admin/size`). A read route
  needs an operator who may read; a write route one who may write.
  The plane admits two credentials: a person's sign-in that verified a
  TOTP code, and an operator token. An operator enrols the second
  factor once, at the first sign-in to the plane, and until then only
  the two enrolment routes answer (`/v1/admin/me/totp`,
  `/v1/admin/me/totp/confirm`). A signed-in operator mints an operator
  token for an agent, one permission and an hour at most
  (`/v1/admin/me/tokens`), and a write operator resets a person's
  password, audited (`/v1/admin/password-resets`).
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
  is in the first answer only.
- **The calling app and its version.** `x-app` and `x-app-version`
  name the client, and travel into the provenance of every write.
- **One error envelope.** Every refusal, the framework's own included,
  is one shape: a code, a message, and the request id, under the HTTP
  status. A 5xx says `internal error` and the real message goes to the
  log under the request id; the admission 503 alone says which bound it
  hit, with a `Retry-After`.
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
| `bootstrap` | Seeds a fresh local environment with one org and its owner; `--operator` puts the owner on the operator allowlist with write. Local only, like every seed. |
| `grant-operator` | The grant job: `--email <e> --permission read\|write` puts an identity on the operator allowlist, `--email <e> --disable` takes it off, and `--email <e> --mint-token provisioner\|smoke [--expires-in N]` mints that identity's operator token into the secret store as `tadas-<env>-<holder>-token`, never printed in the cloud. An operator signs up first; the platform's own identities (`@platform.tadas.invalid`) are made by their first grant. |
| `add-member` | Seeds a person into an existing org; a no-op for a member. |
| `openapi` | Emits the OpenAPI document the clients are generated from. |

The migration runs inside every cloud deploy, as a one-off task before
the service rolls; a failed migration leaves the old tasks serving.

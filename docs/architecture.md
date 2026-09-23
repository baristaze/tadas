# Tadas, as built

This page describes what exists in this repository. How we build is in
the Software Design and Architecture Guidelines, which this project
adopts unchanged; the technology choices as adopted are recorded in
[ADR 0002](adr/0002-technology-choices.md).

## Object model (`om/`)

The `tadas-om` distribution holds the base classes (`Platform`, the
mixins, `new_id`, `utcnow`), the context model in `opcontext.py` with
`Role`, `Permission`, `CredentialKind`, and `AppType` declared beside it,
the exception root, the storage root with its Postgres and memory impls,
and one namespace per swimlane. `Created` (`created_at` alone) is the
base of `Trackable` and is composed alone by the rows the platform
writes for itself, the outbox row, the idempotency record, and the
socket ticket, as the guideline's "Naming Entities" states the rule and
"Namespace Shape" and "The Gateway" declare the two rows
(`OutboxRow(Identifiable, Created)`, `IdempotencyMarker(Identifiable,
Created)`; Tadas names the marker `IdempotencyRecord`, the same row
under its own name). No person stands behind such a row, so it carries
no `created_by`, and what the platform stamps on it later is a field
named for what happened (`done_at`, `redeemed_at`). `Trackable` records
who created a row and who last changed it (`updated_by`); every update
sets it from the context. The copy on update starts from the stored
row: the caller's entity supplies the fields a caller may change, and
`PROVENANCE_FIELDS` (a constant beside the mixins naming `created_at`,
`created_by`, `deleted_at`, and `deleted_by`) stay as stored, so no
caller rewrites who made a row or brings a deleted one back by sending
an entity. A copy that carries the caller's dump is
`Task.model_validate` over the stored dump and the caller's, never
`model_copy`, which does not validate; `model_copy` is for values
constructed of the field's own type (`om/tests/unit/test_update_copy.py`
holds the rule). The
API's partial update is translation: it merges only the request's set
fields onto the stored entity, and the request type names no provenance
field and forbids extra ones.

The context model is two orthogonal ideas. The stages are four frozen
types ordered by evidence: `RequestContext` (a request exists: its id,
the calling app, the trace id, and the request that caused it where a
handoff named one, empty at the edge), `IdentityContext` (a person is verified
by their own sign-in; no tenant, on purpose), `OpContext` (a membership
is established: the user, the org, the role and its permissions, the
credential), and `OperatorContext` (an identity on the operator allowlist;
no org, on purpose). A subclass is a refinement, so every stage is
accepted where `RequestContext` is asked for; `OperatorContext` is an
`IdentityContext`, `OpContext` is not, because what a tenant operation
knows about the person is the user inside the tenant. A stage above the
request stage is produced only by a transition, an operation of the
tenancy manager or one that asks it, and nowhere else
(`authenticate_login`, `authenticate`, `admit_operator`,
`redeem_ticket`, `service_context`, the worker's claim, and the
seeding), and a function that
takes a stage relies on its invariant instead of re-checking it. The
context carries ids and facts, never a `User` or an `Org`: a manager that
needs the entity loads it, so a role change is seen on the next request,
and `opcontext.py` imports nothing above `base.py`.

The scopes are five `Protocol` views over what a stage carries, each a
set of read-only properties: `RequestScope`, `TenantScope`, `ActorScope`
(there is no actor without a tenant), `CredentialScope`, and
`ProvenanceScope` (actor, request, and app: the one named composition,
because provenance is a domain concept). A function that reads only a
few fields declares the scope it reads (`outbox_row` and `audit_event`
take `ProvenanceScope`, the realtime `subscribe` takes `ActorScope`, the
rate limit's subject takes `CredentialScope`) and its callers keep
passing the stage they hold. A manager operation takes `OpContext`, which
is its scope, and says nothing narrower; a function that forwards the
context on keeps the stage the callee needs.

- `tenancy`: orgs, identities, users, memberships, sessions, api keys,
  socket tickets; sign-in, tenant-scoped session tokens, role-capped api
  keys, the operator allowlist, and the service contexts workers run
  under. Permissions are a function of role, one table in
  `tenancy.types.role`; the ladder beside it ranks the person roles
  (viewer, member, admin, owner) and a unit test holds it to the table, so
  a role at most another holds a subset of its permissions. The service
  role is no rung: `role_at_most` answers False on either side of it, and
  every operation that issues a credential or grants a membership refuses
  it by name before the ladder is asked. An api key never mints another:
  revoking a leaked key has to end the access it gave, and a successor
  would outlive it, so `create_api_key` refuses an api key credential the
  way `logout` refuses anything but a session. The operator plane (every org, delete an org) is a second
  manager, `TenancyOperatorManagerInterface`, which takes `OperatorContext`
  and nothing else. Deleting an org soft-deletes the row and lands
  `tenancy.org.deleted` beside it, so every socket of the tenant closes;
  a claim of its queued work fails the item in the same call, and once
  the retention has passed the sweep purges every row of the tenant and
  keeps the org row as the record. A socket ticket is a row; redeeming it is one conditional
  update on its hash, and the cache only remembers a redeemed one so a
  replay is refused without a round trip. Every unique key the schema
  declares (an identity's email, an org's slug, one live user per identity
  and one membership per user in a tenant, the hashes of sessions, api
  keys, and socket tickets) is refused by both storage impls as
  `UniqueKeyTaken`, a `Conflict` (409), so a race the read did not see is
  never a driver error and never mistaken for a retry: the Postgres
  create primitive reports an existing id only when the primary key is the
  violated constraint. A unique key on a soft-deletable table is unique
  among the living: the org slug, the user's identity in a tenant, and
  the membership are partial unique indexes `WHERE deleted_at IS NULL`,
  so a deleted org frees its slug, a removed member frees the identity
  and the membership, and the same value can be created again; the slug
  lookup reads the living. The api key hash stays a full index because it
  digests a fresh random secret that is never created again. A partial
  index serves none of the sweep's reads, which are the dead rows and a
  deleted tenant's, so users and memberships each carry a plain
  `(org_id, deleted_at)` index beside their unique one. The seeding
  transitions are named atomic creates:
  `bootstrap` lands the org, its first user, and the owner's membership in
  one commit (`create_org_with_owner`), `add_member` the user, the
  membership, and the outbox row (`create_member`), so a concurrent
  duplicate leaves no partial tenant behind; the identity each mints or
  promotes lands in that same commit, so a refused tenant leaves no
  identity behind. Removing a member revokes their sessions and api
  keys, each announced, and ends their membership with them in one
  commit (`remove_member`): soft-deleted beside the user, hidden from
  every read, out of reach of a role change, and never a live user
  without a membership. A user or a membership another tenant owns is
  answered there the way one that never existed is, over both impls, so
  the refusal says nothing about what exists under someone else. A sign-in verifies the
  password against a fixed dummy hash when the email is unknown, so the
  response time does not say which emails exist, and runs scrypt off the
  event loop. Sessions and api keys are listed newest first and filtered
  at the storage (live at the instant asked; a member's own keys), so a
  page of dead rows never hides a live one. Members, memberships, api
  keys, and the operator's org list answer a page (`UserPage`,
  `MembershipPage`, `ApiKeyPage`, `OrgPage`: items, `has_more`) after a
  cursor, which is the id the previous page ended on, since every one of
  them is ordered by one unique id - members and orgs ascending,
  memberships by user id ascending so a page of roles pairs with the
  page of members that ends on the same id, keys descending, an id
  being minted in time order; the manager asks storage for one row past the page and
  keeps it out, so a limit is a page size and never a ceiling past which
  a live key stops being listed. The purge also removes
  sessions revoked or expired and socket tickets redeemed or expired past
  the retention. Login credentials are stored under the system scope,
  and the sweep mints a service context for that scope first, so the
  expired ones are purged like a tenant's dead sessions; api keys are
  purged once revoked or expired. Exchanging a login for an org that is
  gone, or a membership that has ended, is `NotAuthorized` (403), not a
  sign-in failure: the login itself still stands. Every person has
  exactly one personal org (`Org.kind`, `personal` or `team`, and
  `personal_identity_id`, the person; a partial unique index keeps one
  living personal org per identity, and a check constraint ties the two
  columns). Sign-up (`sign_up`, on the request stage) asks for an email,
  a name, and a password, and lands the new identity, its personal org
  (named after the person, the slug generated from the name with a
  random tail), the person's user, and the owner membership in one
  commit (`creates.create_person` over `create_org_with_owner`, always
  with a new identity, so a raced email meets the unique key) and
  answers as a login does. `create_person` takes the identity as its
  caller built it, so a door other than the password can call it. Every
  other create that makes an identity (the seeding's `bootstrap` and
  `add-member`, the operator plane's create and add) lands the new
  person's personal org in the same commit as its own tenant, each
  statement under its own tenant's scope, as a switch does; a sign-in
  of a person an older release made gives them theirs. A personal org
  is never deleted, and its person is never removed from it or given
  another role (`PersonalOrgFixed`, 409). `POST /v1/orgs` makes a team
  org for the caller from a session, under an Idempotency-Key, and
  answers with the caller's place in it; the switch there is the
  exchange. Migration `202609250001` gives every existing person their
  personal org in SQL, under a lifted fence, in one bounded pass that
  refuses to leave anyone behind. `POST
  /v1/auth/signup` has its own rate limit per client address, no
  Idempotency-Key (the marker is kept per tenant and principal, and
  sign-up has neither), and `TADAS_SIGNUP_ENABLED` (true by default),
  which, false, makes it answer the router's own 404. With no email
  verification, sign-up has two accepted costs: a held address answers
  `409`, so anyone can test which addresses have an account, and anyone
  can claim an address that is not theirs. With no verified address
  there is no account recovery either. An exchange
  presented with a session is a switch: `replace_session` revokes it and
  lands the new one in one transaction, each statement under its own
  tenant's scope, with the revocation's outbox row, so the old socket
  closes. One person is a
  member of at most `max_orgs_per_identity` orgs (100, an option of both
  tenancy managers). Every read of the users one identity is asks for
  one past the bound; an add or an org create past it is
  `MembershipLimitReached` (409), and a read that still finds more (two
  adds that raced) is refused the same way, never cut short. The plan
  bounds the rest: `create_api_key` is refused on a plan without keys,
  and an api key of such an org authenticates to the same 402 rather
  than a 401, kept and never revoked; the operator plane's add asks
  `refuse_past` for a seat through `add_member_to`'s admission hook,
  which also answers the `work.SYNC_SEATS` row a per-seat plan's add
  rides, and `remove_member` lands that row beside its own. The seed's
  add is not bound by seats. Owners and admins hold `manage_billing`.
- `work`: the table-backed work queue in the `queue` role; a row's
  routing field is its `lane`, payload shapes are fixed per `WorkKind`
  by `WORK_PAYLOADS`, and the permission each kind is asked for with by
  `WORK_ENQUEUE_PERMISSIONS`, which the worker's tests hold to every
  handler's `REQUIRES`. The kinds are `NOOP` and `SYNC_SEATS`. Enqueue is a create: it validates the payload, and
  the manager's copy stamps the actor from the context, the timestamps,
  status `QUEUED`, zero attempts, and clears every claim field whatever
  the caller sent; the insert reports an existing id and changes nothing,
  so a retried enqueue returns the row as stored, claim intact; a reused
  idempotency key is reported the same way and never raised as a driver
  error. The insert returns an `InsertOutcome` (`INSERTED`, `ID_EXISTS`,
  `KEY_EXISTS`), and the manager reads the row back by the key that
  collided, by `read_item_by_key` for a key; the key is unique per
  tenant, `(org_id, idempotency_key)`. That is what
  lets an enqueue that runs twice under one key leave one item. A fresh
  row publishes `work_available`. An item carries the request that caused
  the work and that request's `traceparent`, both as constructed: the
  relayed enqueue reads them off the outbox row of the write and a direct
  create off its caller's context, and neither enqueue mints one. The
  claim is one `SELECT ... FOR UPDATE
  SKIP LOCKED` statement on the lane that mints a `claim_token` on the row
  and returns the enqueuer's principal, under a request stage of its own
  that names the item's request as its `caused_by_request_id`. Every transition (complete, fail,
  defer, release, extend_lease) is conditional on the token in the
  statement itself, not on the worker's name, because one worker can hold
  one item twice across a requeue: a worker whose lease has passed is
  refused with `LeaseLost`, a `Conflict`, and hands the item back without
  spending an attempt; the requeue clears the token. Every write to the
  row after the enqueue is the platform's, so the claim, the renewal,
  the hand-back, the requeue, the failure, and the completion all sign
  `updated_by` with `EMPTY_UUID`, and the copy starts from the stored
  row: `created_by` is the person who asked for the work, `updated_by`
  is the machinery that ran it, and a worker's copy rewrites neither. A failed item is a
  dead letter, named by a `work.item.failed` event in the tenant's
  stream and counted on the outcome counter. Done or failed items are
  purged by the sweep after the work retention (30 days).
- `tasks`: the to-do items (`Task`: title, notes, status, position,
  version), listed by a `TaskFilter` (team or mine) and paged by a
  cursor, `OpenTaskCursor` over (position, id) for the open list and
  `TaskCursor` over (updated_at, id) for the done one, all passed
  unchanged from the manager to storage; the visibility, cursor, and
  placement rules are pure functions in `tasks.rules`, the active-task
  bound is the plan's (`count_open_tasks`, asked before a create and a
  reopen, a read then a write, so a race at the bound can overshoot by
  the racers), which the memory
  impl calls and the Postgres impl mirrors in SQL. A placement reads one
  open place, bounded in the statement: the top one for a task created
  or reopened, the one that follows the anchor for a move
  (`tasks.rules.follows`, which the statement spells and a contract case
  holds to the function). A gap halved down to
  float precision is renumbered: the whole open list gets whole-number
  positions in one compare-and-set over every row (`update_tasks`),
  each announced. A task carries a
  `version` because it is edited from two windows and two terminals at
  once ([ADR 0009](adr/0009-tasks-carry-a-version.md)): the manager's
  copy increments it on update, move, and soft delete, and the storage
  write is a compare-and-set, `WHERE version = :expected` in one
  statement in Postgres and the same check and write under the lock in
  the memory impl, which raises `PreconditionFailed` (412
  `precondition_failed`), when the row is at another version or is gone.
  The version the write compares with is the caller's, never one the
  update reads: `If-Match` on a `PATCH` and a `DELETE`, `expected_version`
  on the move, and a write that names none is `ValidationFailed`. The
  copy on update keeps `PROVENANCE_FIELDS` and the task's
  `MANAGER_OWNED_FIELDS` (its position and its version) as stored.
  The update never inserts; the create primitive is the only way in. So
  a snapshot that missed a write is refused, never merged over it, and
  an edit that raced a delete finds the task gone and cannot bring it
  back. A list answers a `TaskPage` (items, `has_more`): the manager
  clamps the page size at 200, asks storage for one row more, and keeps
  it out, so `has_more` is a fact about the rows and a list the clamp
  cut still says a page follows. The API encodes the cursor opaquely
  with the list it belongs to, refuses one from the other list, and
  answers a real `next_cursor` for both lists. `TaskView` shows the
  version, and every write names the one the caller read: the update
  and the move in their bodies, the delete as a required `version` query
  parameter, since a DELETE has no body and `If-Match` would mean entity
  tags, 412, and an `ETag` on every response. An assignee is held to
  membership when the assignment changes, never over one already stored:
  removing a member leaves their tasks assigned to them, and marking such
  a task done or editing its title is an update about something else,
  which a stale assignment must not refuse. Clearing the assignee is
  always allowed, and the portal names a member it no longer lists
  "someone".

- `billing`: an org's plan and its account at the payment processor
  ([ADR 0027](adr/0027-plans-are-levers-and-the-processor-is-mirrored.md)).
  `BillingAccount` (one per org, the org its unique key, every field
  manager-owned) mirrors the subscription: the customer, the
  subscription, the price's lookup key, the status, the period's end,
  cancel at period end, the quantity, and a plan an operator granted.
  `billing.rules` is the one table of what each plan entitles an org to
  (`PLAN_LIMITS`: members, api keys, active tasks, storage) and costs
  (`PLAN_PRICES`, Max's volume tiers mirrored by `monthly_price_cents`),
  and derives the plan from the mirror: a live status carries its plan,
  a subscription set to end carries it until the period's end, and a
  grant is a second source, the higher winning. `refuse_past` is the
  lever: it raises `PlanLimitReached`, a 402 carrying the lever, the
  plan, the bound, and the plan that lifts it. The tasks and tenancy
  managers hold `EntitlementsInterface` alone; the billing manager reads
  the processor through `PaymentsInterface` (see Integrations) and
  writes the account only from what it answers. `apply_delivery`
  re-reads the subscription for every delivery, copies it when the
  account follows it or it is live (`should_mirror`), and lands the
  delivery's mark (`BillingDelivery`, its id the delivery's UUID v5) in
  the account's commit, so a copy changes nothing and deliveries out of
  order converge. `org_of_delivery` is the request-stage lookup of the
  org a delivery names; `sync_seats` holds a Max subscription's
  quantity to the member count. The operator plane is
  `BillingOperatorManagerInterface`: read an org's plan, grant one.
  Both tables are `core` and `org`-scoped. The marks are purged after
  thirty days; a tenant past its retention loses its account too.
- `idempotency`: the durable outcome of a request the caller may retry,
  one record per (tenant, user, key); the gateway begins it before a
  creating request and finishes it with the outcome. The record carries
  the id the create uses, minted by the gateway before the marker, and
  the token of the attempt that holds it: `begin` mints one with the
  marker, and the take-over stamps one of its own in the same conditional
  write. A record left pending past its lease (a crash between marker and
  outcome, or an attempt still running past the lease) is taken over by
  the next retry, which runs the request again on that id; a create that
  finds its own id already written returns the row as stored, so the
  rerun cannot create twice. The one create that issues a secret, the api
  key, is the exception: the secret is stored as a digest and shown once,
  and the first one reached no one when the marker stored no outcome, so
  its rerun re-mints the secret on the row the id names, in the same
  storage method that inserts it (`issue_api_key`, one conditional write
  on the issuer's row, no second outbox row), and returns a fresh
  `IssuedApiKey` with the same id; the old secret stops authenticating.
  That write has two more guards in its own `WHERE`, because a re-mint is
  destructive where an insert is not. A revoked row is never re-minted,
  so a rerun cannot put a live secret back on a key somebody revoked in
  between. And the digest lands only while the marker on that id still
  holds the attempt making the write: an attempt that ran past the
  pending lease lost the marker to the retry that took it over, that
  retry has already handed its key to the caller, and the zombie's
  `finish` will be refused anyway, so its re-mint is refused here too.
  The fence is the marker's liveness and no clock is: two attempts can
  stamp one `created_at`, and a skewed clock orders them backwards, so
  there is nothing to compare and only a marker to ask. Both are a
  `Conflict` and change nothing.
  That makes the re-mint the one write outside the `idempotency`
  namespace that reads a marker. The marker is one of the two system
  rows every namespace touches, the outbox row being the other, so the
  read is the crossing the outbox row already is: the Postgres impl
  reads it in the same statement (both tables are in the `core` role,
  so no statement spans two), and the memory impl asks the markers the
  storage root hands it, through `AttemptFenceInterface`, the way it
  lands outbox rows through `OutboxLandingInterface`. The fence reads
  `(org_id, target_id)`, which the markers carry an index for; the
  unique index beside it leads with the key the caller sent and cannot
  serve it. The attempt travels from the gateway to the write on
  `Attempt`, the pair of the id the create uses and the token of the
  marker holding it, which `Idempotency.run` hands its handler.
  `finish` and `release` are conditional on the attempt token in the
  statement itself: the storage reports what matched (the record, or
  `None`; a bool for the release) and the manager refuses a lost attempt
  with `IdempotencyAttemptLost`, a `Conflict`, like a worker whose lease
  has passed. The gateway logs and counts the refusal (`attempt_lost`)
  and answers with what the attempt produced, which is the row the retry
  found. A failure (a `5xx`) is not an outcome: the marker is released
  and the retry runs again. The release keeps the record with its digest
  and its target id and clears only the attempt, so a released marker
  has no attempt and no outcome; the next retry re-arms it in one
  conditional write on that state (a new attempt token, the lease
  restarted) and reruns with the marker's id, so the retry that follows
  a failure after the row landed finds the row instead of creating a
  second one, and of two retries racing for a released marker exactly
  one re-arms it while the other is told to wait. A held marker is
  taken over only past the pending lease; a released one is re-armed at
  once, never taken over. A refusal (a `4xx`) is stored and replayed,
  its envelope rewritten with the replaying request's id, the one its
  header carries. The stored outcome of a create that issued a secret is
  the view with the secret absent: a wire view declares its secret fields
  (`View.secret_fields`; `IssuedApiKeyView` names `key`) and the gateway
  strips them before `finish`, for any route, so the first response alone
  carries the key, a replay answers with the row, `key` null, and
  `Idempotent-Replayed: true`, and the secret exists in one place, as a
  digest. The key lands in a unique index, so the gateway refuses one
  longer than 255 characters with a 422, and an empty one the same way:
  a header present with nothing in it is a malformed request, not an
  absence. The sweep purges finished and
  released records after the idempotency retention (24 hours; a retry
  that late begins afresh) and held pending ones past ten times the
  pending lease, a marker no retry came back for.
- `outbox`: the transactional outbox. A manager that writes a core row
  hands the storage the `OutboxRow`s that announce it (`org_id`, `kind`,
  `target_id`, a `payload` of ids only (a task's is empty), the actor, the
  request, and that request's `traceparent`, read off the tracer, since
  the context carries the trace id and a span links to the header) as one tuple, and the storage base inserts them all in one
  commit (`_insert(..., outbox_rows)` for a create, which
  reports an existing id and changes nothing then; `_upsert(...,
  outbox_rows)` for an update; `core` role). An entity change is one
  row; a write that also starts work passes a second row of kind
  `work.<kind>` in the same tuple, because the queue is a role of its
  own and no statement reaches both.
  The row carries its own `org_id`, stamped from the context the way the
  actor, the request, and the app are: the relay and the sweep run with
  no context and read the tenant off the row. The claim hands back rows
  and not pairs, because the row already names its tenant.
  The manager then calls `OutboxRelayInterface.relay(org_id, row)` for
  each; the tenant stays first in the signature, the shape an operation
  without a principal takes, and the row now also knows it. The row's
  kind is its destination: an entity change appends the
  `Event` under the row's id and publishes `entity_changed` with
  `(kind, target_id, seq)`; a `work.<kind>` row is enqueued by the
  relay (`WorkManagerInterface.enqueue_relayed(org_id, row)`, no
  context, the actor from the row, the row's id as the item's
  idempotency key, so a relay that runs twice leaves one item) and
  publishes `work_available`. Either way the row is then marked done.
  The relay reaches the work manager through a provider the business
  root binds, because the work manager needs the tenancy manager, which
  needs the relay; the graph the root hands back is still whole.
  A member added or removed on Max starts work: its commit lands a
  `work.SYNC_SEATS` row beside the change's, and the relay enqueues it
  ([ADR 0012](adr/0012-the-work-queue-has-no-producer-yet.md) records
  the interval before).
  Tadas relays in the request path, the step the guideline names as the
  one a system takes when push latency earns it, and pays the round
  trips it names for a push that arrives in milliseconds; the sweep
  alone, on an interval of a second or two, is the cheaper first step
  the guideline names, and Tadas keeps the sweep as the fallback
  instead. A relay that fails is logged and counted, never raised; the
  maintenance sweep claims whatever is pending. The claim is one
  statement (`FOR UPDATE SKIP LOCKED`, oldest first) over rows neither
  done nor failed, whose next attempt is due, and older than the grace
  (a younger row is the request path's to relay), so two sweeps relay
  disjoint sets; it spends an attempt and sets `next_attempt_at` with a
  delay that doubles per attempt, so a row that will not relay waits on
  its own and starves nothing behind it. A failed relay keeps its
  `last_error`; past the relay's `max_attempts` the row is failed for
  good (`failed_at`), logged, counted as `dead_letter`, and named by an
  `outbox.row.failed` event under the row's own provenance, best effort,
  since the stream may be what is failing. The grace, the backoff, and
  the attempt limit are `OutboxOptions`. Done and failed rows are purged
  after the outbox retention.
- `events`: the append-only stream behind every realtime push, in the
  `activity` role: `Event(Identifiable)` with `org_id` (on the event, as
  on the outbox row, because the relay appends with no context), `seq`
  (per tenant, gapless, assigned by the append, the one number storage
  assigns), `kind` (`<namespace>.<entity>.<action>`, or an audit kind),
  `target_id`, a `payload`, and the actor and request that produced it.
  The append takes the number from the tenant's cursor row in `event_cursors`,
  `head + 1` under the row's lock inside the append's own transaction,
  so two appends to one tenant queue on the row and a rollback returns
  the number with it; it never computes `MAX(seq) + 1` and retries on
  the unique `(org_id, seq)` index, which stays as a guard. The cursor
  row is also the tenant's head seq: `read_head`, the number the first
  frame and every pong carry, reads that one row. The append is
  idempotent on the event id, so relaying an outbox row twice appends
  once and consumes no number. An id another tenant owns is refused
  before the number is spent, over both impls, as Postgres rolls the
  number back with the insert it refused, so a write this tenant cannot
  make never moves its cursor. No update, and one delete: the sweep drops a
  tenant's whole stream once the deleted tenant is past the retention. An
  event about a user leaves out `email` and `display_name`. The entity events reach the stream through
  the event storage, from the outbox relay; the manager's `append_event` is for
  an audit entry (the work manager's dead letter), requires `WRITE`, and
  stamps the tenant, the actor, the request, and the app from the
  context, never from the caller's event.

Every table belongs to one database role (`core`, `activity`, `queue`,
`admin`); the map in `tadas.om.storage.roles` decides the schema, the
pool, and the migration chain.

Every table also belongs to one tenancy scope, and that map, in
`tadas.om.storage.scopes`, decides the row-level security policy it
carries: `system` for a global table (no policy), `org` for rows that
belong to a tenant, `both` for rows that belong to a tenant and to a
person in it, and `identity` for rows that belong to an identity and no
tenant, which no table is today. The policy is the second fence
([ADR 0016](adr/0016-row-level-security-is-the-second-fence.md)). The
first one is the predicate in the query, and it is the only one the
business layer relies on: no manager and no impl assumes a policy
exists, and the cross-tenant cases of the contract suites run unchanged
over Postgres. The policy is what catches the predicate that went
missing. `PgStorageBase._session_for` is the funnel every statement
already passes, and it takes the scope of the call, so the tenant is
named once per transaction and not once per query: it writes
`app.org_id`, and `app.user_id` when the call narrows to one person,
with `set_config(..., true)`, which dies with the transaction. Each
policy is `FOR ALL`, `USING` and `WITH CHECK` the same expression, with
`FORCE ROW LEVEL SECURITY` so the owner is held too, and the
application's login is never a superuser and never carries `BYPASSRLS`,
either of which walks past every policy. A transaction that names no
tenant reads nothing and is refused every write: fail closed, with the
silent read the accepted price. `EMPTY_UUID` as the tenant is the system
scope, the cross-tenant sweeps and the login lookups, spelled at the
call site and held to the enumerated exceptions by
`om/tests/unit/test_session_scope.py`. What proves the policy is live
rather than merely enabled is the two-run negative control in
[the tenant isolation runbook](runbooks/tenant-isolation.md). Migrations are hand-written SQL under
`om/migrations/sql/<role>/` with Alembic wrappers; `core`, `activity`,
and `queue` have chains today, and `admin` has no table yet. Each role's
pool carries bounds of its own: a size, how long a checkout waits before
it fails, and the deadline every statement on it runs under. Each is a
setting with a per-role override that defaults to the shared value, the
way a role URL does. The deadline travels in `server_settings`, so
Postgres cancels a statement that passes it on every connection the pool
opens and no call site carries one, and the driver's connect timeout is
the checkout bound, so a database that accepts no connection fails a
call inside the same bound. There is no overflow: the declared size is
the number of connections the process can hold, and a checkout past it
waits and then fails rather than queueing without end. One engine serves
each distinct URL and bounds, so roles that share both share a pool and
a role given bounds of its own is the bulkhead between two load profiles
on one database. `StoragePostgresImpl` takes the URLs and the bounds
from the settings object its composition root read at boot and reads no
environment of its own. Its `healthcheck` connects and runs `SELECT 1`
on every engine under the sum of that pool's two bounds, the worst a
healthy answer can cost, so a saturated or unreachable pool answers
false instead of holding the caller. Optimistic
concurrency stays opt-in: `tasks` is the one table that carries a
`version`, because a task is edited from two windows and two terminals
at once ([ADR 0009](adr/0009-tasks-carry-a-version.md)); every other
table has no concurrent edits that matter, so there the last writer
wins. Last writer wins does not extend to undoing a delete: every
update is a read, a copy, and a write of the whole entity, so a delete
that commits in between would be put back by a copy still carrying
`deleted_at = None`, leaving (for a user) a live row with no live
membership, listed but unable to sign in and past every sweep. Both
storage bases refuse it with `RowDeleted`, a `Conflict`; there is no
restore in this domain, and the caller reads the row again.

## Infrastructure (`infra/`)

The `tadas-infra` distribution fronts cache, buckets, topics, queues,
and secrets with interfaces, each with a local or memory impl and a
cloud impl (Valkey, S3, SQS, Secrets Manager). Infra imports nothing
from the object model: it has its own frozen model base, its own
exception root (`InfraException`, with the same `http_status` and `code`
shape the platform root has, so the gateway presents both alike;
`InfraUnavailable` (503, code `unavailable`) stands beside
`InfraNotFound` and `InfraValidationFailed` as the mirror of the
platform's `Unavailable`, and `BackendUnreachable` is a leaf under it
that inherits the code, so one code reaches the wire whichever side
says the call cannot be served now), and
the system scope as a value (`SYSTEM_SCOPE`, equal to the model's
`EMPTY_UUID`; a unit test holds the two together). Topics today:
`work_available` (`lane`, `kind`) and `entity_changed` (`kind`,
`target_id`, `seq`, `actor_id`); `TopicPayload` is a frozen base
declared in infra
with `extra="ignore"`, so a consumer ignores a field it does not know;
a payload gains only optional, defaulted fields, so an old producer's
message and a queued row written before a deploy still parse, and the
two sides roll out in either order. `actor_id` is the field that came
later, so it defaults to `NO_ACTOR`, the reserved UUID no person's id
equals: a frame from a replica one release behind is a change by nobody
the client knows, not a frame dropped as malformed. A bucket listing is
bounded like a storage read: keys in lexical order, at most `limit`, after
the key `after` names (S3 `MaxKeys` and `StartAfter`). A topic is best effort. Every capability interface declares `start()` and `close()`; the
roots call them unconditionally: the Valkey topic listener opens its
subscriber in `start()`, and each hosted impl (S3, SQS, Secrets Manager)
opens its one client there, holds it through an exit stack for every
call, and closes it in `close()`; nothing opens a client per call, and a
call before `start()` is refused. A listener the driver fails is not
left dead: the failure is counted (`topics` / `listener_failed`) and
logged, the subscriber is dropped, and a new one is opened after a
backoff that grows with consecutive failures.

- The queue impls count `sent`, `received`, `deleted`, and, in the
  memory twin where the transition is visible, `dead_lettered` on the
  outcome counter, with a log line naming the message and the queue;
  the twin does not deduplicate, exactly like SQS, and `send` offers no
  knob that says otherwise. The
  cache impls count `hit` and `miss` on `get`, and Valkey `unreachable`.
  On Valkey, `increment` is one server-side script (count, and set the
  window when the key has none), so a counter is never left without a
  window by a failure between two commands. Each infra root builds one
  cache per `CacheScope` in its constructor, like every other member
  (ADR 0007), so the boot line names every scope.
- One breaker stands in front of Valkey (`infra/breaker.py`), and there
  is one of it: the four cache scopes and the topic publisher hold the
  same instance, because a breaker stands for a dependency and not for
  an interface, so the first of them to pay the timeouts opens it for
  all of them. What it counts is the cost and not the error: a call that
  spends the whole of `TADAS_VALKEY_TIMEOUT_SECONDS` is a failure,
  `TADAS_VALKEY_BREAKER_FAILURES` of them in a row open it, it refuses
  for `TADAS_VALKEY_BREAKER_COOLDOWN_SECONDS`, and then one call goes
  through alone to decide whether it closes. It raises nothing. A
  decoration over each interface holds it (`cache/breaker.py`,
  `topics/breaker.py`) and answers the way the dependency's own failure
  answers, at once and without going out, so nothing above can tell an
  open breaker from a Valkey that is down: a `get` is a miss, a `put`
  and an `invalidate` are dropped, `increment` answers no count in the
  window asked for, which the login limit reads as fail open, and a
  publish is dropped, a
  topic being best effort. A payload of the wrong type still raises,
  because the breaker declines to pay the timeout and never to keep the
  contract. Its four outcomes are counted under the `valkey_breaker`
  subsystem: `opened`, `refused` once per call it turns away, `probed`
  for the call it lets through, and `closed`. While it is open the
  `cache` hit and miss counters and `topics` / `publish_failed` go
  quiet, since the dependency is not being asked at all, and those
  outcomes are what say why: an alert on `publish_failed` alone would
  fall silent exactly when the bus is worst. `subscribe` and the
  lifecycle calls pass through untouched, and the listener is not behind
  the breaker at all: it is one task on a subscriber of its own, nothing
  waits on it, and the reconnect backoff above is its bound. The memory
  impls are not wrapped either, being a dict on the process's own event
  loop, which cannot time out and cannot be down.
- The AWS impls translate every driver error into an `InfraException`
  leaf (`tadas.infra.exceptions`) through the one module that names
  botocore (`tadas.infra.aws_errors`): a service answer the impl cannot
  map is `BackendFailed` under its error code; an endpoint, connection,
  or timeout failure is `BackendUnreachable` under the driver's error
  class; any other driver error is `BackendFailed` under that
  class. Not-found codes keep their `NotFound` shape. The hosted secrets
  impl answers `has` with a describe, never a fetch of the value, and
  `put` is a create with a new version on `ResourceExistsException`,
  not a read followed by a write.
- Environment names are one set, shared with Terraform: `local` and
  `test` allow the local backends; `dev`, `staging`, and `production`
  refuse them; any other name is refused at boot. A secret belongs to a
  tenant: every `SecretsInterface` call takes the `org_id` first, each
  store keeps a tenant's secrets under `org/<org_id>/`, and a name is one
  segment, so none climbs out of its tenant's prefix. The local secrets
  impl receives its `TADAS_SECRET_<ORG>_<NAME>` overrides from the settings
  object, collected once at boot from `.env` and from the environment
  over it, the two sources every other setting has; nothing below
  settings reads either. `.env.example` documents every knob.

- Every outbound client carries a timeout from settings, one per client,
  so a downstream that hangs cannot hold a replica's whole pool:
  `TADAS_AWS_TIMEOUT_SECONDS` bounds connect and read on every AWS client
  (`tadas.infra.aws_clients` is the one module that names botocore's
  client configuration; an SQS long poll is capped two seconds below it,
  and at the queue's own twenty, so an empty poll answers empty instead
  of timing out), `TADAS_VALKEY_TIMEOUT_SECONDS` every Valkey
  request, and `TADAS_OTEL_TIMEOUT_SECONDS` every trace export. The
  Sentry SDK bounds its own transport.

`InfraConfiguredImpl` picks impls from settings; `InfraLocalImpl` runs
everything in-process for tests.

## Integrations (`integrations/`)

The `tadas-integrations` distribution holds the providers the platform
cannot conjure, each an interface with a real client and a deterministic
twin; it imports infra and nothing from the object model, and its
exceptions hang under infra's root. Payments is the first:
`PaymentsInterface` (a customer per org, a checkout, the processor's
portal, cancel at period end, the seat count, a read of a subscription,
and `verify_delivery`), `PaymentsStripeImpl` over the Stripe SDK (one
client opened at start, `Stripe-Context` naming the account and a pinned
`Stripe-Version` on every call, a timeout on its transport, errors
translated to `PaymentsRefused`, `BackendUnreachable`, or
`BackendFailed`), and `PaymentsTwinImpl`, which keeps customers and
subscriptions in memory and signs its own deliveries with the
processor's scheme, which the SDK's own check verifies. `build_payments`
refuses the twin outside local and test and a key whose mode is not the
environment's (production live, everything else test), and with no key
answers `billing_unavailable` (503) to every call.
`PaymentsCatalogInterface` is the bootstrap's view of the same account:
products, prices by lookup key, webhook endpoints, and the portal's
configuration.

## Processes

- `services/api` (`tadas-api`): the one API process. Gateway (bearer
  by prefix, `NotAuthenticated` (401) when none or an invalid one is
  presented, request id, error envelope, rate limits keyed on the
  credential id or, on an unauthenticated route, the client address,
  admission, edge idempotency), routers for tenancy, tasks, and the
  operator plane
  under `/v1/admin/*`, health, readiness, and metrics outside `/v1`, and the
  realtime channel at `/v1/realtime` opened with a single-use ticket,
  billing under `/v1/billing`, and the payment processor's deliveries at
  `/webhooks/stripe`, outside `/v1`: the gateway reads the body and the
  `Stripe-Signature` header, the service checks the signature and its
  five-minute window before anything is queued, and queues the delivery
  on `webhooks` under a UUID v5 of the event id. A `plan_limit_reached`
  envelope carries `plan_limit`, and the edge's idempotency marker is
  released on a 402 as on a 429.
  The client address is the peer's, or the one `X-Forwarded-For` names
  when the peer is one of `TADAS_TRUSTED_PROXIES` (empty locally; the
  VPC block in the cloud, where the load balancer lives; each entry is
  an address or a CIDR block, never `*`, which the settings refuse at
  boot because a wildcard trusts every peer and so lets any caller pick
  its own address), so behind the load balancer the login limit still
  counts per client and a peer outside it cannot pick its own address. The envelope carries the
  exception's code and status; for a status of 500 or more its message
  is `internal error` and the real one goes to the log under the
  request id. An unhandled exception is answered inside the
  observability middleware, while the id is still in hand, so the 500
  carries the request id header, the log line the id, and the request
  counter the status; Starlette's own catch-all stays as the last
  resort. CORS sits outside that middleware, so the envelope it writes
  carries the headers a browser needs to read it, as a refusal from the
  same origin already did; a preflight is answered before the request id
  is minted and belongs in neither the access log nor the metrics.
  The chain is CORS, then the request id, then admission, then the
  router. Admission is the bound on what this process has in flight
  (`gateway/admission.py`), and it is two bounds: a read lane for `GET`
  and `HEAD` (`TADAS_ADMISSION_LIMIT_READS`) and a write lane for every
  other method (`TADAS_ADMISSION_LIMIT_WRITES`), counted apart so that a
  read storm, which is what a client replaying its backlog after an
  outage is, cannot take every slot from the commands. A method the
  process does not know is a write, since the cheaper budget is not the
  one to hand an invented method. Past a lane's bound a request is
  refused at once with `Unavailable` (503, code `unavailable`) in the
  one envelope, naming the lane that is full, and a `Retry-After` of
  `TADAS_ADMISSION_RETRY_AFTER_SECONDS`, so a saturated process answers
  and says why instead of queueing work it cannot start. It is not the
  rate limit beside it, and the two fail in opposite directions: a rate
  limit is fairness between subjects, counted in the shared cache, and
  fails open, while admission is the process defending itself, counted
  in its own memory on the one event loop, and fails closed. It sits
  inside CORS because a browser has to read the refusal and its header,
  and inside the request id because a refusal is an answer of this API
  like any other, with an id to correlate on, a line in the access log,
  and a count per lane (`admission_reads` and `admission_writes` /
  `admitted`, `refused`; a lane is a subsystem of its own, since the one
  outcome counter carries the two labels every subsystem shares). The
  three operational routes are never refused in either lane, since a
  saturated process must still be able to say that it is saturated and
  the collector must still be able to read by how much, and a socket
  holds no slot, a bound a long-lived connection can fill being no bound
  on requests.
  `/healthz` answers from the process alone and `/readyz` asks storage
  whether it can serve a request right now, under
  `TADAS_READINESS_TIMEOUT_SECONDS`, shorter than the interval it is
  polled on: the deadline answers 503 and `ready: false`, so a hung
  database makes the probe say no rather than stop answering.
  Starlette's own `HTTPException`, which it raises for a path that
  matches nothing (404) and a method a route does not take (405), is
  presented as the envelope too, not as its default `{"detail": ...}`. uvicorn's access log is off: the middleware writes one line
  per request by route template, and uvicorn's remaining lines lose
  their query string, so the socket ticket, which travels as a query
  parameter, is never logged.
  The gateway mints the request stage once per request
  (`request_context`: the request id the middleware stamped, `X-App`
  and `X-App-Version`, the current trace id) and asks the tenancy
  manager for every stronger stage: `Ctx` is `authenticate` over the
  bearer (a session token or an api key), `Identity` is
  `authenticate_login` over it (the sign-in credential or a live session,
  on the tenant choice, the switch, `GET /v1/auth/memberships`, and the
  operator gate), `OperatorCtx` is `admit_operator` over the identity,
  which admits the sign-in credential alone, and the socket builds the request stage from its scope,
  accepts the handshake, and then redeems its ticket: a refusal is a
  close with code 4401 on the open socket, which both clients read as
  "sign in again" (a close before the accept would reach the wire as an
  HTTP 403 handshake failure, indistinguishable from any other refusal).
  An admitted socket holds the context its ticket produced for the life
  of the connection, and that life is bounded twice. A revocation
  reaches it: revoking a session (`revoke_session`, `logout`) lands an
  outbox row `tenancy.session.revoked` beside the session, as removing
  a member lands `tenancy.user.deleted` and revoking a key
  `tenancy.api_key.deleted`, the relay publishes each on the bus like
  any change, and the realtime service in every process hears it and
  closes the sockets it names with 4401 (the one the session or the key
  opened, every one of the removed user, every one of a deleted org),
  in whichever process they
  live. The expiry is the bound that covers a frame the bus dropped:
  the redemption yields the context beside the session's or the api
  key's expiry (`SocketPrincipal`), and the handler closes the socket
  with 4401 at that instant whatever the client does. Either way the
  clients sign in again, as they do for a refused ticket. A role change
  is not a revocation: the socket carries hints, and the next request
  sees the new role.
  The login route takes the request stage alone.
  Per socket the process keeps one send buffer of two bounded lanes
  (`realtime/send_buffer.py`) and a drainer. A frame that says where the
  socket stands is a control frame (`hello`, `pong`, `subscribed`,
  `unsubscribed`, `error`) and an event hint is a stream frame; the
  drainer writes the control lane first, so a burst of hints never
  delays the pong that carries the head seq and never evicts it. A full
  stream lane (`TADAS_REALTIME_SEND_BUFFER_SIZE`) drops its oldest
  frame, logs it, counts it, and the client that sees the gap replays.
  The control lane has a small bound of its own
  (`TADAS_REALTIME_CONTROL_BUFFER_SIZE`), and a lane that fills there is
  a fault of the process rather than a burst, so its drop is logged as
  an error. The revocation close and the transport keepalive are not
  buffered at all.
  A peer that drops mid-stream ends the drainer with a disconnect; the
  teardown treats that as the normal end of a socket, not an error.
  Two pings keep a socket alive, one per direction, both pinned with the
  load balancer's idle timeout in `deployment/realtime-timeouts.json`
  (`realtime/timeouts.py`, held to the file by
  `test_realtime_timeouts.py`): the client's application ping every 25
  seconds from a timer of its own, whatever the inbound traffic, whose
  pong carries the head seq, and the server's protocol
  ping every 20 seconds, which uvicorn sends (`ws_ping_interval`,
  `ws_ping_timeout` in `server_options`) and which closes the socket
  when no pong arrives within 20 more; the two together stay below the
  60 second idle timeout, so the server, not the load balancer, ends a
  dead socket. The protocol ping is answered by the client's socket
  implementation, not by the app: a browser answers it from the tab
  whose timers it has throttled in the background, so that tab keeps
  its socket and only its head-seq check slows down. There is no
  heartbeat thread beside the event loop, on purpose: the process is
  one loop that must never block, a blocked loop fails every request
  and the health check with it, and a thread that kept pinging through
  that would only hide it.
  No service calls another today, so no internal credential is minted;
  `CredentialKind.INTERNAL` is what the seeding and the worker's service
  contexts carry. The sweep's service contexts are minted for the tenant,
  not for a member: each carries the tenant, the service role, and the
  system user (`EMPTY_UUID`) as its actor, at one read per page of
  tenants, so a tenant whose members have all left is still swept. The
  claim of a work item is minted the same way, with the enqueuer's
  `user_id` kept as the attribution: the person authorized the work once,
  at enqueue, so only the org must be live, and a member who has left
  does not stop the work they asked for.
  `tadas-api serve | migrate | bootstrap | add-member | openapi`
  (`bootstrap` and `add-member` are what `make seed` runs; both produce
  the context the seeding then runs under).
- `workers/maintenance` (`tadas-maintenance`): beside the claim loop, a
  delivery consumer that long-polls the `webhooks` queue, finds the org a
  delivery names, and applies it under that org's service context,
  deleting the message once applied or when it never can be and leaving
  any other failure to its visibility and the queue's dead letter; the
  claim loop for the kinds `NOOP` and `SYNC_SEATS` on one lane (`TADAS_WORKER_LANE`, or `serve --lane`), lease
  renewal and self-fencing (a renewal refused with `LeaseLost` cancels
  the running task at once, because another worker holds the item now;
  a renewal that fails for any other reason is retried once, each
  attempt bounded by the time left to half the lease, and the task is
  cancelled at half the lease if none succeeds, half the lease before
  it expires), a liveness heartbeat held in memory and published to the
  cache as best effort (each publish bounded by its interval; a cache
  that stalls or raises leaves the worker unpublished and still
  claiming, since the queue and its leases live in Postgres), and the
  maintenance sweep (requeue stale leases under one service context per
  tenant, a batch of `requeue_batch` (100) per tenant per sweep bounded
  in the statement and the rest on the next sweep, the system scope
  first and deleted tenants included, then
  purge the tenant's soft-deleted tasks, removed
  members with their ended memberships, revoked api keys, dead sessions,
  and spent socket tickets past their retention (the one hard delete,
  30 days by default), its finished idempotency records and abandoned
  markers, then claim and relay the
  pending outbox rows, one attempt each with a growing delay, and purge
  the done and failed ones after eight days, which outlives the
  seven-day database backup retention, so a role restored to an earlier
  point than its siblings is reconciled by relaying the outbox again,
  and purge every tenant's done or failed work items past their retention
  in one statement, `purge_items`).
  Under a tenant whose org row is deleted longer ago than the retention
  it is every row that goes, its open and done tasks among them, since
  an open task carries no `deleted_at` of its own and the sweep that
  reads one would leave it forever; the org row stays as the record.
  Each namespace purges its own rows and asks tenancy the one question,
  `tenant_expired`, so the whole sweep reads one answer.
  `tadas-maintenance serve | health`.
  The serving process answers `/metrics` and `/healthz` on
  `TADAS_METRICS_PORT` (9464) from one thread: `/healthz` asks the
  loop for its last beat, on its event loop, so a blocked loop fails
  the probe, a cache outage does not, and the probe boots nothing;
  the image's `HEALTHCHECK` and the task definition ask that URL, and
  `health` asks it by hand.
- Every Python process builds its roots whole at boot, once: storage,
  infra, then every manager, in dependency order; a request constructs
  nothing. The cost is the imports (about 450 ms, once per process);
  a root itself builds in microseconds. `make benchmark-boot` measures it;
  [ADR 0007](adr/0007-roots-built-whole-at-boot.md) says why a lazy
  root is refused.
- Every Python process boots error reporting (the Sentry SDK, on only when
  `TADAS_SENTRY_DSN` is set: unhandled exceptions and ERROR log lines,
  tagged with `service` and `request_id`, and carrying the environment
  the process runs in, which is what separates the environments inside
  the product's one tracker project), tracing (OpenTelemetry, on only
  when `TADAS_OTEL_ENDPOINT` is set), and Prometheus metrics, all from
  `tadas.infra.observability`. Naming the process is a boot step of its
  own, right after logging and before all three, so every line a process
  writes carries the service and the environment whether or not error
  reporting is configured, beside the request id and the request that
  caused it where a handoff named one; one filter attaches all four and
  no call site passes any.
- Two processes raise spans: the API's middleware opens the server span
  per request, and the worker opens one per run of a work item. The run's
  span links to the trace context the item carried instead of becoming its
  child, because a durable queue holds an item well past the end of the
  request that filled it; an item that carries none starts a trace of its
  own, which is what a process with no tracer configured does anyway.
- `apps/portal` (`@tadas/portal`): React, Vite, TanStack Query,
  Zustand; sign-in and sign-up (`/sign-up`: email, name, password), the
  picker when a person has several orgs, the personal one first, an org
  chip in the chrome that switches the tab's one session (the old
  tenant's cache dropped, the socket reopened) and opens the new team
  org at `/orgs/new`, which creates it and switches into it, the
  tasks screen at `/` (My and Team's tasks, open in
  manual order and done newest first, both paged by the server's cursor
  with Show more, inline edit, drag to reorder), settings at `/settings`
  (members, api keys with Show more, sign-out, which revokes the server
  session and empties the query cache with the token), and one realtime
  channel that
  invalidates queries by the entity name inside a push's `kind`, or by
  the query that carries the entity (a membership, through `me`); the
  status says connecting from the moment a socket drops, degraded from
  the second failed cycle, and closed on a 4401. Every
  write sends the version of the task the query cache holds; a write
  the server refused because the task changed since (the drag reorder
  is the natural case, from two windows) is said in one line and the
  list refetched. The reorder is one flow with its effects handed in
  (`src/features/tasks/reorder.ts`), so the stale case runs in a test
  without React. The socket's loop (`src/realtime/channel.ts`: ticket,
  reconnect with a backoff that doubles and carries jitter, so tabs
  dropped by one shared failure do not come back at the same instant,
  the degraded polling mode, the cursor and its
  replay) has no React in it and runs in its test over a fake socket and
  fake timers; the provider hands it the query cache, the transport
  client, and the connection store. A socket counts as connected once
  the hello frame arrives (or once it has stayed open a few seconds), so
  a server that accepts and closes at once still meets a growing
  backoff. The client keeps the last contiguous `seq`; a push ahead of
  it is a replay of `/v1/events` after the cursor, never a skip: the
  replay pages until the last page, a failed fetch, or a page that moved
  the cursor nowhere (a seq between is not in storage yet), and the
  cursor never moves past a seq that was not applied, so the next push
  or pong retries from where it stands.
  Errors go to the Sentry-compatible backend named by `sentryDsn` in
  the runtime `config.json` (locally, by `VITE_SENTRY_DSN`), through
  every route's `errorElement` and React's root error hooks; the DSN is
  the product's one project in every environment, and the config's
  `environment` rides on each event, which is what separates them. A write
  that fails is said, never swallowed: a view-model turns what it caught
  into one line (`src/app/errorMessage.ts`, the request id of an API
  refusal quoted) and leaves it in the notices store, which `Notices`
  renders above every page as a kit banner until dismissed or after a
  few seconds. The API is reached through `src/api/`: the committed
  `openapi.json` at the app root, generated types behind the facade
  `types.ts`, one transport client, which puts a deadline on every call
  (`requestTimeoutMs` in the runtime config, 30 seconds by default) and
  rejects a call that runs out with `RequestTimeout`, which carries the
  app's one retry (`src/api/retry.ts`, `retryAttempts` and
  `retryBaseDelayMs` in the same config): a read or a POST under an
  `Idempotency-Key` may be sent twice and nothing else may, a deadline,
  a connection that failed before an answer, and a 502, 503, or 504 are
  what it retries, any other status being a decision that does not
  change for being asked again, and the wait doubles per attempt and
  carries jitter. TanStack Query's own retry is off, queries and
  mutations alike, so a failing API sees those attempts and no multiple
  of them. The client reads
  the status and the content type before the body: a 401 clears
  authentication whatever its body is, a proxy's HTML 502 or 504 is an
  `ApiError` carrying the status and the request id, and a success that
  is not JSON is a typed error too. Client state is in stores, never
  read from a storage by a feature: the session token lives in memory
  and in the tab's session storage, so a reload survives and a closed
  tab forgets, never in local storage, and a token an earlier build left
  there is dropped on load; the preferences kept across visits (the task
  scope) live in a persisted store over local storage, which is for
  preferences only. Every push and every event record carry `actor_id`, so a client
  can say who changed what, and the hello frame and every pong carry
  the stream position (`seq`), so a client replays from there after a
  reconnect even when no push reached it before the drop, and a push
  that was dropped with nothing behind it is found on the next
  keepalive rather than on the next event.
- `clients/python` (`tadas-client`, `tadas.client`): the one Python client,
  generated from the same committed `openapi.json` (`schema.py`, by
  `make openapi`, for the workspace's Python version, which CI holds
  current) behind the facade `types.py`; one transport client with
  the error envelope, idempotency keys, the OS trust store, and a timeout
  on every call, which the caller's settings name (the CLI reads
  `TADAS_HTTP_TIMEOUT_SECONDS`) and the socket's open shares; the retry
  arrives through the constructor beside it (`TADAS_HTTP_RETRIES`,
  `TADAS_HTTP_RETRY_BACKOFF_SECONDS`), under the portal's rule, so a
  caller sets the policy and none of them wraps a second round of
  attempts around this one; the socket
  frames mirrored by hand (`envelopes.py`); the placement rule
  (`stream.py`); and the channel (`realtime.py`): ticket, one
  subscription, pings, gaps replayed from `/v1/events`, reconnect with a
  backoff that carries jitter, so listeners dropped by one failure do
  not come back at the same instant. The demo recorders use it; the interval before it existed is
  [ADR 0004](adr/0004-demo-recorder-calls-the-api-directly.md).
- `apps/cli` (`tadas-cli`, `tadas`): Typer over the Python client. Command
  mode (`add`, `ls`, `edit`, `done`, `reopen`, `rm`, `mv`) does one call
  and exits with 0, 1 (refused), 2 (usage), 3 (not signed in), or 4
  (unreachable: any failure of the wire, refused, timed out, or reset;
  the API did not decide); a verb that changes a task reads it first and
  sends the version it read, so a change that raced another is refused
  (exit 1) and never overwrites it, and `ls` follows the cursor to the
  end of the list; `listen` prints every task change as one line (who did
  what to which task) as it arrives on the channel, `--mine` for the
  caller's own; a task read that fails is told on stderr and the change
  skipped, the channel is not ended by it. `login` keeps a session token
  under `TADAS_HOME`; `logout` revokes it at the API that issued it and
  forgets the file whatever the API answers; `TADAS_TOKEN` (a session
  token or an api key) and `TADAS_API_URL` win over it. The rules of what is shown live in `model.py`, pure and unit
  tested; the commands run in tests against the whole API in-process.

## Deployment (`deployment/`)

- `local/`: the compose stack (Postgres, Valkey, ElasticMQ, MinIO, and,
  under the `devx` profile, developer dashboards plus Prometheus, Grafana,
  Jaeger, and a seeded GlitchTip) and a second file that adds the
  application containers, the portal among them. Prometheus scrapes the
  containers; the host processes, which stay on 127.0.0.1, are scraped by
  an OpenTelemetry collector that remote-writes into Prometheus, the shape
  of the cloud's sidecar. On Linux a third file, which the Makefile adds,
  puts that collector on the host's network, the one place a loopback
  listener answers.
- `docker/`: one two-stage image per process, non-root, with a
  healthcheck (`/healthz` for the API and, on its metrics port, the
  worker; `/` for the portal's nginx). That probe decides whether the
  process is alive and should be restarted, which is liveness. ECS reads
  the task definition's own health check rather than this one, and it
  probes `/healthz` too. The API's target group probes `/healthz` as
  well: ECS replaces a task its target group calls unhealthy, so a
  readiness probe there would turn one database blip into every replica
  replaced at once. `/readyz` stays the process's answer on whether it
  can serve right now.
- `terraform/`: every cloud resource. `modules/` holds one module per
  resource family (`network`, `cluster`, `database`, `cache`, `queue`,
  `buckets`, `secrets`, `load_balancer`, `certificate`, `domain_records`,
  `portal`, `service`, `alarms`, `dashboard`), `environment`, the graph
  that wires them and that each root calls, and `account`,
  `deploy_role`, and `investigate_role`, which the bootstrap roots
  instantiate; `environments/staging`
  and `environments/prod` instantiate the same graph and differ only in
  variables, including the image digests, the autoscaling flip, and
  the alarm address. Each environment has an AWS account of its own,
  named in `deployment/cloud/environments.json` with the region and the
  public names
  ([ADR 0021](adr/0021-each-environment-has-an-aws-account-of-its-own.md)),
  and every root pins its provider to that account. `bootstrap/staging`
  and `bootstrap/prod` hold what an account has before its first deploy:
  the registry, the state bucket, the two zones, the deploy roles, the
  investigate role, and the budget (see
  [Operations](#operations-ops-claudeskills)). Staging's replicates
  every image and portal build into production's account, so
  production never reads staging's. The load balancer's idle timeout is read from
  `deployment/realtime-timeouts.json`, the file the api pins its
  protocol ping against and the api and the portal pin the client's
  ping interval against. The API's target group polls `/healthz`,
  which reads no dependency.
  The worker's service instance
  caps a rollout at 100% of desired because a worker holds leases. Every
  task runs an ADOT collector sidecar that scrapes the process's
  `/metrics` into CloudWatch (namespace `Tadas`) and forwards its traces to
  X-Ray; the load balancer answers `/metrics` with a 404. Errors report to
  the DSN in the `<prefix>sentry_dsn` secret, which starts as `off`. That
  secret is per environment because a secret is per account, but the DSN
  in it is one project's: there is one tracker project for the product,
  and the environment on each event is what separates them, so a read of
  it filters on `environment:<env>`. The payment processor's key and the
  signing secret of its endpoint are `<prefix>stripe_org_key` and
  `<prefix>stripe_webhook_secret`, injected into the API and the worker
  the same way and "off" until set (`tadas-ops stripe-bootstrap` writes
  the second), and each root commits its `stripe_account_id`: the
  sandbox for staging, the live account for production. The
  module README explains state and credentials.
- `.github/workflows/ci.yml`: the fast gate, the integration job (which
  runs `make migrate-check` right after `make migrate`), an image build
  per Dockerfile, and `terraform fmt -check` plus `validate` per root.
- Two branches, two deploy workflows, one approval
  ([ADR 0008](adr/0008-main-is-staging-release-is-production.md)).
  `main` is staging: `deploy-staging.yml` follows every green `ci` run
  on `main`, builds and pushes both images tagged by the commit `ci`
  ran, keeps the portal build by the commit in its artifacts bucket, and
  plans and applies staging with no approval (the plan text goes to the
  job summary and the `staging-plan` artifact). `release` is production,
  moved only by a fast-forward from `main` that `release.yml` makes when
  a person dispatches it (a pull request into `release` fails its one
  check). A push to `release` runs `deploy-production.yml`: a guard that
  refuses unless `release` is an ancestor of `main` and the `production`
  environment carries a required-reviewers rule, a job that resolves the
  digests and the portal build staging made for that commit, from the
  copies replicated into production's account, and refuses a commit
  with no copy there, a plan job (text to the
  `production-plan` artifact, the saved plan to the state bucket), and,
  behind the `production` environment's approval, an apply of exactly
  that plan and the publication of the same portal files. Nothing is
  rebuilt for production. The migration is inside the apply: the
  `service` module runs the API's `pre_rollout_command` as a one-off
  task on every new task definition before the service rolls, the
  worker rolls after it, and every service waits for steady state, so a
  failed migration or a rolled-back rollout fails the apply with the old
  tasks still serving; a migration is compatible with the release before
  it (expand and contract), so the old tasks serve the new schema
  meanwhile. Each environment has a credential of its
  own, and production has two: `tadas-deploy-staging` for staging,
  `tadas-plan-production`, which reads, for the plan, and
  `tadas-deploy-production`, which writes, for the apply. The trust of
  each names one GitHub environment and one branch, so the required
  reviewer on `production` holds the credential and not only the step:
  a job that has not waited there cannot mint the subject the writing
  role trusts. The plan runs before that approval by construction, so
  it runs under the reading role, in an environment of its own,
  `production-plan`, which carries no reviewer. Each GitHub environment
  holds its own variables under the same names (`AWS_ROLE_ARN`,
  `TF_STATE_BUCKET`, and, where the job plans, `API_DOMAIN_NAME`,
  `APP_DOMAIN_NAME`, and `ALARM_EMAIL`), so a staging job never holds a
  production value, and the first job of each workflow checks them;
  while they are empty staging skips every cloud job, says so in the
  summary, and stays green, and production fails. [The deploy
  runbook](runbooks/deploy.md) says how to cut a release, what to check
  at the approval, and how to roll back.
- Public names are inputs: the API at `api_domain_name` (the load balancer,
  e.g. `api.tadas.fyi`, `api.staging.tadas.fyi` for staging) and the portal at
  `app_domain_name` (a private S3 bucket behind CloudFront, e.g.
  `app.tadas.fyi`). Each name is the apex of a Route 53 zone of its own
  in the environment's account, delegated from the domain's zone at
  Cloudflare, where the domain is registered, and holds its certificate's
  validation record and its alias. Each environment has one base domain,
  `tadas.fyi` for production and `staging.tadas.fyi` for staging; the
  names are written in `deployment/cloud/environments.json`, and the
  workflows pass them from the environment's variables. The
  portal reads `/config.json`, written per environment by Terraform, before
  it renders, and calls the API cross-origin; locally it falls back to the
  `VITE_` build variables. The distribution's response headers policy,
  declared beside it in the portal module, sends the security headers:
  a `Content-Security-Policy` that names the page's own origin, the API
  over HTTPS and over the websocket (both from `api_url`), the error
  reporter's origin when a DSN is set, and nothing else, with no unsafe
  directive because the build has no inline script or style; plus
  `nosniff`, `DENY` framing, the referrer policy, and HSTS. An offline
  `terraform test` in the module pins the header. The local nginx sends
  no such header: the API and GlitchTip origins it would name are build
  arguments the static config cannot read.

## Operations (`ops/`, `.claude/skills/`)

People steer, agents maintain. Every operational task is a skill a
person runs with an agent, and the boundary is the credential the
skill holds. [ops/README.md](../ops/README.md) is the operator's own
page; this section says what exists.

- **Roles.** Four, as "Operator Roles" names them. The administrator is
  a person under the account's administrator profile
  (`tadas-staging-admin`, `tadas-prod-admin`, an Identity Center
  permission set), and only `scripts/cloud_create.sh` and
  `scripts/cloud_nuke.sh` run under it.
  The deployers are the three OIDC roles of
  [ADR 0013](adr/0013-each-environment-has-its-own-deploy-credential.md).
  The investigators are `tadas-investigate-staging` and
  `tadas-investigate-production`, declared by `modules/investigate_role`
  in each account: `ReadOnlyAccess`, the log, trace, metric, cost, and
  budget reads spelled out, the state bucket's environment prefix so
  `terraform plan -lock=false` runs, and fences that deny every
  `secretsmanager:GetSecretValue`, every object of a data bucket,
  `rds-db:connect`, the other environment by tag, and every `iam:*`
  write. The supporter holds no role of its own: it is the investigate
  profile plus an operator identity whose allowlist entry is read
  ([ADR 0018](adr/0018-the-operator-allowlist-carries-a-role.md)).
  There is no IAM user and no access key: the investigate role trusts
  the account's Identity Center PowerUserAccess role, and an agent runs
  inside the session a person signed in
  ([ADR 0021](adr/0021-each-environment-has-an-aws-account-of-its-own.md)).
- **Credentials.** Three profiles per account in `~/.aws/config`: the
  administrator (`tadas-staging-admin`, `tadas-prod-admin`), the
  sign-in (`tadas-staging`, `tadas-prod`), and the investigate profile
  (`tadas-staging-investigate`, `tadas-production-investigate`), which
  chains from the sign-in.
  Everything else an operator reaches lives in
  `~/.config/tadas/ops/<env>.env`, owner-only: the API's URL, the
  operator identity (a read entry), the provisioner identity (the
  file's one write entry, used only by the traffic generator to create
  a run's tenants), the error tracker's URL and token, and for
  `local` the Prometheus and Jaeger URLs of the `devx` profile. Every
  skill verifies the profile it holds with `sts get-caller-identity`
  before it reads, and refuses a wider one.
- **Skills.** The nine of "Operational Skills", under `.claude/skills/`,
  copied from the guideline's templates with the product's name:
  `ops-investigate`, `ops-watch`, `ops-root-cause`, `ops-infra-as-code`,
  `ops-cloud-deployment-create`, `ops-cloud-deployment-nuke`,
  `ops-simulate-traffic`, `stress-test-create-or-update`,
  `stress-test-run`. Every one that reads or drives an environment
  takes `--env local|staging|production`, and `local` reads the
  compose stack's twins, so each is exercised with no cloud; create
  and nuke take `staging` or `production` only, and
  `stress-test-create-or-update` writes a file and touches none. The
  eight that hold a credential read
  `.claude/skills/_shared/ops-preamble.md` first, where the profiles,
  the account check, and the env file's fields are written once; the
  rules that stop a secret leaking stay inline in each of them, and
  `infra/tests/test_ops_skills.py` holds both halves.
  The first responder is an agent: `ops-investigate` and
  `ops-watch` read the platform's size (`tadas-ops size`) before they
  escalate an alarm, and a platform of one tenant and one user is the
  developer at work.
- **Dashboards and alarms.** `modules/dashboard` declares the CloudWatch
  dashboard `tadas-<env>` from a template whose first five panels carry
  the titles of the local Grafana dashboard
  (`deployment/local/grafana/dashboards/tadas-overview.json`), and
  `infra/tests/test_dashboard_parity.py` holds the titles equal.
  `modules/alarms` declares the SNS topic `tadas-<env>-alarms`, the
  email subscription from `alarm_email`, and seven alarms: the load
  balancer's 5xx ratio, its unhealthy targets, its p95, the database's
  CPU and free storage, and each of the two services running below its
  desired count. [runbooks/operate.md](runbooks/operate.md) reads them.
- **Scale-out.** Every service declares an autoscaling target and a
  CPU target-tracking policy in `modules/service`, created only when
  its `autoscaling.enabled` is true. The environment module ANDs each
  service's own `enabled` (true by default) with the root's
  `autoscaling_enabled`, which both roots set to `false`: the one flip.
  `desired_count` stays the truth an apply resets to, and the policy
  raises it from there ([runbooks/scale.md](runbooks/scale.md)).
- **Cost.** Each account's bootstrap root declares a monthly budget
  (`monthly_budget_usd`, 200 by default in each, sized in
  [deployment/cloud/README.md](../deployment/cloud/README.md)) with alerts at 50, 80, and 100 percent actual and
  100 percent forecast to `owner_email`, and a cost anomaly monitor
  by service with a daily subscription above 20 dollars of impact.
  Every log group has a retention and every resource carries
  `tadas:environment` from the provider's default tags.
- **Create and nuke.** `scripts/cloud_create.sh <env>` is the
  administrator's one run per account, staging, then production, then
  staging again to turn the replication on: the state backend, the
  bootstrap root, the delegation of the two names at Cloudflare, the
  investigate profile, the GitHub environments and their variables, the
  first deploy through the pipeline, and the smoke command. It clears
  any AWS key exported in the shell and checks the account before every
  apply.
  `scripts/cloud_nuke.sh <env>` refuses `production` unless
  `--confirm production` is typed, `environments/prod/main.tf` on
  `origin/release` reads `database_deletion_protection = false`, and
  production's state shows that release applied; it applies
  `destroyable=true`, destroys, and names what remains. Production keeps
  its final snapshot and its automated backups either way. Both
  take `--dry-run`, and `infra/tests/test_cloud_scripts.py` runs the
  dry runs and the refusals. Neither has run against an account yet.
- **Traffic, stress, and the round trip.** `ops/` is the `tadas-ops`
  distribution: `tadas.ops.traffic` plays realistic sessions over
  `clients/python` at four profiles; `tadas.ops.stress` runs a scenario
  from `ops/stress/` with a ramp and a target; `tadas.ops.signals` is
  one `SignalsInterface` with `SignalsLocalImpl` (Prometheus, Jaeger,
  GlitchTip, the process's own log stream) and `SignalsCloudImpl`
  (CloudWatch Logs Insights, CloudWatch metrics on namespace `Tadas`,
  X-Ray, Sentry). `ops/tests/test_telemetry_roundtrip.py`, marker
  `telemetry`, starts the API as a real process on a free port, aims
  the devx collector at that port for the length of the run
  (`make collector-scrape`), drives one session, and reads every
  signal back by request id; `make test-telemetry` runs it, and CI's
  `telemetry` job runs it under `TADAS_TELEMETRY_REQUIRED=1`, which
  turns the skips a developer's machine wants into failures, then
  with thirty seconds of light traffic
  (`make traffic PROFILE=light DURATION=30`). A run signs
  each of its people in once and out once, and the target judges the
  working requests, with the sign-in and the sign-out reported beside
  the verdict. The target is an input: the scenario states one, a run
  may state its own (`--p95-ms`, `--error-ratio`), and the verdict
  names which one it judged. `.github/workflows/stress.yml` runs a
  scenario against staging on a dispatch, from one small runner, with
  the target among its inputs: the shape of a stress run, and not a
  load test.
- **Documents.** A README at every level (`om/README.md` for a reader
  with no code, one per namespace, `infra/`, `services/api/`,
  `workers/maintenance/`, `deployment/`, `ops/`), and `llms.txt` at the
  root names what each audience is served.

## Checks

The guideline's static checker runs first. `make arch-check` runs
`arch-check` at the guideline's ref over every source tree, in the fast
gate after the types; `[tool.arch-check]` in `pyproject.toml` names the
package, the tenant-less storage methods (CTX-12), the sites that build
a stage (CTX-26), and the one exception, STO-26 on `api_keys`
([ADR 0019](adr/0019-an-api-key-hash-stays-unique-after-revocation.md)).
It holds the import direction of the object model and infra (CON-10,
CON-12) on its own. The rest of what a program can check is checked in
`om/tests/unit/`: `test_import_direction.py` scans every module under
`tadas.om` statically and fails on one outside `tadas.om.root`
importing an infra impl rather than an interface.
`test_storage_exceptions.py` lists every
storage method that does not take `org_id` first, asserts every manager
operation takes a context stage first (the outbox relay is the stated
exception), and names the transitions that take `RequestContext` or
`IdentityContext`, so a new principal-less operation must be listed.
That file reads signatures, so it says the tenant is offered to the
query and never that the query uses it. Each contract suite declares in
`CROSS_TENANT_CASES` the methods it fences with a case that presents
another tenant's identifier, and the same file holds those sets to the
interfaces, so a storage method added with no case fails the gate. What
the cases catch when a predicate is taken out of a query is recorded in
[the tenant isolation runbook](runbooks/tenant-isolation.md).
`test_stage_construction.py` scans every source tree (`om`, `infra`,
`services`, `workers`, `apps`, `clients`) for a site that constructs
`IdentityContext`, `OpContext`, or `OperatorContext` or calls
`build_context`, and fails when one appears that is not the tenancy
manager's transitions or the helper they use, so only a transition
produces a stage above the request stage. `test_role_rules.py` holds the
role ladder to the permission table and keeps the service role off it.
`test_interfaces.py` fails on a `*Interface` under `tadas.om` or
`tadas.infra` that is not an `ABC` with every public method abstract,
and on a storage interface method or a bucket listing that returns a
list and takes no `limit`; the contract suites hold both impls to the
bound, in the statement and at the same row.
`infra/tests/test_timeouts.py` scans every source root and fails on a
client construction that names no timeout. The storage contracts race
the named atomic methods, not only call them: two claimers and two
take-overs run at once through `asyncio.gather` and exactly one wins,
over memory in the fast gate and over Postgres in the integration job.
The same contracts hold every unique key the schema declares to both
impls (a duplicate raises `UniqueKeyTaken` and the row that holds the
key is unchanged; an update by copy of that row passes; a key on a
soft-deletable table is created, deleted, and created again), and show
that a named atomic create lands whole or not at all.
`services/api/tests/test_public_types.py` reads the emitted OpenAPI
document and fails on a view that carries a token, a key, or a ticket
without the `Issued` prefix.
Each process's `tests/test_settings.py` (and `infra/tests/`) reads
`.env.example` and fails on a settings field it does not document, and
reads every Terraform environment and fails on a field the cloud neither
sets nor lists, with a reason, as one it leaves at the local default.
`make migrate-check` compares
every role's ORM metadata with the migrated schema; it needs the compose
database, so CI's integration job runs it and the fast gate does not
([ADR 0003](adr/0003-migrate-check-in-the-integration-job.md)). It
compares tables, columns, and indexes, and a policy is invisible to it,
so `om/tests/unit/test_scopes.py` holds the scope map to the tables and
to the migration chain in the fast gate, and
`om/tests/integration/test_row_level_security.py` reads `pg_class` and
`pg_policies` off the migrated database and asserts every table holds
what its scope declares, that the login is neither a superuser nor
`BYPASSRLS`, and that a transaction with no scope reads nothing and is
refused its writes.

## Decisions

See [docs/adr/](adr/).

### Considered

Shapes a sibling system, scaffolded in one shot from the guideline, has
and this one does not, judged and not taken, or not yet:

- **A TypeScript client as its own workspace package** (`clients/api-client`
  beside `clients/python`). "Clients Live in One Place" read literally; the
  portal today keeps the committed `openapi.json`, the generated types, the
  facade, and the transport client under `apps/portal/src/api/`, which is one
  place while the portal is the only TypeScript caller. The move is real and
  mechanical (a package with its own `tsconfig`, the portal importing it,
  `make openapi` regenerating into it) and it pays off the day a second
  TypeScript app arrives; it is not taken before then.
- **A server-side scope on the realtime subscription** (`subscribe` with
  `scope: team | mine`, the push carrying the record's assignee and creator
  so the server filters by audience). Not taken: every push carries the
  tenant's stream position and both clients hold a contiguous cursor, so a
  push the server withholds is a gap to them, and the next push that arrives
  replays `/v1/events` after the cursor, which is unscoped and hands back what
  was withheld. A scoped subscription would either cost a replay per filtered
  push or need a scoped replay and a per-subscription frame counter to keep
  the dropped-frame guarantee, a second protocol. The "mine" rule stays where
  it is, in the client (`model.py`, the portal's scoped lists), until the
  channel carries enough traffic that filtering at the server pays for the
  protocol it needs.

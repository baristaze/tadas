# ADR 0026: What guideline 0.31.0 leaves as a choice, and what release B removes

**Status**: accepted (2026-09-22).

## Context

Tadas moves its pin from guideline v0.29.0 to v0.31.0 in one change,
release A. It adds the three database logins, the fence that admits the
system scope to the system login, operator tokens and a second factor,
the grant job, the caller's version and 412, the per-tenant work-item
key, and the bounded upload. Most of the new rules now hold in the code.

A few rules name a shape Tadas does not take, because Tadas has a
reason or lacks the feature the rule is for. Release A also keeps three
compatibility pieces so the release before keeps serving while it rolls
out. This record lists both.

## Decision

These are choices, each kept on purpose:

- **More system-scope methods than the guideline lists (`CTX-12`).**
  "The Second Fence" names the sweeps and the pre-identity lookups.
  Tadas passes no tenant in a few more, and each says why in its
  docstring. Most read or write the two `system` tables, `identities`
  and `sign_in_delays`, which have no tenant to pass:
  `read_identity`, `write_identity`, the TOTP writes
  (`write_totp_secret`, `confirm_totp`, `use_totp_step`), and the
  sign-in delay (`read_sign_in_delay`, `record_failed_sign_in`,
  `clear_failed_sign_ins`, `purge_sign_in_delays`). A second group is
  the operator plane's reads across tenants: `read_orgs`, `count_orgs`,
  `count_users`, and `read_org_by_slug`. A third is the steps between an
  identity and its tenants: `read_users_by_identity`,
  `read_memberships_by_identity`, and `read_session_by_id`. The last
  group is the two counters behind the metrics: `count_since` and
  `count_created_since`. `[tool.arch-check.options.CTX-12]` in
  `pyproject.toml` and `om/tests/unit/test_storage_exceptions.py` hold
  the same list.
- **Sessions, API keys, and socket tickets stay `both`.** The guideline's
  scaffold makes them `identity` tables. In Tadas each one belongs to
  one person inside one org: a session is in one org at a time, and a
  switch ends it (ADR 0020). So their policy stays on `org_id`, narrowed
  by the person. An operator token is a session under the system scope,
  which only `read_session_by_digest`, on the system login, finds.
- **No `read_identity_by_issuer_subject`.** It is the fifth pre-identity
  lookup, behind an external provider's find-or-create. Tadas signs in
  with an email and a password and has no external provider, so there
  is nothing for it to look up. It arrives with the first provider.
- **The session lifetimes.** The guideline's defaults are 24 hours idle
  and 7 days absolute. Tadas keeps shorter ones: 4 hours idle
  (`TADAS_SESSION_IDLE_LIFETIME_SECONDS`) and 12 hours absolute
  (`TADAS_SESSION_LIFETIME_SECONDS`). A person signs in once a working
  day. An operator token lasts an hour at most, everywhere.
- **`valkeys://` to the cache.** The guideline writes `rediss://` for
  TLS to the cache. Tadas's client is Valkey's, whose TLS scheme is
  `valkeys://`. It is the same transport under the client's own name.
- **Audit redaction has nothing to redact today (`STO-34`).** An audit
  entry is an event (ADR 0011), and every event, outbox payload, and
  work-item payload carries ids only. So the erasure sweep finds no
  personal value in an audit entry. The redaction arrives with the
  first audit entry that records a value.

Release B follows release A once every task of the release before has
stopped. It removes the three compatibility pieces:

- **The transitional `'tadas'` clause.** Every `tenant_fence` policy
  admits the system scope to `current_user IN ('tadas_system',
  'tadas')`. Release B drops `'tadas'`, and ADR 0023 closes.
- **The old work-items idempotency index.** `uq_work_items_idempotency_key`,
  on the key alone, stays beside `uq_work_items_org_id_idempotency_key`
  so a task of the release before still reads a taken key as a retry.
  Release B drops it.
- **The deprecated body and query `version`.** A task write names its
  version in `If-Match` or `expected_version` (ADR 0009). The body's
  and the query's `version` stay accepted, marked deprecated, for a
  portal tab or a CLI of the release before. Release B drops them from
  the API and regenerates both type sets.

Release B also drops `identities.failed_sign_ins` and
`identities.last_failed_sign_in_at`, which the sign-in delay's own
table replaced.

## Consequences

- A review that reads `CTX-12`, `STO-34`, or the session lifetimes
  against Tadas cites this record.
- Release B is one pull request of contractions: migrations that drop, and
  one API change. It needs no rollout order of its own, since nothing
  running still reads what it drops.
- The day Tadas adds an external provider, the fifth lookup lands with
  it and its line here goes.

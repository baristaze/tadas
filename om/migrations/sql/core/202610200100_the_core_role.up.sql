-- The core role: the tenancy swimlane, tasks, the idempotency markers, the
-- transactional outbox, files, billing, Slack, and the orchestrations.
-- Every table opens with its mixin header block. The columns of a table
-- stand in the order every migrated database holds them.
--
-- The second fence. Every tenant table carries a policy that holds the rows
-- of one tenant, and the tenant comes from a transaction setting the storage
-- funnel writes once per transaction. The predicate in the query is the
-- fence the business layer relies on; the policy is what catches the
-- predicate that went missing. FORCE holds the owner too, so the policy
-- binds the login that owns the table.
--
-- A transaction that names no tenant reads nothing and writes nothing: fail
-- closed. A setting that was never written reads as NULL, and every
-- comparison to NULL is false. A setting written with set_config(..., true)
-- in an earlier transaction on the same connection does not go back to NULL
-- when that transaction ends; it goes back to the empty string, which casts
-- to no uuid at all. NULLIF makes the two the same answer, which is the
-- answer a fence gives when nobody says whose rows these are.
--
-- The system scope is the one deliberate bypass, spelled in every policy as
-- the empty UUID, so every place it holds can be found by reading this file.
-- It belongs to the system login: any session may write a setting, so the
-- clause names the login too, and the runtime login naming the system scope
-- reads nothing.
--
-- A table that belongs to a person inside the tenant is narrowed further
-- when the transaction names one, and not narrowed when it does not. A row
-- that names its user narrows on `app.user_id`; a user's person is the
-- identity behind it, so `users` narrows on `app.identity_id`.
--
-- Every index is a plain CREATE INDEX: the runner applies a role's chain in
-- one transaction, where CONCURRENTLY is refused. A partial predicate names
-- no bound value, only IS NULL, IS NOT NULL, and a literal the read spells
-- too, so a prepared statement's generic plan proves it and reads the index.

-- The tenancy swimlane: orgs, identities, users, memberships, sessions, api
-- keys, socket tickets, sign-in delays, and invitations.

-- An org says what it is for (`kind`, personal or team), and a personal org
-- names its person. `provider_org_id` is the org's organization at the
-- identity provider, made the first time it is needed. `purged_at` is when
-- the sweep found nothing left of a deleted tenant to trim; it leaves the
-- tenant out from then on. org_id is the row's own id, so it gets no index.
CREATE TABLE core.orgs (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    deleted_at timestamptz NULL,
    deleted_by uuid NULL,
    slug text NOT NULL,
    updated_by uuid NOT NULL,
    kind text NOT NULL DEFAULT 'team',
    personal_identity_id uuid NULL,
    provider_org_id text NULL,
    purged_at timestamptz NULL,
    CONSTRAINT pk_orgs PRIMARY KEY (id),
    CONSTRAINT ck_orgs_personal_identity CHECK ((kind = 'personal') = (personal_identity_id IS NOT NULL))
);
-- A unique key on a soft-deletable table is unique among the living, so a
-- deleted org frees its slug.
CREATE UNIQUE INDEX uq_orgs_slug ON core.orgs (slug) WHERE deleted_at IS NULL;
-- One personal org per person, among the living.
CREATE UNIQUE INDEX uq_orgs_personal_identity_id ON core.orgs (personal_identity_id) WHERE kind = 'personal' AND deleted_at IS NULL;
CREATE UNIQUE INDEX uq_orgs_provider_org_id ON core.orgs (provider_org_id) WHERE provider_org_id IS NOT NULL AND deleted_at IS NULL;

ALTER TABLE core.orgs ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.orgs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.orgs FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

-- A system table: an identity is a person across tenants, it carries no
-- tenant column, and it gets no policy. `operator_role` is the allowlist
-- entry, `read` or `write` (write includes read), and null for a person who
-- is not an operator. The issuer and the subject are the identity provider's
-- name for the person. `time_zone` is the zone a due date's reminder is
-- timed in.
--
-- An address is one address in any case (ADR 0072): the digest is a
-- generated column over the address folded to lower case, by Unicode's full
-- mapping, which `lower` gives under the builtin `pg_unicode_fast` collation
-- whatever the database's locale, and which `rules.fold_email` gives in the
-- process. A generated column takes only immutable functions:
-- `decode(..., 'escape')` is the immutable spelling of the address's UTF-8
-- bytes (an address holds no backslash, which it would read as an escape).
-- A writer that does not fold meets the unique index with a second spelling
-- instead of making a second person.
CREATE TABLE core.identities (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    email text NOT NULL,
    updated_by uuid NOT NULL,
    operator_role text NULL,
    email_digest text GENERATED ALWAYS AS (encode(sha256(decode(lower(email COLLATE pg_unicode_fast), 'escape')), 'hex')) STORED,
    totp_secret text NULL,
    totp_confirmed_at timestamptz NULL,
    totp_last_step bigint NULL,
    issuer text NULL,
    subject text NULL,
    time_zone text NULL,
    CONSTRAINT pk_identities PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_identities_email_digest ON core.identities (email_digest);
CREATE UNIQUE INDEX uq_identities_issuer_subject ON core.identities (issuer, subject) WHERE subject IS NOT NULL;

CREATE TABLE core.users (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    deleted_at timestamptz NULL,
    deleted_by uuid NULL,
    identity_id uuid NOT NULL,
    email text NOT NULL,
    display_name text NOT NULL,
    updated_by uuid NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id)
);
CREATE INDEX ix_users_identity_id ON core.users (identity_id);
-- One live user per identity in a tenant, the rule add_member reads for.
-- org_id leads it, so it gets no index of its own.
CREATE UNIQUE INDEX uq_users_org_id_identity_id_live ON core.users (org_id, identity_id) WHERE deleted_at IS NULL;
-- The purge of a tenant past its retention reads `org_id = X` alone, and the
-- member list `org_id = X AND deleted_at IS NULL`. The first targets the
-- rows the partial unique index leaves out, so the table carries a plain
-- (org_id, deleted_at) index, which serves both.
CREATE INDEX ix_users_org_id_deleted_at ON core.users (org_id, deleted_at);
-- The purge across tenants reads the removed users by their delete.
CREATE INDEX ix_users_deleted_at ON core.users (deleted_at) WHERE deleted_at IS NOT NULL;

ALTER TABLE core.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.users FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.users FOR ALL
    USING (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.identity_id', true) IS NULL
            OR current_setting('app.identity_id', true) = ''
            OR identity_id = NULLIF(current_setting('app.identity_id', true), '')::uuid
        )
    )
    WITH CHECK (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.identity_id', true) IS NULL
            OR current_setting('app.identity_id', true) = ''
            OR identity_id = NULLIF(current_setting('app.identity_id', true), '')::uuid
        )
    );

-- A removed member's membership ends with them: it is soft-deleted beside
-- the user, so no read lists it and no role change reaches it during the
-- retention period.
CREATE TABLE core.memberships (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    user_id uuid NOT NULL,
    role text NOT NULL,
    teams jsonb NOT NULL,
    updated_by uuid NOT NULL,
    deleted_at timestamptz NULL,
    deleted_by uuid NULL,
    CONSTRAINT pk_memberships PRIMARY KEY (id)
);
-- Unique among the living, so an ended membership frees its (org, user).
CREATE UNIQUE INDEX uq_memberships_org_id_user_id ON core.memberships (org_id, user_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_memberships_org_id_deleted_at ON core.memberships (org_id, deleted_at);
CREATE INDEX ix_memberships_deleted_at ON core.memberships (deleted_at) WHERE deleted_at IS NOT NULL;

ALTER TABLE core.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.memberships FOR ALL
    USING (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    )
    WITH CHECK (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    );

-- A session, a sign-in, and an operator token, told apart by
-- `credential_kind`. `last_seen_at` counts the idle lifetime,
-- `second_factor_at` and `operator_role` are the operator plane's, and
-- `provider_session_id` is the identity provider's own session behind a
-- session: the sign-out ends it too.
CREATE TABLE core.sessions (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    identity_id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_hash text NOT NULL,
    credential_kind text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz NULL,
    updated_by uuid NOT NULL,
    last_seen_at timestamptz NULL,
    second_factor_at timestamptz NULL,
    operator_role text NULL,
    provider_session_id text NULL,
    CONSTRAINT pk_sessions PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_sessions_token_hash ON core.sessions (token_hash);
-- A tenant's sessions by their expiry, for the purge of a tenant; org_id
-- leads it, so it gets no index of its own. The purge across tenants reads
-- the expiry alone.
CREATE INDEX ix_sessions_org_id_expires_at ON core.sessions (org_id, expires_at);
CREATE INDEX ix_sessions_expires_at ON core.sessions (expires_at);

ALTER TABLE core.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.sessions FOR ALL
    USING (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    )
    WITH CHECK (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    );

CREATE TABLE core.api_keys (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    deleted_at timestamptz NULL,
    deleted_by uuid NULL,
    user_id uuid NOT NULL,
    key_hash text NOT NULL,
    role text NOT NULL,
    expires_at timestamptz NOT NULL,
    updated_by uuid NOT NULL,
    CONSTRAINT pk_api_keys PRIMARY KEY (id)
);
CREATE INDEX ix_api_keys_org_id ON core.api_keys (org_id);
-- Full, not among the living (ADR 0019): the hash digests a fresh random
-- secret and is never created again, and the lookup reads revoked keys too.
CREATE UNIQUE INDEX uq_api_keys_key_hash ON core.api_keys (key_hash);
CREATE INDEX ix_api_keys_deleted_at ON core.api_keys (deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX ix_api_keys_expires_at ON core.api_keys (expires_at);

ALTER TABLE core.api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.api_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.api_keys FOR ALL
    USING (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    )
    WITH CHECK (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    );

-- Socket tickets: a single-use credential standing for a session or an api
-- key. Redeeming one is a conditional update on its hash, so the row, not a
-- cache entry, decides who was first.
CREATE TABLE core.socket_tickets (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    user_id uuid NOT NULL,
    ticket_hash text NOT NULL,
    credential_kind text NOT NULL,
    credential_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    redeemed_at timestamptz NULL,
    CONSTRAINT pk_socket_tickets PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_socket_tickets_ticket_hash ON core.socket_tickets (ticket_hash);
CREATE INDEX ix_socket_tickets_org_id_expires_at ON core.socket_tickets (org_id, expires_at);
CREATE INDEX ix_socket_tickets_expires_at ON core.socket_tickets (expires_at);

ALTER TABLE core.socket_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.socket_tickets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.socket_tickets FOR ALL
    USING (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    )
    WITH CHECK (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    );

-- A person's run of failed sign-ins, and when the last one was: the sign-in
-- delay grows from them. A system table, like identities: keyed on an
-- address's digest before any identity is known, so it has no tenant, no
-- policy, and no row-level security.
CREATE TABLE core.sign_in_delays (
    id uuid NOT NULL,
    email_digest text NOT NULL,
    failures integer NOT NULL,
    last_failed_at timestamptz NOT NULL,
    CONSTRAINT pk_sign_in_delays PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_sign_in_delays_email_digest ON core.sign_in_delays (email_digest);

-- A tenant's invitations. The identity provider sends the email; the row
-- holds the role the person gets and where the invitation stands.
CREATE TABLE core.invitations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    provider_invitation_id text NOT NULL,
    state text NOT NULL,
    expires_at timestamptz NOT NULL,
    accepted_user_id uuid NULL,
    CONSTRAINT pk_invitations PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_invitations_provider_invitation_id ON core.invitations (provider_invitation_id);
-- One pending invitation per address in an org; the tenant leads it, so
-- it serves the tenant's list of pending invitations too.
CREATE UNIQUE INDEX uq_invitations_pending_email ON core.invitations (org_id, email) WHERE state = 'pending';
-- The purge of a tenant reads one tenant's invitations; the purge across
-- tenants reads the expired and the closed ones.
CREATE INDEX ix_invitations_org_id_expires_at ON core.invitations (org_id, expires_at);
CREATE INDEX ix_invitations_expires_at ON core.invitations (expires_at);
CREATE INDEX ix_invitations_updated_at ON core.invitations (updated_at);

ALTER TABLE core.invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.invitations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.invitations FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

-- The tasks swimlane. An open task's place in the list is its rank: an exact
-- decimal, so there is always one between two others and a move writes one
-- row (ADR 0050). A task carries a version: every write increments it and
-- lands only when the stored row has the version the caller read. A task is
-- due on a date, never at a time, and remembers when its reminder went out.
-- A task the cleanup archived carries when; it leaves the done list and can
-- be read and restored. Each list has its compound index, so org_id gets no
-- index of its own.
CREATE TABLE core.tasks (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    deleted_at timestamptz NULL,
    deleted_by uuid NULL,
    title text NOT NULL,
    notes text NOT NULL,
    status text NOT NULL,
    assignee_id uuid NULL,
    position double precision NOT NULL,
    updated_by uuid NOT NULL,
    version integer NOT NULL DEFAULT 1,
    reminded_at timestamptz NULL,
    due_on date NULL,
    archived_at timestamptz NULL,
    rank numeric NOT NULL,
    CONSTRAINT pk_tasks PRIMARY KEY (id)
);
-- The open list in rank order.
CREATE INDEX ix_tasks_org_id_status_rank ON core.tasks (org_id, status, rank);
-- The open tasks newest first: Slack's short list of the newest ten reads
-- the org's open tasks by id, whose time is when each was made.
CREATE INDEX ix_tasks_org_id_status_id ON core.tasks (org_id, status, id);
-- The sweep's respace finds a tenant's rank that grew past 24 digits after
-- the point (tasks.rules.RANK_SCALE_BOUND). Only such ranks are in it. The
-- bound is a literal, which the storage writes as one too.
CREATE INDEX ix_tasks_org_id_rank_long ON core.tasks (org_id, rank) WHERE scale(rank) > 24 AND deleted_at IS NULL;
-- The `mine` scope: the caller's tasks are the ones assigned to them, and the
-- unassigned ones they made. Each arm of that OR has its own index, and the
-- planner joins them in a BitmapOr, so a member with few tasks reads only
-- theirs instead of every open or done task of the tenant.
CREATE INDEX ix_tasks_org_id_assignee_id_status ON core.tasks (org_id, assignee_id, status) WHERE deleted_at IS NULL;
CREATE INDEX ix_tasks_org_id_created_by_status ON core.tasks (org_id, created_by, status) WHERE assignee_id IS NULL AND deleted_at IS NULL;
-- The done list and the archive, one index per shelf. The daily cleanup's
-- read of the archivable tasks walks only the unarchived ones, however large
-- the archive grows. The predicates leave `status` out: the storage binds it
-- as a parameter, and a generic plan cannot prove a partial predicate on one.
CREATE INDEX ix_tasks_org_id_status_updated_at_id_unarchived ON core.tasks (org_id, status, updated_at, id) WHERE archived_at IS NULL AND deleted_at IS NULL;
CREATE INDEX ix_tasks_org_id_status_updated_at_id_archived ON core.tasks (org_id, status, updated_at, id) WHERE archived_at IS NOT NULL AND deleted_at IS NULL;
-- The purge across tenants reads the deleted tasks by their delete; most
-- tasks are never deleted, so the index holds only those that are.
CREATE INDEX ix_tasks_deleted_at ON core.tasks (deleted_at) WHERE deleted_at IS NOT NULL;
-- The sweep reads, once a pass and across tenants, which tenants have a
-- chore due. One arm of that read is the done tasks not archived whose last
-- change is older than the day's cleanup cut. This index holds that shelf
-- alone, by its last change, so the cut is a range of it and only the
-- archivable tasks are read; the tenant rides along for the answer. A write
-- that leaves a task open, archived, or deleted writes it no entry.
CREATE INDEX ix_tasks_updated_at_org_id_done_unarchived ON core.tasks (updated_at, org_id) WHERE status = 'done' AND archived_at IS NULL AND deleted_at IS NULL;

ALTER TABLE core.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.tasks FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

-- The position is the rank as a float (ADR 0050). It is in the table and out
-- of the mapping, so no statement of the tree names it, and two triggers
-- keep it and the rank in step. Both triggers, their functions, and the
-- column go together, in a revision on this one.
--
-- A row written with a position and no rank takes the rank its position
-- names, digit for digit: a float's text is the shortest that reads back as
-- the same float. So does a row whose position changed alone. The trigger
-- runs before the check, so such a row meets NOT NULL with its rank set. A
-- write that sets the rank itself is left alone.
CREATE FUNCTION core.tasks_rank_from_position() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.rank IS NULL
        OR (TG_OP = 'UPDATE' AND NEW.rank = OLD.rank AND NEW.position IS DISTINCT FROM OLD.position)
    THEN
        NEW.rank := NEW.position::text::numeric;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tasks_rank_from_position BEFORE INSERT OR UPDATE ON core.tasks
FOR EACH ROW EXECUTE FUNCTION core.tasks_rank_from_position();

-- A row inserted with no position, and a row whose rank changed while its
-- position stayed, takes the float of its rank. The column is NOT NULL: this
-- trigger fills it before the check. It also keeps the trigger above, which
-- fills the rank from a position that changed alone, from ever meeting a
-- stale position. A row written with both is left alone.
CREATE FUNCTION core.tasks_position_from_rank() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.position IS NULL
        OR (TG_OP = 'UPDATE' AND NEW.rank IS DISTINCT FROM OLD.rank AND NEW.position = OLD.position)
    THEN
        NEW.position := NEW.rank::double precision;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tasks_position_from_rank BEFORE INSERT OR UPDATE ON core.tasks
FOR EACH ROW EXECUTE FUNCTION core.tasks_position_from_rank();

-- The idempotency swimlane: the durable outcome of a request the caller may
-- retry. org_id leads the unique compound index, so it gets no index of its
-- own. The id the create uses travels on the marker (`target_id`), minted
-- before it, so a retry that takes over an abandoned marker creates on the
-- same id. The marker carries the token of the attempt that holds it
-- (`attempt_id`): begin mints one, a take-over stamps a new one, and finish
-- and release are conditional on it. A released marker has no attempt and no
-- outcome, and the next retry re-arms it.
CREATE TABLE core.idempotency_records (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid NOT NULL,
    key text NOT NULL,
    request_digest text NOT NULL,
    status integer NULL,
    body text NULL,
    created_at timestamptz NOT NULL,
    target_id uuid NOT NULL,
    attempt_id uuid NULL,
    CONSTRAINT pk_idempotency_records PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_idempotency_records_org_id_user_id_key ON core.idempotency_records (org_id, user_id, key);
-- The purge across tenants reads the records by their birth.
CREATE INDEX ix_idempotency_records_created_at ON core.idempotency_records (created_at);
-- The pending markers (no status yet) by their attempt. An attempt token is
-- minted once, so the attempt alone finds the one marker: the re-mint's
-- fence reads the marker its attempt holds, and the purge reads the
-- abandoned attempts of every tenant.
CREATE INDEX ix_idempotency_records_attempt_id ON core.idempotency_records (attempt_id) WHERE status IS NULL;

ALTER TABLE core.idempotency_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.idempotency_records FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.idempotency_records FOR ALL
    USING (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    )
    WITH CHECK (
        (
            org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            OR (
                current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
                AND current_user = 'tadas_system'
            )
        )
        AND (
            current_setting('app.user_id', true) IS NULL
            OR current_setting('app.user_id', true) = ''
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
    );

-- The transactional outbox: a handoff that follows a core write lands in the
-- same commit as the core row, is relayed at once, and is swept after a
-- crash. The sweep claims pending rows: each claim spends an attempt and
-- sets the next one with a growing delay, and a row past the relay's
-- max_attempts is failed, a dead letter. `traceparent` is the trace context
-- of the request that made the write: the W3C header and not a trace id,
-- since only the header carries what a span links to.
CREATE TABLE core.outbox_rows (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    kind text NOT NULL,
    target_id uuid NOT NULL,
    payload jsonb NOT NULL,
    actor_id uuid NOT NULL,
    request_id uuid NOT NULL,
    app text NOT NULL,
    done_at timestamptz NULL,
    attempts integer NOT NULL,
    next_attempt_at timestamptz NULL,
    last_error text NULL,
    failed_at timestamptz NULL,
    traceparent text NULL,
    CONSTRAINT pk_outbox_rows PRIMARY KEY (id)
);
-- The sweep reads pending rows across tenants oldest first and purges done
-- ones by time, both over (done_at, id). No statement reads the outbox by
-- tenant, so org_id gets no index.
CREATE INDEX ix_outbox_rows_done_at_id ON core.outbox_rows (done_at, id);
-- The purge of the failed rows walks this partial index, which holds only
-- the dead letters.
CREATE INDEX ix_outbox_rows_failed_at ON core.outbox_rows (failed_at) WHERE failed_at IS NOT NULL;

ALTER TABLE core.outbox_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.outbox_rows FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

-- The media swimlane: one row per file a tenant keeps in the object store,
-- a reference and never the bytes. A subject's files are read by id, the
-- sweep reads the deleted rows and the abandoned uploads, and the usage sums
-- the live rows; each read leads with org_id, so org_id gets no index of its
-- own. The size is a bigint because a sum of sizes is.
CREATE TABLE core.files (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    deleted_at timestamptz NULL,
    deleted_by uuid NULL,
    key text NOT NULL,
    extension text NOT NULL,
    content_type text NOT NULL,
    size_bytes bigint NOT NULL,
    purpose text NOT NULL,
    subject_id uuid NULL,
    status text NOT NULL,
    CONSTRAINT pk_files PRIMARY KEY (id)
);
CREATE INDEX ix_files_org_id_purpose_subject_id_id ON core.files (org_id, purpose, subject_id, id);
CREATE INDEX ix_files_org_id_deleted_at ON core.files (org_id, deleted_at);
CREATE INDEX ix_files_org_id_status_created_at ON core.files (org_id, status, created_at);
CREATE INDEX ix_files_deleted_at ON core.files (deleted_at) WHERE deleted_at IS NOT NULL;
-- The sweep reads the live uploads never confirmed by their birth. The read
-- names the status as a literal, the one this predicate names. The index
-- holds the pending uploads alone: a confirm, which moves an upload to
-- stored, writes it no entry.
CREATE INDEX ix_files_created_at_pending ON core.files (created_at) WHERE deleted_at IS NULL AND status = 'pending';

ALTER TABLE core.files ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.files FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.files FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

-- The billing swimlane. An org's billing account mirrors its subscription at
-- the payment processor, one row per org; a delivery mark is the processor's
-- event already applied, written in the same commit as the account, so the
-- next copy of the event changes nothing.
CREATE TABLE core.billing_accounts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    customer_id text NULL,
    subscription_id text NULL,
    price_lookup_key text NULL,
    status text NULL,
    current_period_end timestamptz NULL,
    cancel_at_period_end boolean NOT NULL,
    quantity integer NOT NULL,
    comped_plan text NULL,
    synced_at timestamptz NULL,
    CONSTRAINT pk_billing_accounts PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_billing_accounts_org_id ON core.billing_accounts (org_id);

ALTER TABLE core.billing_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.billing_accounts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.billing_accounts FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

CREATE TABLE core.billing_deliveries (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    event_id text NOT NULL,
    event_type text NOT NULL,
    CONSTRAINT pk_billing_deliveries PRIMARY KEY (id)
);
CREATE INDEX ix_billing_deliveries_org_id_created_at ON core.billing_deliveries (org_id, created_at);
-- The purge across tenants reads the delivery marks by their birth.
CREATE INDEX ix_billing_deliveries_created_at ON core.billing_deliveries (created_at);

ALTER TABLE core.billing_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.billing_deliveries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.billing_deliveries FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

-- The Slack swimlane: the app an org installs, the one-time states an
-- install carries through Slack and back, and the record of every message
-- posted. All three are a tenant's rows and carry the tenant fence; the two
-- lookups that start from what Slack sends (a workspace, a state) read in
-- the system scope.
--
-- An installation is unique among the living twice: one per org, and one
-- org per workspace. Its bot token is not here: `credential_ref` names the
-- org's own secret that holds it. A state is kept as its digest, unique. A
-- post is unique per org on the key of the work that posted it, which is
-- what keeps a retried post from posting twice.
CREATE TABLE core.slack_installations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    deleted_at timestamptz NULL,
    deleted_by uuid NULL,
    team_id text NOT NULL,
    team_name text NOT NULL,
    app_id text NOT NULL,
    bot_user_id text NOT NULL,
    scopes text NOT NULL,
    installed_by_slack_user text NOT NULL,
    credential_ref text NOT NULL,
    token_expires_at timestamptz NULL,
    refreshing_until timestamptz NULL,
    channel_id text NULL,
    status text NOT NULL,
    broken_reason text NULL,
    CONSTRAINT pk_slack_installations PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_slack_installations_org_id ON core.slack_installations (org_id)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_slack_installations_team_id ON core.slack_installations (team_id)
    WHERE deleted_at IS NULL;
-- The Slack purge reads a tenant's uninstalled installations, and the tenant
-- purge all of them. Both unique indexes hold only the living ones.
CREATE INDEX ix_slack_installations_org_id_deleted_at ON core.slack_installations (org_id, deleted_at);
CREATE INDEX ix_slack_installations_deleted_at ON core.slack_installations (deleted_at) WHERE deleted_at IS NOT NULL;

ALTER TABLE core.slack_installations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.slack_installations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.slack_installations FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

CREATE TABLE core.slack_install_states (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    user_id uuid NOT NULL,
    state_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    redeemed_at timestamptz NULL,
    CONSTRAINT pk_slack_install_states PRIMARY KEY (id)
);
CREATE INDEX ix_slack_install_states_org_id ON core.slack_install_states (org_id);
CREATE UNIQUE INDEX uq_slack_install_states_state_hash
    ON core.slack_install_states (state_hash);
CREATE INDEX ix_slack_install_states_expires_at ON core.slack_install_states (expires_at);
CREATE INDEX ix_slack_install_states_redeemed_at ON core.slack_install_states (redeemed_at) WHERE redeemed_at IS NOT NULL;

ALTER TABLE core.slack_install_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.slack_install_states FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.slack_install_states FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

CREATE TABLE core.slack_posts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    key uuid NOT NULL,
    channel_id text NOT NULL,
    ts text NOT NULL,
    CONSTRAINT pk_slack_posts PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_slack_posts_org_id_key ON core.slack_posts (org_id, key);
CREATE INDEX ix_slack_posts_created_at ON core.slack_posts (created_at);

ALTER TABLE core.slack_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.slack_posts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.slack_posts FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

-- Long-running orchestrations. An orchestration is a durable record with a
-- status and a cursor, advanced one step at a time by whichever worker holds
-- its work item: the import of tasks from a CSV file, and the daily cleanup
-- of old done tasks. A record kept per period (the cleanup's day) is one per
-- org, kind, and period.
CREATE TABLE core.orchestrations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    kind text NOT NULL,
    input jsonb NOT NULL,
    period text NULL,
    status text NOT NULL,
    cursor integer NOT NULL,
    total integer NULL,
    applied integer NOT NULL,
    skipped integer NOT NULL,
    row_errors jsonb NOT NULL,
    park_reason text NULL,
    fail_reason text NULL,
    fail_detail text NULL,
    finished_at timestamptz NULL,
    version integer NOT NULL,
    CONSTRAINT pk_orchestrations PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_orchestrations_org_id_kind_period
    ON core.orchestrations (org_id, kind, period) WHERE period IS NOT NULL;
CREATE INDEX ix_orchestrations_org_id_kind_id ON core.orchestrations (org_id, kind, id);
CREATE INDEX ix_orchestrations_org_id_status_updated_at
    ON core.orchestrations (org_id, status, updated_at);
-- The purge across tenants reads the orchestrations that settled, by their
-- last change: the status picks the rows, so it leads.
CREATE INDEX ix_orchestrations_status_updated_at ON core.orchestrations (status, updated_at);

ALTER TABLE core.orchestrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.orchestrations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.orchestrations FOR ALL
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'tadas_system'
        )
    );

-- The runtime and the system logins hold DML on every table of the role and
-- nothing else: no table is theirs, so neither can drop a policy, turn FORCE
-- off, or alter a table. Every table the migration login creates from here on
-- grants the same, by default privilege. The migration bookkeeping is the
-- migration login's alone. `migrate ensure-logins` makes the logins and runs
-- the same grants, so it runs before this.
GRANT USAGE ON SCHEMA core TO tadas_runtime, tadas_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core TO tadas_runtime, tadas_system;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA core TO tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA core
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA core
    GRANT USAGE, SELECT ON SEQUENCES TO tadas_runtime, tadas_system;
REVOKE ALL ON core.alembic_version FROM tadas_runtime, tadas_system;

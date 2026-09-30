-- The activity role: each tenant's event stream, and the cursor that says
-- where the stream stands.
--
-- The second fence. Both tables belong to a tenant and to nobody in it, and
-- each carries a policy that holds the rows of one tenant. The tenant comes
-- from a transaction setting the storage funnel writes once per transaction.
-- FORCE holds the owner too, so the policy binds the login that owns the
-- table. A transaction that names no tenant reads nothing and writes
-- nothing: a setting never written reads as NULL, one written in an earlier
-- transaction on the same connection reads as the empty string, and NULLIF
-- makes the two the same answer. The system scope is the one deliberate
-- bypass, spelled in every policy as the empty UUID, and it belongs to the
-- system login alone: the runtime login naming it reads nothing.

-- The event stream: append-only, one sequence per tenant, read by seq on a
-- reconnect. An event is (kind, target_id, payload) plus its provenance: the
-- actor, the request, and the app. The kind folds the namespace, the entity,
-- and the action into one name, and an audit entry is the same shape under
-- an audit kind. The not-null constraints of `kind` and `target_id` carry
-- the names every migrated database holds.
CREATE TABLE activity.events (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    seq bigint NOT NULL,
    kind text CONSTRAINT events_entity_not_null NOT NULL,
    target_id uuid CONSTRAINT events_entity_id_not_null NOT NULL,
    produced_at timestamptz NOT NULL,
    actor_id uuid NOT NULL,
    request_id uuid NOT NULL,
    app text NOT NULL,
    payload jsonb NOT NULL,
    CONSTRAINT pk_events PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_events_org_id_seq ON activity.events (org_id, seq);
-- The trim, and the operator's count of the events of the last day, read
-- across every tenant by when an event was produced. A b-tree, not a BRIN:
-- the trim frees pages at the bottom of the heap, new events land there, and
-- the physical order stops following the time.
CREATE INDEX ix_events_produced_at ON activity.events (produced_at);

ALTER TABLE activity.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.events FOR ALL
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

-- The cursor row per tenant. The append takes the next seq as `head + 1`
-- under the row's lock inside its own transaction, and `head` is the tenant's
-- head seq the pong carries. The floor is the highest seq the trim has
-- removed from the stream, 0 while it has removed none: every event above
-- it, up to the head, is stored, and a read that starts below it is refused.
CREATE TABLE activity.event_cursors (
    org_id uuid NOT NULL,
    head bigint NOT NULL,
    floor bigint NOT NULL DEFAULT 0,
    CONSTRAINT pk_event_cursors PRIMARY KEY (org_id)
);

ALTER TABLE activity.event_cursors ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.event_cursors FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.event_cursors FOR ALL
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
GRANT USAGE ON SCHEMA activity TO tadas_runtime, tadas_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA activity TO tadas_runtime, tadas_system;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA activity TO tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA activity
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA activity
    GRANT USAGE, SELECT ON SEQUENCES TO tadas_runtime, tadas_system;
REVOKE ALL ON activity.alembic_version FROM tadas_runtime, tadas_system;

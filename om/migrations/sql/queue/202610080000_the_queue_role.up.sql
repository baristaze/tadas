-- The queue role: the work queue, hot and tiny, in a role of its own so a
-- claim never competes with an analytical scan.

-- A work item. Its routing field is its lane. Every claim mints a token the
-- claim returns, and every transition of a claimed item is conditional on
-- it, since one worker can hold one item twice across a requeue. The item
-- carries the request that caused the work and its trace context: the W3C
-- header and not a trace id, because a span links to a span. The not-null
-- constraint of `lane` carries the name every migrated database holds.
CREATE TABLE queue.work_items (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    kind text NOT NULL,
    target_id uuid NOT NULL,
    idempotency_key uuid NOT NULL,
    payload jsonb NOT NULL,
    lane text CONSTRAINT work_items_queue_not_null NOT NULL,
    status text NOT NULL,
    available_at timestamptz NOT NULL,
    claimed_by text NULL,
    lease_expires_at timestamptz NULL,
    attempts integer NOT NULL,
    max_attempts integer NOT NULL,
    last_error text NULL,
    updated_by uuid NOT NULL,
    claim_token uuid NULL,
    request_id uuid NOT NULL,
    traceparent text NULL,
    CONSTRAINT pk_work_items PRIMARY KEY (id)
);

-- The idempotency key collides within its tenant, as every index on a tenant
-- table leads with the tenant, so the read-back under that tenant always
-- finds the row that holds the key. Two tenants may hold one key. org_id
-- leads this index, so it gets none of its own.
CREATE UNIQUE INDEX uq_work_items_org_id_idempotency_key
    ON queue.work_items (org_id, idempotency_key);

-- The claim takes the ready item that became ready first: ORDER BY
-- (available_at, id). This index walks exactly that order inside a lane and a
-- status, so a claim reads the first unlocked row and stops, however long the
-- ready backlog is.
CREATE INDEX ix_work_items_lane_status_available_at_id ON queue.work_items (lane, status, available_at, id);

-- The sweep requeues expired leases across tenants in one statement, so its
-- index leads with the status and the expiry, not the tenant.
CREATE INDEX ix_work_items_status_lease_expires_at ON queue.work_items (status, lease_expires_at);

-- The purge of done and failed items reads every tenant's in one statement,
-- by status and by the last change.
CREATE INDEX ix_work_items_status_updated_at ON queue.work_items (status, updated_at);

-- The sweep reads the age of the item ready longest on any lane, once a
-- pass, for the backlog alarm. The claim's index leads with the lane, so
-- across lanes it gives no order by readiness. This partial index holds the
-- queued items alone, in the order they become ready, so the read is its
-- first entry.
CREATE INDEX ix_work_items_available_at_queued ON queue.work_items (available_at)
    WHERE status = 'queued';

-- The second fence, as one policy per login (ADR 0044). The table belongs to
-- a tenant, and the claim runs in the system scope, since a worker sweeps
-- every tenant's lane. FORCE holds the owner too.
--
-- - tenant_fence, TO tadas_runtime: the rows of the tenant the transaction
--   names, and nothing else. It carries no system-scope clause, so the
--   runtime login naming the system scope reads nothing.
-- - system_fence, TO tadas_system: every row, when the transaction names the
--   system scope, the empty UUID; nothing when it names none.
--
-- A policy applies only to the logins it names, and a login no policy names
-- reads nothing. So the migration login and the master read no work item
-- under any setting. A setting never written reads as NULL, one written in
-- an earlier transaction on the same connection reads as the empty string,
-- and NULLIF makes the two the same answer: no tenant, no row.
--
-- Postgres picks the policies by login when it plans. The system login's
-- claim sees one plain predicate on the setting, not an OR with a tenant
-- comparison the planner estimates at one tenant's share of the rows, so it
-- walks the claim's index in order and stops at the first free row.
ALTER TABLE queue.work_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE queue.work_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON queue.work_items FOR ALL TO tadas_runtime
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY system_fence ON queue.work_items FOR ALL TO tadas_system
    USING (current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000')
    WITH CHECK (current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000');

-- The runtime and the system logins hold DML on every table of the role and
-- nothing else: no table is theirs, so neither can drop a policy, turn FORCE
-- off, or alter a table. Every table the migration login creates from here on
-- grants the same, by default privilege. The migration bookkeeping is the
-- migration login's alone. `migrate ensure-logins` makes the logins and runs
-- the same grants, so it runs before this.
GRANT USAGE ON SCHEMA queue TO tadas_runtime, tadas_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA queue TO tadas_runtime, tadas_system;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA queue TO tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA queue
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA queue
    GRANT USAGE, SELECT ON SEQUENCES TO tadas_runtime, tadas_system;
REVOKE ALL ON queue.alembic_version FROM tadas_runtime, tadas_system;

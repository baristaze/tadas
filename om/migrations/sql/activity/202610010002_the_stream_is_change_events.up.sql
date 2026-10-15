-- The stream takes the name change events, and its cursors with it. A
-- rename keeps every row, the grants, and the row-level security, which
-- follow the table; the constraints, the not-null ones included, and the
-- indexes take the new names. The
-- fence is spelled again on each new name, so the chain names every table it
-- holds.

ALTER TABLE activity.events RENAME TO change_events;
ALTER TABLE activity.change_events RENAME CONSTRAINT pk_events TO pk_change_events;
ALTER INDEX activity.uq_events_org_id_seq RENAME TO uq_change_events_org_id_seq;
ALTER INDEX activity.ix_events_produced_at RENAME TO ix_change_events_produced_at;
ALTER TABLE activity.event_cursors RENAME TO change_event_cursors;
ALTER TABLE activity.change_event_cursors
    RENAME CONSTRAINT pk_event_cursors TO pk_change_event_cursors;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_id_not_null TO change_events_id_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_org_id_not_null TO change_events_org_id_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_seq_not_null TO change_events_seq_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_produced_at_not_null TO change_events_produced_at_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_actor_id_not_null TO change_events_actor_id_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_request_id_not_null TO change_events_request_id_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_app_not_null TO change_events_app_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_payload_not_null TO change_events_payload_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_entity_not_null TO change_events_kind_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT events_entity_id_not_null TO change_events_target_id_not_null;
ALTER TABLE activity.change_event_cursors RENAME CONSTRAINT event_cursors_org_id_not_null TO change_event_cursors_org_id_not_null;
ALTER TABLE activity.change_event_cursors RENAME CONSTRAINT event_cursors_head_not_null TO change_event_cursors_head_not_null;
ALTER TABLE activity.change_event_cursors RENAME CONSTRAINT event_cursors_floor_not_null TO change_event_cursors_floor_not_null;

ALTER TABLE activity.change_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
DROP POLICY tenant_fence ON activity.change_events;
CREATE POLICY tenant_fence ON activity.change_events
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

ALTER TABLE activity.change_event_cursors ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.change_event_cursors FORCE ROW LEVEL SECURITY;
DROP POLICY tenant_fence ON activity.change_event_cursors;
CREATE POLICY tenant_fence ON activity.change_event_cursors
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

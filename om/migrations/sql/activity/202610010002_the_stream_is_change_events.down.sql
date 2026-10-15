-- Gives the stream and its cursors their earlier names back, every row kept;
-- the fence and the grants follow the tables, and their constraints and
-- indexes take their earlier names.

ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_id_not_null TO events_id_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_org_id_not_null TO events_org_id_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_seq_not_null TO events_seq_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_produced_at_not_null TO events_produced_at_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_actor_id_not_null TO events_actor_id_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_request_id_not_null TO events_request_id_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_app_not_null TO events_app_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_payload_not_null TO events_payload_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_kind_not_null TO events_entity_not_null;
ALTER TABLE activity.change_events RENAME CONSTRAINT change_events_target_id_not_null TO events_entity_id_not_null;
ALTER TABLE activity.change_event_cursors RENAME CONSTRAINT change_event_cursors_org_id_not_null TO event_cursors_org_id_not_null;
ALTER TABLE activity.change_event_cursors RENAME CONSTRAINT change_event_cursors_head_not_null TO event_cursors_head_not_null;
ALTER TABLE activity.change_event_cursors RENAME CONSTRAINT change_event_cursors_floor_not_null TO event_cursors_floor_not_null;
ALTER TABLE activity.change_event_cursors
    RENAME CONSTRAINT pk_change_event_cursors TO pk_event_cursors;
ALTER TABLE activity.change_event_cursors RENAME TO event_cursors;
ALTER INDEX activity.ix_change_events_produced_at RENAME TO ix_events_produced_at;
ALTER INDEX activity.uq_change_events_org_id_seq RENAME TO uq_events_org_id_seq;
ALTER TABLE activity.change_events RENAME CONSTRAINT pk_change_events TO pk_events;
ALTER TABLE activity.change_events RENAME TO events;

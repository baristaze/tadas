-- The size tally counts change events: its column and the column's
-- not-null constraint take their name, its one row kept.

ALTER TABLE admin.system_sizes RENAME COLUMN events_last_24h TO change_events_last_24h;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT system_sizes_events_last_24h_not_null TO system_sizes_change_events_last_24h_not_null;

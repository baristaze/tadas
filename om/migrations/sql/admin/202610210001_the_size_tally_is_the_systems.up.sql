-- The size tally takes the system's name. A rename keeps the one row, its
-- key, and the serving logins' grants, which follow the table; the key and
-- the not-null constraints take the table's new name.

ALTER TABLE admin.platform_sizes RENAME TO system_sizes;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT pk_platform_sizes TO pk_system_sizes;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT platform_sizes_id_not_null TO system_sizes_id_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT platform_sizes_tenants_not_null TO system_sizes_tenants_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT platform_sizes_users_not_null TO system_sizes_users_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT platform_sizes_tasks_last_24h_not_null TO system_sizes_tasks_last_24h_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT platform_sizes_events_last_24h_not_null TO system_sizes_events_last_24h_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT platform_sizes_since_not_null TO system_sizes_since_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT platform_sizes_counted_at_not_null TO system_sizes_counted_at_not_null;

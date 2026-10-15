-- Gives the size tally and its constraints their earlier names back, its
-- row kept.

ALTER TABLE admin.system_sizes RENAME CONSTRAINT system_sizes_id_not_null TO platform_sizes_id_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT system_sizes_tenants_not_null TO platform_sizes_tenants_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT system_sizes_users_not_null TO platform_sizes_users_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT system_sizes_tasks_last_24h_not_null TO platform_sizes_tasks_last_24h_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT system_sizes_events_last_24h_not_null TO platform_sizes_events_last_24h_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT system_sizes_since_not_null TO platform_sizes_since_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT system_sizes_counted_at_not_null TO platform_sizes_counted_at_not_null;
ALTER TABLE admin.system_sizes RENAME CONSTRAINT pk_system_sizes TO pk_platform_sizes;
ALTER TABLE admin.system_sizes RENAME TO platform_sizes;

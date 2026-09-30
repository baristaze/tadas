-- Takes back what the runtime and the system logins hold on the role, then
-- drops its two tables, each with its indexes and its policy.

ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA activity
    REVOKE USAGE, SELECT ON SEQUENCES FROM tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA activity
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA activity FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL TABLES IN SCHEMA activity FROM tadas_runtime, tadas_system;
REVOKE USAGE ON SCHEMA activity FROM tadas_runtime, tadas_system;

DROP TABLE activity.event_cursors;
DROP TABLE activity.events;

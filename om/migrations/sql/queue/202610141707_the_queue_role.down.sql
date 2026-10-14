-- Takes the queue role back to empty: the grants, then the tenants' caps
-- and the work items, each with its policies.

ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA queue
    REVOKE USAGE, SELECT ON SEQUENCES FROM tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA queue
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA queue FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL TABLES IN SCHEMA queue FROM tadas_runtime, tadas_system;
REVOKE USAGE ON SCHEMA queue FROM tadas_runtime, tadas_system;

DROP TABLE queue.tenant_caps;
DROP TABLE queue.work_items;

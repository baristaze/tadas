-- Takes the admin role back to empty: the grants, then the size tally.

ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA admin
    REVOKE USAGE, SELECT ON SEQUENCES FROM tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA admin
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA admin FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL TABLES IN SCHEMA admin FROM tadas_runtime, tadas_system;
REVOKE USAGE ON SCHEMA admin FROM tadas_runtime, tadas_system;

DROP TABLE admin.platform_sizes;

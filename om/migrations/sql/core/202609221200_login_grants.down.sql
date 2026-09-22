-- Takes back what the runtime and the system logins held on the role.

ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA core
    REVOKE USAGE, SELECT ON SEQUENCES FROM tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA core
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA core FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL TABLES IN SCHEMA core FROM tadas_runtime, tadas_system;
REVOKE USAGE ON SCHEMA core FROM tadas_runtime, tadas_system;

-- Takes back what the runtime and the system logins held on the role.

ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA queue
    REVOKE USAGE, SELECT ON SEQUENCES FROM tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA queue
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA queue FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL TABLES IN SCHEMA queue FROM tadas_runtime, tadas_system;
REVOKE USAGE ON SCHEMA queue FROM tadas_runtime, tadas_system;

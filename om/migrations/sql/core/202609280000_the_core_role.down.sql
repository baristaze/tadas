-- Takes the core role back to empty: the grants, then every table with its
-- policy and its indexes.

ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA core
    REVOKE USAGE, SELECT ON SEQUENCES FROM tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA core
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA core FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL TABLES IN SCHEMA core FROM tadas_runtime, tadas_system;
REVOKE USAGE ON SCHEMA core FROM tadas_runtime, tadas_system;

DROP TABLE core.orchestrations;
DROP TABLE core.files;
DROP TABLE core.idempotency_records;
DROP TABLE core.outbox_rows;
DROP TABLE core.sign_in_delays;
DROP TABLE core.socket_tickets;
DROP TABLE core.api_keys;
DROP TABLE core.sessions;
DROP TABLE core.invitations;
DROP TABLE core.memberships;
DROP TABLE core.users;
DROP TABLE core.identities;
DROP TABLE core.orgs;

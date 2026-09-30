-- Takes back what the runtime and the system logins hold on the role, then
-- drops every table of it, each with its indexes, its policy, and its
-- triggers, and the two functions the triggers of the tasks ran.

ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA core
    REVOKE USAGE, SELECT ON SEQUENCES FROM tadas_runtime, tadas_system;
ALTER DEFAULT PRIVILEGES FOR ROLE tadas_migration IN SCHEMA core
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA core FROM tadas_runtime, tadas_system;
REVOKE ALL ON ALL TABLES IN SCHEMA core FROM tadas_runtime, tadas_system;
REVOKE USAGE ON SCHEMA core FROM tadas_runtime, tadas_system;

DROP TABLE core.orchestrations;
DROP TABLE core.slack_posts;
DROP TABLE core.slack_install_states;
DROP TABLE core.slack_installations;
DROP TABLE core.billing_deliveries;
DROP TABLE core.billing_accounts;
DROP TABLE core.files;
DROP TABLE core.outbox_rows;
DROP TABLE core.idempotency_records;
DROP TABLE core.tasks;
DROP FUNCTION core.tasks_position_from_rank();
DROP FUNCTION core.tasks_rank_from_position();
DROP TABLE core.invitations;
DROP TABLE core.sign_in_delays;
DROP TABLE core.socket_tickets;
DROP TABLE core.api_keys;
DROP TABLE core.sessions;
DROP TABLE core.memberships;
DROP TABLE core.users;
DROP TABLE core.identities;
DROP TABLE core.orgs;

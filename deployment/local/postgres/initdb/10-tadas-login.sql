-- The application's login, and the reason it is not the superuser.
--
-- A superuser walks past every row-level security policy, and so does a role
-- with BYPASSRLS, so a fence behind one is a drawing. The container's
-- superuser is `postgres`; `tadas` is what every process, every migration and
-- every test connects as, and it has neither attribute. It owns the database,
-- which it needs to create the schemas and tables, and FORCE ROW LEVEL
-- SECURITY on each table holds the owner too.
--
-- This runs once, on an empty data directory. A stack that was up before this
-- file existed keeps the old login until `make reset`.

CREATE ROLE tadas LOGIN PASSWORD 'tadas' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

ALTER DATABASE tadas OWNER TO tadas;
ALTER SCHEMA public OWNER TO tadas;

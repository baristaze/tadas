-- The position comes back as the release before this one declares it: each
-- task's rank as a float, not null, kept by the two triggers.
--
-- The column is filled first, under the fence lifted for the one statement,
-- since a migration names no tenant. Then it is set NOT NULL, which fails the
-- whole step if the fill missed a row. The triggers come after the fill: the
-- one that gives a row the rank its position names would read a position that
-- changed alone and rewrite a long rank as the float's digits.
ALTER TABLE core.tasks ADD COLUMN position double precision NULL;
ALTER TABLE core.tasks NO FORCE ROW LEVEL SECURITY;
UPDATE core.tasks SET position = rank::double precision;
ALTER TABLE core.tasks FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tasks ALTER COLUMN position SET NOT NULL;

CREATE FUNCTION core.tasks_rank_from_position() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.rank IS NULL
        OR (TG_OP = 'UPDATE' AND NEW.rank = OLD.rank AND NEW.position IS DISTINCT FROM OLD.position)
    THEN
        NEW.rank := NEW.position::text::numeric;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tasks_rank_from_position BEFORE INSERT OR UPDATE ON core.tasks
FOR EACH ROW EXECUTE FUNCTION core.tasks_rank_from_position();

CREATE FUNCTION core.tasks_position_from_rank() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.position IS NULL
        OR (TG_OP = 'UPDATE' AND NEW.rank IS DISTINCT FROM OLD.rank AND NEW.position = OLD.position)
    THEN
        NEW.position := NEW.rank::double precision;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tasks_position_from_rank BEFORE INSERT OR UPDATE ON core.tasks
FOR EACH ROW EXECUTE FUNCTION core.tasks_position_from_rank();

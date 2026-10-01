-- The contract half of ADR 0038. A task's place is its rank alone
-- (ADR 0050). The release before this one names the position in no
-- statement: its mapping leaves the column out, and its view reads the rank.
-- So the position goes, with the two triggers that kept it and the rank in
-- step, and their functions. Each position is its rank's float, so nothing
-- is lost: the down file fills the column from the rank again.

DROP TRIGGER tasks_position_from_rank ON core.tasks;
DROP TRIGGER tasks_rank_from_position ON core.tasks;
DROP FUNCTION core.tasks_position_from_rank();
DROP FUNCTION core.tasks_rank_from_position();
ALTER TABLE core.tasks DROP COLUMN position;

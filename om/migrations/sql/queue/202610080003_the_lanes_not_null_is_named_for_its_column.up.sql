-- The not-null constraint on a work item's lane takes the name Postgres
-- gives it on a table made in one step, `<table>_<column>_not_null`, so the
-- chain and a schema built whole name it alike.

ALTER TABLE queue.work_items RENAME CONSTRAINT work_items_queue_not_null TO work_items_lane_not_null;

-- Gives the not-null constraint on a work item's lane its earlier name.

ALTER TABLE queue.work_items RENAME CONSTRAINT work_items_lane_not_null TO work_items_queue_not_null;

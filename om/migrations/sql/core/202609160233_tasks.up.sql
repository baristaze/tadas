-- The tasks swimlane. A feed: the compound (org_id, id) index sorts by
-- creation time, and org_id gets no index of its own.

CREATE TABLE core.tasks (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    deleted_at timestamptz NULL,
    deleted_by uuid NULL,
    title text NOT NULL,
    notes text NOT NULL,
    status text NOT NULL,
    CONSTRAINT pk_tasks PRIMARY KEY (id)
);
CREATE INDEX ix_tasks_org_id_id ON core.tasks (org_id, id);

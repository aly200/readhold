-- Plan, part two: a task can be marked as the one that matters and can hold a short checklist of its own.
-- A routine can belong to some days of the week only (for example weekdays).

ALTER TABLE todos ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;   -- 1 = "this one matters"

CREATE TABLE todo_items (
    id TEXT PRIMARY KEY,
    todo_id TEXT NOT NULL,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    ord REAL NOT NULL DEFAULT 0,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_todo_items ON todo_items(todo_id, ord);

-- '' = every day; otherwise the weekdays it is for, as digits (0 = Monday ... 6 = Sunday), e.g. '01234'
ALTER TABLE routines ADD COLUMN weekdays TEXT NOT NULL DEFAULT '';

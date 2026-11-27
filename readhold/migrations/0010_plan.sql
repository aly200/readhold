-- Plan: tasks get a day, a repeat rule, a life area and a note. Routines are short ordered checklists
-- for a part of the day (morning, day, evening) that start fresh every day.

ALTER TABLE todos ADD COLUMN due TEXT;
ALTER TABLE todos ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT '';
ALTER TABLE todos ADD COLUMN area TEXT NOT NULL DEFAULT '';
ALTER TABLE todos ADD COLUMN note TEXT NOT NULL DEFAULT '';
ALTER TABLE todos ADD COLUMN next_id TEXT;
CREATE INDEX idx_todos_due ON todos(due);

CREATE TABLE routines (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT 'morning',      -- morning | day | evening
    ord REAL NOT NULL DEFAULT 0,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE routine_steps (
    id TEXT PRIMARY KEY,
    routine_id TEXT NOT NULL,
    text TEXT NOT NULL,
    minutes INTEGER NOT NULL DEFAULT 0,        -- 0 = no timer for this step
    ord REAL NOT NULL DEFAULT 0,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_routine_steps ON routine_steps(routine_id, ord);

CREATE TABLE routine_checks (
    id TEXT PRIMARY KEY,
    routine_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    day TEXT NOT NULL,                         -- the local day the step was done
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_routine_checks ON routine_checks(routine_id, day);

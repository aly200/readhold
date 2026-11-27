-- A calm timer and a to-do list whose tasks you can time.
-- A focus run is also recorded as a session, so it counts in Stamina and the journal's day story.

CREATE TABLE todos (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    minutes INTEGER NOT NULL DEFAULT 25,       -- your estimate
    spent_ms INTEGER NOT NULL DEFAULT 0,       -- time actually spent on it with the timer
    ord REAL NOT NULL DEFAULT 0,
    link_type TEXT NOT NULL DEFAULT '',        -- '' | step | document | lecture
    link_id TEXT NOT NULL DEFAULT '',
    done_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_todos_open ON todos(done_at, ord);

CREATE TABLE timer_runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                        -- focus | break | stopwatch
    label TEXT NOT NULL DEFAULT '',
    planned_ms INTEGER NOT NULL DEFAULT 0,     -- 0 for the stopwatch
    elapsed_ms INTEGER NOT NULL DEFAULT 0,     -- time counted up to running_since (or in total once paused/ended)
    running_since TEXT,                        -- when it was last started or resumed (NULL while paused)
    status TEXT NOT NULL DEFAULT 'active',     -- active | done | stopped
    todo_id TEXT,
    session_id TEXT,                           -- the session row for a focus run
    link_type TEXT NOT NULL DEFAULT '',
    link_id TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_timer_runs_status ON timer_runs(status, started_at);

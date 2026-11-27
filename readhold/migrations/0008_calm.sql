-- Calm tools for overthinking and anxiety.
-- Guess vs. reality: before a session you guess how hard it will feel (0 to 10), afterwards you rate how it was.
-- Unstick: a log of each tiny start (Shrink it) and each breathing reset (Steady me), so the app can show
-- your own numbers back to you.

ALTER TABLE sessions ADD COLUMN guess_hard INTEGER;
ALTER TABLE sessions ADD COLUMN real_hard INTEGER;

CREATE TABLE unstick_events (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                        -- shrink | steady
    step TEXT NOT NULL DEFAULT '',             -- shrink: the tiny step you named
    run_id TEXT,                               -- shrink: the timer run it rides on
    own_run INTEGER NOT NULL DEFAULT 0,        -- shrink: 1 when it started that run itself
    base_ms INTEGER NOT NULL DEFAULT 0,        -- shrink: the run's elapsed time when the tiny start began
    stage INTEGER NOT NULL DEFAULT 0,          -- shrink: rung reached (0 = the first 2 minutes)
    went_ms INTEGER NOT NULL DEFAULT 0,        -- shrink: how long you actually went
    pattern TEXT NOT NULL DEFAULT '',          -- steady: slow | sigh | box
    tense_before INTEGER,                      -- steady: 1 (calm) to 5 (flooded), optional
    tense_after INTEGER,
    status TEXT NOT NULL DEFAULT 'active',     -- active | stopped | kept | left | done
    ended_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_unstick_kind ON unstick_events(kind, created_at);

-- Think (step 1 of the agent, no AI model): suggestions you approve, and a few ideas to think about each day.

-- A suggestion is one small change the app proposes (link two notes, turn a mention into a link, file an idea
-- under a note, add a tag). Nothing changes until you accept it. `key` names what it is about, so a suggestion
-- you turned down is never offered again.
CREATE TABLE suggestions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                       -- link | mention | file_idea | tag
    key TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',       -- JSON: the ids it is about
    reason TEXT NOT NULL DEFAULT '',          -- why it is proposed, in words you can check
    score REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'new',       -- new | accepted | rejected | stale
    undo TEXT NOT NULL DEFAULT '',            -- JSON: what accepting changed, so it can be taken back
    decided_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_suggestions_key ON suggestions(key);
CREATE INDEX idx_suggestions_status ON suggestions(status, created_at);

-- The few notes or ideas picked for a day, each with the reason it was picked.
CREATE TABLE daily_picks (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,                        -- local date YYYY-MM-DD
    item_kind TEXT NOT NULL,                  -- page | idea
    item_id TEXT NOT NULL,
    signal TEXT NOT NULL,                     -- quest | question | orphan | resting
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',       -- new | opened | dismissed
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_daily_picks_day ON daily_picks(day);

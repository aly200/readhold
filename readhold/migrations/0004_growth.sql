-- Growth: topic maps (what a quest needs you to understand, and in which order),
-- a daily 3-line log, and tiny habits with "never miss twice".

CREATE TABLE map_nodes (
    id TEXT PRIMARY KEY,
    quest_id TEXT NOT NULL REFERENCES quests(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',       -- new | shaky | solid (can I explain it?)
    note TEXT NOT NULL DEFAULT '',
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_map_nodes ON map_nodes(quest_id);

CREATE TABLE map_edges (
    id TEXT PRIMARY KEY,
    quest_id TEXT NOT NULL REFERENCES quests(id),
    from_id TEXT NOT NULL REFERENCES map_nodes(id),  -- the prerequisite
    to_id TEXT NOT NULL REFERENCES map_nodes(id),    -- the concept that needs it
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_map_edges ON map_edges(quest_id);

CREATE TABLE day_logs (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,                         -- local date, YYYY-MM-DD
    quest_id TEXT,
    did TEXT NOT NULL DEFAULT '',
    learned TEXT NOT NULL DEFAULT '',
    next TEXT NOT NULL DEFAULT '',             -- tomorrow's first step
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_day_logs ON day_logs(day);

CREATE TABLE habits (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,                       -- "Review 5 cards"
    anchor TEXT NOT NULL DEFAULT '',           -- "After my morning coffee"
    tiny TEXT NOT NULL DEFAULT '',             -- the 2-minute version for low days
    archived INTEGER NOT NULL DEFAULT 0,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE habit_checks (
    id TEXT PRIMARY KEY,
    habit_id TEXT NOT NULL REFERENCES habits(id),
    day TEXT NOT NULL,                         -- local date, YYYY-MM-DD
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_habit_checks ON habit_checks(habit_id, day);

-- A note from steady you: on a good day you write a few lines to your stuck self.
-- Unstick shows one of them first, in your own words. The one shown longest ago comes next.

CREATE TABLE steady_notes (
    id TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    shown_at TEXT,                             -- when Unstick last showed it (NULL = never)
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_steady_notes_shown ON steady_notes(deleted, shown_at);

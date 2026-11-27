-- Reflect: how sessions felt (energy drain log), paper critique and a result to reproduce,
-- mixed practice attempts, and the sync columns every record needs (settings lacked them).

ALTER TABLE sessions ADD COLUMN feel TEXT NOT NULL DEFAULT '';          -- energized | neutral | drained

ALTER TABLE documents ADD COLUMN critique TEXT NOT NULL DEFAULT '';     -- strengths, weaknesses, what I'd test
ALTER TABLE documents ADD COLUMN reproduce TEXT NOT NULL DEFAULT '';    -- one result I'd reproduce

CREATE TABLE practice_attempts (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,               -- quest_question | question | term
    source_id TEXT NOT NULL,
    result TEXT NOT NULL,                    -- got | partly | missed
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_practice_created ON practice_attempts(created_at);

ALTER TABLE settings ADD COLUMN id TEXT;
ALTER TABLE settings ADD COLUMN device_id TEXT NOT NULL DEFAULT '';
ALTER TABLE settings ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0;
UPDATE settings SET id = lower(hex(randomblob(16))) WHERE id IS NULL;

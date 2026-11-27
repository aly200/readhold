-- Compass: one main quest at a time, the questions it must answer, and the steps that answer them.
-- Energy check-ins and side quests make "the right thing, at the right energy" visible.

CREATE TABLE quests (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    why TEXT NOT NULL DEFAULT '',
    done_looks_like TEXT NOT NULL DEFAULT '',   -- the definition of done, written before starting
    deadline TEXT,
    status TEXT NOT NULL DEFAULT 'active',      -- active | done | parked
    finished_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_quests_status ON quests(status, updated_at);

CREATE TABLE quest_questions (
    id TEXT PRIMARY KEY,
    quest_id TEXT NOT NULL REFERENCES quests(id),
    ord INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    answered_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_quest_questions ON quest_questions(quest_id, ord);

CREATE TABLE quest_steps (
    id TEXT PRIMARY KEY,
    quest_id TEXT NOT NULL REFERENCES quests(id),
    question_id TEXT,                          -- the quest question this step moves (optional)
    document_id TEXT,                          -- a reading step opens this document
    ord INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,                       -- the medium-energy version
    low TEXT NOT NULL DEFAULT '',              -- tiny version for low days
    high TEXT NOT NULL DEFAULT '',             -- full version for high days
    minutes INTEGER NOT NULL DEFAULT 20,
    lead INTEGER NOT NULL DEFAULT 0,           -- the step that makes the others easier
    done_at TEXT,
    output TEXT NOT NULL DEFAULT '',           -- what finishing it produced
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_quest_steps ON quest_steps(quest_id, ord);

CREATE TABLE side_quests (
    id TEXT PRIMARY KEY,
    quest_id TEXT,                             -- the main quest active when it pulled at you
    text TEXT NOT NULL,
    decision TEXT NOT NULL,                    -- parked | timeboxed | linked
    minutes INTEGER NOT NULL DEFAULT 0,
    question_id TEXT,                          -- when it turned out to answer a quest question
    document_id TEXT,
    resolved INTEGER NOT NULL DEFAULT 0,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE checkins (
    id TEXT PRIMARY KEY,
    energy TEXT NOT NULL,                      -- low | medium | high
    note TEXT NOT NULL DEFAULT '',
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_checkins_created ON checkins(created_at);

-- Sessions can now belong to the main quest (reading or a focus step), and record what they produced.
ALTER TABLE sessions ADD COLUMN quest_id TEXT;
ALTER TABLE sessions ADD COLUMN step_id TEXT;
ALTER TABLE sessions ADD COLUMN output TEXT NOT NULL DEFAULT '';

-- A document can be read to answer one of the main quest's questions.
ALTER TABLE documents ADD COLUMN quest_question_id TEXT;

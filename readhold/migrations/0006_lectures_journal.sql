-- Lectures (PDF slides, PowerPoint, HTML pages) shown as pages, not reflowed text;
-- a notebook of notes in several forms; digital-pen ink; a journal and letters to your future self.

CREATE TABLE lectures (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,                       -- pdf | pptx | html
    source TEXT NOT NULL DEFAULT '',          -- original file name
    file_hash TEXT NOT NULL,                  -- library/<hash>.<ext> holds the original
    pages INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL DEFAULT 0,      -- page you were on
    page_tint TEXT NOT NULL DEFAULT 'normal', -- normal | dim | sepia | night
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE lecture_pages (
    id TEXT PRIMARY KEY,
    lecture_id TEXT NOT NULL REFERENCES lectures(id),
    ord INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',            -- plain text, for search
    speaker_notes TEXT NOT NULL DEFAULT '',   -- PowerPoint notes
    width REAL NOT NULL DEFAULT 0,
    height REAL NOT NULL DEFAULT 0,
    layout TEXT NOT NULL DEFAULT '',          -- PowerPoint: JSON of positioned text, images, tables (never HTML)
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_lecture_pages ON lecture_pages(lecture_id, ord);

CREATE TABLE lecture_notes (
    id TEXT PRIMARY KEY,
    lecture_id TEXT NOT NULL REFERENCES lectures(id),
    page INTEGER,                             -- page ord, or NULL for the whole lecture
    kind TEXT NOT NULL,                       -- text | cornell | snip | question | sketch | recall
    body TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}',          -- JSON: cornell fields, snip rectangle, question back
    color TEXT NOT NULL DEFAULT '',
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_lecture_notes ON lecture_notes(lecture_id, page);

CREATE TABLE ink (
    id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,                 -- lecture_page | note | journal
    owner_id TEXT NOT NULL,
    strokes TEXT NOT NULL DEFAULT '[]',       -- JSON vector strokes, coordinates 0..1
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_ink_owner ON ink(owner_type, owner_id);

CREATE TABLE journal_entries (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,                        -- local date YYYY-MM-DD, one page per day
    weather TEXT NOT NULL DEFAULT '',         -- your inner weather: sunny | bright | cloudy | rainy | stormy
    body TEXT NOT NULL DEFAULT '',
    prompts TEXT NOT NULL DEFAULT '[]',       -- JSON [{q, a}]
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_journal_day ON journal_entries(day);

CREATE TABLE letters (
    id TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    open_on TEXT NOT NULL,                    -- YYYY-MM-DD: sealed until then
    opened_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

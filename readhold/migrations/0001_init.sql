-- Readhold schema v1. Every record: UUID id, device_id, created_at, updated_at, deleted flag (sync-ready).

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT,                       -- URL or original file name
    source_type TEXT NOT NULL,         -- markdown | text | pdf | web | arxiv | plain
    file_hash TEXT,                    -- library/<hash>.<ext> holds the original
    why TEXT NOT NULL DEFAULT '',      -- "why am I reading this?"
    deadline TEXT,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | reading | finished
    import_warning TEXT,
    position INTEGER NOT NULL DEFAULT 0,      -- sentence ord of the resume point
    current_pass INTEGER NOT NULL DEFAULT 1,
    explain_text TEXT NOT NULL DEFAULT '',
    total_sentences INTEGER NOT NULL DEFAULT 0,
    finished_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sections (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    ord INTEGER NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other',   -- abstract | intro | related | method | results | discussion | conclusion | references | appendix | other
    level INTEGER NOT NULL DEFAULT 1,
    background INTEGER NOT NULL DEFAULT 0,  -- safe to skip
    hidden INTEGER NOT NULL DEFAULT 0,      -- hidden by clean view
    prediction TEXT NOT NULL DEFAULT '',
    prediction_check TEXT NOT NULL DEFAULT '',
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_sections_doc ON sections(document_id, ord);

CREATE TABLE paragraphs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    section_id TEXT NOT NULL REFERENCES sections(id),
    ord INTEGER NOT NULL,                  -- document-global order
    kind TEXT NOT NULL DEFAULT 'text',     -- text | code | caption | equation | reference | list
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_paragraphs_doc ON paragraphs(document_id, ord);

CREATE TABLE sentences (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    paragraph_id TEXT NOT NULL REFERENCES paragraphs(id),
    ord INTEGER NOT NULL,                  -- document-global order, stable for the life of the document
    text TEXT NOT NULL,
    words INTEGER NOT NULL,
    density REAL NOT NULL,                 -- 0..1 from rules
    personal REAL NOT NULL DEFAULT 0,      -- learned: how much you slow down here (-0.3..0.6)
    read_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_sentences_doc ON sentences(document_id, ord);

CREATE TABLE questions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    section_id TEXT,
    source_sentence INTEGER,               -- ord of the claim it came from
    text TEXT NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    answer TEXT NOT NULL DEFAULT '',       -- "in my words" recall answer
    answered_at TEXT,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_questions_doc ON questions(document_id);

CREATE TABLE question_links (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(id),
    paragraph_id TEXT NOT NULL REFERENCES paragraphs(id),
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_qlinks_q ON question_links(question_id);

-- Questions you write teach the templates for the next paper of the same kind.
CREATE TABLE template_bank (
    id TEXT PRIMARY KEY,
    section_kind TEXT NOT NULL,
    text TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 1,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    UNIQUE(section_kind, text)
);

CREATE TABLE highlights (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    sentence INTEGER NOT NULL,             -- sentence ord
    end_sentence INTEGER NOT NULL,
    type TEXT NOT NULL,                    -- claim | evidence | definition | confusing | idea
    text TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    cloze TEXT NOT NULL DEFAULT '',        -- hidden word for fill-in-the-blank cards
    resolved INTEGER NOT NULL DEFAULT 0,   -- for confusing
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_highlights_doc ON highlights(document_id);

CREATE TABLE notes (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    sentence INTEGER NOT NULL,
    text TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_notes_doc ON notes(document_id);

CREATE TABLE terms (
    id TEXT PRIMARY KEY,
    term TEXT NOT NULL,
    guess TEXT NOT NULL DEFAULT '',
    definition TEXT NOT NULL DEFAULT '',
    document_id TEXT,
    sentence INTEGER,
    source_text TEXT NOT NULL DEFAULT '',
    is_concept INTEGER NOT NULL DEFAULT 0,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_terms_term ON terms(term);

CREATE TABLE cards (
    id TEXT PRIMARY KEY,
    document_id TEXT,
    source_type TEXT NOT NULL,             -- term | definition | question | cloze
    source_id TEXT NOT NULL,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    fsrs TEXT NOT NULL,                    -- FSRS card state as JSON
    due TEXT NOT NULL,
    suspended INTEGER NOT NULL DEFAULT 0,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_cards_due ON cards(due);
CREATE UNIQUE INDEX idx_cards_source ON cards(source_type, source_id);

CREATE TABLE reviews (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES cards(id),
    rating INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    document_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    energy TEXT NOT NULL DEFAULT 'medium',
    time_box_min INTEGER NOT NULL DEFAULT 15,
    question TEXT NOT NULL DEFAULT '',
    focused_ms INTEGER NOT NULL DEFAULT 0,
    longest_run_ms INTEGER NOT NULL DEFAULT 0,
    distractions INTEGER NOT NULL DEFAULT 0,
    sentences_read INTEGER NOT NULL DEFAULT 0,
    next_step TEXT NOT NULL DEFAULT '',
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_sessions_started ON sessions(started_at);

CREATE TABLE ideas (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    document_id TEXT,
    sentence INTEGER,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

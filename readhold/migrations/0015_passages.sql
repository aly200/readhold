-- A full-text index over the sections of your documents (SQLite FTS5, ranked with BM25).
-- One row per section: its title and its text. It is derived data: readhold/passages.py rebuilds a document's
-- rows whenever its structure changes, and fills in documents that were imported before this index existed.
CREATE VIRTUAL TABLE section_fts USING fts5(
    title,
    body,
    document_id UNINDEXED,
    section_id UNINDEXED,
    first_ord UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- Where a reading session started and where it stopped (sentence ords), so "where you left off" is a fact, not a guess.
ALTER TABLE sessions ADD COLUMN start_ord INTEGER;
ALTER TABLE sessions ADD COLUMN last_ord INTEGER;

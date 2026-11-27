-- Document tags (AI plan, milestone 3.3, its non-AI layer): words you give a document, space separated, lower case,
-- written like note #tags. A tag is also a collection: the Documents tab can show the documents that carry it.
-- Set only by you (a model may suggest one; you add it, with Undo).
ALTER TABLE documents ADD COLUMN tags TEXT NOT NULL DEFAULT '';

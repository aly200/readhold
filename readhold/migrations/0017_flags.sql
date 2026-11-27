-- What is odd about a document, for the warning badge (docs/ai/PLAN.md, section 6.2).
-- import_flags: set by the importer. "hidden_text" = the PDF held text a reader cannot see (too small, off the page, or white).
-- flags: import_flags plus what readhold/ai/guard.py finds ("instructions" = text that reads like orders to a model).
--        NULL means the document has not been looked at yet; it is looked at when the app starts.
ALTER TABLE documents ADD COLUMN import_flags TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN flags TEXT;

-- Who wrote a margin note (docs/ai/PLAN.md, section 6.6: provenance labels).
-- '' = you. 'ai' = it was saved from something an AI model wrote; the label stays until you edit the note.
ALTER TABLE notes ADD COLUMN origin TEXT NOT NULL DEFAULT '';

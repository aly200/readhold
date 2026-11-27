-- What an AI feature produced and showed you (docs/ai/PLAN.md, section 5: "Suggestion").
-- One row per result: the feature, what it is about, and the result as JSON. A result is kept so the same
-- question is not sent to a model twice, and so "why did it say this?" can find its log row.
-- input_key is a hash of everything the result depends on; when that changes, the old result no longer applies.
-- status: shown (you saw it) | accepted | edited | dismissed. Nothing here is written into your notes by itself.
CREATE TABLE ai_results (
    id TEXT PRIMARY KEY,
    feature TEXT NOT NULL,                     -- resume, explain, digest, ...
    target_type TEXT NOT NULL DEFAULT '',      -- document, ...
    target_id TEXT NOT NULL DEFAULT '',
    input_key TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',        -- JSON, already cleaned and checked
    status TEXT NOT NULL DEFAULT 'shown',
    prompt_version TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    log_id TEXT NOT NULL DEFAULT '',           -- the ai_log row of the call (gone after 30 days)
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_ai_results_target ON ai_results(feature, target_id, input_key);

-- The AI log: one row for every call to a model (docs/ai/PLAN.md, section 6.4 and 6.8).
-- It holds a hash and a short preview of what was sent and what came back, never the whole text and never a key.
-- readhold/ai/log.py deletes rows older than 30 days; "Clear AI history" empties it.
-- It is a log of this device, so it is not in the full export.
CREATE TABLE ai_log (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,                        -- the feature or task: explain, digest, test, ...
    provider TEXT NOT NULL DEFAULT '',         -- local | anthropic | openai
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',   -- empty until the prompt registry exists
    input_hash TEXT NOT NULL DEFAULT '',       -- SHA-256 of the text that was sent
    input_preview TEXT NOT NULL DEFAULT '',    -- its first characters, with secrets removed
    output_preview TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,       -- 1, or 2 after the one retry
    checks TEXT NOT NULL DEFAULT '{}',         -- JSON: schema passed, output cut, tokens estimated
    outcome TEXT NOT NULL DEFAULT '',          -- ok | invalid | timeout | cancelled | error | budget | no_key | setup
    error TEXT NOT NULL DEFAULT '',            -- a short reason, with secrets removed
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_ai_log_created ON ai_log(created_at);
CREATE INDEX idx_ai_log_provider ON ai_log(provider, created_at);

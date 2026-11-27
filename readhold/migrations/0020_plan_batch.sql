-- Reading plan (docs/ai/PLAN.md, milestone 3.1): the tasks one reading plan added to Plan share a batch id,
-- so the whole plan can be taken back in one step. '' = a task you added yourself.
ALTER TABLE todos ADD COLUMN plan_batch TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_todos_plan_batch ON todos(plan_batch) WHERE plan_batch != '';

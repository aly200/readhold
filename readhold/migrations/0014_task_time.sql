-- A task can have a time of day ("14:30", '' = no time). While Readhold is open it reminds you at that time.
-- Repeat rules also gain "every:N" (every N days); that needs no new column.
ALTER TABLE todos ADD COLUMN at TEXT NOT NULL DEFAULT '';

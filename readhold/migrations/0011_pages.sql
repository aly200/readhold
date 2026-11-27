-- Notes: your own pages, linked to each other with [[double brackets]].
-- A link stores the lower-cased title it points to, so a page can be linked before it exists.

CREATE TABLE pages (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL,                   -- the title, lower-cased and trimmed: how links find a page
    body TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',             -- the #tags found in the body, space separated
    pinned INTEGER NOT NULL DEFAULT 0,
    daily TEXT,                                -- YYYY-MM-DD for a daily note
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_pages_key ON pages(title_key);
CREATE INDEX idx_pages_daily ON pages(daily);

CREATE TABLE page_links (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL,
    target TEXT NOT NULL,                      -- title_key of the page (or other thing) it points to
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_page_links_from ON page_links(from_id);
CREATE INDEX idx_page_links_target ON page_links(target);

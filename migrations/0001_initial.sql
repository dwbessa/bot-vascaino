-- Schema inicial — plan.md §5.
-- Todo TEXT com timestamp é ISO 8601 aware.

CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    window_start TEXT NOT NULL,
    window_end   TEXT NOT NULL,
    status       TEXT NOT NULL,           -- running|ok|partial|failed
    stats_json   TEXT
);

CREATE TABLE IF NOT EXISTS source_state (
    source_id      TEXT PRIMARY KEY,
    watermark_ts   TEXT,
    watermark_extid TEXT,
    last_ok_at     TEXT,
    last_error     TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id             TEXT PRIMARY KEY,      -- sha256(url_canonica)
    source_id      TEXT NOT NULL,
    external_id    TEXT,
    url            TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    summary        TEXT,
    body           TEXT,
    published_at   TEXT NOT NULL,
    fetched_at     TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    category       TEXT,
    confidence     REAL,
    classify_method TEXT,                 -- rule_exclusion|rule_positive|llm
    llm_model      TEXT,
    status         TEXT NOT NULL,         -- ok|pending_review
    cluster_id     TEXT,
    run_id         TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_articles_cat ON articles(category, published_at);
CREATE INDEX IF NOT EXISTS idx_articles_run ON articles(run_id);

CREATE TABLE IF NOT EXISTS clusters (
    id                    TEXT PRIMARY KEY,
    canonical_article_id  TEXT NOT NULL,
    category              TEXT NOT NULL,
    size                  INTEGER NOT NULL,
    run_id                TEXT NOT NULL,
    FOREIGN KEY (canonical_article_id) REFERENCES articles(id),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_clusters_run_cat ON clusters(run_id, category);

CREATE TABLE IF NOT EXISTS digests (
    id                TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL,
    category          TEXT NOT NULL,
    headline          TEXT NOT NULL,
    bullets_json      TEXT NOT NULL,
    source_urls_json  TEXT NOT NULL,
    llm_model         TEXT,
    UNIQUE(run_id, category),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS posts (
    id               TEXT PRIMARY KEY,
    digest_id        TEXT NOT NULL,
    platform         TEXT NOT NULL,       -- x|bluesky
    thread_index     INTEGER NOT NULL,
    text             TEXT NOT NULL,
    has_link         INTEGER NOT NULL,
    status           TEXT NOT NULL,       -- pending|approved|published|failed|skipped
    external_id      TEXT,
    cost_usd         REAL DEFAULT 0,
    published_at     TEXT,
    error            TEXT,
    idempotency_key  TEXT NOT NULL UNIQUE,
    FOREIGN KEY (digest_id) REFERENCES digests(id)
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);

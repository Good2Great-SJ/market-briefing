-- state.db (git에 커밋됨, 민감정보 없음)
CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    blog_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    raw_content TEXT,
    summary TEXT,
    keywords TEXT,
    status TEXT NOT NULL DEFAULT 'collected',
    collected_at TEXT NOT NULL,
    notified_at TEXT
);

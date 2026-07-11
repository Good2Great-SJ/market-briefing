-- kakao_tokens.db (항상 .gitignore 대상, 절대 커밋되지 않음)
CREATE TABLE IF NOT EXISTS kakao_tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

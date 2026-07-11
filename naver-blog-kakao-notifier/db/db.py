import os
import sqlite3
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "state.db")
# 카카오 토큰은 state.db와 별도 파일에 저장한다. state.db는 dedup 상태 유지를 위해
# git에 커밋되지만(민감정보 없음), kakao_tokens.db는 항상 .gitignore 대상이라
# 실 토큰이 git 히스토리에 남지 않는다.
TOKENS_DB_PATH = os.path.join(PROJECT_ROOT, "kakao_tokens.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
TOKENS_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema_tokens.sql")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_tokens_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(TOKENS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()

    tokens_conn = get_tokens_connection()
    try:
        with open(TOKENS_SCHEMA_PATH, encoding="utf-8") as f:
            tokens_conn.executescript(f.read())
        tokens_conn.commit()
    finally:
        tokens_conn.close()


def post_exists(post_id: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM posts WHERE post_id = ?", (post_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def insert_post(post: dict):
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO posts (post_id, blog_id, title, url, published_at, raw_content, status, collected_at)
            VALUES (:post_id, :blog_id, :title, :url, :published_at, :raw_content, :status, :collected_at)
            """,
            {
                "post_id": post["post_id"],
                "blog_id": post["blog_id"],
                "title": post["title"],
                "url": post["url"],
                "published_at": post.get("published_at"),
                "raw_content": post.get("raw_content"),
                "status": post.get("status", "collected"),
                "collected_at": post.get("collected_at", datetime.now(timezone.utc).isoformat()),
            },
        )
        conn.commit()
    finally:
        conn.close()


def get_posts_by_status(status: str) -> list:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM posts WHERE status = ?", (status,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_post_status(post_id: str, status: str, **fields):
    conn = get_connection()
    try:
        set_clauses = ["status = :status"]
        params = {"status": status, "post_id": post_id}
        for key, value in fields.items():
            set_clauses.append(f"{key} = :{key}")
            params[key] = value
        sql = f"UPDATE posts SET {', '.join(set_clauses)} WHERE post_id = :post_id"
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def save_kakao_tokens(access_token: str, refresh_token: str, expires_at: str):
    conn = get_tokens_connection()
    try:
        conn.execute(
            """
            INSERT INTO kakao_tokens (id, access_token, refresh_token, expires_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at
            """,
            (access_token, refresh_token, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_kakao_tokens():
    conn = get_tokens_connection()
    try:
        row = conn.execute(
            "SELECT access_token, refresh_token, expires_at FROM kakao_tokens WHERE id = 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

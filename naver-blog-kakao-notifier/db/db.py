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


_REQUIRED_CONSENSUS_COLUMNS = [
    ("fiscal_year_current", "TEXT"),
    ("revenue_estimate_current", "REAL"),
    ("operating_profit_estimate_current", "REAL"),
    ("fiscal_year_next", "TEXT"),
    ("revenue_estimate_next", "REAL"),
    ("operating_profit_estimate_next", "REAL"),
]


def _ensure_consensus_schema(conn: sqlite3.Connection):
    """외부 요인(개발 환경의 파일 스냅샷 복원 등)으로 테이블이 구버전 스키마로 되돌아간 경우,
    기존 데이터를 보존한 채 누락된 컬럼만 추가해 자동 복구한다."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(consensus_reports)").fetchall()}
    if not existing:
        return
    for col_name, col_type in _REQUIRED_CONSENSUS_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE consensus_reports ADD COLUMN {col_name} {col_type}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS consensus_snapshot_state (
            stock_code TEXT PRIMARY KEY,
            avg_target_price REAL,
            margin_current REAL,
            margin_next REAL,
            optimistic INTEGER,
            neutral INTEGER,
            pessimistic INTEGER,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_consensus_schema(conn)
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


def report_exists(nid: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM consensus_reports WHERE nid = ?", (nid,)).fetchone()
        return row is not None
    finally:
        conn.close()


def insert_consensus_report(report: dict):
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO consensus_reports (
                nid, stock_code, stock_name, broker, report_date, title,
                target_price, opinion_raw,
                fiscal_year_current, revenue_estimate_current, operating_profit_estimate_current,
                fiscal_year_next, revenue_estimate_next, operating_profit_estimate_next,
                estimate_unit, pdf_status, collected_at
            ) VALUES (
                :nid, :stock_code, :stock_name, :broker, :report_date, :title,
                :target_price, :opinion_raw,
                :fiscal_year_current, :revenue_estimate_current, :operating_profit_estimate_current,
                :fiscal_year_next, :revenue_estimate_next, :operating_profit_estimate_next,
                :estimate_unit, :pdf_status, :collected_at
            )
            """,
            report,
        )
        conn.commit()
    finally:
        conn.close()


def get_consensus_reports(stock_code: str, since_date: str | None = None) -> list:
    conn = get_connection()
    try:
        if since_date:
            rows = conn.execute(
                "SELECT * FROM consensus_reports WHERE stock_code = ? AND report_date >= ? ORDER BY report_date",
                (stock_code, since_date),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM consensus_reports WHERE stock_code = ? ORDER BY report_date", (stock_code,)
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_consensus_state(stock_code: str) -> dict:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM consensus_state WHERE stock_code = ?", (stock_code,)
        ).fetchall()
        return {row["broker"]: dict(row) for row in rows}
    finally:
        conn.close()


def upsert_consensus_state(
    stock_code: str, broker: str, target_price, opinion_raw: str, stance: str, report_date: str, nid: str
):
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO consensus_state (
                stock_code, broker, target_price, opinion_raw, stance, last_report_date, last_nid, updated_at
            ) VALUES (:stock_code, :broker, :target_price, :opinion_raw, :stance, :last_report_date, :last_nid, :updated_at)
            ON CONFLICT(stock_code, broker) DO UPDATE SET
                target_price = excluded.target_price,
                opinion_raw = excluded.opinion_raw,
                stance = excluded.stance,
                last_report_date = excluded.last_report_date,
                last_nid = excluded.last_nid,
                updated_at = excluded.updated_at
            """,
            {
                "stock_code": stock_code,
                "broker": broker,
                "target_price": target_price,
                "opinion_raw": opinion_raw,
                "stance": stance,
                "last_report_date": report_date,
                "last_nid": nid,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        conn.commit()
    finally:
        conn.close()


def is_watchlist_stock_bootstrapped(stock_code: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT bootstrapped_at FROM consensus_watchlist_state WHERE stock_code = ?", (stock_code,)
        ).fetchone()
        return bool(row and row["bootstrapped_at"])
    finally:
        conn.close()


def mark_watchlist_stock_bootstrapped(stock_code: str, stock_name: str):
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO consensus_watchlist_state (stock_code, stock_name, bootstrapped_at)
            VALUES (:stock_code, :stock_name, :bootstrapped_at)
            ON CONFLICT(stock_code) DO UPDATE SET
                stock_name = excluded.stock_name,
                bootstrapped_at = excluded.bootstrapped_at
            """,
            {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "bootstrapped_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        conn.commit()
    finally:
        conn.close()


def has_run_consensus_check_today() -> bool:
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        row = conn.execute("SELECT last_run_date FROM consensus_run_log WHERE id = 1").fetchone()
        return bool(row and row["last_run_date"] == today)
    finally:
        conn.close()


def mark_consensus_check_ran_today():
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO consensus_run_log (id, last_run_date) VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET last_run_date = excluded.last_run_date
            """,
            (today,),
        )
        conn.commit()
    finally:
        conn.close()


def get_consensus_snapshot(stock_code: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM consensus_snapshot_state WHERE stock_code = ?", (stock_code,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_consensus_snapshot(stock_code: str, snapshot: dict):
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO consensus_snapshot_state (
                stock_code, avg_target_price, margin_current, margin_next,
                optimistic, neutral, pessimistic, updated_at
            ) VALUES (
                :stock_code, :avg_target_price, :margin_current, :margin_next,
                :optimistic, :neutral, :pessimistic, :updated_at
            )
            ON CONFLICT(stock_code) DO UPDATE SET
                avg_target_price = excluded.avg_target_price,
                margin_current = excluded.margin_current,
                margin_next = excluded.margin_next,
                optimistic = excluded.optimistic,
                neutral = excluded.neutral,
                pessimistic = excluded.pessimistic,
                updated_at = excluded.updated_at
            """,
            {
                "stock_code": stock_code,
                "avg_target_price": snapshot.get("avg_target_price"),
                "margin_current": snapshot.get("margin_current"),
                "margin_next": snapshot.get("margin_next"),
                "optimistic": snapshot.get("optimistic"),
                "neutral": snapshot.get("neutral"),
                "pessimistic": snapshot.get("pessimistic"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
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
